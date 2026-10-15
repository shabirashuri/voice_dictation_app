from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.graph.state import LangGraphState


@dataclass
class StreamingSession:
    """One dictation session's in-memory graph state."""

    session_id: str
    state: LangGraphState = field(default_factory=LangGraphState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_access: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_access = time.monotonic()
