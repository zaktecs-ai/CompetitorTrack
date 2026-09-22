"""Alembic environment — async, driven by DATABASE_URL.

``DATABASE_URL`` is read straight from the environment rather than through
``app.config.Settings``. A migration run is not the application: it has no
business failing because ``JWT_SECRET`` or ``MASTER_ENCRYPTION_KEYS`` is absent,
and ``deploy.sh`` runs ``alembic upgrade head`` in a one-shot container before
the services come up.

``target_metadata`` is ``None`` in P1 because there are no ORM models yet — the
A5 schema arrives in P2's ``0001``, which wires ``Base.metadata`` here and
enables autogenerate. Migrations are **forward-only and additive** (§A12): a
rollback re-deploys the previous image against the newer schema, so a column is
dropped only one release after the code stopped using it.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Run migrations through compose, e.g. "
            "`docker compose run --rm api alembic upgrade head`."
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
