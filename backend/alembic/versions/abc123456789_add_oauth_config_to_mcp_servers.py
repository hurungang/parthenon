"""add_oauth_config_to_mcp_servers

Revision ID: f8a9b2c3d4e5
Revises: 06519db12d6e
Create Date: 2026-05-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f8a9b2c3d4e5'
down_revision = '06519db12d6e'
branch_labels = None
depends_on = None


def upgrade():
    # Add oauth_config JSON column to mcp_servers table
    op.add_column('mcp_servers', sa.Column('oauth_config', postgresql.JSON(astext_type=sa.Text()), nullable=True))


def downgrade():
    # Remove oauth_config column
    op.drop_column('mcp_servers', 'oauth_config')
