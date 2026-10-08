"""Allow virtual tool ids in skill_tool_bindings.

Decision tools are VIRTUAL MCP-hub entries (no ``mcp_tools`` row) — skill
bindings that reference them store a deterministic uuid5 id
(``decision-tool:<decision_tool_id>``). The database-level FK on
``skill_tool_bindings.tool_id`` would reject such ids, so it is dropped;
referential integrity for regular MCP tools is enforced by the skills API
validation layer (same place system-tool ids are validated).

Revision ID: f1e2d3c4b5a6
Revises: d5e6a7b8c9d0
Create Date: 2026-10-06
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1e2d3c4b5a6"
down_revision = "d5e6a7b8c9d0"
branch_labels = None
depends_on = None

_CONSTRAINT = "skill_tool_bindings_tool_id_fkey"


def upgrade() -> None:
    op.execute(f"ALTER TABLE skill_tool_bindings DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_skill_tool_bindings_tool_id "
        "ON skill_tool_bindings (tool_id)"
    )


def downgrade() -> None:
    # Re-adding the FK rejects rows bound to virtual decision tool ids;
    # clean those up first so the downgrade is reversible.
    op.execute(
        "DELETE FROM skill_tool_bindings b WHERE NOT EXISTS "
        "(SELECT 1 FROM mcp_tools t WHERE t.id = b.tool_id)"
    )
    op.execute(
        f"ALTER TABLE skill_tool_bindings ADD CONSTRAINT {_CONSTRAINT} "
        "FOREIGN KEY (tool_id) REFERENCES mcp_tools (id) ON DELETE CASCADE"
    )
    op.execute("DROP INDEX IF EXISTS ix_skill_tool_bindings_tool_id")
