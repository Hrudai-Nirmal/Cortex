"""Database configuration helpers keep runtime URLs authoritative across processes."""

from __future__ import annotations

from alembic.config import Config

from cortex.config import Settings


def applyAlembicDatabaseUrl(config: Config, settings: Settings) -> None:
    """Force Alembic to use the validated runtime database URL instead of ini defaults."""
    if config is None:
        raise ValueError("config is required")
    if settings is None:
        raise ValueError("settings are required")
    config.set_main_option("sqlalchemy.url", settings.databaseUrl)
