"""optimized_plan_status_enum gains 'retired'.

Revision ID: c2d3e4f5a6b7
Revises: a1dbc4760d9a
Create Date: 2026-10-25

Adds the ``retired`` value to ``optimized_plan_status_enum``: "Retire plan"
(and plan regeneration) now MARK rows retired instead of deleting them, so
the composition stays available for reference. Only status='ready' plans
gate execution.
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "a1dbc4760d9a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction on some
    # PostgreSQL versions; guarded with IF NOT EXISTS for idempotency.
    op.execute(
        "ALTER TYPE optimized_plan_status_enum "
        "ADD VALUE IF NOT EXISTS 'retired'"
    )


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value; downgrade is a no-op. Existing
    # 'retired' rows remain valid for the VARCHAR-backed enum.
    pass
