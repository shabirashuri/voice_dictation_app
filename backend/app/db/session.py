from __future__ import annotations

import os
import ssl
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
	create_async_engine,
	AsyncSession,
	async_sessionmaker,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings

# Determine DB URL: prefer `DATABASE_URL` env, then `supabase_db_url`, then `db_url`.
DATABASE_URL = (
	os.getenv("DATABASE_URL")
	or getattr(settings, "supabase_db_url", None)
	or getattr(settings, "db_url", None)
)

if not DATABASE_URL:
	raise RuntimeError("DATABASE URL not configured. Set DATABASE_URL or supabase_db_url or settings.db_url")

# Ensure async driver schemes: asyncpg for Postgres, aiosqlite for SQLite.
if DATABASE_URL.startswith("postgres://"):
	DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
	DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("sqlite://"):
	DATABASE_URL = DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://", 1)

IS_POSTGRES = DATABASE_URL.startswith("postgresql+asyncpg://")

# Optional SSL context (opt-in via DB_SSL env var)
ssl_context: Optional[ssl.SSLContext] = None
if os.getenv("DB_SSL", "0") in ("1", "true", "True"):
	ssl_context = ssl.create_default_context()

# Build connect args for the async driver. Keep statement cache disabled for PgBouncer.
connect_args: dict = {}
engine_url = DATABASE_URL
if IS_POSTGRES:
	connect_args["statement_cache_size"] = 0
	if ssl_context is not None:
		connect_args["ssl"] = ssl_context
	engine_url = f"{DATABASE_URL}{'&' if '?' in DATABASE_URL else '?'}prepared_statement_cache_size=0"

# Create async engine with NullPool for short-lived connections (suitable for serverless/PgBouncer)
engine = create_async_engine(
	engine_url,
	echo=False,
	pool_pre_ping=True,
	poolclass=NullPool,
	connect_args=connect_args,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
	bind=engine,
	class_=AsyncSession,
	expire_on_commit=False,
	autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
	"""FastAPI dependency that yields an `AsyncSession` and closes it after use."""
	async with AsyncSessionLocal() as session:
		yield session

