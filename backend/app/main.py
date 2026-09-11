"""Entry point for the backend FastAPI app (placeholder).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
import os

# Load `.env` from the project root so environment variables like
# ASSEMBLYAI_API_KEY are available to the running process.
env_path = find_dotenv(filename=".env")
if env_path:
    load_dotenv(env_path)

from app.api.websocket import voice as voice_ws
from app.db import session as db_session
import logging
from sqlalchemy import create_engine
import os

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def _startup():
    logger = logging.getLogger("uvicorn")
    try:
        # If a DATABASE_URL is configured, attempt to create missing tables
        # using the async engine provided by `app.db.session`.
        try:
            from app.db.models.report import Base as ReportBase

            engine = db_session.engine

            async def _create_if_needed():
                async with engine.begin() as conn:
                    await conn.run_sync(ReportBase.metadata.create_all)

            import asyncio

            asyncio.create_task(_create_if_needed())
            logger.info("Triggered async DB table creation (if needed)")
        except Exception:
            logger.exception("Failed to initialize DB tables on startup")
    except Exception:
        logger.exception("Unexpected error during startup Supabase init")
