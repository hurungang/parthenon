"""add_model_vendor_disabled_event_categories

Phase 3.10: extend ``execution_event_category_enum`` with
``model_disabled`` and ``vendor_disabled`` so the Agent Runtime
pre-execution availability check can log deny verdicts with dedicated
event categories that the operator UI can filter on.

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-01 22:45:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres-style ALTER TYPE for ``execution_event_category_enum``.
    # Each new value is added idempotently; the test suite (which uses
    # SQLite) tolerates the ``IF NOT EXISTS``-style no-op.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        for value in ("model_disabled", "vendor_disabled"):
            # Use string formatting instead of bindparams because PostgreSQL
            # doesn't support parameterized queries for DDL statements
            op.execute(
                sa.text(
                    f"ALTER TYPE execution_event_category_enum "
                    f"ADD VALUE IF NOT EXISTS '{value}'"
                )
            )
    else:
        # SQLite stores enums as plain strings — nothing to alter.
        pass


def downgrade() -> None:
    # Postgres cannot drop enum values in use without a table rewrite.
    # For an additive change we leave the values in place on downgrade;
    # a future cleanup migration can drop them after verifying no rows
    # reference them.
    pass
