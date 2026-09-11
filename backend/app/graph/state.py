from typing import List, Literal, Optional
from pydantic import BaseModel, Field, validator


# Core Report: single source of truth for the six required fields
class Report(BaseModel):
    patient: str = ""
    specimen: str = ""
    gross_description: str = ""
    microscopic_description: str = ""
    diagnosis: str = ""
    comments: str = ""

    comment_source: Optional[Literal["doctor", "ai"] | None] = None

    def apply_update(self, update: "FieldUpdate") -> bool:
        """Apply a single FieldUpdate to this Report.

        - `append` will add content to the existing field with sentence separation.
        - `replace` will overwrite the field.

        The Report is the single source of truth; all updates must be applied here.
        """
        target = update.target_section
        content = update.content.strip()
        if not content:
            return

        current = getattr(self, target, "") or ""
        if update.operation == "replace":
            if current == content:
                return False
            setattr(self, target, content)
        else:
            # append
            if content == current or content in current:
                return False
            if not current:
                new_val = content
            else:
                if current.endswith((".", "!", "?")):
                    new_val = f"{current} {content}"
                else:
                    new_val = f"{current}. {content}"
            setattr(self, target, new_val.strip())
        return True


class Comment(BaseModel):
    text: str
    source: Literal["doctor", "ai"]


class FieldUpdate(BaseModel):
    target_section: Literal[
        "patient",
        "specimen",
        "gross_description",
        "microscopic_description",
        "diagnosis",
        "comments",
    ]
    operation: Literal["append", "replace"] = "append"
    content: str

    @validator("content")
    def strip_content(cls, v: str) -> str:
        return (v or "").strip()


class ExtractionResponse(BaseModel):
    """Validated response returned by the incremental extraction provider."""

    updates: List[FieldUpdate] = Field(default_factory=list)


class ExtractedChunk(BaseModel):
    # original chunk text
    chunk_text: str
    # zero or more field updates extracted from this chunk
    updates: List[FieldUpdate] = Field(default_factory=list)
    # optional comment extracted from the chunk
    comment: Optional[Comment] = None
    # optional timestamp or order index
    timestamp: Optional[float] = None


class LangGraphState(BaseModel):
    """Top-level LangGraph workflow state.

    `report` is the persistent single source of truth. All field mutations
    are applied to `report` via `apply_updates`.

    Temporary workflow fields capture current chunk processing state.
    """

    report: Report = Field(default_factory=Report)

    # Temporary workflow state
    current_chunk: Optional[str] = None
    cleaned_chunk: Optional[str] = None
    previous_chunk: Optional[str] = None
    detected_fields: List[str] = Field(default_factory=list)
    active_field: Optional[str] = None
    # store extracted chunks history (each chunk may contain multiple updates)
    extracted_data: List[ExtractedChunk] = Field(default_factory=list)
    # most recent applied updates (for telemetry/UI diffs)
    updated_fields: List[FieldUpdate] = Field(default_factory=list)
    is_finished: bool = False

    def apply_updates(self, updates: List[FieldUpdate]) -> None:
        """Apply multiple updates to the single source-of-truth report.

        This updates `report` in-place and records `updated_fields`.
        """
        applied = []
        for u in updates:
            # apply to report
            if self.report.apply_update(u):
                applied.append(u)
        # record applied updates
        self.updated_fields = applied

