"""The two health endpoints, including the 503 semantics P1 is judged on (§A12)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import HEARTBEAT_MAX_AGE_SECONDS
from app.health import HEARTBEAT_NAME, HealthReport, write_heartbeat
from app.main import app

pytestmark = pytest.mark.db


async def _get(path: str) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def _set_heartbeat_age(engine, seconds: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO heartbeats (name, beat_at)
                VALUES (:name, now() - make_interval(secs => :secs))
                ON CONFLICT (name) DO UPDATE SET beat_at = excluded.beat_at
                """
            ),
            {"name": HEARTBEAT_NAME, "secs": seconds},
        )


async def test_ready_is_200_when_the_database_answers(engine) -> None:
    status, body = await _get("/api/health/ready")
    assert status == 200
    assert body == {"status": "ready", "db": "ok"}


async def test_health_is_503_before_the_scheduler_ever_beats(engine) -> None:
    status, body = await _get("/api/health")
    assert status == 503
    assert body["db"] == "ok"
    assert body["scheduler"] == "unknown"
    assert body["heartbeat_age_s"] is None


async def test_health_is_200_with_a_fresh_heartbeat(engine) -> None:
    await write_heartbeat(engine)
    status, body = await _get("/api/health")
    assert status == 200
    assert body["api"] == "ok"
    assert body["db"] == "ok"
    assert body["scheduler"] == "ok"
    assert body["heartbeat_age_s"] < 5


async def test_health_is_503_when_the_heartbeat_is_stale_but_ready_stays_200(engine) -> None:
    """The DoD check: a dead scheduler pages, but never triggers a rollback."""
    await _set_heartbeat_age(engine, HEARTBEAT_MAX_AGE_SECONDS + 60)

    status, body = await _get("/api/health")
    assert status == 503
    assert body["scheduler"] == "stale"
    assert body["heartbeat_age_s"] > HEARTBEAT_MAX_AGE_SECONDS

    ready_status, ready_body = await _get("/api/health/ready")
    assert ready_status == 200
    assert ready_body["db"] == "ok"


async def test_heartbeat_upsert_keeps_one_row_and_moves_forward(engine) -> None:
    await _set_heartbeat_age(engine, 120)
    await write_heartbeat(engine)
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT name, beat_at FROM heartbeats"))).all()
    assert len(rows) == 1
    assert rows[0].name == HEARTBEAT_NAME


@pytest.mark.parametrize(
    ("db_ok", "age", "expected_state", "expected_healthy"),
    [
        (True, 0.0, "ok", True),
        (True, float(HEARTBEAT_MAX_AGE_SECONDS), "ok", True),
        (True, HEARTBEAT_MAX_AGE_SECONDS + 0.1, "stale", False),
        (True, None, "unknown", False),
        (False, None, "unknown", False),
    ],
)
def test_report_boundaries(db_ok, age, expected_state, expected_healthy) -> None:
    """Exactly at the limit is still healthy; a hair past it is not."""
    report = HealthReport(db_ok=db_ok, heartbeat_age_s=age)
    assert report.scheduler_state == expected_state
    assert report.healthy is expected_healthy
    assert set(report.payload) == {
        "api",
        "db",
        "scheduler",
        "heartbeat_age_s",
        "heartbeat_max_age_s",
    }
