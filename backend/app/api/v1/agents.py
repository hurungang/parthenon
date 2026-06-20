"""Agent management API routers: AgentRole, AgentIdentity, AgentJob, AgentType, AgentInstance, ModelConfig."""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_claims, require_permission
from app.core.resource_types import RT_AGENT
from app.db.models.agents import (
    AgentIdentity,
    AgentInstance,
    AgentJob,
    AgentJobStatus,
    AgentType,
    AgentTypeSkillBinding,
    AgentTypeSopBinding,
)
from app.db.models.sop_recursion_validation_check import SopRecursionCheckContext
from app.db.session import DbSession
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
    ModelAvailabilityUpdate,
    ModelAvailabilityVendorRead,
    ModelConfigCreate,
    ModelConfigRead,
    ModelConfigUpdate,
    ModelUsageGuardrailLimitCreate,
    ModelUsageGuardrailLimitRead,
    ModelUsageGuardrailLimitUpdate,
    ModelUsagePostureRead,
    PreflightAvailabilityRequest,
    PreflightAvailabilityResponse,
    RuntimeTerminalJobPurgeRead,
    RuntimeTerminateRequest,
    RuntimeTopologyEdgeRead,
    RuntimeTopologyNodeRead,
    RuntimeTopologyRead,
    TerminationCascadeOutcomeRead,
    TerminationRequestRead,
    VendorDisabledUpdate,
    WorkflowGenerationModelConfigRead,
    WorkflowGenerationModelConfigUpdate,
    WorkflowGenerationModelOption,
)
from app.services.agents.agent_type_service import AgentTypeService
from app.services.agents.binding_validation import validate_bindings
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
from app.services.agents.permission_manager import get_shared_permission_manager
from app.services.agents.plan_generation_service import PlanGenerationService
from app.services.agents.role_service import (
    AgentRoleConflictError,
    AgentRoleNotFoundError,
    AgentRoleService,
)
from app.services.agents.session_service import AgentSessionService
from app.services.agents.tool_naming import build_tool_name, is_system_tool
from app.services.agents.workflow_generation_settings import (
    get_workflow_generation_model_id,
    set_workflow_generation_model_id,
)
from app.services.control_center.model_availability_service import (
    ModelAvailabilityService,
)
from app.services.control_center.model_usage_guardrail_service import (
    ModelGuardrailDuplicatePeriodError,
    ModelGuardrailModelNotFoundError,
    ModelUsageGuardrailService,
)
from app.services.control_center.recursion_validation_service import (
    RecursionValidationError,
    get_recursion_validation_service,
)
from app.services.control_center.runtime_topology_controller import RuntimeTopologyController
from app.services.control_center.termination_orchestrator import (
    TerminationDeniedError,
    TerminationOrchestrator,
)
from app.services.gateway.lifecycle_handler import AgentAuthError, GatewayLifecycleHandler

logger = logging.getLogger(__name__)

# Shared service singletons (stateless; safe for app-level reuse)
_role_service = AgentRoleService()
_identity_service = AgentIdentityService()
_session_service = AgentSessionService()
_permission_manager = get_shared_permission_manager()
_model_config_service = ModelConfigService()
_model_usage_guardrail_service = ModelUsageGuardrailService()
_model_availability_service = ModelAvailabilityService()
_runtime_topology_controller = RuntimeTopologyController()
_termination_orchestrator = TerminationOrchestrator()
_lifecycle_handler = GatewayLifecycleHandler()
_plan_generation_service = PlanGenerationService()
_agent_type_service = AgentTypeService()

# Wire the permission manager into the role service so it can invalidate the cache
_role_service._permission_manager = _permission_manager

AgentRoleRouter = APIRouter(prefix="/agents/roles", tags=["Agents"])
AgentIdentityRouter = APIRouter(prefix="/agents/identities", tags=["Agents"])
AgentOAuthRouter = APIRouter(prefix="/agents", tags=["Agents"])
AgentJobRouter = APIRouter(prefix="/agents/sessions", tags=["Agents"])
AgentTypeRouter = APIRouter(prefix="/agents/types", tags=["Agents"])
AgentInstanceRouter = APIRouter(prefix="/agents/instances", tags=["Agents"])
ModelConfigRouter = APIRouter(prefix="/agents/model-configs", tags=["Agents"])
ModelUsageGuardrailRouter = APIRouter(prefix="/agents/guardrails", tags=["Agents"])
ModelAvailabilityRouter = APIRouter(prefix="/agents", tags=["Agents"])
RuntimeControlRouter = APIRouter(prefix="/agents/runtime", tags=["Agents"])


# ── Agent Role Endpoints ───────────────────────────────────────────────────────


@AgentRoleRouter.get("", response_model=list[AgentRoleRead])
async def list_agent_roles(
    db: DbSession,
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentRoleRead]:
    roles = await _role_service.list_roles(db, limit=limit, offset=offset)
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
    skill_ids: str | None = None,  # Comma-separated UUIDs for preview
    sop_ids: str | None = None,     # Comma-separated UUIDs for preview
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[str]:
    """Return the set of allowed MCP tool identifiers for a given role.
    
    Query Parameters:
        skill_ids: Optional comma-separated list of skill UUIDs to preview (for unsaved changes)
        sop_ids: Optional comma-separated list of SOP UUIDs to preview (for unsaved changes)
    
    If both skill_ids and sop_ids are provided, the endpoint returns a preview
    without reading from the database. Otherwise, it reads the saved role configuration.
    """
    try:
        override_skill_ids: set[uuid.UUID] | None = None
        override_sop_ids: set[uuid.UUID] | None = None

        # Parse query parameters for preview mode
        if skill_ids is not None and sop_ids is not None:
            override_skill_ids = {uuid.UUID(s.strip()) for s in skill_ids.split(",") if s.strip()}
            override_sop_ids = {uuid.UUID(s.strip()) for s in sop_ids.split(",") if s.strip()}

        tools = await _permission_manager.calculate_allowed_tools(role_id, db, override_skill_ids, override_sop_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID format: {exc}")
    except Exception as exc:
        logger.warning("Permission manager failed for role %s: %s", role_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    canonical_tools = [build_tool_name("system", tool) if is_system_tool(tool) and "____" not in tool else tool for tool in tools]
    return sorted(canonical_tools)


@AgentRoleRouter.get("/{role_id}/allowed-agent-types", response_model=list[str])
async def get_role_allowed_agent_types(
    role_id: uuid.UUID,
    db: DbSession,
    sop_ids: str | None = None,  # Comma-separated UUIDs for preview
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[str]:
    """Return delegated agent type slugs allowed for a role.

    The permission set is derived from SOP steps with ``step_type=agent_delegation``.
    If ``sop_ids`` is provided, the response is a preview for unsaved SOP selections.
    """
    try:
        override_sop_ids: set[uuid.UUID] | None = None
        if sop_ids is not None:
            override_sop_ids = {uuid.UUID(s.strip()) for s in sop_ids.split(",") if s.strip()}

        allowed_agent_types = await _permission_manager.calculate_allowed_agent_types(
            role_id,
            db,
            override_sop_ids=override_sop_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID format: {exc}")
    except Exception as exc:
        logger.warning("Allowed agent type resolution failed for role %s: %s", role_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))

    return sorted(allowed_agent_types)


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


@AgentRoleRouter.get("/{role_id}/mcp-session-coverage")
async def get_mcp_session_coverage(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> dict:
    """Check whether all MCP servers required by a role's skills have sessions assigned.
    
    Returns { covered: bool, missing_servers: [{slug, name}] }.
    When covered is false, the agent will fail at runtime with 502 errors.
    """
    try:
        return await _role_service.validate_mcp_session_coverage(role_id=role_id, db=db)
    except AgentRoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Agent Identity Endpoints ───────────────────────────────────────────────────


@AgentIdentityRouter.get("", response_model=list[AgentIdentityRead])
async def list_agent_identities(
    db: DbSession,
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentIdentity]:
    return await _identity_service.list_identities(db, limit=limit, offset=offset)


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
        logger.warning("Agent identity not found for deletion: %s", identity_id)
        raise HTTPException(status_code=404, detail=str(exc))
    except AgentIdentityConflictError as exc:
        logger.error(
            "Cannot delete agent identity %s: %s",
            identity_id,
            str(exc),
        )
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
        result = await _identity_service.refresh_token(identity_id=identity_id, db=db)
        logger.info(
            "Successfully refreshed token for identity %s (name: %s)",
            identity_id,
            result.name,
        )
        return result
    except AgentIdentityNotFoundError as exc:
        logger.warning("Agent identity not found for token refresh: %s", identity_id)
        raise HTTPException(status_code=404, detail=str(exc))
    except AgentOAuthError as exc:
        logger.error(
            "Token refresh failed for identity %s: %s",
            identity_id,
            str(exc),
        )
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

    # Recursion pre-flight validation before launching
    try:
        await get_recursion_validation_service().validate_agent_type(
            agent_type_id=body.agent_type_id,
            context=SopRecursionCheckContext.run,
            db=db,
            checked_by_user_id=user_id,
        )
    except RecursionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "recursion_validation_failed",
                "summary": exc.summary,
                "findings": [
                    {
                        "type": f.finding_type.value,
                        "severity": f.severity.value,
                        "path": f.path_signature,
                        "recommendation": f.recommendation,
                    }
                    for f in exc.findings
                ],
            },
        )

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
    job = await _session_service.get_session(session_id, db)
    return job


@AgentJobRouter.get("", response_model=list[AgentJobStatusRead])
async def list_agent_sessions(
    db: DbSession,
    request: Request,
    status: AgentJobStatus | None = Query(None, description="Filter by session status"),
    from_date: str | None = Query(None, alias="from_date", description="ISO 8601 datetime lower bound"),
    to_date: str | None = Query(None, alias="to_date", description="ISO 8601 datetime upper bound"),
    agent_type_id: uuid.UUID | None = Query(None, description="Filter by agent type"),
    limit: int = Query(50, description="Max number of sessions to return"),
    offset: int = Query(0, description="Number of sessions to skip"),
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
        limit=limit,
        offset=offset,
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
    if job.status not in (
        AgentJobStatus.completed,
        AgentJobStatus.failed,
        AgentJobStatus.terminated,
    ):
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


@AgentJobRouter.get("/{session_id}/logs/stream")
async def stream_session_execution_logs(
    session_id: uuid.UUID,
    db: DbSession,
    poll_ms: int = Query(1000, ge=250, le=5000),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> StreamingResponse:
    """Stream append-only execution log entries for a session while it is active.

    Emits NDJSON events in timestamp order:
    - {"type":"log_entry","entry":{...}}
    - {"type":"human_intervene","request_id":"...","reason":"...","intervention_type":"...","choices":[...]}
    - {"type":"stream_completed","session_id":"...","session_status":"completed|failed"}

    When the client disconnects, the inner generator catches
    ``asyncio.CancelledError`` / ``GeneratorExit`` so the DB session
    can be returned to the pool without a ``CancelledError`` during
    connection teardown.
    """
    from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
    from app.db.models.session_logs import ExecutionLogEntry

    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    async def stream_events():
        sent_ids: set[uuid.UUID] = set()
        sent_intervene: bool = False
        sent_propagate_ids: set[uuid.UUID] = set()

        try:
            while True:
                result = await db.execute(
                    select(ExecutionLogEntry)
                    .where(ExecutionLogEntry.session_id == session_id)
                    .order_by(ExecutionLogEntry.timestamp, ExecutionLogEntry.id)
                )
                entries = result.scalars().all()

                for entry in entries:
                    if entry.id in sent_ids:
                        continue
                    sent_ids.add(entry.id)
                    payload = {
                        "type": "log_entry",
                        "entry": ExecutionLogEntryRead.model_validate(entry).model_dump(mode="json"),
                    }
                    yield json.dumps(payload) + "\n"

                current_job = await _session_service.get_session(session_id, db)
                if not current_job:
                    terminal_payload = {
                        "type": "stream_completed",
                        "session_id": str(session_id),
                        "session_status": "failed",
                    }
                    yield json.dumps(terminal_payload) + "\n"
                    break

                if current_job.status in (
                    AgentJobStatus.completed,
                    AgentJobStatus.failed,
                    AgentJobStatus.terminated,
                ):
                    terminal_payload = {
                        "type": "stream_completed",
                        "session_id": str(session_id),
                        "session_status": current_job.status.value,
                    }
                    yield json.dumps(terminal_payload) + "\n"
                    break

                # Reset sent_intervene when the session leaves waiting_for_human so
                # subsequent delegations in the same session can re-trigger the event.
                if (
                    sent_intervene
                    and current_job.status != AgentJobStatus.waiting_for_human
                ):
                    sent_intervene = False

                if not sent_intervene:
                    # Emit a dedicated human_intervene event when:
                    # 1. The session has a pending InterveneRequest (direct intervention), OR
                    # 2. A human_intervene execution log entry was created (propagated from
                    #    a delegated child session via system_tools.py)
                    stmt = (
                        select(InterveneRequest)
                        .where(
                            InterveneRequest.agent_session_id == session_id,
                            InterveneRequest.status == InterveneRequestStatus.pending,
                        )
                        .limit(1)
                    )
                    intervene_result = await db.execute(stmt)
                    intervene_req = intervene_result.scalar_one_or_none()

                    if intervene_req:
                        sent_intervene = True
                        intervene_payload = {
                            "type": "human_intervene",
                            "request_id": str(intervene_req.id),
                            "session_id": str(session_id),
                            "reason": intervene_req.reason,
                            "intervention_type": intervene_req.intervention_type.value,
                            "choices": intervene_req.choices,
                        }
                        yield json.dumps(intervene_payload) + "\n"
                    else:
                        # Check for propagated human_intervene log entries
                        # that have not already been sent. The old .limit(1)
                        # always returned the oldest entry, so a second
                        # delegation's intervention was never picked up.
                        propagate_filters = [
                            ExecutionLogEntry.session_id == session_id,
                            ExecutionLogEntry.event_type == "human_intervene",
                        ]
                        if sent_propagate_ids:
                            propagate_filters.append(
                                ~ExecutionLogEntry.id.in_(list(sent_propagate_ids))
                            )
                        propagate_stmt = (
                            select(ExecutionLogEntry)
                            .where(*propagate_filters)
                            .order_by(ExecutionLogEntry.timestamp)
                            .limit(1)
                        )
                        log_result = await db.execute(propagate_stmt)
                        propagate_entry = log_result.scalar_one_or_none()
                        if propagate_entry:
                            sent_intervene = True
                            sent_propagate_ids.add(propagate_entry.id)
                            entry_data = propagate_entry.data or {}
                            intervene_payload = {
                                "type": "human_intervene",
                                "request_id": entry_data.get("request_id", ""),
                                "session_id": str(session_id),
                                "reason": propagate_entry.message,
                                "intervention_type": entry_data.get(
                                    "intervention_type", "general"
                                ),
                                "choices": None,
                            }
                            yield json.dumps(intervene_payload) + "\n"

                await asyncio.sleep(poll_ms / 1000)

        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected — exit the stream loop gracefully.
            # Starlette cancels the task when the response is closed, and
            # without this guard the CancelledError propagates to the DB
            # connection teardown, causing the pool error seen in logs.
            logger.info(
                "Stream cancelled for session %s (client disconnected)",
                session_id,
            )

    return StreamingResponse(stream_events(), media_type="application/x-ndjson")


# ── Phase 3.2: Delegation & Intervention Status Endpoints ─────────────────────


class PendingInterventionResponse(BaseModel):
    """Pending intervention request for a non-conversational agent session."""

    request_id: uuid.UUID
    intervention_type: str
    reason: str
    choices: list[str] | None = None
    sub_agent_session_id: uuid.UUID
    sub_agent_type_slug: str
    created_at: datetime
    delegation_depth: int = 0


class DelegationStatusResponse(BaseModel):
    """Current delegation status for a task agent session."""

    has_active_delegation: bool = False
    current_depth: int = 0
    max_depth: int = 1
    active_sub_agent_slug: str | None = None
    recent_events: list[dict] = Field(default_factory=list)


@AgentJobRouter.get(
    "/{session_id}/interventions/pending",
    response_model=PendingInterventionResponse | None,
)
async def get_pending_intervention(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> PendingInterventionResponse | None:
    """Return the currently pending intervention request for a task agent session.

    Non-conversational (task) agent interventions are created when a delegated
    sub-agent calls ``human_intervene``. This endpoint queries child sessions
    (via ``AgentJob.parent_job_id``) for pending intervene requests so the
    execution log viewer can re-surface outstanding intervention dialogs on
    reconnect.

    Returns 404 if the session does not exist.
    Returns the pending intervention details, or ``null`` if none is pending.
    """
    from app.db.models.intervene import InterveneRequest, InterveneRequestStatus

    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    # Find child sessions that have pending intervene requests.
    # A child session is an AgentJob whose parent_job_id == our session_id.
    child_jobs_result = await db.execute(
        select(AgentJob.id).where(
            AgentJob.parent_job_id == session_id,
        )
    )
    child_job_ids = [row[0] for row in child_jobs_result.fetchall()]
    if not child_job_ids:
        return None

    # Query pending intervene requests for any child session.
    result = await db.execute(
        select(InterveneRequest)
        .options(selectinload(InterveneRequest.agent_session).selectinload(AgentJob.agent_type))
        .where(
            InterveneRequest.agent_session_id.in_(child_job_ids),
            InterveneRequest.status == InterveneRequestStatus.pending,
        )
        .order_by(InterveneRequest.created_at.desc())
        .limit(1)
    )
    intervene_req = result.scalar_one_or_none()
    if intervene_req is None:
        return None

    sub_agent_type_slug = ""
    if intervene_req.agent_session and intervene_req.agent_session.agent_type:
        sub_agent_type_slug = intervene_req.agent_session.agent_type.name  # type: ignore[union-attr]

    return PendingInterventionResponse(
        request_id=intervene_req.id,
        intervention_type=intervene_req.intervention_type.value,
        reason=intervene_req.reason,
        choices=intervene_req.choices,
        sub_agent_session_id=intervene_req.agent_session_id,
        sub_agent_type_slug=sub_agent_type_slug,
        created_at=intervene_req.created_at,
        delegation_depth=intervene_req.delegation_depth,
    )


@AgentJobRouter.get(
    "/{session_id}/delegation/status",
    response_model=DelegationStatusResponse,
)
async def get_delegation_status(
    session_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> DelegationStatusResponse:
    """Return the current delegation status for a task agent session.

    Queries recent delegation-related ``ExecutionLogEntry`` entries for the
    session and checks child ``AgentJob`` records to determine current
    delegation depth and active sub-agent.

    Used by the execution log viewer to render the delegation status timeline
    on initial load.

    Returns 404 if the session does not exist.
    """
    from app.db.models.session_logs import ExecutionLogEntry

    job = await _session_service.get_session(session_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Session not found")

    # Query recent delegation-related log entries
    delegation_event_types = [
        "delegation_started",
        "delegation_waiting",
        "delegation_resumed",
        "delegation_depth_blocked",
        "delegation_timeout",
        "delegation_failed",
    ]

    entries_result = await db.execute(
        select(ExecutionLogEntry)
        .where(
            ExecutionLogEntry.session_id == session_id,
            ExecutionLogEntry.event_type.in_(delegation_event_types),
        )
        .order_by(ExecutionLogEntry.timestamp.desc())
        .limit(20)
    )
    recent_entries = entries_result.scalars().all()

    # Determine current depth and active sub-agent from the most recent
    # delegation_started / delegation_resumed sequence.
    current_depth = 0
    active_sub_agent: str | None = None
    has_active_delegation = False

    # Check child sessions to see if any are still running
    child_result = await db.execute(
        select(AgentJob).where(
            AgentJob.parent_job_id == session_id,
            AgentJob.status == AgentJobStatus.running,
        )
    )
    running_child = child_result.scalar_one_or_none()
    if running_child:
        has_active_delegation = True
        current_depth = running_child.delegation_depth
        if running_child.agent_type:
            active_sub_agent = running_child.agent_type.name  # type: ignore[union-attr]
    else:
        # Determine depth from the most recent delegation_started entry
        for entry in reversed(recent_entries):
            if entry.event_type == "delegation_started":
                current_depth = entry.data.get("delegation_depth", 0) if entry.data else 0
                active_sub_agent = entry.data.get("delegation_target") if entry.data else None
                break

    recent_event_list: list[dict] = []
    for entry in recent_entries:
        recent_event_list.append({
            "event_type": entry.event_type,
            "message": entry.message,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "data": entry.data,
        })

    return DelegationStatusResponse(
        has_active_delegation=has_active_delegation,
        current_depth=current_depth,
        max_depth=1,
        active_sub_agent_slug=active_sub_agent,
        recent_events=recent_event_list,
    )


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
    conv_session_id: uuid.UUID | None = None,
) -> None:
    """WebSocket endpoint for conversational agent sessions.

    Optional conv_session_id query param associates a ConversationSession with
    this connection so that auto-naming fires after the first user message.
    """
    await websocket.accept()
    try:
        # For conversation sessions there may not be a backing AgentJob yet
        job = await _session_service.get_session(session_id, db)
        if not job and conv_session_id is None:
            await websocket.close(code=4004, reason="Session not found")
            return

        await _session_service.handle_chat_websocket(
            session_id, websocket, db, conv_session_id=conv_session_id
        )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception as exc:
        logger.error("WebSocket error for session %s: %s", session_id, exc)
        await websocket.close(code=1011)


# ── Agent Type Endpoints ───────────────────────────────────────────────────────

@AgentTypeRouter.get("", response_model=list[AgentTypeRead])
async def list_agent_types(
    db: DbSession,
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[AgentTypeRead]:
    result = await db.execute(
        select(AgentType)
        .order_by(AgentType.name)
        .options(
            selectinload(AgentType.plan),
            selectinload(AgentType.sop_bindings).selectinload(AgentTypeSopBinding.sop),
            selectinload(AgentType.skill_bindings).selectinload(AgentTypeSkillBinding.skill),
        )
        .offset(offset)
        .limit(limit)
    )
    agents = list(result.scalars().all())
    return [AgentTypeRead.model_validate(a) for a in agents]


@AgentTypeRouter.post("", response_model=AgentTypeRead, status_code=status.HTTP_201_CREATED)
async def create_agent_type(
    body: AgentTypeCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> AgentTypeRead:
    if not body.sop_bindings and not body.skill_bindings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent types must specify at least one SOP or Skill binding",
        )

    # Validate bindings against role permissions
    if body.sop_bindings or body.skill_bindings:
        binding_errors = await validate_bindings(
            db=db,
            role_id=body.role_id,
            sop_bindings=body.sop_bindings,
            skill_bindings=body.skill_bindings,
        )
        if binding_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "binding_validation_failed", "messages": binding_errors},
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
    )
    db.add(agent_type)
    await db.flush()
    await db.refresh(agent_type)

    # Save bindings
    await _agent_type_service.set_bindings(
        db=db,
        agent_type_id=agent_type.id,
        sop_bindings=body.sop_bindings,
        skill_bindings=body.skill_bindings,
    )

    # Recursion/dead-loop validation (may block in strict_block mode)
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    checked_by = uuid.UUID(user_id_str) if user_id_str else None
    try:
        await get_recursion_validation_service().validate_agent_type(
            agent_type_id=agent_type.id,
            context=SopRecursionCheckContext.create,
            db=db,
            checked_by_user_id=checked_by,
        )
    except RecursionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "recursion_validation_failed",
                "summary": exc.summary,
                "findings": [
                    {
                        "type": f.finding_type.value,
                        "severity": f.severity.value,
                        "path": f.path_signature,
                        "recommendation": f.recommendation,
                    }
                    for f in exc.findings
                ],
            },
        )

    # Generate plan after commit (non-blocking — failures are recorded, not raised)
    await _plan_generation_service.generate_plan(agent_type, db)

    # Reload with relationships eagerly loaded so the response includes plan and bindings
    result = await db.execute(
        select(AgentType)
        .where(AgentType.id == agent_type.id)
        .options(
            selectinload(AgentType.plan),
            selectinload(AgentType.sop_bindings).selectinload(AgentTypeSopBinding.sop),
            selectinload(AgentType.skill_bindings).selectinload(AgentTypeSkillBinding.skill),
        )
    )
    agent_type = result.scalar_one()
    return AgentTypeRead.model_validate(agent_type)


@AgentTypeRouter.get("/{type_id}", response_model=AgentTypeRead)
async def get_agent_type(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> AgentTypeRead:
    result = await db.execute(
        select(AgentType)
        .where(AgentType.id == type_id)
        .options(
            selectinload(AgentType.plan),
            selectinload(AgentType.sop_bindings).selectinload(AgentTypeSopBinding.sop),
            selectinload(AgentType.skill_bindings).selectinload(AgentTypeSkillBinding.skill),
        )
    )
    agent_type = result.scalar_one_or_none()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")
    return AgentTypeRead.model_validate(agent_type)


@AgentTypeRouter.put("/{type_id}", response_model=AgentTypeRead)
async def update_agent_type(
    type_id: uuid.UUID,
    body: AgentTypeUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentTypeRead:
    agent_type = await db.get(AgentType, type_id)
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")

    # Save raw Pydantic model objects before model_dump converts them to dicts
    raw_sop_bindings = body.sop_bindings
    raw_skill_bindings = body.skill_bindings

    update_data = body.model_dump(exclude_unset=True)

    # Determine effective role_id after applying the update
    effective_role_id = update_data.get("role_id", agent_type.role_id)

    # Determine effective sop_bindings after applying the update
    # Use the raw Pydantic model objects (not dicts) so attribute access works
    sop_bindings_provided = "sop_bindings" in update_data
    skill_bindings_provided = "skill_bindings" in update_data
    effective_sop_bindings = raw_sop_bindings if sop_bindings_provided else None
    effective_skill_bindings = raw_skill_bindings if skill_bindings_provided else None

    # Enforce at least one SOP or Skill binding for all input types
    if sop_bindings_provided or skill_bindings_provided:
        effective_sop_count = len(effective_sop_bindings) if effective_sop_bindings else 0
        effective_skill_count = len(effective_skill_bindings) if effective_skill_bindings else 0

        if not sop_bindings_provided:
            existing_sop = await db.execute(
                select(AgentTypeSopBinding).where(
                    AgentTypeSopBinding.agent_type_id == agent_type.id
                )
            )
            effective_sop_count = len(existing_sop.scalars().all())
        if not skill_bindings_provided:
            existing_skill = await db.execute(
                select(AgentTypeSkillBinding).where(
                    AgentTypeSkillBinding.agent_type_id == agent_type.id
                )
            )
            effective_skill_count = len(existing_skill.scalars().all())

        if effective_sop_count == 0 and effective_skill_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent types must specify at least one SOP or Skill binding",
            )
    else:
        existing_sop = await db.execute(
            select(AgentTypeSopBinding).where(
                AgentTypeSopBinding.agent_type_id == agent_type.id
            )
        )
        existing_skill = await db.execute(
            select(AgentTypeSkillBinding).where(
                AgentTypeSkillBinding.agent_type_id == agent_type.id
            )
        )
        if len(existing_sop.scalars().all()) == 0 and len(existing_skill.scalars().all()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent types must specify at least one SOP or Skill binding",
            )

    # Validate bindings if they are being updated
    if effective_sop_bindings is not None or effective_skill_bindings is not None:
        role_for_validation = effective_role_id or agent_type.role_id
        binding_errors = await validate_bindings(
            db=db,
            role_id=role_for_validation,
            sop_bindings=effective_sop_bindings or [],
            skill_bindings=effective_skill_bindings or [],
        )
        if binding_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "binding_validation_failed",
                    "messages": binding_errors,
                },
            )

    # Separate binding fields from regular fields to handle binding updates differently
    update_data.pop("sop_bindings", None)
    update_data.pop("skill_bindings", None)

    for field, value in update_data.items():
        setattr(agent_type, field, value)

    await db.flush()

    # Update bindings if provided — use raw Pydantic model objects (not dicts)
    if sop_bindings_provided or skill_bindings_provided:
        await _agent_type_service.set_bindings(
            db=db,
            agent_type_id=agent_type.id,
            sop_bindings=raw_sop_bindings or [],
            skill_bindings=raw_skill_bindings or [],
        )

    await db.refresh(agent_type, attribute_names=["sop_bindings", "skill_bindings"])

    # Recursion/dead-loop validation (may block in strict_block mode)
    claims = get_current_claims(request)
    user_id_str: str | None = claims.get("platform_user_id")
    checked_by = uuid.UUID(user_id_str) if user_id_str else None
    try:
        await get_recursion_validation_service().validate_agent_type(
            agent_type_id=agent_type.id,
            context=SopRecursionCheckContext.update,
            db=db,
            checked_by_user_id=checked_by,
        )
    except RecursionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "recursion_validation_failed",
                "summary": exc.summary,
                "findings": [
                    {
                        "type": f.finding_type.value,
                        "severity": f.severity.value,
                        "path": f.path_signature,
                        "recommendation": f.recommendation,
                    }
                    for f in exc.findings
                ],
            },
        )

    # Regenerate plan after update (non-blocking — failures are recorded, not raised)
    await _plan_generation_service.generate_plan(agent_type, db)

    # Reload with relationships eagerly loaded so the response includes plan and bindings
    result = await db.execute(
        select(AgentType)
        .where(AgentType.id == agent_type.id)
        .options(
            selectinload(AgentType.plan),
            selectinload(AgentType.sop_bindings).selectinload(AgentTypeSopBinding.sop),
            selectinload(AgentType.skill_bindings).selectinload(AgentTypeSkillBinding.skill),
        )
    )
    agent_type = result.scalar_one()
    return AgentTypeRead.model_validate(agent_type)


@AgentTypeRouter.post("/{type_id}/regenerate-plan", response_model=AgentTypeRead)
async def regenerate_agent_type_plan(
    type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> AgentTypeRead:
    result = await db.execute(
        select(AgentType)
        .where(AgentType.id == type_id)
        .options(
            selectinload(AgentType.sop_bindings),
            selectinload(AgentType.skill_bindings),
        )
    )
    agent_type = result.scalar_one_or_none()
    if not agent_type:
        raise HTTPException(status_code=404, detail="Agent type not found")

    await _plan_generation_service.generate_plan(agent_type, db)

    result = await db.execute(
        select(AgentType)
        .where(AgentType.id == agent_type.id)
        .options(
            selectinload(AgentType.plan),
            selectinload(AgentType.sop_bindings).selectinload(AgentTypeSopBinding.sop),
            selectinload(AgentType.skill_bindings).selectinload(AgentTypeSkillBinding.skill),
        )
    )
    agent_type = result.scalar_one()
    return AgentTypeRead.model_validate(agent_type)


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
    await db.flush()


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
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[ModelConfigRead]:
    configs = await _model_config_service.list_model_configs(db, limit=limit, offset=offset)
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


@ModelConfigRouter.get("/workflow-generation", response_model=WorkflowGenerationModelConfigRead)
async def get_workflow_generation_model(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> WorkflowGenerationModelConfigRead:
    configs = await _model_config_service.list_model_configs(db)
    options: list[WorkflowGenerationModelOption] = []
    for config in configs:
        for model_id in config.enabled_models or []:
            options.append(
                WorkflowGenerationModelOption(
                    model_id=model_id,
                    config_id=config.id,
                    config_display_name=config.display_name,
                    provider_type=config.provider_type,
                )
            )

    return WorkflowGenerationModelConfigRead(
        selected_model_id=get_workflow_generation_model_id(),
        options=options,
    )


@ModelConfigRouter.put("/workflow-generation", response_model=WorkflowGenerationModelConfigRead)
async def set_workflow_generation_model(
    body: WorkflowGenerationModelConfigUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> WorkflowGenerationModelConfigRead:
    configs = await _model_config_service.list_model_configs(db)
    allowed_model_ids: set[str] = {
        model_id for config in configs for model_id in (config.enabled_models or [])
    }
    if body.model_id is not None and body.model_id not in allowed_model_ids:
        raise HTTPException(
            status_code=422,
            detail="Selected workflow generation model is not enabled in any model configuration",
        )

    set_workflow_generation_model_id(body.model_id)
    return await get_workflow_generation_model(db=db, _={})


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


# ── Model Usage Guardrail Endpoints ──────────────────────────────────────────
#
# Phase 3.7 rework: each POST creates exactly one (model, period) row.
# A duplicate (model_id, period) returns 409 with a deterministic error
# code so the UI can render the conflict without parsing free text.


@ModelUsageGuardrailRouter.get("/model-usage-limits", response_model=list[ModelUsageGuardrailLimitRead])
async def list_model_usage_limits(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[ModelUsageGuardrailLimitRead]:
    configs = await _model_usage_guardrail_service.list_configurations(db)
    return [ModelUsageGuardrailLimitRead.model_validate(c) for c in configs]


@ModelUsageGuardrailRouter.post(
    "/model-usage-limits",
    response_model=ModelUsageGuardrailLimitRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_model_usage_limit(
    body: ModelUsageGuardrailLimitCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "create")),
) -> ModelUsageGuardrailLimitRead:
    try:
        config = await _model_usage_guardrail_service.create_configuration(
            model_id=body.model_id,
            model_name=body.model_name,
            model_config_id=body.model_config_id,
            period=body.period,
            limit_value=body.limit_value,
            unit=body.unit,
            enforcement_posture=body.enforcement_posture,
            is_active=body.is_active,
            details=body.details,
            db=db,
        )
    except ModelGuardrailDuplicatePeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "guardrail_period_conflict",
                "model_config_id": str(exc.model_config_id),
                "period": exc.period.value,
            },
        ) from exc
    except ModelGuardrailModelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return ModelUsageGuardrailLimitRead.model_validate(config)


@ModelUsageGuardrailRouter.get(
    "/model-usage-limits/{config_id}",
    response_model=ModelUsageGuardrailLimitRead,
)
async def get_model_usage_limit(
    config_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> ModelUsageGuardrailLimitRead:
    config = await _model_usage_guardrail_service.get_configuration(config_id, db)
    if config is None:
        raise HTTPException(status_code=404, detail="Model usage limit not found")
    return ModelUsageGuardrailLimitRead.model_validate(config)


@ModelUsageGuardrailRouter.put(
    "/model-usage-limits/{config_id}",
    response_model=ModelUsageGuardrailLimitRead,
)
async def update_model_usage_limit(
    config_id: uuid.UUID,
    body: ModelUsageGuardrailLimitUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> ModelUsageGuardrailLimitRead:
    payload = body.model_dump(exclude_unset=True)
    config = await _model_usage_guardrail_service.update_configuration(
        config_id,
        db=db,
        **payload,
    )
    if config is None:
        raise HTTPException(status_code=404, detail="Model usage limit not found")
    return ModelUsageGuardrailLimitRead.model_validate(config)


@ModelUsageGuardrailRouter.delete(
    "/model-usage-limits/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_model_usage_limit(
    config_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> None:
    deleted = await _model_usage_guardrail_service.delete_configuration(config_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model usage limit not found")


@ModelUsageGuardrailRouter.get("/model-usage-posture", response_model=list[ModelUsagePostureRead])
async def get_model_usage_posture(
    db: DbSession,
    refresh: bool = Query(True),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[ModelUsagePostureRead]:
    if refresh:
        await _model_usage_guardrail_service.refresh_posture_snapshots(db)
    postures = await _model_usage_guardrail_service.get_current_posture(db)
    return [ModelUsagePostureRead.model_validate(p) for p in postures]


# ── Model Availability Endpoints ─────────────────────────────────────────────


@ModelAvailabilityRouter.put(
    "/model-configs/{config_id}/disabled",
    response_model=ModelConfigRead,
)
async def set_vendor_disabled(
    config_id: uuid.UUID,
    body: VendorDisabledUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> ModelConfigRead:
    """Toggle vendor-level ``ModelConfig.is_disabled`` and cascade to
    ModelAvailability rows.
    """
    try:
        config = await _model_availability_service.set_vendor_disabled(
            db, config_id, body.is_disabled
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ModelConfigRead.model_validate(config)


@ModelAvailabilityRouter.put(
    "/model-configs/{config_id}/models/{model_name}/disabled",
)
async def set_model_availability(
    config_id: uuid.UUID,
    model_name: str,
    body: ModelAvailabilityUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "update")),
) -> dict:
    """Toggle per-model availability with ``disabled_reason = manual``."""
    try:
        row = await _model_availability_service.set_model_disabled(
            db, config_id, model_name, body.is_disabled
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": str(row.id),
        "model_name": row.model_name,
        "vendor_model_config_id": str(row.vendor_model_config_id),
        "is_disabled": row.is_disabled,
        "disabled_reason": row.disabled_reason.value,
    }


@ModelAvailabilityRouter.get(
    "/model-availability",
    response_model=list[ModelAvailabilityVendorRead],
)
async def get_model_availability(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[ModelAvailabilityVendorRead]:
    """Return the full vendor → model → guardrail hierarchy.

    The response is a flat list of vendor rows, each carrying the
    effective (vendor-cascaded) model disable state and embedded
    guardrail summaries. The list shape matches the frontend's
    ``ModelAvailabilityHierarchy`` type and the
    ``useModelAvailability`` hook contract.
    """
    from app.schemas.agents import (
        ModelAvailabilityGuardrailSummary,
        ModelAvailabilityModelRead,
    )

    hierarchy = await _model_availability_service.list_hierarchy(db)
    return [
        ModelAvailabilityVendorRead(
            vendor_config_id=v["vendor_model_config_id"],
            vendor_display_name=v["display_name"],
            is_disabled=v["is_disabled"],
            models=[
                ModelAvailabilityModelRead(
                    model_name=m["model_name"],
                    is_disabled=m["effective_is_disabled"],
                    disabled_reason=m["disabled_reason"],
                    guardrails=[
                        ModelAvailabilityGuardrailSummary(
                            id=g["id"],
                            period=g["period"],
                            limit_value=g["limit_value"],
                            unit=g["unit"],
                            enforcement_posture=g["enforcement_posture"],
                            is_active=g["is_active"],
                            usage_value=g["usage_value"],
                            posture_state=g["posture_state"],
                        )
                        for g in m["guardrails"]
                    ],
                )
                for m in v["models"]
            ],
        )
        for v in hierarchy
    ]


@ModelAvailabilityRouter.post(
    "/preflight/availability",
    response_model=PreflightAvailabilityResponse,
    # The Agent Runtime pre-execution check is permission-gated the same
    # way the rest of the guardrail surface is — it is a runtime/control
    # plane contract, not a public endpoint.
    dependencies=[Depends(require_permission(RT_AGENT, "read"))],
)
async def preflight_availability(
    body: PreflightAvailabilityRequest,
    db: DbSession,
) -> PreflightAvailabilityResponse:
    """Pre-execution availability check used by Agent Runtime before dispatch.

    Returns ``allowed=True`` when the supplied model is enabled by at
    least one vendor; otherwise returns a deny verdict with a stable
    ``blocked_by`` token (model_disabled / vendor_disabled /
    model_not_found).
    """
    outcome = await _model_availability_service.check_availability(
        db, model_name=body.model_id, vendor_config_id=body.vendor_model_config_id
    )
    return PreflightAvailabilityResponse(
        allowed=outcome.allowed,
        reason=outcome.reason,
        disabled_reason=outcome.disabled_reason,
        blocked_by=outcome.blocked_by,
    )


# ── Runtime Control Endpoints ───────────────────────────────────────────────


@RuntimeControlRouter.get("/topology", response_model=RuntimeTopologyRead)
async def get_runtime_topology(
    db: DbSession,
    include_terminal: bool = Query(False),
    max_nodes: int = Query(200, ge=1, le=1000),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> RuntimeTopologyRead:
    from app.db.models.agents import AgentJobStatus

    statuses = (
        [AgentJobStatus.queued, AgentJobStatus.running]
        if not include_terminal
        else [
            AgentJobStatus.queued,
            AgentJobStatus.running,
            AgentJobStatus.completed,
            AgentJobStatus.failed,
            AgentJobStatus.terminated,
        ]
    )

    projection = await _runtime_topology_controller.get_active_topology(
        db,
        include_statuses=statuses,
        max_nodes=max_nodes,
    )  # include_conversations and include_instances default to True

    return RuntimeTopologyRead(
        nodes=[
            RuntimeTopologyNodeRead(
                session_id=node.session_id,
                agent_type_id=node.agent_type_id,
                agent_type_name=node.agent_type_name,
                status=node.status,
                depth_from_root=node.depth_from_root,
                parent_session_id=node.parent_session_id,
                started_at=node.started_at,
                created_at=node.created_at,
                termination_category=node.termination_category,
                kind=node.kind,
                title=node.title,
            )
            for node in projection.nodes
        ],
        edges=[
            RuntimeTopologyEdgeRead(
                parent_session_id=edge.parent_session_id,
                child_session_id=edge.child_session_id,
                depth_from_root=edge.depth_from_root,
            )
            for edge in projection.edges
        ],
        root_session_ids=projection.root_session_ids,
    )


@RuntimeControlRouter.post(
    "/terminal-jobs/purge",
    response_model=RuntimeTerminalJobPurgeRead,
)
async def purge_terminal_jobs(
    db: DbSession,
    older_than_hours: int = Query(
        24,
        ge=0,
        le=8760,
        description=(
            "Delete AgentJob rows with status in {completed, failed} whose "
            "updated_at is older than this many hours. Defaults to 24h; "
            "pass 0 to purge all terminal jobs."
        ),
    ),
    _: dict = Depends(require_permission(RT_AGENT, "delete")),
) -> RuntimeTerminalJobPurgeRead:
    """Purge completed/failed agent jobs to release database resources.

    The runtime control dashboard intentionally only shows *live* runs
    (queued + running). Terminal jobs are kept for audit and observability
    for a configurable retention window, but operators can force a purge
    earlier than the retention horizon via this endpoint.

    Includes ``terminated`` sessions (operator-initiated
    cancellations) alongside ``completed`` and ``failed`` so they
    count toward the same retention horizon.

    Deletion cascades to ``agent_run_relationships`` (FK ON DELETE
    CASCADE) and to ``session_logs`` rows that reference the session
    through the application-level delete path.
    """
    from sqlalchemy import delete as sql_delete

    from app.db.models.agents import AgentJob, AgentJobStatus

    statuses = [
        AgentJobStatus.completed,
        AgentJobStatus.failed,
        AgentJobStatus.terminated,
    ]
    cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)

    # Count before deletion so the response can show the remaining terminal
    # population (which is the same set, just minus what we deleted).
    count_stmt = select(func.count(AgentJob.id)).where(AgentJob.status.in_(statuses))
    if older_than_hours > 0:
        count_stmt = count_stmt.where(AgentJob.updated_at < cutoff)
    total_before = (await db.execute(count_stmt)).scalar_one()

    delete_stmt = sql_delete(AgentJob).where(AgentJob.status.in_(statuses))
    if older_than_hours > 0:
        delete_stmt = delete_stmt.where(AgentJob.updated_at < cutoff)
    delete_result = await db.execute(delete_stmt)
    purged = delete_result.rowcount or 0

    await db.commit()

    return RuntimeTerminalJobPurgeRead(
        purged_count=purged,
        remaining_terminal_count=max(total_before - purged, 0),
        cutoff=cutoff,
        statuses=statuses,
    )


@RuntimeControlRouter.post("/terminate", response_model=TerminationRequestRead)
async def request_runtime_termination(
    body: RuntimeTerminateRequest,
    request: Request,
    db: DbSession,
) -> TerminationRequestRead:
    """Submit a permission-gated runtime terminate request.

    This endpoint returns explicit policy-denial reasons and always records
    termination request outcomes in Control Center persistence.
    """
    from app.db.models.identity import Identity
    from app.db.models.platform_user import PlatformUser
    from app.services.permissions.permission_engine import PermissionEngine

    claims = get_current_claims(request)
    sub: str | None = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=403, detail="No identity claims found.")

    user_result = await db.execute(select(PlatformUser).where(PlatformUser.sub == sub))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=403,
            detail="User not found in platform. Please re-authenticate.",
        )

    identity_result = await db.execute(select(Identity).where(Identity.subject == sub))
    identity = identity_result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(
            status_code=403,
            detail="Identity not found in platform. Please re-authenticate.",
        )

    auth = await PermissionEngine().authorize(
        db=db,
        user_id=user.id,
        module=RT_AGENT,
        action="execute",
        resource_id="*",
        resource_tags={},
    )

    try:
        request_record = await _termination_orchestrator.request_termination(
            target_session_id=body.target_session_id,
            requested_by_user_id=identity.id,
            scope=body.termination_scope,
            operator_reason=body.operator_reason,
            db=db,
            can_terminate=auth.allowed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TerminationDeniedError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "termination_permission_denied",
                "reason": exc.reason,
            },
        )

    return TerminationRequestRead.model_validate(request_record)


@RuntimeControlRouter.get(
    "/terminate/{request_id}",
    response_model=list[TerminationCascadeOutcomeRead],
)
async def get_runtime_termination_outcomes(
    request_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[TerminationCascadeOutcomeRead]:
    request_record = await _termination_orchestrator.get_termination_request(request_id, db)
    if request_record is None:
        raise HTTPException(status_code=404, detail="Termination request not found")

    outcomes = await _termination_orchestrator.get_cascade_outcomes(request_id, db)
    return [TerminationCascadeOutcomeRead.model_validate(o) for o in outcomes]


@RuntimeControlRouter.get("/policy-events", response_model=list[ExecutionLogEntryRead])
async def list_runtime_policy_events(
    db: DbSession,
    session_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _: dict = Depends(require_permission(RT_AGENT, "read")),
) -> list[ExecutionLogEntryRead]:
    """List structured runtime policy events for dashboard/log correlation."""
    from app.db.models.session_logs import ExecutionEventCategory, ExecutionLogEntry

    stmt = select(ExecutionLogEntry).where(
        ExecutionLogEntry.event_category.in_(
            [
                ExecutionEventCategory.guardrail,
                ExecutionEventCategory.validation,
                ExecutionEventCategory.termination,
                ExecutionEventCategory.posture,
            ]
        )
    )
    if session_id is not None:
        stmt = stmt.where(ExecutionLogEntry.session_id == session_id)

    result = await db.execute(
        stmt.order_by(ExecutionLogEntry.timestamp.desc(), ExecutionLogEntry.id.desc()).limit(limit)
    )
    entries = list(result.scalars().all())
    entries.reverse()
    return [ExecutionLogEntryRead.model_validate(e) for e in entries]

