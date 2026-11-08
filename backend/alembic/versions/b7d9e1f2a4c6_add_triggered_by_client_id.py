"""add triggered_by_client_id to agent_jobs and conversation_sessions

Revision ID: b7d9e1f2a4c6
Revises: f1a2b3c4d5e6
Create Date: 2026-11-05 00:00:00.000000

Client-invocation provenance: records WHICH third-party client (integration
gateway credential) triggered an agent job or created a conversation, so the
Agent Runtime Monitor can visualise "client" as a trigger type alongside
user and schedule.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'b7d9e1f2a4c6'
down_revision: str | None = 'f1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'agent_jobs',
        sa.Column('triggered_by_client_id', UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'conversation_sessions',
        sa.Column('triggered_by_client_id', UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_agent_jobs_triggered_by_client_id',
        'agent_jobs',
        'agent_clients',
        ['triggered_by_client_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_conversation_sessions_triggered_by_client_id',
        'conversation_sessions',
        'agent_clients',
        ['triggered_by_client_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_conversation_sessions_triggered_by_client_id',
        'conversation_sessions',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_agent_jobs_triggered_by_client_id',
        'agent_jobs',
        type_='foreignkey',
    )
    op.drop_column('conversation_sessions', 'triggered_by_client_id')
    op.drop_column('agent_jobs', 'triggered_by_client_id')
