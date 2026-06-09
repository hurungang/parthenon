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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_service_certificate
from app.db.session import DbSession
from app.services.agents.permission_manager import AgentPermissionManager
from app.services.agents.tool_naming import build_tool_name, parse_tool_name

logger = logging.getLogger(__name__)
_permission_manager = AgentPermissionManager()


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
    stop_category: str | None
    stop_reason: str | None
    stop_details: dict | None
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

    status: Literal["running", "completed", "failed", "waiting_for_human"]
    output_data: dict | None = None
    error_message: str | None = None
    stop_category: str | None = None
    stop_reason: str | None = None
    stop_details: dict | None = None
    intervene_request_id: str | None = None


class SessionStatusUpdateResponse(BaseModel):
    session_id: uuid.UUID
    status: str


class LogExecutionEventRequest(BaseModel):
    """Request body for POST /sessions/{session_id}/log."""

    event_type: str = Field(..., max_length=50)
    log_level: str = Field(default="INFO", max_length=20)
    message: str
    data: dict = Field(default_factory=dict)
    event_category: str = Field(default="functional", max_length=50)
    actor_type: str = Field(default="system", max_length=20)


class LogExecutionEventResponse(BaseModel):
    entry_id: uuid.UUID


class AutoNameRequest(BaseModel):
    """Request body for POST /conversations/{conv_session_id}/auto-name."""

    first_user_message: str
    agent_type_id: uuid.UUID | None = None


class AutoNameResponse(BaseModel):
    title: str | None


class ConversationTurnPrepareRequest(BaseModel):
    """Request body for preparing a conversation turn in Control Center."""

    user_message: str


class ConversationTurnPrepareResponse(BaseModel):
    """Prepared execution context for a conversation turn."""

    agent_type_id: uuid.UUID | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    no_agent_message: str | None = None


class ConversationTurnAppendRequest(BaseModel):
    """Request body for appending agent turn and optional auto-naming."""

    agent_reply: str
    is_first_message: bool = False
    first_user_message: str | None = None
    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, Any]] = Field(default_factory=list)


class ConversationTurnAppendResponse(BaseModel):
    """Result of appending an agent turn."""

    title: str | None = None


class A2ADataRequest(BaseModel):
    """Request body for POST /a2a/request."""

    target_agent_type_slug: str
    requester_instance_id: str
    requester_role_id: uuid.UUID | None = None
    request_payload: dict = Field(default_factory=dict)
    session_link_id: str | None = None
    active_receiver_instance_id: str | None = None


class A2ADataResponse(BaseModel):
    """Control Center prepared A2A execution context for Communication Hub."""

    receiver_instance_id: str
    session_link_id: str
    status: str
    receiver_session_id: uuid.UUID | None = None


def _build_no_agent_message(has_session: bool, has_agent_type: bool) -> str:
    if not has_session:
        return "Conversation session not found."
    if not has_agent_type:
        return "No agent type is configured for this conversation session."
    return "No model is configured for this agent."


def _compose_conversation_system_instruction(context: Any) -> str | None:
    instruction_parts: list[str] = []

    base_instruction = getattr(context, "system_instruction", None)
    if base_instruction:
        instruction_parts.append(str(base_instruction).strip())

    sop_content = getattr(context, "sop_content", None)
    if sop_content:
        instruction_parts.append(str(sop_content).strip())

    mcp_context = getattr(context, "mcp_session_context", None)
    if mcp_context:
        instruction_parts.append(str(mcp_context).strip())

    merged = "\n\n".join(part for part in instruction_parts if part)
    return merged or None


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
        stop_category=(job.stop_category.value if job.stop_category else None),
        stop_reason=(job.stop_reason.value if job.stop_reason else None),
        stop_details=job.stop_details,
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

    Phase 3.11: refuses to OVERWRITE a terminal state (completed/failed)
    with a non-terminal one (running) and refuses to clear an existing
    ``stop_category``/``stop_reason``/``stop_details`` when the
    session was previously terminated by the operator.  This is the
    last line of defence against the agent's late "I'm done!" call
    racing the operator's "Terminate" request.
    """
    from app.db.models.agents import (
        AgentJob,
        AgentJobStatus,
        AgentTerminationCategory,
        SessionStopCategory,
        SessionStopReason,
    )

    job = await db.get(AgentJob, session_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Phase 3.12: terminal-state guards.  Once a session is in a
    # terminal state, the only way OUT is via a NEW termination
    # request (which the orchestrator handles directly on the DB, not
    # through this endpoint).  A late "running" or "completed" call
    # from Agent Runtime after operator termination must be ignored.
    is_already_terminal = job.status in (
        AgentJobStatus.completed,
        AgentJobStatus.failed,
        AgentJobStatus.terminated,
    )
    is_terminated_by_operator = (
        getattr(job, "termination_category", None)
        in (
            AgentTerminationCategory.user_requested,
            AgentTerminationCategory.cascade_parent_terminated,
        )
    )
    if is_already_terminal and body.status in ("running",):
        logger.info(
            "Ignoring late 'running' status update for already-terminal session %s "
            "(status=%s, termination_category=%s)",
            session_id,
            job.status.value,
            getattr(job, "termination_category", None),
        )
        return SessionStatusUpdateResponse(
            session_id=session_id, status=job.status.value
        )
    if is_terminated_by_operator and body.status == "completed":
        # The agent's late "I finished!" call.  Persist the output
        # data on the row (so the operator can see what would have
        # been produced) but DO NOT change the status, do NOT clear
        # the termination attribution, do NOT clear the stop fields.
        # The session stays "failed" with the operator's
        # termination_category attached.
        logger.info(
            "Refusing to overwrite operator-terminated session %s with 'completed' "
            "(recording output_data but keeping status=%s, termination_category=%s)",
            session_id,
            job.status.value,
            getattr(job, "termination_category", None),
        )
        if body.output_data is not None:
            job.output_data = body.output_data
        await db.flush()
        await db.commit()
        return SessionStatusUpdateResponse(
            session_id=session_id, status=job.status.value
        )

    now = datetime.now(timezone.utc)
    if body.status == "running":
        job.status = AgentJobStatus.running
        job.started_at = now
    elif body.status == "completed":
        job.status = AgentJobStatus.completed
        job.completed_at = now
        if body.output_data is not None:
            job.output_data = body.output_data
        # Only clear stop fields if there is no prior termination
        # attribution — otherwise we'd be erasing the operator's
        # intent (the call above already returned early when the
        # session was terminated by the operator, so this branch
        # only fires for sessions that reached completion naturally).
        if not is_terminated_by_operator:
            job.stop_category = None
            job.stop_reason = None
            job.stop_details = None
    elif body.status == "failed":
        job.status = AgentJobStatus.failed
        job.completed_at = now
        if body.output_data is not None:
            job.output_data = body.output_data
        if body.error_message is not None:
            job.error_message = body.error_message
        if body.stop_category is not None:
            job.stop_category = body.stop_category
        if body.stop_reason is not None:
            job.stop_reason = body.stop_reason
        if body.stop_details is not None:
            job.stop_details = body.stop_details
    elif body.status == "waiting_for_human":
        job.status = AgentJobStatus.waiting_for_human
        if body.intervene_request_id is not None:
            job.intervene_request_id = uuid.UUID(body.intervene_request_id)

    await db.flush()
    await db.commit()

    if body.status == "completed":
        await _dispatch_result_to_comm_hub(
            session_id,
            {
                "status": "completed",
                "output_data": body.output_data or {},
            },
        )
    elif body.status == "failed":
        await _dispatch_result_to_comm_hub(
            session_id,
            {
                "status": "failed",
                "error": body.error_message or "Receiver session failed",
                "output_data": body.output_data or {},
                "stop_category": body.stop_category,
                "stop_reason": body.stop_reason,
                "stop_details": body.stop_details,
            },
        )

    return SessionStatusUpdateResponse(session_id=session_id, status=body.status)


@InternalSessionDataRouter.post(
    "/a2a/request",
    response_model=A2ADataResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Resolve and prepare A2A delegation request",
)
async def prepare_a2a_request(
    body: A2ADataRequest,
    db: DbSession,
) -> A2ADataResponse:
    """Resolve target agent type, enforce permission, create session link, enqueue receiver job.

    Communication Hub calls this endpoint so all A2A DB access remains in Control Center.
    """
    from sqlalchemy import select

    from app.db.models.agents import (
        A2ASessionStatus,
        AgentA2ASession,
        AgentType,
    )
    from app.services.agents.session_service import AgentSessionService
    from app.services.control_center.comm_hub_client import (
        CommunicationHubClient,
        CommunicationHubClientError,
    )

    result = await db.execute(select(AgentType).where(AgentType.name == body.target_agent_type_slug))
    target_agent_type = result.scalar_one_or_none()
    if not target_agent_type:
        raise HTTPException(
            status_code=404,
            detail=f"Target agent type '{body.target_agent_type_slug}' not found",
        )
    if not target_agent_type.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"Target agent type '{body.target_agent_type_slug}' is not active",
        )

    if body.requester_role_id is not None:
        allowed_agent_types = await _permission_manager.calculate_allowed_agent_types(
            body.requester_role_id,
            db,
        )
        if body.target_agent_type_slug not in allowed_agent_types:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role {body.requester_role_id} is not allowed to delegate "
                    f"to '{body.target_agent_type_slug}'"
                ),
            )

    if body.session_link_id:
        existing = await db.execute(
            select(AgentA2ASession).where(
                AgentA2ASession.session_link_id == body.session_link_id,
                AgentA2ASession.requester_instance_id == body.requester_instance_id,
                AgentA2ASession.status == A2ASessionStatus.active,
            )
        )
        existing_session = existing.scalar_one_or_none()
        if existing_session is not None:
            return A2ADataResponse(
                receiver_instance_id=existing_session.receiver_instance_id,
                session_link_id=existing_session.session_link_id,
                status="accepted",
                receiver_session_id=None,
            )

    receiver_instance_id = (
        body.active_receiver_instance_id
        if body.active_receiver_instance_id
        else f"agent_{target_agent_type.id}_{uuid.uuid4()}"
    )
    receiver_is_dynamic = body.active_receiver_instance_id is None

    session_link_id = str(uuid.uuid4())
    a2a_session = AgentA2ASession(
        requester_instance_id=body.requester_instance_id,
        receiver_instance_id=receiver_instance_id,
        receiver_is_dynamic=receiver_is_dynamic,
        session_link_id=session_link_id,
        status=A2ASessionStatus.active,
    )
    db.add(a2a_session)
    await db.flush()

    session_service = AgentSessionService()
    receiver_job = await session_service.enqueue(
        agent_type_id=target_agent_type.id,
        input_data=body.request_payload,
        user_id=None,
        db=db,
    )
    await db.commit()

    try:
        client = CommunicationHubClient()
        await client.trigger_execution(
            session_id=receiver_job.id,
            agent_type_id=target_agent_type.id,
            input_data=body.request_payload,
        )
    except CommunicationHubClientError as exc:
        logger.error(
            "Failed to trigger receiver execution via Communication Hub "
            "(receiver=%s session=%s): %s",
            receiver_instance_id,
            receiver_job.id,
            exc,
        )

    return A2ADataResponse(
        receiver_instance_id=receiver_instance_id,
        session_link_id=session_link_id,
        status="accepted",
        receiver_session_id=receiver_job.id,
    )


@InternalSessionDataRouter.post(
    "/a2a/sessions/{session_link_id}/disconnect",
    dependencies=[Depends(require_service_certificate)],
    summary="Mark A2A session disconnected",
)
async def disconnect_a2a_session(
    session_link_id: str,
    db: DbSession,
) -> dict[str, str]:
    """Mark an A2A session as completed in Control Center."""
    from sqlalchemy import select

    from app.db.models.agents import A2ASessionStatus, AgentA2ASession

    result = await db.execute(
        select(AgentA2ASession).where(AgentA2ASession.session_link_id == session_link_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"A2A session '{session_link_id}' not found",
        )

    session.status = A2ASessionStatus.completed
    session.disconnect_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()

    return {"status": "disconnected", "session_link_id": session_link_id}


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/prepare-turn",
    response_model=ConversationTurnPrepareResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Persist user turn and return prepared conversation context",
)
async def prepare_conversation_turn(
    conv_session_id: uuid.UUID,
    body: ConversationTurnPrepareRequest,
    db: DbSession,
) -> ConversationTurnPrepareResponse:
    """Persist the user message and return conversation messages for runtime execution."""
    from app.api.v1.internal.agent_data import get_agent_context
    from app.db.models.agents import AgentType
    from app.db.models.conversations import ConversationSession, ConversationTurn, TurnRole
    from app.services.conversations.store import ConversationStore

    store = ConversationStore()
    await store.add_turn(conv_session_id, TurnRole.user, body.user_message, db)

    conv_session = await db.get(ConversationSession, conv_session_id)
    if conv_session is None:
        await db.commit()
        return ConversationTurnPrepareResponse(
            no_agent_message=_build_no_agent_message(False, False)
        )

    if conv_session.agent_type_id is None:
        await db.commit()
        return ConversationTurnPrepareResponse(
            no_agent_message=_build_no_agent_message(True, False)
        )

    agent_type = await db.get(AgentType, conv_session.agent_type_id)
    if agent_type is None or not agent_type.model_id:
        await db.commit()
        return ConversationTurnPrepareResponse(
            agent_type_id=conv_session.agent_type_id,
            no_agent_message=_build_no_agent_message(True, True),
        )

    context = await get_agent_context(agent_type_id=agent_type.id, db=db)
    system_instruction = _compose_conversation_system_instruction(context)

    turns_result = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.session_id == conv_session_id)
        .where(ConversationTurn.role.in_([TurnRole.user, TurnRole.agent]))
        .order_by(ConversationTurn.created_at)
    )
    turns = list(turns_result.scalars().all())

    messages: list[dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    for turn in turns:
        role = "user" if turn.role == TurnRole.user else "assistant"
        messages.append({"role": role, "content": turn.content})

    await db.commit()
    return ConversationTurnPrepareResponse(
        agent_type_id=agent_type.id,
        messages=messages,
        no_agent_message=None,
    )


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/append-turn",
    response_model=ConversationTurnAppendResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Persist agent turn and optionally auto-name conversation",
)
async def append_conversation_turn(
    conv_session_id: uuid.UUID,
    body: ConversationTurnAppendRequest,
    db: DbSession,
) -> ConversationTurnAppendResponse:
    """Persist the agent response and optionally auto-name on first message."""
    from app.db.models.conversations import ConversationSession, TurnRole
    from app.services.conversations.auto_namer import SessionAutoNamer
    from app.services.conversations.store import ConversationStore

    store = ConversationStore()
    agent_turn = await store.add_turn(conv_session_id, TurnRole.agent, body.agent_reply, db)

    for status_event in body.status_events:
        if not isinstance(status_event, dict):
            continue
        status_value = status_event.get("status")
        if not isinstance(status_value, str):
            continue
        await store.add_tool_call(
            turn_id=agent_turn.id,
            tool_name="chat_status",
            db=db,
            tool_output={
                "status": status_value,
                "agent_type": status_event.get("agent_type"),
                "tool_name": status_event.get("tool_name"),
                "receiver_session_id": status_event.get("receiver_session_id"),
                "timestamp": status_event.get("timestamp"),
            },
        )

    conv_session = await db.get(ConversationSession, conv_session_id)
    if conv_session is not None and body.guardrail_usage is not None:
        conv_session.guardrail_usage = body.guardrail_usage

    title: str | None = None
    if body.is_first_message and body.first_user_message:
        agent_type_id = conv_session.agent_type_id if conv_session else None
        try:
            namer = SessionAutoNamer()
            title = await namer.generate_and_save(
                session_id=conv_session_id,
                first_user_message=body.first_user_message,
                agent_type_id=agent_type_id,
                db=db,
            )
        except Exception as exc:
            logger.warning(
                "Auto-naming failed while appending turn for conversation %s: %s",
                conv_session_id,
                exc,
            )

    await db.commit()
    return ConversationTurnAppendResponse(title=title)


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
    from app.db.models.session_logs import ExecutionLogEntry, ExecutionEventCategory, ExecutionActorType

    # Map string values to enums with fallback to safe defaults
    try:
        category = ExecutionEventCategory(body.event_category)
    except ValueError:
        category = ExecutionEventCategory.functional
    try:
        actor = ExecutionActorType(body.actor_type)
    except ValueError:
        actor = ExecutionActorType.system

    entry_id = uuid.uuid4()
    entry = ExecutionLogEntry(
        id=entry_id,
        session_id=session_id,
        event_type=body.event_type,
        log_level=body.log_level.upper(),
        message=body.message,
        data=body.data,
        event_category=category,
        actor_type=actor,
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
