import json
from types import SimpleNamespace

import pytest
from assemblyai.streaming.v3 import RealTimeEvents
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.graph.routers import finalize, process_chunk
from app.graph.state import LangGraphState
from app.graph.workflow import _load_state, _save_state
from app.services.llm.provider import LLMRateLimitError
from app.services.streaming.manager import StreamingManager, session_manager


class FakeLLM:
    def __init__(self, comment="AI-generated comment", generate_error=None):
        self.comment = comment
        self.generate_error = generate_error
        self.generate_called = 0

    async def extract(self, prompt="", **kwargs):
        if "biopsy" in kwargs.get("chunk", "").lower():
            return {"updates": [{"target_section": "specimen", "operation": "append", "content": "Gastric biopsy"}]}
        return {"updates": []}

    async def generate(self, prompt="", **kwargs):
        self.generate_called += 1
        if self.generate_error:
            raise self.generate_error
        return self.comment


@pytest.mark.asyncio
async def test_finalize_twice_generates_ai_comment_once():
    _save_state("finish_once", LangGraphState())
    llm = FakeLLM()
    await process_chunk("finish_once", "Specimen is a gastric biopsy.", llm=llm)
    first = await finalize("finish_once", llm=llm)
    second = await finalize("finish_once", llm=llm)
    assert llm.generate_called == 1
    assert first["awaiting_review"] is True and first["is_finished"] is True
    assert second["report"]["comments"] == "AI-generated comment"
    assert second["report"]["comment_source"] == "ai"


@pytest.mark.asyncio
async def test_chunks_after_finalize_do_not_change_report():
    _save_state("finish_late", LangGraphState())
    llm = FakeLLM()
    await finalize("finish_late", llm=llm)
    before = _load_state("finish_late").report.dict()
    res = await process_chunk("finish_late", "Specimen is a gastric biopsy.", llm=llm)
    assert res["updated_fields"] == []
    assert _load_state("finish_late").report.dict() == before


@pytest.mark.asyncio
async def test_rate_limited_comment_generation_still_finishes_with_error():
    _save_state("finish_rate", LangGraphState())
    llm = FakeLLM(generate_error=LLMRateLimitError("quota"))
    res = await finalize("finish_rate", llm=llm)
    assert res["is_finished"] is True and res["awaiting_review"] is True
    assert res["error_code"] == "llm_rate_limit"
    assert res["report"]["comments"] == ""
    assert res["report"]["comment_source"] is None


def test_session_manager_sweeps_idle_sessions_and_returns_copies():
    manager = StreamingManager(ttl_seconds=0)
    state = LangGraphState()
    manager.save("a", state)
    loaded = manager.load("a")
    loaded.report.patient = "mutated"
    assert manager.load("a").report.patient == ""
    manager.sweep()
    assert "a" not in manager.sessions


class FakeTranscriber:
    """Stands in for AssemblyAI: each audio frame yields one final turn."""

    def __init__(self, api_key=None):
        self.handlers = {}
        self.disconnected = False

    def on(self, event, handler):
        self.handlers[event] = handler

    async def connect(self, params):
        await self.handlers[RealTimeEvents.Begin](self, SimpleNamespace(id="ws_test"))

    async def stream(self, audio_bytes):
        event = SimpleNamespace(
            transcript=audio_bytes.decode(), end_of_turn=True, turn_order=1, language_code="en", words=[]
        )
        await self.handlers[RealTimeEvents.Turn](self, event)

    async def disconnect(self, terminate=False):
        self.disconnected = True


@pytest.fixture
def ws_client(monkeypatch):
    from app.api.websocket import voice

    llm = FakeLLM()
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test")
    monkeypatch.setattr(voice, "AsyncRealTimeTranscriber", FakeTranscriber)
    monkeypatch.setattr("app.services.llm.provider.build_default_llm", lambda: llm)
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app), llm


def _audio(text):
    import base64

    return json.dumps({"audio": base64.b64encode(text.encode()).decode()})


def _next(ws, type_):
    while True:
        msg = ws.receive_json()
        if msg.get("type") == type_:
            return msg


def test_websocket_stop_finalizes_and_keeps_socket_open_for_review(ws_client):
    client, llm = ws_client
    with client.websocket_connect("/ws/voice") as ws:
        assert _next(ws, "begin")["id"] == "ws_test"
        ws.send_text(_audio("Specimen is a gastric biopsy."))
        state = _next(ws, "state")
        assert state["report"]["specimen"] == "Gastric biopsy"

        ws.send_text(json.dumps({"type": "stop"}))
        final = _next(ws, "state")
        assert final["is_finished"] is True and final["awaiting_review"] is True
        assert final["report"]["comment_source"] == "ai"
        assert llm.generate_called == 1

        # socket is still open during review; audio is ignored now
        ws.send_text(_audio("Diagnosis is gastritis biopsy."))
        ws.send_text(json.dumps({"type": "close"}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    # live state is dropped once the session ends
    assert "ws_test" not in session_manager.sessions
