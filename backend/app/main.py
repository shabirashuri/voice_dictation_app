"""Entry point for the backend FastAPI app.

The database schema is managed by Alembic (`alembic upgrade head`); the app
does not create tables on startup.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv

# Load `.env` from the project root so environment variables like
# ASSEMBLYAI_API_KEY are available to the running process.
env_path = find_dotenv(filename=".env")
if env_path:
    load_dotenv(env_path)

from app.api.routes import reports as reports_routes
from app.api.websocket import voice as voice_ws

app = FastAPI()

# Development: allow all origins for websocket and browser clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_ws.router)
app.include_router(reports_routes.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
