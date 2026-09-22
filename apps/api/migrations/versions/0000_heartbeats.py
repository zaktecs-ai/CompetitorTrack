"""heartbeats

Revision ID: 0000
Revises:
Create Date: 2026-09-22

The only table P1 needs. It carries the scheduler's liveness signal, which is
what lets ``/api/health`` return 503 for a dead scheduler (§A12) — the failure
that breaks the product while every page still renders.

``beat_at`` is written with the *database's* ``now()``, never the container's
clock, so a skewed scheduler cannot fake liveness.

The rest of the A5 schema arrives in P2 as ``0001``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "heartbeats",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "beat_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("name", name="heartbeats_pkey"),
    )


def downgrade() -> None:
    # Production never downgrades (§A12); this exists so a developer can rebuild
    # a local database without dropping the volume.
    op.drop_table("heartbeats")
