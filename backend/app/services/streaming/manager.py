from __future__ import annotations

import os
import time

from app.graph.state import LangGraphState
from app.services.streaming.session import StreamingSession


def _default_ttl() -> float:
    try:
        return float(os.environ.get("SESSION_TTL_SECONDS", "3600"))
    except ValueError:
        return 3600.0


class StreamingManager:
    """In-memory store for per-session graph state.

    State lives only for the dictation session (plus a TTL backstop); the
    approved report is persisted to the database, never the live state.
    `load`/`save` hand out deep copies so callers can't mutate stored state
    by accident.
    """

    def __init__(self, ttl_seconds: float | None = None):
        self.ttl_seconds = _default_ttl() if ttl_seconds is None else ttl_seconds
        self.sessions: dict[str, StreamingSession] = {}

    def _session(self, session_id: str) -> StreamingSession:
        self.sweep()
        session = self.sessions.get(session_id)
        if session is None:
            session = StreamingSession(session_id)
            self.sessions[session_id] = session
        session.touch()
        return session

    def lock(self, session_id: str):
        return self._session(session_id).lock

    def load(self, session_id: str) -> LangGraphState:
        return self._session(session_id).state.model_copy(deep=True)

    def save(self, session_id: str, state: LangGraphState) -> None:
        self._session(session_id).state = state.model_copy(deep=True)

    def discard(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def sweep(self) -> None:
        """Drop idle sessions past the TTL, skipping any currently in use."""
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [
            sid
            for sid, s in self.sessions.items()
            if s.last_access < cutoff and not s.lock.locked()
        ]
        for sid in expired:
            del self.sessions[sid]


session_manager = StreamingManager()
