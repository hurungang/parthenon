"""per-tenant entity adoption and mcp slug scoping

strict-tenant-isolation, Phases 2 & 3 (schema):

1. **Adoption** — every NULL-tenant data-plane row is adopted once into
   the root tenant (``tenants.is_system_tenant``), retiring the
   "NULL tenant = shared/global" slot. Idempotent: only rows still NULL
   are updated; a no-op when the root tenant does not exist yet.
2. **MCP hub scoping** — ``mcp_servers.slug`` uniqueness becomes
   per-tenant (``uq_mcp_servers_tenant_slug``); the platform-wide unique
   constraint is dropped. ``mcp_tools`` gains a denormalized ``tenant_id``
   (must always equal its server's tenant), indexed and FK-bound.
3. **NULL-variant retirement** — the ``uq_*_global_*`` partial unique
   indexes (NULL-tenant name/slug variants from a7b9c1d3e5f7) are
   removed; per-tenant uniqueness is the only rule.
4. **NOT NULL enforcement** — after adoption guarantees zero NULLs,
   ``tenant_id`` becomes mandatory on all covered tables.

Downgrade restores the previous schema only (platform-wide slug unique,
global partial indexes, nullable ``tenant_id``); rows adopted into the
root tenant cannot safely return to NULL — that data state is preserved.

Revision ID: b8c9d0e1f2a3
Revises: a7b9c1d3e5f7
Create Date: 2026-10-07 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b9c1d3e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables whose NULL-tenant rows are adopted into the root tenant and whose
# ``tenant_id`` becomes NOT NULL afterwards (all guaranteed NULL-free by
# the adoption UPDATE that immediately precedes the constraint swap).
_ADOPT_AND_REQUIRE_TENANT: list[str] = [
    "mcp_servers",
    "agent_data",
    "agent_outputs",
    "agent_data_types",
    "scheduled_jobs",
    "notification_channels",
    "recipient_groups",
    "skills",
    "sops",
    "agent_types",
    "model_configs",
    "groups",
    "tag_definitions",
    "agent_api_keys",
    "agent_roles",
    "agent_identities",
]

# NULL-tenant partial unique indexes retired by this migration (mirrors
# the model __table_args__ removed alongside).
_RETIRED_GLOBAL_INDEXES: list[str] = [
    "uq_model_configs_global_display_name",
    "uq_agent_roles_global_name",
    "uq_agent_identities_global_name",
    "uq_agent_types_global_name",
    "uq_skills_global_name",
    "uq_sops_global_name",
    "uq_agent_data_types_global_name",
    "uq_agent_data_types_global_slug",
    "uq_groups_global_name",
    "uq_tag_definitions_global_key",
    "uq_scheduled_jobs_global_name",
    "uq_notification_channels_global_name",
    "uq_recipient_groups_global_name",
    "uq_recipient_groups_global_slug",
    "uq_agent_api_keys_global_name",
]

# (table, column, index name) — for rebuilding the retired partial unique
# indexes on downgrade.
_RETIRED_GLOBAL_INDEX_COLUMNS: list[tuple[str, str, str]] = [
    ("model_configs", "display_name", "uq_model_configs_global_display_name"),
    ("agent_roles", "name", "uq_agent_roles_global_name"),
    ("agent_identities", "name", "uq_agent_identities_global_name"),
    ("agent_types", "name", "uq_agent_types_global_name"),
    ("skills", "name", "uq_skills_global_name"),
    ("sops", "name", "uq_sops_global_name"),
    ("agent_data_types", "name", "uq_agent_data_types_global_name"),
    ("agent_data_types", "slug", "uq_agent_data_types_global_slug"),
    ("groups", "name", "uq_groups_global_name"),
    ("tag_definitions", "key", "uq_tag_definitions_global_key"),
    ("scheduled_jobs", "name", "uq_scheduled_jobs_global_name"),
    ("notification_channels", "name", "uq_notification_channels_global_name"),
    ("recipient_groups", "name", "uq_recipient_groups_global_name"),
    ("recipient_groups", "slug", "uq_recipient_groups_global_slug"),
    ("agent_api_keys", "name", "uq_agent_api_keys_global_name"),
]


def _root_tenant_exists(bind) -> bool:  # type: ignore[no-untyped-def]
    row = bind.execute(
        __import__("sqlalchemy").text(
            "SELECT 1 FROM tenants WHERE is_system_tenant LIMIT 1"
        )
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (unit tests): fresh schemas come from the models'
        # table_args — the tightening below is PostgreSQL-only.
        return
    from sqlalchemy import text

    has_root = _root_tenant_exists(bind)

    # ── 1. Adoption: NULL-tenant rows → root tenant (idempotent) ──────
    if has_root:
        for table in _ADOPT_AND_REQUIRE_TENANT:
            # Plain SQL with string formatting — no parameterized DDL.
            bind.execute(
                text(
                    f"UPDATE {table} SET tenant_id = "
                    f"(SELECT id FROM tenants WHERE is_system_tenant LIMIT 1) "
                    f"WHERE tenant_id IS NULL"
                )
            )

    # ── 2. McpTool denormalized tenant binding ─────────────────────────
    bind.execute(
        text(
            "ALTER TABLE mcp_tools ADD COLUMN IF NOT EXISTS tenant_id UUID"
        )
    )
    bind.execute(
        text(
            "UPDATE mcp_tools t SET tenant_id = s.tenant_id "
            "FROM mcp_servers s "
            "WHERE t.server_id = s.id AND t.tenant_id IS NULL"
        )
    )
    bind.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_mcp_tools_tenant_id "
            "ON mcp_tools (tenant_id)"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE mcp_tools DROP CONSTRAINT IF EXISTS fk_mcp_tools_tenant_id"
        )
    )
    bind.execute(
        text(
            "ALTER TABLE mcp_tools ADD CONSTRAINT fk_mcp_tools_tenant_id "
            "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE SET NULL"
        )
    )

    # ── 3. McpServer slug: platform-wide → per-tenant ─────────────────
    bind.execute(
        text("ALTER TABLE mcp_servers DROP CONSTRAINT IF EXISTS mcp_servers_slug_key")
    )
    bind.execute(
        text(
            "ALTER TABLE mcp_servers ADD CONSTRAINT uq_mcp_servers_tenant_slug "
            "UNIQUE (tenant_id, slug)"
        )
    )

    # ── 4. Retire NULL-tenant partial unique variants ─────────────────
    for index_name in _RETIRED_GLOBAL_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {index_name}"))

    # ── 5. NOT NULL enforcement (only when adoption guarantees it) ────
    if has_root:
        for table in _ADOPT_AND_REQUIRE_TENANT:
            bind.execute(
                text(
                    f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL"
                )
            )
        bind.execute(
            text("ALTER TABLE mcp_tools ALTER COLUMN tenant_id SET NOT NULL")
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    # ── 5r. Relax NOT NULL (reverse of upgrade step 5) ────────────────
    for table in _ADOPT_AND_REQUIRE_TENANT:
        bind.execute(
            text(f"ALTER TABLE {table} ALTER COLUMN tenant_id DROP NOT NULL")
        )
    bind.execute(
        text("ALTER TABLE mcp_tools ALTER COLUMN tenant_id DROP NOT NULL")
    )

    # ── 4r. Restore NULL-tenant partial unique variants ───────────────
    for table, column, index_name in _RETIRED_GLOBAL_INDEX_COLUMNS:
        bind.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                f"ON {table} ({column}) WHERE tenant_id IS NULL"
            )
        )

    # ── 3r. Restore platform-wide mcp_servers.slug uniqueness ─────────
    bind.execute(
        text(
            "ALTER TABLE mcp_servers DROP CONSTRAINT IF EXISTS uq_mcp_servers_tenant_slug"
        )
    )
    # May fail if same-slug servers were registered in different tenants
    # while multi-tenant mode was on — an operator-visible data condition
    # that is not silently destroyed here.
    bind.execute(
        text(
            "ALTER TABLE mcp_servers ADD CONSTRAINT mcp_servers_slug_key UNIQUE (slug)"
        )
    )

    # ── 2r. Drop the denormalized mcp_tools tenant binding ────────────
    bind.execute(
        text(
            "ALTER TABLE mcp_tools DROP CONSTRAINT IF EXISTS fk_mcp_tools_tenant_id"
        )
    )
    bind.execute(text("DROP INDEX IF EXISTS ix_mcp_tools_tenant_id"))
    bind.execute(text("ALTER TABLE mcp_tools DROP COLUMN IF EXISTS tenant_id"))

    # ── 1r. Note: adopted rows keep their root-tenant binding — the
    # NULL "shared slot" cannot be safely re-created; downgrade restores
    # schema only.
