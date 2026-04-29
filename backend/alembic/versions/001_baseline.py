"""Baseline initial schema — all core platform tables.

Revision ID: 001_baseline
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Enums ────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE role_type_enum AS ENUM ('user', 'agent', 'both')")
    op.execute("CREATE TYPE identity_type_enum AS ENUM ('user', 'agent')")
    op.execute("CREATE TYPE mcp_server_status_enum AS ENUM ('active', 'inactive', 'error')")
    op.execute("CREATE TYPE mcp_session_auth_type_enum AS ENUM ('api_key', 'bearer_token', 'basic_auth', 'none')")
    op.execute("CREATE TYPE sop_step_type_enum AS ENUM ('skill', 'agent_delegation')")
    op.execute("CREATE TYPE agent_mode_enum AS ENUM ('sop-agent', 'skillful-agent')")
    op.execute("CREATE TYPE agent_instance_status_enum AS ENUM ('created', 'active', 'closed', 'error')")
    op.execute("CREATE TYPE conversation_status_enum AS ENUM ('active', 'closed', 'error')")
    op.execute("CREATE TYPE turn_role_enum AS ENUM ('user', 'agent', 'tool', 'system')")
    op.execute("CREATE TYPE job_target_type_enum AS ENUM ('agent', 'sop')")
    op.execute("CREATE TYPE job_status_enum AS ENUM ('active', 'paused', 'deleted')")
    op.execute("CREATE TYPE execution_status_enum AS ENUM ('success', 'failure', 'running')")
    op.execute("CREATE TYPE channel_type_enum AS ENUM ('email', 'slack', 'teams', 'webhook')")
    op.execute("CREATE TYPE delivery_status_enum AS ENUM ('pending', 'delivered', 'failed')")

    # ── Identity & Auth ──────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("role_type", postgresql.ENUM(name="role_type_enum", create_type=False), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    op.create_table(
        "identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("identity_type", postgresql.ENUM(name="identity_type_enum", create_type=False), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject"),
    )

    # ── MCP Hub ──────────────────────────────────────────────────────────────
    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_url", sa.String(2000), nullable=False),
        sa.Column("status", postgresql.ENUM(name="mcp_server_status_enum", create_type=False), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "mcp_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("auth_type", postgresql.ENUM(name="mcp_session_auth_type_enum", create_type=False), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("identity_subject", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_session_server_name"),
    )

    op.create_table(
        "mcp_tools",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("server_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(400), nullable=False),
        sa.Column("original_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_schema", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_tool_server_name"),
    )

    op.create_table(
        "tool_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["mcp_tools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tool_id", "role_id", name="uq_tool_permission_tool_role"),
    )

    # ── Skills & SOPs ────────────────────────────────────────────────────────
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "skill_tool_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["mcp_tools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "tool_id", name="uq_skill_tool_binding"),
    )

    op.create_table(
        "sops",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "sop_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("step_type", postgresql.ENUM(name="sop_step_type_enum", create_type=False), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("delegate_agent_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sop_id"], ["sops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Agent Engine ─────────────────────────────────────────────────────────
    op.create_table(
        "agent_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mode", postgresql.ENUM(name="agent_mode_enum", create_type=False), nullable=False),
        sa.Column("llm_provider", sa.String(100), nullable=False),
        sa.Column("llm_model", sa.String(200), nullable=False),
        sa.Column("encrypted_llm_credentials", sa.Text(), nullable=True),
        sa.Column("sop_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("max_instances", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("identity_subject", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sop_id"], ["sops.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "agent_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", postgresql.ENUM(name="agent_instance_status_enum", create_type=False), nullable=False),
        sa.Column("session_handle", sa.String(200), nullable=False),
        sa.Column("initiator_subject", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_type_id"], ["agent_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_handle"),
    )

    op.create_table(
        "agent_skill_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_type_id"], ["agent_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_type_id", "skill_id", name="uq_agent_skill_assignment"),
    )

    # ── Gateway ──────────────────────────────────────────────────────────────
    op.create_table(
        "gateway_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("http_base_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_type_id"),
    )

    # ── Conversations ────────────────────────────────────────────────────────
    op.create_table(
        "conversation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("initiator_subject", sa.String(500), nullable=True),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("status", postgresql.ENUM(name="conversation_status_enum", create_type=False), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_instance_id"], ["agent_instances.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", postgresql.ENUM(name="turn_role_enum", create_type=False), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tool_call_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(400), nullable=False),
        sa.Column("tool_input", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_output", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Results ──────────────────────────────────────────────────────────────
    op.create_table(
        "result_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(400), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("tags", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_instance_id"], ["agent_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_type_id"], ["agent_types.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_session_id"], ["conversation_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Scheduling ───────────────────────────────────────────────────────────
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("target_type", postgresql.ENUM(name="job_target_type_enum", create_type=False), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("status", postgresql.ENUM(name="job_status_enum", create_type=False), nullable=False),
        sa.Column("scheduler_job_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "job_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", postgresql.ENUM(name="execution_status_enum", create_type=False), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Notifications ────────────────────────────────────────────────────────
    op.create_table(
        "notification_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("channel_type", postgresql.ENUM(name="channel_type_enum", create_type=False), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("encrypted_config", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "notification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recipient", sa.String(500), nullable=True),
        sa.Column("status", postgresql.ENUM(name="delivery_status_enum", create_type=False), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("notification_events")
    op.drop_table("notification_channels")
    op.drop_table("job_executions")
    op.drop_table("scheduled_jobs")
    op.drop_table("result_records")
    op.drop_table("tool_call_records")
    op.drop_table("conversation_turns")
    op.drop_table("conversation_sessions")
    op.drop_table("gateway_routes")
    op.drop_table("agent_skill_assignments")
    op.drop_table("agent_instances")
    op.drop_table("agent_types")
    op.drop_table("sop_steps")
    op.drop_table("sops")
    op.drop_table("skill_tool_bindings")
    op.drop_table("skills")
    op.drop_table("tool_permissions")
    op.drop_table("mcp_tools")
    op.drop_table("mcp_sessions")
    op.drop_table("mcp_servers")
    op.drop_table("identities")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS delivery_status_enum")
    op.execute("DROP TYPE IF EXISTS channel_type_enum")
    op.execute("DROP TYPE IF EXISTS execution_status_enum")
    op.execute("DROP TYPE IF EXISTS job_status_enum")
    op.execute("DROP TYPE IF EXISTS job_target_type_enum")
    op.execute("DROP TYPE IF EXISTS turn_role_enum")
    op.execute("DROP TYPE IF EXISTS conversation_status_enum")
    op.execute("DROP TYPE IF EXISTS agent_instance_status_enum")
    op.execute("DROP TYPE IF EXISTS agent_mode_enum")
    op.execute("DROP TYPE IF EXISTS sop_step_type_enum")
    op.execute("DROP TYPE IF EXISTS mcp_session_auth_type_enum")
    op.execute("DROP TYPE IF EXISTS mcp_server_status_enum")
    op.execute("DROP TYPE IF EXISTS identity_type_enum")
    op.execute("DROP TYPE IF EXISTS role_type_enum")
