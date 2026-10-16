from __future__ import annotations

import logging

from app.graph.state import LangGraphState

logger = logging.getLogger(__name__)

REJECT_MESSAGE = "The model output for this chunk could not be validated. The report was not changed."


def repair_node(state: LangGraphState) -> dict:
    """Node: count a repair attempt. The extract node then re-asks the LLM
    with `validation_errors` included as feedback."""
    return {"retry_count": state.retry_count + 1}


def reject_node(state: LangGraphState) -> dict:
    """Node: give up on this chunk. The report and `previous_chunk` are untouched."""
    # Error text can quote dictated values, so only the count is logged.
    logger.warning("rejecting chunk after %d validation failure(s)", len(state.validation_errors))
    return {
        "error_code": "validation",
        "error_message": REJECT_MESSAGE,
        "updated_fields": [],
    }
