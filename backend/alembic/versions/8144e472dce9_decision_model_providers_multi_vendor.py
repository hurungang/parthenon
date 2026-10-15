"""decision model providers multi vendor

Revision ID: 8144e472dce9
Revises: c9d0e1f2a3b4
Create Date: 2026-10-13 20:41:19.498396

Schema changes (data-model doc: decision-model-providers):
- New table ``decision_model_availability`` (per-model enablement under a
  Decision Model Provider, mirroring ``model_availability``).
- ``decision_tools.decision_model_availability_id`` nullable FK to the
  selected enabled model (legacy free-text ``provider_model`` kept readable).
- Unique (tenant_id, provider_type, display_name) on ``system_one_provider_configs``
  to support multiple providers per tenant.

Data migration is idempotent: re-running on an upgraded DB changes nothing.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8144e472dce9'
down_revision: str | None = 'c9d0e1f2a3b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISABLED_REASON_ENUM = 'decision_model_availability_disabled_reason_enum'

# Idempotent enum creation (parameter-free DDL; safe to re-run).
_CREATE_ENUM = f"""
DO $$ BEGIN
    CREATE TYPE {DISABLED_REASON_ENUM} AS ENUM ('manual', 'vendor_cascaded');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
"""


def upgrade() -> None:
    # --- enum (create_type=False on the column type; created explicitly) ---
    op.execute(_CREATE_ENUM)

    # --- dedup legacy provider rows (idempotent, runs BEFORE any FK exists) ---
    # Legacy single-provider era data can contain duplicate
    # (tenant_id, provider_type, display_name) rows (e.g. E2E stubs). Keep the
    # oldest row per key; safe here because decision_tools has no FK to
    # providers yet and availability rows do not exist yet.
    op.execute(
        """
        DELETE FROM system_one_provider_configs p
        USING system_one_provider_configs q
        WHERE p.tenant_id IS NOT DISTINCT FROM q.tenant_id
          AND p.provider_type = q.provider_type
          AND p.display_name = q.display_name
          AND (q.created_at, q.id) < (p.created_at, p.id)
        """
    )

    # --- new table: decision model availability ---
    op.create_table(
        'decision_model_availability',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=True),
        sa.Column('model_name', sa.String(length=500), nullable=False),
        sa.Column('decision_model_provider_id', sa.UUID(), nullable=False),
        sa.Column('is_disabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column(
            'disabled_reason',
            postgresql.ENUM(
                'manual', 'vendor_cascaded',
                name=DISABLED_REASON_ENUM,
                create_type=False,
            ),
            server_default='manual',
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['decision_model_provider_id'],
            ['system_one_provider_configs.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'decision_model_provider_id',
            'model_name',
            name='uq_decision_model_availability_provider_model',
        ),
    )
    op.create_index('ix_decision_model_availability_provider', 'decision_model_availability', ['decision_model_provider_id'], unique=False)
    op.create_index('ix_decision_model_availability_tenant_id', 'decision_model_availability', ['tenant_id'], unique=False)

    # --- decision tools: structured model reference (nullable FK) ---
    op.add_column(
        'decision_tools',
        sa.Column(
            'decision_model_availability_id',
            sa.UUID(),
            nullable=True,
            comment='Selected enabled decision model (replaces legacy provider_model)',
        ),
    )
    op.create_foreign_key(
        'fk_decision_tools_decision_model_availability_id',
        'decision_tools',
        'decision_model_availability',
        ['decision_model_availability_id'],
        ['id'],
        ondelete='RESTRICT',
    )

    # --- multi-vendor provider registry: tenant-scoped display-name uniqueness ---
    op.create_unique_constraint(
        'uq_system_one_providers_tenant_type_display',
        'system_one_provider_configs',
        ['tenant_id', 'provider_type', 'display_name'],
    )

    # ------------------------------------------------------------------
    # Data migration (idempotent — safe to re-run on an upgraded DB).
    # ------------------------------------------------------------------

    # 1. Promote each existing provider row: seed its default_model as the
    #    initial ENABLED availability row (one per provider; skips providers
    #    that already have availability rows).
    op.execute(
        """
        INSERT INTO decision_model_availability (
            id, tenant_id, model_name, decision_model_provider_id,
            is_disabled, disabled_reason, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            p.tenant_id,
            COALESCE(NULLIF(p.default_model, ''), 'jev-latest'),
            p.id,
            FALSE,
            'manual',
            now(),
            now()
        FROM system_one_provider_configs p
        WHERE NOT EXISTS (
            SELECT 1
            FROM decision_model_availability a
            WHERE a.decision_model_provider_id = p.id
        )
        """
    )

    # 2. Backfill each DecisionTool's model reference from its legacy
    #    provider_model; fall back to the migrated provider's default row.
    #    Only rows with a NULL reference are touched, so re-runs are no-ops.
    op.execute(
        """
        UPDATE decision_tools t
        SET decision_model_availability_id = sel.avail_id
        FROM (
            SELECT
                t2.id AS tool_id,
                COALESCE(
                    -- exact match on the tool's legacy provider_model
                    (
                        SELECT a.id
                        FROM decision_model_availability a
                        JOIN system_one_provider_configs p
                            ON p.id = a.decision_model_provider_id
                        WHERE p.tenant_id IS NOT DISTINCT FROM t2.tenant_id
                          AND a.model_name = NULLIF(t2.provider_model, '')
                        ORDER BY a.created_at
                        LIMIT 1
                    ),
                    -- fallback: the provider's migrated default model
                    (
                        SELECT a.id
                        FROM decision_model_availability a
                        JOIN system_one_provider_configs p
                            ON p.id = a.decision_model_provider_id
                        WHERE p.tenant_id IS NOT DISTINCT FROM t2.tenant_id
                        ORDER BY a.created_at
                        LIMIT 1
                    )
                ) AS avail_id
            FROM decision_tools t2
            WHERE t2.decision_model_availability_id IS NULL
        ) sel
        WHERE t.id = sel.tool_id
          AND sel.avail_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Undo backfill reference, then drop the column/FK.
    op.drop_constraint(
        'fk_decision_tools_decision_model_availability_id',
        'decision_tools',
        type_='foreignkey',
    )
    op.drop_column('decision_tools', 'decision_model_availability_id')

    # Restore multi-vendor uniqueness relaxation.
    op.drop_constraint(
        'uq_system_one_providers_tenant_type_display',
        'system_one_provider_configs',
        type_='unique',
    )

    # Drop availability table, indexes, and the enum.
    op.drop_index('ix_decision_model_availability_tenant_id', table_name='decision_model_availability')
    op.drop_index('ix_decision_model_availability_provider', table_name='decision_model_availability')
    op.drop_table('decision_model_availability')
    op.execute(f'DROP TYPE IF EXISTS {DISABLED_REASON_ENUM}')
