# CLAUDE.md

## What this project is

**Pathology Voice Reporting (MVP)**: a clinical documentation assistant. A pathologist dictates naturally, in any order. The app streams the audio to speech-to-text, extracts structured updates from each transcript chunk with an LLM, validates them, merges them into one cumulative report, and shows the report filling in live in the UI. The clinician reviews it before finalizing.

It is **assistive only**. It structures what the clinician says and must never diagnose or invent clinical facts. See "Safety rules".

Design docs are the three PDFs in the repo root (`pathology_voice_reporting_*.pdf`). They are the source of truth for intent. `README.md` is partly out of date (see "Known gaps").

## Architecture

```
Browser mic --(base64 PCM16 16kHz over WS)--> FastAPI /ws/voice --> AssemblyAI streaming STT
   ^                                                                        |
   |                                                       final turn (end_of_turn)
   |                                                                        v
   +-- {"type":"state", report, updated_fields} <-- merge <-- extract (Groq LLM) <-- classify <-- clean
```

Core principle: `State(n+1) = Graph(State(n), TranscriptChunk(n))`.

- **Report sections are state, not sequential graph nodes.** Never force Patient → Specimen → Gross → Micro → Diagnosis order. A chunk can touch any section, several sections, or revisit an earlier one.
- The LLM returns **only deltas**, never a whole regenerated report: `{"updates":[{"target_section","operation":"append|replace","content"}]}`.
- `active_field` is a **hint, not a rule**. The LLM may override it.
- LLM output is **untrusted** until Pydantic validates it. Only validated updates are merged and sent to the UI. Never stream raw LLM tokens into clinical fields.
- Report fields: `patient`, `specimen`, `gross_description`, `microscopic_description`, `diagnosis`, `comments` (all plain strings), plus `comment_source` (`"doctor"` | `"ai"` | None).

### Comment rule (important)

- If the doctor dictates a comment, keep it and mark it `doctor`.
- If not, generate **one** AI comment **only at finalize** (on the client's `{"type":"stop"}`), from the final validated report. Mark it `ai`; the clinician must review it.
- Never generate comments per chunk. The comment prompt may use only the report fields and must not add findings.

## Layout

```
backend/app/
  main.py                    FastAPI app, CORS (*), /health, startup DB create_all
  core/config.py             pydantic-settings Settings (db_url, supabase_*, stt_provider)
  api/websocket/voice.py     /ws/voice: AssemblyAI v3 streaming, turn handling, English-only/confidence filters, stop -> finalize
  api/routes/reports.py      stub (GET /reports/ returns [])  -- note: not included in main.py
  graph/state.py             Report, FieldUpdate, ExtractionResponse, ExtractedChunk, LangGraphState (Pydantic)
  graph/workflow.py          Workflow.process_chunk / finalize; per-session JSON persistence + asyncio locks
  graph/routers.py           thin module-level process_chunk()/finalize() wrappers used by the WS handler
  graph/nodes/               clean -> classify (keyword hints) -> extract (LLM) -> merge; finalize.py is stale
  graph/sessions/*.json      per-session state files written at runtime (see gotchas)
  services/llm/provider.py   LLMBase, GroqLLM (OpenAI-compatible chat API via httpx), DummyLLM, build_default_llm()
  services/stt|streaming/    mostly stubs
  db/session.py, db/models/  async SQLAlchemy engine/models; alembic/ has migration 0001 (reports table)
  schemas/                   small Pydantic schemas (events, report, voice)
backend/tests/               pytest (test_workflow.py, test_llm_provider.py)
frontend/react-app/          Vite + React 18 (plain JS/JSX, no TS, no router, no state lib)
  src/hooks/useVoiceSession.js   WS client, mic capture, message handling (begin/turn/state/termination/error)
  src/lib/audio.js               PCM16 capture/encode
  src/components/                Header, RecordButton, TranscriptPanel, ReportPanel
```

### WebSocket protocol

- Client → server: `{"audio": "<base64 pcm16>"}` frames, then `{"type":"stop"}` to finalize.
- Server → client: `begin` (carries the AssemblyAI session id, which is also the graph session id), `turn` (partial/final transcript), `state` (`report`, `updated_fields`, `is_finished`), `termination`, `error`.
- Only **final** turns (`end_of_turn`) go through the graph. Partials are display-only. Duplicate final turns are skipped.

## Commands

```bash
# Backend (venv lives at backend/venv)
cd backend && source venv/bin/activate && pip install -r requirements.txt
python -m uvicorn app.main:app --reload          # http://localhost:8000, WS ws://localhost:8000/ws/voice
python -m pytest tests                           # run from backend/

# Frontend
cd frontend/react-app && npm install && npm run dev   # http://localhost:5173
npm run build
```

The frontend hard-codes the WS URL as `ws(s)://<hostname>:8000/ws/voice` (`useVoiceSession.js`).

### Environment (`.env`, never commit)

`ASSEMBLYAI_API_KEY` (required), `GROQ_API_KEY` (without it `build_default_llm()` falls back to `DummyLLM`), `GROQ_API_BASE`, `GROQ_MODEL` (default `openai/gpt-oss-20b`), `GROQ_MAX_RETRIES` (default 0, for streaming latency), `TURN_SILENCE_MS` (default 7000), `VAD_THRESHOLD` (default 0.7), `DATABASE_URL` / `SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_DB_URL`, `DB_SSL`.

## Conventions

- Python 3, async throughout (FastAPI, httpx, asyncio). Pydantic models are the contract; the code uses the v1-style API (`.dict()`, `.json()`, `parse_raw`, `@validator`), so match that or migrate deliberately.
- Keep it simple. Out of scope for the MVP: Docker, Redis/Celery/Kafka, microservices, RAG/vector DB, auth/multitenancy, audit/versioning, OS-wide dictation.
- LLM provider errors are typed (`LLMProviderError` > `LLMAPIError` > `LLMRateLimitError`, plus `LLMResponseError`). The WS handler turns rate limits into a friendly `error` event. Don't swallow API failures silently.
- Tests inject fake LLMs and monkeypatch `workflow._SESSIONS_DIR` / httpx. Follow that pattern and don't call real APIs in tests.
- `.editorconfig` is mostly cpp_* settings and irrelevant to this codebase.

## Safety rules (healthcare)

- Preserve the doctor's wording in extracted content. Don't paraphrase clinical findings, and don't infer facts that weren't spoken.
- AI-generated text must be labeled `comment_source="ai"` and never presented as clinician-authored.
- The clinician reviews and edits before finalizing. Don't add autonomous diagnosis or decision-making.

## Known gaps and gotchas

- **Session state is stored as JSON files** in `backend/app/graph/sessions/` (one per AssemblyAI session id), not in memory or the DB. Many are committed to git, including test fixtures. Runtime-generated ones show up as untracked; don't commit them. They may contain patient dictation, so consider gitignoring them.
- `graph/nodes/finalize.py` is stale. It imports a nonexistent `ReportState`, and the real finalize logic is `Workflow.finalize`.
- Persistence is unfinished. `repositories/report.py` references `SessionLocal` (session.py exports `AsyncSessionLocal`), `api/routes/reports.py` is a stub and isn't mounted, and README mentions an `app.db.supabase` module that doesn't exist. The PDF plan calls for Supabase save-on-finish plus a clinician review/edit/approve step, which is not fully built.
- The architecture PDFs describe LangGraph nodes and a Pydantic validate → repair/retry loop. The current code runs the nodes sequentially in plain Python (`workflow.py`) without a LangGraph graph or a repair loop. Validation happens when `FieldUpdate` objects are constructed. `langgraph` is in requirements but unused.
- The first PDF mentions MySQL; later docs and code use Supabase/Postgres. Postgres is the current direction.
- `Report.apply_update` returns `None` instead of `False` for empty content (works, but inconsistent). Append skips content already contained in the field.
- CORS is `*`, which is fine for dev only.
