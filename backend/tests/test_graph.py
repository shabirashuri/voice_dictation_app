import pytest

from app.graph.routers import process_chunk
from app.graph.state import LangGraphState
from app.graph.workflow import _load_state, _save_state
from app.services.llm.provider import LLMResponseError


class ScriptedLLM:
    """Returns scripted responses in order; an Exception entry is raised."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def extract(self, prompt="", **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, prompt="", **kwargs):
        return "AI-generated comment"


def _fresh(session_id):
    _save_state(session_id, LangGraphState())


GOOD = {"updates": [{"target_section": "specimen", "operation": "append", "content": "Gastric biopsy"}]}
BAD_SECTION = {"updates": [{"target_section": "not_a_field", "operation": "append", "content": "x"}]}


@pytest.mark.asyncio
async def test_valid_chunk_merges_without_repair():
    _fresh("graph_valid")
    llm = ScriptedLLM(GOOD)
    res = await process_chunk("graph_valid", "Specimen is a gastric biopsy.", llm=llm)
    assert res["report"]["specimen"] == "Gastric biopsy"
    assert res["updated_fields"] == ["specimen"]
    assert "error_code" not in res
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_schema_failure_is_repaired_with_feedback():
    _fresh("graph_repair")
    llm = ScriptedLLM(LLMResponseError("LLM extraction response failed schema validation"), GOOD)
    res = await process_chunk("graph_repair", "Specimen is a gastric biopsy.", llm=llm)
    assert res["report"]["specimen"] == "Gastric biopsy"
    assert "error_code" not in res
    assert len(llm.calls) == 2
    # the retry carries the previous validation error as feedback
    assert llm.calls[1]["validation_errors"]


@pytest.mark.asyncio
async def test_invalid_update_is_repaired():
    _fresh("graph_invalid_repair")
    llm = ScriptedLLM(BAD_SECTION, GOOD)
    res = await process_chunk("graph_invalid_repair", "Specimen is a gastric biopsy.", llm=llm)
    assert res["report"]["specimen"] == "Gastric biopsy"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_exhausted_repair_rejects_chunk_and_leaves_report_unchanged():
    _fresh("graph_reject")
    llm = ScriptedLLM(GOOD)
    await process_chunk("graph_reject", "Specimen is a gastric biopsy.", llm=llm)
    before = _load_state("graph_reject").report.dict()

    llm = ScriptedLLM(BAD_SECTION, BAD_SECTION)
    res = await process_chunk("graph_reject", "Microscopically there is inflammation.", llm=llm)
    assert res["error_code"] == "validation"
    assert res["updated_fields"] == []
    assert len(llm.calls) == 2  # one attempt + one repair, then reject
    assert _load_state("graph_reject").report.dict() == before
    # a rejected chunk is not recorded as the previous chunk
    assert _load_state("graph_reject").previous_chunk == "Specimen is a gastric biopsy."


@pytest.mark.asyncio
async def test_empty_and_repeated_chunks_skip_llm():
    _fresh("graph_skip")
    llm = ScriptedLLM(GOOD)
    await process_chunk("graph_skip", "Specimen is a gastric biopsy.", llm=llm)
    assert (await process_chunk("graph_skip", "", llm=llm))["updated_fields"] == []
    assert (await process_chunk("graph_skip", "Specimen is a gastric biopsy.", llm=llm))["updated_fields"] == []
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_recent_context_is_bounded_to_five_chunks():
    _fresh("graph_context")
    responses = [{"updates": []} for _ in range(7)]
    llm = ScriptedLLM(*responses)
    for i in range(7):
        await process_chunk("graph_context", f"Chunk number {i}.", llm=llm)
    recent = _load_state("graph_context").recent_context
    assert len(recent) == 5
    assert recent[-1] == "Chunk number 6."
    assert llm.calls[-1]["recent_context"][-1] == "Chunk number 5."
