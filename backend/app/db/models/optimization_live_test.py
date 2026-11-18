"""Optimization live-test requests — the live-test ledger of the optimizer.

The conversational optimizer is **replay-only by default**. When replay cannot
prove a script, it may ask the operator for consent to contact a real
integration **once**, with an exact ordered list of operations. This entity is
the durable record of that proposal plus the evidence of what actually ran:

A live test runs **the script** end-to-end — never an individual MCP tool
call. MCP tools are assumed to work; the operator is approving one run of the
script they wrote, as the agent:

* ``script_version_id`` — the saved script version the operator approved
  (nullable for historical rows; ``SET NULL`` so script retention never
  destroys the ledger). The script's ``python_source`` is the unit of
  execution and its own ``tools.call(...)`` lines are the ONLY egress.
* ``requested_operations`` — the **tool-call preview** derived server-side from
  that version's ``python_source`` (``extract_tools_call_names``), stored as an
  ordered ``[{tool_name, …}]`` list for the approval card. It is **not** the
  unit of execution and is never executed operation-by-operation. Immutable
  after creation: a changed proposal is a *new* row with a *new* approval.
  Arguments are state context only — never credentials, tokens, or secrets.
* ``executed_operations`` — nullable; the **script run record**: one
  ``{kind: "script_run", script_version_id, script_name, status, result_summary,
  duration_ms, tool_calls[], telemetry, error}`` entry describing the single
  end-to-end run (bounded result summary, per-``tools.call`` outcomes,
  telemetry and duration). Written once from the run result; empty for
  denial/expiry/cancel.

Deliberately **not** duplicated here (each fact keeps its single home):

* **The subject agent type.** ``target_agent_type_id`` is derived server-side
  from the conversation session's ``agent_type_id`` — in the avatar model the
  session's agent type *is* the agent type being optimized, and it is also the
  identity/permission envelope the operations run under. It is recorded on this
  row so a later session edit cannot rewrite that audit fact.
* **Decision attribution.** Who decided, when, and approve/deny are read from
  the linked ``InterveneResponse``; ``status`` is only the domain projection
  written at decision time.
* **The exactly-once marker.** The single-use gate lives on
  ``ConversationTurnResume`` (``idempotency_key`` + ``write_applied``), so a
  replayed or re-delivered approval can never execute the list twice.

Denial, silence, and expiry leave ``executed_operations`` empty and keep the
session replay-only; a denied request is retained for audit, never resurrected.
Replay evidence stays in ``VerificationRun`` / ``ScriptExecutionRecord`` — this
row plus ``RuntimeToolCall.optimization_live_test_request_id`` are the *live*
record.

Kept in its own optimizer-domain module (not ``intervene.py``): the
intervention entities stay generic for every agent.

Ownership invariant: Control-Center-owned (sole DB writer). Agent Runtime and
Communication Hub receive the approved list through internal APIs and never
touch this table.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OptimizationLiveTestStatus(str, enum.Enum):
    """Domain state machine of a live-test request.

    ``pending`` → ``approved`` (consent recorded; at most one execution attempt
    may follow) → ``executed`` / ``failed``; or ``pending`` → ``denied`` /
    ``expired`` / ``cancelled``, which are terminal and never execute anything.
    ``approved`` never implies execution evidence — only ``executed`` /
    ``failed`` carry the execution timestamps and ``executed_operations``.
    """

    pending = "pending"
    approved = "approved"
    executed = "executed"
    failed = "failed"
    denied = "denied"
    expired = "expired"
    cancelled = "cancelled"


class OptimizationLiveTestRequest(Base):
    """One operator-facing request to run real operations during optimization.

    Raised only inside an optimization conversation (``ConversationSession``
    with ``channel = "optimization"``), whose ``agent_type_id`` is the subject.
    See the module docstring for the immutability, attribution and
    single-use guarantees.
    """

    __tablename__ = "optimization_live_tests"
    __table_args__ = (
        Index(
            "ix_optimization_live_tests_tenant_session",
            "tenant_id",
            "conversation_session_id",
        ),
        # Supports the expiry sweep (overdue ``pending`` rows) and status reads.
        Index("ix_optimization_live_tests_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Owning workspace; the request never crosses tenants.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    # The optimization conversation that raised the request.
    conversation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The agent type being optimized — derived from the session's
    # ``agent_type_id`` (the subject, and the identity/permission envelope the
    # operations run under). Recorded so later session edits cannot rewrite it.
    target_agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The turn that presented the operation list to the operator.
    request_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The reused approval intervention carrying the decision (who/when/approve
    # or deny lives on its ``InterveneResponse``).
    intervene_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intervene_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The exactly-once resume record gating the single execution
    # (``idempotency_key`` + ``write_applied``).
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turn_resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The SAVED script version the operator approved (the unit of execution is
    # the whole script, not the previewed tool calls). ``SET NULL`` so script
    # retention never destroys the ledger; the run is refused when the source is
    # no longer available.
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[OptimizationLiveTestStatus] = mapped_column(
        Enum(
            OptimizationLiveTestStatus,
            name="optimization_live_test_status_enum",
        ),
        nullable=False,
        default=OptimizationLiveTestStatus.pending,
    )
    # Ordered tool-call PREVIEW derived server-side from the approved version's
    # python_source (``extract_tools_call_names``). Describes what the script
    # will call; it is NOT the unit of execution and is never executed
    # operation-by-operation. State context only; never credentials or secrets.
    requested_operations: Mapped[list] = mapped_column(JSON, nullable=False)
    # The script RUN record: one ``{kind: "script_run", script_version_id,
    # script_name, status, result_summary, duration_ms, tool_calls[], telemetry,
    # error}`` entry written once from the live run result; empty for
    # denial/expiry/cancel.
    executed_operations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # End of the answerable window; a lazy check on decision plus the periodic
    # sweep close overdue rows as ``expired``.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_finished_at: Mapped[datetime | None] = mapped_column(
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

    def __repr__(self) -> str:
        return (
            "<OptimizationLiveTestRequest "
            f"id={self.id} session={self.conversation_session_id} "
            f"target_agent_type={self.target_agent_type_id} status={self.status}>"
        )
