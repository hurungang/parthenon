"""add_requires_reauth_to_mcp_sessions

Revision ID: 903e79b3fac9
Revises: b1c2d3e4f5a6
Create Date: 2026-10-27 22:26:24.486940

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '903e79b3fac9'
down_revision: str | None = 'b1c2d3e4f5a6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'mcp_sessions',
        sa.Column('requires_reauth', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column('mcp_sessions', sa.Column('last_refresh_error', sa.Text(), nullable=True))
    op.execute('ALTER TABLE mcp_sessions ALTER COLUMN requires_reauth DROP DEFAULT')


def downgrade() -> None:
    op.drop_column('mcp_sessions', 'last_refresh_error')
    op.drop_column('mcp_sessions', 'requires_reauth')
