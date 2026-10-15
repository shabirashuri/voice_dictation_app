# CLAUDE.md

## What this project is

**Pathology Voice Reporting (MVP)** — a clinical documentation assistant. Doctors sign in (own JWT auth) and create one **case per patient**; each case has exactly one report, and a doctor sees only their own cases. Within a case the pathologist dictates naturally (any order); audio streams to speech-to-text, each transcript chunk is turned into validated structured updates by an LLM, merged into one cumulative report, and shown live. After Stop, the clinician reviews/edits/approves in the UI and the report is saved to Postgres (Supabase).

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
     -> UI review/edit/approve -> POST /cases/{id}/report -> Postgres
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
  api/websocket/voice.py     /ws/voice: first message must be {"type":"auth",token,case_id}; AssemblyAI v3, English/confidence filters, stop->finalize, review phase, idle timeout, coded errors, discards session on close
  api/routes/auth.py         /auth/signup, /auth/login, /auth/me
  api/routes/cases.py        /cases CRUD-lite + /cases/{id}/report (owner-scoped; others' cases are 404)
  api/deps.py                get_current_user (Bearer JWT)
  core/security.py           bcrypt hashing, HS256 JWT (JWT_SECRET >= 32 chars)
  graph/graph.py             builds + compiles chunk_graph and finish_graph (no `from __future__ import annotations` here)
  graph/validation_router.py routing fns, MAX_REPAIR_ATTEMPTS, RECENT_CONTEXT_SIZE
  graph/nodes/               clean, classify, extract (raw output), validate_update, repair/reject, merge, finalize_report, generate_comment
  graph/state.py             Report, FieldUpdate, ExtractionResponse, LangGraphState (incl. graph working fields)
  graph/workflow.py          Workflow.process_chunk / finalize over the graphs; per-session lock
  graph/routers.py           module-level process_chunk()/finalize() used by the WS handler and tests
  prompts/                   extraction + repair note, comment prompt
  services/llm/provider.py   GroqLLM (OpenAI-compatible, httpx), DummyLLM, build_default_llm(), typed errors
  services/streaming/        StreamingManager: in-memory session state (deep copies), asyncio locks, TTL sweep
  db/session.py              async engine (asyncpg for Postgres, aiosqlite for SQLite), get_db, get_session_factory
  db/base.py                 shared declarative Base + Id type
  db/models/                 user.py (User), report.py (Case, Report; constraint names match the migrations)
  repositories/              user, case (owner-scoped get/list, generated case_number), report (one per case/session)
  schemas/                   auth, case, report (API contract, validation)
backend/alembic/versions/    0001 reports, 0002 cases + report fields, 0003 users + case ownership (DB is at 0003)
backend/tests/               pytest suites (see Commands)
frontend/react-app/src/
  App.jsx                    auth gate; signed-in layout (topbar, Sidebar, CaseWorkspace keyed by case)
  lib/api.js                 apiFetch (Bearer token, server error messages), API/WS base URLs
  hooks/useAuth.js           token in localStorage (pvr.token), /auth/me check, login/signup/signOut
  hooks/useCases.js          case list, selected case detail, create, refresh after save
  hooks/useVoiceSession.js   dictation for one case: phases, WS auth handshake, draft/review, save to /cases/{id}/report
  components/                AuthScreen, Sidebar, CaseWorkspace (dictation or read-only reported view), RecordButton, ReportPanel, TranscriptPanel, ReviewBar, ErrorBanner
  test/fakes.js              FakeWebSocket, AudioContext/getUserMedia/fetch stubs for Vitest
```

Frontend phases: `idle → connecting → recording → finalizing → review → saving → saved`. Fields are read-only except in `review`.

## Commands

```bash
cd backend && source venv/bin/activate
python -m uvicorn app.main:app --reload       # :8000
python -m pytest tests                        # 76 tests, no external calls (conftest: SQLite app, JWT_SECRET, BCRYPT_ROUNDS=4)
alembic upgrade head                          # reads backend/.env (DATABASE_URL)
alembic upgrade <from>:head --sql             # review migration SQL before applying

cd frontend/react-app
npm run dev                                   # :5173
npm test                                      # Vitest, 27 tests (test/fakes.js: FakeWebSocket, routeFetch)
npm run build
```

## Conventions

- Python async throughout. `state.py` models still use the Pydantic v1-style API (`.dict()`, `@validator`); `schemas/report.py` uses v2. Match the file you're in.
- LangGraph nodes take the state model and return **only the fields they own** (wrappers in `graph.py` run helpers on a deep copy). Don't mutate the incoming state.
- Schema changes go through a new Alembic migration; never `create_all` against the real DB. Name constraints explicitly and keep model and migration names identical.
- Errors sent to the client always carry a `code`; the UI maps codes to titles in `ErrorBanner.jsx`.
- Tests inject fake LLMs / a fake transcriber (`monkeypatch` `build_default_llm`, `voice.AsyncRealTimeTranscriber`) and use SQLite via `dependency_overrides[get_db]`. Never call real AssemblyAI/Groq/Supabase from tests.
- Every case query is scoped by `owner_id`; return 404 (not 403) for other doctors' cases.
- Keep it simple. Out of scope: Docker, Redis/Celery/Kafka, microservices, RAG, roles/orgs, password reset, audit/versioning, OS-wide dictation.
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
- Approved reports can't be edited (no PUT): that needs audit/versioning, which is out of scope.
- The JWT is stored in localStorage (XSS-readable) and there's no login rate limiting or token revocation; fine for the MVP, not for production.
- uvicorn `--reload` doesn't watch `.env`; restart after changing it.
- `npm audit` flags dev-only tooling (vite 5.0.0's esbuild, vitest internals). Fixing it needs major version upgrades.
