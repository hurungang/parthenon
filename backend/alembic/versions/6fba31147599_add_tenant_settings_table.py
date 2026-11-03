"""add tenant_settings table

Per-tenant key/value settings store (first consumer: the per-tenant
workflow-generation model selection, replacing the global
``config/app.yaml`` value).

Revision ID: 6fba31147599
Revises: 1a0ed55b8cf1
Create Date: 2026-10-31 11:53:06.369888

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6fba31147599'
down_revision: str | None = '1a0ed55b8cf1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('tenant_settings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('value', postgresql.JSON(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tenant_settings_tenant_id'), 'tenant_settings', ['tenant_id'], unique=False)
    op.create_index('uq_tenant_settings_tenant_key', 'tenant_settings', ['tenant_id', 'key'], unique=True)


def downgrade() -> None:
    op.drop_index('uq_tenant_settings_tenant_key', table_name='tenant_settings')
    op.drop_index(op.f('ix_tenant_settings_tenant_id'), table_name='tenant_settings')
    op.drop_table('tenant_settings')
