from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
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


async def _get_or_create_case(db: AsyncSession, case_number: str) -> Case:
    case = await db.scalar(select(Case).where(Case.case_number == case_number))
    if case is None:
        case = Case(case_number=case_number)
        db.add(case)
        await db.flush()
    return case


async def _report_id_for_session(db: AsyncSession, session_id: str) -> Optional[int]:
    return await db.scalar(select(Report.id).where(Report.session_id == session_id))


async def create_approved_report(db: AsyncSession, data: ReportCreate) -> Report:
    """Insert a clinician-approved report. One report per dictation session."""
    if data.session_id:
        existing = await _report_id_for_session(db, data.session_id)
        if existing is not None:
            raise DuplicateSessionError(existing)

    case = await _get_or_create_case(db, data.case_number) if data.case_number else None
    now = datetime.now(timezone.utc)
    report = Report(
        case=case,
        session_id=data.session_id,
        **{name: getattr(data.report, name) for name in REPORT_FIELDS},
        comment_source=data.comment_source,
        status="approved",
        approved_at=now,
    )
    db.add(report)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent save of the same session.
        await db.rollback()
        if data.session_id:
            raise DuplicateSessionError(await _report_id_for_session(db, data.session_id))
        raise
    return await get_report(db, report.id)


async def get_report(db: AsyncSession, report_id: int) -> Optional[Report]:
    return await db.scalar(
        select(Report)
        .options(selectinload(Report.case))
        .where(Report.id == report_id)
        .execution_options(populate_existing=True)
    )


async def list_reports(db: AsyncSession, limit: int = 50, offset: int = 0) -> tuple[list[Report], int]:
    total = await db.scalar(select(func.count()).select_from(Report))
    rows = await db.scalars(
        select(Report)
        .options(selectinload(Report.case))
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0
