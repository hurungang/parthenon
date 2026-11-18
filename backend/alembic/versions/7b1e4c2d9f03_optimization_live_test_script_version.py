"""optimization live test script version

Revision ID: 7b1e4c2d9f03
Revises: 3d7c2a5940bc
Create Date: 2026-11-15 22:06:48.661397

Additive, reversible persistence for the script-level live test: a live test
runs the **script** end-to-end (never an individual MCP tool call), so the
ledger row must name the saved version the operator approved.

* add one nullable ``optimization_live_tests.script_version_id`` FK to
  ``script_versions.id`` with ``ON DELETE SET NULL`` (script retention must
  never destroy the audit row; the run is refused when the source is gone).

``requested_operations`` / ``executed_operations`` keep their column types — only
their MEANING changes (the tool-call preview and the script run record), so no
other DDL is required. No backfill (historical rows simply have no version), no
column drop, no conversation change.

Notes:
- Autogenerate also reported unrelated pre-existing drift (``tenant_id``
  nullability, ``super_admin_credentials``, identity-provider comments,
  ``tenant_invitations`` index uniqueness, role unique constraints); this
  revision was hand-reviewed and limited to the one column above.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7b1e4c2d9f03'
down_revision: str | None = '3d7c2a5940bc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SCRIPT_VERSION_FK_NAME = (
    'optimization_live_tests_script_version_id_fkey'
)


def upgrade() -> None:
    op.add_column(
        'optimization_live_tests',
        sa.Column(
            'script_version_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        _SCRIPT_VERSION_FK_NAME,
        'optimization_live_tests',
        'script_versions',
        ['script_version_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        _SCRIPT_VERSION_FK_NAME,
        'optimization_live_tests',
        type_='foreignkey',
    )
    op.drop_column('optimization_live_tests', 'script_version_id')
