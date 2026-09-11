from __future__ import annotations

from app.graph.workflow import Workflow


# Session-aware convenience functions
_wf = Workflow()


async def process_chunk(session_id: str, chunk: str, llm=None) -> dict:
    """Process a single chunk for `session_id` and return a dict with keys:
    `report`, `updated_fields`, `is_finished`.
    """
    return await _wf.process_chunk(session_id, chunk, llm=llm)


async def finalize(session_id: str, llm=None) -> dict:
    return await _wf.finalize(session_id, llm=llm)
