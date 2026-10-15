from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.report import ReportOut


class CaseCreate(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=200)
    patient_mrn: Optional[str] = Field(None, max_length=64)

    @field_validator("patient_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("patient_name is required")
        return value

    @field_validator("patient_mrn")
    @classmethod
    def _strip_mrn(cls, value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None


class CaseOut(BaseModel):
    id: int
    case_number: str
    patient_name: str
    patient_mrn: Optional[str] = None
    created_at: datetime
    # "open" until the case's report is approved, then "reported"
    status: str
    report_id: Optional[int] = None

    @classmethod
    def from_row(cls, row) -> "CaseOut":
        return cls(
            id=row.id,
            case_number=row.case_number,
            patient_name=row.patient_name,
            patient_mrn=row.patient_mrn,
            created_at=row.created_at,
            status="reported" if row.report else "open",
            report_id=row.report.id if row.report else None,
        )


class CaseDetail(CaseOut):
    report: Optional[ReportOut] = None

    @classmethod
    def from_row(cls, row) -> "CaseDetail":
        base = CaseOut.from_row(row).model_dump()
        return cls(**base, report=ReportOut.from_row(row.report) if row.report else None)


class CaseList(BaseModel):
    cases: List[CaseOut]
    total: int
