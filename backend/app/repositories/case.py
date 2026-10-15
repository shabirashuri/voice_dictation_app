from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.report import Case
from app.schemas.case import CaseCreate


async def create_case(db: AsyncSession, owner_id: int, data: CaseCreate) -> Case:
    """Create a case; its number is derived from the row id: C-<year>-<id:05d>."""
    case = Case(
        case_number=f"pending-{uuid.uuid4()}",
        owner_id=owner_id,
        patient_name=data.patient_name,
        patient_mrn=data.patient_mrn,
    )
    db.add(case)
    await db.flush()
    case.case_number = f"C-{datetime.now(timezone.utc).year}-{case.id:05d}"
    await db.commit()
    return await get_case(db, owner_id, case.id)


async def get_case(db: AsyncSession, owner_id: int, case_id: int) -> Optional[Case]:
    """A case only if it belongs to `owner_id` (others are treated as missing)."""
    return await db.scalar(
        select(Case)
        # report.case resolves from the identity map; don't eager-load it back,
        # populate_existing would then reset Case.report.
        .options(selectinload(Case.report))
        .where(Case.id == case_id, Case.owner_id == owner_id)
        .execution_options(populate_existing=True)
    )


async def list_cases(db: AsyncSession, owner_id: int, limit: int = 100, offset: int = 0) -> tuple[list[Case], int]:
    total = await db.scalar(select(func.count()).select_from(Case).where(Case.owner_id == owner_id))
    rows = await db.scalars(
        select(Case)
        .options(selectinload(Case.report))
        .where(Case.owner_id == owner_id)
        .order_by(Case.created_at.desc(), Case.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0
