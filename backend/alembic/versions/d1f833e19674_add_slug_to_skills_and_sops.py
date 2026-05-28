"""add_slug_to_skills_and_sops

Revision ID: d1f833e19674
Revises: 9f8c6e2b4a1d
Create Date: 2026-05-26 10:16:08.589354

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd1f833e19674'
down_revision: str | None = '9f8c6e2b4a1d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add nullable first so existing rows are not rejected
    op.add_column('skills', sa.Column('slug', sa.String(200), nullable=True))
    op.add_column('sops', sa.Column('slug', sa.String(200), nullable=True))

    # Populate from name (basic slugify in SQL)
    op.execute("UPDATE skills SET slug = LOWER(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(name), '[^a-zA-Z0-9 -]', '', 'g'), '[ _]+', '-', 'g'), '-+', '-', 'g'))")
    op.execute("UPDATE sops SET slug = LOWER(REGEXP_REPLACE(REGEXP_REPLACE(REGEXP_REPLACE(TRIM(name), '[^a-zA-Z0-9 -]', '', 'g'), '[ _]+', '-', 'g'), '-+', '-', 'g'))")

    # Handle uniqueness conflicts by appending short id suffix
    op.execute("UPDATE skills s1 SET slug = s1.slug || '-' || LEFT(s1.id::text, 8) WHERE (SELECT COUNT(*) FROM skills s2 WHERE s2.slug = s1.slug AND s2.id != s1.id) > 0")
    op.execute("UPDATE sops s1 SET slug = s1.slug || '-' || LEFT(s1.id::text, 8) WHERE (SELECT COUNT(*) FROM sops s2 WHERE s2.slug = s1.slug AND s2.id != s1.id) > 0")

    # Make NOT NULL and add constraints
    op.alter_column('skills', 'slug', nullable=False)
    op.alter_column('sops', 'slug', nullable=False)
    op.create_unique_constraint('uq_skills_slug', 'skills', ['slug'])
    op.create_unique_constraint('uq_sops_slug', 'sops', ['slug'])
    op.create_index('ix_skills_slug', 'skills', ['slug'], unique=True)
    op.create_index('ix_sops_slug', 'sops', ['slug'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_sops_slug', table_name='sops')
    op.drop_index('ix_skills_slug', table_name='skills')
    op.drop_constraint('uq_sops_slug', 'sops', type_='unique')
    op.drop_constraint('uq_skills_slug', 'skills', type_='unique')
    op.drop_column('sops', 'slug')
    op.drop_column('skills', 'slug')
