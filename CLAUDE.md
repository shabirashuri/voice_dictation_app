# CLAUDE.md

## What this project is

**Pathology Voice Reporting (MVP)** — a clinical documentation assistant. A pathologist dictates naturally (any order); audio streams to speech-to-text, each transcript chunk is turned into validated structured updates by an LLM, merged into one cumulative report, and shown live. After Stop, the clinician reviews/edits/approves in the UI and the report is saved to Postgres (Supabase).

It is **assistive only** — it structures what the clinician says; it must never diagnose or invent clinical facts. See "Safety rules".

Design docs: the three PDFs in the repo root (`pathology_voice_reporting_*.pdf`) are the source of truth for intent. `README.md` documents setup, config, API and the WebSocket protocol — don't duplicate it here.

## Architecture

```
Browser mic --(WS /ws/voice)--> FastAPI --> AssemblyAI streaming STT
                                      | final turn
                                      v
chunk_graph:  clean -> classify -> extract (LLM) -> validate --ok--> merge -> state event
                                        ^              | invalid
                                        +-- repair <---+ (MAX_REPAIR_ATTEMPTS=1) then reject -> error{code:validation}
stop -> finish_graph: final_validate -> keep_comment | generate_comment (once) -> mark_review (awaiting_review)
     -> UI review/edit/approve -> POST /reports -> Postgres
```

Core principle: `State(n+1) = Graph(State(n), TranscriptChunk(n))`.

- **Report sections are state, not sequential graph nodes.** Never force section order. A chunk can touch any/many sections.
- LLM returns **deltas only**: `{"updates":[{"target_section","operation":"append|replace","content"}]}`.
- `active_field` and `detected_fields` are **hints**, never routing rules.
- LLM output is **untrusted** until `validate_update` passes. Only validated updates merge; never stream raw LLM tokens into fields.
- Fields: `patient`, `specimen`, `gross_description`, `microscopic_description`, `diagnosis`, `comments` (plain strings, by decision) + `comment_source` (`doctor` | `ai` | None).

### Comment rule (important)

- Dictated comment → kept, `comment_source="doctor"`.
- None → **one** AI comment generated **only in the finish graph** (on `{"type":"stop"}`), `comment_source="ai"`. Re-finalizing must not generate another. Never per chunk.
- An AI comment must be acknowledged (checkbox or edit) before approve — enforced in `useVoiceSession.approveAndSave` *and* the UI. Editing it keeps it labelled `ai`.

## Layout

```
backend/app/
  main.py                    FastAPI app: CORS(*), /health, voice WS router, reports router. No create_all.
  api/websocket/voice.py     /ws/voice: AssemblyAI v3, English/confidence filters, stop->finalize, review phase, idle timeout, coded errors, discards session on close
  api/routes/reports.py      POST/GET /reports, GET /reports/{id}
  graph/graph.py             builds + compiles chunk_graph and finish_graph (no `from __future__ import annotations` here)
  graph/validation_router.py routing fns, MAX_REPAIR_ATTEMPTS, RECENT_CONTEXT_SIZE
  graph/nodes/               clean, classify, extract (raw output), validate_update, repair/reject, merge, finalize_report, generate_comment
  graph/state.py             Report, FieldUpdate, ExtractionResponse, LangGraphState (incl. graph working fields)
  graph/workflow.py          Workflow.process_chunk / finalize over the graphs; per-session lock
  graph/routers.py           module-level process_chunk()/finalize() used by the WS handler and tests
  prompts/                   extraction + repair note, comment prompt
  services/llm/provider.py   GroqLLM (OpenAI-compatible, httpx), DummyLLM, build_default_llm(), typed errors
  services/streaming/        StreamingManager: in-memory session state (deep copies), asyncio locks, TTL sweep
  db/session.py              async engine (asyncpg for Postgres, aiosqlite for SQLite), get_db dependency
  db/models/report.py        Case, Report ORM models (constraint names match the migrations)
  repositories/report.py     create_approved_report (DuplicateSessionError), get_report, list_reports
  schemas/report.py          ReportCreate / ReportOut / ReportList (API contract, validation)
backend/alembic/versions/    0001 reports table, 0002 cases + report fields (DB is at 0002)
backend/tests/               pytest suites (see Commands)
frontend/react-app/src/
  hooks/useVoiceSession.js   session phases, WS client, draft/review state, save, errors
  components/                Header, RecordButton, ReportPanel, TranscriptPanel, ReviewBar, ErrorBanner
  test/fakes.js              FakeWebSocket, AudioContext/getUserMedia/fetch stubs for Vitest
```

Frontend phases: `idle → connecting → recording → finalizing → review → saving → saved`. Fields are read-only except in `review`.

## Commands

```bash
cd backend && source venv/bin/activate
python -m uvicorn app.main:app --reload       # :8000
python -m pytest tests                        # 55 tests, no external calls
alembic upgrade head                          # reads backend/.env (DATABASE_URL)
alembic upgrade <from>:head --sql             # review migration SQL before applying

cd frontend/react-app
npm run dev                                   # :5173
npm test                                      # Vitest, 18 tests
npm run build
```

## Conventions

- Python async throughout. `state.py` models still use the Pydantic v1-style API (`.dict()`, `@validator`); `schemas/report.py` uses v2. Match the file you're in.
- LangGraph nodes take the state model and return **only the fields they own** (wrappers in `graph.py` run helpers on a deep copy). Don't mutate the incoming state.
- Schema changes go through a new Alembic migration; never `create_all` against the real DB. Name constraints explicitly and keep model and migration names identical.
- Errors sent to the client always carry a `code`; the UI maps codes to titles in `ErrorBanner.jsx`.
- Tests inject fake LLMs / a fake transcriber (`monkeypatch` `build_default_llm`, `voice.AsyncRealTimeTranscriber`) and use SQLite via `dependency_overrides[get_db]`. Never call real AssemblyAI/Groq/Supabase from tests.
- Keep it simple. Out of scope: Docker, Redis/Celery/Kafka, microservices, RAG, auth/multitenancy, audit/versioning, OS-wide dictation.
- `.editorconfig` is unrelated cpp settings and is not tracked.

## Safety rules (healthcare)

- Preserve the doctor's wording; never infer facts that weren't spoken.
- AI text is always `comment_source="ai"`, never presented as clinician-authored, and must be reviewed before approval.
- A report is stored only after explicit clinician approval. No autonomous diagnosis.

## Gotchas

- A running `uvicorn --reload` reloads on every save mid-edit. Keep anything that touches the real DB out of import/startup paths.
- Chunks that arrive after finalize are ignored (`awaiting_review`), so a late final turn can be dropped. Whether `transcriber.disconnect(terminate=True)` flushes the last turn before finalize is unverified against live AssemblyAI.
- Session state lives in process memory: a server restart mid-dictation loses the draft, and it doesn't work across multiple workers.
- Report IDs can have gaps (sequence numbers aren't reused). `case_number` is the human-facing identifier; the UI doesn't send it yet.
- There's no `PUT /reports/{id}`: editing an approved report needs audit/versioning, which is out of scope.
- `npm audit` flags dev-only tooling (vite 5.0.0's esbuild, vitest internals). Fixing it needs major version upgrades.
