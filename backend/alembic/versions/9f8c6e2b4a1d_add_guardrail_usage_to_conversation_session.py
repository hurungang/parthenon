"""add guardrail usage snapshot to conversation sessions

Revision ID: 9f8c6e2b4a1d
Revises: a44d298ae1f5
Create Date: 2026-05-24 20:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9f8c6e2b4a1d'
down_revision: str | None = 'a44d298ae1f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'conversation_sessions',
        sa.Column('guardrail_usage', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('conversation_sessions', 'guardrail_usage')
