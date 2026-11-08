"""Internal management tool endpoints for the Control Center Assistant.

Exposes the Agents-menu management operations (create / update / read of
skills, SOPs, agent types, roles, identities, model configurations,
schedules, data types, and MCP Hub connections) as Control Center-side
handlers for the management MCP tools registered in
``SystemToolRegistry``.

These are reached over mTLS by the Communication Hub (forward-only).  Every
call is authorized against the authenticated *user* (resolved by ``user_sub``)
using the permission engine, so the assistant and external MCP clients can
never perform an action the user's own REST scope would deny.  There is no
delete verb and no elevated path.  Sensitive material (identity tokens,
decrypted MCP/provider credentials) is never echoed.

Endpoints:
- ``POST /internal/management-tools/resolve``          → resolve an OAuth
  user's identity, tenant and permitted management tools (session creation).
- ``POST /internal/management-tools/{tool_name}``      → execute one
  management tool (create / update / list / get).
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, inspect as sa_inspect, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorize_identity, require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.services.agents.management_payload import (
    ManagementValidationError,
    PayloadValidator,
    ReferenceNotFoundError,
    is_uuid_shaped,
    structured_error,
)

logger = logging.getLogger(__name__)

#: Data-plane execution router — consumes the signed tenant header set CH
#: forwards after a successful ``/resolve``.
router = APIRouter(
    prefix="/internal/management-tools",
    tags=["Internal - Management Tools"],
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
)

#: Control-plane ``/resolve`` router — ESTABLISHES tenant context from the
#: OAuth identity CH already validated.  CH calls ``/resolve`` presenting only
#: the OIDC-validated ``sub`` + ``tenant`` slug (no signed headers — CH is
#: forward-only and must never sign), so the ONLY entry guard here is mTLS
#: (``require_service_certificate``); ``require_internal_tenant_context`` is
#: deliberately absent.  Included before ``router`` so the literal ``/resolve``
#: matches before the ``/{tool_name}`` dynamic route.
resolve_router = APIRouter(
    prefix="/internal/management-tools",
    tags=["Internal - Management Tools"],
    dependencies=[Depends(require_service_certificate)],
)


# ── Request / response models ──────────────────────────────────────────────


class ManagementToolRequest(BaseModel):
    """Request to execute a management tool on behalf of an authenticated user."""

    session_id: str
    user_sub: str
    tool_args: dict[str, Any] = {}
    conversation_session_id: str | None = None
    agent_type_id: str | None = None


class ManagementToolResponse(BaseModel):
    """Response envelope for a management tool execution."""

    result: dict[str, Any]


class ManagementResolveRequest(BaseModel):
    """Request to resolve an OAuth user's identity / tenant / permitted tools."""

    sub: str
    tenant: str | None = None


class ManagementResolveResponse(BaseModel):
    """Resolved OAuth context for an MCP session (identity held server-side)."""

    platform_user_id: str
    user_sub: str
    tenant_id: str | None = None
    permitted_tools: list[str] = []
    tenant_headers: dict[str, str] | None = None


# ── Assistant meta tools (progressive tool disclosure) ─────────────────────
#
# CC handlers for the ``invoke_management_tool`` /
# ``get_management_tool_schema`` / ``list_management_tools`` /
# ``search_assistant_knowledge`` system tools — the conversational assistant
# carries ONLY these constant meta definitions in context instead of all ~36
# management execution schemas.  Declared on a separate router included
# BEFORE the dynamic ``/{tool_name}`` router so the literal single-segment
# paths match.
meta_router = APIRouter(
    prefix="/internal/management-tools",
    tags=["Internal - Management Tools"],
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
)


class ManagementMetaInvokeRequest(BaseModel):
    """Request body for the ``invoke_management_tool`` wrapper dispatch."""

    session_id: str
    user_sub: str
    tool_args: dict[str, Any] = {}
    conversation_session_id: str | None = None
    agent_type_id: str | None = None


@meta_router.post("/invoke_management_tool", response_model=ManagementToolResponse)
async def invoke_management_tool_meta(
    body: ManagementMetaInvokeRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ManagementToolResponse:
    """Dispatch any registered management tool through the existing dispatch.

    Permission parity is re-enforced HERE per actual (resource_type, action)
    against the signed-in user's own scope — exactly like the per-tool
    ``/{tool_name}`` endpoint.  No delete verb exists in the registry, so a
    delete-shaped request is declined as an unknown verb/tool; an unknown
    target tool returns a structured 404.
    """
    from app.services.agents.system_tool_registry import SystemToolRegistry

    args = body.tool_args or {}
    target = str(args.get("tool_name") or "").strip()
    inner_args = args.get("args") if isinstance(args.get("args"), dict) else {}
    if not target:
        raise HTTPException(status_code=400, detail="tool_name is required")

    tool = SystemToolRegistry.get(target)
    if tool is None or tool.parity is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown management tool: {target}. Use list_management_tools "
                f"to see the available management tools."
            ),
        )

    resource_type, action = tool.parity
    # Permission parity per wrapped invocation — the same _authorize the
    # per-tool endpoint uses (no elevation through the wrapper).
    await _authorize(db, body.user_sub, resource_type, action, tenant_ctx.tenant_id)

    inner = ManagementToolRequest(
        session_id=body.session_id,
        user_sub=body.user_sub,
        tool_args=inner_args,
        conversation_session_id=body.conversation_session_id,
        agent_type_id=body.agent_type_id,
    )
    result = await _dispatch(db, target, inner, tenant_ctx.tenant_id)
    return ManagementToolResponse(result=result)


@meta_router.post("/get_management_tool_schema", response_model=ManagementToolResponse)
async def get_management_tool_schema_meta(
    body: ManagementToolRequest,
) -> ManagementToolResponse:
    """Return the full OpenAI schema for one management tool, on demand."""
    from app.services.agents.system_tool_registry import SystemToolRegistry

    target = str((body.tool_args or {}).get("tool_name") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="tool_name is required")
    tool = SystemToolRegistry.get(target)
    if tool is None or tool.parity is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown management tool: {target}. Use list_management_tools "
                f"to see the available management tools."
            ),
        )
    return ManagementToolResponse(result={"tool_name": target, "schema": tool.openai_schema})


@meta_router.post("/list_management_tools", response_model=ManagementToolResponse)
async def list_management_tools_meta(
    body: ManagementToolRequest,
) -> ManagementToolResponse:
    """Return the cheap catalog: name + one-line description + permission."""
    from app.services.agents.system_tool_registry import SystemToolRegistry

    tools = [
        {
            "name": name,
            "description": SystemToolRegistry.get(name).description if SystemToolRegistry.get(name) else "",
            "requires_permission": f"{resource_type}:{action}",
        }
        for name, (resource_type, action) in sorted(SystemToolRegistry.get_parity_map().items())
    ]
    return ManagementToolResponse(result={"tools": tools, "count": len(tools)})


@meta_router.post("/search_assistant_knowledge", response_model=ManagementToolResponse)
async def search_assistant_knowledge_meta(
    body: ManagementToolRequest,
) -> ManagementToolResponse:
    """Keyword search over the platform knowledge corpus.

    Tenant-agnostic and read-only: the corpus contains PLATFORM rules only,
    never tenant data, so nothing sensitive can leak across tenants.
    """
    from app.services.agents.assistant_knowledge import search_knowledge

    args = body.tool_args or {}
    query = str(args.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        top_k = int(args.get("top_k") or 3)
    except (TypeError, ValueError):
        top_k = 3
    results = search_knowledge(query, top_k=top_k)
    return ManagementToolResponse(result={"query": query, "results": results})


# ── Helpers ────────────────────────────────────────────────────────────────


def _validation_error(exc: ManagementValidationError) -> HTTPException:
    """Render a structured validation failure as a 400 with a dict detail.

    Shape: ``{"error": "validation_failed", "problems": [{field, problem, remedy}]}``
    so the assistant can self-correct from the per-field problems.
    """
    return HTTPException(status_code=400, detail=exc.payload())


def _reference_error(exc: ReferenceNotFoundError) -> HTTPException:
    """Render an unknown referenced resource as a structured 404."""
    return HTTPException(status_code=404, detail={"error": "reference_not_found", "message": exc.message})


def _parse_uuid(raw: Any) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def _resolve_user_id(db: AsyncSession, user_sub: str) -> uuid.UUID:
    """Resolve a PlatformUser id by ``sub`` (identity plane, unscoped)."""
    from app.db.models.platform_user import PlatformUser
    from app.db.tenant_scoping import execute_unscoped

    result = await execute_unscoped(db, select(PlatformUser).where(PlatformUser.sub == user_sub))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=403,
            detail="User not found in platform. Please re-authenticate.",
        )
    return user.id


async def _authorize(db: AsyncSession, user_sub: str, resource_type: str, action: str, tenant_id: Any) -> None:
    """Authorize the user for ``(resource_type, action)`` (raises 403 on denial)."""
    await authorize_identity(
        db,
        {"sub": user_sub},
        resource_type,
        action,
        tenant_id=tenant_id,
    )


async def _cc_permitted(
    db: AsyncSession, user_sub: str, tenant_id: Any, action: str
) -> bool:
    """Does the TRIGGERING USER hold integration::control_center:* action?

    FIX-20261101-014511: the per-tenant Control Center entity (slug ``cc``)
    is a protected integration — toolset reads must hide it (or 404) for
    users without the entity-view grant.  Best-effort: any authorization
    failure means "not permitted".
    """
    from app.core.resource_types import RT_INTEGRATION_CONTROL_CENTER

    try:
        await _authorize(db, user_sub, RT_INTEGRATION_CONTROL_CENTER, action, tenant_id)
        return True
    except HTTPException:
        return False


def _row_dict(*, id: Any = None, **fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if id is not None:
        out["id"] = str(id)
    out.update(fields)
    return out


async def _check_duplicate_name(
    db: AsyncSession, model: Any, name_field: str, name: str, tenant_id: Any
) -> None:
    """Reject a duplicate tenant-scoped name (409)."""
    existing = (
        await db.execute(
            select(model).where(
                getattr(model, name_field) == name,
                model.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A {model.__tablename__} with {name_field} '{name}' already exists.",
        )


# ── Resolve (OAuth session creation) ───────────────────────────────────────


@resolve_router.post("/resolve", response_model=ManagementResolveResponse)
async def resolve_management_session(
    body: ManagementResolveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ManagementResolveResponse:
    """Resolve an OAuth user's identity, tenant and permitted management tools.

    Called by the Communication Hub after it validates the user's OIDC Bearer
    token.  The ``sub`` claim (already signature-verified by CH) is resolved
    to a ``PlatformUser``; the tenant is derived AUTHORITATIVELY from the
    OAuth identity (the ``tenant`` slug claim CH forwarded) — not from signed
    internal headers, which CH neither receives nor mints for this call.  The
    derived tenant context is signed here and returned so CH can bind and
    forward it verbatim on subsequent ``/{tool_name}`` executions.

    The permitted-tool set is the management parity map evaluated against the
    user's own permission scope in the DERIVED tenant — resolving a tenant the
    user has no active membership in yields an empty tool set (never elevated).
    """
    from app.core.tenant_signature import sign_context_for_authenticated_session
    from app.services.agents.system_tool_registry import SystemToolRegistry
    from app.services.tenancy.platform_settings_service import get_platform_settings_service
    from app.services.tenancy.root_tenant import get_root_tenant_context
    from app.services.tenancy.tenant_resolution_service import (
        TenantResolutionError,
        TenantResolutionService,
    )

    user_id = await _resolve_user_id(db, body.sub)

    multi_tenancy_enabled = await get_platform_settings_service().is_multi_tenancy_enabled(db)
    tenant_slug = (body.tenant or "").strip()

    if multi_tenancy_enabled and tenant_slug:
        # Multi-tenant: resolve the slug claim forwarded by CH (mirrors
        # ws/chat.py).  Unknown/suspended/deleted → fail closed (403).
        try:
            tenant_context = await TenantResolutionService().resolve_slug(db, tenant_slug)
        except TenantResolutionError as exc:
            raise HTTPException(
                status_code=403,
                detail=f"Unknown tenant: {tenant_slug}",
            ) from exc
    else:
        # Single-tenant (or no tenant claim): bind the ROOT tenant — the same
        # fallback require_internal_tenant_context applies.
        tenant_context = await get_root_tenant_context(db)
        if tenant_context is None:
            raise HTTPException(
                status_code=503,
                detail="Root tenant not provisioned — cannot resolve management session",
            )

    tenant_id = tenant_context.tenant_id
    permitted: list[str] = []
    for bare, (resource_type, action) in sorted(SystemToolRegistry.get_parity_map().items()):
        try:
            await _authorize(db, body.sub, resource_type, action, tenant_id)
            tool = SystemToolRegistry.get(bare)
            if tool is not None:
                permitted.append(tool.canonical_name)
        except HTTPException:
            continue

    tenant_headers: dict[str, str] | None = None
    if multi_tenancy_enabled:
        tenant_headers = sign_context_for_authenticated_session(tenant_context)

    logger.info(
        "Management resolve: sub=%s user=%s tenant=%s permitted=%d",
        body.sub, user_id, tenant_id, len(permitted),
    )
    return ManagementResolveResponse(
        platform_user_id=str(user_id),
        user_sub=body.sub,
        tenant_id=str(tenant_id) if tenant_id else None,
        permitted_tools=permitted,
        tenant_headers=tenant_headers,
    )


# ── Tool dispatch ──────────────────────────────────────────────────────────


@router.post("/{tool_name}", response_model=ManagementToolResponse)
async def execute_management_tool(
    tool_name: str,
    body: ManagementToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ManagementToolResponse:
    """Execute a single management tool on behalf of the authenticated user."""
    from app.services.agents.system_tool_registry import SystemToolRegistry

    tool = SystemToolRegistry.get(tool_name)
    if tool is None or tool.parity is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown or out-of-scope management tool: {tool_name}",
        )

    resource_type, action = tool.parity
    # Defense-in-depth re-authorization against the user's own scope.
    await _authorize(db, body.user_sub, resource_type, action, tenant_ctx.tenant_id)

    result = await _dispatch(db, tool_name, body, tenant_ctx.tenant_id)
    return ManagementToolResponse(result=result)


async def _dispatch(
    db: AsyncSession, tool_name: str, body: ManagementToolRequest, tenant_id: Any
) -> dict[str, Any]:
    """Route a management tool to its resource-specific handler."""
    verb, _, resource = tool_name.partition("_")
    resource = _canonical_resource(resource)
    args = body.tool_args or {}

    # Read verbs share a list/get path.
    if verb == "list":
        return await _list_resource(db, resource, args, tenant_id, user_sub=body.user_sub)
    if verb == "get":
        return await _get_resource(db, resource, args, tenant_id, user_sub=body.user_sub)
    if verb == "create":
        return await _create_resource(db, resource, args, tenant_id, body.user_sub)
    if verb == "update":
        return await _update_resource(db, resource, args, tenant_id)
    raise HTTPException(status_code=404, detail=f"Unknown management verb: {verb}")


# ── Serializers (never echo credentials / tokens) ──────────────────────────


def _serialize_skill(s) -> dict[str, Any]:
    return _row_dict(
        id=s.id, name=s.name, description=s.description,
        instructions=s.instructions, is_active=s.is_active, is_system=s.is_system,
    )


#: Non-fatal warning carried in create/update_skill results when the skill
#: ends up with ZERO tool bindings (FIX-20261101-223511).  Tool-less skills
#: are technically allowed, so this is a warning — not an error — but the
#: assistant's knowledge instructs it to self-correct immediately.
ZERO_BINDING_WARNING = (
    "This skill has no tools bound — it cannot invoke anything. Bind tools "
    "via update_skill tool_ids/tool_names (discover them first with "
    "get_mcp_server)."
)


async def _attach_skill_tool_bindings(
    db: AsyncSession, records: list[dict[str, Any]], tenant_id: Any
) -> None:
    """Attach ``tool_bindings`` (name + owning server) to skill records.

    FIX-20261101-223511: skills read through the management toolset now carry
    their bound tools so the assistant (and the user) can SEE what a skill
    invokes.  One joined query for the whole batch; bindings to virtual tools
    (no ``mcp_tools`` row, e.g. decision tools) degrade gracefully to the
    bare tool id.
    """
    from app.db.models.mcp_hub import McpServer, McpTool
    from app.db.models.skills import SkillToolBinding

    skill_ids = [r.get("id") for r in records if r.get("id")]
    if not skill_ids:
        return
    parsed = [_parse_uuid(sid) for sid in skill_ids]
    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return
    rows = (
        await db.execute(
            select(SkillToolBinding, McpTool, McpServer)
            .outerjoin(McpTool, SkillToolBinding.tool_id == McpTool.id)
            .outerjoin(McpServer, McpTool.server_id == McpServer.id)
            .where(SkillToolBinding.skill_id.in_(parsed))
            .order_by(SkillToolBinding.skill_id, SkillToolBinding.order)
        )
    ).all()
    by_skill: dict[str, list[dict[str, Any]]] = {}
    for binding, tool, server in rows:
        key = str(binding.skill_id)
        by_skill.setdefault(key, []).append(
            {
                "tool_id": str(binding.tool_id),
                "name": (tool.name if tool else None) or str(binding.tool_id),
                "original_name": tool.original_name if tool else None,
                "server_slug": server.slug if server else None,
                "server_name": server.name if server else None,
            }
        )
    for record in records:
        record["tool_bindings"] = by_skill.get(str(record.get("id")), [])


async def _count_skill_bindings(db: AsyncSession, skill_id: Any) -> int:
    """Count a skill's tool bindings (skills are already tenant-scoped)."""
    from app.db.models.skills import SkillToolBinding

    return len(
        (
            await db.execute(
                select(SkillToolBinding.id).where(SkillToolBinding.skill_id == skill_id)
            )
        ).scalars()
        .all()
    )


def _serialize_sop(s) -> dict[str, Any]:
    record = _row_dict(
        id=s.id, name=s.name, description=s.description,
        instructions=s.instructions, is_active=s.is_active,
    )
    # UI-detail parity (task 2.7): the ordered step list the UI step editor
    # shows.  Kept lean: identity/type/reference/name/description per step,
    # step_config only when present.  Steps are eagerly loaded for the
    # get/list tools via _eager_load_options; the unloaded-relationship guard
    # keeps direct serializer reuse safe (async sessions never lazy-load).
    steps: list[Any] = []
    try:
        if "steps" not in sa_inspect(s).unloaded:
            steps = list(s.steps)
    except Exception:  # noqa: BLE001 — inspection is best-effort
        steps = []
    record["steps"] = [
        {
            "order": step.order,
            "step_type": (
                step.step_type.value if hasattr(step.step_type, "value") else str(step.step_type)
            ),
            "skill_id": str(step.skill_id) if step.skill_id else None,
            "target_agent_type_id": (
                str(step.target_agent_type_id) if step.target_agent_type_id else None
            ),
            "name": step.name,
            "description": step.description,
            **({"step_config": step.step_config} if step.step_config else {}),
        }
        for step in sorted(steps, key=lambda st: st.order)
    ]
    return record


def _serialize_agent_type(a) -> dict[str, Any]:
    record = _row_dict(
        id=a.id, name=a.name, description=a.description,
        identity_id=str(a.identity_id) if a.identity_id else None,
        role_id=str(a.role_id) if a.role_id else None,
        model_id=a.model_id, system_instruction=a.system_instruction,
        input_type=a.input_type.value if hasattr(a.input_type, "value") else str(a.input_type),
        output_type=a.output_type.value if hasattr(a.output_type, "value") else str(a.output_type),
        input_schema=a.input_schema, output_schema=a.output_schema,
        output_data_type_id=str(a.output_data_type_id) if a.output_data_type_id else None,
        # UI-detail parity: guardrail configuration (all eight fields).
        guardrail_max_iterations=a.guardrail_max_iterations,
        guardrail_max_delegation_depth=a.guardrail_max_delegation_depth,
        guardrail_max_delegated_steps=a.guardrail_max_delegated_steps,
        guardrail_execution_timeout_seconds=a.guardrail_execution_timeout_seconds,
        guardrail_token_budget=a.guardrail_token_budget,
        guardrail_token_enforcement_mode=(
            a.guardrail_token_enforcement_mode.value
            if hasattr(a.guardrail_token_enforcement_mode, "value")
            else str(a.guardrail_token_enforcement_mode)
        ),
        guardrail_token_fallback_mode=(
            a.guardrail_token_fallback_mode.value
            if hasattr(a.guardrail_token_fallback_mode, "value")
            else str(a.guardrail_token_fallback_mode)
        ),
        guardrail_conversational_token_visibility_mode=(
            a.guardrail_conversational_token_visibility_mode.value
            if hasattr(a.guardrail_conversational_token_visibility_mode, "value")
            else str(a.guardrail_conversational_token_visibility_mode)
        ),
        guardrail_conversational_continuation_policy=(
            a.guardrail_conversational_continuation_policy.value
            if hasattr(a.guardrail_conversational_continuation_policy, "value")
            else str(a.guardrail_conversational_continuation_policy)
        ),
        is_active=a.is_active, is_system=a.is_system,
    )
    # UI-detail parity: the resolved output data type NAME (no lazy-load risk —
    # column read only when the relationship was eagerly loaded by the caller;
    # otherwise degrade to the id already present above).
    try:
        sa_inspect_a = sa_inspect(a)
        if "output_data_type" not in sa_inspect_a.unloaded and a.output_data_type is not None:
            record["output_data_type_name"] = a.output_data_type.name
        else:
            record["output_data_type_name"] = None
    except Exception:  # noqa: BLE001 — inspection is best-effort
        record["output_data_type_name"] = None
    return record


def _serialize_agent_role(r) -> dict[str, Any]:
    record = _row_dict(id=r.id, name=r.name, description=r.description)
    # UI-detail parity: the role's granted skill/SOP ids (same relationship
    # guard as AgentRoleRead.model_validate — never trigger a lazy load in an
    # async session).
    skill_ids: list[str] = []
    sop_ids: list[str] = []
    try:
        insp = sa_inspect(r)
        if "skill_assignments" not in insp.unloaded:
            skill_ids = [str(a.skill_id) for a in r.skill_assignments]
        if "sop_assignments" not in insp.unloaded:
            sop_ids = [str(a.sop_id) for a in r.sop_assignments]
    except Exception:  # noqa: BLE001 — inspection is best-effort
        pass
    record["skill_ids"] = skill_ids
    record["sop_ids"] = sop_ids
    # MCP session mappings (parity with the role editor): one session per
    # server per role — server/session names and the auth TYPE only, never
    # any credential material.  Relationship guard as above (no lazy load).
    mcp_mappings: list[dict[str, Any]] = []
    try:
        insp = sa_inspect(r)
        if "mcp_session_assignments" not in insp.unloaded:
            for a in r.mcp_session_assignments:
                entry: dict[str, Any] = {
                    "server_id": str(a.server_id),
                    "session_id": str(a.mcp_session_id),
                    "server_name": None,
                    "session_name": None,
                    "auth_type": None,
                }
                a_insp = sa_inspect(a)
                if "server" not in a_insp.unloaded and a.server is not None:
                    entry["server_name"] = a.server.name
                if "mcp_session" not in a_insp.unloaded and a.mcp_session is not None:
                    entry["session_name"] = a.mcp_session.name
                    entry["auth_type"] = (
                        a.mcp_session.auth_type.value
                        if hasattr(a.mcp_session.auth_type, "value")
                        else str(a.mcp_session.auth_type)
                    )
                mcp_mappings.append(entry)
    except Exception:  # noqa: BLE001 — inspection is best-effort
        pass
    record["mcp_session_mappings"] = mcp_mappings
    return record


def _serialize_agent_identity(i) -> dict[str, Any]:
    record = _row_dict(
        id=i.id, name=i.name,
        identity_type=i.identity_type.value if hasattr(i.identity_type, "value") else str(i.identity_type),
        realm_name=i.realm_name, realm_username=i.realm_username,
        status=i.status.value if hasattr(i.status, "value") else str(i.status),
        # Non-sensitive token POSTURE (never the token material itself).
        token_expires_at=i.token_expires_at.isoformat() if i.token_expires_at else None,
        has_refresh_token=bool(i.refresh_token),
    )
    # UI-detail parity: assigned role ids (relationship guard — never lazy-load).
    role_ids: list[str] = []
    try:
        insp = sa_inspect(i)
        if "role_assignments" not in insp.unloaded:
            role_ids = [str(a.role_id) for a in i.role_assignments]
    except Exception:  # noqa: BLE001 — inspection is best-effort
        pass
    record["role_ids"] = role_ids
    return record


def _serialize_model_config(m) -> dict[str, Any]:
    return _row_dict(
        id=m.id, display_name=m.display_name,
        provider_type=m.provider_type.value if hasattr(m.provider_type, "value") else str(m.provider_type),
        api_base_url=m.api_base_url, enabled_models=m.enabled_models, is_disabled=m.is_disabled,
        # Non-sensitive credential POSTURE — never the key material itself.
        has_credentials=bool(getattr(m, "encrypted_api_key", None)),
    )


def _serialize_schedule(j) -> dict[str, Any]:
    return _row_dict(
        id=j.id, name=j.name, description=j.description, cron_expression=j.cron_expression,
        target_type=j.target_type.value if hasattr(j.target_type, "value") else str(j.target_type),
        target_id=str(j.target_id), payload=j.payload,
        status=j.status.value if hasattr(j.status, "value") else str(j.status),
        scheduler_job_id=j.scheduler_job_id,
    )


def _serialize_data_type(d) -> dict[str, Any]:
    return _row_dict(id=d.id, name=d.name, slug=d.slug, description=d.description, fields=d.fields)


def _serialize_mcp_server(s) -> dict[str, Any]:
    return _row_dict(
        id=s.id, name=s.name, slug=s.slug, description=s.description,
        base_url=s.base_url,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
    )


_SERIALIZERS = {
    "skills": _serialize_skill,
    "sops": _serialize_sop,
    "agent_types": _serialize_agent_type,
    "agent_roles": _serialize_agent_role,
    "agent_identities": _serialize_agent_identity,
    "model_configs": _serialize_model_config,
    "schedules": _serialize_schedule,
    "data_types": _serialize_data_type,
    "mcp_servers": _serialize_mcp_server,
}

_MODELS = {
    "skills": ("Skill", "name"),
    "sops": ("Sop", "name"),
    "agent_types": ("AgentType", "name"),
    "agent_roles": ("AgentRole", "name"),
    "agent_identities": ("AgentIdentity", "name"),
    "model_configs": ("ModelConfig", "display_name"),
    "schedules": ("ScheduledJob", "name"),
    "data_types": ("AgentDataType", "name"),
    "mcp_servers": ("McpServer", "slug"),
}

#: Singular → plural resource key. The registry registers create/update/get
#: tools under the SINGULAR family name (``create_skill``) and list tools under
#: the PLURAL (``list_skills``); ``_MODELS`` / ``_SERIALIZERS`` are keyed by the
#: plural, so dispatch canonicalizes the parsed resource before lookup.
_SINGULAR_TO_PLURAL = {
    "skill": "skills",
    "sop": "sops",
    "agent_type": "agent_types",
    "agent_role": "agent_roles",
    "agent_identity": "agent_identities",
    "model_config": "model_configs",
    "schedule": "schedules",
    "data_type": "data_types",
    "mcp_server": "mcp_servers",
}


def _canonical_resource(resource: str) -> str:
    """Map a singular resource name to its plural registry key (idempotent)."""
    return _SINGULAR_TO_PLURAL.get(resource, resource)


def _import_model(resource: str) -> tuple[Any, str]:
    model_name, name_field = _MODELS[resource]
    if resource in ("skills", "sops"):
        from app.db.models.skills import Skill, Sop

        return (Skill if resource == "skills" else Sop), name_field
    if resource == "agent_types":
        from app.db.models.agents import AgentType

        return AgentType, name_field
    if resource == "agent_roles":
        from app.db.models.agents import AgentRole

        return AgentRole, name_field
    if resource == "agent_identities":
        from app.db.models.agents import AgentIdentity

        return AgentIdentity, name_field
    if resource == "model_configs":
        from app.db.models.agents import ModelConfig

        return ModelConfig, name_field
    if resource == "schedules":
        from app.db.models.scheduling import ScheduledJob

        return ScheduledJob, name_field
    if resource == "data_types":
        from app.db.models.agent_data_type import AgentDataType

        return AgentDataType, name_field
    if resource == "mcp_servers":
        from app.db.models.mcp_hub import McpServer

        return McpServer, name_field
    raise HTTPException(status_code=404, detail=f"Unknown management resource: {resource}")


def _eager_load_options(resource: str) -> list[Any]:
    """Relationships the UI-detail serializers need (eagerly loaded so async
    sessions never hit a lazy-load)."""
    from app.db.models.agents import AgentIdentity, AgentRole, AgentType

    if resource == "agent_types":
        return [selectinload(AgentType.output_data_type)]
    if resource == "agent_roles":
        from app.db.models.agents import AgentRoleMcpSession

        return [
            selectinload(AgentRole.skill_assignments),
            selectinload(AgentRole.sop_assignments),
            selectinload(AgentRole.mcp_session_assignments).selectinload(
                AgentRoleMcpSession.mcp_session
            ),
            selectinload(AgentRole.mcp_session_assignments).selectinload(
                AgentRoleMcpSession.server
            ),
        ]
    if resource == "agent_identities":
        return [selectinload(AgentIdentity.role_assignments)]
    if resource == "sops":
        from app.db.models.skills import Sop

        return [selectinload(Sop.steps)]
    return []


# ── Read handlers ──────────────────────────────────────────────────────────


async def _list_resource(
    db: AsyncSession,
    resource: str,
    args: dict[str, Any],
    tenant_id: Any,
    *,
    user_sub: str = "",
) -> dict[str, Any]:
    model, _ = _import_model(resource)
    serializer = _SERIALIZERS[resource]
    limit = int(args.get("limit", 50) or 50)
    offset = int(args.get("offset", 0) or 0)
    limit = max(1, min(limit, 100))
    stmt = select(model).where(model.tenant_id == tenant_id)
    # Soft-deleted schedules are hidden (matches the REST list).
    if resource == "schedules":
        from app.db.models.scheduling import JobStatus

        stmt = stmt.where(model.status != JobStatus.deleted)
    stmt = stmt.order_by(getattr(model, _MODELS[resource][1])).offset(offset).limit(limit)
    for option in _eager_load_options(resource):
        stmt = stmt.options(option)
    rows = (await db.execute(stmt)).scalars().all()
    if resource == "mcp_servers":
        # FIX-20261101-014511: the cc entity is only visible to users with
        # integration::control_center:read — omit it otherwise.
        if not await _cc_permitted(db, user_sub, tenant_id, "read"):
            rows = [r for r in rows if getattr(r, "slug", None) != "cc"]
    records = [serializer(r) for r in rows]
    if resource == "skills":
        # FIX-20261101-223511: skills list carries its bound tools.
        await _attach_skill_tool_bindings(db, records, tenant_id)
    return {"records": records, "count": len(records)}


async def _get_resource(
    db: AsyncSession,
    resource: str,
    args: dict[str, Any],
    tenant_id: Any,
    *,
    user_sub: str = "",
) -> dict[str, Any]:
    model, name_field = _import_model(resource)
    serializer = _SERIALIZERS[resource]
    obj_id = _parse_uuid(args.get("id"))
    name = args.get("name")
    stmt = select(model).where(model.tenant_id == tenant_id)
    if obj_id is not None:
        stmt = stmt.where(model.id == obj_id)
    elif name:
        stmt = stmt.where(getattr(model, name_field) == name)
    else:
        raise _validation_error(
            structured_error(
                "id",
                "or name is required",
                "Provide the record id or exact name (use the list tool to find it).",
            )
        )
    for option in _eager_load_options(resource):
        stmt = stmt.options(option)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    if resource == "mcp_servers" and getattr(row, "slug", None) == "cc":
        # FIX-20261101-014511: 404-without-leak for users without the
        # integration::control_center:read entity-view grant.
        if not await _cc_permitted(db, user_sub, tenant_id, "read"):
            raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")
    record = serializer(row)
    if resource == "mcp_servers":
        # Tool discovery (FIX-20261101-000319): return the server's synced
        # tools (canonical server____tool names) so the assistant can find
        # e.g. the supabase server's tool names before creating a skill.
        from app.db.models.mcp_hub import McpTool
        from app.services.agents.tool_naming import build_tool_name

        tools = (
            (
                await db.execute(
                    select(McpTool)
                    .where(
                        McpTool.server_id == row.id,
                        McpTool.tenant_id == tenant_id,
                        McpTool.is_active.is_(True),
                    )
                    .order_by(McpTool.name)
                )
            )
            .scalars()
            .all()
        )
        record["tools"] = [
            {
                "id": str(t.id),
                "name": t.name
                or build_tool_name(row.slug, t.original_name or ""),
                "original_name": t.original_name,
                "description": t.description,
            }
            for t in tools
        ]
    if resource == "skills":
        # FIX-20261101-223511: skills get carries its bound tools.
        await _attach_skill_tool_bindings(db, [record], tenant_id)
    return {"record": record}


# ── Write handlers ─────────────────────────────────────────────────────────


async def _create_resource(
    db: AsyncSession, resource: str, args: dict[str, Any], tenant_id: Any, user_sub: str
) -> dict[str, Any]:
    model, name_field = _import_model(resource)
    serializer = _SERIALIZERS[resource]
    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    name = str(args.get("name") or data.get("name") or data.get("display_name") or "").strip()
    if not name:
        raise _validation_error(structured_error("name", "is required", "Provide the resource name."))
    PayloadValidator.reject_unknown(
        data, _ALLOWED_CREATE_FIELDS.get(resource, set()), f"create_{_singular(resource)}"
    )

    # Tenant-scoped uniqueness check.  Most resources are unique by display
    # name; MCP servers are unique by slug (business identity = (tenant, slug)),
    # so the duplicate probe uses the slug value there.
    unique_value = name
    if resource == "mcp_servers":
        unique_value = str(data.get("slug") or "").strip() or name
    await _check_duplicate_name(db, model, name_field, unique_value, tenant_id)

    try:
        obj = await _build_create(db, resource, model, name, data, tenant_id, user_sub)
    except ManagementValidationError as exc:
        raise _validation_error(exc) from exc
    except ReferenceNotFoundError as exc:
        raise _reference_error(exc) from exc
    db.add(obj)
    try:
        await db.flush()
    except Exception as exc:  # noqa: BLE001 — duplicate / constraint races
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Create failed: {exc}") from exc

    # Agent types may bind skills/SOPs at create time (skill_ids / sop_ids
    # in data).  All identifiers are resolved and validated BEFORE rows are
    # added, so an unknown id/name fails the whole call with no partial write.
    if resource == "agent_types":
        await _bind_agent_type_capabilities(db, obj, data, tenant_id)

    # Roles may be granted skills/SOPs at create time (skill_ids / sop_ids in
    # data, FIX-20261031-131030) — the same resolution-before-write discipline.
    if resource == "agent_roles":
        await _bind_agent_role_capabilities(db, obj, data, tenant_id)

    # Roles: MCP session mappings + the default-mapping rules (task 2.8).
    # All resolution/validation happens BEFORE rows are added (no partial
    # write); ambiguity warnings are returned to the assistant in the result.
    role_mcp_warnings: list[str] = []
    role_auto_mapped: list[str] = []
    if resource == "agent_roles":
        try:
            role_mcp_warnings, role_auto_mapped = await _bind_agent_role_mcp_sessions(
                db, obj, data, tenant_id
            )
        except ManagementValidationError as exc:
            raise _validation_error(exc) from exc
        except ReferenceNotFoundError as exc:
            raise _reference_error(exc) from exc

    # Best-effort side effects (e.g. scheduler registration for schedules).
    if resource == "skills":
        # Skill ↔ tool association (FIX-20261101-000319): tool_ids /
        # tool_names in data create SkillToolBinding rows.  Resolution
        # happens BEFORE any binding row is added (unknown → 404, no
        # partial write).
        await _bind_skill_tools(db, obj, data, tenant_id)

    # SOPs may carry their ordered step list at create time ("steps" in
    # data).  The whole list validates and resolves BEFORE the SOP row is
    # flushed, so an unknown skill/agent-type reference fails the whole call
    # with no partial write.
    resolved_sop_steps: list[dict[str, Any]] = []
    if resource == "sops" and "steps" in data:
        try:
            resolved_sop_steps = await _validate_sop_steps(
                db, data["steps"], tenant_id, PayloadValidator(db, tenant_id)
            )
        except ManagementValidationError as exc:
            raise _validation_error(exc) from exc
        except ReferenceNotFoundError as exc:
            raise _reference_error(exc) from exc

    await _post_create_side_effects(db, resource, obj)
    if resolved_sop_steps:
        await _write_sop_steps(db, obj.id, resolved_sop_steps)
    await db.commit()

    refreshed_stmt = select(model).where(model.id == obj.id)
    for option in _eager_load_options(resource):
        refreshed_stmt = refreshed_stmt.options(option)
    refreshed = (await db.execute(refreshed_stmt)).scalar_one()
    record = serializer(refreshed)
    result: dict[str, Any] = {"record": record}
    if resource == "agent_roles":
        if role_mcp_warnings:
            result["warnings"] = result.get("warnings", []) + role_mcp_warnings
        if role_auto_mapped:
            result["auto_mapped_mcp_sessions"] = role_auto_mapped
    if resource == "skills":
        # FIX-20261101-223511: show the bound tools + guard against zero
        # bindings (non-fatal warning — the assistant self-corrects).
        await _attach_skill_tool_bindings(db, [record], tenant_id)
        if await _count_skill_bindings(db, obj.id) == 0:
            result["warnings"] = [ZERO_BINDING_WARNING]
    return result


def _coerce(enum_cls: Any, raw: Any, field: str) -> Any:
    """Coerce a raw string to a SQLAlchemy enum member (structured 400 on invalid).

    Kept as a thin shim over the shared validator so legacy call sites get the
    structured (field / problem / remedy) error shape for free.
    """
    return PayloadValidator.coerce_enum(enum_cls, raw, field)


#: Per-family allowed ``data`` keys (unknown fields are rejected with a
#: structured problem naming the accepted set — the assistant self-corrects).
_ALLOWED_CREATE_FIELDS: dict[str, set[str]] = {
    "skills": {"name", "description", "instructions", "is_active", "tool_ids", "tool_names"},
    "sops": {"name", "description", "instructions", "is_active", "steps"},
    "agent_types": {
        "name", "description", "identity_id", "role_id", "model_id", "is_active",
        "system_instruction", "input_type", "input_schema", "output_type",
        "output_schema", "output_data_type_id", "skill_ids", "sop_ids",
        "guardrail_max_iterations", "guardrail_max_delegation_depth",
        "guardrail_max_delegated_steps", "guardrail_execution_timeout_seconds",
        "guardrail_token_budget", "guardrail_token_enforcement_mode",
        "guardrail_token_fallback_mode", "guardrail_conversational_token_visibility_mode",
        "guardrail_conversational_continuation_policy",
    },
    "agent_roles": {"name", "description", "skill_ids", "sop_ids", "mcp_session_mappings"},
    "agent_identities": {"name", "identity_type", "realm_name", "realm_username", "status"},
    "model_configs": {"name", "display_name", "provider_type", "api_base_url", "api_key", "enabled_models", "is_disabled"},
    "schedules": {"name", "description", "cron_expression", "cron", "payload", "target_type", "target_id", "agent_type_id"},
    "data_types": {"name", "slug", "description", "fields"},
    "mcp_servers": {"name", "slug", "description", "base_url"},
}

_ALLOWED_UPDATE_FIELDS: dict[str, set[str]] = {
    "skills": {"name", "description", "instructions", "is_active", "tool_ids", "tool_names"},
    "sops": {"name", "description", "instructions", "is_active", "steps"},
    "agent_types": {
        "name", "description", "identity_id", "role_id", "model_id", "is_active",
        "system_instruction", "input_type", "input_schema", "output_type",
        "output_schema", "output_data_type_id", "skill_ids", "sop_ids",
        "guardrail_max_iterations", "guardrail_max_delegation_depth",
        "guardrail_max_delegated_steps", "guardrail_execution_timeout_seconds",
        "guardrail_token_budget", "guardrail_token_enforcement_mode",
        "guardrail_token_fallback_mode", "guardrail_conversational_token_visibility_mode",
        "guardrail_conversational_continuation_policy",
    },
    "agent_roles": {"name", "description", "skill_ids", "sop_ids", "mcp_session_mappings"},
    "agent_identities": {"name", "realm_name", "realm_username", "status", "role_ids"},
    "model_configs": {"name", "display_name", "provider_type", "api_base_url", "api_key", "enabled_models", "is_disabled"},
    "schedules": {"name", "description", "cron_expression", "payload"},
    "data_types": {"name", "description", "fields"},
    "mcp_servers": {"name", "description", "base_url"},
}

_SLUG_PATTERN_RESOURCES = {"skills", "sops", "agent_types", "agent_identities", "mcp_servers"}

_MIN_MAX_ITERATIONS = 1
_MAX_MAX_ITERATIONS = 1000
_MIN_MAX_DELEGATION_DEPTH = 0
_MAX_MAX_DELEGATION_DEPTH = 32
_MIN_MAX_DELEGATED_STEPS = 0
_MAX_MAX_DELEGATED_STEPS = 5000
_MIN_EXECUTION_TIMEOUT_SECONDS = 1
_MAX_EXECUTION_TIMEOUT_SECONDS = 86400
_MIN_TOKEN_BUDGET = 1
_MAX_TOKEN_BUDGET = 10_000_000


def _validate_guardrails_structured(
    *,
    input_type: Any,
    guardrail_max_iterations: int,
    guardrail_max_delegation_depth: int,
    guardrail_max_delegated_steps: int,
    guardrail_execution_timeout_seconds: int,
    guardrail_token_budget: int | None,
    guardrail_token_enforcement_mode: Any,
) -> None:
    """Mirror the REST guardrail contract (`_validate_guardrail_contract`) with
    structured per-field errors (same bounds, same conversational rule)."""
    from app.db.models.agents import AgentInputType, GuardrailTokenEnforcementMode

    bounds = (
        ("guardrail_max_iterations", guardrail_max_iterations, _MIN_MAX_ITERATIONS, _MAX_MAX_ITERATIONS),
        ("guardrail_max_delegation_depth", guardrail_max_delegation_depth, _MIN_MAX_DELEGATION_DEPTH, _MAX_MAX_DELEGATION_DEPTH),
        ("guardrail_max_delegated_steps", guardrail_max_delegated_steps, _MIN_MAX_DELEGATED_STEPS, _MAX_MAX_DELEGATED_STEPS),
        (
            "guardrail_execution_timeout_seconds",
            guardrail_execution_timeout_seconds,
            _MIN_EXECUTION_TIMEOUT_SECONDS,
            _MAX_EXECUTION_TIMEOUT_SECONDS,
        ),
    )
    err = ManagementValidationError()
    for name, value, low, high in bounds:
        if not (low <= value <= high):
            err.add(name, f"must be between {low} and {high}", f"Provide a value between {low} and {high}.")
    if guardrail_token_budget is not None and not (_MIN_TOKEN_BUDGET <= guardrail_token_budget <= _MAX_TOKEN_BUDGET):
        err.add(
            "guardrail_token_budget",
            f"must be between {_MIN_TOKEN_BUDGET} and {_MAX_TOKEN_BUDGET} when provided",
            f"Provide a value between {_MIN_TOKEN_BUDGET} and {_MAX_TOKEN_BUDGET}, or omit it.",
        )
    input_is_conversation = (input_type == AgentInputType.conversation) or (
        getattr(input_type, "value", input_type) == "conversation"
    )
    mode = getattr(guardrail_token_enforcement_mode, "value", guardrail_token_enforcement_mode)
    if input_is_conversation and mode == GuardrailTokenEnforcementMode.enforce.value:
        err.add(
            "guardrail_token_enforcement_mode",
            "conversational agent types cannot use hard token enforcement",
            "Use 'observe' mode for conversational input types.",
        )
    if err.problems:
        raise err


def _validate_conversational_output_conflict(input_type: Any, output_data_type_id: Any) -> None:
    """Mirror the REST rule: conversational agent types cannot take typed outputs."""
    from app.db.models.agents import AgentInputType

    input_is_conversation = (input_type == AgentInputType.conversation) or (
        getattr(input_type, "value", input_type) == "conversation"
    )
    if input_is_conversation and output_data_type_id is not None:
        raise structured_error(
            "output_data_type_id",
            "cannot be set when input_type is 'conversation'",
            "Conversational agent types do not support typed outputs — "
            "omit output_data_type_id or change input_type.",
        )


def _validate_data_type_fields(fields: Any, field_name: str = "fields") -> None:
    """Mirror the REST DataTypeCreate/Update field contract: ≥1 field, no
    duplicate field names — structured errors."""
    if not isinstance(fields, list) or len(fields) == 0:
        raise structured_error(
            field_name,
            "at least one field definition is required",
            "Provide a non-empty JSON array of {name, type, ...} field definitions "
            "(type is one of: string, number, boolean, date, enum).",
        )
    names = [str(f.get("name", "")).strip() if isinstance(f, dict) else str(getattr(f, "name", "")).strip() for f in fields]
    duplicates = sorted({n for n in names if names.count(n) > 1 and n})
    if duplicates:
        raise structured_error(
            field_name,
            f"duplicate field names not allowed: {', '.join(duplicates)}",
            "Give every field definition a unique name.",
        )


async def _validate_sop_steps(
    db: AsyncSession, steps_raw: Any, tenant_id: Any, validator: PayloadValidator
) -> list[dict[str, Any]]:
    """Validate + resolve a typed SOP ``steps`` array (resolve-before-write).

    Mirrors the REST ``SopStepCreate`` contract (``PUT /sops/{id}/steps``):
    each step carries an integer ``order``, a ``step_type`` enum
    (skill_invocation | agent_delegation) and per-type required references —
    ``skill_id`` (id-or-name, tenant-scoped) for skill_invocation steps,
    ``target_agent_type_id`` (id-or-name) for agent_delegation steps.  The
    skill_id-XOR-target invariant is enforced with a structured error naming
    the requirement; unknown per-step fields are rejected.  The whole list
    resolves before any row is written, so an unknown reference aborts the
    call with no partial write.
    """
    from app.db.models.agents import AgentType
    from app.db.models.skills import SopStepType, Skill

    if not isinstance(steps_raw, list):
        raise structured_error(
            "steps",
            "must be a list of step objects",
            "Provide a JSON array of {order, step_type, ...} step definitions "
            "(step_type is one of: skill_invocation, agent_delegation).",
        )
    step_allowed = {"order", "step_type", "skill_id", "target_agent_type_id", "step_config", "name", "description"}
    resolved: list[dict[str, Any]] = []
    for idx, raw in enumerate(steps_raw):
        field = f"steps[{idx}]"
        if not isinstance(raw, dict):
            raise structured_error(
                field,
                "must be a step object",
                f"Each step accepts: {', '.join(sorted(step_allowed))}.",
            )
        unknown = sorted(k for k in raw if k not in step_allowed)
        if unknown:
            raise structured_error(
                field,
                f"unknown field(s): {', '.join(unknown)}",
                f"Each step accepts: {', '.join(sorted(step_allowed))}.",
            )
        order = validator.coerce_int(raw.get("order"), f"{field}.order")
        if order is None:
            raise structured_error(
                f"{field}.order",
                "is required",
                "Provide the step's integer position in the ordered list.",
            )
        step_type = validator.coerce_enum(
            SopStepType, raw.get("step_type", "skill_invocation"), f"{field}.step_type"
        )
        if step_type == SopStepType.skill_invocation:
            if raw.get("target_agent_type_id") is not None:
                raise structured_error(
                    f"{field}.target_agent_type_id",
                    "is not allowed on a skill_invocation step",
                    "skill_invocation steps require skill_id (skill id or exact name); "
                    "use step_type 'agent_delegation' with target_agent_type_id to delegate to an agent.",
                )
            skill_id = await validator.resolve_fk(
                Skill,
                raw.get("skill_id"),
                f"{field}.skill_id",
                "skill",
                required=True,
                discovery_hint="Create the skill first (create_skill) or reference it by its exact name.",
            )
            resolved.append(
                {
                    "order": order,
                    "step_type": step_type,
                    "skill_id": skill_id,
                    "target_agent_type_id": None,
                    "step_config": raw.get("step_config"),
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                }
            )
        else:  # agent_delegation
            if raw.get("skill_id") is not None:
                raise structured_error(
                    f"{field}.skill_id",
                    "is not allowed on an agent_delegation step",
                    "agent_delegation steps require target_agent_type_id (agent type id or exact name); "
                    "use step_type 'skill_invocation' with skill_id to invoke a skill.",
                )
            target_agent_type_id = await validator.resolve_fk(
                AgentType,
                raw.get("target_agent_type_id"),
                f"{field}.target_agent_type_id",
                "agent type",
                required=True,
                discovery_hint="Delegation steps target an existing agent type by id or exact name.",
            )
            resolved.append(
                {
                    "order": order,
                    "step_type": step_type,
                    "skill_id": None,
                    "target_agent_type_id": target_agent_type_id,
                    "step_config": raw.get("step_config"),
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                }
            )
    return resolved


async def _write_sop_steps(db: AsyncSession, sop_id: Any, resolved_steps: list[dict[str, Any]]) -> None:
    """Replace a SOP's full ordered step list (same semantics as the REST
    ``PUT /sops/{id}/steps``) and invalidate the shared permission manager
    cache for every role bound to the SOP — delegation steps change which
    agent types a role's agents may reach, so cached permission decisions
    must be dropped.
    """
    from app.db.models.agents import AgentRoleSOP
    from app.db.models.skills import SopStep
    from app.services.agents.permission_manager import get_shared_permission_manager

    await db.execute(delete(SopStep).where(SopStep.sop_id == sop_id))
    for step in resolved_steps:
        db.add(SopStep(sop_id=sop_id, **step))
    await db.flush()
    role_rows = await db.execute(
        select(AgentRoleSOP.role_id).where(AgentRoleSOP.sop_id == sop_id)
    )
    pm = get_shared_permission_manager()
    for role_id in role_rows.scalars().all():
        pm.invalidate(role_id)


async def _build_create(
    db: AsyncSession, resource: str, model: Any, name: str, data: dict[str, Any], tenant_id: Any, user_sub: str
) -> Any:
    """Construct the ORM instance for a create (no sensitive fields echoed).

    Runs every payload through the shared payload validator: unknown-field
    rejection, enum coercion with valid values in the error, tenant-scoped
    id-or-name FK resolution (resolve-before-write), and structured errors.
    """
    validator = PayloadValidator(db, tenant_id)
    PayloadValidator.reject_unknown(
        data, _ALLOWED_CREATE_FIELDS.get(resource, set()), f"create_{_singular(resource)}"
    )
    description = data.get("description")
    is_active_raw = validator.coerce_bool(data.get("is_active", True), "is_active")
    is_active = True if is_active_raw is None else is_active_raw
    name_field = _MODELS[resource][1]
    if resource in _SLUG_PATTERN_RESOURCES and name_field == "name":
        validator.check_slug_pattern(name, "name")

    if resource == "skills":
        return model(
            tenant_id=tenant_id, name=name, description=description,
            instructions=data.get("instructions"), is_active=is_active,
        )
    if resource == "sops":
        return model(
            tenant_id=tenant_id, name=name, description=description,
            instructions=data.get("instructions"), is_active=is_active,
        )
    if resource == "agent_types":
        from app.db.models.agents import (
            AgentIdentity,
            AgentInputType,
            AgentOutputType,
            AgentRole,
            AgentType,
        )
        from app.db.models.agent_data_type import AgentDataType

        identity_id = await validator.resolve_fk(
            AgentIdentity, data.get("identity_id"), "identity_id", "agent identity"
        )
        role_id = await validator.resolve_fk(AgentRole, data.get("role_id"), "role_id", "agent role")
        output_data_type_id = await validator.resolve_fk(
            AgentDataType, data.get("output_data_type_id"), "output_data_type_id", "data type"
        )
        input_type = validator.coerce_enum(
            AgentInputType, data.get("input_type", "none"), "input_type", default=AgentInputType.none
        )
        output_type = validator.coerce_enum(
            AgentOutputType, data.get("output_type", "auto"), "output_type", default=AgentOutputType.auto
        )
        _validate_conversational_output_conflict(input_type, output_data_type_id)
        guardrails = _coerce_guardrail_fields(validator, data, default_iterations=10)
        _validate_guardrails_structured(
            input_type=input_type,
            guardrail_max_iterations=guardrails["guardrail_max_iterations"],
            guardrail_max_delegation_depth=guardrails["guardrail_max_delegation_depth"],
            guardrail_max_delegated_steps=guardrails["guardrail_max_delegated_steps"],
            guardrail_execution_timeout_seconds=guardrails["guardrail_execution_timeout_seconds"],
            guardrail_token_budget=guardrails["guardrail_token_budget"],
            guardrail_token_enforcement_mode=guardrails["guardrail_token_enforcement_mode"],
        )
        if "input_schema" in data and data["input_schema"] is not None and not isinstance(data["input_schema"], dict):
            raise structured_error(
                "input_schema", "must be a JSON object", "Provide a JSON object schema or omit it."
            )
        if "output_schema" in data and data["output_schema"] is not None and not isinstance(data["output_schema"], dict):
            raise structured_error(
                "output_schema", "must be a JSON object", "Provide a JSON object schema or omit it."
            )
        return model(
            tenant_id=tenant_id, name=name, description=description,
            identity_id=identity_id, role_id=role_id,
            model_id=data.get("model_id"), system_instruction=data.get("system_instruction"),
            input_type=input_type, input_schema=data.get("input_schema"),
            output_type=output_type, output_schema=data.get("output_schema"),
            output_data_type_id=output_data_type_id,
            is_active=is_active,
            guardrail_max_iterations=guardrails["guardrail_max_iterations"],
            guardrail_max_delegation_depth=guardrails["guardrail_max_delegation_depth"],
            guardrail_max_delegated_steps=guardrails["guardrail_max_delegated_steps"],
            guardrail_execution_timeout_seconds=guardrails["guardrail_execution_timeout_seconds"],
            guardrail_token_budget=guardrails["guardrail_token_budget"],
            guardrail_token_enforcement_mode=guardrails["guardrail_token_enforcement_mode"],
            guardrail_token_fallback_mode=guardrails["guardrail_token_fallback_mode"],
            guardrail_conversational_token_visibility_mode=guardrails["guardrail_conversational_token_visibility_mode"],
            guardrail_conversational_continuation_policy=guardrails["guardrail_conversational_continuation_policy"],
        )
    if resource == "agent_roles":
        return model(tenant_id=tenant_id, name=name, description=description)
    if resource == "agent_identities":
        from app.db.models.agents import AgentIdentityStatus, AgentIdentityType

        status = validator.coerce_enum(
            AgentIdentityStatus, data.get("status", "active"), "status", default=AgentIdentityStatus.active
        )
        return model(
            tenant_id=tenant_id, name=name,
            identity_type=validator.coerce_enum(
                AgentIdentityType, data.get("identity_type", "realm_user"), "identity_type"
            ),
            realm_name=data.get("realm_name"), realm_username=data.get("realm_username"),
            status=status,
        )
    if resource == "model_configs":
        from app.db.models.agents import ModelProvider

        if not data.get("provider_type"):
            raise structured_error(
                "provider_type",
                "is required",
                f"Provide one of: {', '.join(m.value for m in ModelProvider)}.",
            )
        provider_type = validator.coerce_enum(ModelProvider, data.get("provider_type"), "provider_type")
        # api_key is WRITE-ONLY: encrypted at the storage boundary (same vault
        # shape as ModelConfigService) and never echoed in any result.
        api_key = data.get("api_key")
        encrypted_api_key = None
        if api_key:
            import json

            from app.core.credential_vault import get_vault

            encrypted_api_key = get_vault().encrypt(json.dumps({"api_key": str(api_key)}))
        return model(
            tenant_id=tenant_id, display_name=name,
            provider_type=provider_type,
            api_base_url=data.get("api_base_url"),
            encrypted_api_key=encrypted_api_key,
            enabled_models=data.get("enabled_models", []),
            is_disabled=bool(data.get("is_disabled", False)),
        )
    if resource == "schedules":
        from app.db.models.agents import AgentType
        from app.db.models.scheduling import JobTargetType

        cron = data.get("cron_expression") or data.get("cron")
        if not cron:
            raise structured_error(
                "cron_expression", "is required", "Provide a cron expression (e.g. '0 9 * * *')."
            )
        target_type = validator.coerce_enum(
            JobTargetType, data.get("target_type", "agent"), "target_type", default=JobTargetType.agent
        )
        target_id = await validator.resolve_fk(
            AgentType,
            data.get("target_id") or data.get("agent_type_id"),
            "target_id",
            "target",
            discovery_hint=" For agent schedules use the agent type id or name.",
        )
        if target_id is None:
            raise structured_error(
                "target_id", "is required", "Provide the target agent type id or exact name."
            )
        if "payload" in data and data["payload"] is not None and not isinstance(data["payload"], dict):
            raise structured_error("payload", "must be a JSON object", "Provide a JSON object payload or omit it.")
        return model(
            tenant_id=tenant_id, name=name, description=description,
            cron_expression=cron,
            target_type=target_type,
            target_id=target_id, payload=data.get("payload"),
            scheduled_by_user_id=_resolve_identity_id_for_user_sub(user_sub),
        )
    if resource == "data_types":
        slug = validator.require(data.get("slug"), "slug", "Provide a URL-safe slug (lowercase letters, digits, hyphens).")
        validator.check_slug_pattern(slug, "slug")
        fields = data.get("fields", [])
        _validate_data_type_fields(fields)
        return model(
            tenant_id=tenant_id, name=name, slug=slug,
            description=description, fields=fields,
        )
    if resource == "mcp_servers":
        slug = validator.require(data.get("slug"), "slug", "Provide a URL-safe slug (lowercase letters, digits, hyphens).")
        validator.check_slug_pattern(slug, "slug")
        base_url = validator.require(
            data.get("base_url"), "base_url", "Provide the MCP server base URL (e.g. https://host/mcp)."
        )
        return model(
            tenant_id=tenant_id, name=name, slug=slug,
            description=description, base_url=base_url,
        )
    raise HTTPException(status_code=404, detail=f"Unknown management resource: {resource}")


def _singular(resource: str) -> str:
    """Plural registry key → singular family name (for messages)."""
    for singular, plural in _SINGULAR_TO_PLURAL.items():
        if plural == resource:
            return singular
    return resource


def _coerce_guardrail_fields(validator: PayloadValidator, data: dict[str, Any], *, default_iterations: int) -> dict[str, Any]:
    """Coerce the eight guardrail fields from tool data (defaults on absent)."""
    from app.db.models.agents import (
        GuardrailConversationalContinuationPolicy,
        GuardrailConversationalTokenVisibilityMode,
        GuardrailTokenEnforcementMode,
        GuardrailTokenFallbackMode,
    )

    return {
        "guardrail_max_iterations": validator.coerce_int(
            data.get("guardrail_max_iterations", default_iterations), "guardrail_max_iterations"
        ),
        "guardrail_max_delegation_depth": validator.coerce_int(
            data.get("guardrail_max_delegation_depth", 3), "guardrail_max_delegation_depth"
        ),
        "guardrail_max_delegated_steps": validator.coerce_int(
            data.get("guardrail_max_delegated_steps", 20), "guardrail_max_delegated_steps"
        ),
        "guardrail_execution_timeout_seconds": validator.coerce_int(
            data.get("guardrail_execution_timeout_seconds", 300), "guardrail_execution_timeout_seconds"
        ),
        "guardrail_token_budget": validator.coerce_int(data.get("guardrail_token_budget"), "guardrail_token_budget"),
        "guardrail_token_enforcement_mode": validator.coerce_enum(
            GuardrailTokenEnforcementMode,
            data.get("guardrail_token_enforcement_mode", "observe"),
            "guardrail_token_enforcement_mode",
            default=GuardrailTokenEnforcementMode.observe,
        ),
        "guardrail_token_fallback_mode": validator.coerce_enum(
            GuardrailTokenFallbackMode,
            data.get("guardrail_token_fallback_mode", "observe_and_log"),
            "guardrail_token_fallback_mode",
            default=GuardrailTokenFallbackMode.observe_and_log,
        ),
        "guardrail_conversational_token_visibility_mode": validator.coerce_enum(
            GuardrailConversationalTokenVisibilityMode,
            data.get("guardrail_conversational_token_visibility_mode", "enabled"),
            "guardrail_conversational_token_visibility_mode",
            default=GuardrailConversationalTokenVisibilityMode.enabled,
        ),
        "guardrail_conversational_continuation_policy": validator.coerce_enum(
            GuardrailConversationalContinuationPolicy,
            data.get("guardrail_conversational_continuation_policy", "allow"),
            "guardrail_conversational_continuation_policy",
            default=GuardrailConversationalContinuationPolicy.allow,
        ),
    }


def _resolve_identity_id_for_user_sub(user_sub: str) -> uuid.UUID | None:
    """Best-effort identity id for schedule provenance (never fatal)."""
    return None


async def _post_create_side_effects(db: AsyncSession, resource: str, obj: Any) -> None:
    """Best-effort side effects after a successful create."""
    if resource != "schedules":
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.scheduling.scheduler import get_scheduling_engine

        engine = get_scheduling_engine()
        scheduler_job_id = await engine.add_job(obj, AsyncSessionLocal)
        obj.scheduler_job_id = scheduler_job_id
        await db.flush()
    except Exception:  # noqa: BLE001 — schedule persists even if APScheduler is unavailable
        logger.warning("Failed to register schedule %s with the scheduler", obj.id)


async def _update_resource(
    db: AsyncSession, resource: str, args: dict[str, Any], tenant_id: Any
) -> dict[str, Any]:
    model, name_field = _import_model(resource)
    serializer = _SERIALIZERS[resource]
    obj_id = _parse_uuid(args.get("id"))
    if obj_id is None:
        raise _validation_error(structured_error("id", "is required", "Provide the record id (get or list first to find it)."))
    obj = (
        await db.execute(select(model).where(model.id == obj_id, model.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")

    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    try:
        await _apply_update(db, resource, obj, args, data, tenant_id)
    except ManagementValidationError as exc:
        raise _validation_error(exc) from exc
    except ReferenceNotFoundError as exc:
        raise _reference_error(exc) from exc
    # Agent types: skill_ids / sop_ids ADD bindings (additive merge, never a
    # replacement — existing bindings are never silently removed).  Resolution
    # happens before any row is added: unknown id/name → 404, no partial write.
    if resource == "agent_types":
        await _bind_agent_type_capabilities(db, obj, data, tenant_id)
    # Roles: skill_ids / sop_ids ADD grants (additive merge, never a removal
    # — FIX-20261031-131030).  Same resolve-before-write discipline.
    if resource == "agent_roles":
        await _bind_agent_role_capabilities(db, obj, data, tenant_id)
    # Roles: MCP session mappings + default-mapping rules (task 3.6).  Same
    # resolve-before-write discipline; structured 404/400/409 on bad input.
    role_mcp_warnings: list[str] = []
    role_auto_mapped: list[str] = []
    if resource == "agent_roles":
        try:
            role_mcp_warnings, role_auto_mapped = await _bind_agent_role_mcp_sessions(
                db, obj, data, tenant_id
            )
        except ManagementValidationError as exc:
            raise _validation_error(exc) from exc
        except ReferenceNotFoundError as exc:
            raise _reference_error(exc) from exc
    # Skills: tool_ids / tool_names ADD bindings (additive merge, never a
    # removal — FIX-20261101-000319).  Same resolve-before-write discipline.
    if resource == "skills":
        await _bind_skill_tools(db, obj, data, tenant_id)
    await _post_update_side_effects(db, resource, obj)
    await db.flush()
    await db.commit()
    refreshed_stmt = select(model).where(model.id == obj.id)
    for option in _eager_load_options(resource):
        refreshed_stmt = refreshed_stmt.options(option)
    refreshed = (await db.execute(refreshed_stmt)).scalar_one()
    record = serializer(refreshed)
    result: dict[str, Any] = {"record": record}
    if resource == "agent_roles":
        if role_mcp_warnings:
            result["warnings"] = result.get("warnings", []) + role_mcp_warnings
        if role_auto_mapped:
            result["auto_mapped_mcp_sessions"] = role_auto_mapped
    if resource == "skills":
        await _attach_skill_tool_bindings(db, [record], tenant_id)
        # FIX-20261101-223511: an update that TOUCHED tools but left the
        # skill with zero bindings is almost certainly a mistake — warn
        # (non-fatal) so the assistant can self-correct.
        if ("tool_ids" in data or "tool_names" in data) and (
            await _count_skill_bindings(db, obj.id) == 0
        ):
            result["warnings"] = [ZERO_BINDING_WARNING]
    return result


async def _apply_update(
    db: AsyncSession, resource: str, obj: Any, args: dict[str, Any], data: dict[str, Any], tenant_id: Any
) -> None:
    """Apply allowed update fields (never sensitive fields are echoed).

    Full UI-parity field sets per the parity matrix; every payload runs
    through the shared validator (unknown-field rejection, enum coercion,
    tenant-scoped id-or-name FK resolution) with structured errors.
    """
    validator = PayloadValidator(db, tenant_id)
    PayloadValidator.reject_unknown(
        data, _ALLOWED_UPDATE_FIELDS.get(resource, set()), f"update_{_singular(resource)}"
    )

    if "description" in data:
        obj.description = data["description"]
    if resource == "skills" or resource == "sops":
        if "instructions" in data:
            obj.instructions = data["instructions"]
        if "is_active" in data:
            obj.is_active = bool(validator.coerce_bool(data["is_active"], "is_active"))
        # SOP steps: presence = FULL REPLACEMENT of the ordered step list
        # (same semantics as REST PUT /sops/{id}/steps); absence leaves the
        # steps untouched.  Resolve-before-write, then delete + recreate, then
        # invalidate the permission cache of every role bound to the SOP.
        if resource == "sops" and "steps" in data:
            resolved = await _validate_sop_steps(db, data["steps"], tenant_id, validator)
            await _write_sop_steps(db, obj.id, resolved)
    elif resource == "agent_types":
        from app.db.models.agents import (
            AgentIdentity,
            AgentInputType,
            AgentOutputType,
            AgentRole,
        )
        from app.db.models.agent_data_type import AgentDataType

        if "identity_id" in data:
            obj.identity_id = await validator.resolve_fk(
                AgentIdentity, data["identity_id"], "identity_id", "agent identity"
            )
        if "role_id" in data:
            obj.role_id = await validator.resolve_fk(AgentRole, data["role_id"], "role_id", "agent role")
        if "output_data_type_id" in data:
            obj.output_data_type_id = await validator.resolve_fk(
                AgentDataType, data["output_data_type_id"], "output_data_type_id", "data type"
            )
        if "model_id" in data:
            obj.model_id = data["model_id"]
        if "system_instruction" in data:
            obj.system_instruction = data["system_instruction"]
        if "input_schema" in data:
            if data["input_schema"] is not None and not isinstance(data["input_schema"], dict):
                raise structured_error(
                    "input_schema", "must be a JSON object", "Provide a JSON object schema or omit it."
                )
            obj.input_schema = data["input_schema"]
        if "output_schema" in data:
            if data["output_schema"] is not None and not isinstance(data["output_schema"], dict):
                raise structured_error(
                    "output_schema", "must be a JSON object", "Provide a JSON object schema or omit it."
                )
            obj.output_schema = data["output_schema"]
        effective_input_type = obj.input_type
        if "input_type" in data:
            obj.input_type = validator.coerce_enum(AgentInputType, data["input_type"], "input_type")
            effective_input_type = obj.input_type
        effective_output_data_type_id = obj.output_data_type_id
        _validate_conversational_output_conflict(effective_input_type, effective_output_data_type_id)
        if "output_type" in data:
            obj.output_type = validator.coerce_enum(AgentOutputType, data["output_type"], "output_type")
        if "is_active" in data:
            obj.is_active = bool(validator.coerce_bool(data["is_active"], "is_active"))
        # Guardrails: contract validation against the EFFECTIVE configuration
        # (provided values on top of current stored values) — mirrors REST.
        guardrail_keys = [k for k in _ALLOWED_UPDATE_FIELDS["agent_types"] if k.startswith("guardrail_")]
        if any(k in data for k in guardrail_keys):
            provided = {k: data[k] for k in guardrail_keys if k in data}
            coerced = _coerce_guardrail_fields(validator, provided, default_iterations=obj.guardrail_max_iterations)
            effective = {
                "guardrail_max_iterations": coerced["guardrail_max_iterations"] if "guardrail_max_iterations" in provided else obj.guardrail_max_iterations,
                "guardrail_max_delegation_depth": coerced["guardrail_max_delegation_depth"] if "guardrail_max_delegation_depth" in provided else obj.guardrail_max_delegation_depth,
                "guardrail_max_delegated_steps": coerced["guardrail_max_delegated_steps"] if "guardrail_max_delegated_steps" in provided else obj.guardrail_max_delegated_steps,
                "guardrail_execution_timeout_seconds": coerced["guardrail_execution_timeout_seconds"] if "guardrail_execution_timeout_seconds" in provided else obj.guardrail_execution_timeout_seconds,
                "guardrail_token_budget": coerced["guardrail_token_budget"] if "guardrail_token_budget" in provided else obj.guardrail_token_budget,
                "guardrail_token_enforcement_mode": coerced["guardrail_token_enforcement_mode"] if "guardrail_token_enforcement_mode" in provided else obj.guardrail_token_enforcement_mode,
            }
            _validate_guardrails_structured(
                input_type=effective_input_type,
                **effective,
            )
            for key, value in coerced.items():
                if key in provided:
                    setattr(obj, key, value)
    elif resource == "agent_identities":
        from app.db.models.agents import AgentIdentityStatus, AgentRole

        if "realm_name" in data:
            obj.realm_name = data["realm_name"]
        if "realm_username" in data:
            obj.realm_username = data["realm_username"]
        if "status" in data:
            obj.status = validator.coerce_enum(AgentIdentityStatus, data["status"], "status")
        # Role assignment (mapped from the REST /identities/{id}/roles concern):
        # id-or-name, ADDITIVE merge (duplicates skipped, mirrors
        # IdentityService.assign_roles), resolved BEFORE any write.
        if "role_ids" in data:
            resolved = await validator.resolve_fk_list(AgentRole, data["role_ids"], "role_ids", "agent role")
            from app.db.models.agents import AgentRoleIdentity

            existing = set(
                (
                    await db.execute(
                        select(AgentRoleIdentity.role_id).where(AgentRoleIdentity.identity_id == obj.id)
                    )
                ).scalars()
            )
            for role_id in resolved:
                if role_id in existing:  # idempotent no-op
                    continue
                db.add(AgentRoleIdentity(identity_id=obj.id, role_id=role_id))
    elif resource == "model_configs":
        from app.db.models.agents import ModelProvider

        if "display_name" in data and data["display_name"]:
            obj.display_name = str(data["display_name"])
        if "provider_type" in data:
            obj.provider_type = validator.coerce_enum(ModelProvider, data["provider_type"], "provider_type")
        if "api_base_url" in data:
            obj.api_base_url = data["api_base_url"]
        if "enabled_models" in data:
            obj.enabled_models = data["enabled_models"]
        if "is_disabled" in data:
            obj.is_disabled = bool(validator.coerce_bool(data["is_disabled"], "is_disabled"))
        # api_key is WRITE-ONLY (omit = unchanged, mirrors ModelConfigUpdate):
        # encrypted at the storage boundary, never echoed.
        if data.get("api_key"):
            import json

            from app.core.credential_vault import get_vault

            obj.encrypted_api_key = get_vault().encrypt(json.dumps({"api_key": str(data["api_key"])}))
    elif resource == "schedules":
        if "cron_expression" in data:
            cron = data["cron_expression"]
            if not cron or not str(cron).strip():
                raise structured_error(
                    "cron_expression", "must not be empty", "Provide a cron expression (e.g. '0 9 * * *')."
                )
            old_scheduler_job_id = obj.scheduler_job_id
            old_cron = obj.cron_expression
            obj.cron_expression = cron
            # Mark for scheduler re-registration when the cron actually
            # changed (best-effort swap in _post_update_side_effects).
            obj._cron_changed = bool(old_scheduler_job_id) and cron != old_cron
            obj._old_scheduler_job_id = old_scheduler_job_id
        if "payload" in data:
            if data["payload"] is not None and not isinstance(data["payload"], dict):
                raise structured_error("payload", "must be a JSON object", "Provide a JSON object payload or omit it.")
            obj.payload = data["payload"]
    elif resource == "data_types":
        if "fields" in data:
            _validate_data_type_fields(data["fields"])
            obj.fields = data["fields"]
    elif resource == "mcp_servers":
        if "base_url" in data:
            if not data["base_url"] or not str(data["base_url"]).strip():
                raise structured_error(
                    "base_url", "must not be empty", "Provide the MCP server base URL."
                )
            obj.base_url = data["base_url"]
    # Common: allow renaming via the top-level "name" argument (or data.name).
    new_name = args.get("name") or data.get("name")
    if new_name:
        new_name = str(new_name).strip()
        name_field = _MODELS[resource][1]
        if resource in _SLUG_PATTERN_RESOURCES and name_field == "name":
            validator.check_slug_pattern(new_name, "name")
        if resource == "model_configs":
            obj.display_name = new_name
        else:
            setattr(obj, "name", new_name)


async def _post_update_side_effects(db: AsyncSession, resource: str, obj: Any) -> None:
    """Best-effort side effects after a successful update.

    Schedules: when the cron expression changed and the job was registered,
    swap the APScheduler registration (remove old trigger, add the new one).
    """
    if resource != "schedules":
        return
    old_job_id = getattr(obj, "_old_scheduler_job_id", None)
    cron_changed = getattr(obj, "_cron_changed", False)
    if not (cron_changed and old_job_id):
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.scheduling.scheduler import get_scheduling_engine

        engine = get_scheduling_engine()
        try:
            await engine.remove_job(old_job_id)
        except Exception:  # noqa: BLE001 — stale registration is non-fatal
            logger.info("Old scheduler registration %s already gone", old_job_id)
        scheduler_job_id = await engine.add_job(obj, AsyncSessionLocal)
        obj.scheduler_job_id = scheduler_job_id
        await db.flush()
    except Exception:  # noqa: BLE001 — schedule persists even if APScheduler is unavailable
        logger.warning("Failed to re-register schedule %s with the scheduler", obj.id)
    finally:
        # Never leak the transient markers onto the ORM object.
        for marker in ("_cron_changed", "_old_scheduler_job_id"):
            try:
                delattr(obj, marker)
            except AttributeError:
                pass


# ── Agent-type skill/SOP binding helpers (FIX-20261031-071721) ──────────────


async def _resolve_capability_ids(
    db: AsyncSession, tenant_id: Any, values: Any, kind: str
) -> list[uuid.UUID]:
    """Resolve a list of skill/SOP id-or-name values to tenant-scoped UUIDs.

    Accepts raw UUIDs (id lookup) or names (name lookup), mirroring the rest
    of the toolset's id-or-name resolution.  Every value must exist within
    the calling tenant — anything else raises a structured 404 with a clear
    message (the caller resolves the WHOLE set before writing, so an unknown
    value never leaves a partial write behind).
    """
    from app.db.models.skills import Skill, Sop

    model = Skill if kind == "skill" else Sop
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail=f"{kind}_ids must be a list of ids or names")
    resolved: list[uuid.UUID] = []
    for raw in values:
        raw_str = str(raw).strip()
        if not raw_str:
            continue
        stmt = select(model).where(model.tenant_id == tenant_id)
        obj_id = _parse_uuid(raw_str)
        if obj_id is not None:
            stmt = stmt.where(model.id == obj_id)
        else:
            stmt = stmt.where(model.name == raw_str)
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"{kind} not found in this workspace: '{raw_str}'. Create "
                    f"the {kind} first (create_{kind}) or use its exact id/name."
                ),
            )
        resolved.append(row.id)
    return resolved


async def _bind_agent_type_capabilities(
    db: AsyncSession, agent_type: Any, data: dict[str, Any], tenant_id: Any
) -> None:
    """Apply ``skill_ids`` / ``sop_ids`` from tool data onto an agent type.

    Semantics (ADDITIVE MERGE — documented in the tool schema descriptions):
    the provided skills/SOPs are ADDED to the agent type's existing binding
    set.  Existing bindings are NEVER silently removed — the management
    toolset has no delete verb and stays non-destructive.  Re-binding an
    already-bound pair is an idempotent no-op success.  New bindings follow
    the ``order`` convention (0-based, appended after the current maximum).
    """
    from app.db.models.agents import AgentTypeSkillBinding, AgentTypeSopBinding

    if "skill_ids" not in data and "sop_ids" not in data:
        return

    # Resolve everything FIRST — unknown values abort with 404 before any
    # binding row is added (no partial write).
    skill_ids: list[uuid.UUID] = []
    sop_ids: list[uuid.UUID] = []
    if "skill_ids" in data:
        skill_ids = await _resolve_capability_ids(db, tenant_id, data["skill_ids"], "skill")
    if "sop_ids" in data:
        sop_ids = await _resolve_capability_ids(db, tenant_id, data["sop_ids"], "sop")

    if skill_ids:
        existing = set(
            (
                await db.execute(
                    select(AgentTypeSkillBinding.skill_id).where(
                        AgentTypeSkillBinding.agent_type_id == agent_type.id
                    )
                )
            ).scalars()
        )
        next_order = (
            (
                await db.execute(
                    select(func.max(AgentTypeSkillBinding.order)).where(
                        AgentTypeSkillBinding.agent_type_id == agent_type.id
                    )
                )
            ).scalar()
            or -1
        ) + 1
        for skill_id in skill_ids:
            if skill_id in existing:  # idempotent no-op
                continue
            db.add(
                AgentTypeSkillBinding(
                    agent_type_id=agent_type.id, skill_id=skill_id, order=next_order
                )
            )
            next_order += 1

    if sop_ids:
        existing = set(
            (
                await db.execute(
                    select(AgentTypeSopBinding.sop_id).where(
                        AgentTypeSopBinding.agent_type_id == agent_type.id
                    )
                )
            ).scalars()
        )
        next_order = (
            (
                await db.execute(
                    select(func.max(AgentTypeSopBinding.order)).where(
                        AgentTypeSopBinding.agent_type_id == agent_type.id
                    )
                )
            ).scalar()
            or -1
        ) + 1
        for sop_id in sop_ids:
            if sop_id in existing:  # idempotent no-op
                continue
            db.add(
                AgentTypeSopBinding(
                    agent_type_id=agent_type.id, sop_id=sop_id, order=next_order
                )
            )
            next_order += 1


async def _bind_agent_role_capabilities(
    db: AsyncSession, agent_role: Any, data: dict[str, Any], tenant_id: Any
) -> None:
    """Apply ``skill_ids`` / ``sop_ids`` from tool data onto an agent role.

    Role-based agents resolve their runtime tool access from the ROLE's
    skill/SOP assignments (``AgentRoleSkill`` / ``AgentRoleSOP``), so granting
    the skill to the agent's role is what makes it accessible at runtime.

    Semantics (ADDITIVE MERGE — documented in the tool schema descriptions):
    provided skills/SOPs are ADDED to the role's existing grant set; existing
    grants are NEVER silently removed (the management toolset has no delete
    verb and stays non-destructive); re-granting an already-granted pair is an
    idempotent no-op success.  All identifiers are resolved BEFORE rows are
    added — an unknown id/name raises a structured 404 with an actionable
    message and leaves no partial write behind.
    """
    from app.db.models.agents import AgentRoleSkill, AgentRoleSOP

    if "skill_ids" not in data and "sop_ids" not in data:
        return

    # Resolve everything FIRST — unknown values abort with 404 before any
    # grant row is added (no partial write).
    skill_ids: list[uuid.UUID] = []
    sop_ids: list[uuid.UUID] = []
    if "skill_ids" in data:
        skill_ids = await _resolve_capability_ids(db, tenant_id, data["skill_ids"], "skill")
    if "sop_ids" in data:
        sop_ids = await _resolve_capability_ids(db, tenant_id, data["sop_ids"], "sop")

    if skill_ids:
        existing = set(
            (
                await db.execute(
                    select(AgentRoleSkill.skill_id).where(
                        AgentRoleSkill.role_id == agent_role.id
                    )
                )
            ).scalars()
        )
        for skill_id in skill_ids:
            if skill_id in existing:  # idempotent no-op
                continue
            db.add(AgentRoleSkill(role_id=agent_role.id, skill_id=skill_id))

    if sop_ids:
        existing = set(
            (
                await db.execute(
                    select(AgentRoleSOP.sop_id).where(
                        AgentRoleSOP.role_id == agent_role.id
                    )
                )
            ).scalars()
        )
        for sop_id in sop_ids:
            if sop_id in existing:  # idempotent no-op
                continue
            db.add(AgentRoleSOP(role_id=agent_role.id, sop_id=sop_id))


async def _resolve_mcp_session_for_server(
    db: AsyncSession, server: Any, raw: Any, field: str
) -> Any:
    """Resolve an MCP session id-or-name scoped to a known server.

    Session names are only unique PER SERVER (uq_mcp_session_server_name), so
    the name is resolved against the given server, never globally.  A
    UUID-shaped value is resolved by id (and still validated to belong to the
    server by the caller).
    """
    from app.db.models.mcp_hub import McpSession

    raw_str = str(raw or "").strip()
    if not raw_str:
        raise structured_error(field, "is required", "Provide the MCP session id or exact name.")
    if is_uuid_shaped(raw_str):
        session = (
            await db.execute(select(McpSession).where(McpSession.id == uuid.UUID(raw_str)))
        ).scalar_one_or_none()
        if session is None:
            raise ReferenceNotFoundError(f"MCP session '{raw_str}' was not found.")
        return session
    from app.db.models.mcp_hub import McpSession, McpSessionAuthType

    raw_str = str(raw or "").strip()
    if not raw_str:
        raise structured_error(field, "is required", "Provide the MCP session id or exact name.")
    if is_uuid_shaped(raw_str):
        session = (
            await db.execute(select(McpSession).where(McpSession.id == uuid.UUID(raw_str)))
        ).scalar_one_or_none()
        if session is None:
            raise ReferenceNotFoundError(f"MCP session '{raw_str}' was not found.")
        return session
    session = (
        await db.execute(
            select(McpSession).where(McpSession.server_id == server.id, McpSession.name == raw_str)
        )
    ).scalar_one_or_none()
    if session is None:
        available = await _describe_server_sessions(db, server.id)
        # The name may actually be an auth TYPE (e.g. 'passthrough') — a common
        # model mistake.  If it matches an auth-type value (case-insensitive),
        # resolve by auth_type on this server instead of failing outright.
        auth_match = next(
            (a for a in McpSessionAuthType if a.value.lower() == raw_str.lower()),
            None,
        )
        if auth_match is not None:
            candidates = (
                await db.execute(
                    select(McpSession)
                    .where(
                        McpSession.server_id == server.id,
                        McpSession.auth_type == auth_match,
                        McpSession.is_active.is_(True),
                    )
                    .order_by(McpSession.is_default.desc(), McpSession.created_at)
                )
            ).scalars().all()
            if candidates:
                return candidates[0]
            raise ReferenceNotFoundError(
                f"MCP session '{raw_str}' was not found on MCP server '{server.name}'. "
                f"'{raw_str}' is an auth TYPE, not a session name, and this server has no "
                f"active session with '{auth_match.value}' auth. {available}"
            )
        raise ReferenceNotFoundError(
            f"MCP session '{raw_str}' was not found on MCP server '{server.name}'. {available}"
        )
    return session


async def _describe_server_sessions(db: AsyncSession, server_id: Any) -> str:
    """Human-readable list of a server's active sessions (name + auth type)."""
    from app.db.models.mcp_hub import McpSession

    rows = (
        await db.execute(
            select(McpSession)
            .where(McpSession.server_id == server_id, McpSession.is_active.is_(True))
            .order_by(McpSession.is_default.desc(), McpSession.created_at)
        )
    ).scalars().all()
    if not rows:
        return "This MCP server has no active sessions."
    listed = ", ".join(f"{s.name} ({s.auth_type.value})" for s in rows)
    return f"Available sessions on this server: {listed}. " \
        "'passthrough' is an auth TYPE, not a session name."


async def _bind_agent_role_mcp_sessions(
    db: AsyncSession, agent_role: Any, data: dict[str, Any], tenant_id: Any
) -> tuple[list[str], list[str]]:
    """Apply ``mcp_session_mappings`` + the default-mapping rules to a role.

    MCP tools only work for an agent if its role has an MCP session mapped
    for every MCP server the role's skills touch.  Semantics:

    - Explicit ``mcp_session_mappings`` (``[{server, session}]``, both
      id-or-name) are ADDITIVE: they add mappings, never remove existing
      ones.  The session must belong to the named server (structured error
      otherwise); one session per (role, server) — re-sending the same pair
      is an idempotent no-op, mapping the server to a DIFFERENT session is a
      409 conflict (the toolset has no delete verb and never silently
      re-points credentials).
    - Default rules then run over the role's FULL effective MCP server set
      (role skills → skill tool bindings → tools' servers): an unmapped
      server with a passthrough session is AUTO-mapped to it; an unmapped
      server with exactly one active session is AUTO-mapped to it; an
      unmapped server with multiple non-passthrough sessions is AUTO-mapped
      to the FIRST one (deterministic order: ``is_default`` DESC, then
      ``created_at`` ASC) and a structured WARNING is returned telling the
      assistant to CONFIRM the choice with the user (listing alternative
      sessions for re-mapping).  Every server is always mapped — ambiguity
      becomes a confirm-with-user warning, never a blocking question.

    Returns ``(warnings, auto_mapped_descriptions)``.
    """
    from app.db.models.agents import AgentRoleMcpSession, AgentRoleSkill
    from app.db.models.mcp_hub import McpSession, McpSessionAuthType, McpServer
    from app.db.models.skills import SkillToolBinding
    from app.db.models.skills import SkillToolBinding
    from app.db.models.mcp_hub import McpTool

    validator = PayloadValidator(db, tenant_id)
    warnings: list[str] = []
    auto_mapped: list[str] = []

    # Existing (role, server) → session map.
    mapped: dict[uuid.UUID, uuid.UUID] = {}
    existing_rows = (
        await db.execute(
            select(AgentRoleMcpSession).where(AgentRoleMcpSession.role_id == agent_role.id)
        )
    ).scalars().all()
    for row in existing_rows:
        mapped[row.server_id] = row.mcp_session_id

    # ── 1. Explicit mappings (resolve-before-write, no partial write) ──────
    if "mcp_session_mappings" in data:
        raw_list = data["mcp_session_mappings"]
        if not isinstance(raw_list, list):
            raise structured_error(
                "mcp_session_mappings",
                "must be a list",
                "Provide a list of {server, session} objects (ids or names).",
            )
        provided_servers: set[uuid.UUID] = set()
        for idx, item in enumerate(raw_list):
            field = f"mcp_session_mappings[{idx}]"
            if not isinstance(item, dict) or not item.get("server") or not item.get("session"):
                raise structured_error(
                    field,
                    "must be an object with 'server' and 'session'",
                    "Provide {\"server\": <id-or-name>, \"session\": <id-or-name>}.",
                )
            server_id_resolved = await validator.resolve_fk(
                McpServer, item["server"], f"{field}.server", "MCP server"
            )
            server = (
                await db.execute(select(McpServer).where(McpServer.id == server_id_resolved))
            ).scalar_one()
            session = await _resolve_mcp_session_for_server(
                db, server, item["session"], f"{field}.session"
            )
            if session.server_id != server.id:
                raise structured_error(
                    f"{field}.session",
                    "does not belong to the given server",
                    f"Session '{session.name}' belongs to a different MCP server; pick a "
                    "session configured on this server (see get_mcp_server).",
                )
            if server.id in provided_servers:
                raise structured_error(
                    field,
                    "names the same server twice",
                    "Send at most one explicit mapping per MCP server per call.",
                )
            provided_servers.add(server.id)
            previous = mapped.get(server.id)
            if previous is not None:
                if previous == session.id:
                    continue  # idempotent no-op
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "conflict",
                        "field": field,
                        "problem": (
                            f"role already maps MCP server '{server.name}' to another session"
                        ),
                        "remedy": (
                            "One session per server per role; existing mappings are never "
                            "silently re-pointed. Keep the existing mapping or (via the Web "
                            "UI role editor) remove it first."
                        ),
                    },
                )
            mapped[server.id] = session.id
            db.add(
                AgentRoleMcpSession(
                    role_id=agent_role.id, server_id=server.id, mcp_session_id=session.id
                )
            )

    # ── 2. Default rules over the effective MCP server set ─────────────────
    # role → AgentRoleSkill → SkillToolBinding → McpTool.server_id (the same
    # traversal the permission resolver uses at runtime).
    effective_server_ids = (
        (
            await db.execute(
                select(McpTool.server_id)
                .distinct()
                .join(SkillToolBinding, SkillToolBinding.tool_id == McpTool.id)
                .join(AgentRoleSkill, AgentRoleSkill.skill_id == SkillToolBinding.skill_id)
                .where(
                    AgentRoleSkill.role_id == agent_role.id,
                    McpTool.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for server_id in effective_server_ids:
        if server_id in mapped:
            continue
        server = (
            await db.execute(select(McpServer).where(McpServer.id == server_id))
        ).scalar_one_or_none()
        sessions = (
            (
                await db.execute(
                    select(McpSession)
                    .where(
                        McpSession.server_id == server_id, McpSession.is_active.is_(True)
                    )
                    .order_by(McpSession.is_default.desc(), McpSession.created_at)
                )
            )
            .scalars()
            .all()
        )
        server_label = server.name if server is not None else str(server_id)
        if not sessions:
            warnings.append(
                f"MCP server '{server_label}' has no sessions configured — create a session "
                "on the server (MCP Hub) before agents using this role can call its tools."
            )
            continue
        passthrough = [s for s in sessions if s.auth_type == McpSessionAuthType.passthrough]
        chosen = None
        reason = ""
        if passthrough:
            chosen = next((s for s in passthrough if s.is_default), passthrough[0])
            reason = "passthrough"
        elif len(sessions) == 1:
            chosen = sessions[0]
            reason = "only session"
        elif len(sessions) > 1:
            chosen = sessions[0]
            reason = "first of multiple (deterministic: is_default DESC, created_at ASC)"
            names = ", ".join(sorted(s.name for s in sessions))
            warnings.append(
                f"MCP server '{server_label}' has {len(sessions)} sessions; defaulted to "
                f"'{chosen.name}' ({chosen.auth_type.value}) — confirm with the user; "
                f"alternatives: {names}"
            )
        if chosen is not None:
            mapped[server_id] = chosen.id
            db.add(
                AgentRoleMcpSession(
                    role_id=agent_role.id, server_id=server_id, mcp_session_id=chosen.id
                )
            )
            auto_mapped.append(
                f"{server_label} → session {chosen.name} (auto-mapped: {reason})"
            )
            continue
    return warnings, auto_mapped


# ── Skill ↔ tool binding helpers (FIX-20261101-000319) ──────────────────────


async def _resolve_skill_tool_ids(
    db: AsyncSession, tenant_id: Any, tool_ids: Any, tool_names: Any
) -> list[uuid.UUID]:
    """Resolve ``tool_ids`` / ``tool_names`` skill data to tenant-scoped UUIDs.

    ``tool_ids`` entries are McpTool UUIDs; ``tool_names`` entries are
    canonical ``server____tool`` names (including ``cc____`` Control Center
    tools), bare original names, or UUIDs.  Every value must resolve to an
    existing McpTool row WITHIN the calling tenant — anything else raises a
    structured 404 with an actionable message.  The WHOLE set is resolved
    before any write, so an unknown value never leaves a partial write.
    """
    from app.db.models.mcp_hub import McpTool
    from app.services.agents.tool_naming import TOOL_SEPARATOR, build_tool_name

    if tool_ids is None and tool_names is None:
        return []
    if tool_ids is not None and not isinstance(tool_ids, list):
        raise HTTPException(status_code=400, detail="tool_ids must be a list of ids")
    if tool_names is not None and not isinstance(tool_names, list):
        raise HTTPException(
            status_code=400, detail="tool_names must be a list of tool names"
        )

    resolved: list[uuid.UUID] = []

    async def _by_id_str(raw_str: str) -> McpTool | None:
        obj_id = _parse_uuid(raw_str)
        if obj_id is None:
            return None
        return (
            await db.execute(
                select(McpTool).where(
                    McpTool.id == obj_id, McpTool.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()

    async def _by_name(raw_str: str) -> McpTool | None:
        candidates = [raw_str]
        if TOOL_SEPARATOR in raw_str:
            server, bare = raw_str.split(TOOL_SEPARATOR, 1)
            candidates.append(build_tool_name(server, bare))
        stmt = select(McpTool).where(
            McpTool.tenant_id == tenant_id,
            McpTool.name.in_(candidates) | McpTool.original_name.in_(candidates),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    for raw in (tool_ids or []):
        raw_str = str(raw).strip()
        if not raw_str:
            continue
        tool = await _by_id_str(raw_str)
        if tool is None:
            tool = await _by_name(raw_str)
        if tool is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"MCP tool not found in this workspace: '{raw_str}'. "
                    f"Discover available tools with get_mcp_server (its "
                    f"'tools' list) and use the exact canonical "
                    f"server____tool name or tool id."
                ),
            )
        resolved.append(tool.id)

    for raw in (tool_names or []):
        raw_str = str(raw).strip()
        if not raw_str:
            continue
        tool = await _by_name(raw_str)
        if tool is None:
            tool = await _by_id_str(raw_str)
        if tool is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"MCP tool not found in this workspace: '{raw_str}'. "
                    f"Discover available tools with get_mcp_server (its "
                    f"'tools' list) and use the exact canonical "
                    f"server____tool name (e.g. 'supabase____run_sql' or "
                    f"'cc____create_skill')."
                ),
            )
        resolved.append(tool.id)

    return resolved


async def _bind_skill_tools(
    db: AsyncSession, skill: Any, data: dict[str, Any], tenant_id: Any
) -> None:
    """Apply ``tool_ids`` / ``tool_names`` from tool data onto a skill.

    Semantics (ADDITIVE MERGE — documented in the tool schema descriptions):
    the provided MCP tools are ADDED to the skill's existing binding set.
    Existing bindings are NEVER silently removed (the management toolset
    has no delete verb and stays non-destructive); re-binding an
    already-bound tool is an idempotent no-op success.  All identifiers are
    resolved BEFORE rows are added — an unknown tool raises a structured
    404 with an actionable message and leaves no partial write behind.
    """
    from app.db.models.skills import SkillToolBinding

    if "tool_ids" not in data and "tool_names" not in data:
        return

    resolved = await _resolve_skill_tool_ids(
        db, tenant_id, data.get("tool_ids"), data.get("tool_names")
    )
    if not resolved:
        return

    existing = set(
        (
            await db.execute(
                select(SkillToolBinding.tool_id).where(
                    SkillToolBinding.skill_id == skill.id
                )
            )
        ).scalars()
    )
    next_order = (
        (
            await db.execute(
                select(func.max(SkillToolBinding.order)).where(
                    SkillToolBinding.skill_id == skill.id
                )
            )
        ).scalar()
        or -1
    ) + 1
    for tool_id in resolved:
        if tool_id in existing:  # idempotent no-op
            continue
        db.add(SkillToolBinding(skill_id=skill.id, tool_id=tool_id, order=next_order))
        next_order += 1
