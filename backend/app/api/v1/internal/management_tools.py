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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorize_identity, require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.session import get_db

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
    return _row_dict(
        id=s.id, name=s.name, description=s.description,
        instructions=s.instructions, is_active=s.is_active,
    )


def _serialize_agent_type(a) -> dict[str, Any]:
    return _row_dict(
        id=a.id, name=a.name, description=a.description,
        identity_id=str(a.identity_id) if a.identity_id else None,
        role_id=str(a.role_id) if a.role_id else None,
        model_id=a.model_id, system_instruction=a.system_instruction,
        input_type=a.input_type.value if hasattr(a.input_type, "value") else str(a.input_type),
        output_type=a.output_type.value if hasattr(a.output_type, "value") else str(a.output_type),
        is_active=a.is_active, is_system=a.is_system,
    )


def _serialize_agent_role(r) -> dict[str, Any]:
    return _row_dict(id=r.id, name=r.name, description=r.description)


def _serialize_agent_identity(i) -> dict[str, Any]:
    return _row_dict(
        id=i.id, name=i.name,
        identity_type=i.identity_type.value if hasattr(i.identity_type, "value") else str(i.identity_type),
        realm_name=i.realm_name, realm_username=i.realm_username,
        status=i.status.value if hasattr(i.status, "value") else str(i.status),
    )


def _serialize_model_config(m) -> dict[str, Any]:
    return _row_dict(
        id=m.id, display_name=m.display_name,
        provider_type=m.provider_type.value if hasattr(m.provider_type, "value") else str(m.provider_type),
        api_base_url=m.api_base_url, enabled_models=m.enabled_models, is_disabled=m.is_disabled,
    )


def _serialize_schedule(j) -> dict[str, Any]:
    return _row_dict(
        id=j.id, name=j.name, description=j.description, cron_expression=j.cron_expression,
        target_type=j.target_type.value if hasattr(j.target_type, "value") else str(j.target_type),
        target_id=str(j.target_id), payload=j.payload,
        status=j.status.value if hasattr(j.status, "value") else str(j.status),
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
        raise HTTPException(status_code=400, detail="id or name is required")
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
    name = str(args.get("name") or data.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    # Tenant-scoped uniqueness check.  Most resources are unique by display
    # name; MCP servers are unique by slug (business identity = (tenant, slug)),
    # so the duplicate probe uses the slug value there.
    unique_value = name
    if resource == "mcp_servers":
        unique_value = str(data.get("slug") or "").strip() or name
    await _check_duplicate_name(db, model, name_field, unique_value, tenant_id)

    obj = _build_create(resource, model, name, data, tenant_id, user_sub)
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

    # Best-effort side effects (e.g. scheduler registration for schedules).
    if resource == "skills":
        # Skill ↔ tool association (FIX-20261101-000319): tool_ids /
        # tool_names in data create SkillToolBinding rows.  Resolution
        # happens BEFORE any binding row is added (unknown → 404, no
        # partial write).
        await _bind_skill_tools(db, obj, data, tenant_id)

    await _post_create_side_effects(db, resource, obj)
    await db.commit()

    refreshed = (await db.execute(select(model).where(model.id == obj.id))).scalar_one()
    record = serializer(refreshed)
    result: dict[str, Any] = {"record": record}
    if resource == "skills":
        # FIX-20261101-223511: show the bound tools + guard against zero
        # bindings (non-fatal warning — the assistant self-corrects).
        await _attach_skill_tool_bindings(db, [record], tenant_id)
        if await _count_skill_bindings(db, obj.id) == 0:
            result["warnings"] = [ZERO_BINDING_WARNING]
    return result


def _coerce(enum_cls: Any, raw: Any, field: str) -> Any:
    """Coerce a raw string to a SQLAlchemy enum member (400 on invalid)."""
    if raw is None:
        return None
    try:
        return enum_cls(str(raw))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {raw}") from exc


def _build_create(
    resource: str, model: Any, name: str, data: dict[str, Any], tenant_id: Any, user_sub: str
) -> Any:
    """Construct the ORM instance for a create (no sensitive fields)."""
    description = data.get("description")
    is_active = bool(data.get("is_active", True))

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
        from app.db.models.agents import AgentInputType, AgentOutputType

        return model(
            tenant_id=tenant_id, name=name, description=description,
            model_id=data.get("model_id"), system_instruction=data.get("system_instruction"),
            input_type=_coerce(AgentInputType, data.get("input_type", "none"), "input_type"),
            output_type=_coerce(AgentOutputType, data.get("output_type", "auto"), "output_type"),
            identity_id=_parse_uuid(data.get("identity_id")),
            role_id=_parse_uuid(data.get("role_id")),
            is_active=is_active,
        )
    if resource == "agent_roles":
        return model(tenant_id=tenant_id, name=name, description=description)
    if resource == "agent_identities":
        from app.db.models.agents import AgentIdentityType

        return model(
            tenant_id=tenant_id, name=name,
            identity_type=_coerce(
                AgentIdentityType, data.get("identity_type", "realm_user"), "identity_type"
            ),
            realm_name=data.get("realm_name"), realm_username=data.get("realm_username"),
        )
    if resource == "model_configs":
        from app.db.models.agents import ModelProvider

        if not data.get("provider_type"):
            raise HTTPException(status_code=400, detail="provider_type is required")
        return model(
            tenant_id=tenant_id, display_name=name,
            provider_type=_coerce(ModelProvider, data.get("provider_type"), "provider_type"),
            api_base_url=data.get("api_base_url"),
            enabled_models=data.get("enabled_models", []),
            is_disabled=bool(data.get("is_disabled", False)),
        )
    if resource == "schedules":
        from app.db.models.scheduling import JobTargetType

        cron = data.get("cron_expression") or data.get("cron")
        if not cron:
            raise HTTPException(status_code=400, detail="cron_expression is required")
        target_type = data.get("target_type", "agent")
        target_id = _parse_uuid(data.get("target_id") or data.get("agent_type_id"))
        if target_id is None:
            raise HTTPException(status_code=400, detail="target_id is required")

        return model(
            tenant_id=tenant_id, name=name, description=description,
            cron_expression=cron,
            target_type=_coerce(JobTargetType, target_type, "target_type"),
            target_id=target_id, payload=data.get("payload"),
            scheduled_by_user_id=_resolve_identity_id_for_user_sub(user_sub),
        )
    if resource == "data_types":
        slug = str(data.get("slug") or "").strip()
        if not slug:
            raise HTTPException(status_code=400, detail="slug is required")
        return model(
            tenant_id=tenant_id, name=name, slug=slug,
            description=description, fields=data.get("fields", []),
        )
    if resource == "mcp_servers":
        slug = str(data.get("slug") or "").strip()
        if not slug:
            raise HTTPException(status_code=400, detail="slug is required")
        base_url = data.get("base_url")
        if not base_url:
            raise HTTPException(status_code=400, detail="base_url is required")
        return model(
            tenant_id=tenant_id, name=name, slug=slug,
            description=description, base_url=base_url,
        )
    raise HTTPException(status_code=404, detail=f"Unknown management resource: {resource}")


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
        raise HTTPException(status_code=400, detail="id is required")
    obj = (
        await db.execute(select(model).where(model.id == obj_id, model.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{resource[:-1]} not found")

    data = args.get("data") if isinstance(args.get("data"), dict) else {}
    _apply_update(resource, obj, args, data)
    # Agent types: skill_ids / sop_ids ADD bindings (additive merge, never a
    # replacement — existing bindings are never silently removed).  Resolution
    # happens before any row is added: unknown id/name → 404, no partial write.
    if resource == "agent_types":
        await _bind_agent_type_capabilities(db, obj, data, tenant_id)
    # Roles: skill_ids / sop_ids ADD grants (additive merge, never a removal
    # — FIX-20261031-131030).  Same resolve-before-write discipline.
    if resource == "agent_roles":
        await _bind_agent_role_capabilities(db, obj, data, tenant_id)
    # Skills: tool_ids / tool_names ADD bindings (additive merge, never a
    # removal — FIX-20261101-000319).  Same resolve-before-write discipline.
    if resource == "skills":
        await _bind_skill_tools(db, obj, data, tenant_id)
    await db.flush()
    await db.commit()
    refreshed = (await db.execute(select(model).where(model.id == obj.id))).scalar_one()
    record = serializer(refreshed)
    result: dict[str, Any] = {"record": record}
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


def _apply_update(resource: str, obj: Any, args: dict[str, Any], data: dict[str, Any]) -> None:
    """Apply allowed update fields (never sensitive fields)."""
    if "description" in data:
        obj.description = data["description"]
    if resource == "skills" or resource == "sops":
        if "instructions" in data:
            obj.instructions = data["instructions"]
        if "is_active" in data:
            obj.is_active = bool(data["is_active"])
    elif resource == "agent_types":
        if "model_id" in data:
            obj.model_id = data["model_id"]
        if "system_instruction" in data:
            obj.system_instruction = data["system_instruction"]
        if "is_active" in data:
            obj.is_active = bool(data["is_active"])
    elif resource == "model_configs":
        if "api_base_url" in data:
            obj.api_base_url = data["api_base_url"]
        if "enabled_models" in data:
            obj.enabled_models = data["enabled_models"]
        if "is_disabled" in data:
            obj.is_disabled = bool(data["is_disabled"])
    elif resource == "data_types":
        if "fields" in data:
            obj.fields = data["fields"]
    elif resource == "mcp_servers":
        if "base_url" in data:
            obj.base_url = data["base_url"]
    # Common: allow renaming via the top-level "name" argument.
    new_name = args.get("name")
    if new_name and resource != "model_configs":
        setattr(obj, "name", str(new_name))
    elif new_name and resource == "model_configs":
        obj.display_name = str(new_name)


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
