# Pathology Voice Reporting — MVP

A clinical documentation assistant. A pathologist dictates naturally, in any order; the app streams speech to text, turns each transcript chunk into validated updates to a structured report, shows the report filling in live, and — after the clinician reviews, edits and approves it — saves it to Postgres (Supabase).

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
     ──> clinician reviews & edits in the UI ──> Approve ──> POST /reports ──> Postgres
```

- **Sections are state, not steps.** Any chunk can update any field, several fields, or a field dictated earlier. The LLM returns only changes (`append` / `replace`), never a regenerated report.
- **Nothing unvalidated reaches the report.** LLM output is checked with Pydantic; an invalid response gets one repair attempt, then the chunk is rejected and the UI is told.
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

Click **Start session**, dictate, click **Stop session**, review and edit the fields, then **Approve & save**.

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
| `DB_SSL` | `0` | Set to `1` to force SSL for the database connection. |
| `TURN_SILENCE_MS` | `7000` | Silence before AssemblyAI ends a turn. Raise it if sentences get split. |
| `VAD_THRESHOLD` | `0.7` | Voice-activity threshold (0–1); higher rejects more background noise. |
| `WS_IDLE_TIMEOUT_SECONDS` | `900` | Close a WebSocket with no client messages for this long. |
| `SESSION_TTL_SECONDS` | `3600` | Drop abandoned in-memory session state after this long. |

## API

| Method | Path | Description |
|---|---|---|
| `WS` | `/ws/voice` | Dictation session (protocol below). |
| `POST` | `/reports` | Save an approved report. `201` with the report; `409` if that dictation session was already saved; `422` if invalid; `503` if the database is unreachable. |
| `GET` | `/reports?limit=&offset=` | List reports, newest first. |
| `GET` | `/reports/{id}` | One report. |
| `GET` | `/health` | Liveness check. |

`POST /reports` body:

```json
{
  "session_id": "assemblyai-session-id",
  "case_number": "S26-0001",
  "report": { "patient": "", "specimen": "", "gross_description": "", "microscopic_description": "", "diagnosis": "", "comments": "" },
  "comment_source": "doctor"
}
```

`comment_source` is required whenever `comments` is non-empty; an entirely empty report is rejected. `case_number` is optional (the UI does not send it yet).

**WebSocket messages**

- Client → server: `{"audio": "<base64 PCM16 16 kHz>"}`, `{"type": "stop"}` (finish dictation), `{"type": "close"}` (end the session).
- Server → client: `begin` (session id), `turn` (partial/final transcript), `state` (`report`, `updated_fields`, `is_finished`, `awaiting_review`), `termination`, and `error` with a `code`: `stt`, `llm_rate_limit`, `validation`, `processing`, `finalize`, `timeout`, `internal`.

After `stop` the socket stays open for review; saving goes over HTTP.

## Database

Postgres via async SQLAlchemy (`backend/app/db/session.py`); the schema is managed only by Alembic (`backend/alembic/versions/`). Tables:

- `cases` — `case_number` (unique).
- `reports` — the six fields, `comment_source`, `session_id` (unique: one report per dictation), `case_id`, `status` (`draft` | `approved`), `created_at`, `updated_at`, `approved_at`.

Report IDs may have gaps (Postgres does not reuse sequence numbers after a rollback). Use `case_number` for human-facing numbering.

## Tests

```bash
cd backend && python -m pytest tests          # graph, finish path, WebSocket, reports API (SQLite), LLM provider
cd frontend/react-app && npm test             # review flow in the hook and App (Vitest + jsdom)
```

Tests use fake LLMs, a fake AssemblyAI transcriber and an in-memory SQLite database — no external services are called.

## Troubleshooting

- **WebSocket 403 / CORS errors:** check the backend is running and `VITE_WS_URL` / `VITE_API_URL` point at it.
- **AssemblyAI authentication errors:** check `ASSEMBLYAI_API_KEY`.
- **"Part of the dictation was not applied":** the LLM output for that chunk failed validation twice; the report was left unchanged. Repeat the sentence.
- **"Report not saved":** the message says why (database unreachable, already saved, invalid). The draft is kept; fix and approve again.
- **Sentences split across turns:** increase `TURN_SILENCE_MS`.
