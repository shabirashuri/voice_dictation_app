from pydantic import BaseModel
from typing import Optional, Dict, Any

class ReportModel(BaseModel):
    patient: Dict[str, Any] = {}
    specimen: Dict[str, Any] = {}
    gross_description: str = ""
    microscopic_description: str = ""
    diagnosis: str = ""
    comments: Optional[str] = None
