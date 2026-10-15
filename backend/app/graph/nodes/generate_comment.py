from __future__ import annotations

import logging

from app.graph.state import LangGraphState
from app.prompts.comment import build_comment_prompt
from app.services.llm.provider import LLMRateLimitError

logger = logging.getLogger(__name__)


async def generate_comment_node(state: LangGraphState, llm=None) -> dict:
    """Node: generate the one-time AI comment from the final validated report.

    Runs only when the clinician dictated no comment. The result is marked
    `ai` and must be reviewed. A failure leaves comments empty and reports a
    recoverable error; the report is still finalized.
    """
    if llm is None:
        from app.services.llm.provider import build_default_llm

        llm = build_default_llm()

    report = state.report.model_copy()
    try:
        text = await llm.generate(prompt=build_comment_prompt(report.model_dump()))
        if isinstance(text, dict):
            # some providers may return a structured response
            text = text.get("text") or text.get("content") or ""
        text = (text or "").strip()
    except LLMRateLimitError:
        logger.warning("LLM rate limit prevented AI comment generation")
        return {
            "error_code": "llm_rate_limit",
            "error_message": "AI comment could not be generated (rate limited). Add a comment manually or retry.",
        }
    except Exception:
        logger.exception("AI comment generation failed")
        return {
            "error_code": "finalize",
            "error_message": "AI comment could not be generated. Add a comment manually or retry.",
        }

    if not text:
        return {}
    report.comments = text
    report.comment_source = "ai"
    return {"report": report}
