"""add is_system to agent types

Revision ID: 1a0ed55b8cf1
Revises: e4f66f7c7f1c
Create Date: 2026-10-29 23:53:09.980225

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1a0ed55b8cf1'
down_revision: str | None = 'e4f66f7c7f1c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'agent_types',
        sa.Column('is_system', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('agent_types', 'is_system')
