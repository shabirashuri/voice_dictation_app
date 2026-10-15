from __future__ import annotations

from app.graph.state import LangGraphState
from app.services.llm.provider import LLMResponseError

EXTRACTION_HINT = (
    "Apply the extraction rules to the current transcript. "
    "Preserve the doctor's wording in update content."
)


async def extract_chunk_node(state: LangGraphState, llm=None) -> dict:
    """Node: ask the LLM for raw (unvalidated) updates for `state.cleaned_chunk`.

    Returns only the raw LLM output. Pydantic validation happens in the
    `validate_update` node, so a bad response can be repaired or rejected.
    Schema failures raised by the provider are captured as validation errors.
    """
    cleaned = state.cleaned_chunk or ""
    if not cleaned:
        return {"raw_updates": [], "raw_comment": None, "validation_errors": []}

    if llm is None:
        from app.services.llm.provider import build_default_llm

        llm = build_default_llm()

    report = state.report
    report_state = report.model_dump() if hasattr(report, "model_dump") else report.dict()

    try:
        resp = await llm.extract(
            prompt=EXTRACTION_HINT,
            chunk=cleaned,
            report_state=report_state,
            detected_fields=state.detected_fields,
            previous_chunk=state.previous_chunk or "",
            active_field=state.active_field,
            recent_context=state.recent_context,
            validation_errors=state.validation_errors,
        )
    except LLMResponseError as exc:
        return {"raw_updates": [], "raw_comment": None, "validation_errors": [str(exc)]}

    if not isinstance(resp, dict):
        return {
            "raw_updates": [],
            "raw_comment": None,
            "validation_errors": ["LLM extraction response must be a dictionary"],
        }

    return {
        "raw_updates": list(resp.get("updates") or []),
        "raw_comment": resp.get("comment") or None,
        "validation_errors": [],
    }
