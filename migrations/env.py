"""Alembic environment for Cortex's asynchronous PostgreSQL schema."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from cortex.config import getSettings
from cortex.models import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", getSettings().databaseUrl)
target_metadata = Base.metadata


def runMigrationsOffline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def doRunMigrations(connection: object) -> None:
    """Configure and execute migrations on an established connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def runMigrationsOnline() -> None:
    """Run migrations through an asynchronous SQLAlchemy engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(doRunMigrations)
    except Exception as error:
        raise RuntimeError("online migration execution failed") from error
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    runMigrationsOffline()
else:
    asyncio.run(runMigrationsOnline())
