"""drop_slug_from_skills_and_sops

Revision ID: e2a947f81c33
Revises: d1f833e19674
Create Date: 2026-05-26 11:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'e2a947f81c33'
down_revision: str | None = 'd1f833e19674'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index('ix_skills_slug', table_name='skills')
    op.drop_index('ix_sops_slug', table_name='sops')
    op.drop_constraint('uq_skills_slug', 'skills', type_='unique')
    op.drop_constraint('uq_sops_slug', 'sops', type_='unique')
    op.drop_column('skills', 'slug')
    op.drop_column('sops', 'slug')


def downgrade() -> None:
    op.add_column('sops', sa.Column('slug', sa.String(200), nullable=True))
    op.add_column('skills', sa.Column('slug', sa.String(200), nullable=True))
    op.create_unique_constraint('uq_sops_slug', 'sops', ['slug'])
    op.create_unique_constraint('uq_skills_slug', 'skills', ['slug'])
    op.create_index('ix_sops_slug', 'sops', ['slug'], unique=True)
    op.create_index('ix_skills_slug', 'skills', ['slug'], unique=True)
