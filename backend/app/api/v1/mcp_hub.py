"""MCP Hub API routers: Server, Session, Tool management."""
import json
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.credential_vault import get_vault
from app.core.resource_types import RT_MCP_SERVER
from app.db.session import DbSession
from app.db.models.mcp_hub import McpServer, McpSession, McpTool, ToolPermission
from app.schemas.mcp_hub import (
    McpServerCreate,
    McpServerRead,
    McpServerUpdate,
    McpSessionCreate,
    McpSessionRead,
    McpSessionUpdate,
    McpToolRead,
    SyncResult,
    ToolPermissionCreate,
    ToolPermissionRead,
)
from app.services.mcp.tool_sync import ToolSyncService

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

    sync_service = ToolSyncService()
    try:
        counts = await sync_service.sync(server, db)
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
    response_model=McpSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_session(
    server_id: uuid.UUID,
    body: McpSessionCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_MCP_SERVER, "manage")),
) -> McpSession:
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
        **session_data,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


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


# ── MCP Tool Router ────────────────────────────────────────────────────────────
McpToolRouter = APIRouter(prefix="/mcp/tools", tags=["MCP Hub — Tools"])


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
