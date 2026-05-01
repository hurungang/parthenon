"""SQLAlchemy models for Agent management: AgentType, AgentInstance, AgentSkillAssignment."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AgentMode(str, enum.Enum):
    """Operating mode of an agent type."""

    sop_agent = "sop-agent"
    skillful_agent = "skillful-agent"


class AgentInstanceStatus(str, enum.Enum):
    """Lifecycle status of an agent instance."""

    created = "created"
    active = "active"
    closed = "closed"
    error = "error"


class AgentType(Base):
    """
    Definition of an agent: operating mode, identity, model binding, and instance limits.
    """

    __tablename__ = "agent_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[AgentMode] = mapped_column(Enum(AgentMode, name="agent_mode_enum"), nullable=False)
    # LLM provider configuration
    llm_provider: Mapped[str] = mapped_column(String(100), nullable=False, default="openai")
    llm_model: Mapped[str] = mapped_column(String(200), nullable=False, default="gpt-4o")
    # AES-encrypted LLM API credentials
    encrypted_llm_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For sop-agent: bound SOP
    sop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sops.id", ondelete="SET NULL"), nullable=True
    )
    max_instances: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # System prompt override
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # OIDC identity subject for this agent type (provisioned after creation)
    identity_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    sop: Mapped["Sop | None"] = relationship("Sop")
    instances: Mapped[list["AgentInstance"]] = relationship(
        "AgentInstance", back_populates="agent_type", cascade="all, delete-orphan"
    )
    skill_assignments: Mapped[list["AgentSkillAssignment"]] = relationship(
        "AgentSkillAssignment", back_populates="agent_type", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentType id={self.id} name={self.name} mode={self.mode}>"


class AgentInstance(Base):
    """A runtime instance of an AgentType with lifecycle status."""

    __tablename__ = "agent_instances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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


class AgentSkillAssignment(Base):
    """Links a Skill to a skillful-agent AgentType."""

    __tablename__ = "agent_skill_assignments"
    __table_args__ = (
        UniqueConstraint("agent_type_id", "skill_id", name="uq_agent_skill_assignment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_types.id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    agent_type: Mapped["AgentType"] = relationship("AgentType", back_populates="skill_assignments")
    skill: Mapped["Skill"] = relationship("Skill")

    def __repr__(self) -> str:
        return f"<AgentSkillAssignment agent_type_id={self.agent_type_id} skill_id={self.skill_id}>"


# Resolve forward references
from app.db.models.skills import Skill, Sop  # noqa: E402, F401
