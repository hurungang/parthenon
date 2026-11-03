"""MCP Hub API routers: Server, Session, Tool management."""
import json
import os
import uuid
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission, identity_has_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_INTEGRATION_MCP_HUB, RT_INTEGRATION_CONTROL_CENTER
from app.schemas.errors import PermissionDeniedDetail, RequiredPermission
from app.db.session import DbSession
from app.db.models.mcp_hub import McpServer, McpSession, McpTool, ToolPermission, McpSessionAuthType, McpServerStatus
from app.db.models.skills import Skill, SkillToolBinding
from app.schemas.mcp_hub import (
    McpServerCreate,
    McpServerRead,
    McpServerUpdate,
    McpSessionCreate,
    McpSessionRead,
    McpSessionUpdate,
    McpToolRead,
    SyncResult,
    TestToolRequest,
    TestToolResponse,
    ToolPermissionCreate,
    ToolPermissionRead,
)
from app.schemas.mcp_oauth import OAuthDiscoveryResult, OAuthInitiateRequest
from app.schemas.skills import SkillRead
from app.services.mcp.tool_sync import ToolSyncService
from app.services.mcp.oauth_refresh import OAuthRefreshService
from app.services.mcp_oauth_service import initiate_oauth_flow, handle_oauth_callback as _handle_oauth_callback, mcp_oauth_states as _mcp_oauth_states
from app.services.mcp_session_test import test_mcp_session_connection
from app.services.agents.tool_naming import build_tool_name

logger = logging.getLogger(__name__)

# ── System (virtual) server constants ─────────────────────────────────────────
SYSTEM_SERVER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DECISION_SERVER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

# System tool IDs — derived from SystemToolRegistry at module load time.
# Do NOT add hardcoded UUID constants here; register tools in system_tool_registry.py.
from app.services.agents.system_tool_registry import SystemToolRegistry as _STR
SYSTEM_TOOL_IDS: set[uuid.UUID] = _STR.get_mcp_hub_ids()


async def _resolve_default_session(server_id: uuid.UUID, db: AsyncSession) -> McpSession:
    """Resolve the default session for a server using is_default flag.

    Resolution order:
    1. is_default=True AND is_active=True
    2. Sole active session (auto-fallback)
    3. Error if multiple active and no default
    4. Error if no active sessions at all
    """
    # Priority 1: explicitly marked default + active
    result = await db.execute(
        select(McpSession).where(
            McpSession.server_id == server_id,
            McpSession.is_default == True,  # noqa: E712
            McpSession.is_active == True,  # noqa: E712
        )
    )
    default_session = result.scalar_one_or_none()
    if default_session:
        return default_session

    # Priority 2: sole active session auto-fallback
    result = await db.execute(
        select(McpSession).where(
            McpSession.server_id == server_id,
            McpSession.is_active == True,  # noqa: E712
        )
    )
    active_sessions = result.scalars().all()

    if len(active_sessions) == 1:
        return active_sessions[0]

    if len(active_sessions) == 0:
        raise HTTPException(status_code=422, detail="No active sessions found.")

    raise HTTPException(
        status_code=422,
        detail="No default session configured. Please designate a default session.",
    )


async def _clear_other_defaults(server_id: uuid.UUID, exclude_session_id: uuid.UUID, db: AsyncSession) -> None:
    """Clear is_default on all other sessions for the same server (at-most-one-default enforcement)."""
    from sqlalchemy import update
    await db.execute(
        update(McpSession)
        .where(
            McpSession.server_id == server_id,
            McpSession.id != exclude_session_id,
            McpSession.is_default == True,  # noqa: E712
        )
        .values(is_default=False)
    )
    await db.flush()

def _system_server_read() -> McpServerRead:
    """Return a virtual McpServerRead for built-in system tools."""
    now = datetime.now(timezone.utc)
    return McpServerRead(
        id=SYSTEM_SERVER_ID,
        name="system",
        slug="system",
        description="Built-in system tools available to all agents",
        base_url="",
        oauth_config=None,
        status=McpServerStatus.active,
        last_synced_at=None,
        session_count=0,
        created_at=now,
        updated_at=now,
    )

def _system_tool_reads() -> list[McpToolRead]:
    """Return virtual McpToolRead objects for all built-in system tools.

    Derived entirely from ``SystemToolRegistry`` — no hardcoded tool data here.
    To add or rename a system tool, update ``system_tool_registry.py``.
    """
    from app.services.agents.system_tool_registry import SystemToolRegistry
    now = datetime.now(timezone.utc)
    return [
        McpToolRead(
            id=entry["id"],
            server_id=SYSTEM_SERVER_ID,
            server_slug="system",
            server_name="system",
            name=entry["name"],
            original_name=entry["original_name"],
            description=entry["description"],
            input_schema=entry["input_schema"],
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        for entry in SystemToolRegistry.get_mcp_hub_entries()
    ]


async def _decision_tool_reads(db: AsyncSession, tenant_id: uuid.UUID | None) -> list[McpToolRead]:
    """Return virtual McpToolRead objects for the caller's tenant decision tools.

    Each tool surfaces canonically as ``decision____<name>`` (shared
    tool-naming convention) with its auto-generated description and an
    AgentDataType-derived input schema. Tenant-contained: only the caller's
    tenant tools are listed.
    """
    from app.db.models.decision_tools import DecisionTool
    from app.core.tenant_context import get_tenant_context  # noqa: F401 (context via caller)
    from app.services.system_one.decision_tool_service import build_input_schema

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(DecisionTool)
        .where(
            DecisionTool.tenant_id == tenant_id,
            DecisionTool.enabled.is_(True),
        )
        .options(selectinload(DecisionTool.questions))
        .order_by(DecisionTool.name)
    )
    reads: list[McpToolRead] = []
    for tool in result.scalars().all():
        tool_id = uuid.uuid5(uuid.NAMESPACE_URL, f"decision-tool:{tool.id}")
        reads.append(
            McpToolRead(
                id=tool_id,
                server_id=DECISION_SERVER_ID,
                server_slug="decision",
                server_name="decision",
                name=build_tool_name("decision", tool.name),
                original_name=tool.name,
                description=tool.description or "",
                input_schema=build_input_schema(tool)
                or {"type": "object", "properties": {}},
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
    return reads


def _decision_server_read() -> McpServerRead:
    """Return a virtual McpServerRead for tenant decision tools."""
    now = datetime.now(timezone.utc)
    return McpServerRead(
        id=DECISION_SERVER_ID,
        name="decision",
        slug="decision",
        description="User-defined decision tools of this workspace",
        base_url="",
        oauth_config=None,
        status=McpServerStatus.active,
        last_synced_at=None,
        session_count=0,
        created_at=now,
        updated_at=now,
    )


async def seed_system_tools(db: "AsyncSession") -> None:
    """Idempotently seed the system server and its built-in tools into the database.

    All tool data is derived from ``SystemToolRegistry`` — no hardcoded tool rows
    here.  Adding a new system tool only requires updating ``system_tool_registry.py``.

    Migration note: if an existing row has ``original_name='save_result'`` it is
    updated in-place to ``save_data`` (same UUID, renamed).
    """
    from app.services.agents.system_tool_registry import SystemToolRegistry

    # Tenant binding: the system server (and its tools) belong to the ROOT
    # tenant — startup seeding runs on an unscoped session, so the stamp is
    # explicit.  Pre-bootstrap (no root tenant yet) stays NULL; the adoption
    # migration re-homes the rows when the root tenant appears.
    from app.services.tenancy.root_tenant import get_root_tenant_id

    root_tenant_id = await get_root_tenant_id(db)

    # ── Seed system server ────────────────────────────────────────────────────
    existing_server = await db.get(McpServer, SYSTEM_SERVER_ID)
    if not existing_server:
        system_server = McpServer(
            id=SYSTEM_SERVER_ID,
            tenant_id=root_tenant_id,
            name="system",
            slug="system",
            description="Built-in system tools available to all agents",
            base_url="",
            status=McpServerStatus.active,
        )
        db.add(system_server)
        await db.flush()
        logger.info("System server seeded (id=%s)", SYSTEM_SERVER_ID)
    elif root_tenant_id is not None and existing_server.tenant_id is None:
        # Self-heal a legacy NULL-tenant row (pre-adoption deployment).
        existing_server.tenant_id = root_tenant_id

    # ── Migrate legacy save_result row → save_data ────────────────────────────
    save_data_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    legacy_row = await db.get(McpTool, save_data_id)
    if legacy_row and legacy_row.original_name == "save_result":
        legacy_row.name = "system____save_data"
        legacy_row.original_name = "save_data"
        legacy_row.description = "Save named intermediate data during execution for later retrieval."
        await db.flush()
        logger.info("Migrated system tool save_result → save_data (id=%s)", save_data_id)

    # ── Seed / upsert all registry tools ─────────────────────────────────────
    for entry in SystemToolRegistry.get_mcp_hub_entries():
        existing_tool = await db.get(McpTool, entry["id"])
        if not existing_tool:
            tool = McpTool(
                id=entry["id"],
                # Denormalized tenant binding — the system server's tenant.
                tenant_id=root_tenant_id,
                server_id=SYSTEM_SERVER_ID,
                name=entry["name"],
                original_name=entry["original_name"],
                description=entry["description"],
                input_schema=None,
                is_active=True,
            )
            db.add(tool)
            logger.info("System tool seeded: %s (id=%s)", entry["name"], entry["id"])
        else:
            updated = False
            if root_tenant_id is not None and existing_tool.tenant_id != root_tenant_id:
                existing_tool.tenant_id = root_tenant_id
                updated = True
            if existing_tool.name != entry["name"]:
                existing_tool.name = entry["name"]
                updated = True
            if existing_tool.original_name != entry["original_name"]:
                existing_tool.original_name = entry["original_name"]
                updated = True
            if existing_tool.description != entry["description"]:
                existing_tool.description = entry["description"]
                updated = True
            if updated:
                logger.info(
                    "System tool updated: %s → %s (id=%s)",
                    existing_tool.original_name, entry["name"], entry["id"],
                )

    # ── Retire legacy system____ management rows (FIX-20261101-000319) ─────
    # Management + meta tools moved to the per-tenant Control Center (cc)
    # entity; the global System entity must no longer list or grant them.
    # Pure SQL (no row hydration — some reserved UUIDs coerce to INTEGER
    # under the SQLite test engine's NUMERIC affinity).  Idempotent:
    # nothing matches once retired.
    from app.db.models.skills import SkillToolBinding as _SkillToolBinding
    from sqlalchemy import delete as _sa_delete

    _mgmt_names = _STR.get_management_tool_names() | _STR.get_meta_tool_names()
    _legacy_row_ids = (
        select(McpTool.id).where(
            McpTool.name.like("system____%"),
            McpTool.original_name.in_(_mgmt_names),
        )
    ).scalar_subquery()
    await db.execute(
        _sa_delete(_SkillToolBinding).where(
            _SkillToolBinding.tool_id.in_(_legacy_row_ids)
        )
    )
    await db.execute(
        _sa_delete(McpTool).where(
            McpTool.name.like("system____%"),
            McpTool.original_name.in_(_mgmt_names),
        )
    )

    await db.flush()
    await db.commit()


McpServerRouter = APIRouter(prefix="/mcp/servers", tags=["MCP Hub — Servers"])


# ── Control Center entity gating (FIX-20261101-014511) ────────────────────────
#
# The per-tenant Control Center MCP entity (slug ``cc``, seeded by
# assistant_seeder) is a PROTECTED integration: ``integration::control_center``
# read = may see it, manage = may define anything around it.  Ordinary
# (non-cc) servers keep following the plain ``integration::mcp_hub`` rules.


def _is_cc_server(server: McpServer) -> bool:
    """True when the resolved server row is the Control Center entity."""
    return getattr(server, "slug", None) == "cc"


async def _cc_visible(request: Request, db: AsyncSession) -> bool:
    """May the calling identity SEE the Control Center entity?"""
    return await identity_has_permission(
        request, db, RT_INTEGRATION_CONTROL_CENTER, "read"
    )


async def _require_cc_permission(
    request: Request, db: AsyncSession, action: str
) -> None:
    """Raise a structured 403 unless the caller holds the cc entity action."""
    if await identity_has_permission(request, db, RT_INTEGRATION_CONTROL_CENTER, action):
        return
    raise HTTPException(
        status_code=403,
        detail=PermissionDeniedDetail(
            detail=(
                f"The Control Center integration requires "
                f"integration::control_center:{action}."
            ),
            required_permission=RequiredPermission(
                resource_type=RT_INTEGRATION_CONTROL_CENTER,
                action=action,
                resource_id=None,
            ),
        ).model_dump(),
    )


async def _gate_cc_server(
    request: Request,
    db: AsyncSession,
    server: McpServer,
    *,
    mutation: bool = False,
) -> None:
    """Enforce entity-view permission when *server* is the cc entity.

    Visibility (read): 404-without-leak for callers without ``read``.
    Mutations: structured 403 for callers without ``manage``.  Non-cc
    servers pass through untouched.
    """
    if not _is_cc_server(server):
        return
    if mutation:
        await _require_cc_permission(request, db, "manage")
    elif not await _cc_visible(request, db):
        raise HTTPException(status_code=404, detail="MCP server not found")


def _reject_cc_mutation(server: McpServer, *, sessions: bool = False) -> None:
    """FIX-20261101-090438: the cc entity is system-managed and sessionless.

    Must be checked BEFORE the FIX-014511 manage-permission gate —
    immutability is unconditional, not a permission question.  Entity
    lifecycle/config (update/delete/sync/OAuth) is locked for EVERYONE
    (including ``integration::control_center:manage`` holders — the seeder
    is the only writer).  Session operations are rejected as unsupported:
    MCP sessions don't apply to the cc entity (access flows through
    role/skill grants only).  Tool GRANTS onto cc tools remain governed
    solely by the FIX-014511 permission gate.  Non-cc servers pass through.
    """
    if not _is_cc_server(server):
        return
    if sessions:
        detail = (
            "Sessions are not supported for the Control Center integration — "
            "access flows through role and skill grants."
        )
    else:
        detail = (
            "The Control Center integration is system-managed and cannot be modified."
        )
    raise HTTPException(
        status_code=403,
        detail={"code": "system_managed_integration", "detail": detail},
    )


@McpServerRouter.get("", response_model=list[McpServerRead])
async def list_mcp_servers(
    request: Request,
    db: DbSession,
    response: Response,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list:
    """List MCP servers with deterministic, permission-correct pagination.

    FIX-20261101-014511: the Control Center entity (slug ``cc``) is only
    listed for callers holding integration::control_center:read.

    FIX-20261102-062047: the cc filter (and the system/decision exclusion)
    is applied BEFORE offset/limit so a page is never short or shifted.
    Pagination runs over the FULL logical ordering — the two virtual
    servers (``system``, ``decision``) occupy the first two slots, then
    DB servers ordered by (name, id).  ``X-Total-Count`` carries the true
    total of that ordering.
    """
    cc_visible = await _cc_visible(request, db)

    filters = [McpServer.id.notin_((SYSTEM_SERVER_ID, DECISION_SERVER_ID))]
    if not cc_visible:
        # Filter in the query — never post-slice (that shortens pages and
        # skips rows on the next offset).
        filters.append(McpServer.slug != "cc")

    db_total = (
        await db.execute(select(func.count()).select_from(McpServer).where(*filters))
    ).scalar_one()
    virtual: list[McpServerRead] = [_system_server_read(), _decision_server_read()]
    total = int(db_total) + len(virtual)
    response.headers["X-Total-Count"] = str(total)

    # Virtual rows come first in the full ordering; only fetch the DB rows
    # the requested window still covers.
    server_reads: list[McpServerRead] = [
        virtual[index] for index in range(offset, min(offset + limit, len(virtual)))
    ]
    db_offset = max(0, offset - len(virtual))
    db_limit = limit - len(server_reads)
    if db_limit > 0:
        result = await db.execute(
            select(McpServer)
            .options(selectinload(McpServer.sessions))
            .where(*filters)
            .order_by(McpServer.name, McpServer.id)
            .offset(db_offset)
            .limit(db_limit)
        )
        db_rows = list(result.scalars().all())
        if not cc_visible:
            # Defense in depth: the query filter is authoritative for
            # pagination; this must never remove a row in production.
            db_rows = [server for server in db_rows if not _is_cc_server(server)]
        for server in db_rows:
            s_read = McpServerRead.model_validate(server)
            s_read.session_count = len(server.sessions)
            server_reads.append(s_read)
    return server_reads


@McpServerRouter.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: McpServerCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "create")),
) -> McpServer:
    # Reject reserved slugs — "system" (built-in system tools), "decision"
    # (user-defined decision tools) and "cc" (Control Center management
    # entity) are namespaces, not registerable servers.
    if body.slug in ("system", "decision", "cc"):
        raise HTTPException(
            status_code=409,
            detail=f"The slug '{body.slug}' is reserved for built-in tools",
        )
    # Enforce slug uniqueness PER TENANT — business identity is
    # (tenant_id, slug); the same slug may exist in different tenants.
    # The session-scoped tenant id is authoritative (fail-closed internal
    # traffic binds the signed tenant; browser traffic the resolved one).
    from app.db.tenant_scoping import scope_for_session

    tenant_id = scope_for_session(db)
    existing = await db.execute(
        select(McpServer).where(
            McpServer.slug == body.slug,
            McpServer.tenant_id == tenant_id,  # noqa: E711 — NULL never matches
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"MCP server slug '{body.slug}' already exists")

    server = McpServer(**body.model_dump())
    if tenant_id is not None:
        # Explicit stamping (defense in depth — the flush listener also stamps).
        server.tenant_id = tenant_id
    db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


@McpServerRouter.get("/{server_id}", response_model=McpServerRead)
async def get_mcp_server(
    server_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
) -> McpServer:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await _gate_cc_server(request, db, server)
    return server


@McpServerRouter.put("/{server_id}", response_model=McpServerRead)
async def update_mcp_server(
    server_id: uuid.UUID,
    body: McpServerUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "update")),
) -> McpServer:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(server)
    await _gate_cc_server(request, db, server, mutation=True)
    # Enforce PER-TENANT slug uniqueness when the slug is being changed —
    # business identity is (tenant_id, slug), so a duplicate check is only
    # meaningful within the server's own tenant.
    new_fields = body.model_dump(exclude_unset=True)
    if "slug" in new_fields and new_fields["slug"] != server.slug:
        from app.db.tenant_scoping import scope_for_session

        tenant_id = scope_for_session(db)
        existing = await db.execute(
            select(McpServer).where(
                McpServer.slug == new_fields["slug"],
                McpServer.id != server.id,
                McpServer.tenant_id == tenant_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"MCP server slug '{new_fields['slug']}' already exists",
            )
    for field, value in new_fields.items():
        setattr(server, field, value)
    await db.flush()
    await db.refresh(server)
    return server


@McpServerRouter.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "delete")),
) -> None:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(server)
    await _gate_cc_server(request, db, server, mutation=True)
    await db.delete(server)


@McpServerRouter.post("/{server_id}/sync", response_model=SyncResult)
async def sync_mcp_server(
    server_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "execute")),
) -> SyncResult:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(server)
    await _gate_cc_server(request, db, server, mutation=True)

    # Gate: require at least one session for sync
    session_count_result = await db.execute(
        select(McpSession).where(McpSession.server_id == server_id)
    )
    has_sessions = session_count_result.first() is not None
    if not has_sessions:
        raise HTTPException(
            status_code=422,
            detail="This server has no configured sessions. Add a session before syncing.",
        )

    # Resolve default session by is_default flag (with sole-active fallback)
    default_session = await _resolve_default_session(server_id, db)
    logger.info(
        "Sync: resolved default session %s (auth_type=%s, has_creds=%s) for server %s",
        default_session.name,
        default_session.auth_type,
        default_session.encrypted_credentials is not None,
        server_id,
    )

    sync_service = ToolSyncService()
    try:
        counts = await sync_service.sync(server, db, session=default_session)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Extract warnings from sync result
    warnings_list: list[str] = counts.get("warnings", [])

    # Count total active tools
    total_result = await db.execute(
        select(McpTool).where(McpTool.server_id == server_id, McpTool.is_active == True)  # noqa: E712
    )
    total_active = len(total_result.scalars().all())

    return SyncResult(
        server_id=server_id,
        tools_added=counts["added"],
        tools_updated=counts["updated"],
        tools_deactivated=counts["deactivated"],
        total_active=total_active,
        warnings=warnings_list,
    )


@McpServerRouter.get("/{server_id}/tools", response_model=list[McpToolRead])
async def list_server_tools(
    server_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
) -> list[McpTool]:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await _gate_cc_server(request, db, server)
    result = await db.execute(
        select(McpTool)
        .where(McpTool.server_id == server_id)
        .order_by(McpTool.name)
    )
    return list(result.scalars().all())


@McpServerRouter.post("/{server_id}/oauth/authorize")
async def get_oauth_authorization_url(
    server_id: uuid.UUID,
    request: Request,
    db: DbSession,
    body: OAuthInitiateRequest | None = None,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> dict:
    """
    Get OAuth authorization URL for an MCP server.

    Configuration priority:
    1. If metadata_url is provided in body, fetch config from that URL
    2. If manual fields (authorization_url, token_url) provided, use them
    3. If server has pre-configured oauth_config, use that
    4. Otherwise, attempt auto-discovery from server's base_url
    
    Performs Dynamic Client Registration (RFC 7591) when no client_id is found.
    """
    manual_config: OAuthDiscoveryResult | None = None
    redirect_uri = os.getenv("MCP_OAUTH_REDIRECT_URI", "http://localhost:5173/oauth/callback")
    
    if body:
        # Priority 1: Fetch from metadata URL if provided
        if body.metadata_url:
            from app.services.mcp_oauth_service import fetch_oauth_metadata
            try:
                manual_config = await fetch_oauth_metadata(body.metadata_url, redirect_uri)
                logger.info("OAuth config fetched from metadata URL: %s", body.metadata_url)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch OAuth metadata from {body.metadata_url}: {exc}"
                )
        # Priority 2: Use manual configuration if provided
        elif body.authorization_url and body.token_url:
            manual_config = OAuthDiscoveryResult(
                authorization_url=body.authorization_url,
                token_url=body.token_url,
                client_id=body.client_id or "",
                client_secret=body.client_secret,
                scope=body.scope,
                redirect_uri=redirect_uri,
                registration_endpoint=None,
            )
            logger.info("Using manual OAuth configuration")

    # When no manual config provided, try auto-discovery.
    # FIX-20261101-014511: mutating the cc entity's configuration requires
    # integration::control_center:manage — resolve the server up front so
    # the gate applies regardless of discovery path.
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(server)
    await _gate_cc_server(request, db, server, mutation=True)
    if manual_config is None:
        if server.oauth_config:
            oauth_cfg = server.oauth_config
            auth_url = oauth_cfg.get("authorization_url")
            client_id = oauth_cfg.get("client_id")
            if auth_url and not client_id:
                raise HTTPException(
                    status_code=400,
                    detail="Incomplete OAuth configuration: client_id is required. "
                    "Please provide a complete oauth_config or use manual configuration.",
                )
        else:
            # Priority 4: Auto-discovery from server's base_url
            from app.services.mcp_oauth_service import discover_oauth_config
            try:
                manual_config = await discover_oauth_config(server.base_url, redirect_uri)
                logger.info("OAuth config auto-discovered for server %s", server_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"OAuth not configured for this server and auto-discovery failed: {exc}. "
                    "Please provide manual OAuth parameters or configure the server's oauth_config.",
                )
    
    # Pass session metadata to OAuth flow
    session_name = body.session_name if body else None
    session_description = body.session_description if body else None
    reauth_session_id: uuid.UUID | None = None
    if body and body.session_id:
        try:
            reauth_session_id = uuid.UUID(body.session_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="session_id must be a valid UUID")

    return await initiate_oauth_flow(
        server_id, db, manual_config, session_name, session_description,
        session_id=reauth_session_id,
    )


# ── MCP Session Router ─────────────────────────────────────────────────────────
McpSessionRouter = APIRouter(prefix="/mcp/servers", tags=["MCP Hub — Sessions"])


@McpSessionRouter.get("/{server_id}/sessions", response_model=list[McpSessionRead])
async def list_mcp_sessions(
    server_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> list[McpSession]:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await _gate_cc_server(request, db, server)
    result = await db.execute(
        select(McpSession).where(McpSession.server_id == server_id).order_by(McpSession.name)
    )
    return list(result.scalars().all())


@McpSessionRouter.post(
    "/{server_id}/sessions",
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_session(
    server_id: uuid.UUID,
    body: McpSessionCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> dict:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(server, sessions=True)
    await _gate_cc_server(request, db, server, mutation=True)

    # Count existing sessions to determine if this is the first
    existing_count_result = await db.execute(
        select(McpSession).where(McpSession.server_id == server_id)
    )
    existing_count = len(existing_count_result.scalars().all())
    is_first_session = existing_count == 0

    # Passthrough sessions: skip credential encryption, skip connection test, activate immediately
    if body.auth_type == McpSessionAuthType.passthrough:
        session_data = body.model_dump(exclude={"credentials", "is_default"})
        session = McpSession(
            server_id=server_id,
            encrypted_credentials=None,
            is_active=True,
            is_default=is_first_session or (body.is_default is True),
            **session_data,
        )
        db.add(session)
        await db.flush()
        # Enforce at-most-one-default: clear other sessions if this one is default
        if session.is_default:
            await _clear_other_defaults(server_id, session.id, db)
        await db.refresh(session)
        return {
            **McpSessionRead.model_validate(session).model_dump(),
            "connection_test": {"success": True, "message": "Passthrough session — no credential test required"},
        }

    # Encrypt credentials before storage
    encrypted_creds = None
    if body.credentials:
        vault = get_vault()
        encrypted_creds = vault.encrypt(json.dumps(body.credentials))

    session_data = body.model_dump(exclude={"credentials", "is_default"})
    session = McpSession(
        server_id=server_id,
        encrypted_credentials=encrypted_creds,
        is_active=True,  # Sessions are active by default
        is_default=is_first_session or (body.is_default is True),
        **session_data,
    )
    db.add(session)
    await db.flush()
    # Enforce at-most-one-default: clear other sessions if this one is default
    if session.is_default:
        await _clear_other_defaults(server_id, session.id, db)
    await db.refresh(session)
    
    # Test connection (informational only — does not affect is_active)
    logger.info("Testing connection for new session %s", session.id)
    test_result = await test_mcp_session_connection(server, session)
    
    logger.info(
        "Session %s connection test %s: %s",
        session.id,
        "succeeded" if test_result.success else "failed",
        test_result.message
    )
    
    # Return session with connection test result
    return {
        **McpSessionRead.model_validate(session).model_dump(),
        "connection_test": test_result.to_dict()
    }


@McpSessionRouter.put(
    "/{server_id}/sessions/{session_id}",
    response_model=McpSessionRead,
)
async def update_mcp_session(
    server_id: uuid.UUID,
    session_id: uuid.UUID,
    body: McpSessionUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> McpSession:
    # FIX-20261101-014511: gate cc-entity session mutation (manage).
    parent_server = await db.get(McpServer, server_id)
    if not parent_server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(parent_server, sessions=True)
    await _gate_cc_server(request, db, parent_server, mutation=True)
    update_data = body.model_dump(exclude_unset=True, exclude={"credentials", "is_default"})
    # NOTE: McpSession is a parent-scoped (tenant-agnostic) table — the
    # McpServer join lets the do_orm_execute choke point constrain the
    # lookup to the request's tenant even when a foreign (server_id,
    # session_id) pair is supplied.  Unscoped sessions: FK-guaranteed
    # inner join, row set unchanged.
    result = await db.execute(
        select(McpSession)
        .join(McpServer, McpServer.id == McpSession.server_id)
        .where(
            McpSession.id == session_id, McpSession.server_id == server_id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="MCP session not found")

    update_data = body.model_dump(exclude_unset=True, exclude={"credentials", "is_default"})
    for field, value in update_data.items():
        setattr(session, field, value)

    # Handle is_default enforcement separately
    if body.is_default is not None:
        session.is_default = body.is_default

    if body.credentials is not None:
        vault = get_vault()
        session.encrypted_credentials = vault.encrypt(json.dumps(body.credentials))

    await db.flush()

    # Enforce at-most-one-default: clear other sessions if this one is default
    if session.is_default:
        await _clear_other_defaults(server_id, session_id, db)

    await db.refresh(session)
    return session


@McpSessionRouter.delete(
    "/{server_id}/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mcp_session(
    server_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> None:
    # FIX-20261101-014511: gate cc-entity session mutation (manage).
    parent_server = await db.get(McpServer, server_id)
    if not parent_server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(parent_server, sessions=True)
    await _gate_cc_server(request, db, parent_server, mutation=True)
    # Parent-scoped table: join the tenant-scoped McpServer parent so a
    # foreign (server_id, session_id) pair cannot be resolved/deleted in
    # tenant context.
    result = await db.execute(
        select(McpSession)
        .join(McpServer, McpServer.id == McpSession.server_id)
        .where(
            McpSession.id == session_id, McpSession.server_id == server_id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="MCP session not found")

    # If session is the default and other sessions exist, block deletion
    if session.is_default:
        other_count_result = await db.execute(
            select(McpSession).where(
                McpSession.server_id == server_id,
                McpSession.id != session_id,
            )
        )
        other_sessions = other_count_result.scalars().all()
        if len(other_sessions) > 0:
            raise HTTPException(
                status_code=409,
                detail="The default session cannot be deleted while other sessions exist. Please designate another session as default first.",
            )

    await db.delete(session)


@McpSessionRouter.post(
    "/{server_id}/sessions/{session_id}/refresh-token",
    response_model=McpSessionRead,
)
async def refresh_oauth_token(
    server_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> McpSession:
    """
    Manually refresh OAuth access token for a session.
    
    Returns the updated session with new token expiry times.
    """
    # FIX-20261101-014511: gate cc-entity session mutation (manage).
    parent_server = await db.get(McpServer, server_id)
    if not parent_server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    _reject_cc_mutation(parent_server, sessions=True)
    await _gate_cc_server(request, db, parent_server, mutation=True)
    # Parent-scoped table: join the tenant-scoped McpServer parent so a
    # foreign (server_id, session_id) pair cannot be resolved in tenant
    # context.
    result = await db.execute(
        select(McpSession)
        .join(McpServer, McpServer.id == McpSession.server_id)
        .where(
            McpSession.id == session_id,
            McpSession.server_id == server_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="MCP session not found")
    
    if session.auth_type != McpSessionAuthType.oauth2:
        raise HTTPException(
            status_code=400,
            detail="Token refresh is only supported for OAuth2 sessions"
        )
    
    # Refresh the token
    refresh_service = OAuthRefreshService()
    success = await refresh_service.refresh_access_token(session, db)
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to refresh OAuth token. Check session logs for details."
        )
    
    await db.refresh(session)
    return session


# ── MCP OAuth Router ───────────────────────────────────────────────────────────
McpOAuthRouter = APIRouter(prefix="/mcp/oauth", tags=["MCP Hub — OAuth"])


@McpOAuthRouter.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: DbSession,
) -> dict:
    """
    Handle OAuth callback and exchange code for tokens.
    Creates an MCP session with the acquired credentials.
    State token provides CSRF protection — no additional auth needed.
    """
    return await _handle_oauth_callback(code=code, state=state, db=db)


# ── MCP Tool Router ────────────────────────────────────────────────────────────
McpToolRouter = APIRouter(prefix="/mcp/tools", tags=["MCP Hub — Tools"])

@McpToolRouter.get("", response_model=list[McpToolRead])
async def list_all_tools(
    request: Request,
    db: DbSession,
    response: Response,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[McpToolRead]:
    """List every tool the caller may browse, deterministically paged.

    FIX-20261102-062047: the previous contract defaulted to ``limit=50``
    with an implementation-defined order, so tenants with >50 tools
    silently lost whole MCP servers (``supabase``/``decision``/...) from
    the picker.  The contract is now:

    - the full set is assembled, permission-filtered, deduplicated and
      SORTED before any slicing, so pages never lose or duplicate rows;
    - ordering is stable: ``(server_slug, tool name, id)``;
    - the default window covers a realistic tenant (200, the max cap) and
      ``X-Total-Count`` exposes the true total for real paging;
    - cc tools are hidden from general browsing without
      ``integration::control_center:read`` (individually resolvable via
      ``GET /mcp/tools/{tool_id}`` when an entity already references them).
    """
    from app.core.tenant_context import get_tenant_context

    context = get_tenant_context(request)
    tenant_id = context.tenant_id if context.is_set else None
    result = await db.execute(
        select(McpTool)
        .options(selectinload(McpTool.server))
        .join(McpServer, McpTool.server_id == McpServer.id)
        .where(McpTool.is_active == True)  # noqa: E712
        .order_by(McpServer.name, McpTool.name)
    )
    tools = result.scalars().all()
    db_tool_reads: list[McpToolRead] = []
    for tool in tools:
        tool_read = McpToolRead.from_orm_with_server(tool)
        # Backward compatibility: normalize legacy "server/tool" names in responses.
        if "/" in tool_read.name and tool_read.server_slug:
            _, bare_name = tool_read.name.split("/", 1)
            tool_read.name = build_tool_name(tool_read.server_slug, bare_name)
        db_tool_reads.append(tool_read)
    all_tools = _system_tool_reads() + await _decision_tool_reads(db, tenant_id) + db_tool_reads
    if not await _cc_visible(request, db):
        all_tools = [tool for tool in all_tools if tool.server_slug != "cc"]
    # Deduplicate by tool ID — system tools are both returned as virtual objects
    # AND seeded into the DB, so without dedup they appear twice in the response.
    seen_ids: set[uuid.UUID] = set()
    deduped: list[McpToolRead] = []
    for tool in all_tools:
        if tool.id not in seen_ids:
            seen_ids.add(tool.id)
            deduped.append(tool)
    # Stable deterministic order over the FULL set BEFORE paginating.
    deduped.sort(key=lambda tool: (tool.server_slug or "", tool.name, str(tool.id)))
    response.headers["X-Total-Count"] = str(len(deduped))
    return deduped[offset:offset + limit]


@McpToolRouter.get("/{tool_id}", response_model=McpToolRead)
async def get_mcp_tool(
    tool_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
) -> McpToolRead:
    """Resolve ONE tool by id (FIX-20261102-062047).

    Used by the editors to render tools an entity already depends on that
    are not part of general browsing.  cc tools stay hidden from the LIST
    without ``integration::control_center:read``; here they are resolvable
    ONLY when an existing skill binding references them (404-without-leak
    otherwise) so the editor can show the dependency read-only.
    """
    result = await db.execute(
        select(McpTool)
        .options(selectinload(McpTool.server))
        .where(McpTool.id == tool_id)
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        # Virtual tools have no mcp_tools row — resolve from their registries.
        for virtual in _system_tool_reads():
            if virtual.id == tool_id:
                return virtual
        from app.core.tenant_context import get_tenant_context

        context = get_tenant_context(request)
        tenant_id = context.tenant_id if context.is_set else None
        for virtual in await _decision_tool_reads(db, tenant_id):
            if virtual.id == tool_id:
                return virtual
        raise HTTPException(status_code=404, detail="MCP tool not found")

    if tool.server is not None and _is_cc_server(tool.server):
        if not await _cc_visible(request, db):
            from app.core.tenant_context import get_tenant_context

            context = get_tenant_context(request)
            tenant_id = context.tenant_id if context.is_set else None
            if not await _tool_referenced_by_skill(db, tool.id, tenant_id):
                raise HTTPException(status_code=404, detail="MCP tool not found")
    return McpToolRead.from_orm_with_server(tool)


async def _tool_referenced_by_skill(
    db: AsyncSession, tool_id: uuid.UUID, tenant_id: uuid.UUID | None
) -> bool:
    """True when a skill of the caller's tenant already binds *tool_id*.

    This is the ONLY door through which a cc tool becomes individually
    visible to an identity lacking ``integration::control_center:read``:
    the entity depends on it, so hiding it would silently corrupt the
    entity's definition.  It never exposes the rest of the cc catalogue.
    """
    stmt = (
        select(SkillToolBinding.id)
        .join(Skill, Skill.id == SkillToolBinding.skill_id)
        .where(SkillToolBinding.tool_id == tool_id)
    )
    if tenant_id is not None:
        stmt = stmt.where(Skill.tenant_id == tenant_id)
    return (await db.execute(stmt.limit(1))).first() is not None



@McpToolRouter.get("/{tool_id}/skills", response_model=list[SkillRead])
async def list_tool_skills(
    tool_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
) -> list[Skill]:
    tool = await db.get(McpTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="MCP tool not found")
    result = await db.execute(
        select(Skill)
        .options(selectinload(Skill.tool_bindings))
        .join(SkillToolBinding, SkillToolBinding.skill_id == Skill.id)
        .where(SkillToolBinding.tool_id == tool_id)
        .order_by(Skill.name)
    )
    return list(result.scalars().all())

async def _cc_tool_gate(
    request: Request,
    db: AsyncSession,
    tool: McpTool,
    *,
    action: str,
) -> None:
    """Gate operations on a Control Center entity tool (FIX-20261101-014511).

    Tools under the cc server are part of the protected integration: listing
    their grants requires ``read`` (visibility); creating/revoking grants
    requires ``manage``.  Non-cc tools pass through untouched.
    """
    server = await db.get(McpServer, tool.server_id)
    if server is None:
        return
    await _gate_cc_server(request, db, server, mutation=(action == "manage"))


@McpToolRouter.get("/{tool_id}/permissions", response_model=list[ToolPermissionRead])
async def list_tool_permissions(
    tool_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> list[ToolPermission]:
    tool = await db.get(McpTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="MCP tool not found")
    await _cc_tool_gate(request, db, tool, action="read")
    result = await db.execute(
        select(ToolPermission).where(ToolPermission.tool_id == tool_id)
    )
    return list(result.scalars().all())


@McpToolRouter.post(
    "/{tool_id}/permissions",
    response_model=ToolPermissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def grant_tool_permission(
    tool_id: uuid.UUID,
    body: ToolPermissionCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> ToolPermission:
    tool = await db.get(McpTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="MCP tool not found")
    await _cc_tool_gate(request, db, tool, action="manage")

    # Check duplicate
    existing = await db.execute(
        select(ToolPermission).where(
            ToolPermission.tool_id == tool_id,
            ToolPermission.role_id == body.role_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Permission already granted for this role")

    tp = ToolPermission(tool_id=tool_id, role_id=body.role_id)
    db.add(tp)
    await db.flush()
    await db.refresh(tp)
    return tp


@McpToolRouter.delete(
    "/{tool_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_tool_permission(
    tool_id: uuid.UUID,
    permission_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "manage")),
) -> None:
    tp = await db.get(ToolPermission, permission_id)
    if not tp or tp.tool_id != tool_id:
        raise HTTPException(status_code=404, detail="Tool permission not found")
    tool = await db.get(McpTool, tool_id)
    if tool is not None:
        await _cc_tool_gate(request, db, tool, action="manage")
    await db.delete(tp)


@McpToolRouter.post("/{tool_id}/test", response_model=TestToolResponse)
async def test_mcp_tool(
    tool_id: uuid.UUID,
    body: TestToolRequest,
    db: DbSession,
    http_request: Request,
    _: dict = Depends(require_permission(RT_INTEGRATION_MCP_HUB, "read")),
) -> TestToolResponse:
    """Test an MCP tool invocation with a specific session."""
    from app.services.mcp.proxy import McpProxyEngine, McpProxyError
    
    # Load the tool — parent-scoped table (mcp_tools inherits scope via
    # mcp_servers), so the McpServer join constrains resolution to the
    # request's tenant; a foreign tool id 404s in tenant context.
    tool_result = await db.execute(
        select(McpTool)
        .join(McpServer, McpServer.id == McpTool.server_id)
        .where(McpTool.id == tool_id)
    )
    tool = tool_result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Load server relationship
    await db.refresh(tool, ["server"])

    # Determine which session to use and whether it is passthrough
    if body.session_id is not None:
        # Parent-scoped table: the McpServer join prevents resolving a
        # foreign tenant's session id (which would otherwise leak its
        # server binding via the mismatch error).
        session_result = await db.execute(
            select(McpSession)
            .join(McpServer, McpServer.id == McpSession.server_id)
            .where(McpSession.id == body.session_id)
        )
        session = session_result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.server_id != tool.server_id:
            raise HTTPException(
                status_code=400,
                detail=f"Session belongs to a different server. Tool server: {tool.server_id}, Session server: {session.server_id}",
            )
    else:
        # No session_id provided — resolve the default session for this server
        try:
            session = await _resolve_default_session(tool.server_id, db)
        except HTTPException:
            # If no default is configured, fall back to passthrough auto-selection
            from sqlalchemy import select as _select
            result = await db.execute(
                _select(McpSession).where(
                    McpSession.server_id == tool.server_id,
                    McpSession.is_active == True,  # noqa: E712
                ).limit(1)
            )
            session = result.scalar_one_or_none()
            if not session:
                raise HTTPException(status_code=404, detail="No active session found for this tool's server")
            # Only auto-use if passthrough
            if session.auth_type != McpSessionAuthType.passthrough:
                raise HTTPException(
                    status_code=400,
                    detail="session_id is required for non-passthrough sessions when no default is configured",
                )

    is_passthrough = session.auth_type == McpSessionAuthType.passthrough

    # For passthrough: get the agent identity token
    agent_jwt: str | None = None
    if is_passthrough:
        if not body.agent_subject:
            raise HTTPException(
                status_code=400,
                detail="Passthrough tool test requires an agent_subject (agent identity ID or username)",
            )
        
        # Load the agent identity by ID (UUID) or username (realm_username)
        from app.db.models.agents import AgentIdentity
        from app.services.agents.identity_service import AgentIdentityService, AgentIdentityNotFoundError, AgentOAuthError
        from app.core.credential_vault import get_vault
        from datetime import datetime, timezone
        
        # Try parsing as UUID first
        identity: AgentIdentity | None = None
        try:
            identity_id = uuid.UUID(body.agent_subject)
            identity = await db.get(AgentIdentity, identity_id)
        except ValueError:
            # Not a UUID, try looking up by realm_username
            from sqlalchemy import select as _select
            result = await db.execute(
                _select(AgentIdentity).where(
                    AgentIdentity.realm_username == body.agent_subject
                )
            )
            identity = result.scalar_one_or_none()
        
        if not identity:
            raise HTTPException(
                status_code=404,
                detail=f"Agent identity '{body.agent_subject}' not found",
            )
        
        # Check if token needs refresh (expired or within 5 minutes of expiration)
        vault = get_vault()
        now = datetime.now(timezone.utc)
        needs_refresh = (
            not identity.access_token
            or not identity.token_expires_at
            or (identity.token_expires_at - now).total_seconds() < 300
        )
        
        if needs_refresh:
            logger.info("Refreshing token for agent identity %s before tool test", identity.id)
            identity_service = AgentIdentityService()
            try:
                identity = await identity_service.refresh_token(identity.id, db)
            except (AgentIdentityNotFoundError, AgentOAuthError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to refresh agent identity token: {str(exc)}",
                )
        
        # Decrypt and use the agent's access token
        agent_jwt = vault.decrypt(identity.access_token)
        logger.info("Using agent identity %s (%s) token for passthrough tool test", identity.id, identity.realm_username)
    
    # Invoke the tool via proxy
    proxy = McpProxyEngine()
    try:
        result = await proxy.call_tool(
            tool=tool,
            tool_input=body.tool_input,
            db=db,
            session_id=str(session.id),
            agent_jwt=agent_jwt,
        )
        return TestToolResponse(
            success=True,
            result=result,
            raw_response=result,
        )
    except McpProxyError as exc:
        return TestToolResponse(
            success=False,
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error testing tool %s", tool_id)
        return TestToolResponse(
            success=False,
            error=f"Unexpected error: {str(exc)}",
        )


async def check_tool_permission(
    tool_id: uuid.UUID, role_id: uuid.UUID, db: DbSession
) -> bool:
    """Check if a role has permission to call a specific tool."""
    result = await db.execute(
        select(ToolPermission).where(
            ToolPermission.tool_id == tool_id,
            ToolPermission.role_id == role_id,
        )
    )
    return result.scalar_one_or_none() is not None
