"""Tool call client for Agent Runtime.

Calls Communication Hub tool routing endpoint with mTLS authentication.
Replaces direct McpProxyEngine usage in runtime_executor.
"""
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)
settings = get_settings()


class CommHubToolClientError(Exception):
    """Raised when a tool call through Communication Hub fails."""


class CommHubToolClient:
    """Client for calling tools through Communication Hub.

    All tool calls (external MCP + system tools) route through Communication Hub,
    which handles:
    - Permission validation (via Control Center)
    - Credential retrieval (from Control Center)
    - Routing to MCP servers or system tool endpoints
    """

    def __init__(self) -> None:
        """Initialize tool call client."""
        # Use getattr with fallback for backward compatibility
        self._comm_hub_url = getattr(settings, "communication_hub_url", "http://localhost:8002")
        self._cert_path: str | None = None
        self._key_path: str | None = None

    def set_certificate(self, cert_path: str, key_path: str) -> None:
        """Set mTLS certificate for authentication.

        Args:
            cert_path: Path to agent certificate file
            key_path: Path to agent private key file
        """
        self._cert_path = cert_path
        self._key_path = key_path
        logger.debug("mTLS certificate configured for tool calls")

    async def call_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session_id: str,
        agent_type_id: str,
    ) -> dict[str, Any]:
        """Call a tool through Communication Hub.

        Args:
            tool_name: Tool name (e.g., "hello-world____helloWorld", "system____save_result")
            tool_args: Tool arguments
            session_id: Agent session ID
            agent_type_id: Agent type ID

        Returns:
            Tool execution result

        Raises:
            CommHubToolClientError: If tool call fails
        """
        endpoint = f"{self._comm_hub_url}/internal/tools/call"

        payload = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "session_id": session_id,
            "agent_type_id": agent_type_id,
        }

        logger.info(
            "Calling tool '%s' via Communication Hub (session=%s)",
            tool_name,
            session_id[:8] if session_id else "none",
        )

        # Log certificate status for debugging
        logger.info(
            "CommHubToolClient cert status: cert_path=%s, key_path=%s",
            self._cert_path,
            self._key_path,
        )

        try:
            # Build mTLS client config
            client_kwargs: dict[str, Any] = {
                "timeout": 60.0,
                "verify": get_ssl_context(),
            }
            
            # Prepare headers
            headers: dict[str, str] = {}

            # For HTTP (localhost dev), send certificate as header
            # For HTTPS (production), use actual TLS client cert
            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    # Production: Use TLS client certificate
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                    logger.info("Using mTLS client certificate for HTTPS")
                else:
                    # Development (HTTP): Send cert as header with escaped newlines
                    # Replace actual newlines with literal \n to make it valid for HTTP headers
                    try:
                        from pathlib import Path
                        cert_content = Path(self._cert_path).read_text()
                        cert_header_value = cert_content.replace("\n", "\\n")
                        headers["X-Client-Certificate"] = cert_header_value
                        logger.info("Using X-Client-Certificate header for HTTP")
                    except Exception as exc:
                        logger.error("Failed to read certificate file: %s", exc)
            else:
                logger.warning(
                    "mTLS certificate NOT configured - tool call will fail authentication"
                )

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(endpoint, json=payload, headers=headers)

                # Log response for debugging
                logger.debug(
                    "Communication Hub response: status=%d",
                    response.status_code,
                )

                response.raise_for_status()
                result_data = response.json()

                # Check for tool execution error
                if result_data.get("error"):
                    error_msg = result_data["error"]
                    logger.error("Tool execution failed: %s", error_msg)
                    raise CommHubToolClientError(error_msg)

                # Return tool result
                tool_result = result_data.get("result", {})
                logger.info("Tool '%s' completed successfully", tool_name)
                return tool_result

        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text[:500] if exc.response else "Unknown error"
            error_msg = f"Communication Hub tool call failed: HTTP {exc.response.status_code if exc.response else 'unknown'} - {error_detail}"
            logger.error(error_msg)
            raise CommHubToolClientError(error_msg) from exc

        except httpx.RequestError as exc:
            error_msg = f"Communication Hub connection error: {exc}"
            logger.error(error_msg)
            raise CommHubToolClientError(error_msg) from exc

        except Exception as exc:
            error_msg = f"Tool call error: {exc}"
            logger.exception("Unexpected error calling tool '%s'", tool_name)
            raise CommHubToolClientError(error_msg) from exc

    async def call_a2a_request(
        self,
        target_agent_type_slug: str,
        session_id: str,
        requester_role_id: str | None,
        request_payload: dict[str, Any] | None = None,
        session_link_id: str | None = None,
        wait_for_response: bool = False,
        wait_timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        """Initiate an A2A delegation request through Communication Hub.

        Args:
            target_agent_type_slug: Target receiver agent type slug.
            session_id: Current requester session ID.
            requester_role_id: Requester role UUID string for permission check.
            request_payload: Optional payload forwarded to receiver.
            session_link_id: Optional existing A2A session link for multi-turn continuation.

        Returns:
            Parsed A2A response payload.

        Raises:
            CommHubToolClientError: If A2A request fails.
        """
        endpoint = f"{self._comm_hub_url}/internal/a2a/request"

        conversation_metadata: dict[str, Any] = {
            "requester_instance_id": session_id,
        }
        if requester_role_id:
            conversation_metadata["requester_role_id"] = requester_role_id
        if session_link_id:
            conversation_metadata["session_link_id"] = session_link_id
        if wait_for_response:
            conversation_metadata["wait_for_response"] = True
            conversation_metadata["wait_timeout_seconds"] = wait_timeout_seconds

        payload = {
            "target_agent_type_slug": target_agent_type_slug,
            "conversation_metadata": conversation_metadata,
            "request_payload": request_payload or {},
        }

        try:
            client_kwargs: dict[str, Any] = {
                "timeout": 60.0,
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response else "Unknown error"
            raise CommHubToolClientError(
                f"A2A delegation failed: HTTP {exc.response.status_code if exc.response else 'unknown'} - {detail}"
            ) from exc
        except Exception as exc:
            raise CommHubToolClientError(f"A2A delegation error: {exc}") from exc

    async def call_human_intervene(
        self,
        session_id: str,
        intervention_type: str,
        reason: str,
        choices: list[str] | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Request human intervention through Communication Hub.

        Forwards a ``human_intervene`` system tool call to Communication Hub,
        which routes it to Control Center for persist and returns a request_id.

        Args:
            session_id: Agent session ID.
            intervention_type: Type of intervention (approval, choice, text).
            reason: Explanation of why human input is needed.
            choices: Available options when type is ``choice``.
            prompt: Descriptive prompt when type is ``text``.

        Returns:
            Dict with ``request_id`` and ``status``.

        Raises:
            CommHubToolClientError: If the call fails.
        """
        endpoint = f"{self._comm_hub_url}/internal/tools/call"

        tool_args: dict[str, Any] = {
            "intervention_type": intervention_type,
            "reason": reason,
        }
        if choices is not None:
            tool_args["choices"] = choices
        if prompt is not None:
            tool_args["prompt"] = prompt

        payload = {
            "tool_name": "human_intervene",
            "tool_args": tool_args,
            "session_id": session_id,
            "agent_type_id": "",
        }

        try:
            client_kwargs: dict[str, Any] = {
                "timeout": 60.0,
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                result_data = response.json()

                if result_data.get("error"):
                    error_msg = result_data["error"]
                    logger.error("Human intervene call failed: %s", error_msg)
                    raise CommHubToolClientError(error_msg)

                return result_data.get("result", {})

        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response else "Unknown error"
            raise CommHubToolClientError(
                f"Human intervene call failed: HTTP {exc.response.status_code if exc.response else 'unknown'} - {detail}"
            ) from exc
        except Exception as exc:
            raise CommHubToolClientError(f"Human intervene error: {exc}") from exc

    async def wait_for_a2a_response(
        self,
        receiver_session_id: str,
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        """Wait for a delegated receiver session to complete.

        Args:
            receiver_session_id: Receiver session UUID string.
            timeout_seconds: Wait timeout in seconds.

        Returns:
            Response payload from Communication Hub wait endpoint.

        Raises:
            CommHubToolClientError: If wait request fails.
        """

        endpoint = f"{self._comm_hub_url}/internal/a2a/wait/{receiver_session_id}"

        try:
            client_kwargs: dict[str, Any] = {
                "timeout": max(5.0, timeout_seconds + 5.0),
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(
                    endpoint,
                    params={"timeout_seconds": timeout_seconds},
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response else "Unknown error"
            raise CommHubToolClientError(
                f"A2A wait failed: HTTP {exc.response.status_code if exc.response else 'unknown'} - {detail}"
            ) from exc
        except Exception as exc:
            raise CommHubToolClientError(f"A2A wait error: {exc}") from exc
