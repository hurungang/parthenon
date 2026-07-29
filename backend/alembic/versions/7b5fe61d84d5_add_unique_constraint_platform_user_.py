"""add_unique_constraint_platform_user_email

Revision ID: 7b5fe61d84d5
Revises: 55c40625459d
Create Date: 2026-07-29 08:44:27.409060

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7b5fe61d84d5'
down_revision: str | None = '55c40625459d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint('uq_platform_user_email', 'platform_users', ['email'])


def downgrade() -> None:
    op.drop_constraint('uq_platform_user_email', 'platform_users', type_='unique')
