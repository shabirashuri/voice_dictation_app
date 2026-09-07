from typing import Any, Dict, List
from pydantic import BaseModel

class ReportState(BaseModel):
    patient: Dict[str, Any] = {}
    specimen: Dict[str, Any] = {}
    gross_description: str = ""
    microscopic_description: str = ""
    diagnosis: str = ""
    comments: str = ""
    active_section: str | None = None
    recent_context: List[str] = []

    def merge_updates(self, updates: list):
        # Placeholder merge logic
        pass
