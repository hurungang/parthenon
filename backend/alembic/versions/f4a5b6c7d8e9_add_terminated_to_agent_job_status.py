"""add_terminated_to_agent_job_status

Phase 3.12: extend ``agent_job_status_enum`` with a ``terminated``
value so operator-initiated terminations (and cascade-parent
terminations) are recorded as a distinct terminal state from
``failed`` (which is reserved for genuine agent/runtime errors).

This lets the frontend show a "Terminated" badge for sessions killed
by the operator, instead of the misleading "Failed" red badge.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-02 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres-style ALTER TYPE for ``agent_job_status_enum``.
    # The new value is added idempotently; the test suite (which uses
    # SQLite) tolerates the no-op.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "ALTER TYPE agent_job_status_enum "
                "ADD VALUE IF NOT EXISTS 'terminated'"
            )
        )
    else:
        # SQLite stores enums as plain strings — nothing to alter.
        pass


def downgrade() -> None:
    # Postgres cannot drop enum values in use without a table rewrite.
    # For an additive change we leave the value in place on downgrade;
    # a future cleanup migration can drop it after verifying no rows
    # reference it.
    pass
