from __future__ import annotations

from app.graph.state import LangGraphState

# One repair attempt after the first failed validation, then reject the chunk.
MAX_REPAIR_ATTEMPTS = 1
# Cleaned chunks kept as short-term context for the LLM.
RECENT_CONTEXT_SIZE = 5


def route_after_clean(state: LangGraphState) -> str:
    """Skip empty chunks and exact repeats of the previous chunk."""
    cleaned = state.cleaned_chunk or ""
    if not cleaned or cleaned == (state.previous_chunk or ""):
        return "skip"
    return "classify"


def route_after_validate(state: LangGraphState) -> str:
    if not state.validation_errors:
        return "merge"
    if state.retry_count < MAX_REPAIR_ATTEMPTS:
        return "repair"
    return "reject"


def route_after_final_validate(state: LangGraphState) -> str:
    """Comment decision: keep an existing comment, otherwise generate one."""
    if state.validation_errors:
        return "invalid"
    if (state.report.comments or "").strip():
        return "keep_comment"
    return "generate_comment"
