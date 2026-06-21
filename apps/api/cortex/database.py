"""Asynchronous SQLAlchemy lifecycle for PostgreSQL-backed services."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cortex.config import getSettings

settings = getSettings()
engine = create_async_engine(settings.databaseUrl, pool_pre_ping=True)
sessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def getDatabaseSession() -> AsyncIterator[AsyncSession]:
    """Yield a transaction-capable session and always close it afterward."""
    try:
        async with sessionFactory() as session:
            yield session
    except Exception as error:
        raise RuntimeError("database session failed") from error
    finally:
        pass
