# Pathology Voice Reporting — MVP

A clinical documentation assistant. Doctors sign in and create a **case** for each patient; within a case the doctor dictates naturally, in any order; the app streams speech to text, turns each transcript chunk into validated updates to a structured report, shows the report filling in live, and — after the clinician reviews, edits and approves it — saves it to Postgres (Supabase).

> **Assistive only.** The system structures what the clinician says. It does not diagnose. Any AI-generated comment is labelled as such and must be reviewed before the report can be approved.

## How it works

```
Browser mic ──WS──> FastAPI /ws/voice ──> AssemblyAI streaming STT
                                              │ final turn
                                              ▼
              chunk graph (LangGraph): clean → classify → extract (LLM) → validate ──> merge
                                                               ▲            │ invalid
                                                               └─ repair ◄──┘ (1 retry, then reject)
UI ◄── live report updates ───────────────────────────────────────────────────┘

Stop ──> finish graph: final validation → keep clinician comment | generate one AI comment
     ──> clinician reviews & edits in the UI ──> Approve ──> POST /cases/{id}/report ──> Postgres
```

- **Sections are state, not steps.** Any chunk can update any field, several fields, or a field dictated earlier. The LLM returns only changes (`append` / `replace`), never a regenerated report.
- **Nothing unvalidated reaches the report.** LLM output is checked with Pydantic; an invalid response gets one repair attempt, then the chunk is rejected and the UI is told.
- **Output must match the dictation.** Each update's numbers, units, laterality and negations must appear in what was said (`backend/app/graph/grounding.py`); an unsupported update gets the same repair-then-reject treatment. The AI comment may only restate the report; an unsupported comment is withheld for the clinician to write.
- **Comments:** a dictated comment is kept as the clinician's. If there is none, one AI comment is generated at Stop — never per chunk — and must be reviewed before approving.
- **Live state stays in memory.** Nothing is written to disk during dictation; only the approved report is stored.

Report fields: `patient`, `specimen`, `gross_description`, `microscopic_description`, `diagnosis`, `comments` (+ `comment_source`: `doctor` | `ai`).

## Quick start

**Backend** (Python 3.10+)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ASSEMBLYAI_API_KEY, GROQ_API_KEY, DATABASE_URL
alembic upgrade head          # create/upgrade the database schema
python -m uvicorn app.main:app --reload    # http://localhost:8000
```

**Frontend**

```bash
cd frontend/react-app
npm install
npm run dev                   # http://localhost:5173
```

Sign up (or sign in), click **+ New case** and enter the patient's name (MRN optional). With the case selected, click **Start session**, dictate, click **Stop session**, review and edit the fields, then **Approve & save**. The case is then marked *Reported* and its report is read-only.

Each doctor sees only their own cases, and each case has exactly one report.

The frontend talks to port 8000 on the page's host by default; override with `VITE_WS_URL` and `VITE_API_URL`.

## Configuration (`backend/.env`)

See [backend/.env.example](backend/.env.example). Never commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `ASSEMBLYAI_API_KEY` | — | Required. Streaming speech-to-text. |
| `GROQ_API_KEY` | — | LLM for extraction and the AI comment. Without it a dummy LLM is used (no extraction). |
| `GROQ_API_BASE` / `GROQ_MODEL` | `https://api.groq.com/openai` / `openai/gpt-oss-20b` | LLM endpoint and model. |
| `GROQ_MAX_RETRIES` | `0` | Rate-limit retries (kept at 0 for streaming latency). |
| `DATABASE_URL` | — | Postgres connection string (Supabase). Falls back to `SUPABASE_DB_URL`. |
| `JWT_SECRET` | — | Required. Signs login tokens; at least 32 random characters. |
| `JWT_EXPIRE_MINUTES` | `720` | How long a login lasts. |
| `BCRYPT_ROUNDS` | `12` | Password hashing cost. |
| `DB_SSL` | `0` | Set to `1` to force SSL for the database connection. |
| `TURN_SILENCE_MS` | `7000` | Silence before AssemblyAI ends a turn. Raise it if sentences get split. |
| `VAD_THRESHOLD` | `0.7` | Voice-activity threshold (0–1); higher rejects more background noise. |
| `WS_IDLE_TIMEOUT_SECONDS` | `900` | Close a WebSocket with no client messages for this long. |
| `STOP_DRAIN_TIMEOUT_SECONDS` | `30` | On Stop, how long to wait for queued dictation to finish before finalizing without the rest. |
| `SESSION_TTL_SECONDS` | `3600` | Drop abandoned in-memory session state after this long. |

## API

All endpoints except `/auth/signup`, `/auth/login` and `/health` need `Authorization: Bearer <access_token>`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/signup` | `{email, full_name, password}` (password ≥ 8 chars) → `201 {access_token, token_type, expires_in, user}`; `409` if the email exists. |
| `POST` | `/auth/login` | `{email, password}` → `{access_token, ...}`; `401` on wrong email or password. |
| `GET` | `/auth/me` | The signed-in doctor. |
| `POST` | `/cases` | `{patient_name, patient_mrn?}` → `201` case with a generated `case_number` (`C-<year>-<id>`). |
| `GET` | `/cases` | The doctor's cases, newest first, each with `status` `open` or `reported`. |
| `GET` | `/cases/{id}` | One case with its `report` (or `null`). Other doctors' cases return `404`. |
| `POST` | `/cases/{id}/report` | Save the approved report: `{session_id, report: {six fields}, comment_source}`. `409` if the case already has a report or the dictation was already saved; `422` if invalid; `503` if the database is unreachable. |
| `GET` | `/cases/{id}/report` | The case's saved report. |
| `WS` | `/ws/voice` | Dictation for one case (protocol below). |
| `GET` | `/health` | Liveness check. |

`comment_source` is required whenever `comments` is non-empty; an entirely empty report is rejected.

**WebSocket messages**

- Client → server: first `{"type": "auth", "token": "<access_token>", "case_id": 1}` (the server closes the socket with an `auth` error if the token is invalid, the case isn't yours, or it already has a report), then `{"audio": "<base64 PCM16 16 kHz>"}`, `{"type": "stop"}` (finish dictation), `{"type": "close"}` (end the session).
- Client → server: `{"type": "retry", "turn_id": 4}` re-runs a failed final turn.
- Server → client: `begin` (session id), `turn` (partial transcript; or a final turn with `turn_id`), `chunk_status` (`turn_id` plus `status`: `applied` | `nothing` | `failed` | `ignored`, and a `code` for failed/ignored turns), `state` (`report`, `updated_fields`, `is_finished`, `awaiting_review`), `termination`, and `error` for session-level problems with a `code`: `auth`, `stt`, `processing`, `finalize`, `timeout`, `internal`.

Every final turn gets exactly one `chunk_status`, so nothing is dropped silently. Transient LLM failures (rate limit, timeout, provider error) are retried automatically with backoff (1s, 3s, 8s) before a turn is marked `failed`. A failed turn can be retried from the transcript; retries after the report is under review are refused (`ignored`, `under_review`).

The case's patient name (and MRN) pre-fills the report's Patient field. After `stop` the socket stays open for review; saving goes over HTTP.

## Database

Postgres via async SQLAlchemy (`backend/app/db/session.py`); the schema is managed only by Alembic (`backend/alembic/versions/`). Tables:

- `users` — doctors: `email` (unique, lower-cased), `full_name`, bcrypt `password_hash`.
- `cases` — `case_number` (unique, generated), `owner_id` → `users`, `patient_name`, `patient_mrn`.
- `reports` — `case_id` (unique: one report per case), the six fields, `comment_source`, `session_id` (unique: one report per dictation), `status` (`draft` | `approved`), `created_at`, `updated_at`, `approved_at`.

IDs and case numbers may have gaps (Postgres does not reuse sequence numbers after a rollback).

## Tests

```bash
cd backend && python -m pytest tests          # auth, cases API, graph, finish path, WebSocket (SQLite), LLM provider
cd frontend/react-app && npm test             # sign-in, cases sidebar, review flow (Vitest + jsdom)
```

Tests use fake LLMs, a fake AssemblyAI transcriber and an in-memory SQLite database — no external services are called.

## Troubleshooting

- **WebSocket 403 / CORS errors:** check the backend is running and `VITE_WS_URL` / `VITE_API_URL` point at it.
- **AssemblyAI authentication errors:** check `ASSEMBLYAI_API_KEY`.
- **"Part of the dictation was not applied":** the LLM output for that chunk failed validation twice; the report was left unchanged. Repeat the sentence.
- **"Report not saved":** the message says why (database unreachable, already saved, invalid). The draft is kept; fix and approve again.
- **Sentences split across turns:** increase `TURN_SILENCE_MS`.
