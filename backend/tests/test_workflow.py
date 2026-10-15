import asyncio
import pytest
from types import SimpleNamespace
from app.graph.routers import process_chunk, finalize
from app.graph.workflow import _load_state, _save_state


class MockLLM:
    def __init__(self):
        self.generate_called = 0
        self.generate_args = None
        self.extract_called = 0
        self.extract_args = []

    async def extract(self, prompt: str = "", **kwargs):
        self.extract_called += 1
        self.extract_args.append((prompt, kwargs))
        chunk = kwargs.get("chunk", "") or ""
        # simple deterministic extraction based on chunk content
        updates = []
        comment = None
        lower = chunk.lower()
        if "patient john doe" in lower or lower.strip().startswith("patient john doe") or "patient john doe." in lower:
            updates.append({"target_section": "patient", "operation": "replace", "content": "John Doe"})
        if "specimen is a gastric biopsy" in lower or "specimen is gastric biopsy" in lower or "gastric biopsy" in lower:
            updates.append({"target_section": "specimen", "operation": "append", "content": "Gastric biopsy"})
        if "two tan-white fragments" in lower or "tan-white" in lower:
            updates.append({"target_section": "specimen", "operation": "append", "content": "It consists of two tan-white fragments"})
        if "microscopically there is chronic inflammation" in lower or "microscopic" in lower and "chronic inflammation" in lower:
            updates.append({"target_section": "microscopic_description", "operation": "append", "content": "Microscopically there is chronic inflammation"})
        if "diagnosis is chronic gastritis" in lower or "diagnosis is" in lower and "chronic gastritis" in lower:
            updates.append({"target_section": "diagnosis", "operation": "append", "content": "Diagnosis is chronic gastritis"})
        if "recommend clinical correlation" in lower:
            # return a comment object in addition to updates
            comment = {"text": "Recommend clinical correlation.", "source": "doctor"}
            updates.append({"target_section": "comments", "operation": "append", "content": "Recommend clinical correlation."})
        return {"updates": updates, "comment": comment}

    async def generate(self, prompt: str = "", **kwargs):
        self.generate_called += 1
        self.generate_args = (prompt, kwargs)
        return "AI-generated comment"


@pytest.mark.asyncio
async def test_streaming_session_with_doctor_comment(tmp_path, monkeypatch):
    session_id = "test_session_doc_comment"
    # ensure clean state file
    from app.graph.state import LangGraphState
    try:
        _save_state(session_id, LangGraphState())
    except Exception:
        pass

    llm = MockLLM()

    # Chunk 1
    r1 = await process_chunk(session_id, "Patient John Doe.", llm=llm)
    assert r1["report"]["patient"] == "John Doe"
    assert "patient" in r1["updated_fields"]

    # Chunk 2
    r2 = await process_chunk(session_id, "Specimen is a gastric biopsy.", llm=llm)
    assert "Gastric biopsy" in r2["report"]["specimen"]
    assert "specimen" in r2["updated_fields"]

    # Chunk 3
    r3 = await process_chunk(session_id, "It consists of two tan-white fragments.", llm=llm)
    specimen = r3["report"]["specimen"]
    assert "Gastric biopsy" in specimen and "two tan-white fragments" in specimen

    # Chunk 4
    r4 = await process_chunk(session_id, "Microscopically there is chronic inflammation.", llm=llm)
    assert "chronic inflammation" in r4["report"]["microscopic_description"].lower()

    # Chunk 5
    r5 = await process_chunk(session_id, "Diagnosis is chronic gastritis.", llm=llm)
    assert "chronic gastritis" in r5["report"]["diagnosis"].lower()

    # Chunk 6
    r6 = await process_chunk(session_id, "Recommend clinical correlation.", llm=llm)
    assert "recommend clinical correlation" in r6["report"]["comments"].lower()
    # comment source should be marked as doctor by merge node
    state = _load_state(session_id)
    assert state.report.comment_source == "doctor"

    # Finalize should NOT call AI generate (doctor comment exists)
    final = await finalize(session_id, llm=llm)
    assert llm.generate_called == 0
    assert final["report"]["comments"] == state.report.comments
    assert final["is_finished"] is True


@pytest.mark.asyncio
async def test_streaming_session_without_doctor_comment_calls_ai(tmp_path):
    session_id = "test_session_no_doc_comment"
    from app.graph.state import LangGraphState
    try:
        _save_state(session_id, LangGraphState())
    except Exception:
        pass

    llm = MockLLM()

    # stream a few chunks that do not include comment
    await process_chunk(session_id, "Patient John Doe.", llm=llm)
    await process_chunk(session_id, "Specimen is a gastric biopsy.", llm=llm)
    await process_chunk(session_id, "It consists of two tan-white fragments.", llm=llm)

    state_before = _load_state(session_id)
    assert not (state_before.report.comments and state_before.report.comments.strip())

    # Finalize should call AI generate
    final = await finalize(session_id, llm=llm)
    assert llm.generate_called == 1
    assert final["report"]["comments"] == "AI-generated comment"
    assert final["report"]["comment_source"] == "ai"
    assert final["is_finished"] is True


@pytest.mark.asyncio
async def test_multiple_fields_single_chunk_and_replace_and_empty_and_isolation(tmp_path):
    from app.graph.state import LangGraphState

    # single chunk updates multiple fields
    s1 = "session_multi"
    _save_state(s1, LangGraphState())
    llm1 = MockLLM()
    res = await process_chunk(s1, "Patient John Doe. Specimen is gastric biopsy.", llm=llm1)
    assert "John Doe" in res["report"]["patient"]
    assert "Gastric biopsy" in res["report"]["specimen"]

    # replace operation
    res2 = await process_chunk(s1, "Patient Jane Doe.", llm=llm1)
    # our mock returns replace for patient John Doe only; to simulate replace test, we directly craft update
    # simulate explicit replace by using llm that returns replace
    class ReplaceLLM(MockLLM):
        async def extract(self, prompt: str = "", **kwargs):
            return {"updates": [{"target_section": "patient", "operation": "replace", "content": "Jane Doe"}], "comment": None}

    rllm = ReplaceLLM()
    res_replace = await process_chunk(s1, "Actually, Jane Doe.", llm=rllm)
    assert "Jane Doe" in res_replace["report"]["patient"]

    # empty chunk does not change state
    before = _load_state(s1).report.dict()
    res_empty = await process_chunk(s1, "", llm=llm1)
    after = _load_state(s1).report.dict()
    assert before == after

    # session isolation
    s2 = "session_other"
    _save_state(s2, LangGraphState())
    llm2 = MockLLM()
    await process_chunk(s2, "Patient Alice Smith.", llm=llm2)
    st1 = _load_state(s1).report.patient
    st2 = _load_state(s2).report.patient
    assert "Jane Doe" in st1
    assert st2 != st1

    # updated_fields correctness
    res_multi = await process_chunk(s2, "Specimen is cardiac tissue.", llm=llm2)
    assert res_multi["updated_fields"] in ([], ["specimen"])

    # frontend receiving correct state is tested by returned dict structure
    assert set(res_multi["report"].keys()) >= {"patient", "specimen", "gross_description", "microscopic_description", "diagnosis", "comments"}

    # finalization only after stop
    # before finalize, is_finished should be False
    s_state = _load_state(s2)
    assert s_state.is_finished is False
    # finalize triggers AI if no comment
    final_s2 = await finalize(s2, llm=llm2)
    assert final_s2["is_finished"] is True


class ContractLLM:
    def __init__(self):
        self.calls = []

    async def extract(self, prompt="", **kwargs):
        self.calls.append(kwargs)
        chunk = kwargs.get("chunk", "").lower()
        if "patient" in chunk and "specimen" in chunk:
            return {
                "updates": [
                    {"target_section": "patient", "operation": "append", "content": "John Doe"},
                    {"target_section": "specimen", "operation": "append", "content": "gastric biopsy"},
                ]
            }
        if "actually" in chunk:
            return {
                "updates": [
                    {"target_section": "specimen", "operation": "replace", "content": "kidney biopsy"}
                ]
            }
        if "foveolar" in chunk:
            return {
                "updates": [
                    {
                        "target_section": "microscopic_description",
                        "operation": "append",
                        "content": "mild foveolar hyperplasia. No intestinal metaplasia or malignancy is identified.",
                    }
                ]
            }
        if "two small tissue pieces" in chunk:
            return {
                "updates": [
                    {"target_section": "specimen", "operation": "append", "content": "It contains two small tissue pieces."}
                ]
            }
        if "clinical correlation" in chunk:
            return {
                "updates": [
                    {"target_section": "comments", "operation": "append", "content": "Recommend clinical correlation."}
                ]
            }
        return {"updates": []}

    async def generate(self, prompt="", **kwargs):
        return "AI-generated comment"


@pytest.mark.asyncio
async def test_incremental_extraction_contract_cases():
    session_id = "test_extraction_contract"
    from app.graph.state import LangGraphState

    _save_state(session_id, LangGraphState())
    llm = ContractLLM()

    result = await process_chunk(session_id, "Patient John Doe. Specimen is a gastric biopsy.", llm=llm)
    assert result["report"]["patient"] == "John Doe"
    assert result["report"]["specimen"] == "gastric biopsy"

    result = await process_chunk(
        session_id,
        "and mild foveolar hyperplasia. No intestinal metaplasia or malignancy is identified.",
        llm=llm,
    )
    assert "foveolar hyperplasia" in result["report"]["microscopic_description"]
    assert result["report"]["comments"] == ""

    result = await process_chunk(session_id, "Actually, the specimen is a kidney biopsy.", llm=llm)
    assert result["report"]["specimen"] == "kidney biopsy"

    result = await process_chunk(session_id, "It contains two small tissue pieces.", llm=llm)
    assert "two small tissue pieces" in result["report"]["specimen"]

    result = await process_chunk(session_id, "Recommend clinical correlation.", llm=llm)
    assert result["report"]["comments"] == "Recommend clinical correlation."
    assert _load_state(session_id).report.comment_source == "doctor"

    calls_before_empty = len(llm.calls)
    result = await process_chunk(session_id, "", llm=llm)
    assert result["report"]["comments"] == "Recommend clinical correlation."
    assert len(llm.calls) == calls_before_empty

    continuation_call = llm.calls[1]
    assert continuation_call["previous_chunk"].startswith("Patient John Doe")
    assert continuation_call["report_state"]["specimen"] == "gastric biopsy"


@pytest.mark.asyncio
async def test_active_field_and_duplicate_chunk_are_persisted_and_deduplicated():
    session_id = "test_active_field_and_duplicate"
    from app.graph.state import LangGraphState

    _save_state(session_id, LangGraphState())
    class MicroscopicLLM(ContractLLM):
        async def extract(self, prompt="", **kwargs):
            self.calls.append(kwargs)
            if "gastric mucosa" in kwargs.get("chunk", "").lower():
                return {
                    "updates": [
                        {
                            "target_section": "microscopic_description",
                            "operation": "append",
                            "content": "gastric mucosa",
                        }
                    ]
                }
            return await super().extract(prompt=prompt, **kwargs)

    llm = MicroscopicLLM()

    first = await process_chunk(session_id, "Microscopic examination shows gastric mucosa.", llm=llm)
    assert first["updated_fields"] == ["microscopic_description"]

    # The mocked provider recognizes the continuation and returns the field update.
    second = await process_chunk(session_id, "and mild foveolar hyperplasia. No intestinal metaplasia or malignancy is identified.", llm=llm)
    assert second["updated_fields"] == ["microscopic_description"]
    persisted = _load_state(session_id)
    assert persisted.active_field == "microscopic_description"
    assert persisted.previous_chunk == "and mild foveolar hyperplasia. No intestinal metaplasia or malignancy is identified."

    call_count = len(llm.calls)
    duplicate = await process_chunk(session_id, "and mild foveolar hyperplasia. No intestinal metaplasia or malignancy is identified.", llm=llm)
    assert duplicate["updated_fields"] == []
    assert len(llm.calls) == call_count
    assert duplicate["report"] == second["report"]


@pytest.mark.asyncio
async def test_updated_fields_only_contains_changed_report_fields():
    session_id = "test_exact_updated_fields"
    from app.graph.state import LangGraphState

    _save_state(session_id, LangGraphState())

    class MultiFieldLLM(ContractLLM):
        async def extract(self, prompt="", **kwargs):
            self.calls.append(kwargs)
            return {
                "updates": [
                    {"target_section": "patient", "operation": "append", "content": "John"},
                    {"target_section": "specimen", "operation": "append", "content": "gastric biopsy"},
                    {"target_section": "diagnosis", "operation": "append", "content": "gastritis"},
                ]
            }

    llm = MultiFieldLLM()
    result = await process_chunk(session_id, "Patient is John. Specimen is gastric biopsy. Diagnosis is gastritis.", llm=llm)
    assert result["updated_fields"] == [
        "patient",
        "specimen",
        "diagnosis",
    ]
    assert set(result["report"]) >= {
        "patient",
        "specimen",
        "gross_description",
        "microscopic_description",
        "diagnosis",
        "comments",
    }