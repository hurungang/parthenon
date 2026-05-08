"""Tool Sync Service — fetches tool list from MCP server and upserts records."""
import json
import logging
import ssl
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import truststore
    _ssl_context: ssl.SSLContext | None = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except ImportError:
    _ssl_context = None

from app.db.models.mcp_hub import McpServer, McpServerStatus, McpTool, McpSession, McpSessionAuthType
from app.core.credential_vault import get_vault

logger = logging.getLogger(__name__)


class ToolSyncService:
    """
    Fetches the tool list from a registered MCP server's HTTP endpoint
    and upserts tools namespaced under the server slug.
    """

    def __init__(self):
        # Cache MCP session IDs per server to avoid re-initializing
        self._session_cache: dict[str, str] = {}

    async def _initialize_mcp_session(
        self, 
        server_id: str, 
        base_url: str, 
        headers: dict[str, str]
    ) -> str | None:
        """
        Initialize MCP session with the server.
        Required for Supabase MCP and other servers that need session tracking.
        
        Returns:
            Session ID from response headers, or None if not provided
        """
        mcp_url = f"{base_url.rstrip('/')}/mcp"
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "parthenon-mcp-client",
                    "version": "1.0.0"
                }
            }
        }
        
        # Build headers for initialization (must include Accept header)
        init_headers = headers.copy()
        init_headers["Content-Type"] = "application/json"
        init_headers["Accept"] = "application/json, text/event-stream"
        
        logger.info("Initializing MCP session for server %s at %s", server_id, mcp_url)
        logger.debug("Initialize headers: %s", {k: v[:50] + "..." if k.lower() == "authorization" and len(v) > 50 else v for k, v in init_headers.items()})
        logger.debug("Initialize payload: %s", init_payload)
        
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context or True) as client:
                response = await client.post(mcp_url, json=init_payload, headers=init_headers)
                
                logger.debug("Initialize response status: %s", response.status_code)
                logger.debug("Initialize response headers: %s", dict(response.headers))
                
                response.raise_for_status()
                
                # Extract session ID from response headers (case-insensitive)
                session_id = response.headers.get('mcp-session-id') or response.headers.get('Mcp-Session-Id')
                
                if session_id:
                    self._session_cache[server_id] = session_id
                    logger.info("Initialized MCP session %s for server %s", session_id[:16], server_id)
                else:
                    logger.debug("No session ID returned from initialize (server may not require it)")
                
                return session_id
        except Exception as exc:
            logger.warning("Failed to initialize MCP session for server %s: %s", server_id, exc)
            return None

    async def sync(self, server: McpServer, db: AsyncSession, session: McpSession | None = None) -> dict[str, int]:
        """
        Sync tools from the MCP server. Returns counts of added/updated/deactivated tools.

        Uses MCP protocol: JSON-RPC 2.0 POST to {base_url}/mcp with method "tools/list".
        
        Args:
            server: The MCP server to sync from
            db: Database session
            session: Optional session with credentials for authentication
        """
        # Proactive OAuth token refresh (check if token is about to expire)
        if session and session.auth_type == McpSessionAuthType.oauth2 and session.oauth_expires_at:
            from app.services.mcp.oauth_refresh import OAuthRefreshService
            
            refresh_service = OAuthRefreshService()
            refresh_success = await refresh_service.check_and_refresh_if_needed(session, db, buffer_minutes=5)
            
            if not refresh_success:
                logger.error("Failed to refresh OAuth token for session %s", session.id)
                server.status = McpServerStatus.error
                await db.flush()
                raise RuntimeError("OAuth token refresh failed")
            
            # Refresh session object to get updated credentials
            await db.refresh(session)
        
        # Use the base_url exactly as stored - it's verified during registration
        mcp_url = server.base_url.rstrip('/')
        jsonrpc_payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

        # Build authentication headers if session is provided
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        if session and session.encrypted_credentials:
            try:
                vault = get_vault()
                creds_json = vault.decrypt(session.encrypted_credentials)
                creds = json.loads(creds_json)
                
                # Add authentication based on auth type
                if session.auth_type == McpSessionAuthType.bearer_token:
                    token = creds.get("token") or creds.get("access_token")
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                elif session.auth_type == McpSessionAuthType.api_key:
                    api_key = creds.get("api_key")
                    if api_key:
                        headers["X-API-Key"] = api_key
                elif session.auth_type == McpSessionAuthType.oauth2:
                    access_token = creds.get("access_token")
                    if access_token:
                        headers["Authorization"] = f"Bearer {access_token}"
                        # Log token info (first/last 8 chars for debugging without exposing full token)
                        token_preview = f"{access_token[:8]}...{access_token[-8:]}" if len(access_token) > 16 else "[short]"
                        logger.debug("OAuth token preview: %s", token_preview)
                # basic_auth is handled by httpx auth parameter, not headers
                
                logger.info("Using session %s (%s) for tool sync", session.name, session.auth_type.value)
            except Exception as exc:
                logger.warning("Failed to decrypt session credentials: %s", exc)
        else:
            if not session:
                logger.info("No session provided for tool sync - attempting without authentication")
            elif not session.encrypted_credentials:
                logger.warning("Session %s has no credentials", session.name)

        # Initialize MCP session if not already cached (required for Supabase MCP)
        server_id_str = str(server.id)
        mcp_session_id = self._session_cache.get(server_id_str)
        
        if not mcp_session_id:
            logger.debug("No cached MCP session for server %s, initializing...", server_id_str)
            mcp_session_id = await self._initialize_mcp_session(server_id_str, server.base_url, headers)
        
        # Add Mcp-Session-Id header if we have a session ID
        if mcp_session_id:
            headers["Mcp-Session-Id"] = mcp_session_id
            logger.debug("Using MCP session ID: %s", mcp_session_id[:16])

        try:
            async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context or True) as client:
                response = await client.post(mcp_url, json=jsonrpc_payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            # Log the full error response for debugging
            error_detail = exc.response.text
            logger.error(
                "Failed to fetch tools from %s: HTTP %s - %s", 
                mcp_url, exc.response.status_code, error_detail
            )
            
            # Reactive retry on 401/403 - try OAuth refresh first for OAuth sessions
            if exc.response.status_code in (401, 403):
                retry_success = False
                
                # First, try OAuth token refresh if this is an OAuth session
                if session and session.auth_type == McpSessionAuthType.oauth2 and session.encrypted_credentials:
                    logger.info("Authentication failed, attempting OAuth token refresh for session %s", session.id)
                    from app.services.mcp.oauth_refresh import OAuthRefreshService
                    
                    refresh_service = OAuthRefreshService()
                    if await refresh_service.refresh_access_token(session, db):
                        logger.info("OAuth token refreshed, retrying request...")
                        # Refresh session object to get updated credentials
                        await db.refresh(session)
                        
                        # Rebuild headers with new token
                        try:
                            vault = get_vault()
                            creds_json = vault.decrypt(session.encrypted_credentials)
                            creds = json.loads(creds_json)
                            access_token = creds.get("access_token")
                            if access_token:
                                headers["Authorization"] = f"Bearer {access_token}"
                                
                                # Retry the request with new token
                                try:
                                    async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context or True) as client:
                                        response = await client.post(mcp_url, json=jsonrpc_payload, headers=headers)
                                        response.raise_for_status()
                                        data = response.json()
                                        logger.info("Retry successful after OAuth token refresh")
                                        retry_success = True
                                except httpx.HTTPStatusError:
                                    logger.warning("Retry failed even after OAuth token refresh")
                        except Exception as refresh_exc:
                            logger.warning("Failed to rebuild headers after OAuth refresh: %s", refresh_exc)
                    else:
                        logger.warning("OAuth token refresh failed")
                
                # If OAuth refresh didn't work or not applicable, try MCP session reinit
                if not retry_success and mcp_session_id:
                    logger.info("Trying MCP session reinitialization...")
                    self._session_cache.pop(server_id_str, None)
                    
                    # Reinitialize and retry once
                    new_session_id = await self._initialize_mcp_session(server_id_str, server.base_url, headers)
                    if new_session_id:
                        headers["Mcp-Session-Id"] = new_session_id
                        try:
                            async with httpx.AsyncClient(timeout=30.0, verify=_ssl_context or True) as client:
                                response = await client.post(mcp_url, json=jsonrpc_payload, headers=headers)
                                response.raise_for_status()
                                data = response.json()
                                logger.info("Retry successful after MCP session reinitialization")
                                retry_success = True
                        except httpx.HTTPStatusError as retry_exc:
                            error_detail = retry_exc.response.text
                            logger.error("Retry failed: HTTP %s - %s", retry_exc.response.status_code, error_detail)
                
                # If all retries failed
                if not retry_success:
                    server.status = McpServerStatus.error
                    await db.flush()
                    raise RuntimeError(f"Authentication failed after all retry attempts: {error_detail[:200]}") from exc
            else:
                # Provide helpful error messages based on status code
                if exc.response.status_code == 400:
                    error_msg = f"Bad request. Server response: {error_detail[:200]}"
                else:
                    error_msg = f"HTTP {exc.response.status_code}: {error_detail[:200]}"
                
                server.status = McpServerStatus.error
                await db.flush()
                raise RuntimeError(error_msg) from exc
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch tools from %s: %s", mcp_url, exc)
            server.status = McpServerStatus.error
            await db.flush()
            raise RuntimeError(f"Failed to fetch tools: {exc}") from exc

        if "error" in data:
            err = data["error"]
            logger.error("JSON-RPC error from %s: %s", mcp_url, err)
            server.status = McpServerStatus.error
            await db.flush()
            raise RuntimeError(f"tools/list failed: {err.get('message', err)}")

        remote_data: list[dict[str, Any]] = data["result"]["tools"]

        remote_names: set[str] = set()
        added = 0
        updated = 0

        for tool_data in remote_data:
            original_name = tool_data.get("name", "")
            if not original_name:
                continue
            namespaced_name = f"{server.slug}/{original_name}"
            remote_names.add(namespaced_name)

            # Look for existing tool record
            result = await db.execute(
                select(McpTool).where(
                    McpTool.server_id == server.id,
                    McpTool.name == namespaced_name,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.description = tool_data.get("description")
                existing.input_schema = tool_data.get("inputSchema") or tool_data.get("input_schema")
                existing.is_active = True
                updated += 1
            else:
                new_tool = McpTool(
                    server_id=server.id,
                    name=namespaced_name,
                    original_name=original_name,
                    description=tool_data.get("description"),
                    input_schema=tool_data.get("inputSchema") or tool_data.get("input_schema"),
                    is_active=True,
                )
                db.add(new_tool)
                added += 1

        # Deactivate tools that are no longer present on the server
        existing_tools_result = await db.execute(
            select(McpTool).where(
                McpTool.server_id == server.id,
                McpTool.is_active == True,  # noqa: E712
            )
        )
        existing_tools = existing_tools_result.scalars().all()
        deactivated = 0
        for tool in existing_tools:
            if tool.name not in remote_names:
                tool.is_active = False
                deactivated += 1

        # Update server sync timestamp
        server.last_synced_at = datetime.now(timezone.utc)
        server.status = McpServerStatus.active
        await db.flush()

        logger.info(
            "Synced tools for server %s: +%d updated=%d deactivated=%d",
            server.slug, added, updated, deactivated,
        )
        return {"added": added, "updated": updated, "deactivated": deactivated}
