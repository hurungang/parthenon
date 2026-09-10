"""add_api_key_expires_at

Revision ID: b5403591994f
Revises: cf44fe226b0d
Create Date: 2026-08-25 23:09:48.997590

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b5403591994f'
down_revision: str | None = 'cf44fe226b0d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('agent_api_keys', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_api_keys', 'expires_at')
