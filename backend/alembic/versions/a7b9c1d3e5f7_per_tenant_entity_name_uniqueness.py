"""per-tenant entity name/slug uniqueness

Multi-tenancy: entity display names / slugs become unique **per tenant**
instead of platform-wide, so identical names in different tenants do not
collide (same treatment as roles in c8e2f5b17a93).  Global (tenant-less)
rows keep platform-wide unique names via partial unique indexes.

Note: ``mcp_servers.slug`` intentionally stays platform-wide — the slug is
the namespace for all synced tools (project convention).

- ``model_guardrail_configurations`` is untouched: its constraint spans
  ``model_id`` which is a real FK to ``model_configs`` (per-tenant already
  via the parent row).

Re-scoped tables/columns:

- model_configs.display_name
- agent_roles.name
- agent_identities.name
- agent_types.name
- skills.name
- sops.name
- agent_data_types.name / .slug
- groups.name
- tag_definitions.key
- scheduled_jobs.name
- notification_channels.name
- recipient_groups.name / .slug
- agent_api_keys.name (uq_agent_api_keys_name)

Revision ID: a7b9c1d3e5f7
Revises: f1e2d3c4b5a6
Create Date: 2026-10-07 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b9c1d3e5f7"
down_revision: str | None = "f1e2d3c4b5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, old constraint-or-index name, column, tenant-constraint name)
_TARGETS: list[tuple[str, str, str, str]] = [
    ("model_configs", "model_configs_display_name_key", "display_name", "uq_model_configs_tenant_display_name"),
    ("agent_roles", "agent_roles_name_key", "name", "uq_agent_roles_tenant_name"),
    ("agent_identities", "agent_identities_name_key", "name", "uq_agent_identities_tenant_name"),
    ("agent_types", "agent_types_name_key", "name", "uq_agent_types_tenant_name"),
    ("skills", "skills_name_key", "name", "uq_skills_tenant_name"),
    ("sops", "sops_name_key", "name", "uq_sops_tenant_name"),
    ("agent_data_types", "agent_data_types_name_key", "name", "uq_agent_data_types_tenant_name"),
    ("agent_data_types", "agent_data_types_slug_key", "slug", "uq_agent_data_types_tenant_slug"),
    ("groups", "groups_name_key", "name", "uq_groups_tenant_name"),
    ("tag_definitions", "tag_definitions_key_key", "key", "uq_tag_definitions_tenant_key"),
    ("scheduled_jobs", "scheduled_jobs_name_key", "name", "uq_scheduled_jobs_tenant_name"),
    ("notification_channels", "notification_channels_name_key", "name", "uq_notification_channels_tenant_name"),
    ("recipient_groups", "recipient_groups_name_key", "name", "uq_recipient_groups_tenant_name"),
    ("recipient_groups", "recipient_groups_slug_key", "slug", "uq_recipient_groups_tenant_slug"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (unit tests) stores unique constraints inline — the
        # models' table_args carry the new semantics for fresh schemas.
        return
    # PostgreSQL does not support parameterized DDL — plain SQL per
    # project migration conventions.
    for table, old_name, column, tenant_name in _TARGETS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {old_name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {tenant_name} "
            f"UNIQUE (tenant_id, {column})"
        )
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_global_{column} "
            f"ON {table} ({column}) WHERE tenant_id IS NULL"
        )
    # agent_api_keys: named platform-wide constraint → per-tenant.
    op.execute("ALTER TABLE agent_api_keys DROP CONSTRAINT IF EXISTS uq_agent_api_keys_name")
    op.execute(
        "ALTER TABLE agent_api_keys ADD CONSTRAINT uq_agent_api_keys_tenant_name "
        "UNIQUE (tenant_id, name)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_api_keys_global_name "
        "ON agent_api_keys (name) WHERE tenant_id IS NULL"
    )
    # recipient_groups.slug was a unique *index* (unique=True, index=True),
    # not a constraint — re-create it as a plain index.
    op.execute("DROP INDEX IF EXISTS ix_recipient_groups_slug")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recipient_groups_slug "
        "ON recipient_groups (slug)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Reversing to platform-wide uniqueness could fail if duplicates were
    # created across tenants while multi-tenant mode was on; that is an
    # operator-visible data condition and not silently destroyed here.
    op.execute("DROP INDEX IF EXISTS ix_recipient_groups_slug")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_recipient_groups_slug "
        "ON recipient_groups (slug)"
    )
    op.execute("DROP INDEX IF EXISTS uq_agent_api_keys_global_name")
    op.execute(
        "ALTER TABLE agent_api_keys DROP CONSTRAINT IF EXISTS uq_agent_api_keys_tenant_name"
    )
    op.execute(
        "ALTER TABLE agent_api_keys ADD CONSTRAINT uq_agent_api_keys_name UNIQUE (name)"
    )
    for table, old_name, column, tenant_name in reversed(_TARGETS):
        op.execute(f"DROP INDEX IF EXISTS uq_{table}_global_{column}")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {tenant_name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {old_name} UNIQUE ({column})")
