from __future__ import annotations

from pydantic import ValidationError

from app.graph.state import Comment, ExtractedChunk, FieldUpdate, LangGraphState


def _summarize(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or 'value'}: {err['msg']}"
            for err in exc.errors()
        )
    return str(exc)


def validate_update_node(state: LangGraphState) -> dict:
    """Node: validate raw LLM output with Pydantic before anything is merged.

    On success, appends an `ExtractedChunk` to `extracted_data`. On failure,
    returns `validation_errors` and leaves `extracted_data` untouched so the
    router can send the chunk to repair or reject.
    """
    # Errors already recorded by extract (e.g. provider schema failure) carry over.
    errors: list[str] = list(state.validation_errors)
    updates: list[FieldUpdate] = []

    for raw in state.raw_updates:
        try:
            updates.append(FieldUpdate(**raw))
        except (ValidationError, TypeError) as exc:
            errors.append(f"invalid update {raw!r}: {_summarize(exc)}")

    comment = None
    if state.raw_comment:
        try:
            comment = Comment(**state.raw_comment)
        except (ValidationError, TypeError) as exc:
            errors.append(f"invalid comment: {_summarize(exc)}")

    if errors:
        return {"validation_errors": errors}

    extracted = ExtractedChunk(
        chunk_text=state.cleaned_chunk or "",
        updates=updates,
        comment=comment,
    )
    return {
        "validation_errors": [],
        "extracted_data": [*state.extracted_data, extracted],
    }
