"""Migration 0000 applies and creates exactly what P1 needs."""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


async def test_heartbeats_table_exists(engine) -> None:
    async with engine.connect() as conn:
        regclass = (await conn.execute(text("SELECT to_regclass('public.heartbeats')"))).scalar()
    assert regclass == "heartbeats"


async def test_alembic_is_at_revision_0000(engine) -> None:
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert version == "0000", "P1 ships one migration; the A5 schema is P2's 0001"


async def test_p1_creates_no_other_tables(engine) -> None:
    """A guard against P2 work leaking into P1."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT table_name
                      FROM information_schema.tables
                     WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                     ORDER BY table_name
                    """
                )
            )
        ).all()
    assert [row.table_name for row in rows] == ["alembic_version", "heartbeats"]


async def test_name_is_the_primary_key(engine) -> None:
    async with engine.connect() as conn:
        columns = (
            await conn.execute(
                text(
                    """
                    SELECT a.attname AS column_name
                      FROM pg_index i
                      JOIN pg_attribute a
                        ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
                     WHERE i.indrelid = 'heartbeats'::regclass AND i.indisprimary
                    """
                )
            )
        ).all()
    assert [row.column_name for row in columns] == ["name"]


async def test_beat_at_is_timestamptz(engine) -> None:
    async with engine.connect() as conn:
        data_type = (
            await conn.execute(
                text(
                    """
                    SELECT data_type
                      FROM information_schema.columns
                     WHERE table_name = 'heartbeats' AND column_name = 'beat_at'
                    """
                )
            )
        ).scalar()
    assert data_type == "timestamp with time zone"
