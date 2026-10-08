"""decision tools (replaces decision skills)

Revision ID: c3f7a1d92e40
Revises: a7c2e9d41b58
Create Date: 2026-10-04 00:00:00.000000

NOTE: hand-authored (following a7c2e9d41b58's convention). Re-keys the
decision feature from decision SKILLS to tenant-contained decision TOOLS:

- drops ``decision_skill_definitions`` + ``decision_questions``
- drops ``skills.skill_type`` + ``skill_type_enum`` (skills revert)
- drops and recreates ``decision_execution_results`` keyed to
  ``decision_tool_id``
- creates ``decision_tools`` (unique ``(tenant_id, name)`` — tool names
  unique WITHIN a tenant) + ``decision_tool_questions``
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3f7a1d92e40'
down_revision: str | None = 'a7c2e9d41b58'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_decision_question_type_enum = postgresql.ENUM(
    'choice', 'score', 'noul', name='decision_question_type_enum', create_type=False
)
_decision_outcome_enum = postgresql.ENUM(
    'act', 'confirm', 'escalate', name='decision_outcome_enum', create_type=False
)
_decision_execution_status_enum = postgresql.ENUM(
    'completed', 'failed', name='decision_execution_status_enum', create_type=False
)


def upgrade() -> None:
    # Tool status enum (created explicitly — sa.Enum in column defs does not
    # emit CREATE TYPE inside migrations under asyncpg).
    sa.Enum('draft', 'active', 'disabled', name='decision_tool_status_enum').create(
        op.get_bind(), checkfirst=True
    )

    # 1. Drop the superseded decision-skill tables (and the results table,
    #    recreated below re-keyed to the tool).
    op.drop_index(
        'ix_decision_execution_results_tenant_id', table_name='decision_execution_results'
    )
    op.drop_table('decision_execution_results')
    op.drop_table('decision_questions')
    op.drop_table('decision_skill_definitions')

    # 2. Skills revert: remove the skill_type discriminator.
    op.drop_column('skills', 'skill_type')
    sa.Enum(name='skill_type_enum').drop(op.get_bind(), checkfirst=True)

    # 3. Decision tools (tenant-contained: unique (tenant_id, name)).
    op.create_table(
        'decision_tools',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('purpose', sa.Text(), nullable=True),
        sa.Column(
            'description', sa.Text(), nullable=True,
            comment='Auto-generated tool description from the definition',
        ),
        sa.Column(
            'input_schema', postgresql.JSON(astext_type=sa.Text()), nullable=True,
            comment='Structured input schema (system-tool aligned)',
        ),
        sa.Column(
            'output_schema', postgresql.JSON(astext_type=sa.Text()), nullable=True,
            comment='Structured output schema (system-tool aligned)',
        ),
        sa.Column(
            'state_preset', postgresql.JSON(astext_type=sa.Text()), nullable=True,
            comment='Mapping of input/agent data to state fields',
        ),
        sa.Column('act_threshold', sa.Float(), server_default='0.9', nullable=False),
        sa.Column('confirm_threshold', sa.Float(), server_default='0.7', nullable=False),
        sa.Column(
            'provider_model', sa.String(length=200), server_default='jev-latest',
            nullable=False,
        ),
        sa.Column(
            'status',
            postgresql.ENUM('draft', 'active', 'disabled', name='decision_tool_status_enum', create_type=False),
            server_default='active', nullable=False,
        ),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'is_system', sa.Boolean(), nullable=False,
            comment='False; mirrors system-tool flag',
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_decision_tools_tenant_id_name'),
    )
    op.create_index('ix_decision_tools_tenant_id', 'decision_tools', ['tenant_id'], unique=False)

    op.create_table(
        'decision_tool_questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('decision_tool_id', sa.UUID(), nullable=False),
        sa.Column('ordering', sa.Integer(), nullable=False),
        sa.Column('question_key', sa.String(length=200), nullable=False),
        sa.Column('question_type', _decision_question_type_enum, nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column(
            'criteria_options', postgresql.JSON(astext_type=sa.Text()), nullable=True,
            comment='Criteria/options appropriate to the question type',
        ),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['decision_tool_id'], ['decision_tools.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('decision_tool_id', 'question_key', name='uq_decision_tool_questions_key'),
    )

    # 4. Decision execution results — recreated keyed to the decision tool.
    op.create_table(
        'decision_execution_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('decision_tool_id', sa.UUID(), nullable=False),
        sa.Column('conversation_session_id', sa.UUID(), nullable=True),
        sa.Column('input_state_snapshot', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            'answers', postgresql.JSON(astext_type=sa.Text()), nullable=True,
            comment='Per question: typed value, probabilities, confidence',
        ),
        sa.Column('outcome', _decision_outcome_enum, nullable=False),
        sa.Column('status', _decision_execution_status_enum, nullable=False),
        sa.Column('provider_model', sa.String(length=200), nullable=True, comment='e.g. jev-latest'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_session_id'], ['conversation_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['decision_tool_id'], ['decision_tools.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_decision_execution_results_tenant_id',
        'decision_execution_results',
        ['tenant_id'],
        unique=False,
    )


def downgrade() -> None:
    # Reverse: back to the decision-skill shape.
    op.drop_index(
        'ix_decision_execution_results_tenant_id', table_name='decision_execution_results'
    )
    op.drop_table('decision_execution_results')
    op.drop_table('decision_tool_questions')
    op.drop_index('ix_decision_tools_tenant_id', table_name='decision_tools')
    op.drop_table('decision_tools')

    sa.Enum('tool_based', 'decision', name='skill_type_enum').create(
        op.get_bind(), checkfirst=True
    )
    op.add_column(
        'skills',
        sa.Column(
            'skill_type',
            postgresql.ENUM('tool_based', 'decision', name='skill_type_enum', create_type=False),
            server_default='tool_based',
            nullable=False,
        ),
    )

    op.create_table(
        'decision_skill_definitions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('skill_id', sa.UUID(), nullable=False),
        sa.Column('state_preset', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('act_threshold', sa.Float(), server_default='0.9', nullable=False),
        sa.Column('confirm_threshold', sa.Float(), server_default='0.7', nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('skill_id', name='uq_decision_skill_definitions_skill_id'),
    )
    op.create_table(
        'decision_questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('definition_id', sa.UUID(), nullable=False),
        sa.Column('ordering', sa.Integer(), nullable=False),
        sa.Column('question_key', sa.String(length=200), nullable=False),
        sa.Column('question_type', _decision_question_type_enum, nullable=False),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('criteria_options', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['definition_id'], ['decision_skill_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'decision_execution_results',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('skill_id', sa.UUID(), nullable=False),
        sa.Column('definition_id', sa.UUID(), nullable=False),
        sa.Column('conversation_session_id', sa.UUID(), nullable=True),
        sa.Column('input_state_snapshot', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('answers', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('outcome', _decision_outcome_enum, nullable=False),
        sa.Column('status', _decision_execution_status_enum, nullable=False),
        sa.Column('provider_model', sa.String(length=200), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_session_id'], ['conversation_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['definition_id'], ['decision_skill_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_decision_execution_results_tenant_id',
        'decision_execution_results',
        ['tenant_id'],
        unique=False,
    )
    sa.Enum(name='decision_tool_status_enum').drop(op.get_bind(), checkfirst=True)
