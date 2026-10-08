"""SQLAlchemy models for Skills and SOPs."""
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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Skill(Base):
    """
    A named, permission-assignable unit wrapping one or more MCP tool invocations.

    Tenant ownership is mandatory (no shared NULL-tenant slot); names are
    unique per tenant only. NOT NULL on ``tenant_id`` is enforced at the
    database level by migration ``b8c9d0e1f2a3``; the ORM column stays
    nullable for legacy paths.
    """

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_skills_tenant_name"),
        Index("ix_skills_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    tool_bindings: Mapped[list["SkillToolBinding"]] = relationship(
        "SkillToolBinding", back_populates="skill", cascade="all, delete-orphan"
    )
    sop_steps: Mapped[list["SopStep"]] = relationship("SopStep", back_populates="skill")

    def __repr__(self) -> str:
        return f"<Skill id={self.id} name={self.name}>"


class SkillToolBinding(Base):
    """Links a Skill to one or more MCP tools it invokes."""

    __tablename__ = "skill_tool_bindings"
    __table_args__ = (
        UniqueConstraint("skill_id", "tool_id", name="uq_skill_tool_binding"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    # No FK: tool_id may reference VIRTUAL tools that have no mcp_tools row
    # (system tools are DB-seeded; tenant decision tools are pure virtual
    # uuid5 ids — see decision_tool_service.resolve_virtual_tool_id).
    # Referential integrity is enforced at the skills API validation layer.
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Ordering of tool calls within the skill
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    skill: Mapped["Skill"] = relationship("Skill", back_populates="tool_bindings")
    # Explicit foreign() join — the column carries no database-level FK so
    # virtual (decision) tool ids never match a row; regular tools do.
    tool: Mapped["McpTool"] = relationship(
        "McpTool",
        primaryjoin="foreign(SkillToolBinding.tool_id) == McpTool.id",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<SkillToolBinding skill_id={self.skill_id} tool_id={self.tool_id}>"


class Sop(Base):
    """A Standard Operating Procedure composing multiple Skills with sequencing.

    Tenant ownership is mandatory; names are unique per tenant only.
    NOT NULL on ``tenant_id`` is enforced at the database level by
    migration ``b8c9d0e1f2a3``; the ORM column stays nullable for legacy
    paths.
    """

    __tablename__ = "sops"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_sops_tenant_name"),
        Index("ix_sops_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    steps: Mapped[list["SopStep"]] = relationship(
        "SopStep",
        back_populates="sop",
        cascade="all, delete-orphan",
        order_by="SopStep.order",
    )

    def __repr__(self) -> str:
        return f"<Sop id={self.id} name={self.name}>"


class SopStepType(str, enum.Enum):
    """Type of action performed in a SOP step."""

    skill_invocation = "skill_invocation"
    agent_delegation = "agent_delegation"


class SopStep(Base):
    """An ordered step in a SOP; either a Skill invocation or agent delegation."""

    __tablename__ = "sop_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sops.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[SopStepType] = mapped_column(
        Enum(SopStepType, name="sop_step_type_enum"), nullable=False, default=SopStepType.skill_invocation
    )
    # For skill steps
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    # For agent_delegation steps
    target_agent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    sop: Mapped["Sop"] = relationship("Sop", back_populates="steps")
    skill: Mapped["Skill | None"] = relationship("Skill", back_populates="sop_steps")

    def __repr__(self) -> str:
        return f"<SopStep id={self.id} sop_id={self.sop_id} order={self.order}>"


# Resolve forward reference
from app.db.models.mcp_hub import McpTool  # noqa: E402, F401
