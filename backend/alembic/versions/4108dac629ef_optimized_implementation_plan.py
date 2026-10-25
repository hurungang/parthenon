"""optimized_implementation_plan

Revision ID: 4108dac629ef
Revises: 38b5903c0c22
Create Date: 2026-10-21 14:22:51.485862

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4108dac629ef'
down_revision: str | None = '38b5903c0c22'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum carried on the column with create_type=False — the type is created
# explicitly below (project convention: AGENTS.md enum rule).
optimized_plan_status = postgresql.ENUM(
    'generating', 'ready', 'failed',
    name='optimized_plan_status_enum', create_type=False,
)


def _create_enum_types() -> None:
    op.execute(
        "DO $$ BEGIN\n"
        "    CREATE TYPE optimized_plan_status_enum AS ENUM "
        "('generating', 'ready', 'failed');\n"
        "EXCEPTION\n"
        "    WHEN duplicate_object THEN NULL;\n"
        "END $$;"
    )


def _drop_enum_types() -> None:
    op.execute("DROP TYPE IF EXISTS optimized_plan_status_enum")


def upgrade() -> None:
    _create_enum_types()
    op.create_table(
        'optimized_implementation_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('agent_type_id', sa.UUID(), nullable=False),
        sa.Column('agent_plan_id', sa.UUID(), nullable=False),
        sa.Column('plan_steps', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('fully_scripted', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('status', optimized_plan_status, nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_plan_id'], ['agent_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_type_id'], ['agent_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_optimized_implementation_plans_agent_plan_id',
        'optimized_implementation_plans', ['agent_plan_id'], unique=False,
    )
    op.create_index(
        'ix_optimized_implementation_plans_agent_type_id',
        'optimized_implementation_plans', ['agent_type_id'], unique=False,
    )
    op.create_index(
        'ix_optimized_implementation_plans_tenant_id',
        'optimized_implementation_plans', ['tenant_id'], unique=False,
    )
    op.add_column(
        'script_definitions',
        sa.Column('source_optimized_plan_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_script_definitions_source_optimized_plan_id',
        'script_definitions', 'optimized_implementation_plans',
        ['source_optimized_plan_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_script_definitions_source_optimized_plan_id',
        'script_definitions', type_='foreignkey',
    )
    op.drop_column('script_definitions', 'source_optimized_plan_id')
    op.drop_index(
        'ix_optimized_implementation_plans_tenant_id',
        table_name='optimized_implementation_plans',
    )
    op.drop_index(
        'ix_optimized_implementation_plans_agent_type_id',
        table_name='optimized_implementation_plans',
    )
    op.drop_index(
        'ix_optimized_implementation_plans_agent_plan_id',
        table_name='optimized_implementation_plans',
    )
    op.drop_table('optimized_implementation_plans')
    _drop_enum_types()
