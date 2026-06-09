"""add_intervene_source_type_enum_values

Add ``intervene_request_created`` and ``intervene_request_responded`` to
the ``source_type_enum`` so notifications can be triggered by intervene
lifecycle events.

Revision ID: c5d6e7f8a9b0
Revises: bd215bb4dc55
Create Date: 2026-06-05 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "bd215bb4dc55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TRIGGER_VALUES = (
    "intervene_request_created",
    "intervene_request_responded",
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        for value in _NEW_TRIGGER_VALUES:
            op.execute(
                sa.text(
                    f"ALTER TYPE source_type_enum "
                    f"ADD VALUE IF NOT EXISTS '{value}'"
                )
            )
    else:
        # SQLite stores enums as plain strings — nothing to alter.
        pass


def downgrade() -> None:
    # PostgreSQL cannot drop enum values in use without a table rewrite.
    # For an additive change we leave the values in place on downgrade;
    # a future cleanup migration can drop them after verifying no rows
    # reference them.
    pass
