from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from app.graph.state import LangGraphState
from app.graph.nodes.clean import clean_chunk_node
from app.graph.nodes.classify import classify_chunk_node
from app.graph.nodes.extract import extract_chunk_node
from app.graph.nodes.merge import merge_chunk_node
from app.graph.nodes.clean import clean_text

_SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
_session_locks: dict = {}


def _session_path(session_id: str) -> str:
    # sanitize session_id: allow alnum, -, _
    safe = "".join([c for c in session_id if c.isalnum() or c in ("-", "_")])
    return os.path.join(_SESSIONS_DIR, f"{safe}.json")


def _ensure_sessions_dir() -> None:
    try:
        os.makedirs(_SESSIONS_DIR, exist_ok=True)
    except Exception:
        pass


async def _acquire_lock(session_id: str):
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    await lock.acquire()


def _release_lock(session_id: str):
    lock = _session_locks.get(session_id)
    if lock and lock.locked():
        lock.release()


def _load_state(session_id: str) -> LangGraphState:
    _ensure_sessions_dir()
    path = _session_path(session_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
                return LangGraphState.parse_raw(data)
        except Exception:
            # fallback to fresh state
            return LangGraphState()
    return LangGraphState()


def _save_state(session_id: str, state: LangGraphState) -> None:
    _ensure_sessions_dir()
    path = _session_path(session_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(state.json())
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass
        os.replace(tmp, path)


class Workflow:
    """Session-aware workflow that processes one chunk at a time.

    Usage: call `process_chunk(session_id, chunk, llm)` for each incoming
    transcript chunk. The LangGraphState is persisted per-session so state
    survives between chunk invocations.
    """

    async def process_chunk(self, session_id: str, chunk: str, llm=None) -> dict:
        """Process a single transcript chunk for `session_id` and persist state.

        Returns a dict with keys: `report` (dict), `updated_fields` (list), `is_finished` (bool)
        """
        await _acquire_lock(session_id)
        try:
            state = _load_state(session_id)

            # set current chunk
            state.current_chunk = chunk
            state.is_finished = False

            cleaned = await clean_text(chunk or "")
            if not cleaned or cleaned == (state.previous_chunk or ""):
                state.cleaned_chunk = cleaned
                state.updated_fields = []
                _save_state(session_id, state)
                return {
                    "report": state.report.dict(),
                    "updated_fields": [],
                    "is_finished": state.is_finished,
                }

            # run nodes sequentially
            await clean_chunk_node(state)
            await classify_chunk_node(state)
            await extract_chunk_node(state, llm=llm)
            res = await merge_chunk_node(state)

            # persist
            _save_state(session_id, state)

            return {
                "report": state.report.dict(),
                "updated_fields": [u.target_section for u in state.updated_fields],
                "is_finished": state.is_finished,
            }
        finally:
            _release_lock(session_id)

    async def finalize(self, session_id: str, llm=None) -> dict:
        """Finalize the session: if a doctor comment exists, preserve it.

        If no doctor comment exists, generate an AI comment using `llm.generate`.
        Returns the final report and marks `is_finished` True.
        """
        await _acquire_lock(session_id)
        try:
            state = _load_state(session_id)
            report = state.report

            # Determine if a doctor-provided comment exists
            has_comment = bool((report.comments or "").strip())
            if has_comment:
                # ensure source set to doctor if not already
                report.comment_source = report.comment_source or "doctor"
                state.is_finished = True
                _save_state(session_id, state)
                return {"report": state.report.dict(), "is_finished": True}

            # No doctor comment: generate AI comment with Groq.
            if llm is None:
                try:
                    from app.services.llm.provider import build_default_llm

                    llm = build_default_llm()
                except Exception:
                    try:
                        from app.services.llm.provider import DummyLLM

                        llm = DummyLLM()
                    except Exception:
                        llm = None

            ai_text = ""
            if llm is not None:
                # Build a prompt that asks the model to produce a concise clinician-facing comment
                prompt_parts = [
                    "You are an assistant that generates a concise clinician-facing comment based ONLY on the provided report fields.\n",
                    "Do NOT invent findings, do not modify any fields except to produce the comment text.\n",
                    "Return only the comment text (no JSON).\n\n",
                    "Report:\n",
                ]
                # Include the six fields explicitly
                rep = report.dict()
                for k in [
                    "patient",
                    "specimen",
                    "gross_description",
                    "microscopic_description",
                    "diagnosis",
                    "comments",
                ]:
                    prompt_parts.append(f"{k}: {rep.get(k) or ''}\n")

                prompt = "".join(prompt_parts)
                try:
                    ai_text = await llm.generate(prompt=prompt)
                    if isinstance(ai_text, dict):
                        # some providers may return structured response
                        ai_text = ai_text.get("text") or ai_text.get("content") or ""
                    ai_text = (ai_text or "").strip()
                except Exception:
                    ai_text = ""

            if ai_text:
                report.comments = ai_text
                report.comment_source = "ai"
            else:
                report.comments = report.comments or ""
                report.comment_source = report.comment_source or None

            state.is_finished = True
            _save_state(session_id, state)
            return {"report": state.report.dict(), "is_finished": True}
        finally:
            _release_lock(session_id)
