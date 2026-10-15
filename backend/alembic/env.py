from __future__ import with_statement

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
try:
    from app.db.models.report import Base as ReportBase  # also registers User
    target_metadata = ReportBase.metadata
except Exception:
    target_metadata = None


# Load backend/.env so `alembic` works without exporting variables first.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass


def get_url():
    """Same precedence as app/db/session.py: DATABASE_URL, then SUPABASE_DB_URL.

    Alembic runs synchronously (psycopg2), so an async driver suffix is removed.
    """
    url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or config.get_main_option("sqlalchemy.url")
    )
    if not url:
        raise RuntimeError("Set DATABASE_URL (or SUPABASE_DB_URL) to run migrations")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1).replace("postgres://", "postgresql://", 1)


def run_migrations_offline():
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
