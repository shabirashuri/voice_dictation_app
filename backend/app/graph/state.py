import logging
import re
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)

# A replace that keeps less than this share of the field is suspicious, but
# corrections legitimately shorten text, so it is only logged (never blocked).
REPLACE_SHRINK_WARN_RATIO = 0.4


def _normalize_sentence(text: str) -> str:
    """Lower-case, collapse whitespace and drop trailing sentence punctuation."""
    return " ".join(text.lower().split()).rstrip(".!?").strip()


def _ends_with_sentence(field: str, content: str) -> bool:
    """True when `content` is exactly the field's last sentence (or the whole field).

    Compares whole sentences, not substrings: "negative" is not a repeat of
    "Margins are negative", but "No H. pylori" is a repeat of "...No H. pylori".
    """
    norm_field = _normalize_sentence(field)
    norm_content = _normalize_sentence(content)
    if not norm_content:
        return False
    if norm_field == norm_content:
        return True
    return re.search(r"[.!?]\s+" + re.escape(norm_content) + r"$", norm_field) is not None


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
            return False

        current = getattr(self, target, "") or ""
        if update.operation == "replace":
            if current == content:
                return False
            if current and len(content) < len(current) * REPLACE_SHRINK_WARN_RATIO:
                # Logged by field and size only: report text is never logged.
                logger.warning(
                    "replace shrank %s from %d to %d characters",
                    target,
                    len(current),
                    len(content),
                )
            setattr(self, target, content)
        else:
            # append
            if _ends_with_sentence(current, content):
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
    # set by the finish graph: dictation is over and the clinician must review
    awaiting_review: bool = False

    # Chunk-graph working fields (reset at the start of every chunk)
    # bounded window of recent cleaned chunks passed to the LLM as context
    recent_context: List[str] = Field(default_factory=list)
    # raw, not-yet-validated LLM output for the current chunk
    raw_updates: List[dict] = Field(default_factory=list)
    raw_comment: Optional[dict] = None
    validation_errors: List[str] = Field(default_factory=list)
    retry_count: int = 0
    # set when a chunk is rejected; the report is left unchanged
    error_code: Optional[str] = None
    error_message: Optional[str] = None

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

