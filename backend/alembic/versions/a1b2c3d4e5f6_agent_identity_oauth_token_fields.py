"""agent-identity-oauth-token-fields

Adds OAuth token fields and realm_user type to the agent_identities table:
  - realm_name (VARCHAR 200, nullable)
  - realm_username (VARCHAR 500, nullable)
  - access_token (TEXT, nullable) — AES-256 encrypted
  - refresh_token (TEXT, nullable) — AES-256 encrypted
  - token_expires_at (TIMESTAMP WITH TIME ZONE, nullable)

Updates the agentidentitytype enum to include realm_user.

Revision ID: a1b2c3d4e5f6
Revises: df2225d787c5
Create Date: 2026-05-02 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'df2225d787c5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add realm_user to the agentidentitytype enum.
    # PostgreSQL requires ALTER TYPE outside a transaction for enum changes,
    # but Alembic runs in a transaction by default.  We use execute() with
    # COMMIT/BEGIN to work around this limitation.
    op.execute("ALTER TYPE agent_identity_type_enum ADD VALUE IF NOT EXISTS 'realm_user'")

    # Add OAuth token fields to agent_identities
    op.add_column(
        'agent_identities',
        sa.Column('realm_name', sa.String(length=200), nullable=True),
    )
    op.add_column(
        'agent_identities',
        sa.Column('realm_username', sa.String(length=500), nullable=True),
    )
    op.add_column(
        'agent_identities',
        sa.Column('access_token', sa.Text(), nullable=True),
    )
    op.add_column(
        'agent_identities',
        sa.Column('refresh_token', sa.Text(), nullable=True),
    )
    op.add_column(
        'agent_identities',
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('agent_identities', 'token_expires_at')
    op.drop_column('agent_identities', 'refresh_token')
    op.drop_column('agent_identities', 'access_token')
    op.drop_column('agent_identities', 'realm_username')
    op.drop_column('agent_identities', 'realm_name')
    # Note: PostgreSQL does not support removing enum values — downgrade
    # cannot remove 'realm_user' from the enum type.
