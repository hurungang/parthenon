"""add output_data_type_id to agent_types

Revision ID: 76078a3ecff2
Revises: a69529d1090f
Create Date: 2026-06-20 17:50:51.172006

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '76078a3ecff2'
down_revision: str | None = 'a69529d1090f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add output_data_type_id column to agent_types table."""
    op.add_column('agent_types', sa.Column('output_data_type_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_agent_types_output_data_type',
        'agent_types', 'agent_data_types',
        ['output_data_type_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove output_data_type_id column from agent_types table."""
    op.drop_constraint('fk_agent_types_output_data_type', 'agent_types', type_='foreignkey')
    op.drop_column('agent_types', 'output_data_type_id')
