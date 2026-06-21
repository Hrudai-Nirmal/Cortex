"""Independent raw-content, trace, and audit retention operations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def redactExpiredRawContent(session: AsyncSession, now: datetime) -> int:
    """Remove raw strings while preserving structured trace diagnostics until trace expiry."""
    try:
        result = await session.execute(
            text(
                """
                UPDATE trace_memory
                SET raw_query = '[expired]', raw_response = NULL,
                    payload = payload - 'modelInputs' - 'retrievedText'
                WHERE raw_content_expires_at <= :now
                  AND raw_query <> '[expired]'
                """
            ),
            {"now": now},
        )
        await session.commit()
        return int(result.rowcount or 0)
    except Exception:
        await session.rollback()
        raise


async def purgeExpiredTraces(session: AsyncSession, now: datetime) -> int:
    """Delete trace rows while PostgreSQL nulls audit pointers through the foreign key."""
    try:
        result = await session.execute(
            text("DELETE FROM trace_memory WHERE expires_at <= :now"),
            {"now": now},
        )
        await session.commit()
        return int(result.rowcount or 0)
    except Exception:
        await session.rollback()
        raise
