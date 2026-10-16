from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.report import Case, Report
from app.schemas.report import REPORT_FIELDS, ReportCreate


class DuplicateSessionError(Exception):
    """The dictation session's report was already saved."""

    def __init__(self, report_id: Optional[int]):
        super().__init__(f"session already saved as report {report_id}")
        self.report_id = report_id


class CaseAlreadyReportedError(Exception):
    """The case already has its (single) approved report."""

    def __init__(self, report_id: Optional[int]):
        super().__init__(f"case already has report {report_id}")
        self.report_id = report_id


async def _report_id_where(db: AsyncSession, clause) -> Optional[int]:
    return await db.scalar(select(Report.id).where(clause))


async def create_approved_report(db: AsyncSession, case: Case, data: ReportCreate) -> Report:
    """Insert the clinician-approved report for `case` (one per case, one per session)."""
    existing = await _report_id_where(db, Report.case_id == case.id)
    if existing is not None:
        raise CaseAlreadyReportedError(existing)
    if data.session_id:
        existing = await _report_id_where(db, Report.session_id == data.session_id)
        if existing is not None:
            raise DuplicateSessionError(existing)

    report = Report(
        case_id=case.id,
        session_id=data.session_id,
        **{name: getattr(data.report, name) for name in REPORT_FIELDS},
        comment_source=data.comment_source,
        transcript=[line.model_dump() for line in data.transcript] if data.transcript is not None else None,
        status="approved",
        approved_at=datetime.now(timezone.utc),
    )
    db.add(report)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent save; report which rule was hit.
        await db.rollback()
        existing = await _report_id_where(db, Report.case_id == case.id)
        if existing is not None:
            raise CaseAlreadyReportedError(existing)
        if data.session_id:
            raise DuplicateSessionError(await _report_id_where(db, Report.session_id == data.session_id))
        raise
    return await get_report(db, report.id)


async def get_report(db: AsyncSession, report_id: int) -> Optional[Report]:
    return await db.scalar(
        select(Report)
        .options(selectinload(Report.case))
        .where(Report.id == report_id)
        .execution_options(populate_existing=True)
    )
