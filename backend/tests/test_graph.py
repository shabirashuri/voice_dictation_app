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


class SectionLLM:
    """Routes each chunk by keyword, like a well-behaved extractor."""

    def __init__(self):
        self.generate_called = 0

    async def extract(self, prompt="", **kwargs):
        chunk = kwargs["chunk"].lower()
        updates = []
        if "microscopically" in chunk:
            updates.append({"target_section": "microscopic_description", "operation": "append", "content": "Chronic inactive gastritis."})
        if "specimen" in chunk:
            updates.append({"target_section": "specimen", "operation": "append", "content": "Gastric biopsy from the antrum."})
        if "diagnosis" in chunk:
            updates.append({"target_section": "diagnosis", "operation": "append", "content": "Chronic inactive gastritis."})
        return {"updates": updates}

    async def generate(self, prompt="", **kwargs):
        self.generate_called += 1
        return "AI-generated comment"


@pytest.mark.asyncio
async def test_sections_can_be_dictated_in_any_order():
    _fresh("graph_order")
    llm = SectionLLM()
    r1 = await process_chunk("graph_order", "Microscopically, chronic inactive gastritis.", llm=llm)
    assert r1["updated_fields"] == ["microscopic_description"]
    assert r1["report"]["specimen"] == "" and r1["report"]["diagnosis"] == ""

    r2 = await process_chunk("graph_order", "The final diagnosis is chronic inactive gastritis.", llm=llm)
    assert r2["updated_fields"] == ["diagnosis"]

    r3 = await process_chunk("graph_order", "The specimen is a gastric biopsy from the antrum.", llm=llm)
    assert r3["updated_fields"] == ["specimen"]
    assert r3["report"]["microscopic_description"] == "Chronic inactive gastritis."
    assert r3["report"]["diagnosis"] == "Chronic inactive gastritis."


@pytest.mark.asyncio
async def test_one_chunk_can_update_multiple_sections():
    _fresh("graph_multi")
    res = await process_chunk(
        "graph_multi",
        "The specimen is a gastric biopsy from the antrum. Microscopically there is chronic inactive gastritis.",
        llm=SectionLLM(),
    )
    assert res["updated_fields"] == ["microscopic_description", "specimen"]


@pytest.mark.asyncio
async def test_comments_are_never_generated_per_chunk():
    _fresh("graph_no_comment")
    llm = SectionLLM()
    for chunk in ["Specimen is a biopsy.", "Microscopically, gastritis.", "Diagnosis is gastritis."]:
        res = await process_chunk("graph_no_comment", chunk, llm=llm)
        assert res["report"]["comments"] == ""
    assert llm.generate_called == 0
