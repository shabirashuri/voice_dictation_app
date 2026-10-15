from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Generous per-field cap; protects the API from runaway payloads.
MAX_FIELD_LENGTH = 20_000

REPORT_FIELDS = (
    "patient",
    "specimen",
    "gross_description",
    "microscopic_description",
    "diagnosis",
    "comments",
)


class ReportFields(BaseModel):
    """The six report fields as reviewed and approved by the clinician."""

    patient: str = Field("", max_length=MAX_FIELD_LENGTH)
    specimen: str = Field("", max_length=MAX_FIELD_LENGTH)
    gross_description: str = Field("", max_length=MAX_FIELD_LENGTH)
    microscopic_description: str = Field("", max_length=MAX_FIELD_LENGTH)
    diagnosis: str = Field("", max_length=MAX_FIELD_LENGTH)
    comments: str = Field("", max_length=MAX_FIELD_LENGTH)

    @field_validator(*REPORT_FIELDS, mode="before")
    @classmethod
    def _strip(cls, value):
        return (value or "").strip() if isinstance(value, str) or value is None else value


class ReportCreate(BaseModel):
    """Body of POST /cases/{case_id}/report: the clinician-approved report."""

    session_id: Optional[str] = Field(None, max_length=128)
    report: ReportFields
    comment_source: Optional[Literal["doctor", "ai"]] = None

    @model_validator(mode="after")
    def _check_comment_and_content(self):
        if not any(getattr(self.report, name) for name in REPORT_FIELDS):
            raise ValueError("report is empty")
        if self.report.comments and self.comment_source is None:
            # Comment provenance must never be ambiguous.
            raise ValueError("comment_source is required when comments are present")
        if not self.report.comments:
            self.comment_source = None
        return self


class ReportOut(BaseModel):
    id: int
    case_id: int
    case_number: Optional[str] = None
    session_id: Optional[str] = None
    patient: str = ""
    specimen: str = ""
    gross_description: str = ""
    microscopic_description: str = ""
    diagnosis: str = ""
    comments: str = ""
    comment_source: Optional[Literal["doctor", "ai"]] = None
    status: Literal["draft", "approved"]
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row) -> "ReportOut":
        return cls(
            id=row.id,
            case_id=row.case_id,
            case_number=row.case.case_number if row.case else None,
            session_id=row.session_id,
            **{name: getattr(row, name) or "" for name in REPORT_FIELDS},
            comment_source=row.comment_source,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            approved_at=row.approved_at,
        )
