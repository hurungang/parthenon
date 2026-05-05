"""Agent management API routers: AgentRole, AgentIdentity, AgentJob, AgentType, AgentInstance."""
import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.api.deps import require_permission, get_current_claims
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_AGENT
from app.db.session import DbSession
from app.db.models.agents import (
    AgentIdentity,
    AgentInstance,
    AgentInstanceStatus,
    AgentJob,
    AgentJobStatus,
    AgentRole,
    AgentType,
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
    AgentRoleCreate,
    AgentRoleRead,
    AgentRoleUpdate,
    AgentTypeCreate,
    AgentTypeRead,
    AgentTypeUpdate,
)
from app.services.agents.identity_service import (
    AgentIdentityConflictError,
    AgentIdentityNotFoundError,
    AgentIdentityService,
    AgentOAuthError,
)
from app.services.agents.instance_manager import AgentInstanceManager
from app.services.agents.role_service import (
    AgentRoleConflictError,
    AgentRoleNotFoundError,
    AgentRoleService,
)
from app.services.agents.session_service import AgentSessionService
from app.services.agents.permission_manager import AgentPermissionManager

logger = logging.getLogger(__name__)

# Shared service singletons (stateless; safe for app-level reuse)
_role_service = AgentRoleService()
_identity_service = AgentIdentityService()
_session_service = AgentSessionService()
_permission_manager = AgentPermissionManager()

# Wire the permission manager into the role service so it can invalidate the cache
_role_service._permission_manager = _permission_manager

AgentRoleRouter = APIRouter(prefix="/agents/roles", tags=["Agents"])
AgentIdentityRouter = APIRouter(prefix="/agents/identities", tags=["Agents"])
AgentOAuthRouter = APIRouter(prefix="/agents", tags=["Agents"])
AgentJobRouter = APIRouter(prefix="/agents/sessions", tags=["Agents"])
AgentTypeRouter = APIRouter(prefix="/agents/types", tags=["Agents"])
AgentInstanceRouter = APIRouter(prefix="/agents/instances", tags=["Agents"])


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


# ── Agent Session (Job) Endpoints ──────────────────────────────────────────────


@AgentJobRouter.post("", response_model=AgentJobStatusRead, status_code=status.HTTP_202_ACCEPTED)
async def launch_agent_session(
    body: AgentJobCreate,
    db: DbSession,
    request: Request,
    _: dict = Depends(require_permission(RT_AGENT, "execute")),
) -> AgentJob:
    """Enqueue a new agent session. Returns 202 with session ID immediately."""
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    job = await _session_service.enqueue(
        agent_type_id=body.agent_type_id,
        input_data=body.input_data,
        user_id=user_id,
        db=db,
    )
    return job


@AgentJobRouter.get("", response_model=list[AgentJobStatusRead])
async def list_agent_sessions(
    db: DbSession,
    request: Request,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentJob]:
    """List sessions triggered by the current user."""
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    return await _session_service.list_sessions(user_id=user_id, db=db)


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
    encrypted_creds = None
    if body.llm_api_key:
        vault = get_vault()
        encrypted_creds = vault.encrypt(json.dumps({"api_key": body.llm_api_key}))

    agent_type = AgentType(
        name=body.name,
        description=body.description,
        identity_id=body.identity_id,
        role_id=body.role_id,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        encrypted_llm_credentials=encrypted_creds,
        system_instruction=body.system_instruction,
        input_type=body.input_type,
        input_schema=body.input_schema,
        output_type=body.output_type,
        output_schema=body.output_schema,
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

    update_data = body.model_dump(exclude_unset=True, exclude={"llm_api_key"})
    for field, value in update_data.items():
        setattr(agent_type, field, value)

    if body.llm_api_key is not None:
        vault = get_vault()
        agent_type.encrypted_llm_credentials = vault.encrypt(
            json.dumps({"api_key": body.llm_api_key})
        )

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

