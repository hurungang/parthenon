"""add_conversation_activity

Revision ID: 7127b840ae80
Revises: b7d9e1f2a4c6
Create Date: 2026-11-10 21:29:14.837721

Persisted, authoritative per-session agent activity record (ConversationActivity)
that powers the chat processing indicator across reloads, restarts, and failover.

Notes:
- The `activity_state_enum` type is created by model import (SQLAlchemy metadata);
  this migration references it with postgresql.ENUM(..., create_type=False) and
  drops it defensively on downgrade (guarded for existence).
- Autogenerate initially included unrelated schema drift; this migration was
  hand-reviewed and limited to the conversation_activities changes only.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7127b840ae80'
down_revision: str | None = 'b7d9e1f2a4c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guard-create the enum type: it may already exist (model import / test
    # metadata.create_all), but must exist before the table references it.
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'activity_state_enum') THEN CREATE TYPE activity_state_enum AS ENUM ('thinking', 'using_tool', 'delegating', 'waiting_for_human', 'finished', 'failed', 'timed_out'); END IF; END $$;")
    op.create_table('conversation_activities',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('conversation_session_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('state', postgresql.ENUM(
        'thinking', 'using_tool', 'delegating', 'waiting_for_human',
        'finished', 'failed', 'timed_out',
        name='activity_state_enum', create_type=False,
    ), nullable=False),
    sa.Column('current_turn_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('pending_intervene_request_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('tool_name', sa.String(length=400), nullable=True),
    sa.Column('target_agent_type_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('detail', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('is_terminal', sa.Boolean(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['conversation_session_id'], ['conversation_sessions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['current_turn_id'], ['conversation_turns.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['pending_intervene_request_id'], ['intervene_requests.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['target_agent_type_id'], ['agent_types.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_session_id')
    )
    op.create_index('ix_conversation_activities_last_updated_at', 'conversation_activities', ['last_updated_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_conversation_activities_last_updated_at', table_name='conversation_activities')
    op.drop_table('conversation_activities')

    # The enum type is created by model import, not by this migration's upgrade();
    # drop it defensively only if it exists (reversibility guard).
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'activity_state_enum') THEN DROP TYPE activity_state_enum; END IF; END $$;")
