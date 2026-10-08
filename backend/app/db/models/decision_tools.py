"""SQLAlchemy models for user-definable decision tools and their questions.

Decision tools are the decision-making counterpart of built-in system tools,
authored by tenant users. They mirror system-tool entity conventions
(name, description, is_active, tenant scoping) so skills, agents, SOPs,
roles/permissions, and MCP exposure work with the existing tool consumption
model. Tool names are unique WITHIN a tenant — tenant A and tenant B can each
define ``tool_a``. The ``decision____`` prefix is applied only at the MCP/tool
surface (see the Communication Hub bridge), never in storage.

Input/output contracts are nullable FK references to the platform's
AgentDataType registry (``agent_data_types``) — no inline schema storage.
Both are nullable: a tool may be state-only. Referenced data types are
protected from deletion (see the data-type service).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class DecisionToolStatus(str, enum.Enum):
    """Lifecycle status of a decision tool (mirrors system-tool conventions)."""

    draft = "draft"
    active = "active"
    disabled = "disabled"


class DecisionQuestionType(str, enum.Enum):
    """Type of a decision question (noul = binary numeric judgment)."""

    choice = "choice"
    score = "score"
    noul = "noul"


class DecisionTool(Base):
    """A tenant-scoped, user-defined decision tool.

    Carries structured input/output JSON schemas aligned with the TypeSafe
    Jev contract, a state preset mapping input/agent data into the decision
    state, act/confirm confidence thresholds, and an auto-generated tool
    description (derived from the definition; regenerated on update) — the
    description skills, agents, and MCP clients see.
    """

    __tablename__ = "decision_tools"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_decision_tools_tenant_id_name"),
        Index("ix_decision_tools_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Author-provided purpose; the auto-generated description lives below.
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Auto-generated tool description from the definition",
    )
    input_data_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_data_types.id", ondelete="RESTRICT"),
        nullable=True,
        comment="Input contract: AgentDataType reference (nullable — state-only tools)",
    )
    output_data_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_data_types.id", ondelete="RESTRICT"),
        nullable=True,
        comment="Output contract: AgentDataType reference (nullable)",
    )
    state_preset: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Mapping of input/agent data to state fields"
    )
    act_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.9, server_default="0.9"
    )
    confirm_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.7, server_default="0.7"
    )
    provider_model: Mapped[str] = mapped_column(
        String(200), nullable=False, default="jev-latest", server_default="jev-latest"
    )
    status: Mapped[DecisionToolStatus] = mapped_column(
        Enum(DecisionToolStatus, name="decision_tool_status_enum"),
        nullable=False,
        default=DecisionToolStatus.active,
        server_default=DecisionToolStatus.active.value,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="False; mirrors system-tool flag"
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
    input_data_type: Mapped["AgentDataType | None"] = relationship(
        "AgentDataType", foreign_keys=[input_data_type_id], lazy="joined"
    )
    output_data_type: Mapped["AgentDataType | None"] = relationship(
        "AgentDataType", foreign_keys=[output_data_type_id], lazy="joined"
    )
    questions: Mapped[list["DecisionToolQuestion"]] = relationship(
        "DecisionToolQuestion",
        back_populates="tool",
        cascade="all, delete-orphan",
        order_by="DecisionToolQuestion.ordering",
    )
    execution_results: Mapped[list["DecisionExecutionResult"]] = relationship(
        "DecisionExecutionResult",
        back_populates="tool",
        # DB-level ON DELETE CASCADE handles history cleanup; without
        # passive_deletes the ORM would nullify the NOT NULL FK first.
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<DecisionTool id={self.id} tenant_id={self.tenant_id} name={self.name}>"
        )


class DecisionToolQuestion(Base):
    """An ordered, typed question child of a DecisionTool."""

    __tablename__ = "decision_tool_questions"
    __table_args__ = (
        UniqueConstraint(
            "decision_tool_id", "question_key", name="uq_decision_tool_questions_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_tools.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordering: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_key: Mapped[str] = mapped_column(String(200), nullable=False)
    question_type: Mapped[DecisionQuestionType] = mapped_column(
        Enum(DecisionQuestionType, name="decision_question_type_enum"),
        nullable=False,
        default=DecisionQuestionType.choice,
    )
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_options: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Criteria/options appropriate to the question type"
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    tool: Mapped["DecisionTool"] = relationship(
        "DecisionTool", back_populates="questions"
    )

    def __repr__(self) -> str:
        return (
            f"<DecisionToolQuestion id={self.id} tool_id={self.decision_tool_id} "
            f"question_key={self.question_key}>"
        )


# Resolve forward reference
from app.db.models.results import DecisionExecutionResult  # noqa: E402, F401
