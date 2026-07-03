"""MCP Hub API routers: Server, Session, Tool management."""
import json
import os
import uuid
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_MCP_SERVER
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
        name="System",
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
            server_name="System",
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


async def seed_system_tools(db: "AsyncSession") -> None:
    """Idempotently seed the system server and its built-in tools into the database.

    All tool data is derived from ``SystemToolRegistry`` — no hardcoded tool rows
    here.  Adding a new system tool only requires updating ``system_tool_registry.py``.

    Migration note: if an existing row has ``original_name='save_result'`` it is
    updated in-place to ``save_data`` (same UUID, renamed).
    """
    from app.services.agents.system_tool_registry import SystemToolRegistry

    # ── Seed system server ────────────────────────────────────────────────────
    existing_server = await db.get(McpServer, SYSTEM_SERVER_ID)
    if not existing_server:
        system_server = McpServer(
            id=SYSTEM_SERVER_ID,
            name="System",
            slug="system",
            description="Built-in system tools available to all agents",
            base_url="",
            status=McpServerStatus.active,
        )
        db.add(system_server)
        await db.flush()
        logger.info("System server seeded (id=%s)", SYSTEM_SERVER_ID)

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
                server_id=SYSTEM_SERVER_ID,
                name=entry["name"],
                original_name=entry["original_name"],
                description=entry["description"],
                input_schema=None,
                is_active=True,
            )
            db.add(tool)
            logger.info("System tool seeded: %s (id=%s)", entry["name"], entry["id"])

    await db.flush()
    await db.commit()


McpServerRouter = APIRouter(prefix="/mcp/servers", tags=["MCP Hub — Servers"])


@McpServerRouter.get("", response_model=list[McpServerRead])
async def list_mcp_servers(
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list:
    result = await db.execute(
        select(McpServer)
        .options(selectinload(McpServer.sessions))
        .order_by(McpServer.name)
        .offset(offset)
        .limit(limit)
    )
    db_servers_raw = list(result.scalars().all())
    # Filter out the DB-seeded System server — only the virtual entry appears
    db_servers: list[McpServer] = [s for s in db_servers_raw if s.id != SYSTEM_SERVER_ID]
    # Build schema objects with session_count populated from eager-loaded relationship
    server_reads: list[McpServerRead] = []
    for server in db_servers:
        s_read = McpServerRead.model_validate(server)
        s_read.session_count = len(server.sessions)
        server_reads.append(s_read)
    if offset == 0:
        server_reads.insert(0, _system_server_read())
    return server_reads


@McpServerRouter.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: McpServerCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "create")),
) -> McpServer:
    # Reject reserved slugs — "system" is used for built-in system tools
    if body.slug == "system":
        raise HTTPException(
            status_code=409,
            detail="The slug 'system' is reserved for built-in system tools",
        )
    # Enforce slug uniqueness
    existing = await db.execute(select(McpServer).where(McpServer.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"MCP server slug '{body.slug}' already exists")

    server = McpServer(**body.model_dump())
    db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


@McpServerRouter.get("/{server_id}", response_model=McpServerRead)
async def get_mcp_server(
    server_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
) -> McpServer:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


@McpServerRouter.put("/{server_id}", response_model=McpServerRead)
async def update_mcp_server(
    server_id: uuid.UUID,
    body: McpServerUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "update")),
) -> McpServer:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(server, field, value)
    await db.flush()
    await db.refresh(server)
    return server


@McpServerRouter.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "delete")),
) -> None:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await db.delete(server)


@McpServerRouter.post("/{server_id}/sync", response_model=SyncResult)
async def sync_mcp_server(
    server_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "execute")),
) -> SyncResult:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
) -> list[McpTool]:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
    result = await db.execute(
        select(McpTool)
        .where(McpTool.server_id == server_id)
        .order_by(McpTool.name)
    )
    return list(result.scalars().all())


@McpServerRouter.post("/{server_id}/oauth/authorize")
async def get_oauth_authorization_url(
    server_id: uuid.UUID,
    db: DbSession,
    body: OAuthInitiateRequest | None = None,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
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

    # When no manual config provided, try auto-discovery
    if manual_config is None:
        server = await db.get(McpServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail="MCP server not found")
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
    
    return await initiate_oauth_flow(server_id, db, manual_config, session_name, session_description)


# ── MCP Session Router ─────────────────────────────────────────────────────────
McpSessionRouter = APIRouter(prefix="/mcp/servers", tags=["MCP Hub — Sessions"])


@McpSessionRouter.get("/{server_id}/sessions", response_model=list[McpSessionRead])
async def list_mcp_sessions(
    server_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> list[McpSession]:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")
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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> dict:
    server = await db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP server not found")

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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> McpSession:
    result = await db.execute(
        select(McpSession).where(
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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> None:
    result = await db.execute(
        select(McpSession).where(
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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> McpSession:
    """
    Manually refresh OAuth access token for a session.
    
    Returns the updated session with new token expiry times.
    """
    result = await db.execute(
        select(McpSession).where(
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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[McpToolRead]:
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
    all_tools = _system_tool_reads() + db_tool_reads
    # Deduplicate by tool ID — system tools are both returned as virtual objects
    # AND seeded into the DB, so without dedup they appear twice in the response.
    seen_ids: set[uuid.UUID] = set()
    deduped: list[McpToolRead] = []
    for tool in all_tools:
        if tool.id not in seen_ids:
            seen_ids.add(tool.id)
            deduped.append(tool)
    return deduped[offset:offset + limit]


@McpToolRouter.get("/{tool_id}/skills", response_model=list[SkillRead])
async def list_tool_skills(
    tool_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
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

@McpToolRouter.get("/{tool_id}/permissions", response_model=list[ToolPermissionRead])
async def list_tool_permissions(
    tool_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> list[ToolPermission]:
    tool = await db.get(McpTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="MCP tool not found")
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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> ToolPermission:
    tool = await db.get(McpTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="MCP tool not found")

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
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> None:
    tp = await db.get(ToolPermission, permission_id)
    if not tp or tp.tool_id != tool_id:
        raise HTTPException(status_code=404, detail="Tool permission not found")
    await db.delete(tp)


@McpToolRouter.post("/{tool_id}/test", response_model=TestToolResponse)
async def test_mcp_tool(
    tool_id: uuid.UUID,
    body: TestToolRequest,
    db: DbSession,
    http_request: Request,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
) -> TestToolResponse:
    """Test an MCP tool invocation with a specific session."""
    from app.services.mcp.proxy import McpProxyEngine, McpProxyError
    
    # Load the tool
    tool = await db.get(McpTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    
    # Load server relationship
    await db.refresh(tool, ["server"])

    # Determine which session to use and whether it is passthrough
    if body.session_id is not None:
        session = await db.get(McpSession, body.session_id)
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
