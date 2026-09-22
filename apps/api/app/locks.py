"""PostgreSQL advisory locks — the only coordination primitive in the system.

There is no Redis, no Celery and no broker (§A0). Two things need coordinating
and both use a *session-level* advisory lock held on its own connection:

* the scheduler singleton, so exactly one scheduler process owns background
  work even while a deploy overlaps two containers (§A6.11);
* per-domain politeness, so the scheduler and the API never hit the same
  storefront at the same moment (§A6.2). The key builder lives here; its call
  sites arrive with the scraper in P3.

The key is computed **in Python** with blake2b, never with PostgreSQL's
``hashtext()``: that function is undocumented, 32-bit, and free to change
between major versions — a silent key collision would serialize two unrelated
domains, or worse, let two runs of one domain proceed.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import new_dedicated_engine

log = logging.getLogger(__name__)

#: Lock name of the scheduler singleton (§A6.11).
SCHEDULER_LOCK_NAME = "ct:scheduler"

#: Prefix of the per-domain politeness lock (§A6.2).
DOMAIN_LOCK_PREFIX = "ct:domain:"

_KEY_BYTES = 8  # pg advisory locks take one signed bigint


def advisory_key(name: str) -> int:
    """Map a lock name to the signed 64-bit integer PostgreSQL expects."""
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=_KEY_BYTES).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def domain_lock_name(domain: str) -> str:
    """Politeness lock name for a store domain (already normalized, lowercase)."""
    return f"{DOMAIN_LOCK_PREFIX}{domain}"


class AdvisoryLock:
    """A session-level advisory lock on a dedicated, unpooled connection.

    Session-level (``pg_try_advisory_lock``) rather than transaction-level: the
    scheduler holds its lock for the life of the process, across many
    transactions. The connection is unpooled so the lock can never be leaked to
    the next borrower of a pooled connection.

    Non-blocking by design — ``try_acquire()`` returns ``False`` instead of
    waiting, because every caller has something better to do than block: the
    scheduler retries in ten seconds, the API answers 409 ``store_busy``.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.key = advisory_key(name)
        self._engine: AsyncEngine | None = None
        self._conn: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._conn is not None

    async def try_acquire(self) -> bool:
        """Take the lock if it is free. Idempotent while held."""
        if self.held:
            return True
        engine = new_dedicated_engine()
        conn = await engine.connect()
        try:
            # AUTOCOMMIT: a session lock outlives transactions, and an idle
            # open transaction on a long-lived connection blocks VACUUM.
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            result = await conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
            )
            acquired = bool(result.scalar())
        except Exception:
            await _quietly_close(conn, engine)
            raise
        if not acquired:
            await _quietly_close(conn, engine)
            return False
        self._engine = engine
        self._conn = conn
        log.info("advisory lock acquired", extra={"lock": self.name, "lock_key": self.key})
        return True

    async def release(self) -> None:
        """Release the lock and close its connection. Safe to call twice."""
        conn, engine = self._conn, self._engine
        self._conn = self._engine = None
        if conn is None:
            return
        try:
            # Unlock explicitly before closing: closing alone would do it, but
            # only once the backend notices, and a deploy cannot wait for that.
            await conn.execute(text("SELECT pg_advisory_unlock_all()"))
        except Exception:  # shutdown path; closing the connection is what matters
            log.warning(
                "advisory unlock failed; closing connection",
                extra={"lock": self.name},
                exc_info=True,
            )
        finally:
            await _quietly_close(conn, engine)
        log.info("advisory lock released", extra={"lock": self.name})

    async def __aenter__(self) -> AdvisoryLock:
        if not await self.try_acquire():
            raise LockUnavailable(self.name)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.release()


class LockUnavailable(RuntimeError):
    """Raised when a lock used as a context manager is held elsewhere."""

    def __init__(self, name: str) -> None:
        super().__init__(f"advisory lock {name!r} is held by another session")
        self.name = name


async def _quietly_close(conn: AsyncConnection | None, engine: AsyncEngine | None) -> None:
    if conn is not None:
        try:
            await conn.close()
        except Exception:  # nothing useful left to do
            log.debug("connection close failed", exc_info=True)
    if engine is not None:
        try:
            await engine.dispose()
        except Exception:
            log.debug("engine dispose failed", exc_info=True)
