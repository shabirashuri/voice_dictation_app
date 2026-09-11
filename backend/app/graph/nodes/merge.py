from __future__ import annotations

from typing import List
from app.graph.state import LangGraphState, FieldUpdate


async def merge_chunk_node(state: LangGraphState) -> dict:
    """Node: merge only the updates present in the most recent extracted chunk.

    - Reads `state.extracted_data` (uses the last element if present).
    - Applies only those `FieldUpdate` items to `state.report`.
    - Preserves unrelated fields.
    - Does not call any LLM.
    Returns a dict with `updated_fields` (list of FieldUpdate).
    """
    if not isinstance(state, LangGraphState):
        raise TypeError("state must be a LangGraphState")

    if not state.extracted_data:
        state.updated_fields = []
        return {"updated_fields": []}

    last = state.extracted_data[-1]
    updates: List[FieldUpdate] = last.updates or []
    state.updated_fields = []
    if not updates:
        state.previous_chunk = last.chunk_text
        # still may have a comment extracted (doctor comment)
        if getattr(last, "comment", None):
            # apply doctor comment text and mark source
            c = last.comment
            if c and getattr(c, "text", None):
                changed = state.report.comments != c.text
                state.report.comments = c.text
                state.report.comment_source = c.source or "doctor"
                state.updated_fields = [
                    FieldUpdate(target_section="comments", operation="replace", content=c.text)
                ] if changed else []
                state.previous_chunk = last.chunk_text
                state.active_field = "comments" if changed else state.active_field
                return {"updated_fields": state.updated_fields}
        return {"updated_fields": []}

    # Apply updates to the single source-of-truth report via state.apply_updates
    state.apply_updates(updates)

    # Context follows the most recent successful field assignment. A comments
    # update is doctor-provided because AI comments are generated only at stop.
    state.previous_chunk = last.chunk_text
    if state.updated_fields:
        state.active_field = state.updated_fields[-1].target_section
        if any(update.target_section == "comments" for update in state.updated_fields):
            state.report.comment_source = "doctor"

    # If the extracted chunk included an explicit comment object, treat it as doctor-provided
    if getattr(last, "comment", None):
        c = last.comment
        if c and getattr(c, "text", None):
            # ensure report.comments contains the comment text (apply_updates may have done this)
            state.report.comments = c.text
            try:
                state.report.comment_source = c.source or "doctor"
            except Exception:
                state.report.comment_source = "doctor"

    return {"updated_fields": state.updated_fields}
