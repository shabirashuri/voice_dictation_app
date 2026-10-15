import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.repositories import case as cases
from app.repositories import report as reports
from app.schemas.case import CaseCreate, CaseDetail, CaseList, CaseOut
from app.schemas.report import ReportCreate, ReportOut

router = APIRouter(prefix="/cases", tags=["cases"])
logger = logging.getLogger(__name__)

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
_DB_DOWN = "The database is unavailable; the report was not saved. Please retry."


async def _own_case(db: AsyncSession, user: User, case_id: int):
    case = await cases.get_case(db, user.id, case_id)
    if case is None:
        # Other doctors' cases are indistinguishable from missing ones.
        raise _NOT_FOUND
    return case


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(body: CaseCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return CaseOut.from_row(await cases.create_case(db, user.id, body))


@router.get("", response_model=CaseList)
async def list_cases(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await cases.list_cases(db, user.id, limit=limit, offset=offset)
    return CaseList(cases=[CaseOut.from_row(r) for r in rows], total=total)


@router.get("/{case_id}", response_model=CaseDetail)
async def get_case(case_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return CaseDetail.from_row(await _own_case(db, user, case_id))


@router.get("/{case_id}/report", response_model=ReportOut)
async def get_case_report(case_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    case = await _own_case(db, user, case_id)
    if case.report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This case has no report yet")
    return ReportOut.from_row(case.report)


@router.post("/{case_id}/report", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def save_case_report(
    case_id: int,
    body: ReportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the clinician-approved report for this case (one per case)."""
    case = await _own_case(db, user, case_id)
    try:
        row = await reports.create_approved_report(db, case, body)
    except reports.CaseAlreadyReportedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This case already has an approved report (#{exc.report_id}).",
        )
    except reports.DuplicateSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This dictation was already saved as report #{exc.report_id}.",
        )
    except (OperationalError, InterfaceError, OSError):
        logger.exception("failed to save report")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_DB_DOWN)
    return ReportOut.from_row(row)
