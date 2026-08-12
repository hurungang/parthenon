"""add_is_default_to_mcp_sessions

Revision ID: 6beca08c57cf
Revises: 94b463ce35c0
Create Date: 2026-06-10 09:07:12.035105

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6beca08c57cf'
down_revision: str | None = '94b463ce35c0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('mcp_sessions', sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('mcp_sessions', 'is_default')
