"""add_partial_failure_to_script_execution_outcome

Revision ID: e4f66f7c7f1c
Revises: 903e79b3fac9
Create Date: 2026-10-27 22:34:38.045979

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e4f66f7c7f1c'
down_revision: str | None = '903e79b3fac9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new value to enum if it exists
    op.execute("ALTER TYPE script_execution_outcome_enum ADD VALUE IF NOT EXISTS 'partial_failure'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values easily; leave as-is
    pass
