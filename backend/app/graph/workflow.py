from __future__ import annotations

from app.graph.graph import chunk_graph, finish_graph
from app.graph.state import LangGraphState
from app.services.streaming.manager import session_manager


def _load_state(session_id: str) -> LangGraphState:
    return session_manager.load(session_id)


def _save_state(session_id: str, state: LangGraphState) -> None:
    session_manager.save(session_id, state)


def discard_session(session_id: str) -> None:
    """Drop a session's in-memory state (on disconnect or after save)."""
    session_manager.discard(session_id)


async def _run(graph, state: LangGraphState, llm) -> LangGraphState:
    out = await graph.ainvoke(state.model_dump(), config={"configurable": {"llm": llm}})
    return out if isinstance(out, LangGraphState) else LangGraphState(**out)


def _with_error(result: dict, state: LangGraphState) -> dict:
    if state.error_code:
        result["error_code"] = state.error_code
        result["error_message"] = state.error_message
    return result


class Workflow:
    """Session-aware workflow over the chunk and finish graphs.

    Call `process_chunk(session_id, chunk, llm)` for each final transcript
    chunk and `finalize(session_id, llm)` when the clinician stops dictating.
    State is kept in memory per session (see `StreamingManager`) and is never
    written to disk; only the approved report is persisted.
    """

    async def process_chunk(self, session_id: str, chunk: str, llm=None) -> dict:
        """Process a single transcript chunk for `session_id`.

        Runs the chunk graph (clean → classify → extract → validate → merge).
        Returns a dict with keys: `report` (dict), `updated_fields` (list),
        `is_finished` (bool), and `error_code`/`error_message` when the chunk
        was rejected (the report is unchanged in that case). Chunks arriving
        after finalize are ignored so they can't change a report under review.
        """
        async with session_manager.lock(session_id):
            state = _load_state(session_id)
            if not state.awaiting_review:
                state.current_chunk = chunk
                state.is_finished = False
                state = await _run(chunk_graph, state, llm)
                _save_state(session_id, state)
            else:
                state.updated_fields = []
                state.error_code = None

            return _with_error(
                {
                    "report": state.report.dict(),
                    "updated_fields": [u.target_section for u in state.updated_fields],
                    "is_finished": state.is_finished,
                },
                state,
            )

    async def finalize(self, session_id: str, llm=None) -> dict:
        """Run the finish graph: final validation → comment decision → keep the
        clinician comment or generate one AI comment → awaiting review.

        Calling it again does not generate a second AI comment.
        """
        async with session_manager.lock(session_id):
            state = _load_state(session_id)
            state = await _run(finish_graph, state, llm)
            _save_state(session_id, state)
            return _with_error(
                {
                    "report": state.report.dict(),
                    "is_finished": state.is_finished,
                    "awaiting_review": state.awaiting_review,
                },
                state,
            )
