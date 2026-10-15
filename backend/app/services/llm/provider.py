import json
import logging
import os
import asyncio
from typing import Any, Dict, Optional

import httpx

from app.graph.state import ExtractionResponse
from app.prompts.extraction import EXTRACTION_SYSTEM_PROMPT, REPAIR_NOTE_TEMPLATE
from .base import LLMBase


logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Base error for failures talking to or parsing the LLM provider."""


class LLMAPIError(LLMProviderError):
    """The provider rejected the request or returned an unsuccessful response."""


class LLMRateLimitError(LLMAPIError):
    """The provider throttled the request or the account has exhausted quota."""


class LLMResponseError(LLMProviderError):
    """The provider returned content that was not valid extraction JSON."""


EXTRACTION_FIELDS = (
    "patient",
    "specimen",
    "gross_description",
    "microscopic_description",
    "diagnosis",
    "comments",
)



class DummyLLM(LLMBase):
    async def extract(self, prompt: str, **kwargs):
        # Return placeholder structured update
        return {"updates": []}

    async def generate(self, prompt: str, **kwargs):
        return "AI-generated comment"


class GroqLLM(LLMBase):
    """Async Groq client for the OpenAI-compatible chat endpoint."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        configured_base = base_url or os.getenv("GROQ_API_BASE", "https://api.groq.com/openai")
        self.base_url = configured_base.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3].rstrip("/")
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.max_retries = max(0, int(os.getenv("GROQ_MAX_RETRIES", "0")))
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")

    async def _chat_request(
        self,
        messages: list,
        temperature: float = 0.0,
        max_tokens: int = 512,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for attempt in range(self.max_retries + 1):
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code != 429:
                        break

                    retry_after = resp.headers.get("Retry-After")
                    try:
                        delay = min(float(retry_after), 5.0) if retry_after else min(2**attempt, 5.0)
                    except ValueError:
                        delay = min(2**attempt, 5.0)

                    if attempt < self.max_retries:
                        logger.warning(
                            "LLM provider rate limited request; retrying in %.1f seconds (attempt %d/%d)",
                            delay,
                            attempt + 1,
                            self.max_retries,
                        )
                        await asyncio.sleep(delay)
                    else:
                        detail = ""
                        try:
                            body = resp.json()
                            if isinstance(body, dict):
                                detail = str(body.get("error", {}).get("message", ""))
                        except ValueError:
                            pass
                        message = "LLM provider rate limit or quota exceeded"
                        if detail:
                            message = f"{message}: {detail}"
                        logger.warning("%s", message)
                        raise LLMRateLimitError(message)

                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException as exc:
            logger.exception("LLM request timed out")
            raise LLMAPIError("LLM request timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            error_code = ""
            try:
                body = exc.response.json()
                error = body.get("error", {}) if isinstance(body, dict) else {}
                if isinstance(error, dict):
                    detail = str(error.get("message", ""))
                    error_code = str(error.get("code", ""))
            except ValueError:
                detail = exc.response.text[:500]

            suffix = f": {detail}" if detail else ""
            if error_code:
                suffix = f" ({error_code}){suffix}"
            logger.warning(
                "LLM request failed with HTTP status %s%s",
                exc.response.status_code,
                suffix,
            )
            raise LLMAPIError(
                f"LLM request failed with HTTP status {exc.response.status_code}{suffix}"
            ) from exc
        except httpx.RequestError as exc:
            logger.exception("LLM request failed")
            raise LLMAPIError("LLM request failed") from exc
        except ValueError as exc:
            logger.exception("LLM returned invalid JSON at the HTTP response level")
            raise LLMResponseError("LLM returned invalid HTTP response JSON") from exc

    @staticmethod
    def _json_content(content: Any) -> Any:
        if isinstance(content, (dict, list)):
            return content
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM response did not contain JSON content")

        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1]).strip()

        decoder = json.JSONDecoder()
        try:
            return decoder.raw_decode(text)[0]
        except json.JSONDecodeError:
            # Some compatible endpoints add a short preamble. Find JSON
            # boundaries with the decoder rather than a greedy regex.
            for index, character in enumerate(text):
                if character != "{":
                    continue
                try:
                    return decoder.raw_decode(text[index:])[0]
                except json.JSONDecodeError:
                    continue
            logger.exception("LLM returned invalid extraction JSON")
            raise LLMResponseError("LLM returned invalid JSON")

    @staticmethod
    def _response_content(response: Dict[str, Any]) -> Any:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response did not contain assistant content") from exc

    async def extract(self, prompt: str, **kwargs):
        """Extract explicitly dictated incremental updates from one transcript chunk."""
        chunk = kwargs.get("chunk", "")
        report_state = kwargs.get("report_state", {}) or {}
        detected = kwargs.get("detected_fields", []) or []
        previous_chunk = kwargs.get("previous_chunk", "") or ""
        active_field = kwargs.get("active_field") or "none"
        recent_context = kwargs.get("recent_context") or []
        validation_errors = kwargs.get("validation_errors") or []
        state_text = "\n".join(f"{field}: {report_state.get(field, '')}" for field in EXTRACTION_FIELDS)
        recent_text = "\n".join(recent_context) or "[none]"
        repair_note = (
            REPAIR_NOTE_TEMPLATE.format(errors="\n".join(validation_errors)) + "\n"
            if validation_errors
            else ""
        )
        user_content = f"""{prompt}

{repair_note}CURRENT REPORT STATE:
{state_text}

CURRENT/PREVIOUS CONTEXT:
Previous chunk: {previous_chunk or '[none]'}
Recent chunks: {recent_text}
Active field: {active_field}

CURRENT TRANSCRIPT CHUNK:
{chunk}

DETECTED FIELDS AS HINTS:
{json.dumps(detected)}

OUTPUT SCHEMA:
{{"updates": [{{"target_section": "patient|specimen|gross_description|microscopic_description|diagnosis|comments", "operation": "append|replace", "content": "string"}}]}}"""
        user = {"role": "user", "content": user_content}

        try:
            res = await self._chat_request(
                [{"role": "system", "content": EXTRACTION_SYSTEM_PROMPT}, user],
                temperature=0.0,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            parsed = self._json_content(self._response_content(res))
            if hasattr(ExtractionResponse, "model_validate"):
                validated = ExtractionResponse.model_validate(parsed)
            else:
                validated = ExtractionResponse.parse_obj(parsed)
        except LLMProviderError:
            raise
        except Exception as exc:
            logger.exception("LLM extraction schema validation failed")
            raise LLMResponseError("LLM extraction response failed schema validation") from exc

        if not validated.updates:
            logger.info("LLM extraction returned an empty update list")
        if hasattr(validated, "model_dump"):
            return validated.model_dump()
        return validated.dict()

    async def generate(self, prompt: str, **kwargs):
        system = {"role": "system", "content": "You are a helpful assistant."}
        user = {"role": "user", "content": prompt}
        res = await self._chat_request([system, user], temperature=0.6, max_tokens=512)
        try:
            choices = res.get("choices", [])
            if not choices:
                return ""
            assistant = choices[0].get("message", {}).get("content", "")
            return assistant
        except Exception:
            return ""


def build_default_llm() -> LLMBase:
    """Build the single configured Groq provider."""
    return GroqLLM() if os.getenv("GROQ_API_KEY") else DummyLLM()
