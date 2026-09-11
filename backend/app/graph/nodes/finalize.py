from __future__ import annotations

from app.graph.state import ReportState


async def finalize_report(state: ReportState, doctor_provided_comment: bool = False) -> dict:
    """Prepare final report metadata.

    Returns a dict with keys:
      - report: the ReportState dict
      - comment_source: 'doctor'|'ai'
      - needs_ai_comment: bool
    """
    if not isinstance(state, ReportState):
        raise TypeError("state must be a ReportState")

    has_comment = bool((state.comments or "").strip())
    if has_comment:
        source = "doctor" if doctor_provided_comment else (state.comment_source or "doctor")
        needs_ai = False
    else:
        source = "ai"
        needs_ai = True

    return {"report": state.dict(), "comment_source": source, "needs_ai_comment": needs_ai}
