"""make_api_key_name_unique

Revision ID: cf44fe226b0d
Revises: 65b29c8fcdbc
Create Date: 2026-08-24 21:06:17.607186

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'cf44fe226b0d'
down_revision: str | None = '65b29c8fcdbc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # API keys may now be created freely per identity-role pair; key names are unique.
    op.drop_constraint('uq_agent_api_keys_identity_role', 'agent_api_keys', type_='unique')
    op.create_unique_constraint('uq_agent_api_keys_name', 'agent_api_keys', ['name'])


def downgrade() -> None:
    op.drop_constraint('uq_agent_api_keys_name', 'agent_api_keys', type_='unique')
    op.create_unique_constraint('uq_agent_api_keys_identity_role', 'agent_api_keys', ['agent_identity_id', 'agent_role_id'])
