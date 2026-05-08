"""MCP Proxy Engine — routes tool-call invocations to the correct server session."""
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.mcp_hub import McpSession, McpSessionAuthType, McpTool
from app.services.mcp.oauth_refresh import OAuthRefreshService

logger = logging.getLogger(__name__)


class McpProxyError(Exception):
    """Raised when an MCP tool call fails."""


class McpProxyEngine:
    """
    Routes a tool-call invocation to the correct MCP server session,
    injects decrypted credentials at call time, and returns the structured result.

    Credentials are never logged.
    """

    async def call_tool(
        self,
        tool: McpTool,
        tool_input: dict[str, Any],
        db: AsyncSession,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Invoke a tool on its MCP server using JSON-RPC 2.0 protocol.

        Args:
            tool: The McpTool record to invoke.
            tool_input: Input parameters for the tool.
            db: Database session.
            session_id: Optional specific session ID to use; otherwise uses the first active session.

        Returns:
            Structured tool result as a dict.
        """
        # Resolve the session
        mcp_session = await self._resolve_session(tool.server_id, session_id, db)

        # Auto-refresh OAuth token if needed (checks expiry and refreshes proactively)
        if mcp_session.auth_type == McpSessionAuthType.oauth2:
            refresh_service = OAuthRefreshService()
            refresh_success = await refresh_service.check_and_refresh_if_needed(
                mcp_session, db, buffer_minutes=5
            )
            if not refresh_success:
                logger.error(
                    "Failed to refresh OAuth token for session %s before tool call",
                    mcp_session.id
                )
                raise McpProxyError(
                    "OAuth token expired and refresh failed. Please re-authenticate the session."
                )
            # Refresh session object to get updated credentials
            await db.refresh(mcp_session)

        # Use the base_url exactly as stored - it's verified during registration
        endpoint_url = tool.server.base_url.rstrip("/")

        logger.info(
            "MCP tool invocation: server=%s, endpoint=%s, tool=%s (original: %s)",
            tool.server.name,
            endpoint_url,
            tool.name,
            tool.original_name
        )

        # Prepare headers with decrypted credentials
        headers = self._build_auth_headers(mcp_session)
        
        # Add MCP session ID to headers
        logger.debug(
            "Session %s identity_binding: %s",
            mcp_session.id,
            mcp_session.identity_binding if mcp_session.identity_binding else "None"
        )
        
        if mcp_session.identity_binding and isinstance(mcp_session.identity_binding, dict):
            mcp_session_id = mcp_session.identity_binding.get("mcp_session_id")
            if mcp_session_id:
                headers['Mcp-Session-Id'] = mcp_session_id
                logger.info("Added Mcp-Session-Id header: %s...", mcp_session_id[:30])
            else:
                logger.warning(
                    "Session %s has identity_binding but no mcp_session_id. "
                    "This session needs to be re-authenticated to get MCP session ID.",
                    mcp_session.id
                )
        else:
            logger.warning(
                "Session %s (auth_type=%s) has no identity_binding. "
                "For OAuth2 sessions, re-authenticate to initialize MCP session.",
                mcp_session.id,
                mcp_session.auth_type.value
            )

        # Build JSON-RPC 2.0 payload
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool.original_name,
                "arguments": tool_input,
            }
        }

        # Add Accept header for MCP servers that require both JSON and SSE support
        headers["Accept"] = "application/json, text/event-stream"

        logger.debug("MCP JSON-RPC payload: %s", json.dumps(payload, indent=2))

        try:
            async with httpx.AsyncClient(timeout=60.0, verify=get_ssl_context()) as client:
                response = await client.post(endpoint_url, json=payload, headers=headers)
                
                logger.debug("MCP response status: %d", response.status_code)
                
                if response.status_code >= 400:
                    logger.error("MCP error response: %s", response.text[:500])
                
                response.raise_for_status()
                
                # Parse JSON-RPC response
                json_response: dict[str, Any] = response.json()
                
                # Check for JSON-RPC error
                if "error" in json_response:
                    error_msg = json_response["error"].get("message", "Unknown MCP error")
                    logger.error("MCP JSON-RPC error for %s: %s", tool.name, error_msg)
                    raise McpProxyError(f"MCP error: {error_msg}")
                
                # Return the result field from JSON-RPC response
                return json_response.get("result", {})
                
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Tool call failed for %s: HTTP %d", tool.name, exc.response.status_code
            )
            raise McpProxyError(
                f"Tool call failed: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("Tool call network error for %s: %s", tool.name, exc)
            raise McpProxyError(f"Tool call network error: {exc}") from exc

    async def _resolve_session(
        self,
        server_id: Any,
        session_id: str | None,
        db: AsyncSession,
    ) -> McpSession:
        """Resolve the MCP session to use for a tool call."""
        from sqlalchemy.orm import selectinload

        if session_id:
            result = await db.execute(
                select(McpSession).where(
                    McpSession.id == session_id,
                    McpSession.server_id == server_id,
                    McpSession.is_active == True,  # noqa: E712
                )
            )
        else:
            result = await db.execute(
                select(McpSession).where(
                    McpSession.server_id == server_id,
                    McpSession.is_active == True,  # noqa: E712
                ).limit(1)
            )

        session = result.scalar_one_or_none()
        if not session:
            raise McpProxyError(f"No active session found for server {server_id}")
        return session

    def _build_auth_headers(self, session: McpSession) -> dict[str, str]:
        """Build auth headers by decrypting session credentials."""
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if not session.encrypted_credentials:
            return headers

        try:
            vault = get_vault()
            creds_json = vault.decrypt(session.encrypted_credentials)
            creds: dict[str, Any] = json.loads(creds_json)
        except Exception as exc:
            logger.error("Failed to decrypt credentials for session %s", session.id)
            raise McpProxyError("Failed to decrypt session credentials") from exc

        # Build auth header based on auth type — never log credential values
        if session.auth_type == McpSessionAuthType.api_key:
            api_key = creds.get("api_key", "")
            headers["X-API-Key"] = api_key
            logger.debug("Using API key authentication for session %s", session.id)
        elif session.auth_type == McpSessionAuthType.bearer_token:
            token = creds.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
            logger.debug("Using bearer token authentication for session %s", session.id)
        elif session.auth_type == McpSessionAuthType.oauth2:
            # OAuth2 uses access_token as Bearer token
            access_token = creds.get("access_token", "")
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
                # Log token preview for debugging without exposing full token
                token_preview = f"{access_token[:8]}...{access_token[-8:]}" if len(access_token) > 16 else "[short]"
                logger.debug("Using OAuth2 access token for session %s: %s", session.id, token_preview)
            else:
                logger.warning("OAuth2 session %s has no access_token in credentials", session.id)
        elif session.auth_type == McpSessionAuthType.basic_auth:
            import base64
            user = creds.get("username", "")
            pwd = creds.get("password", "")
            encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
            logger.debug("Using basic auth for session %s (user: %s)", session.id, user)

        return headers
