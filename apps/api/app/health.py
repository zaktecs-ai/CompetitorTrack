"""Health reporting — two endpoints with deliberately different meanings (§A12).

``/api/health/ready`` answers "can this API serve requests?" It touches the
database and nothing else. It is the **deploy gate**, so it must not depend on
the scheduler: a scheduler that is still starting (or waiting on the singleton
lock during an overlapping deploy) would otherwise trigger a false rollback.

``/api/health`` answers "is the system doing its job?" A dead scheduler means no
scraping and no digests, which is total product failure while every page still
loads — so this endpoint returns **503** when the heartbeat is stale, and it is
the one the uptime monitor pings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import HEARTBEAT_MAX_AGE_SECONDS

log = logging.getLogger(__name__)

#: The scheduler's row in ``heartbeats`` (§A5).
HEARTBEAT_NAME = "scheduler"

_AGE_SQL = text(
    """
    SELECT EXTRACT(EPOCH FROM (now() - beat_at))::double precision AS age_s
      FROM heartbeats
     WHERE name = :name
    """
)


@dataclass(frozen=True)
class HealthReport:
    """Everything ``/api/health`` needs to answer, in one round trip."""

    db_ok: bool
    heartbeat_age_s: float | None
    max_age_s: int = HEARTBEAT_MAX_AGE_SECONDS

    @property
    def scheduler_state(self) -> str:
        if not self.db_ok:
            return "unknown"
        if self.heartbeat_age_s is None:
            # No row at all: a fresh database whose scheduler has not beaten yet,
            # or a scheduler that has never run. Both mean "no background work".
            return "unknown"
        return "ok" if self.heartbeat_age_s <= self.max_age_s else "stale"

    @property
    def healthy(self) -> bool:
        return self.db_ok and self.scheduler_state == "ok"

    @property
    def payload(self) -> dict[str, Any]:
        age = self.heartbeat_age_s
        return {
            "api": "ok",
            "db": "ok" if self.db_ok else "error",
            "scheduler": self.scheduler_state,
            "heartbeat_age_s": round(age, 1) if age is not None else None,
            "heartbeat_max_age_s": self.max_age_s,
        }


async def check_db(engine: AsyncEngine) -> bool:
    """True when the database answers a trivial query."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # any failure is the same answer: not ready
        log.warning("database readiness check failed", exc_info=True)
        return False
    return True


async def build_report(engine: AsyncEngine) -> HealthReport:
    """Read the heartbeat age; a database failure is reported, never raised.

    The age is computed by PostgreSQL rather than in Python, so a clock skew
    between the ``api`` and ``scheduler`` containers cannot fake a stale (or a
    suspiciously fresh) heartbeat.
    """
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(_AGE_SQL, {"name": HEARTBEAT_NAME})).first()
    except Exception:
        log.warning("health query failed", exc_info=True)
        return HealthReport(db_ok=False, heartbeat_age_s=None)
    age = float(row.age_s) if row is not None and row.age_s is not None else None
    return HealthReport(db_ok=True, heartbeat_age_s=age)


async def write_heartbeat(engine: AsyncEngine, name: str = HEARTBEAT_NAME) -> None:
    """Upsert the heartbeat row with the *database's* clock."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO heartbeats (name, beat_at)
                VALUES (:name, now())
                ON CONFLICT (name) DO UPDATE SET beat_at = now()
                """
            ),
            {"name": name},
        )
