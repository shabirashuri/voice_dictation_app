import json

import httpx
import pytest

from app.services.llm.provider import (
    GroqLLM,
    LLMAPIError,
    LLMRateLimitError,
    LLMResponseError,
)


@pytest.mark.asyncio
async def test_extract_sends_full_context_and_validates_response(monkeypatch):
    llm = GroqLLM(api_key="test-key", base_url="https://example.test/v1")
    captured = {}

    async def fake_request(messages, temperature, max_tokens, response_format):
        captured.update(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "updates": [
                                    {
                                        "target_section": "microscopic_description",
                                        "operation": "append",
                                        "content": "mild foveolar hyperplasia",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(llm, "_chat_request", fake_request)
    result = await llm.extract(
        prompt="Apply the extraction rules.",
        chunk="and mild foveolar hyperplasia.",
        report_state={
            "patient": "",
            "specimen": "gastric biopsy",
            "gross_description": "",
            "microscopic_description": "gastric mucosa with chronic inflammation",
            "diagnosis": "",
            "comments": "",
        },
        detected_fields=[],
        previous_chunk="gastric mucosa with chronic inflammation",
        active_field="microscopic_description",
    )

    assert result["updates"][0]["target_section"] == "microscopic_description"
    assert llm.base_url == "https://example.test"
    assert captured["temperature"] == 0.0
    assert captured["response_format"]["type"] == "json_schema"
    schema = captured["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["updates"]["items"]["properties"]["target_section"]["enum"][0] == "patient"
    user_message = captured["messages"][1]["content"]
    assert "CURRENT REPORT STATE" in user_message
    assert "CURRENT TRANSCRIPT CHUNK" in user_message
    assert "previous_chunk" not in user_message
    assert "gastric mucosa with chronic inflammation" in user_message
    assert "mild foveolar hyperplasia" in user_message


@pytest.mark.asyncio
async def test_extract_accepts_fenced_json(monkeypatch):
    llm = GroqLLM(api_key="test-key")

    async def fake_request(*args, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"updates": []}\n```',
                    }
                }
            ]
        }

    monkeypatch.setattr(llm, "_chat_request", fake_request)
    assert await llm.extract(prompt="", chunk="unrelated noise") == {"updates": []}


@pytest.mark.asyncio
async def test_extract_raises_for_invalid_model_response(monkeypatch):
    llm = GroqLLM(api_key="test-key")

    async def fake_request(*args, **kwargs):
        return {"choices": [{"message": {"content": "not json"}}]}

    monkeypatch.setattr(llm, "_chat_request", fake_request)
    with pytest.raises(LLMResponseError):
        await llm.extract(prompt="", chunk="patient information")


@pytest.mark.asyncio
async def test_extract_does_not_hide_api_failures(monkeypatch):
    llm = GroqLLM(api_key="test-key")

    async def fake_request(*args, **kwargs):
        raise LLMAPIError("provider unavailable")

    monkeypatch.setattr(llm, "_chat_request", fake_request)
    with pytest.raises(LLMAPIError, match="provider unavailable"):
        await llm.extract(prompt="", chunk="patient information")


@pytest.mark.asyncio
async def test_chat_request_normalizes_v1_without_duplication(monkeypatch):
    llm = GroqLLM(api_key="test-key", base_url="https://example.test/v1/")
    requested = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": []}

    async def fake_post(self, url, headers, json):
        requested["url"] = url
        return Response()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        post = fake_post

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: Client())
    await llm._chat_request([])
    assert requested["url"] == "https://example.test/v1/chat/completions"


def test_groq_uses_active_default_model(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    llm = GroqLLM(api_key="test-key")
    assert llm.model == "openai/gpt-oss-20b"


@pytest.mark.asyncio
async def test_chat_request_reports_rate_limit_without_retry(monkeypatch):
    llm = GroqLLM(api_key="test-key")
    llm.max_retries = 0

    class Response:
        status_code = 429
        headers = {"Retry-After": "60"}

        def json(self):
            return {"error": {"message": "quota exceeded"}}

        def raise_for_status(self):
            raise AssertionError("429 should be handled before raise_for_status")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: Client())
    with pytest.raises(LLMRateLimitError, match="quota exceeded"):
        await llm._chat_request([])


@pytest.mark.asyncio
async def test_chat_request_preserves_http_error_details(monkeypatch):
    llm = GroqLLM(api_key="test-key")

    class Response:
        status_code = 400
        text = "bad request"

        def json(self):
            return {"error": {"message": "invalid model setting", "code": "bad_request"}}

        def raise_for_status(self):
            request = httpx.Request("POST", "https://example.test")
            raise httpx.HTTPStatusError("bad request", request=request, response=self)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: Client())
    with pytest.raises(LLMAPIError, match="invalid model setting"):
        await llm._chat_request([])




def test_json_object_mode_can_be_selected(monkeypatch):
    monkeypatch.setenv("GROQ_RESPONSE_FORMAT", "json_object")
    assert GroqLLM(api_key="k").response_format == {"type": "json_object"}
