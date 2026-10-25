"""Optimized Implementation Plan (Software 3.0 two-layer plan model).

A *separate* entity from the high-level base implementation plan
(``AgentPlan``). Whereas the base plan is a plain step list (action type /
name / description), an ``OptimizedImplementationPlan`` is the model-authored
workflow composition — sandboxed Python script segments, LLM bridge steps, an
output decision, and an execution-semantics mark (``fully_scripted``) — that
the "Optimize & Verify" flow produces on demand and associates with the script
versions it authored.

Ownership invariant: Control-Center-owned (sole DB gateway). The optimization
service runs in Control Center and reuses the AR script-framework modules
(sandbox capability contract, validator, compiler) as library code — no agent
or sandboxed script executes outside Agent Runtime at serving time.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class OptimizedPlanStatus(str, enum.Enum):
    """Lifecycle status of an optimized-plan generation attempt."""

    generating = "generating"
    ready = "ready"
    failed = "failed"
    # Verification exhausted its attempts without a passing composition:
    # surfaced to the user so they can steer the next regeneration via
    # feedback (never silently "failed").
    needs_feedback = "needs_feedback"
    # Plan superseded by "Retire plan" (or a regeneration) — the row is KEPT
    # for reference and never gates execution; one active (non-retired)
    # record per agent type at any time.
    retired = "retired"


class OptimizedImplementationPlan(Base):
    """A model-authored workflow composition produced by "Optimize & Verify".

    Refers to the base ``AgentPlan`` it optimized from, carries the authored
    composition as ``plan_steps`` (script segments with ``python_source``,
    LLM bridge steps, output decision), the ``fully_scripted`` execution mark,
    and lineage to the script versions it authored (via
    ``ScriptDefinition.source_optimized_plan_id``).
    """

    __tablename__ = "optimized_implementation_plans"
    __table_args__ = (
        Index("ix_optimized_implementation_plans_tenant_id", "tenant_id"),
        Index("ix_optimized_implementation_plans_agent_type_id", "agent_type_id"),
        Index("ix_optimized_implementation_plans_agent_plan_id", "agent_plan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The base high-level plan this optimization was generated from.
    agent_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Model-authored composition steps (script segments + LLM bridges + output
    # decision), strongly structured the same way the plan parser normalizes
    # them (order/type/name/description/python_source/scriptable/output_mode/...).
    plan_steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Execution semantics (product decision): only a fully_scripted optimized
    # plan is served directly as a zero-LLM script; otherwise its scripts are
    # exposed as invocable tools and the LLM path orchestrates.
    fully_scripted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    status: Mapped[OptimizedPlanStatus] = mapped_column(
        Enum(OptimizedPlanStatus, name="optimized_plan_status_enum"),
        nullable=False,
        default=OptimizedPlanStatus.generating,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-attempt verification was retired: verification happens inside the
    # agent's REAL execution (the optimize side-run IS the evidence), so the
    # separate user-facing verification_log column was dropped.
    # Accumulated user feedback memory: a list of
    # {created_at, raw_feedback, summary} entries; ALL entries are included in
    # the authoring prompt when the optimized plan is regenerated.
    feedback_comments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
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
    agent_type: Mapped["AgentType"] = relationship(
        "AgentType", back_populates="optimized_plans"
    )
    base_plan: Mapped["AgentPlan"] = relationship(
        "AgentPlan", back_populates="optimized_plans"
    )
    script_definitions: Mapped[list["ScriptDefinition"]] = relationship(
        "ScriptDefinition",
        back_populates="optimized_source_plan",
        foreign_keys="ScriptDefinition.source_optimized_plan_id",
    )

    def __repr__(self) -> str:
        return (
            f"<OptimizedImplementationPlan id={self.id} "
            f"agent_type_id={self.agent_type_id} status={self.status} "
            f"fully_scripted={self.fully_scripted}>"
        )
