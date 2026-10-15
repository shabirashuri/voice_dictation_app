import base64
import json
from types import SimpleNamespace

import pytest
from assemblyai.streaming.v3 import RealTimeEvents
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.llm.provider import LLMRateLimitError
from app.services.streaming.manager import session_manager

BAD_UPDATE = {"updates": [{"target_section": "not_a_field", "operation": "append", "content": "x"}]}


class FakeLLM:
    """Keyword-driven extractor; special chunks trigger failures."""

    def __init__(self):
        self.generate_called = 0

    async def extract(self, prompt="", **kwargs):
        chunk = kwargs.get("chunk", "").lower()
        if "ratelimit" in chunk:
            raise LLMRateLimitError("quota exceeded")
        if "garbled" in chunk:
            return BAD_UPDATE
        if "biopsy" in chunk:
            return {"updates": [{"target_section": "specimen", "operation": "append", "content": "Gastric biopsy"}]}
        return {"updates": []}

    async def generate(self, prompt="", **kwargs):
        self.generate_called += 1
        return "AI-generated comment"


class FakeTranscriber:
    """Stands in for AssemblyAI: each audio frame yields one final turn."""

    def __init__(self, api_key=None):
        self.handlers = {}

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
        pass


@pytest.fixture
def ws_client(app, monkeypatch):
    from app.api.websocket import voice

    llm = FakeLLM()
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test")
    monkeypatch.setattr(voice, "AsyncRealTimeTranscriber", FakeTranscriber)
    monkeypatch.setattr("app.services.llm.provider.build_default_llm", lambda: llm)
    return TestClient(app), llm


def _doctor_with_case(client, email="doc@example.com", patient="John Doe", mrn="MRN-7"):
    res = client.post("/auth/signup", json={"email": email, "full_name": "Dr. House", "password": "correct-horse"})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    case = client.post("/cases", json={"patient_name": patient, "patient_mrn": mrn}, headers=headers).json()
    return token, case, headers


def _auth(ws, token, case_id):
    ws.send_text(json.dumps({"type": "auth", "token": token, "case_id": case_id}))


def _audio(text):
    return json.dumps({"audio": base64.b64encode(text.encode()).decode()})


def _next(ws, type_):
    while True:
        msg = ws.receive_json()
        if msg.get("type") == type_:
            return msg


def test_stop_finalizes_and_keeps_socket_open_for_review(ws_client):
    client, llm = ws_client
    token, case, _ = _doctor_with_case(client)
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, token, case["id"])
        assert _next(ws, "begin")["id"] == "ws_test"
        ws.send_text(_audio("Specimen is a gastric biopsy."))
        state = _next(ws, "state")
        assert state["report"]["specimen"] == "Gastric biopsy"
        # the report starts with the case's patient
        assert state["report"]["patient"] == "John Doe (MRN MRN-7)"

        ws.send_text(json.dumps({"type": "stop"}))
        final = _next(ws, "state")
        assert final["is_finished"] is True and final["awaiting_review"] is True
        assert final["report"]["comment_source"] == "ai"
        assert llm.generate_called == 1

        # still open during review; audio is ignored, a second stop is a no-op
        ws.send_text(_audio("Diagnosis is gastritis biopsy."))
        ws.send_text(json.dumps({"type": "stop"}))
        ws.send_text(json.dumps({"type": "close"}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    assert llm.generate_called == 1
    # live state is dropped once the session ends
    assert "ws_test" not in session_manager.sessions


def test_missing_assemblyai_key_reports_stt_error(ws_client, monkeypatch):
    client, _ = ws_client
    token, case, _ = _doctor_with_case(client)
    monkeypatch.delenv("ASSEMBLYAI_API_KEY")
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, token, case["id"])
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "stt"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_llm_rate_limit_reports_coded_error_and_keeps_session(ws_client):
    client, _ = ws_client
    token, case, _ = _doctor_with_case(client)
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, token, case["id"])
        _next(ws, "begin")
        ws.send_text(_audio("ratelimit this chunk"))
        err = _next(ws, "error")
        assert err["code"] == "llm_rate_limit"
        # the session keeps working afterwards
        ws.send_text(_audio("Specimen is a gastric biopsy."))
        assert _next(ws, "state")["report"]["specimen"] == "Gastric biopsy"
        ws.send_text(json.dumps({"type": "close"}))


def test_rejected_chunk_reports_validation_error_and_report_is_unchanged(ws_client):
    client, _ = ws_client
    token, case, _ = _doctor_with_case(client)
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, token, case["id"])
        _next(ws, "begin")
        ws.send_text(_audio("Specimen is a gastric biopsy."))
        _next(ws, "state")
        ws.send_text(_audio("garbled words"))
        state = _next(ws, "state")
        assert state["updated_fields"] == []
        assert state["report"]["specimen"] == "Gastric biopsy"
        assert _next(ws, "error")["code"] == "validation"
        ws.send_text(json.dumps({"type": "close"}))


def test_idle_socket_is_closed_with_timeout_error(ws_client, monkeypatch):
    client, _ = ws_client
    token, case, _ = _doctor_with_case(client)
    monkeypatch.setenv("WS_IDLE_TIMEOUT_SECONDS", "0.2")
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, token, case["id"])
        _next(ws, "begin")
        assert _next(ws, "error")["code"] == "timeout"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def _expect_auth_error(ws, text):
    msg = ws.receive_json()
    assert msg["type"] == "error" and msg["code"] == "auth"
    assert text in msg["error"]
    with pytest.raises(WebSocketDisconnect):
        ws.receive_json()


def test_first_message_must_be_auth(ws_client):
    client, _ = ws_client
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(_audio("Specimen is a gastric biopsy."))
        _expect_auth_error(ws, "auth message")


def test_invalid_token_is_rejected(ws_client):
    client, _ = ws_client
    _, case, _ = _doctor_with_case(client)
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, "not-a-token", case["id"])
        _expect_auth_error(ws, "not signed in")


def test_another_doctors_case_is_rejected(ws_client):
    client, _ = ws_client
    _, alice_case, _ = _doctor_with_case(client, email="alice@example.com")
    bob_token, _, _ = _doctor_with_case(client, email="bob@example.com")
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, bob_token, alice_case["id"])
        _expect_auth_error(ws, "case not found")


def test_reported_case_cannot_be_dictated_again(ws_client):
    client, _ = ws_client
    token, case, headers = _doctor_with_case(client)
    saved = client.post(
        f"/cases/{case['id']}/report",
        json={"report": {"diagnosis": "Gastritis"}, "comment_source": None},
        headers=headers,
    )
    assert saved.status_code == 201
    with client.websocket_connect("/ws/voice") as ws:
        _auth(ws, token, case["id"])
        _expect_auth_error(ws, "already has an approved report")
