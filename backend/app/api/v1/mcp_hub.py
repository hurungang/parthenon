"""MCP Hub API routers: Server, Session, Tool management."""
import json
import os
import uuid
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_MCP_SERVER
from app.db.session import DbSession
from app.db.models.mcp_hub import McpServer, McpSession, McpTool, ToolPermission, McpSessionAuthType
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
from app.services.mcp_oauth_service import initiate_oauth_flow, handle_oauth_callback as _handle_oauth_callback
from app.services.mcp_session_test import test_mcp_session_connection

logger = logging.getLogger(__name__)

# ── MCP Server Router ──────────────────────────────────────────────────────────
McpServerRouter = APIRouter(prefix="/mcp/servers", tags=["MCP Hub — Servers"])


@McpServerRouter.get("", response_model=list[McpServerRead])
async def list_mcp_servers(
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
) -> list[McpServer]:
    result = await db.execute(select(McpServer).order_by(McpServer.name))
    return list(result.scalars().all())


@McpServerRouter.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: McpServerCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "create")),
) -> McpServer:
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

    # Find the first active session for authentication (default session)
    from app.db.models.mcp_hub import McpSession
    session_result = await db.execute(
        select(McpSession).where(
            McpSession.server_id == server_id,
            McpSession.is_active == True  # noqa: E712
        ).order_by(McpSession.created_at.asc()).limit(1)
    )
    default_session = session_result.scalar_one_or_none()
    if default_session:
        logger.info("Sync: using session %s (auth_type=%s, has_creds=%s) for server %s",
                    default_session.name, default_session.auth_type,
                    default_session.encrypted_credentials is not None, server_id)
    else:
        logger.info("Sync: no active session found for server %s, syncing without credentials", server_id)

    sync_service = ToolSyncService()
    try:
        counts = await sync_service.sync(server, db, session=default_session)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

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

    # Encrypt credentials before storage
    encrypted_creds = None
    if body.credentials:
        vault = get_vault()
        encrypted_creds = vault.encrypt(json.dumps(body.credentials))

    session_data = body.model_dump(exclude={"credentials"})
    session = McpSession(
        server_id=server_id,
        encrypted_credentials=encrypted_creds,
        is_active=False,  # Start as inactive, will activate after connection test
        **session_data,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    
    # Test connection
    logger.info("Testing connection for new session %s", session.id)
    test_result = await test_mcp_session_connection(server, session)
    
    # Update is_active based on test result
    session.is_active = test_result.success
    await db.flush()
    await db.refresh(session)
    
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

    update_data = body.model_dump(exclude_unset=True, exclude={"credentials"})
    for field, value in update_data.items():
        setattr(session, field, value)

    if body.credentials is not None:
        vault = get_vault()
        session.encrypted_credentials = vault.encrypt(json.dumps(body.credentials))

    await db.flush()
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
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> dict:
    """
    Handle OAuth callback and exchange code for tokens.
    Creates an MCP session with the acquired credentials.
    """
    return await _handle_oauth_callback(code=code, state=state, db=db)


# ── MCP Tool Router ────────────────────────────────────────────────────────────
McpToolRouter = APIRouter(prefix="/mcp/tools", tags=["MCP Hub — Tools"])

@McpToolRouter.get("", response_model=list[McpToolRead])
async def list_all_tools(
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "read")),
) -> list[McpToolRead]:
    result = await db.execute(
        select(McpTool)
        .options(selectinload(McpTool.server))
        .join(McpServer, McpTool.server_id == McpServer.id)
        .where(McpTool.is_active == True)  # noqa: E712
        .order_by(McpServer.name, McpTool.name)
    )
    tools = result.scalars().all()
    return [McpToolRead.from_orm_with_server(t) for t in tools]


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
    request: TestToolRequest,
    db: DbSession,
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
    
    # Verify session exists and belongs to the same server
    session = await db.get(McpSession, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.server_id != tool.server_id:
        raise HTTPException(
            status_code=400,
            detail=f"Session belongs to a different server. Tool server: {tool.server_id}, Session server: {session.server_id}"
        )
    
    # Invoke the tool via proxy
    proxy = McpProxyEngine()
    try:
        result = await proxy.call_tool(
            tool=tool,
            tool_input=request.tool_input,
            db=db,
            session_id=str(request.session_id),
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
