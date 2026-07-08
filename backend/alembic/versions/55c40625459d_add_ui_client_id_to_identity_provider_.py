"""add_ui_client_id_to_identity_provider_config

Revision ID: 55c40625459d
Revises: 49ab45b8226e
Create Date: 2026-07-08 12:47:42.234217

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '55c40625459d'
down_revision: str | None = '49ab45b8226e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('identity_provider_configs', sa.Column('ui_client_id', sa.String(length=500), nullable=True, comment='Public OIDC client ID for frontend PKCE login (no secret). Only used for user scope.'))


def downgrade() -> None:
    op.drop_column('identity_provider_configs', 'ui_client_id')
