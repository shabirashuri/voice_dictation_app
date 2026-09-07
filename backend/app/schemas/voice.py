from pydantic import BaseModel

class TranscriptChunk(BaseModel):
    session_id: str
    chunk: str
    timestamp: float | None = None
