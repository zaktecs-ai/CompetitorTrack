"""The ``scheduler`` service — a single process that owns all background work.

Run with ``python -m app.scheduler``. It is the *same image* as the API; only
the entrypoint differs (§A2).

P1 ships the two load-bearing behaviours and nothing else:

1. **Singleton guard.** A session-level advisory lock on a dedicated connection
   (§A6.11). A second instance does not race, does not half-work and does not
   crash — it logs ``lock held, waiting`` and retries every ten seconds, which
   is exactly what happens during a deploy while the old container drains.
2. **Heartbeat.** One row upserted every 60 s, using the database clock. This is
   what makes ``/api/health`` able to return 503 for a dead scheduler (§A12) —
   a silent scheduler is the one failure that breaks the product while every
   page still loads.

Jobs that land later, all in this process, all created with
``max_instances=1, coalesce=True, misfire_grace_time=600`` (§A3):

    P3  scrape tick (60 s)      — reap orphan runs, then claim due stores
    P3  weekly robots/meta re-check, weekly garbage collection of unlinked stores
    P4  digest tick (DIGEST_TICK_MINUTES)

§A6.11 also has the scheduler mark leftover ``scrape_runs`` rows as ``aborted``
right after acquiring the lock. That table does not exist until P2's ``0001``
migration, so the step arrives with it (D1.6) — P1 would have nothing to abort.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import dispose_engine, get_engine
from app.health import HEARTBEAT_NAME, write_heartbeat
from app.locks import SCHEDULER_LOCK_NAME, AdvisoryLock
from app.logging_setup import configure_logging

log = logging.getLogger(__name__)

SERVICE_NAME = "scheduler"

#: Heartbeat cadence (§A5). ``/api/health`` tolerates 5 minutes of silence.
HEARTBEAT_SECONDS = 60

#: How long to wait before retrying the singleton lock (§A6.11).
LOCK_RETRY_SECONDS = 10


async def _heartbeat_job() -> None:
    try:
        await write_heartbeat(get_engine(), HEARTBEAT_NAME)
    except Exception:  # a failed beat must not kill the scheduler
        log.error("heartbeat write failed", exc_info=True)


async def _acquire_singleton(lock: AdvisoryLock, stop: asyncio.Event) -> bool:
    """Block until the singleton lock is ours, or until we are asked to stop."""
    attempt = 0
    while not stop.is_set():
        attempt += 1
        try:
            if await lock.try_acquire():
                return True
        except Exception:  # database not up yet is normal on boot
            log.warning("could not reach the database to take the lock", exc_info=True)
        log.warning(
            "lock held, waiting",
            extra={
                "lock": lock.name,
                "lock_key": lock.key,
                "attempt": attempt,
                "retry_in_s": LOCK_RETRY_SECONDS,
            },
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=LOCK_RETRY_SECONDS)
    return False


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)


async def run() -> None:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.LOG_LEVEL)

    stop = asyncio.Event()
    _install_signal_handlers(stop)

    lock = AdvisoryLock(SCHEDULER_LOCK_NAME)
    scheduler: AsyncIOScheduler | None = None
    try:
        if not await _acquire_singleton(lock, stop):
            log.info("asked to stop before acquiring the lock; exiting")
            return

        scheduler = AsyncIOScheduler(timezone=UTC)
        scheduler.add_job(
            _heartbeat_job,
            trigger=IntervalTrigger(seconds=HEARTBEAT_SECONDS),
            id="heartbeat",
            name="heartbeat",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
            next_run_time=datetime.now(UTC),  # beat immediately, don't wait 60 s
        )
        scheduler.start()
        log.info(
            "scheduler started",
            extra={"jobs": [job.id for job in scheduler.get_jobs()], "singleton": lock.name},
        )

        await stop.wait()
        log.info("shutdown signal received")
    finally:
        if scheduler is not None:
            # wait=False: nothing running here is worth draining, and P3's runs
            # are cancelled deliberately because ingest is atomic (§A6.11).
            scheduler.shutdown(wait=False)
        await lock.release()
        await dispose_engine()
        log.info("scheduler stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
