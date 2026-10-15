import pytest

from app.graph.routers import finalize, process_chunk
from app.graph.state import LangGraphState
from app.graph.workflow import _load_state, _save_state
from app.services.llm.provider import LLMRateLimitError
from app.services.streaming.manager import StreamingManager


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


@pytest.mark.asyncio
async def test_ai_comment_with_an_unsupported_statement_is_withheld():
    _save_state("finish_withheld", LangGraphState())
    llm = FakeLLM(comment="No additional pathology identified.")
    await process_chunk("finish_withheld", "Specimen is a gastric biopsy.", llm=llm)
    res = await finalize("finish_withheld", llm=llm)
    assert res["report"]["comments"] == ""
    assert res["report"]["comment_source"] is None
    assert res["is_finished"] is True and res["awaiting_review"] is True


@pytest.mark.asyncio
async def test_grounded_ai_comment_is_kept():
    _save_state("finish_grounded", LangGraphState())
    llm = FakeLLM(comment="Gastric biopsy received.")
    await process_chunk("finish_grounded", "Specimen is a gastric biopsy.", llm=llm)
    res = await finalize("finish_grounded", llm=llm)
    assert res["report"]["comments"] == "Gastric biopsy received."
    assert res["report"]["comment_source"] == "ai"
