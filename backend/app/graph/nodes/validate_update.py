from __future__ import annotations

from pydantic import ValidationError

from app.graph.grounding import check_dropped_negation, check_grounding
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

    # Grounding: model output must only state what was dictated (see grounding.py).
    # Checked only when the model produced something; a chunk with no report content
    # (e.g. chit-chat containing "no") is not an error.
    source = state.cleaned_chunk or ""
    for update in updates:
        context = source
        if update.operation == "replace":
            # A replace restates the whole field, so the field's existing text is grounded too.
            context = f"{source} {getattr(state.report, update.target_section, '') or ''}"
        errors += check_grounding(context, update.content, label=update.target_section)
    if comment is not None:
        errors += check_grounding(source, comment.text, label="comment")
    contents = [update.content for update in updates] + ([comment.text] if comment else [])
    if updates:
        errors += check_dropped_negation(source, contents)

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
