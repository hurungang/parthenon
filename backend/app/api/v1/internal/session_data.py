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
   POST  /tool-calls                        — record tool executions (batch)
   POST  /conversations/{conv_session_id}/auto-name  — generate and save conversation title
   PUT   /conversations/{conv_session_id}/activity    — upsert persisted activity state
   GET   /conversations/{conv_session_id}/activity    — hydrate persisted activity state
   POST  /conversations/{conv_session_id}/activity/touch — refresh a live working heartbeat
   PUT   /conversations/{conv_session_id}/resume      — create/reuse the live resume index
   GET   /conversations/{conv_session_id}/resume      — live resume record (explicit null)
   PUT   /conversations/{conv_session_id}/resume/checkpoint  — upsert opaque payload
   GET   /conversations/{conv_session_id}/resume/checkpoint  — load opaque payload
   POST  /conversations/{conv_session_id}/resume/claim       — acquire/renew turn claim
   POST  /conversations/{conv_session_id}/resume/release     — release turn claim
   POST  /conversations/{conv_session_id}/resume/complete    — single-transaction closer
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.models.conversation_turn_resume import (
    CheckpointPayloadKind,
    ResumeOutcome,
    ResumeState,
)
from app.db.session import DbSession
from app.schemas.conversations import ConversationOptimizationBlock
from app.services.agents.permission_manager import get_shared_permission_manager
from app.services.agents.tool_naming import build_tool_name, parse_tool_name

logger = logging.getLogger(__name__)
_permission_manager = get_shared_permission_manager()


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
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
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
    output_data: dict[str, Any] | str | list[Any] | None
    error_message: str | None
    stop_category: str | None
    stop_reason: str | None
    stop_details: dict | None
    conversation_history: list | None
    created_at: datetime
    #: Persisted delegation depth of this job (0 for a root run).  Agent
    #: Runtime seeds its guardrail state from this value so a delegated child
    #: evaluates nested delegation from its real chain depth instead of zero.
    delegation_depth: int


class ConversationHistoryResponse(BaseModel):
    """Conversation message history for a session."""

    session_id: uuid.UUID
    messages: list[dict]


class SessionResultRequest(BaseModel):
    """Request body for POST /sessions/{session_id}/result."""

    output_data: dict[str, Any] | str | list[Any] = Field(
        ..., description="Execution output payload to persist"
    )


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
    output_data: dict[str, Any] | str | list[Any] | None = None
    error_message: str | None = None
    stop_category: str | None = None
    stop_reason: str | None = None
    stop_details: dict | None = None
    intervene_request_id: str | None = None
    conversation_history: list | None = None


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


class ConversationTurnBlockedBlock(BaseModel):
    """Why a new user turn was refused while a decision is pending.

    ``reason_code`` is ``decision_pending`` (an ask/decide or a live-test
    approval is awaiting the operator). The chat keeps the composer disabled and
    re-hydrates the pending card; nothing is retried in the background.
    """

    reason_code: str = "decision_pending"
    message: str
    intervene_request_id: uuid.UUID | None = None
    live_test_request_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class ConversationTurnPrepareResponse(BaseModel):
    """Prepared execution context for a conversation turn."""

    agent_type_id: uuid.UUID | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    no_agent_message: str | None = None
    #: Present only for an optimization conversation (omitted otherwise, so the
    #: business / assistant prepare contract is unchanged).
    optimization: ConversationOptimizationBlock | None = None
    #: Present only when a decision is still pending for this conversation: the
    #: new user message is refused server-side (no turn persisted, no work,
    #: no assumption) and the client must re-surface the pending request.
    blocked: ConversationTurnBlockedBlock | None = None


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


class ConversationActivityUpsertRequest(BaseModel):
    """Request body for PUT /conversations/{conv_session_id}/activity."""

    state: str = Field(..., description="ActivityState value")
    current_turn_id: uuid.UUID | None = None
    tool_name: str | None = Field(default=None, max_length=400)
    target_agent_type_id: uuid.UUID | None = None
    pending_intervene_request_id: uuid.UUID | None = None
    active_resume_id: uuid.UUID | None = None
    detail: dict[str, Any] | None = None


class ConversationActivityResponse(BaseModel):
    """The persisted current-activity record for a conversation session.

    The durable paused-turn projection (``resume_state``,
    ``terminal_reason_code``, ``terminal_message_key``, ``write_applied``) is
    resolved from the session's resume record so Communication Hub hydrates the
    exact state Control Center owns instead of deriving it from ``detail``.
    """

    conversation_session_id: uuid.UUID
    state: str
    current_turn_id: uuid.UUID | None = None
    tool_name: str | None = None
    target_agent_type_id: uuid.UUID | None = None
    pending_intervene_request_id: uuid.UUID | None = None
    active_resume_id: uuid.UUID | None = None
    resume_state: str | None = None
    resume_outcome: str | None = None
    resume_expires_at: datetime | None = None
    terminal_reason_code: str | None = None
    terminal_message_key: str | None = None
    write_applied: bool = False
    detail: dict | None = None
    is_terminal: bool = False
    started_at: datetime | None = None
    last_updated_at: datetime | None = None
    finished_at: datetime | None = None


# ── Durable paused-turn resume / checkpoint schemas ──────────────────────────


class ConversationTurnResumeUpsertRequest(BaseModel):
    """Request body for PUT /conversations/{conv_session_id}/resume."""

    intervene_request_id: uuid.UUID | None = None
    turn_id: uuid.UUID | None = None
    #: Accepted for wire compatibility with Agent Runtime; IGNORED — Control
    #: Center recomputes the answerable window from tenant policy.
    expires_at: datetime | None = None
    resume_key: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=255)


class ConversationTurnResumeResponse(BaseModel):
    """The resume index read model — never carries the checkpoint payload."""

    resume_id: uuid.UUID
    conversation_session_id: uuid.UUID
    resume_key: str
    #: Opaque per-paused-turn key.  Agent Runtime reads it back from the record
    #: so confirmed-write tool calls carry a key that is stable for the whole
    #: paused turn (never derived from user input).
    idempotency_key: str | None = None
    state: str
    resume_outcome: str | None = None
    expires_at: datetime | None = None
    write_applied: bool = False
    is_terminal: bool = False
    terminal_reason_code: str | None = None
    terminal_message_key: str | None = None
    attempt_count: int = 0
    outcome_turn_id: uuid.UUID | None = None
    # The live resume id currently backing the paused turn (null when terminal).
    active_resume_id: uuid.UUID | None = None


class ConversationTurnResumeReleaseRequest(BaseModel):
    """Request body for POST /conversations/{conv_session_id}/resume/release."""

    instance_id: str | None = Field(default=None, max_length=255)


class ConversationTurnResumeReleaseResponse(BaseModel):
    """Result of a best-effort claim release."""

    resume_id: uuid.UUID
    released: bool


class ConversationTurnResumeCompleteRequest(BaseModel):
    """Request body for POST /conversations/{conv_session_id}/resume/complete.

    The single-transaction closer: appends the outcome turn once, records the
    terminal state/outcome, consumes the checkpoint, and resolves activity to
    ``finished``.  A duplicate call returns the stored outcome without a second
    outcome turn.
    """

    resume_id: uuid.UUID | None = None
    outcome: ResumeOutcome
    write_applied: bool = False
    applied_effect_summary: dict[str, Any] | None = None
    applied_by_user_id: uuid.UUID | None = None
    outcome_turn_id: uuid.UUID | None = None
    outcome_turn_content: str | None = None
    consume_checkpoint: bool = True


class ConversationTurnCheckpointUpsertRequest(BaseModel):
    """Request body for PUT /conversations/{conv_session_id}/resume/checkpoint."""

    payload: dict[str, Any]
    payload_kind: CheckpointPayloadKind = CheckpointPayloadKind.agent_turn_state
    schema_version: int = Field(default=1, ge=1)
    #: Accepted for wire compatibility; IGNORED — the payload lives for the
    #: resume record's answerable window (tenant policy).
    expires_at: datetime | None = None


class ConversationTurnCheckpointResponse(BaseModel):
    """Checkpoint metadata; ``payload`` is present only on a load."""

    resume_id: uuid.UUID
    payload_kind: str
    schema_version: int
    payload_bytes: int
    is_consumed: bool = False
    expires_at: datetime | None = None
    payload: dict[str, Any] | None = None


class ConversationTurnResumeClaimRequest(BaseModel):
    """Request body for POST /conversations/{conv_session_id}/resume/claim."""

    instance_id: str = Field(..., min_length=1, max_length=255)
    lease_seconds: int = Field(default=45, ge=1, le=3600)


class ConversationTurnResumeClaimResponse(BaseModel):
    """Claim arbitration result: acquired / already_held / not_found / terminal."""

    status: Literal["acquired", "already_held", "not_found", "terminal"]
    resume: ConversationTurnResumeResponse | None = None
    holder_instance_id: str | None = None
    claim_expires_at: datetime | None = None


class RuntimeToolCallRecord(BaseModel):
    """A single tool-execution record reported by Agent Runtime."""

    session_id: uuid.UUID
    session_kind: Literal["agent", "conversation"]
    tool_name: str = Field(..., min_length=1, max_length=400)
    route_type: Literal["system", "mcp", "a2a"]
    mcp_slug: str | None = Field(default=None, max_length=100)
    status: Literal["success", "error"]
    duration_ms: int | None = None
    error: str | None = None
    #: Set ONLY by the approved live-test runner: this call was part of an
    #: operator-approved, single-use optimization live test. Absent for every
    #: ordinary run, replay verification and normal conversation turn, so live
    #: contact is distinguishable from replay work in the raw tool log.
    optimization_live_test_request_id: uuid.UUID | None = None


class RuntimeToolCallIngestRequest(BaseModel):
    """Request body for POST /tool-calls — one record or a batch."""

    records: list[RuntimeToolCallRecord] = Field(..., min_length=1, max_length=100)


class RuntimeToolCallIngestResponse(BaseModel):
    """Result of ingesting tool-call records."""

    recorded: int


class A2ADataRequest(BaseModel):
    """Request body for POST /a2a/request."""

    target_agent_type_slug: str
    requester_instance_id: str
    requester_role_id: uuid.UUID | None = None
    request_payload: dict = Field(default_factory=dict)
    session_link_id: str | None = None
    active_receiver_instance_id: str | None = None
    conv_session_id: str | None = None


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
        delegation_depth=job.delegation_depth or 0,
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
    result_content: str | None = (
        body.output_data.get("result")
        if isinstance(body.output_data, dict)
        else body.output_data
        if isinstance(body.output_data, str)
        else None
    )
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
                agent_type_id=job.agent_type_id,
                title=(
                    body.output_data.get("title")
                    if isinstance(body.output_data, dict)
                    else None
                ) or None,
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
            # Extract output_id from output_data if present (set by typed output persistence)
            if isinstance(body.output_data, dict) and "output_id" in body.output_data:
                output_id_str = body.output_data["output_id"]
                if isinstance(output_id_str, str):
                    try:
                        job.output_id = uuid.UUID(output_id_str)
                    except ValueError:
                        logger.warning("Invalid output_id format in output_data: %s", output_id_str)
                elif isinstance(output_id_str, uuid.UUID):
                    job.output_id = output_id_str
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
        if body.conversation_history is not None:
            job.conversation_history = body.conversation_history

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
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> A2ADataResponse:
    """Resolve target agent type, enforce permission, create session link, enqueue receiver job.

    Communication Hub calls this endpoint so all A2A DB access remains in Control Center.
    The target agent type resolves strictly by ``(tenant_id, name)`` — a name
    collision across tenants never routes to the wrong tenant's agent.
    """
    from sqlalchemy import select

    from app.db.models.agents import (
        A2ASessionStatus,
        AgentA2ASession,
        AgentJob,
        AgentType,
    )
    from app.services.agents.session_service import AgentSessionService
    from app.services.control_center.comm_hub_client import (
        CommunicationHubClient,
        CommunicationHubClientError,
    )

    result = await db.execute(
        select(AgentType).where(
            AgentType.name == body.target_agent_type_slug,
            AgentType.tenant_id == tenant_ctx.tenant_id,
        )
    )
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

    # Parse parent job ID only when requester_instance_id is an existing agent_job.
    # Conversational agents pass conv_session_id as requester_instance_id, which lives in
    # conversation_sessions (not agent_jobs) and would violate the FK constraint.
    parent_job_id: uuid.UUID | None = None
    try:
        _candidate = uuid.UUID(str(body.requester_instance_id))
        _exists = await db.scalar(select(AgentJob.id).where(AgentJob.id == _candidate).limit(1))
        if _exists is not None:
            parent_job_id = _candidate
    except (ValueError, AttributeError):
        pass

    session_service = AgentSessionService()
    enqueue_input = body.request_payload.copy() if body.request_payload else {}
    if body.conv_session_id:
        enqueue_input["__conv_session_id"] = body.conv_session_id
    enqueue_input["__requester_session_id"] = body.requester_instance_id

    # Trigger provenance: when the delegating session is a conversation
    # (chat-originated delegation), resolve the chat user from the source
    # ConversationSession so the delegated job carries the human trigger —
    # otherwise the job would show "unknown" provenance in the runtime
    # monitor.  Jobs delegated from another agent job inherit via
    # session_service.enqueue (parent triggered_by_user_id).
    delegation_user_id: uuid.UUID | None = None
    if body.conv_session_id:
        try:
            conv_uuid = uuid.UUID(str(body.conv_session_id))
        except (ValueError, AttributeError):
            conv_uuid = None
        if conv_uuid is not None:
            from app.db.models.conversations import ConversationSession

            conv_row = await db.get(ConversationSession, conv_uuid)
            if conv_row is not None:
                delegation_user_id = conv_row.triggered_by_user_id

    receiver_job = await session_service.enqueue(
        agent_type_id=target_agent_type.id,
        input_data=enqueue_input,
        user_id=delegation_user_id,
        db=db,
        parent_job_id=parent_job_id,
        tenant_id=tenant_ctx.tenant_id,
    )
    await db.commit()

    try:
        client = CommunicationHubClient()
        await client.trigger_execution(
            session_id=receiver_job.id,
            agent_type_id=target_agent_type.id,
            input_data=body.request_payload,
            # Multi-tenancy: propagate the signed calling tenant so the
            # delegated sub-agent run is tenant-bound end to end (AR
            # verifies the headers and re-forwards them on its own CC calls).
            tenant_context=tenant_ctx,
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


async def _pending_decision_block(
    db: AsyncSession, conv_session_id: uuid.UUID
) -> "ConversationTurnBlockedBlock | None":
    """Return the refusal block when this conversation awaits a decision.

    The durable resume record is the authority (it survives reconnects and
    instance failover): a live ``waiting_for_human`` record means the operator
    still owes an answer, so a new user turn must be refused WITHOUT persisting
    anything and without any background work or assumption.

    Overdue live-test approvals are closed first (lazy expiry) so an expired
    approval never blocks the conversation.
    """
    from app.db.models.conversation_turn_resume import ResumeState
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    record = await ConversationTurnResumeStore().get_live_for_session(
        conv_session_id, db
    )
    if record is None or record.state is not ResumeState.waiting_for_human:
        return None

    # A pause is live: only now pay for the live-test expiry check. An overdue
    # approval is closed here, which settles the pause and unblocks the chat.
    try:
        from app.services.agents.optimization_live_test_service import (
            get_live_test_service,
        )

        if await get_live_test_service().expire_overdue(
            db, conversation_session_id=conv_session_id
        ):
            await db.flush()
            record = await ConversationTurnResumeStore().get_live_for_session(
                conv_session_id, db
            )
            if record is None or record.state is not ResumeState.waiting_for_human:
                return None
    except Exception:  # noqa: BLE001 — a prepare must never fail on the sweep
        logger.warning(
            "Live-test expiry check failed for conversation %s", conv_session_id,
            exc_info=True,
        )

    live_test_request_id: uuid.UUID | None = None
    if record.intervene_request_id is not None:
        try:
            from app.services.agents.optimization_live_test_service import (
                get_live_test_service,
            )

            live_row = await get_live_test_service().get_for_intervention(
                db, record.intervene_request_id
            )
            if live_row is not None:
                live_test_request_id = live_row.id
        except Exception:  # noqa: BLE001 — the block does not depend on this
            live_test_request_id = None

    return ConversationTurnBlockedBlock(
        reason_code="decision_pending",
        message=(
            "Waiting for your decision on the pending request — answer it (or "
            "end the conversation) before sending another message."
        ),
        intervene_request_id=record.intervene_request_id,
        live_test_request_id=live_test_request_id,
        expires_at=record.expires_at,
    )


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/prepare-turn",
    response_model=ConversationTurnPrepareResponse,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_service_certificate)],
    summary="Persist user turn and return prepared conversation context",
)
async def prepare_conversation_turn(
    conv_session_id: uuid.UUID,
    body: ConversationTurnPrepareRequest,
    db: DbSession,
) -> ConversationTurnPrepareResponse:
    """Persist the user message and return conversation messages for runtime execution.

    The conversation's CHANNEL decides the mode: an optimization conversation
    runs the conversational loop regardless of the agent type's ``input_type``
    and receives the optimization mission as the system message plus an
    ``optimization`` guidance block. Business / assistant conversations keep
    their existing prepare contract (no block, no mode change).

    A conversation that is still waiting for the operator's decision refuses the
    new message (``blocked``) without persisting a turn, starting work, or
    assuming anything.
    """
    from app.api.v1.internal.agent_data import get_agent_context
    from app.db.models.agents import AgentType
    from app.db.models.conversations import ConversationSession, ConversationTurn, TurnRole
    from app.services.agents.optimization_mode import (
        OPTIMIZATION_MODE,
        get_optimization_conversation_availability,
        resolve_optimization_mode,
    )
    from app.services.conversations.store import ConversationStore

    # Decision pending: refuse the new turn BEFORE anything is written.
    blocked = await _pending_decision_block(db, conv_session_id)
    if blocked is not None:
        conv_session_for_block = await db.get(ConversationSession, conv_session_id)
        return ConversationTurnPrepareResponse(
            agent_type_id=(
                conv_session_for_block.agent_type_id
                if conv_session_for_block is not None
                else None
            ),
            messages=[],
            no_agent_message=None,
            blocked=blocked,
        )

    store = ConversationStore()
    user_turn = await store.add_turn(conv_session_id, TurnRole.user, body.user_message, db)

    conv_session = await db.get(ConversationSession, conv_session_id)
    if conv_session is None:
        await db.commit()
        return ConversationTurnPrepareResponse(
            agent_type_id=None,
            messages=[],
            no_agent_message=_build_no_agent_message(False, False),
        )

    # Channel decides the loop; ``input_type`` is not consulted for this.
    conv_mode = await resolve_optimization_mode(db, conv_session_id)
    is_optimization = bool(conv_mode is not None and conv_mode.is_optimization)

    # Persistent activity state: the assistant starts "thinking" on the new
    # turn so reconnecting clients hydrate a working indicator immediately.
    from app.db.models.conversation_activity import ActivityState
    from app.services.conversations.activity_store import ConversationActivityStore

    try:
        await ConversationActivityStore().upsert(
            conv_session_id,
            db,
            state=ActivityState.thinking,
            current_turn_id=user_turn.id,
        )
    except LookupError:
        pass  # Session missing — handled by the no_agent_message path above
    except Exception as exc:
        logger.warning(
            "Failed to set thinking activity for conversation %s: %s",
            conv_session_id, exc,
        )

    if conv_session.agent_type_id is None:
        await db.commit()
        return ConversationTurnPrepareResponse(
            agent_type_id=None,
            messages=[],
            no_agent_message=_build_no_agent_message(True, False),
        )

    agent_type = await db.get(AgentType, conv_session.agent_type_id)
    # A business conversation needs the agent's runtime model. An optimization
    # conversation does NOT: it runs on the workspace optimizer model, which is
    # resolved (and fails closed) by the agent-context call below.
    if agent_type is None or (not is_optimization and not agent_type.model_id):
        await db.commit()
        return ConversationTurnPrepareResponse(
            agent_type_id=conv_session.agent_type_id,
            messages=[],
            no_agent_message=_build_no_agent_message(True, True),
        )

    context = await get_agent_context(
        agent_type_id=agent_type.id,
        db=db,
        conv_session_id=conv_session_id,
    )
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

    optimization_block: ConversationOptimizationBlock | None = None
    if is_optimization:
        availability = await get_optimization_conversation_availability(db, agent_type)
        optimization_block = ConversationOptimizationBlock(
            mode=OPTIMIZATION_MODE,
            subject_agent_type_id=agent_type.id,
            available=availability.available,
            reason_code=availability.reason_code,
            reason=availability.reason,
        )

    await db.commit()
    return ConversationTurnPrepareResponse(
        agent_type_id=agent_type.id,
        messages=messages,
        no_agent_message=None,
        **({"optimization": optimization_block} if is_optimization else {}),
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

    # Persistent activity state: resolve the activity to a terminal outcome.
    # The final status event decides which terminal state — a watchdog/
    # provider timeout maps to ``timed_out``, a guardrail stop to ``failed``,
    # and a normal reply to ``finished``.
    from app.db.models.conversation_activity import ActivityState
    from app.services.conversations.activity_store import ConversationActivityStore

    _activity_state = ActivityState.finished
    for status_event in reversed(body.status_events):
        if not isinstance(status_event, dict):
            continue
        status_value = status_event.get("status")
        if not isinstance(status_value, str) or not status_value:
            continue
        if status_value == "timeout_or_failed":
            _activity_state = ActivityState.timed_out
        elif status_value.startswith("guardrail_"):
            _activity_state = ActivityState.failed
        break
    try:
        await ConversationActivityStore().resolve_terminal(
            conv_session_id, db, state=_activity_state
        )
    except Exception as exc:
        logger.warning(
            "Failed to resolve terminal activity for conversation %s: %s",
            conv_session_id, exc,
        )

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
        # Defense-in-depth: conversation sessions have no row in the
        # AgentJob-backed sessions table, so an FK violation here means the
        # caller shipped an execution-log entry for a conversation session.
        # Conversational turns don't need execution-log persistence — ack
        # the write as a no-op (200) instead of breaking the caller with 500.
        from sqlalchemy.exc import IntegrityError

        from app.db.models.conversations import ConversationSession

        if isinstance(exc, IntegrityError):
            try:
                await db.rollback()
                conv_session = await db.get(ConversationSession, session_id)
            except Exception:
                conv_session = None
            if conv_session is not None:
                logger.debug(
                    "Execution-log entry skipped for conversation session %s "
                    "(conversation sessions don't persist execution logs)",
                    session_id,
                )
                return LogExecutionEventResponse(entry_id=entry_id)
        logger.warning("Failed to persist log entry for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to persist log entry")

    return LogExecutionEventResponse(entry_id=entry_id)


@InternalSessionDataRouter.post(
    "/tool-calls",
    response_model=RuntimeToolCallIngestResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Record tool executions performed by Agent Runtime",
)
async def record_tool_calls(
    body: RuntimeToolCallIngestRequest,
    db: DbSession,
) -> RuntimeToolCallIngestResponse:
    """Persist one or a batch of tool-call records from Agent Runtime.

    ``session_id`` is polymorphic: an agent job id (``session_kind="agent"``)
    or a conversation session id (``session_kind="conversation"``).  There is
    intentionally no FK so conversation turns — which execute without a
    backing AgentJob — can record their tool calls too.

    Agent Runtime treats this write as fire-and-forget: recording failures
    must never abort tool execution, so this endpoint always returns 200 with
    the count of records persisted (invalid rows are dropped, not fatal).
    """
    from app.db.models.tool_calls import (
        RuntimeToolCall,
        RuntimeToolCallRouteType,
        RuntimeToolCallSessionKind,
        RuntimeToolCallStatus,
    )

    recorded = 0
    for item in body.records:
        try:
            db.add(
                RuntimeToolCall(
                    session_id=item.session_id,
                    session_kind=RuntimeToolCallSessionKind(item.session_kind),
                    tool_name=item.tool_name,
                    route_type=RuntimeToolCallRouteType(item.route_type),
                    mcp_slug=item.mcp_slug,
                    status=RuntimeToolCallStatus(item.status),
                    duration_ms=item.duration_ms,
                    error=item.error,
                    optimization_live_test_request_id=(
                        item.optimization_live_test_request_id
                    ),
                )
            )
            recorded += 1
        except (ValueError, TypeError) as exc:
            logger.warning("Dropping invalid tool-call record (%s): %s", item, exc)

    if recorded == 0:
        return RuntimeToolCallIngestResponse(recorded=0)

    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist tool-call records: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to persist tool-call records")

    return RuntimeToolCallIngestResponse(recorded=recorded)


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


# ── Conversation activity (persistent agent activity state) ──────────────────


async def _activity_response(
    activity: Any,
    conv_session_id: uuid.UUID,
    db: AsyncSession | None = None,
) -> ConversationActivityResponse:
    from app.db.models.conversation_activity import ActivityState
    from app.db.models.conversation_turn_resume import ConversationTurnResume

    state = activity.state
    resume: ConversationTurnResume | None = None
    if db is not None:
        resume = await _projected_resume(activity, db)
    # A stale working row that died mid-flight has no resume record to carry the
    # terminal reason; the reaper records it in the activity detail instead.
    detail = activity.detail if isinstance(activity.detail, dict) else {}
    detail_reason = detail.get("terminal_reason_code")
    detail_message_key = detail.get("terminal_message_key")
    return ConversationActivityResponse(
        conversation_session_id=conv_session_id,
        state=state.value if isinstance(state, ActivityState) else str(state),
        current_turn_id=activity.current_turn_id,
        tool_name=activity.tool_name,
        target_agent_type_id=activity.target_agent_type_id,
        pending_intervene_request_id=activity.pending_intervene_request_id,
        active_resume_id=activity.active_resume_id,
        resume_state=(
            (resume.state.value if isinstance(resume.state, ResumeState) else str(resume.state))
            if resume is not None
            else None
        ),
        resume_outcome=(
            (resume.resume_outcome.value if isinstance(resume.resume_outcome, ResumeOutcome) else resume.resume_outcome)
            if resume is not None and resume.resume_outcome is not None
            else None
        ),
        resume_expires_at=resume.expires_at if resume is not None else None,
        terminal_reason_code=(
            detail_reason
            if isinstance(detail_reason, str) and detail_reason
            else (resume.terminal_reason_code if resume is not None else None)
        ),
        terminal_message_key=(
            detail_message_key
            if isinstance(detail_message_key, str) and detail_message_key
            else (resume.terminal_message_key if resume is not None else None)
        ),
        write_applied=bool(resume.write_applied) if resume is not None else False,
        detail=activity.detail,
        is_terminal=activity.is_terminal,
        started_at=activity.started_at,
        last_updated_at=activity.last_updated_at,
        finished_at=activity.finished_at,
    )


async def _projected_resume(activity: Any, db: AsyncSession) -> Any:
    """Resolve the resume record that explains the persisted activity state.

    The live record backing a paused turn wins; otherwise a terminal activity
    falls back to the session's newest terminal record so hydration can carry
    the reason code of a turn the Terminal Resolver already closed.
    """
    from app.db.models.conversation_turn_resume import ConversationTurnResume
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    store = ConversationTurnResumeStore()
    if activity.active_resume_id is not None:
        record: ConversationTurnResume | None = await store.get(
            activity.active_resume_id, db
        )
        if record is not None:
            return record
    if activity.is_terminal:
        latest = await store.get_latest_for_session(
            activity.conversation_session_id, db
        )
        if latest is not None and latest.is_terminal:
            return latest
    return None


def _turn_resume_response(record: Any) -> ConversationTurnResumeResponse:
    """Build the resume read model (state/outcome/terminal reason, never payload)."""
    state = record.state
    outcome = record.resume_outcome
    return ConversationTurnResumeResponse(
        resume_id=record.id,
        conversation_session_id=record.conversation_session_id,
        resume_key=record.resume_key,
        idempotency_key=record.idempotency_key,
        state=state.value if isinstance(state, ResumeState) else str(state),
        resume_outcome=(
            outcome.value if isinstance(outcome, ResumeOutcome) else outcome
        ),
        expires_at=record.expires_at,
        write_applied=record.write_applied,
        is_terminal=record.is_terminal,
        terminal_reason_code=record.terminal_reason_code,
        terminal_message_key=record.terminal_message_key,
        attempt_count=record.attempt_count,
        outcome_turn_id=record.outcome_turn_id,
        active_resume_id=None if record.is_terminal else record.id,
    )


def _checkpoint_response(record: Any, *, include_payload: bool) -> ConversationTurnCheckpointResponse:
    kind = record.payload_kind
    return ConversationTurnCheckpointResponse(
        resume_id=record.resume_id,
        payload_kind=kind.value if isinstance(kind, CheckpointPayloadKind) else str(kind),
        schema_version=record.schema_version,
        payload_bytes=record.payload_bytes,
        is_consumed=record.is_consumed,
        expires_at=record.expires_at,
        payload=record.payload if include_payload else None,
    )


async def _tenant_scoped_conversation_session(
    conv_session_id: uuid.UUID,
    tenant_ctx: TenantContext,
    db: AsyncSession,
) -> Any:
    """Resolve a conversation session, rejecting cross-tenant access.

    The signed internal tenant context decides the tenant (forward-only: no
    client-supplied tenant is ever accepted).  A session owned by another
    tenant is rejected with 403 and nothing is persisted.
    """
    from app.db.models.conversations import ConversationSession

    conv_session = await db.get(ConversationSession, conv_session_id)
    if conv_session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Conversation session {conv_session_id} not found",
        )
    session_tenant_id = getattr(conv_session, "tenant_id", None)
    if (
        tenant_ctx.tenant_id is not None
        and session_tenant_id is not None
        and session_tenant_id != tenant_ctx.tenant_id
    ):
        logger.warning(
            "Cross-tenant conversation access rejected: session=%s session_tenant=%s "
            "request_tenant=%s",
            conv_session_id,
            session_tenant_id,
            tenant_ctx.tenant_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Conversation session belongs to a different tenant",
        )
    return conv_session


@InternalSessionDataRouter.put(
    "/conversations/{conv_session_id}/activity",
    response_model=ConversationActivityResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Upsert the persisted conversation activity (single live row per session)",
)
async def upsert_conversation_activity(
    conv_session_id: uuid.UUID,
    body: ConversationActivityUpsertRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationActivityResponse:
    """Persist an activity transition from Agent Runtime (relayed via Communication Hub).

    Communication Hub calls this endpoint — Agent Runtime never touches the
    database. The conversation session is tenant-scoped by the signed internal
    tenant context; an unknown session fails with 404 and a cross-tenant
    session fails with 403.

    A ``waiting_for_human`` transition requires a live resume record; without
    one the write is rejected with 409 so the UI can never show "waiting" for a
    turn that is not actually answerable.
    """
    from app.db.models.conversation_activity import ActivityState
    from app.services.conversations.activity_store import (
        ActivityResumeInvariantError,
        ConversationActivityStore,
    )

    try:
        state = ActivityState(body.state)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown activity state '{body.state}'",
        )

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)

    store = ConversationActivityStore()
    try:
        activity = await store.upsert(
            conv_session_id,
            db,
            state=state,
            current_turn_id=body.current_turn_id,
            tool_name=body.tool_name,
            target_agent_type_id=body.target_agent_type_id,
            pending_intervene_request_id=body.pending_intervene_request_id,
            detail=body.detail,
            active_resume_id=body.active_resume_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ActivityResumeInvariantError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    # Re-load server-default / onupdate columns (started_at, last_updated_at)
    # before building the response — after commit the instance is expired and a
    # sync attribute access inside the response builder would trigger lazy IO
    # (MissingGreenlet) on the second-and-later upsert (update path).
    await db.refresh(activity)

    logger.info(
        "Activity upserted for conversation %s → %s",
        conv_session_id,
        state.value,
    )
    return await _activity_response(activity, conv_session_id, db)


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/activity/touch",
    response_model=ConversationActivityResponse | None,
    dependencies=[Depends(require_service_certificate)],
    summary="Refresh the activity heartbeat of a live working turn",
)
async def touch_conversation_activity(
    conv_session_id: uuid.UUID,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationActivityResponse | None:
    """Refresh ``last_updated_at`` for a live working activity row.

    Communication Hub calls this from its ~15s conversation heartbeat so a
    genuinely live turn stays fresh while the model is quiet, which lets the
    reaper's staleness bound mean "the heartbeat stopped → the turn is dead".
    No state change: terminal and ``waiting_for_human`` rows are untouched
    (a paused turn deliberately stops emitting beats, and the reaper's pause
    semantics come from the durable resume record, not a heartbeat).
    """
    from app.services.conversations.activity_store import ConversationActivityStore

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)

    store = ConversationActivityStore()
    activity = await store.touch(conv_session_id, db)
    if activity is None:
        return None
    await db.commit()
    # Re-load server-default / onupdate columns before building the response.
    await db.refresh(activity)
    return await _activity_response(activity, conv_session_id, db)


@InternalSessionDataRouter.get(
    "/conversations/{conv_session_id}/activity",
    response_model=ConversationActivityResponse | None,
    dependencies=[Depends(require_service_certificate)],
    summary="Return the persisted current activity (explicit null when idle)",
)
async def get_conversation_activity(
    conv_session_id: uuid.UUID,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationActivityResponse | None:
    """Hydrate the current activity for a conversation session.

    Communication Hub calls this on WebSocket connect; an idle session
    (no live activity row) returns an explicit ``null`` body.
    """
    from app.services.conversations.activity_store import ConversationActivityStore

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)

    store = ConversationActivityStore()
    activity = await store.get(conv_session_id, db)
    if activity is None:
        return None
    return await _activity_response(activity, conv_session_id, db)


# ── Durable paused-turn resume index / checkpoint (CH → CC only) ─────────────


@InternalSessionDataRouter.put(
    "/conversations/{conv_session_id}/resume",
    response_model=ConversationTurnResumeResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Create or reuse the live resume record for a paused turn",
)
async def save_conversation_turn_resume(
    conv_session_id: uuid.UUID,
    body: ConversationTurnResumeUpsertRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnResumeResponse:
    """Register a pause (create) or reuse the record for the same intervention.

    Any other live record for the session is superseded in the same
    transaction, so at most one live resume row exists per session.

    Control Center is the authority for the answerable window: ``expires_at``
    is recomputed as ``now + tenant resume TTL`` (default 15 minutes) and any
    client-supplied ``expires_at`` from Agent Runtime is ignored, so a tenant's
    configured policy always wins.
    """
    from app.services.conversations.turn_resume_settings import (
        resolve_resume_expiry,
    )
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
        TurnResumeConflictError,
        TurnResumeNotFoundError,
    )

    conv_session = await _tenant_scoped_conversation_session(
        conv_session_id, tenant_ctx, db
    )
    expires_at = await resolve_resume_expiry(db, tenant_id=conv_session.tenant_id)
    try:
        record = await ConversationTurnResumeStore().create_or_reuse(
            conv_session_id,
            db,
            intervene_request_id=body.intervene_request_id,
            turn_id=body.turn_id,
            # Deliberately NOT body.expires_at: tenant policy decides.
            expires_at=expires_at,
            resume_key=body.resume_key,
            idempotency_key=body.idempotency_key,
            tenant_id=conv_session.tenant_id,
        )
    except TurnResumeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TurnResumeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    await db.refresh(record)
    return _turn_resume_response(record)


@InternalSessionDataRouter.get(
    "/conversations/{conv_session_id}/resume",
    response_model=ConversationTurnResumeResponse | None,
    dependencies=[Depends(require_service_certificate)],
    summary="Return the live resume record (explicit null when idle)",
)
async def get_conversation_turn_resume(
    conv_session_id: uuid.UUID,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnResumeResponse | None:
    """Return the session's live resume record, or an explicit ``null``."""
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)
    record = await ConversationTurnResumeStore().get_live_for_session(
        conv_session_id, db
    )
    if record is None:
        return None
    return _turn_resume_response(record)


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/resume/release",
    response_model=ConversationTurnResumeReleaseResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Release the turn claim (best effort)",
)
async def release_conversation_turn_resume(
    conv_session_id: uuid.UUID,
    body: ConversationTurnResumeReleaseRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnResumeReleaseResponse:
    """Release the caller's claim on the session's live resume record."""
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)
    store = ConversationTurnResumeStore()
    record = await store.get_live_for_session(conv_session_id, db)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No live resume record for conversation {conv_session_id}",
        )
    released = await store.release(record.id, db, instance_id=body.instance_id)
    await db.commit()
    return ConversationTurnResumeReleaseResponse(
        resume_id=record.id, released=released
    )


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/resume/complete",
    response_model=ConversationTurnResumeResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Single-transaction closer: outcome turn + terminal state + activity",
)
async def complete_conversation_turn_resume(
    conv_session_id: uuid.UUID,
    body: ConversationTurnResumeCompleteRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnResumeResponse:
    """Close a paused turn exactly once.

    One transaction: append the outcome turn (guarded by ``outcome_turn_id``),
    set the terminal state/outcome, consume the checkpoint, and resolve the
    activity to ``finished``.  A duplicate call returns the stored outcome and
    appends no second outcome turn.
    """
    from app.db.models.conversation_activity import ActivityState
    from app.db.models.conversations import TurnRole
    from app.services.conversations.activity_store import ConversationActivityStore
    from app.services.conversations.store import ConversationStore
    from app.services.conversations.turn_checkpoint_store import (
        ConversationTurnCheckpointStore,
    )
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
        TurnResumeTransitionError,
    )

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)
    store = ConversationTurnResumeStore()

    record = None
    if body.resume_id is not None:
        record = await store.get(body.resume_id, db)
        if record is not None and record.conversation_session_id != conv_session_id:
            record = None
    if record is None:
        record = await store.get_live_for_session(conv_session_id, db)
    if record is None:
        latest = await store.get_latest_for_session(conv_session_id, db)
        if latest is not None and latest.is_terminal:
            return _turn_resume_response(latest)
        raise HTTPException(
            status_code=404,
            detail=f"No resume record for conversation {conv_session_id}",
        )

    if record.is_terminal:
        # Duplicate close: report the stored outcome, append nothing.
        if body.consume_checkpoint:
            await ConversationTurnCheckpointStore().mark_consumed(record.id, db)
            await db.commit()
        return _turn_resume_response(record)

    outcome_turn_id = body.outcome_turn_id
    if record.outcome_turn_id is None and outcome_turn_id is None:
        if body.outcome_turn_content:
            outcome_turn = await ConversationStore().add_turn(
                conv_session_id,
                TurnRole.agent,
                body.outcome_turn_content,
                db,
            )
            outcome_turn_id = outcome_turn.id
    if outcome_turn_id is None:
        outcome_turn_id = record.outcome_turn_id

    try:
        record = await store.resolve(
            record.id,
            db,
            body.outcome,
            write_applied=body.write_applied,
            applied_by_user_id=body.applied_by_user_id,
            applied_effect_summary=body.applied_effect_summary,
            outcome_turn_id=outcome_turn_id,
        )
    except TurnResumeTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if body.consume_checkpoint:
        await ConversationTurnCheckpointStore().mark_consumed(record.id, db)
    await ConversationActivityStore().resolve_terminal(
        conv_session_id, db, state=ActivityState.finished
    )
    await db.commit()
    await db.refresh(record)
    return _turn_resume_response(record)


@InternalSessionDataRouter.put(
    "/conversations/{conv_session_id}/resume/checkpoint",
    response_model=ConversationTurnCheckpointResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Upsert the opaque checkpoint payload for the live resume record",
)
async def save_conversation_turn_checkpoint(
    conv_session_id: uuid.UUID,
    body: ConversationTurnCheckpointUpsertRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnCheckpointResponse:
    """Persist the opaque paused-turn payload (size-capped, one row per resume).

    The payload's expiry follows the resume record's answerable window (tenant
    policy): a tenant that allows a longer window than the platform default
    must not have its saved state purged early, and a client-supplied
    ``expires_at`` is ignored.
    """
    from app.services.conversations.turn_checkpoint_store import (
        CheckpointPayloadError,
        CheckpointTooLargeError,
        ConversationTurnCheckpointStore,
    )
    from app.services.conversations.turn_resume_settings import (
        resolve_resume_expiry,
    )
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    conv_session = await _tenant_scoped_conversation_session(
        conv_session_id, tenant_ctx, db
    )
    live = await ConversationTurnResumeStore().get_live_for_session(
        conv_session_id, db
    )
    if live is None:
        raise HTTPException(
            status_code=404,
            detail=f"No live resume record for conversation {conv_session_id}",
        )
    expires_at = live.expires_at or await resolve_resume_expiry(
        db, tenant_id=conv_session.tenant_id
    )

    try:
        checkpoint = await ConversationTurnCheckpointStore().upsert_payload(
            live.id,
            db,
            payload=body.payload,
            payload_kind=body.payload_kind,
            schema_version=body.schema_version,
            # Deliberately NOT body.expires_at: tenant policy decides.
            expires_at=expires_at,
        )
    except CheckpointTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except CheckpointPayloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    await db.refresh(checkpoint)
    return _checkpoint_response(checkpoint, include_payload=False)


@InternalSessionDataRouter.get(
    "/conversations/{conv_session_id}/resume/checkpoint",
    response_model=ConversationTurnCheckpointResponse | None,
    dependencies=[Depends(require_service_certificate)],
    summary="Load the opaque checkpoint payload (null when absent/consumed/expired)",
)
async def get_conversation_turn_checkpoint(
    conv_session_id: uuid.UUID,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnCheckpointResponse | None:
    """Return the loadable payload for the live resume record, or ``null``."""
    from app.services.conversations.turn_checkpoint_store import (
        ConversationTurnCheckpointStore,
    )
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)
    live = await ConversationTurnResumeStore().get_live_for_session(
        conv_session_id, db
    )
    if live is None:
        return None
    checkpoint = await ConversationTurnCheckpointStore().load_payload(live.id, db)
    if checkpoint is None:
        return None
    return _checkpoint_response(checkpoint, include_payload=True)


@InternalSessionDataRouter.post(
    "/conversations/{conv_session_id}/resume/claim",
    response_model=ConversationTurnResumeClaimResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Acquire or renew the turn claim (acquired/already_held/not_found/terminal)",
)
async def claim_conversation_turn_resume(
    conv_session_id: uuid.UUID,
    body: ConversationTurnResumeClaimRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> ConversationTurnResumeClaimResponse:
    """Claim the paused turn so one instance continues it at a time."""
    from app.services.conversations.turn_resume_store import (
        ClaimStatus,
        ConversationTurnResumeStore,
    )

    await _tenant_scoped_conversation_session(conv_session_id, tenant_ctx, db)
    store = ConversationTurnResumeStore()
    record = await store.get_live_for_session(conv_session_id, db)
    if record is None:
        latest = await store.get_latest_for_session(conv_session_id, db)
        if latest is not None and latest.is_terminal:
            return ConversationTurnResumeClaimResponse(
                status=ClaimStatus.terminal.value,
                resume=_turn_resume_response(latest),
                holder_instance_id=latest.claimed_by_instance_id,
                claim_expires_at=latest.claim_expires_at,
            )
        return ConversationTurnResumeClaimResponse(
            status=ClaimStatus.not_found.value
        )

    result = await store.claim(
        record.id,
        db,
        instance_id=body.instance_id,
        lease_seconds=body.lease_seconds,
    )
    await db.commit()
    resume_response = (
        _turn_resume_response(result.resume) if result.resume is not None else None
    )
    return ConversationTurnResumeClaimResponse(
        status=result.status.value,
        resume=resume_response,
        holder_instance_id=result.holder_instance_id,
        claim_expires_at=result.claim_expires_at,
    )


# ── Internal intervention respond (CH cert auth, no JWT needed) ──────────────

from app.schemas.intervene import InterveneResponseRead
from app.services.agents.intervene_service import InterveneRequestStore
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
from app.api.v1.intervene import _resume_agent_session

_internal_intervene_store = InterveneRequestStore()


class InternalInterveneRespondRequest(BaseModel):
    request_id: uuid.UUID
    approval_value: bool | None = None
    selected_choice: str | None = None
    text_value: str | None = None
    operator_subject: str | None = None  # OIDC subject from WebSocket session


@InternalSessionDataRouter.post(
    "/intervene/respond",
    response_model=InterveneResponseRead,
    dependencies=[Depends(require_service_certificate)],
    summary="Submit intervention response (internal, service-cert auth)",
)
async def internal_intervene_respond(
    body: InternalInterveneRespondRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: DbSession,
) -> InterveneResponseRead:
    """Submit an intervention response (internal, service-cert auth).

    ``tenant_ctx`` is the VERIFIED signed tenant context (or the root tenant in
    single-tenant mode). It is threaded explicitly into the resume dispatch:
    this path is a bypassed ``/api/v1/internal/*`` route, so no tenant
    contextvar is bound here and relying on it dispatched the resume
    headerless (CH→CC relay 401 → the turn died as ``unresumable``).
    """
    req = await db.get(InterveneRequest, body.request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != InterveneRequestStatus.pending:
        raise HTTPException(status_code=400, detail=f"Request is {req.status.value}")

    # Resolve operator user from the conversation session or agent job
    operator_user_id: uuid.UUID | None = None
    from app.db.models.agents import AgentJob
    from app.db.models.identity import Identity

    job = await db.get(AgentJob, req.agent_session_id)
    if job and job.triggered_by_user_id:
        # triggered_by_user_id on AgentJob IS an Identity UUID (FK → identities.id)
        operator_user_id = job.triggered_by_user_id

    if operator_user_id is None and body.operator_subject:
        # Look up Identity by OIDC subject (identity plane —
        # tenant-scope-exempt, FIX-20260929-221449: the operator's
        # Identity row may live in another tenant than the signed
        # request context).
        from app.db.tenant_scoping import execute_unscoped

        identity_result = await execute_unscoped(
            db, select(Identity).where(Identity.subject == body.operator_subject)
        )
        identity = identity_result.scalar_one_or_none()
        if identity:
            operator_user_id = identity.id

    if operator_user_id is None:
        raise HTTPException(status_code=400, detail="Cannot determine operator user for intervention response")

    # Same transaction as the stored response: advance the durable resume record
    # (answering user, `resuming`, attempt) — or, for a terminal record / an
    # elapsed answer window, settle it without dispatching anything.
    from app.services.conversations.turn_resolution import (
        REASON_EXPIRED,
        advance_answered_intervention,
        dispatch_answered_conversation_turn,
        execute_approved_live_test,
        prepare_live_test_decision,
        push_outcome_message,
    )

    # Live-test approval: apply the decision to the ledger BEFORE the response
    # and the resume advance, so the expiry check wins (nothing is recorded for
    # an expired approval). No linked ledger row → handled=False.
    live_decision = await prepare_live_test_decision(
        db, req, approved=body.approval_value
    )
    if live_decision.expired:
        await db.commit()
        if req.conversation_session_id is not None:
            await push_outcome_message(req.conversation_session_id, REASON_EXPIRED)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "live_test_expired",
                "reason": (
                    "This live-test approval expired before it was answered. "
                    "Nothing ran — verification stays replay-only."
                ),
            },
        )

    response = await _internal_intervene_store.submit_response(
        db=db,
        request_id=body.request_id,
        operator_user_id=operator_user_id,
        approval_value=body.approval_value,
        selected_choice=body.selected_choice,
        text_value=body.text_value,
    )

    advance = await advance_answered_intervention(
        db, req, operator_user_id=operator_user_id
    )
    response_data = InterveneResponseRead.model_validate(response)
    await db.commit()

    response_value: dict = {}
    if body.approval_value is not None:
        response_value["approval_value"] = body.approval_value
    if body.selected_choice is not None:
        response_value["selected_choice"] = body.selected_choice
    if body.text_value is not None:
        response_value["text_value"] = body.text_value
    if live_decision.handled:
        response_value.update(live_decision.resume_payload)

    if live_decision.should_execute and live_decision.request_id is not None and advance.dispatch:
        # The approved SCRIPT, once end to end, before the resume.
        payload = await execute_approved_live_test(
            db,
            live_decision.request_id,
            tenant_context=tenant_ctx,
        )
        response_value.update(payload)

    if req.agent_session_id is not None:
        agent_session_id = req.agent_session_id
        await _resume_agent_session(
            agent_session_id, response_value, tenant_context=tenant_ctx
        )
    elif req.conversation_session_id is not None:
        # Conversation-scoped request (conversational assistant): dispatch the
        # durable resume with the resume identity so a duplicate answer can
        # never start a second resume.
        await dispatch_answered_conversation_turn(
            db, req, advance, response_value, tenant_context=tenant_ctx
        )

    return response_data
