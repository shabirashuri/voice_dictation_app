import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories import report as repo
from app.schemas.report import ReportCreate, ReportList, ReportOut

router = APIRouter(prefix="/reports", tags=["reports"])
logger = logging.getLogger(__name__)

_DB_DOWN = "The database is unavailable; the report was not saved. Please retry."


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(body: ReportCreate, db: AsyncSession = Depends(get_db)):
    """Save a clinician-approved report (one per dictation session)."""
    try:
        row = await repo.create_approved_report(db, body)
    except repo.DuplicateSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This dictation was already saved as report #{exc.report_id}.",
        )
    except (OperationalError, InterfaceError, OSError):
        logger.exception("failed to save report")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_DB_DOWN)
    return ReportOut.from_row(row)


@router.get("", response_model=ReportList)
async def list_reports(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await repo.list_reports(db, limit=limit, offset=offset)
    return ReportList(reports=[ReportOut.from_row(r) for r in rows], total=total)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: int, db: AsyncSession = Depends(get_db)):
    row = await repo.get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return ReportOut.from_row(row)
