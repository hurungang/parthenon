"""Internal data API for Communication Hub and Agent Runtime — session management.

All endpoints require a service certificate (via ``require_service_certificate``).

Routes (all under /internal/data):
  GET   /sessions/{session_id}               — session metadata
  GET   /sessions/{session_id}/history       — conversation messages
  POST  /sessions/{session_id}/result        — persist execution result
  GET   /users/{user_id}/permissions         — resolved tool permission set
  POST  /sessions/claim-queued              — atomically claim queued sessions
  PATCH /sessions/{session_id}/status       — transition session status
  POST  /sessions/{session_id}/log          — write execution log entry
  POST  /conversations/{conv_session_id}/auto-name  — generate and save conversation title
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import selectinload

from app.api.deps import require_service_certificate
from app.db.session import DbSession
from app.services.agents.tool_naming import build_tool_name, parse_tool_name

logger = logging.getLogger(__name__)


def _canonicalize_mcp_tool_name(name: str, server_slug: str | None, original_name: str | None) -> str:
    """Return canonical ``server____tool`` for MCP tool identifiers."""
    if server_slug and isinstance(original_name, str) and original_name:
        return build_tool_name(server_slug, original_name)

    try:
        parsed_server, parsed_tool = parse_tool_name(name)
        return build_tool_name(parsed_server, parsed_tool)
    except ValueError:
        if "/" in name:
            parsed_server, parsed_tool = name.split("/", 1)
            return build_tool_name(parsed_server, parsed_tool)
        return name

InternalSessionDataRouter = APIRouter(
    prefix="/internal/data",
    tags=["internal"],
)


# ── Request / response schemas ────────────────────────────────────────────────


class SessionResponse(BaseModel):
    """AgentJob session metadata."""

    id: uuid.UUID
    agent_type_id: uuid.UUID
    triggered_by_user_id: uuid.UUID | None
    input_data: dict | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    output_data: dict | None
    error_message: str | None
    conversation_history: list | None
    created_at: datetime


class ConversationHistoryResponse(BaseModel):
    """Conversation message history for a session."""

    session_id: uuid.UUID
    messages: list[dict]


class SessionResultRequest(BaseModel):
    """Request body for POST /sessions/{session_id}/result."""

    output_data: dict = Field(..., description="Execution output payload to persist")


class SessionResultResponse(BaseModel):
    session_id: uuid.UUID
    status: str


class UserPermissionsResponse(BaseModel):
    """Resolved MCP tool permission set for a user."""

    user_id: uuid.UUID
    allowed_tools: list[str]


class ClaimQueuedSessionsRequest(BaseModel):
    """Request body for POST /sessions/claim-queued."""

    limit: int = Field(default=4, ge=1, le=32)


class ClaimQueuedSessionsResponse(BaseModel):
    """Atomically claimed session IDs ready for execution."""

    session_ids: list[uuid.UUID]


class SessionStatusUpdateRequest(BaseModel):
    """Request body for PATCH /sessions/{session_id}/status."""

    status: Literal["running", "completed", "failed"]
    output_data: dict | None = None
    error_message: str | None = None


class SessionStatusUpdateResponse(BaseModel):
    session_id: uuid.UUID
    status: str


class LogExecutionEventRequest(BaseModel):
    """Request body for POST /sessions/{session_id}/log."""

    event_type: str = Field(..., max_length=50)
    log_level: str = Field(default="INFO", max_length=20)
    message: str
    data: dict = Field(default_factory=dict)


class LogExecutionEventResponse(BaseModel):
    entry_id: uuid.UUID


class AutoNameRequest(BaseModel):
    """Request body for POST /conversations/{conv_session_id}/auto-name."""

    first_user_message: str
    agent_type_id: uuid.UUID | None = None


class AutoNameResponse(BaseModel):
    title: str | None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@InternalSessionDataRouter.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return session metadata",
)
async def get_session(
    session_id: uuid.UUID,
    db: DbSession,
) -> SessionResponse:
    """Return AgentJob metadata for a session."""
    from app.db.models.agents import AgentJob

    job = await db.get(AgentJob, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionResponse(
        id=job.id,
        agent_type_id=job.agent_type_id,
        triggered_by_user_id=job.triggered_by_user_id,
        input_data=job.input_data,
        status=job.status.value,
        started_at=job.started_at,
        completed_at=job.completed_at,
        output_data=job.output_data,
        error_message=job.error_message,
        conversation_history=job.conversation_history,
        created_at=job.created_at,
    )


@InternalSessionDataRouter.get(
    "/sessions/{session_id}/history",
    response_model=ConversationHistoryResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return conversation message history for a session",
)
async def get_session_history(
    session_id: uuid.UUID,
    db: DbSession,
) -> ConversationHistoryResponse:
    """Return ordered conversation messages stored on the AgentJob."""
    from app.db.models.agents import AgentJob

    job = await db.get(AgentJob, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return ConversationHistoryResponse(
        session_id=session_id,
        messages=job.conversation_history or [],
    )


@InternalSessionDataRouter.post(
    "/sessions/{session_id}/result",
    response_model=SessionResultResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Persist execution result from Agent Runtime",
)
async def post_session_result(
    session_id: uuid.UUID,
    body: SessionResultRequest,
    db: DbSession,
) -> SessionResultResponse:
    """Receive and persist an execution result from Agent Runtime.

    Transitions the session to ``completed`` and stores ``output_data``.

    After persisting, dispatches the result to the Communication Hub so that
    connected WebSocket subscribers receive the agent response in real time.
    This completes the Phase 5.5 full execution cycle:
    CC trigger → AR execute → CC persist → CH dispatch → UI WebSocket delivery.
    """
    from app.db.models.agents import AgentJob, AgentJobStatus

    job = await db.get(AgentJob, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    job.status = AgentJobStatus.completed
    job.completed_at = datetime.now(timezone.utc)
    job.output_data = body.output_data
    await db.flush()

    # If the output contains an explicit result (e.g. from save_result via CommHub),
    # persist it to the Result Repository so it appears in the UI.
    result_content: str | None = body.output_data.get("result") if body.output_data else None
    if result_content:
        try:
            from app.db.models.agents import AgentType, AgentOutputType
            from app.services.results.store import ResultStore

            agent_type = await db.get(AgentType, job.agent_type_id)
            output_type = agent_type.output_type if agent_type else AgentOutputType.auto
            output_value = output_type.value if isinstance(output_type, AgentOutputType) else str(output_type)
            content_type = (
                "text/markdown"
                if output_value == AgentOutputType.markdown.value
                else "application/json"
                if output_value == AgentOutputType.typed.value
                else "text/plain"
            )

            store = ResultStore()
            await store.save(
                payload={"content": result_content},
                db=db,
                title=body.output_data.get("title") or None,
                agent_type_id=job.agent_type_id,
                content_type=content_type,
                # conversation_session_id is None for task agent sessions
            )
            logger.info(
                "ResultRecord created for session %s (post_session_result safety net)",
                session_id,
            )
        except Exception as exc:
            # Non-fatal: result is already in output_data; log and continue.
            logger.warning(
                "Failed to create ResultRecord for session %s: %s (output_data persisted)",
                session_id,
                exc,
            )

    await db.commit()

    logger.info("Session %s result persisted via CC data API", session_id)

    # Phase 5.5: dispatch the result to Communication Hub so the WebSocket
    # subscriber receives it.  Failures are logged but do not affect the 200
    # response — the result is already persisted in the database.
    await _dispatch_result_to_comm_hub(session_id, body.output_data)

    return SessionResultResponse(session_id=session_id, status="completed")


async def _dispatch_result_to_comm_hub(
    session_id: uuid.UUID, output_data: dict
) -> None:
    """Call CommHubClient to push the completed result to the broker channel.

    Runs after the result is committed so a broker failure never rolls back
    the database write.  Errors are logged and swallowed.
    """
    try:
        from app.services.control_center.comm_hub_client import CommunicationHubClient

        client = CommunicationHubClient()
        await client.dispatch_message(
            session_id=session_id,
            message_type="agent_result",
            content=output_data,
        )
    except Exception as exc:
        logger.warning(
            "Failed to dispatch result for session %s to Communication Hub: %s "
            "(result is persisted; WebSocket delivery may be delayed until next poll)",
            session_id,
            exc,
        )


@InternalSessionDataRouter.get(
    "/users/{user_id}/permissions",
    response_model=UserPermissionsResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Return resolved MCP tool permission set for a user",
)
async def get_user_permissions(
    user_id: uuid.UUID,
    db: DbSession,
) -> UserPermissionsResponse:
    """Return the full set of MCP tool identifiers allowed for a user.

    Resolves via the user's platform roles → agent roles → skills/SOPs → tools.
    """
    from sqlalchemy import select

    from app.db.models.mcp_hub import McpTool
    from app.db.models.skills import Skill, SkillToolBinding, SopStep, SopStepType
    from app.db.models.user_roles import UserRole, RolePermission

    # Resolve permissions via the user's assigned roles
    # This is a simplified resolution: collect all tool permissions assigned to the user
    allowed_tools: set[str] = set()

    try:
        # Get skill IDs from user role → role permission → tool bindings
        role_rows = await db.execute(
            select(RolePermission.resource_id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(
                UserRole.user_id == user_id,
                RolePermission.resource_type == "skill",
            )
        )
        skill_ids = [row[0] for row in role_rows.fetchall()]

        if skill_ids:
            tool_rows = await db.execute(
                select(McpTool)
                .options(selectinload(McpTool.server))
                .join(SkillToolBinding, SkillToolBinding.tool_id == McpTool.id)
                .where(
                    SkillToolBinding.skill_id.in_(skill_ids),
                    McpTool.is_active.is_(True),
                )
            )
            for tool in tool_rows.scalars().all():
                allowed_tools.add(
                    _canonicalize_mcp_tool_name(
                        tool.name,
                        tool.server.slug if tool.server is not None else None,
                        tool.original_name,
                    )
                )
    except Exception as exc:
        logger.warning("Failed to resolve permissions for user %s: %s", user_id, exc)

    return UserPermissionsResponse(
        user_id=user_id,
        allowed_tools=sorted(allowed_tools),
    )


@InternalSessionDataRouter.post(
    "/sessions/claim-queued",
    response_model=ClaimQueuedSessionsResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Atomically claim queued sessions for execution",
)
async def claim_queued_sessions(
    body: ClaimQueuedSessionsRequest,
    db: DbSession,
) -> ClaimQueuedSessionsResponse:
    """Atomically claim up to ``limit`` queued sessions using SELECT FOR UPDATE SKIP LOCKED.

    Transitions claimed sessions to ``running`` status.  Agent Runtime calls
    this endpoint on each poll cycle instead of accessing the database directly.
    """
    from sqlalchemy import select, update

    from app.db.models.agents import AgentJob, AgentJobStatus

    result = await db.execute(
        select(AgentJob.id)
        .where(AgentJob.status == AgentJobStatus.queued)
        .order_by(AgentJob.created_at)
        .limit(body.limit)
        .with_for_update(skip_locked=True)
    )
    session_ids = [row[0] for row in result.fetchall()]

    if session_ids:
        await db.execute(
            update(AgentJob)
            .where(AgentJob.id.in_(session_ids))
            .values(
                status=AgentJobStatus.running,
                started_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        logger.info("Claimed %d session(s) for Agent Runtime execution", len(session_ids))

    return ClaimQueuedSessionsResponse(session_ids=session_ids)


@InternalSessionDataRouter.patch(
    "/sessions/{session_id}/status",
    response_model=SessionStatusUpdateResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Transition session status",
)
async def update_session_status(
    session_id: uuid.UUID,
    body: SessionStatusUpdateRequest,
    db: DbSession,
) -> SessionStatusUpdateResponse:
    """Transition an AgentJob to running, completed, or failed.

    Agent Runtime calls this endpoint to report execution progress without
    direct database access.
    """
    from app.db.models.agents import AgentJob, AgentJobStatus

    job = await db.get(AgentJob, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    now = datetime.now(timezone.utc)
    if body.status == "running":
        job.status = AgentJobStatus.running
        job.started_at = now
    elif body.status == "completed":
        job.status = AgentJobStatus.completed
        job.completed_at = now
        if body.output_data is not None:
            job.output_data = body.output_data
    elif body.status == "failed":
        job.status = AgentJobStatus.failed
        job.completed_at = now
        if body.error_message is not None:
            job.error_message = body.error_message

    await db.flush()
    await db.commit()

    return SessionStatusUpdateResponse(session_id=session_id, status=body.status)


@InternalSessionDataRouter.post(
    "/sessions/{session_id}/log",
    response_model=LogExecutionEventResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Write an execution log entry for a session",
)
async def log_execution_event(
    session_id: uuid.UUID,
    body: LogExecutionEventRequest,
    db: DbSession,
) -> LogExecutionEventResponse:
    """Persist a structured execution log entry from Agent Runtime.

    Allows Agent Runtime to write audit-quality event entries without
    direct database access.
    """
    from app.db.models.session_logs import ExecutionLogEntry

    entry_id = uuid.uuid4()
    entry = ExecutionLogEntry(
        id=entry_id,
        session_id=session_id,
        event_type=body.event_type,
        log_level=body.log_level.upper(),
        message=body.message,
        data=body.data,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(entry)
    try:
        await db.flush()
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist log entry for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to persist log entry")

    return LogExecutionEventResponse(entry_id=entry_id)


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/auto-name",
    response_model=AutoNameResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Generate and save an auto-generated conversation title",
)
async def auto_name_conversation(
    conv_session_id: uuid.UUID,
    body: AutoNameRequest,
    db: DbSession,
) -> AutoNameResponse:
    """Generate and persist a title for a conversation session.

    Communication Hub calls this endpoint after the first user message
    instead of creating its own database session.
    """
    from app.db.models.conversations import ConversationSession
    from app.services.conversations.auto_namer import SessionAutoNamer

    agent_type_id = body.agent_type_id
    if agent_type_id is None:
        conv = await db.get(ConversationSession, conv_session_id)
        agent_type_id = conv.agent_type_id if conv else None

    try:
        namer = SessionAutoNamer()
        title = await namer.generate_and_save(
            session_id=conv_session_id,
            first_user_message=body.first_user_message,
            agent_type_id=agent_type_id,
            db=db,
        )
        return AutoNameResponse(title=title)
    except Exception as exc:
        logger.warning("Auto-naming failed for conversation %s: %s", conv_session_id, exc)
        return AutoNameResponse(title=None)
