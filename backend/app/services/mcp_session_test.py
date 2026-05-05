"""MCP Session connection testing service."""

import json
import logging
import os
from typing import Any

import httpx

from app.core.credential_vault import get_vault
from app.db.models.mcp_hub import McpServer, McpSession, McpSessionAuthType

logger = logging.getLogger(__name__)


class ConnectionTestResult:
    """Result of a connection test."""

    def __init__(self, success: bool, message: str, status_code: int | None = None):
        self.success = success
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        result = {
            "success": self.success,
            "message": self.message,
        }
        if self.status_code is not None:
            result["status_code"] = self.status_code
        return result


async def test_mcp_session_connection(
    server: McpServer,
    session: McpSession,
) -> ConnectionTestResult:
    """Test connection to an MCP server with the given session credentials.

    Args:
        server: The MCP server to connect to.
        session: The session with credentials to use.

    Returns:
        ConnectionTestResult indicating success or failure with details.
    """
    try:
        # Prepare headers based on auth type
        headers: dict[str, str] = {}
        
        # Decrypt credentials if present
        credentials: dict[str, Any] | None = None
        if session.encrypted_credentials:
            vault = get_vault()
            decrypted_json = vault.decrypt(session.encrypted_credentials)
            credentials = json.loads(decrypted_json)

        # Build auth headers based on auth type
        if session.auth_type == McpSessionAuthType.api_key:
            if credentials and "api_key" in credentials:
                headers["Authorization"] = f"Bearer {credentials['api_key']}"
            else:
                return ConnectionTestResult(
                    success=False,
                    message="API key missing from credentials"
                )

        elif session.auth_type == McpSessionAuthType.bearer_token:
            if credentials and "token" in credentials:
                headers["Authorization"] = f"Bearer {credentials['token']}"
            else:
                return ConnectionTestResult(
                    success=False,
                    message="Bearer token missing from credentials"
                )

        elif session.auth_type == McpSessionAuthType.basic_auth:
            if credentials and "username" in credentials and "password" in credentials:
                # Use encoded basic auth if available, otherwise build it
                if "encoded" in credentials:
                    headers["Authorization"] = f"Basic {credentials['encoded']}"
                else:
                    import base64
                    encoded = base64.b64encode(
                        f"{credentials['username']}:{credentials['password']}".encode()
                    ).decode()
                    headers["Authorization"] = f"Basic {encoded}"
            else:
                return ConnectionTestResult(
                    success=False,
                    message="Username/password missing from credentials"
                )

        elif session.auth_type == McpSessionAuthType.oauth2:
            if credentials and "access_token" in credentials:
                headers["Authorization"] = f"Bearer {credentials['access_token']}"
            else:
                return ConnectionTestResult(
                    success=False,
                    message="OAuth2 access token missing from credentials"
                )

        elif session.auth_type == McpSessionAuthType.none:
            # No authentication needed
            pass

        # Try to connect to the MCP server
        # First try a GET to the base URL, then try common MCP endpoints
        test_urls = [
            server.base_url,
            f"{server.base_url}/health",
            f"{server.base_url}/v1/tools",
            f"{server.base_url}/mcp/v1/tools",
        ]
        
        # Check if SSL verification should be disabled (for dev/testing)
        verify_ssl = os.getenv("MCP_OAUTH_VERIFY_SSL", "true").lower() != "false"

        last_error = None
        for url in test_urls:
            try:
                async with httpx.AsyncClient(timeout=10.0, verify=verify_ssl) as client:
                    response = await client.get(url.rstrip("/"), headers=headers)
                    
                    # Consider 2xx and 401/403 as "connection successful"
                    # 401/403 means we reached the server but auth failed
                    if response.status_code < 500:
                        if response.status_code < 300:
                            logger.info(
                                "Connection test successful for session %s at %s (HTTP %d)",
                                session.id, url, response.status_code
                            )
                            return ConnectionTestResult(
                                success=True,
                                message=f"Connected successfully (HTTP {response.status_code})",
                                status_code=response.status_code
                            )
                        elif response.status_code in (401, 403):
                            logger.warning(
                                "Connection test reached server but auth failed for session %s at %s (HTTP %d)",
                                session.id, url, response.status_code
                            )
                            return ConnectionTestResult(
                                success=False,
                                message=f"Server reached but authentication failed (HTTP {response.status_code})",
                                status_code=response.status_code
                            )
                        elif response.status_code == 404:
                            # 404 is okay - server is reachable, just wrong endpoint
                            # Try next URL
                            continue
                    
                    last_error = f"HTTP {response.status_code}"
                    
            except httpx.ConnectError as exc:
                last_error = f"Connection error: {exc}"
                logger.debug("Connection test failed for %s: %s", url, exc)
                continue
            except httpx.TimeoutException:
                last_error = "Connection timeout"
                logger.debug("Connection test timeout for %s", url)
                continue
            except Exception as exc:
                last_error = str(exc)
                logger.debug("Connection test error for %s: %s", url, exc)
                continue

        # If we got here, none of the URLs worked
        return ConnectionTestResult(
            success=False,
            message=f"Could not connect to MCP server: {last_error or 'All endpoints failed'}"
        )

    except Exception as exc:
        logger.error("Unexpected error testing MCP session connection: %s", exc)
        return ConnectionTestResult(
            success=False,
            message=f"Connection test failed: {str(exc)}"
        )
