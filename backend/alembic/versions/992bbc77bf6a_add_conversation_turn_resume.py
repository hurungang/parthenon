"""add_conversation_turn_resume

Revision ID: 992bbc77bf6a
Revises: a7b8c9d0e1f2
Create Date: 2026-11-12 07:55:35.334522

Durable resume index + opaque checkpoint payload for paused conversational
turns (``ConversationTurnResume`` / ``ConversationTurnCheckpoint``), plus the
``conversation_activities.active_resume_id`` link.

Notes:
- The three enum types are created by model import (SQLAlchemy metadata); this
  migration guard-creates them and references them with
  ``postgresql.ENUM(..., create_type=False)`` so a create_all-created database
  and a migrated database converge.
- ``uq_conversation_turn_resumes_live_session`` is a PARTIAL unique index
  (``is_terminal = false``) enforcing at most one live resume row per session.
- Autogenerate initially included unrelated schema drift (tenant_id nullability,
  super_admin_credentials, identity provider comments, tenant_invitations index);
  this migration was hand-reviewed and limited to the resume/checkpoint/
  active_resume_id changes only.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '992bbc77bf6a'
down_revision: str | None = 'a7b8c9d0e1f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RESUME_STATE_VALUES = "'waiting_for_human', 'resuming', 'resolved', 'unresumable'"
_RESUME_OUTCOME_VALUES = (
    "'approved_applied', 'denied', 'cancelled', 'expired', 'superseded', 'resume_failed'"
)
_CHECKPOINT_PAYLOAD_KIND_VALUES = "'agent_turn_state', 'conversation_state'"

_ACTIVITY_RESUME_FK = 'conversation_activities_active_resume_id_fkey'


def upgrade() -> None:
    # Guard-create the enum types: they may already exist (model import /
    # test metadata.create_all), but must exist before the tables reference them.
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resume_state_enum') "
        f"THEN CREATE TYPE resume_state_enum AS ENUM ({_RESUME_STATE_VALUES}); END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resume_outcome_enum') "
        f"THEN CREATE TYPE resume_outcome_enum AS ENUM ({_RESUME_OUTCOME_VALUES}); END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'checkpoint_payload_kind_enum') "
        f"THEN CREATE TYPE checkpoint_payload_kind_enum AS ENUM ({_CHECKPOINT_PAYLOAD_KIND_VALUES}); END IF; END $$;"
    )

    op.create_table(
        'conversation_turn_resumes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('conversation_session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('turn_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('intervene_request_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('state', postgresql.ENUM(
            'waiting_for_human', 'resuming', 'resolved', 'unresumable',
            name='resume_state_enum', create_type=False,
        ), nullable=False),
        sa.Column('resume_outcome', postgresql.ENUM(
            'approved_applied', 'denied', 'cancelled', 'expired', 'superseded', 'resume_failed',
            name='resume_outcome_enum', create_type=False,
        ), nullable=True),
        sa.Column('is_terminal', sa.Boolean(), nullable=False),
        sa.Column('resume_key', sa.String(length=255), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('write_applied', sa.Boolean(), nullable=False),
        sa.Column('applied_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_effect_summary', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('outcome_turn_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('claimed_by_instance_id', sa.String(length=255), nullable=True),
        sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('terminal_reason_code', sa.String(length=100), nullable=True),
        sa.Column('terminal_message_key', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['conversation_session_id'], ['conversation_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['turn_id'], ['conversation_turns.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['intervene_request_id'], ['intervene_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['applied_by_user_id'], ['identities.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outcome_turn_id'], ['conversation_turns.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index(
        'ix_conversation_turn_resumes_conversation_session_id',
        'conversation_turn_resumes', ['conversation_session_id'], unique=False,
    )
    op.create_index(
        'ix_conversation_turn_resumes_expires_at',
        'conversation_turn_resumes', ['expires_at'], unique=False,
    )
    op.create_index(
        'ix_conversation_turn_resumes_resume_key',
        'conversation_turn_resumes', ['resume_key'], unique=False,
    )
    # At most one live (non-terminal) resume row per conversation session.
    op.create_index(
        'uq_conversation_turn_resumes_live_session',
        'conversation_turn_resumes', ['conversation_session_id'],
        unique=True, postgresql_where=sa.text('is_terminal = false'),
    )

    op.create_table(
        'conversation_turn_checkpoints',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('resume_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('payload_kind', postgresql.ENUM(
            'agent_turn_state', 'conversation_state',
            name='checkpoint_payload_kind_enum', create_type=False,
        ), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('payload', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('payload_bytes', sa.Integer(), nullable=False),
        sa.Column('is_consumed', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['resume_id'], ['conversation_turn_resumes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resume_id'),
    )

    op.add_column(
        'conversation_activities',
        sa.Column('active_resume_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        _ACTIVITY_RESUME_FK, 'conversation_activities', 'conversation_turn_resumes',
        ['active_resume_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(_ACTIVITY_RESUME_FK, 'conversation_activities', type_='foreignkey')
    op.drop_column('conversation_activities', 'active_resume_id')

    op.drop_table('conversation_turn_checkpoints')

    op.drop_index('uq_conversation_turn_resumes_live_session', table_name='conversation_turn_resumes')
    op.drop_index('ix_conversation_turn_resumes_resume_key', table_name='conversation_turn_resumes')
    op.drop_index('ix_conversation_turn_resumes_expires_at', table_name='conversation_turn_resumes')
    op.drop_index('ix_conversation_turn_resumes_conversation_session_id', table_name='conversation_turn_resumes')
    op.drop_table('conversation_turn_resumes')

    # Types are created by model import, so drop them defensively only if present
    # (and only after the tables that reference them are gone).
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'checkpoint_payload_kind_enum') "
        "THEN DROP TYPE checkpoint_payload_kind_enum; END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resume_outcome_enum') "
        "THEN DROP TYPE resume_outcome_enum; END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resume_state_enum') "
        "THEN DROP TYPE resume_state_enum; END IF; END $$;"
    )
