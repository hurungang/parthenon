"""add_intervene_requests

Revision ID: bd215bb4dc55
Revises: b38732c813c9
Create Date: 2026-06-04 21:45:25.522553

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bd215bb4dc55'
down_revision: str | None = 'b38732c813c9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('intervene_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agent_session_id', sa.UUID(), nullable=False),
    sa.Column('agent_type_id', sa.UUID(), nullable=False),
    sa.Column('intervention_type', sa.Enum('approval', 'choice', 'text', name='intervention_type_enum'), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('choices', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Enum('pending', 'responded', 'cancelled', 'expired', name='intervene_request_status_enum'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agent_session_id'], ['agent_jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('intervene_responses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('operator_user_id', sa.UUID(), nullable=False),
    sa.Column('approval_value', sa.Boolean(), nullable=True),
    sa.Column('selected_choice', sa.Text(), nullable=True),
    sa.Column('text_value', sa.Text(), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['operator_user_id'], ['identities.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['intervene_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_id')
    )

    # Add waiting_for_human to the agent_job_status_enum
    op.execute("ALTER TYPE agent_job_status_enum ADD VALUE 'waiting_for_human'")


def downgrade() -> None:
    # Remove waiting_for_human from agent_job_status_enum requires recreating
    # columns that use it. For simplicity, we drop the intervene tables first
    # and note that the enum value persists (PostgreSQL does not allow removal).
    op.drop_table('intervene_responses')
    op.drop_table('intervene_requests')
    # Note: agent_job_status_enum still contains 'waiting_for_human' because
    # PostgreSQL does not support removing values from enum types without
    # recreating dependent columns.
