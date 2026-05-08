"""Agent management API routers: AgentRole, AgentIdentity, AgentJob, AgentType, AgentInstance, ModelConfig."""
import json
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.api.deps import require_permission, get_current_claims
from app.core.resource_types import RT_AGENT
from app.db.session import DbSession
from app.db.models.agents import (
    AgentIdentity,
    AgentInputType,
    AgentInstance,
    AgentInstanceStatus,
    AgentJob,
    AgentJobStatus,
    AgentRole,
    AgentType,
    ModelConfig,
)
from app.schemas.agents import (
    AgentIdentityCreate,
    AgentIdentityOAuthAuthorizeResponse,
    AgentIdentityRead,
    AgentIdentityUpdate,
    AgentInstanceRead,
    AgentJobCreate,
    AgentJobRead,
    AgentJobStatusRead,
    AgentRoleAssignment,
    AgentRoleCreate,
    AgentRoleIdentityAssignment,
    AgentRoleRead,
    AgentRoleUpdate,
    AgentTypeCreate,
    AgentTypeRead,
    AgentTypeUpdate,
    ExecutionLogEntryRead,
    ExecutionLogRead,
    ModelConfigCreate,
    ModelConfigRead,
    ModelConfigUpdate,
)
from app.services.agents.identity_service import (
    AgentIdentityConflictError,
    AgentIdentityNotFoundError,
    AgentIdentityService,
    AgentOAuthError,
)
from app.services.agents.instance_manager import AgentInstanceManager
from app.services.agents.model_config_service import (
    ModelConfigConflictError,
    ModelConfigNotFoundError,
    ModelConfigService,
)
from app.services.agents.role_service import (
    AgentRoleConflictError,
    AgentRoleNotFoundError,
    AgentRoleService,
)
from app.services.agents.session_service import AgentSessionService
from app.services.agents.permission_manager import AgentPermissionManager
from app.services.gateway.lifecycle_handler import AgentAuthError, GatewayLifecycleHandler

logger = logging.getLogger(__name__)

# Shared service singletons (stateless; safe for app-level reuse)
_role_service = AgentRoleService()
_identity_service = AgentIdentityService()
_session_service = AgentSessionService()
_permission_manager = AgentPermissionManager()
_model_config_service = ModelConfigService()
_lifecycle_handler = GatewayLifecycleHandler()

# Wire the permission manager into the role service so it can invalidate the cache
_role_service._permission_manager = _permission_manager

AgentRoleRouter = APIRouter(prefix="/agents/roles", tags=["Agents"])
AgentIdentityRouter = APIRouter(prefix="/agents/identities", tags=["Agents"])
AgentOAuthRouter = APIRouter(prefix="/agents", tags=["Agents"])
AgentJobRouter = APIRouter(prefix="/agents/sessions", tags=["Agents"])
AgentTypeRouter = APIRouter(prefix="/agents/types", tags=["Agents"])
AgentInstanceRouter = APIRouter(prefix="/agents/instances", tags=["Agents"])
ModelConfigRouter = APIRouter(prefix="/agents/model-configs", tags=["Agents"])


# ── Agent Role Endpoints ───────────────────────────────────────────────────────


@AgentRoleRouter.get("", response_model=list[AgentRoleRead])
async def list_agent_roles(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentRoleRead]:
    roles = await _role_service.list_roles(db)
    return [AgentRoleRead.model_validate(r) for r in roles]


@AgentRoleRouter.post("", response_model=AgentRoleRead, status_code=status.HTTP_201_CREATED)
async def create_agent_role(
    body: AgentRoleCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> AgentRoleRead:
    role = await _role_service.create_role(
        name=body.name,
        description=body.description,
        sop_ids=body.sop_ids,
        skill_ids=body.skill_ids,
        db=db,
    )
    return AgentRoleRead.model_validate(role)


@AgentRoleRouter.get("/{role_id}", response_model=AgentRoleRead)
async def get_agent_role(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentRoleRead:
    try:
        role = await _role_service.get_role(role_id, db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return AgentRoleRead.model_validate(role)


@AgentRoleRouter.put("/{role_id}", response_model=AgentRoleRead)
async def update_agent_role(
    role_id: uuid.UUID,
    body: AgentRoleUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentRoleRead:
    try:
        role = await _role_service.update_role(
            role_id=role_id,
            name=body.name,
            description=body.description,
            sop_ids=body.sop_ids,
            skill_ids=body.skill_ids,
            db=db,
        )
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return AgentRoleRead.model_validate(role)


@AgentRoleRouter.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_role(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> None:
    try:
        await _role_service.delete_role(role_id, db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AgentRoleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@AgentRoleRouter.get("/{role_id}/mcp-tools", response_model=list[str])
async def get_role_mcp_tools(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[str]:
    """Return the set of allowed MCP tool identifiers for a given role."""
    try:
        tools = await _permission_manager.calculate_allowed_tools(role_id, db)
    except Exception as exc:
        logger.warning("Permission manager failed for role %s: %s", role_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    return sorted(tools)


@AgentRoleRouter.post("/{role_id}/identities", status_code=status.HTTP_204_NO_CONTENT)
async def assign_identities_to_role(
    role_id: uuid.UUID,
    body: AgentRoleIdentityAssignment,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> None:
    """Bulk-assign identities to an agent role."""
    try:
        await _role_service.assign_identities(role_id=role_id, identity_ids=body.identity_ids, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentRoleRouter.delete("/{role_id}/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_identity_from_role(
    role_id: uuid.UUID,
    identity_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> None:
    """Remove a specific identity assignment from a role."""
    try:
        await _role_service.remove_identity(role_id=role_id, identity_id=identity_id, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentRoleRouter.get("/{role_id}/identities", response_model=list[AgentIdentityRead])
async def list_role_identities(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list:
    """List all identities assigned to a role."""
    try:
        return await _role_service.list_identities(role_id=role_id, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Agent Role MCP Session Endpoints ───────────────────────────────────────────


@AgentRoleRouter.post("/{role_id}/mcp-sessions", status_code=status.HTTP_204_NO_CONTENT)
async def assign_mcp_session_to_role(
    role_id: uuid.UUID,
    body: dict,  # {mcp_session_id: str}
    db: DbSession,
    request: Request,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> None:
    """Assign an MCP session to an agent role.
    
    Enforces one-session-per-server constraint.
    """
    try:
        session_id = uuid.UUID(body["mcp_session_id"])
        claims = get_current_claims(request)
        user_id_str: str | None = claims.get("platform_user_id")
        user_id = uuid.UUID(user_id_str) if user_id_str else None
        await _role_service.assign_mcp_session(
            role_id=role_id,
            mcp_session_id=session_id,
            assigned_by=user_id,
            db=db,
        )
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=400, detail="mcp_session_id required")


@AgentRoleRouter.delete("/{role_id}/mcp-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mcp_session_from_role(
    role_id: uuid.UUID,
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> None:
    """Remove an MCP session assignment from a role."""
    try:
        await _role_service.remove_mcp_session(role_id=role_id, mcp_session_id=session_id, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentRoleRouter.get("/{role_id}/mcp-sessions")
async def list_role_mcp_sessions(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[dict]:
    """List all MCP sessions assigned to a role."""
    try:
        return await _role_service.list_mcp_sessions(role_id=role_id, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentRoleRouter.get("/{role_id}/available-mcp-sessions")
async def list_available_mcp_sessions_for_role(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[dict]:
    """List MCP sessions available for assignment to a role.
    
    Filtered by servers whose tools are used by the role's SOPs/Skills.
    """
    try:
        return await _role_service.get_available_mcp_sessions(role_id=role_id, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Agent Identity Endpoints ───────────────────────────────────────────────────


@AgentIdentityRouter.get("", response_model=list[AgentIdentityRead])
async def list_agent_identities(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentIdentity]:
    return await _identity_service.list_identities(db)


@AgentIdentityRouter.post("", response_model=AgentIdentityRead, status_code=status.HTTP_201_CREATED)
async def create_agent_identity(
    body: AgentIdentityCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> AgentIdentity:
    return await _identity_service.create_identity(
        name=body.name,
        realm_name=body.realm_name,
        realm_username=body.realm_username,
        status=body.status,
        db=db,
    )


@AgentIdentityRouter.get("/{identity_id}", response_model=AgentIdentityRead)
async def get_agent_identity(
    identity_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentIdentity:
    try:
        return await _identity_service.get_identity(identity_id, db)
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentIdentityRouter.put("/{identity_id}", response_model=AgentIdentityRead)
async def update_agent_identity(
    identity_id: uuid.UUID,
    body: AgentIdentityUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentIdentity:
    try:
        return await _identity_service.update_identity(
            identity_id=identity_id,
            name=body.name,
            realm_name=body.realm_name,
            realm_username=body.realm_username,
            status=body.status,
            db=db,
        )
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentIdentityRouter.delete("/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_identity(
    identity_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> None:
    try:
        await _identity_service.delete_identity(identity_id, db)
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AgentIdentityConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@AgentIdentityRouter.post("/{identity_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
async def assign_roles_to_identity(
    identity_id: uuid.UUID,
    body: AgentRoleAssignment,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> None:
    """Bulk-assign roles to an agent identity."""
    try:
        await _identity_service.assign_roles(identity_id=identity_id, role_ids=body.role_ids, db=db)
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentIdentityRouter.delete("/{identity_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role_from_identity(
    identity_id: uuid.UUID,
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> None:
    """Remove a specific role assignment from an identity."""
    try:
        await _identity_service.remove_role(identity_id=identity_id, role_id=role_id, db=db)
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentIdentityRouter.get("/{identity_id}/roles", response_model=list[AgentRoleRead])
async def list_identity_roles(
    identity_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list:
    """List all roles assigned to an identity."""
    try:
        return await _identity_service.list_roles(identity_id=identity_id, db=db)
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@AgentIdentityRouter.post("/{identity_id}/refresh-token", response_model=AgentIdentityRead)
async def refresh_identity_token(
    identity_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentIdentity:
    """Refresh the access token for an agent identity using its stored refresh token."""
    try:
        return await _identity_service.refresh_token(identity_id=identity_id, db=db)
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except AgentOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@AgentIdentityRouter.get("/{identity_id}/reauth-url")
async def get_reauth_url(
    identity_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> dict:
    """Get an OAuth re-authentication URL for an expired identity."""
    try:
        url = await _identity_service.get_reauth_url(
            identity_id=identity_id, request=request, db=db
        )
        return {"authorization_url": url}
    except AgentIdentityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Agent Session (Job) Endpoints ──────────────────────────────────────────────


@AgentJobRouter.post("", response_model=AgentJobStatusRead, status_code=status.HTTP_202_ACCEPTED)
async def launch_agent_session(
    body: AgentJobCreate,
    db: DbSession,
    request: Request,
    _: dict = Depends(require_permission(RT_AGENT, "execute")),
) -> AgentJob:
    """Validate agent identity OAuth token, enqueue a new agent session, and return 202 with session ID."""
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    try:
        result = await _lifecycle_handler.launch(
            agent_type_id=body.agent_type_id,
            input_data=body.input_data,
            user_id=user_id,
            db=db,
        )
    except AgentAuthError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    session_id = uuid.UUID(result["session_id"])
    job = await db.get(AgentJob, session_id)
    return job


@AgentJobRouter.get("", response_model=list[AgentJobStatusRead])
async def list_agent_sessions(
    db: DbSession,
    request: Request,
    status: Optional[AgentJobStatus] = Query(None, description="Filter by session status"),
    from_date: Optional[str] = Query(None, alias="from_date", description="ISO 8601 datetime lower bound"),
    to_date: Optional[str] = Query(None, alias="to_date", description="ISO 8601 datetime upper bound"),
    agent_type_id: Optional[uuid.UUID] = Query(None, description="Filter by agent type"),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentJob]:
    """List sessions triggered by the current user with optional filters."""
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    # Parse optional date bounds
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    try:
        if from_date:
            from_dt = datetime.fromisoformat(from_date)
        if to_date:
            to_dt = datetime.fromisoformat(to_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    return await _session_service.list_sessions(
        user_id=user_id,
        status=status,
        from_date=from_dt,
        to_date=to_dt,
        agent_type_id=agent_type_id,
        db=db,
    )


@AgentJobRouter.get("/{session_id}", response_model=AgentJobStatusRead)
async def get_agent_session_status(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentJob:
    """Get current status of an agent session."""
    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")
    return job


@AgentJobRouter.get("/{session_id}/result", response_model=AgentJobRead)
async def get_agent_session_result(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentJob:
    """Get full session result. Returns 409 if session is not yet completed."""
    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")
    if job.status not in (AgentJobStatus.completed, AgentJobStatus.failed):
        raise HTTPException(
            status_code=409,
            detail=f"Session is not yet complete (status={job.status})",
        )
    return job


@AgentJobRouter.get("/{session_id}/history", response_model=list[dict])
async def get_agent_session_history(
    session_id: uuid.UUID,
    db: DbSession,
    request: Request,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[dict]:
    """Return the conversation history for a session.

    Returns an empty list for task-type sessions.  Returns 404 if the session
    does not exist.  Returns 403 if the session is not owned by the current user.
    """
    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    # Ownership check
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    if user_id_str and job.triggered_by_user_id:
        if str(job.triggered_by_user_id) != user_id_str:
            raise HTTPException(status_code=403, detail="Access denied")

    return job.conversation_history or []


@AgentJobRouter.get("/{session_id}/logs", response_model=list[ExecutionLogEntryRead])
async def get_session_execution_logs(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list:
    """Retrieve execution log entries for a session in chronological order."""
    from app.db.models.session_logs import ExecutionLogEntry

    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == session_id)
        .order_by(ExecutionLogEntry.timestamp)
    )
    entries = result.scalars().all()
    return [ExecutionLogEntryRead.model_validate(e) for e in entries]


@AgentJobRouter.get("/{session_id}/execution-logs", response_model=list[ExecutionLogRead])
async def get_session_prompt_logs(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list:
    """Return the system instruction and user prompt captured before the first LLM call.

    Returns 404 if the session does not exist.
    Returns an empty list if no prompt log has been captured yet (e.g. session is still queued).
    """
    from app.db.models.agents import AgentPromptLog

    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(AgentPromptLog)
        .where(AgentPromptLog.session_id == session_id)
        .order_by(AgentPromptLog.logged_at)
    )
    entries = result.scalars().all()
    return [ExecutionLogRead.model_validate(e) for e in entries]


@AgentJobRouter.websocket("/{session_id}/chat")
async def agent_session_chat(
    session_id: uuid.UUID,
    websocket: WebSocket,
    db: DbSession,
) -> None:
    """WebSocket endpoint for conversational agent sessions."""
    await websocket.accept()
    try:
        job = await _session_service.get_session(session_id, db)
        if not job:
            await websocket.close(code=4004, reason="Session not found")
            return

        # Route messages through the session service chat handler
        await _session_service.handle_chat_websocket(session_id, websocket, db)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception as exc:
        logger.error("WebSocket error for session %s: %s", session_id, exc)
        await websocket.close(code=1011)


# ── Agent Type Endpoints ───────────────────────────────────────────────────────

@AgentTypeRouter.get("", response_model=list[AgentTypeRead])
async def list_agent_types(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentType]:
    result = await db.execute(select(AgentType).order_by(AgentType.name))
    return list(result.scalars().all())


@AgentTypeRouter.post("", response_model=AgentTypeRead, status_code=status.HTTP_201_CREATED)
async def create_agent_type(
    body: AgentTypeCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> AgentType:
    if body.input_type == AgentInputType.none:
        if not body.primary_sop_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent types with no input must specify a primary_sop_id",
            )
    agent_type = AgentType(
        name=body.name,
        description=body.description,
        identity_id=body.identity_id,
        role_id=body.role_id,
        model_id=body.model_id,
        system_instruction=body.system_instruction,
        input_type=body.input_type,
        input_schema=body.input_schema,
        output_type=body.output_type,
        output_schema=body.output_schema,
        primary_sop_id=body.primary_sop_id,
    )
    db.add(agent_type)
    await db.flush()
    await db.refresh(agent_type)
    return agent_type


@AgentTypeRouter.get("/{type_id}", response_model=AgentTypeRead)
async def get_agent_type(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentType:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")
    return agent_type


@AgentTypeRouter.put("/{type_id}", response_model=AgentTypeRead)
async def update_agent_type(
    type_id: uuid.UUID,
    body: AgentTypeUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentType:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")

    update_data = body.model_dump(exclude_unset=True)

    # Determine effective input_type and role_id after applying the update
    effective_input_type = update_data.get("input_type", agent_type.input_type)
    effective_role_id = update_data.get("role_id", agent_type.role_id)

    if effective_input_type == AgentInputType.none:
        effective_primary_sop_id = update_data.get("primary_sop_id", agent_type.primary_sop_id)
        if not effective_primary_sop_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent types with no input must specify a primary_sop_id",
            )

    for field, value in update_data.items():
        setattr(agent_type, field, value)

    await db.flush()
    await db.refresh(agent_type)
    return agent_type


@AgentTypeRouter.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_type(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> None:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")
    await db.delete(agent_type)


@AgentTypeRouter.get("/{type_id}/instances", response_model=list[AgentInstanceRead])
async def list_agent_instances(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentInstance]:
    result = await db.execute(
        select(AgentInstance)
        .where(AgentInstance.agent_type_id == type_id)
        .order_by(AgentInstance.created_at.desc())
    )
    return list(result.scalars().all())


# ── Agent Instance Endpoints ───────────────────────────────────────────────────

@AgentInstanceRouter.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def terminate_agent_instance(
    instance_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "execute")),
) -> None:
    manager = AgentInstanceManager()
    try:
        await manager.close(instance_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Agent OAuth Endpoints ──────────────────────────────────────────────────────


@AgentOAuthRouter.get(
    "/identities/oauth/authorize",
    response_model=AgentIdentityOAuthAuthorizeResponse,
)
async def agent_oauth_authorize(
    request: Request,
    identity_id: uuid.UUID | None = None,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentIdentityOAuthAuthorizeResponse:
    """Return the OAuth authorization URL for signing in as an agent user.

    If identity_id is provided, embeds it in the OAuth `state` for token refresh.
    If identity_id is None, the callback will auto-create a new AgentIdentity
    after successful authentication based on the agent user's realm and username.
    """
    # Determine frontend origin from request headers (for dev/prod flexibility)
    # Origin header is reliably sent in CORS requests from the browser
    origin = request.headers.get("origin")
    if not origin:
        # Fallback: extract from referer if origin not present
        referer = request.headers.get("referer", "")
        if referer:
            # Parse origin from referer (e.g., "http://localhost:5173/agents" -> "http://localhost:5173")
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
    if not origin or not origin.startswith("http"):
        origin = "http://localhost:5173"  # Default to Vite dev server
    
    # Build redirect_uri pointing at the frontend callback page (not the API endpoint)
    redirect_uri = f"{origin}/agents/identities/oauth/callback"
    logger.info("[AUTHORIZE] origin=%s, redirect_uri=%s", origin, redirect_uri)
    
    # Use identity_id as state if provided, else use "new" to signal creation
    state_value = str(identity_id) if identity_id else "new"
    authorization_url = _identity_service.get_oauth_authorize_url(state_value, redirect_uri)
    return AgentIdentityOAuthAuthorizeResponse(authorization_url=authorization_url)


@AgentOAuthRouter.get("/identities/oauth/callback", response_model=AgentIdentityRead)
async def agent_oauth_callback(
    code: str,
    state: str,
    request: Request,
    db: DbSession,
) -> AgentIdentity:
    """Handle the OAuth callback from the frontend page.

    The frontend AgentOAuthCallbackPage receives the redirect from Keycloak,
    then calls this API endpoint to exchange the code for tokens.

    The redirect_uri must match what was used in the authorize step, which is
    the frontend callback page URL (not this API endpoint).

    This endpoint is public (no auth required) because the frontend callback page
    doesn't have the user's bearer token in the popup window context.

    TODO: Implement proper state validation by storing signed state tokens in Redis
    with user session context, then validating them here.

    If state is a UUID, updates that existing AgentIdentity's tokens.
    If state is "new", creates a new AgentIdentity after fetching user info.
    """
    # Reconstruct redirect_uri using the same logic as authorize step
    # Origin header is reliably sent in CORS requests from the browser
    origin = request.headers.get("origin")
    if not origin:
        # Fallback: extract from referer if origin not present
        referer = request.headers.get("referer", "")
        logger.info("[CALLBACK] referer=%s", referer)
        if referer:
            # Parse origin from referer
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}"
    if not origin or not origin.startswith("http"):
        origin = "http://localhost:5173"  # Default to Vite dev server
    
    # Build redirect_uri the same way as authorize step
    redirect_uri = f"{origin}/agents/identities/oauth/callback"
    logger.info("[CALLBACK] origin=%s, redirect_uri=%s", origin, redirect_uri)
    
    if state == "new":
        # Auto-create flow: exchange code, get user info, create identity
        try:
            identity = await _identity_service.create_identity_from_oauth(
                code=code,
                redirect_uri=redirect_uri,
                db=db,
            )
        except AgentOAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return identity
    else:
        # Refresh flow: update existing identity's tokens
        try:
            identity_id = uuid.UUID(state)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid state parameter — expected identity UUID or 'new'")

        try:
            identity = await _identity_service.complete_oauth_flow(
                identity_id=identity_id,
                code=code,
                redirect_uri=redirect_uri,
                db=db,
            )
        except AgentIdentityNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except AgentOAuthError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return identity


# ── ModelConfig Endpoints ──────────────────────────────────────────────────────


@ModelConfigRouter.get("", response_model=list[ModelConfigRead])
async def list_model_configs(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[ModelConfigRead]:
    configs = await _model_config_service.list_model_configs(db)
    return [ModelConfigRead.model_validate(c) for c in configs]


@ModelConfigRouter.post("", response_model=ModelConfigRead, status_code=status.HTTP_201_CREATED)
async def create_model_config(
    body: ModelConfigCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> ModelConfigRead:
    config = await _model_config_service.create_model_config(
        display_name=body.display_name,
        provider_type=body.provider_type,
        api_base_url=body.api_base_url,
        api_key=body.api_key,
        enabled_models=body.enabled_models,
        db=db,
    )
    return ModelConfigRead.model_validate(config)


@ModelConfigRouter.get("/{config_id}", response_model=ModelConfigRead)
async def get_model_config(
    config_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> ModelConfigRead:
    try:
        config = await _model_config_service.get_model_config(config_id, db)
    except ModelConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ModelConfigRead.model_validate(config)


@ModelConfigRouter.put("/{config_id}", response_model=ModelConfigRead)
async def update_model_config(
    config_id: uuid.UUID,
    body: ModelConfigUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> ModelConfigRead:
    try:
        config = await _model_config_service.update_model_config(
            config_id,
            display_name=body.display_name,
            provider_type=body.provider_type,
            api_base_url=body.api_base_url,
            api_key=body.api_key,
            enabled_models=body.enabled_models,
            db=db,
        )
    except ModelConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ModelConfigRead.model_validate(config)


@ModelConfigRouter.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_config(
    config_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> None:
    try:
        await _model_config_service.delete_model_config(config_id, db)
    except ModelConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ModelConfigConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@ModelConfigRouter.get("/{config_id}/models", response_model=list[str])
async def list_models_for_config(
    config_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[str]:
    """Return the available model names for this config by querying the live provider API.

    Always queries the provider to get the full list of available models,
    regardless of what's currently in enabled_models. This allows users to
    update their model selection when clicking 'Fetch Models' in the UI.
    """
    try:
        return await _model_config_service.list_models_for_config(config_id, db)
    except ModelConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

