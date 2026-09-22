"""Database engines.

Two flavours exist, and the difference matters:

``get_engine()``
    The pooled, process-wide engine. Request handlers and jobs use it.

``new_dedicated_engine()``
    A fresh engine with :class:`~sqlalchemy.pool.NullPool`, for a connection
    that must be held for the lifetime of a *session-level* advisory lock and
    must never return to a shared pool (§A6.2, §A6.11). A pooled connection
    handed back while holding a lock would leak the lock to the next borrower.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """The shared pooled engine, created on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,  # survives a database restart without a failed request
            pool_size=5,
            max_overflow=5,
            pool_recycle=1800,
            echo=False,
        )
    return _engine


async def dispose_engine() -> None:
    """Close the pooled engine (application shutdown, and between tests)."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def new_dedicated_engine() -> AsyncEngine:
    """An unpooled engine for one long-lived connection (advisory locks)."""
    settings = get_settings()
    return create_async_engine(settings.DATABASE_URL, poolclass=NullPool, echo=False)
