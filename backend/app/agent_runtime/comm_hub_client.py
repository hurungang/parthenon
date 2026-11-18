"""Tool call client for Agent Runtime.

Calls Communication Hub tool routing endpoint with mTLS authentication.
Replaces direct McpProxyEngine usage in runtime_executor.
"""
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.internal_http import internal_httpx_client
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
        #: Opaque per-paused-turn idempotency key (None outside a paused turn).
        #: Set from the durable resume record on a resume and from the turn key
        #: on a pause; never derived from user input.
        self._turn_idempotency_key: str | None = None

    def set_certificate(self, cert_path: str, key_path: str) -> None:
        """Set mTLS certificate for authentication.

        Args:
            cert_path: Path to agent certificate file
            key_path: Path to agent private key file
        """
        self._cert_path = cert_path
        self._key_path = key_path
        logger.debug("mTLS certificate configured for tool calls")

    def set_turn_idempotency_key(self, idempotency_key: str | None) -> None:
        """Bind the paused turn's idempotency key to every subsequent tool call.

        The key comes from the durable resume record (Control Center generated),
        is stable for the whole paused turn, and is only present while the turn
        is being continued from a pause.
        """
        self._turn_idempotency_key = idempotency_key or None

    @property
    def turn_idempotency_key(self) -> str | None:
        return self._turn_idempotency_key

    async def call_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        session_id: str,
        agent_type_id: str,
        conv_session_id: str | None = None,
        provenance: str | None = None,
        script_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Call a tool through Communication Hub.

        Args:
            tool_name: Tool name (e.g., "hello-world____helloWorld", "system____save_result")
            tool_args: Tool arguments
            session_id: Agent session ID
            agent_type_id: Agent type ID
            conv_session_id: Parent conversation session ID (for conversation-context interventions)
            idempotency_key: Override for the paused turn's idempotency key
                (defaults to the value bound by ``set_turn_idempotency_key``).

        Returns:
            Tool execution result

        Raises:
            CommHubToolClientError: If tool call fails
        """
        endpoint = f"{self._comm_hub_url}/internal/tools/call"

        _effective_key = idempotency_key or self._turn_idempotency_key

        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "session_id": session_id,
            "agent_type_id": agent_type_id,
        }
        if conv_session_id:
            payload["conv_session_id"] = conv_session_id
        # Script provenance tagging (G2): script vs llm + originating version.
        if provenance:
            payload["provenance"] = provenance
        if script_version:
            payload["script_version"] = script_version
        # Paused-turn idempotency key: CH forwards it to Control Center as a
        # request header so the confirmed management write commits its applied
        # marker in the same transaction.  Absent outside a paused turn.
        if _effective_key:
            payload["idempotency_key"] = _effective_key

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
            
            # Prepare headers (cert header added below when on HTTP);
            # tenant headers are attached by the internal_httpx_client hook.
            headers: dict[str, str] = {}
            if _effective_key:
                from app.agent_runtime.checkpoint_transport import (
                    turn_idempotency_headers,
                )

                headers.update(turn_idempotency_headers(_effective_key))

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

            async with internal_httpx_client(**client_kwargs) as client:
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

                # Software 3.0: best-effort per-session capture of LLM-path
                # tool calls (auto-compilation input). Script executions
                # (provenance/script_version tagged) are never captured.
                if not provenance and not script_version:
                    try:
                        from app.agent_runtime.scripts.capture import record_tool_call

                        record_tool_call(
                            session_id, tool_name, tool_args, tool_result
                        )
                    except Exception as capture_exc:
                        logger.debug(
                            "Tool-call capture skipped for '%s': %s",
                            tool_name, capture_exc,
                        )
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
        conv_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Initiate an A2A delegation request through Communication Hub.

        Args:
            target_agent_type_slug: Target receiver agent type slug.
            session_id: Current requester session ID.
            requester_role_id: Requester role UUID string for permission check.
            request_payload: Optional payload forwarded to receiver.
            session_link_id: Optional existing A2A session link for multi-turn continuation.
            conv_session_id: Parent conversation session ID for conversation-context propagation.

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
        if conv_session_id:
            conversation_metadata["conv_session_id"] = conv_session_id

        payload = {
            "target_agent_type_slug": target_agent_type_slug,
            "conversation_metadata": conversation_metadata,
            "request_payload": request_payload or {},
        }

        try:
            # When waiting for a response, the CH may hold the connection for up to
            # wait_timeout_seconds + HITL extensions.  Set the HTTP timeout high enough
            # to avoid cutting off the CH before it can return the receiver result.
            http_timeout: float = 60.0
            if wait_for_response:
                http_timeout = max(http_timeout, wait_timeout_seconds + 300.0)
            client_kwargs: dict[str, Any] = {
                "timeout": http_timeout,
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}
            # Tenant headers are attached by the internal_httpx_client hook —
            # the A2A target resolves within the calling tenant on CC.

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with internal_httpx_client(**client_kwargs) as client:
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
        conv_session_id: str | None = None,
        idempotency_key: str | None = None,
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
            conv_session_id: Parent conversation session ID for conversation-context routing.
            idempotency_key: The paused turn's opaque idempotency key. Control
                Center stores it on the resume record, so a replayed tool task
                and the confirmed write share one stable key.

        Returns:
            Dict with ``request_id`` and ``status``.

        Raises:
            CommHubToolClientError: If the call fails.
        """
        endpoint = f"{self._comm_hub_url}/internal/tools/call"

        _effective_key = idempotency_key or self._turn_idempotency_key

        tool_args: dict[str, Any] = {
            "intervention_type": intervention_type,
            "reason": reason,
        }
        if choices is not None:
            tool_args["choices"] = choices
        if prompt is not None:
            tool_args["prompt"] = prompt
        if _effective_key:
            # Consumed by CC's human_intervene handler when it registers the
            # durable resume record — registration replay then reuses it.
            tool_args["turn_idempotency_key"] = _effective_key

        payload: dict[str, Any] = {
            "tool_name": "human_intervene",
            "tool_args": tool_args,
            "session_id": session_id,
            "agent_type_id": "",
        }
        if conv_session_id:
            payload["conv_session_id"] = conv_session_id
        if _effective_key:
            payload["idempotency_key"] = _effective_key

        try:
            client_kwargs: dict[str, Any] = {
                "timeout": 60.0,
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}
            # Tenant headers are attached by the internal_httpx_client hook.
            if _effective_key:
                from app.agent_runtime.checkpoint_transport import (
                    turn_idempotency_headers,
                )

                headers.update(turn_idempotency_headers(_effective_key))

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with internal_httpx_client(**client_kwargs) as client:
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

    async def call_request_live_test(
        self,
        session_id: str,
        script_version_id: str,
        reason: str,
        agent_type_id: str,
        conv_session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Ask the operator for ONE approved live run of a saved script.

        Forwards a ``request_live_test`` system tool call to Control Center,
        which validates the request (the script version must be this agent
        type's own, saved and runnable, with a previewable ``tools.call`` set)
        and records the ledger row + the approval intervention. The tool-call
        preview on the approval card is derived server-side from the script
        source — this call never sends an operation list.

        Returns Control Center's result dict:
        ``{"status": "pending"|"refused"|"executed"|"failed"|"denied"|"expired"|…}``
        with ``live_test_request_id`` / ``intervene_request_id`` for a pending
        request, or the stored outcome when the tool task was replayed after the
        operator's decision (so the replay never asks for approval twice).

        Raises:
            CommHubToolClientError: If the call fails.
        """
        endpoint = f"{self._comm_hub_url}/internal/tools/call"

        _effective_key = idempotency_key or self._turn_idempotency_key
        tool_args: dict[str, Any] = {
            "script_version_id": script_version_id,
            "reason": reason,
            "agent_type_id": agent_type_id,
        }
        if _effective_key:
            tool_args["turn_idempotency_key"] = _effective_key

        payload: dict[str, Any] = {
            "tool_name": "system____request_live_test",
            "tool_args": tool_args,
            "session_id": session_id,
            "agent_type_id": agent_type_id,
        }
        if conv_session_id:
            payload["conv_session_id"] = conv_session_id
        if _effective_key:
            payload["idempotency_key"] = _effective_key

        try:
            client_kwargs: dict[str, Any] = {
                "timeout": 60.0,
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}
            if _effective_key:
                from app.agent_runtime.checkpoint_transport import (
                    turn_idempotency_headers,
                )

                headers.update(turn_idempotency_headers(_effective_key))

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with internal_httpx_client(**client_kwargs) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                result_data = response.json()

                if result_data.get("error"):
                    error_msg = result_data["error"]
                    logger.error("Live-test request call failed: %s", error_msg)
                    raise CommHubToolClientError(error_msg)

                payload = result_data.get("result", {})
                # Control Center wraps its tool payload in a ``result`` key and CH
                # relays that body verbatim, so unwrap the single wrapper level
                # (same normalisation the human_intervene tool applies).
                if (
                    isinstance(payload, dict)
                    and isinstance(payload.get("result"), dict)
                    and "status" not in payload
                ):
                    payload = payload["result"]
                return payload if isinstance(payload, dict) else {}

        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response else "Unknown error"
            raise CommHubToolClientError(
                f"Live-test request call failed: HTTP "
                f"{exc.response.status_code if exc.response else 'unknown'} - {detail}"
            ) from exc
        except CommHubToolClientError:
            raise
        except Exception as exc:
            raise CommHubToolClientError(f"Live-test request error: {exc}") from exc

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

        logger.info(
            "A2A wait: calling CH endpoint %s with timeout=%ss",
            endpoint,
            timeout_seconds,
        )

        # Cap timeout to CH API's max (120s) to avoid HTTP 422
        capped_timeout = min(timeout_seconds, 120.0)
        if capped_timeout != timeout_seconds:
            logger.warning(
                "A2A wait: clamping timeout from %ss to %ss (CH API max)",
                timeout_seconds,
                capped_timeout,
            )

        try:
            # The CH wait may hold the connection indefinitely for HITL.
            # Use a generous HTTP timeout (1 hour) to accommodate human response time.
            client_kwargs: dict[str, Any] = {
                "timeout": 3600.0,
                "verify": get_ssl_context(),
            }
            headers: dict[str, str] = {}
            # Tenant headers are attached by the internal_httpx_client hook.

            if self._cert_path and self._key_path:
                if self._comm_hub_url.startswith("https://"):
                    client_kwargs["cert"] = (self._cert_path, self._key_path)
                else:
                    from pathlib import Path

                    cert_content = Path(self._cert_path).read_text()
                    headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

            async with internal_httpx_client(**client_kwargs) as client:
                response = await client.get(
                    endpoint,
                    params={"timeout_seconds": capped_timeout},
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
