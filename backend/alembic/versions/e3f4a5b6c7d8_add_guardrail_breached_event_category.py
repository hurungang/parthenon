"""add_guardrail_breached_event_category

Phase 3.11: extend ``execution_event_category_enum`` with
``guardrail_breached`` so the Agent Runtime pre-execution availability
check can log deny verdicts caused by a breached terminate-posture
guardrail with a dedicated event category. Distinct from
``model_disabled`` because the model itself is enabled — only the
guardrail is on fire.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-02 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres-style ALTER TYPE for ``execution_event_category_enum``.
    # The new value is added idempotently; the test suite (which uses
    # SQLite) tolerates the no-op.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "ALTER TYPE execution_event_category_enum "
                "ADD VALUE IF NOT EXISTS 'guardrail_breached'"
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
