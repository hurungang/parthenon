"""Internal MCP tool proxy endpoint — called by Communication Hub.

All endpoints require a service certificate (via ``require_service_certificate``).

Routes (all under /internal/mcp):
  POST /proxy-tool  — proxy an MCP tool call through McpProxyEngine
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_service_certificate
from app.core.credential_vault import get_vault
from app.db.models.agents import AgentIdentity, AgentType, AgentRoleMcpSession
from app.db.models.mcp_hub import McpTool, McpSession
from app.db.session import DbSession
from app.services.agents.tool_naming import parse_tool_name, build_tool_name
from app.services.mcp.proxy import McpProxyEngine, McpProxyError
from app.services.token_refresh import check_token_expiration, refresh_oauth_token

logger = logging.getLogger(__name__)

InternalMcpProxyRouter = APIRouter(
    prefix="/internal/mcp",
    tags=["internal"],
)


class McpProxyRequest(BaseModel):
    """Request to proxy an MCP tool call."""

    tool_name: str  # Canonical "server____tool" (legacy "server/tool" also accepted)
    tool_args: dict[str, Any]
    agent_type_id: str | None = None  # Agent type ID (internal Agent Runtime path)
    agent_role_id: str | None = None  # Agent role ID (external API-key MCP path)
    agent_identity_id: str | None = None  # Agent identity ID (external API-key MCP path)
    agent_session_id: str | None = None  # Agent session ID (for logging only)
    agent_jwt: str | None = None  # Optional JWT for passthrough sessions
    user_jwt: str | None = None  # Optional user identity JWT for dual-identity passthrough


class McpProxyResponse(BaseModel):
    """Response from proxied MCP tool call."""

    result: dict[str, Any]


@InternalMcpProxyRouter.post(
    "/proxy-tool",
    response_model=McpProxyResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def proxy_mcp_tool(
    body: McpProxyRequest,
    db: DbSession,
) -> McpProxyResponse:
    """Proxy an MCP tool call to the external MCP server via McpProxyEngine.

    Called by Communication Hub to execute MCP tools without direct database
    access. Resolves the correct MCP session based on the agent's role and the
    tool's server.  All MCP protocol details (OAuth refresh, Mcp-Session-Id
    header, JSON-RPC) are handled by McpProxyEngine.

    Args:
        body: Proxy request with full tool name, args, agent_type_id
        db: Database session

    Returns:
        Structured tool result

    Raises:
        HTTPException: 404 if tool/agent not found, 502 if MCP call fails
    """
    logger.info(
        "MCP proxy request: tool=%s agent_type=%s session=%s",
        body.tool_name,
        body.agent_type_id,
        body.agent_session_id,
    )

    # Look up McpTool by canonical name with legacy slash-name fallback.
    tool_name_candidates = [body.tool_name]
    try:
        server_slug, bare_tool_name = parse_tool_name(body.tool_name)
        canonical_name = build_tool_name(server_slug, bare_tool_name)
        legacy_name = f"{server_slug}/{bare_tool_name}"
        tool_name_candidates = [canonical_name, legacy_name]
    except ValueError:
        # Non-canonical names are still checked directly via the original candidate.
        pass

    result = await db.execute(
        select(McpTool)
        .where(McpTool.name.in_(tool_name_candidates), McpTool.is_active.is_(True))
        .options(selectinload(McpTool.server))
    )
    tool = result.scalar_one_or_none()
    if not tool:
        logger.error("MCP tool not found: %s", body.tool_name)
        raise HTTPException(status_code=404, detail=f"MCP tool not found: {body.tool_name}")

    # Resolve the agent role (and optional identity) used to select the MCP session.
    # Internal Agent Runtime supplies an agent type; external MCP clients supply a
    # role + identity resolved from their API key. Both converge on the same
    # role-based session lookup below.
    agent_type = None
    role_id: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    if body.agent_role_id:
        role_id = uuid.UUID(body.agent_role_id)
    elif body.agent_type_id:
        agent_type_uuid = uuid.UUID(body.agent_type_id)
        agent_type = await db.get(AgentType, agent_type_uuid)
        if not agent_type or not agent_type.role_id:
            logger.error("Agent type %s not found or has no role", body.agent_type_id)
            raise HTTPException(
                status_code=404,
                detail=f"Agent type {body.agent_type_id} not found or has no role",
            )
        role_id = agent_type.role_id
        identity_id = agent_type.identity_id
    else:
        raise HTTPException(
            status_code=400,
            detail="agent_role_id or agent_type_id is required",
        )

    if body.agent_identity_id:
        identity_id = uuid.UUID(body.agent_identity_id)

    # Resolve MCP session for this tool's server from role assignments
    mcp_session_result = await db.execute(
        select(McpSession)
        .join(AgentRoleMcpSession, AgentRoleMcpSession.mcp_session_id == McpSession.id)
        .where(
            AgentRoleMcpSession.role_id == role_id,
            McpSession.server_id == tool.server_id,
            McpSession.is_active.is_(True),
        )
    )
    mcp_session = mcp_session_result.scalar_one_or_none()
    if not mcp_session:
        logger.error(
            "No MCP session found for role %s and server %s (tool: %s)",
            role_id,
            tool.server_id,
            body.tool_name,
        )
        raise HTTPException(
            status_code=502,
            detail=f"No MCP session assigned to role for server {tool.server.name}. "
            f"Please assign an MCP session to the role.",
        )

    # Resolve agent JWT for passthrough sessions
    agent_jwt = body.agent_jwt
    logger.debug("MCP session auth_type=%s, agent_jwt provided=%s", 
                 mcp_session.auth_type.value if mcp_session.auth_type else None, 
                 bool(agent_jwt))
    
    if mcp_session.auth_type.value == "passthrough" and not agent_jwt:
        logger.info("Passthrough session detected, resolving agent JWT...")
        # Get agent identity JWT (same logic as runtime_executor)

        if identity_id:
            logger.info("Resolving identity JWT for identity_id=%s...", identity_id)
            # Use explicit query to avoid lazy loading issues with encrypted columns
            identity_result = await db.execute(
                select(AgentIdentity).where(AgentIdentity.id == identity_id)
            )
            identity = identity_result.scalar_one_or_none()
            logger.info("Identity fetched: %s", identity is not None)
            
            logger.info("About to check if identity has access_token...")
            if identity and identity.access_token:
                logger.info("Identity has access token, checking expiration...")
                try:
                    # Check and refresh if needed
                    token_expiring = await check_token_expiration(identity.id, db)
                    logger.info("Token expiration check complete: expiring=%s", token_expiring)
                    
                    if token_expiring:
                        logger.info("Agent identity %s token expiring, refreshing...", identity.id)
                        await refresh_oauth_token(identity.id, db)
                        logger.info("Token refresh complete, committing...")
                        await db.commit()
                        logger.info("Commit complete, refreshing identity object...")
                        await db.refresh(identity)
                        logger.info("Identity refresh complete")

                    # Decrypt token
                    logger.info("Decrypting agent JWT...")
                    vault = get_vault()
                    agent_jwt = vault.decrypt(identity.access_token)
                    logger.info("Resolved agent JWT for passthrough session")
                except Exception as exc:
                    logger.error(
                        "Failed to resolve agent JWT for identity %s: %s",
                        identity.id,
                        exc,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=f"Passthrough authentication failed: Unable to refresh expired token. "
                        f"Please re-authenticate the agent identity.",
                    ) from exc

    try:
        engine = McpProxyEngine()
        tool_result = await engine.call_tool(
            tool=tool,
            tool_input=body.tool_args,
            db=db,
            session_id=str(mcp_session.id),  # Use resolved MCP session ID
            agent_jwt=agent_jwt,
            user_jwt=body.user_jwt,
        )
        logger.info("MCP proxy completed: tool=%s mcp_session=%s", body.tool_name, mcp_session.id)
        return McpProxyResponse(result=tool_result)

    except McpProxyError as exc:
        logger.error("MCP proxy error for %s: %s", body.tool_name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
