"""unique (tenant_id, provider_scope) on identity_provider_configs

Enforces strict tenant containment on the identity plane: every tenant
has at most one provider config per scope (user / agent).  The SHARED
NULL-tenant slot is retired; a partial unique index keeps legacy
tenant-less rows unique per scope so they cannot multiply.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-09
"""
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE identity_provider_configs "
        "DROP CONSTRAINT IF EXISTS uq_idp_tenant_scope"
    )
    op.execute(
        "ALTER TABLE identity_provider_configs "
        "ADD CONSTRAINT uq_idp_tenant_scope "
        "UNIQUE (tenant_id, provider_scope)"
    )
    op.execute(
        "DROP INDEX IF EXISTS uq_idp_legacy_shared_scope"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_idp_legacy_shared_scope "
        "ON identity_provider_configs (provider_scope) "
        "WHERE tenant_id IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_idp_legacy_shared_scope"
    )
    op.execute(
        "ALTER TABLE identity_provider_configs "
        "DROP CONSTRAINT IF EXISTS uq_idp_tenant_scope"
    )
