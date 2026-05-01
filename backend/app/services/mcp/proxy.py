"""MCP Proxy Engine — routes tool-call invocations to the correct server session."""

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.mcp_hub import McpSession, McpSessionAuthType, McpTool

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
        Invoke a tool on its MCP server.

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

        # Build the tool call URL
        base_url = tool.server.base_url.rstrip("/")
        call_url = f"{base_url}/tools/call"

        # Prepare headers with decrypted credentials
        headers = self._build_auth_headers(mcp_session)

        payload = {
            "name": tool.original_name,
            "arguments": tool_input,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(call_url, json=payload, headers=headers)
                response.raise_for_status()
                result: dict[str, Any] = response.json()
                return result
        except httpx.HTTPStatusError as exc:
            logger.error("Tool call failed for %s: HTTP %d", tool.name, exc.response.status_code)
            raise McpProxyError(f"Tool call failed: HTTP {exc.response.status_code}") from exc
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
                select(McpSession)
                .where(
                    McpSession.server_id == server_id,
                    McpSession.is_active == True,  # noqa: E712
                )
                .limit(1)
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
        elif session.auth_type == McpSessionAuthType.bearer_token:
            token = creds.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
        elif session.auth_type == McpSessionAuthType.basic_auth:
            import base64

            user = creds.get("username", "")
            pwd = creds.get("password", "")
            encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers
