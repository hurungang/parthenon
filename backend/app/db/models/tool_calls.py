"""SQLAlchemy models for runtime tool-call records: RuntimeToolCall.

Every tool execution performed by Agent Runtime (MCP tools, system tools,
and A2A delegations) is recorded here so the Agent Runtime Monitor can
render per-node tool-call history for both agent jobs and conversation
sessions.

``session_id`` is deliberately polymorphic (NO FK): it references either an
``agent_jobs.id`` (``session_kind="agent"``) or a
``conversation_sessions.id`` (``session_kind="conversation"``), because
conversation turns execute without a backing AgentJob.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RuntimeToolCallSessionKind(str, enum.Enum):
    """What kind of session the recorded tool call belongs to."""

    agent = "agent"
    conversation = "conversation"


class RuntimeToolCallRouteType(str, enum.Enum):
    """Routing path the tool call took through Communication Hub."""

    system = "system"
    mcp = "mcp"
    a2a = "a2a"


class RuntimeToolCallStatus(str, enum.Enum):
    """Outcome of the tool execution."""

    success = "success"
    error = "error"


class RuntimeToolCall(Base):
    """Record of a single tool execution performed by Agent Runtime."""

    __tablename__ = "runtime_tool_calls"
    __table_args__ = (
        Index("ix_runtime_tool_calls_session", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Polymorphic session reference — agent job id OR conversation id (no FK).
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_kind: Mapped[RuntimeToolCallSessionKind] = mapped_column(
        Enum(RuntimeToolCallSessionKind, name="runtime_tool_call_session_kind_enum"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(400), nullable=False)
    route_type: Mapped[RuntimeToolCallRouteType] = mapped_column(
        Enum(RuntimeToolCallRouteType, name="runtime_tool_call_route_type_enum"),
        nullable=False,
    )
    # MCP server slug for MCP-routed calls (``parse_tool_name``); None otherwise.
    mcp_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[RuntimeToolCallStatus] = mapped_column(
        Enum(RuntimeToolCallStatus, name="runtime_tool_call_status_enum"),
        nullable=False,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            "<RuntimeToolCall "
            f"id={self.id} session={self.session_id} tool={self.tool_name} "
            f"route={self.route_type} status={self.status}>"
        )
