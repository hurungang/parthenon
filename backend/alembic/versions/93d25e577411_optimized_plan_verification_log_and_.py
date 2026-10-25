"""optimized plan verification log and feedback comments

Revision ID: 93d25e577411
Revises: 4108dac629ef
Create Date: 2026-10-21 22:31:22.923436

Adds two JSON columns to ``optimized_implementation_plans``:
- ``verification_log`` — per-attempt outcomes of the generate → test → refine
  verification loop ({attempt, outcome, detail} entries);
- ``feedback_comments`` — accumulated user feedback memory
  ({created_at, raw_feedback, summary} entries).

NOTE: reviewed by hand — the autogenerate run detected unrelated pre-existing
model/DB drift (tenant_id nullability, super_admin_credentials, index
uniqueness) which is deliberately EXCLUDED from this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '93d25e577411'
down_revision: str | None = '4108dac629ef'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('optimized_implementation_plans', sa.Column('verification_log', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('optimized_implementation_plans', sa.Column('feedback_comments', postgresql.JSON(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('optimized_implementation_plans', 'feedback_comments')
    op.drop_column('optimized_implementation_plans', 'verification_log')
