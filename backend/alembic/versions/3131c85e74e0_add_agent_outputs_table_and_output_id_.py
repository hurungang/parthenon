"""add agent_outputs table and output_id to agent_jobs

Revision ID: 3131c85e74e0
Revises: 76078a3ecff2
Create Date: 2026-06-20 18:14:34.027013

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3131c85e74e0'
down_revision: str | None = '76078a3ecff2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create agent_outputs table and add output_id FK to agent_jobs."""
    # Create the enum type first (may already exist from model import, which is safe)
    agent_output_validation_status_enum = sa.Enum(
        'valid', 'validation_error',
        name='agent_output_validation_status_enum',
    )
    agent_output_validation_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table('agent_outputs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('data_type_id', sa.UUID(), nullable=False),
    sa.Column('agent_type_id', sa.UUID(), nullable=False),
    sa.Column('execution_session_id', sa.UUID(), nullable=False),
    sa.Column('field_values', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('validation_status', postgresql.ENUM('valid', 'validation_error', name='agent_output_validation_status_enum', create_type=False), nullable=False),
    sa.Column('raw_output', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['data_type_id'], ['agent_data_types.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['execution_session_id'], ['agent_jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_agent_outputs_agent_type_id_created_at', 'agent_outputs', ['agent_type_id', 'created_at'], unique=False)
    op.create_index('ix_agent_outputs_data_type_id_created_at', 'agent_outputs', ['data_type_id', 'created_at'], unique=False)
    op.add_column('agent_jobs', sa.Column('output_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_agent_jobs_output_id', 'agent_jobs', 'agent_outputs',
        ['output_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    """Drop agent_outputs table and remove output_id from agent_jobs."""
    op.drop_constraint('fk_agent_jobs_output_id', 'agent_jobs', type_='foreignkey')
    op.drop_column('agent_jobs', 'output_id')
    op.drop_index('ix_agent_outputs_data_type_id_created_at', table_name='agent_outputs')
    op.drop_index('ix_agent_outputs_agent_type_id_created_at', table_name='agent_outputs')
    op.drop_table('agent_outputs')
