"""Shared fixtures.

Tests run against a **real PostgreSQL** (§A13) — advisory locks, ``ON CONFLICT``
upserts and ``now()`` semantics are exactly the things SQLite would fake.

Locally: start one with the compose override (``cd deploy && docker compose up -d
db``) and export the URL, or point ``DATABASE_URL`` at any throwaway database.
Without a reachable database the DB-backed tests **skip** — except when
``CT_REQUIRE_DB=1``, which CI sets, so a missing service container fails the
build instead of quietly passing an empty suite.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]

DEFAULT_DATABASE_URL = "postgresql+psycopg://ct:ct@localhost:5432/competitortrack_test"

# Set before any `app.*` import: Settings validates at construction, and these
# are the fields with no default. The values are deliberately obvious fakes.
_DEFAULT_TEST_ENV = {
    "DATABASE_URL": DEFAULT_DATABASE_URL,
    "JWT_SECRET": "test-secret-not-for-production-0123456789",
    "MASTER_ENCRYPTION_KEYS": base64.urlsafe_b64encode(bytes(32)).decode(),
    "PUBLIC_ORIGIN": "http://localhost",
    "COOKIE_SECURE": "false",
    "LOG_LEVEL": "WARNING",
}
for _name, _value in _DEFAULT_TEST_ENV.items():
    os.environ.setdefault(_name, _value)


def _database_reachable(url: str, timeout: int = 3) -> bool:
    """Open a real connection.

    A TCP probe is not enough: a developer may point DATABASE_URL at a unix
    socket, and CI's service container answers on TCP but not always
    immediately. Connecting is the only honest check.
    """
    import psycopg
    from sqlalchemy.engine import make_url

    dsn = make_url(url).set(drivername="postgresql")
    try:
        with psycopg.connect(dsn.render_as_string(hide_password=False), connect_timeout=timeout):
            return True
    except Exception:  # noqa: BLE001 - unreachable, bad credentials, no database: same answer
        return False


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Apply every migration once per session; skip (or fail) without a database."""
    if not _database_reachable(database_url):
        from sqlalchemy.engine import make_url

        safe = make_url(database_url).render_as_string(hide_password=True)
        message = (
            f"no PostgreSQL reachable at {safe} — start one "
            "(cd deploy && docker compose up -d db) and set DATABASE_URL"
        )
        if os.environ.get("CT_REQUIRE_DB") == "1":
            pytest.fail(message, pytrace=False)
        pytest.skip(message)

    # A subprocess, because migrations/env.py calls asyncio.run() and cannot run
    # inside the test event loop. It is also exactly how deploy.sh invokes it.
    result = subprocess.run(  # fixed argv, no shell
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic upgrade head failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            pytrace=False,
        )
    return database_url


@pytest.fixture
async def engine(migrated_database: str) -> AsyncIterator[object]:
    """A fresh pooled engine per test, with an empty ``heartbeats`` table."""
    from sqlalchemy import text

    from app.db import dispose_engine, get_engine

    await dispose_engine()  # never reuse an engine bound to a closed event loop
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM heartbeats"))
    try:
        yield eng
    finally:
        await dispose_engine()


@pytest.fixture
def clean_settings() -> Iterator[None]:
    """Drop the cached Settings so a test can change the environment."""
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()
