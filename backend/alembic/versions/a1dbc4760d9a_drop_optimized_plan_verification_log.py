"""drop optimized plan verification log

Revision ID: a1dbc4760d9a
Revises: c41e7a9d2b3f
Create Date: 2026-10-24 16:06:21.633692

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1dbc4760d9a'
down_revision: str | None = 'c41e7a9d2b3f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Verification now happens inside the agent's REAL execution — the
    # user-facing per-attempt verification log surface was removed.
    op.drop_column('optimized_implementation_plans', 'verification_log')


def downgrade() -> None:
    op.add_column(
        'optimized_implementation_plans',
        sa.Column('verification_log', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
