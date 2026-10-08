"""SQLAlchemy models for MCP Hub: McpServer, McpSession, McpTool, ToolPermission."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class McpServerStatus(str, enum.Enum):
    """Connection/sync status of an MCP server."""

    active = "active"
    inactive = "inactive"
    error = "error"


class McpServer(Base):
    """A registered external tool server.

    Tenant ownership is mandatory (strict tenant isolation): every server
    belongs to exactly one tenant and ``slug`` is unique **per tenant**
    (business identity is ``(tenant_id, slug)``) — the platform-wide slug
    uniqueness was retired. The ORM column stays nullable for legacy
    code paths; the database enforces NOT NULL via migration
    ``b8c9d0e1f2a3`` after NULL-tenant rows are adopted into the root
    tenant.
    """

    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_mcp_servers_tenant_slug"),
        Index("ix_mcp_servers_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # OAuth configuration for server-level authentication (auto-discovered or manually configured)
    oauth_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[McpServerStatus] = mapped_column(
        Enum(McpServerStatus, name="mcp_server_status_enum"),
        nullable=False,
        default=McpServerStatus.active,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    sessions: Mapped[list["McpSession"]] = relationship(
        "McpSession", back_populates="server", cascade="all, delete-orphan"
    )
    tools: Mapped[list["McpTool"]] = relationship(
        "McpTool", back_populates="server", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<McpServer id={self.id} slug={self.slug}>"


class McpSessionAuthType(str, enum.Enum):
    """How credentials are provided for an MCP session."""

    api_key = "api_key"
    bearer_token = "bearer_token"
    basic_auth = "basic_auth"
    oauth2 = "oauth2"
    none = "none"
    passthrough = "passthrough"


class McpSession(Base):
    """A named connection configuration on an MCP server with encrypted credentials."""

    __tablename__ = "mcp_sessions"
    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_mcp_session_server_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[McpSessionAuthType] = mapped_column(
        Enum(McpSessionAuthType, name="mcp_session_auth_type_enum"),
        nullable=False,
        default=McpSessionAuthType.api_key,
    )
    # AES-256 encrypted credential payload (JSON blob)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional binding to an agent identity or role
    identity_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Structured binding info for agent identity/role (extends identity_subject)
    identity_binding: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Session-specific credential configuration (field shape, required keys)
    credential_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # OAuth token expiry tracking
    oauth_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    oauth_refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # OAuth metadata (token_url, client_id, etc. for token refresh)
    oauth_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    server: Mapped["McpServer"] = relationship("McpServer", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<McpSession id={self.id} name={self.name} server_id={self.server_id}>"


class McpTool(Base):
    """A tool synced from an MCP server, namespaced under the server slug.

    Carries a denormalized ``tenant_id`` (defense in depth — tool lookups
    in hot paths do not need to join through the server to prove tenant
    containment). The server remains the source of truth; the tool's
    tenant always equals its server's tenant (kept consistent by tool
    sync). NOT NULL is enforced at the database level by migration
    ``b8c9d0e1f2a3``; the ORM column stays nullable for legacy paths.
    """

    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_mcp_tool_server_name"),
        Index("ix_mcp_tools_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized tenant binding — must always equal the owning server's tenant.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    # Namespaced name: "{slug}/{tool_name}"
    name: Mapped[str] = mapped_column(String(400), nullable=False)
    # Original tool name on the server
    original_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON Schema for the tool's input parameters
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    server: Mapped["McpServer"] = relationship("McpServer", back_populates="tools")
    permissions: Mapped[list["ToolPermission"]] = relationship(
        "ToolPermission", back_populates="tool", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<McpTool id={self.id} name={self.name}>"


class ToolPermission(Base):
    """Grants a Role or Identity access to a specific MCP tool."""

    __tablename__ = "tool_permissions"
    __table_args__ = (
        UniqueConstraint("tool_id", "role_id", name="uq_tool_permission_tool_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_tools.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    tool: Mapped["McpTool"] = relationship("McpTool", back_populates="permissions")
    role: Mapped["Role"] = relationship("Role")

    def __repr__(self) -> str:
        return f"<ToolPermission id={self.id} tool_id={self.tool_id} role_id={self.role_id}>"


# Import Role here to avoid circular imports at module load time
from app.db.models.identity import Role  # noqa: E402, F401
