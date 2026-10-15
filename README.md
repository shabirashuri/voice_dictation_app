# Pathology Voice Reporting — MVP

Simple prototype that converts clinician speech into a structured pathology report using streaming STT, an LLM extraction step, and Pydantic validation. The system processes each AssemblyAI transcript chunk, asks an LLM to produce structured updates for target report fields, validates them, merges into persistent report state, and streams validated updates to the UI in real time.

**Architecture**

- **STT (AssemblyAI)**: Streaming speech-to-text provides transcript chunks after pauses.
- **FastAPI WebSocket**: Receives client audio and proxies/coordinates streaming events to LangGraph/workflow.
- **LangGraph + LLM**: Orchestrates chunk processing: understand chunk → determine target fields → produce structured updates.
- **Pydantic**: Validates structured updates before they are merged into the report state.
- **Frontend (React)**: Shows live, validated updates (finalized updates appended, partial updates shown inline).

**Core behavior (simple)**

- Clinician speaks naturally in any order.
- Each transcript chunk is processed against the current report state and recent context.
- The LLM returns structured `updates` that target one or more report fields (append/update).
- Only validated updates are merged and sent to the frontend.

**Where code lives**

- Backend: `backend/` (FastAPI app). See [backend/app/main.py](backend/app/main.py#L1).
- Frontend: `frontend/react-app/` (Vite + React). See [frontend/react-app/package.json](frontend/react-app/package.json#L1).
- Requirements: [backend/requirements.txt](backend/requirements.txt#L1).

**Environment variables**

- `ASSEMBLYAI_API_KEY` — required for real-time STT (put in `.env` at repository root or export in your shell).
- `TURN_SILENCE_MS` — optional, milliseconds to wait for silence before finalizing a turn (defaults to `7000`).
- `VAD_THRESHOLD` — optional, AssemblyAI voice-activity threshold from `0` to `1`; higher values reject more background noise (defaults to `0.7`).
- `GROQ_API_KEY` — required for the Groq LLM provider; keep it in the environment and never commit it.
- `GROQ_API_BASE` — optional Groq API base URL (defaults to `https://api.groq.com/openai`).
- `GROQ_MODEL` — optional Groq model name (defaults to `openai/gpt-oss-20b`).
- `GROQ_MAX_RETRIES` — optional number of rate-limit retries (defaults to `0` for low-latency streaming).
- `SUPABASE_URL` — your Supabase project URL (set in `.env` as SUPABASE_URL).
- `SUPABASE_KEY` — your Supabase service key (set in `.env` as SUPABASE_KEY). Keep this secret.

Quick start (recommended for development)

1. Backend (Python)

```bash
cd backend
python -m venv .venv               # create a venv (optional but recommended)
source .venv/bin/activate          # macOS / Linux
pip install -r requirements.txt
# copy .env.example -> .env and set ASSEMBLYAI_API_KEY and optional TURN_SILENCE_MS
python -m uvicorn app.main:app --reload
```

2. Frontend (React / Vite)

```bash
cd frontend/react-app
npm install
npm run dev
# open http://localhost:5173 in your browser
```

3. Connect frontend to backend

- Use the WebSocket URL `ws://localhost:8000/ws/voice` in the frontend UI input and click Connect.

Notes and tips

- The frontend shows a single live partial line for the active turn and appends finalized turns below it.
- If sentences are split across turns, increase `TURN_SILENCE_MS` in your environment to allow longer silence before finalizing.
- The repo `.gitignore` excludes local venvs, `node_modules`, build artifacts, and `.env` files — ensure you do not commit secrets.

Database / Supabase

This project includes a minimal Supabase client wrapper used by the backend. Create a `reports` table in your Supabase project with a simple schema like:

```sql
create table reports (
	id uuid primary key default gen_random_uuid(),
	case_number text,
	patient_name text,
	specimen jsonb,
	microscopic_description text,
	diagnosis text,
	comments text,
	created_at timestamptz default now()
);
```

The backend connects to Postgres through `DATABASE_URL` (or `SUPABASE_DB_URL`) using the async SQLAlchemy engine in `backend/app/db/session.py`. Schema changes are managed with Alembic (`cd backend && alembic upgrade head`).

Security & safety

- This prototype is an assistive tool. All AI-generated content must be reviewed by a clinician before finalization. Do not use this system as an autonomous diagnostic product.

Troubleshooting

- If you get CORS or WebSocket 403 errors, confirm the backend is running and that the frontend WebSocket URL matches the backend host/port.
- If AssemblyAI returns authentication errors, verify `ASSEMBLYAI_API_KEY` is set and valid.

License / next steps

- This README is intentionally brief. Next steps: add tests, persist reports to a database, and replace the LLM stub with a production model + LangGraph orchestration.
  thanks
