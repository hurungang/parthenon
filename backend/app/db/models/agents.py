"""SQLAlchemy models for Agent management: AgentRole, AgentIdentity, AgentType, AgentJob."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class AgentIdentityType(str, enum.Enum):
    """Type of OIDC principal representing an agent's credentials."""

    realm_user = "realm_user"
    # Legacy values retained for migration compatibility
    oauth = "oauth"
    service_account = "service_account"
    user_delegate = "user_delegate"


class AgentIdentityStatus(str, enum.Enum):
    """Lifecycle status of an agent identity."""

    active = "active"
    suspended = "suspended"
    deprovisioned = "deprovisioned"


class AgentInputType(str, enum.Enum):
    """How an agent accepts input."""

    none = "none"
    typed = "typed"
    conversation = "conversation"


class AgentOutputType(str, enum.Enum):
    """How an agent produces output."""

    auto = "auto"
    typed = "typed"
    markdown = "markdown"


class AgentJobStatus(str, enum.Enum):
    """Lifecycle status of an agent job."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class AgentInstanceStatus(str, enum.Enum):
    """Lifecycle status of a legacy agent instance."""

    created = "created"
    active = "active"
    closed = "closed"
    error = "error"


# ── Role Models ───────────────────────────────────────────────────────────────


class AgentRole(Base):
    """A named permission set granting access to specific SOPs and/or Skills."""

    __tablename__ = "agent_roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    sop_assignments: Mapped[list["AgentRoleSOP"]] = relationship(
        "AgentRoleSOP", back_populates="role", cascade="all, delete-orphan"
    )
    skill_assignments: Mapped[list["AgentRoleSkill"]] = relationship(
        "AgentRoleSkill", back_populates="role", cascade="all, delete-orphan"
    )
    agent_types: Mapped[list["AgentType"]] = relationship(
        "AgentType", back_populates="role"
    )

    def __repr__(self) -> str:
        return f"<AgentRole id={self.id} name={self.name}>"


class AgentRoleSOP(Base):
    """Join table linking an AgentRole to a Sop."""

    __tablename__ = "agent_role_sops"
    __table_args__ = (
        UniqueConstraint("role_id", "sop_id", name="uq_agent_role_sop"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sops.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Relationships
    role: Mapped["AgentRole"] = relationship("AgentRole", back_populates="sop_assignments")
    sop: Mapped["Sop"] = relationship("Sop")

    def __repr__(self) -> str:
        return f"<AgentRoleSOP role_id={self.role_id} sop_id={self.sop_id}>"


class AgentRoleSkill(Base):
    """Join table linking an AgentRole to a Skill."""

    __tablename__ = "agent_role_skills"
    __table_args__ = (
        UniqueConstraint("role_id", "skill_id", name="uq_agent_role_skill"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Relationships
    role: Mapped["AgentRole"] = relationship("AgentRole", back_populates="skill_assignments")
    skill: Mapped["Skill"] = relationship("Skill")

    def __repr__(self) -> str:
        return f"<AgentRoleSkill role_id={self.role_id} skill_id={self.skill_id}>"


# ── Identity Model ────────────────────────────────────────────────────────────


class AgentIdentity(Base):
    """A first-class OIDC principal representing an agent's credentials in the identity provider."""

    __tablename__ = "agent_identities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    identity_type: Mapped[AgentIdentityType] = mapped_column(
        Enum(AgentIdentityType, name="agent_identity_type_enum"), nullable=False
    )
    # OAuth agent realm fields (used when identity_type = realm_user)
    realm_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    realm_username: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # AES-256 encrypted OAuth tokens (nullable until OAuth flow completes)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Legacy fields (kept for backward compatibility with existing records)
    client_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[AgentIdentityStatus] = mapped_column(
        Enum(AgentIdentityStatus, name="agent_identity_status_enum"),
        nullable=False,
        default=AgentIdentityStatus.active,
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
    agent_types: Mapped[list["AgentType"]] = relationship(
        "AgentType", back_populates="identity"
    )

    def __repr__(self) -> str:
        return f"<AgentIdentity id={self.id} name={self.name} status={self.status}>"


# ── AgentType ─────────────────────────────────────────────────────────────────


class AgentType(Base):
    """Definition of an agent: role, identity, model binding, and input/output configuration."""

    __tablename__ = "agent_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Identity and role
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_identities.id", ondelete="SET NULL"),
        nullable=True,
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_roles.id", ondelete="SET NULL"),
        nullable=True,
    )

    # LLM provider configuration
    llm_provider: Mapped[str] = mapped_column(String(100), nullable=False, default="openai")
    llm_model: Mapped[str] = mapped_column(String(200), nullable=False, default="gpt-4o")
    # AES-encrypted LLM API credentials
    encrypted_llm_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Instruction and I/O configuration
    system_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_type: Mapped[AgentInputType] = mapped_column(
        Enum(AgentInputType, name="agent_input_type_enum"),
        nullable=False,
        default=AgentInputType.none,
    )
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_type: Mapped[AgentOutputType] = mapped_column(
        Enum(AgentOutputType, name="agent_output_type_enum"),
        nullable=False,
        default=AgentOutputType.auto,
    )
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

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
    identity: Mapped["AgentIdentity | None"] = relationship(
        "AgentIdentity", back_populates="agent_types"
    )
    role: Mapped["AgentRole | None"] = relationship(
        "AgentRole", back_populates="agent_types"
    )
    instances: Mapped[list["AgentInstance"]] = relationship(
        "AgentInstance", back_populates="agent_type", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["AgentJob"]] = relationship(
        "AgentJob", back_populates="agent_type", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentType id={self.id} name={self.name}>"


# ── AgentInstance (legacy — superseded by AgentJob in Phase 5) ───────────────


class AgentInstance(Base):
    """Legacy runtime instance of an AgentType. Superseded by AgentJob in Phase 5."""

    __tablename__ = "agent_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_types.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AgentInstanceStatus] = mapped_column(
        Enum(AgentInstanceStatus, name="agent_instance_status_enum"),
        nullable=False,
        default=AgentInstanceStatus.created,
    )
    # Session handle token returned to the caller
    session_handle: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    # External caller identifier
    initiator_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent_type: Mapped["AgentType"] = relationship("AgentType", back_populates="instances")

    def __repr__(self) -> str:
        return f"<AgentInstance id={self.id} type_id={self.agent_type_id} status={self.status}>"


# ── AgentJob ──────────────────────────────────────────────────────────────────


class AgentJob(Base):
    """Tracks a single agent execution session from submission through completion."""

    __tablename__ = "agent_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_types.id", ondelete="CASCADE"), nullable=False
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identities.id", ondelete="SET NULL"), nullable=True
    )
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[AgentJobStatus] = mapped_column(
        Enum(AgentJobStatus, name="agent_job_status_enum"),
        nullable=False,
        default=AgentJobStatus.queued,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    agent_type: Mapped["AgentType"] = relationship("AgentType", back_populates="jobs")

    def __repr__(self) -> str:
        return f"<AgentJob id={self.id} type_id={self.agent_type_id} status={self.status}>"


# Resolve forward references
from app.db.models.skills import Skill, Sop  # noqa: E402, F401
