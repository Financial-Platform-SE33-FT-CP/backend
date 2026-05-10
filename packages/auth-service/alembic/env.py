"""Alembic environment configuration for async migrations."""

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from auth_service.modules.auth.infrastructure.models import Base

# Alembic Config object
config = context.config

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _database_url() -> str:
    """Prefer DATABASE_URL from backend/.env, fall back to alembic.ini."""
    load_dotenv(_REPO_ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    ini_url = config.get_main_option("sqlalchemy.url")
    if not ini_url:
        msg = "Set DATABASE_URL or sqlalchemy.url in alembic.ini"
        raise RuntimeError(msg)
    return ini_url


# Set up logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for auto-detection
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine.
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations in 'online' mode with a connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    url = _database_url()
    engine = create_async_engine(url)

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
