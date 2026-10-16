from __future__ import annotations

import logging

from pydantic import ValidationError

from app.graph.state import LangGraphState, Report

logger = logging.getLogger(__name__)


def final_validate_node(state: LangGraphState) -> dict:
    """Node: re-validate the complete report before the comment decision."""
    try:
        Report.model_validate(state.report.model_dump())
    except ValidationError as exc:
        # str(exc) echoes the report text; log locations only.
        locations = sorted({".".join(str(part) for part in err["loc"]) for err in exc.errors()})
        logger.warning("final report validation failed in: %s", ", ".join(locations))
        return {
            "validation_errors": [f"invalid field: {location}" for location in locations],
            "error_code": "finalize",
            "error_message": "The final report failed validation.",
        }
    return {"validation_errors": [], "error_code": None, "error_message": None}


def keep_comment_node(state: LangGraphState) -> dict:
    """Node: a comment already exists. Keep it; an AI comment from an earlier
    finalize stays `ai`, anything else is clinician-authored."""
    report = state.report.model_copy()
    report.comment_source = report.comment_source or "doctor"
    return {"report": report}


def mark_review_node(state: LangGraphState) -> dict:
    """Node: dictation is over; the report now waits for clinician review."""
    return {"is_finished": True, "awaiting_review": True}
