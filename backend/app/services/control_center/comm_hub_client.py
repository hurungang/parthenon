"""Control Center → Communication Hub HTTP client.

Provides ``CommunicationHubClient`` — the outbound HTTP client used by
Control Center to dispatch messages (agent results, system notifications)
to the Communication Hub broker via mTLS-authenticated HTTP.

Control Center uses its own service certificate (``CC_CERT_PATH`` /
``CC_KEY_PATH``) for outbound calls so that Communication Hub's
``ControlPlaneMiddleware`` can validate the caller's identity.

Phase 5.4 — Control Flow Implementation.
"""
from __future__ import annotations

import logging
import os
import ssl
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.tenant_context import TenantContext
from app.core.tenant_signature import tenant_context_headers

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_CC_CERT_PATH = "certs/control-center/service-cert.pem"
_DEFAULT_CC_KEY_PATH = "certs/control-center/service-key.pem"


def _allow_insecure_internal_fallback() -> bool:
    """Return True only for explicit development-mode insecure fallback opt-in."""
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


class CommunicationHubClientError(Exception):
    """Raised when a Communication Hub HTTP call fails."""


class CommunicationHubClient:
    """Async HTTP client for dispatching messages via the Communication Hub.

    Uses Control Center's own service certificate for mTLS so that
    Communication Hub's ``ControlPlaneMiddleware`` can validate the caller.

    In development or when no certificate files are configured, the client
    falls back to plain HTTP so local testing works without a full PKI setup.

    Usage::

        client = CommunicationHubClient()
        await client.dispatch_message(
            session_id=session_id,
            message_type="agent_result",
            content={"output": "..."},
        )

    Environment variables consumed:
        ``COMM_HUB_URL``  — base URL of the Communication Hub service.
        ``CC_CERT_PATH``  — Control Center's PEM service certificate.
        ``CC_KEY_PATH``   — Control Center's PEM private key.
        ``CA_CERT_PATH``  — CA certificate for peer verification.
    """

    def __init__(
        self,
        comm_hub_url: str | None = None,
        cert_path: str | None = None,
        key_path: str | None = None,
        ca_cert_path: str | None = None,
    ) -> None:
        self._comm_hub_url = (
            comm_hub_url
            or os.environ.get("COMM_HUB_URL", "http://localhost:8002")
        ).rstrip("/")
        # CWD-independent resolution (FIX-20261031-131030): explicit absolute
        # configuration wins; relative paths anchor to the backend root.
        from app.core.cert_paths import resolve_cert_path

        self._cert_path = resolve_cert_path(
            cert_path or os.environ.get("CC_CERT_PATH", _DEFAULT_CC_CERT_PATH)
        )
        self._key_path = resolve_cert_path(
            key_path or os.environ.get("CC_KEY_PATH", _DEFAULT_CC_KEY_PATH)
        )
        self._ca_cert_path = resolve_cert_path(ca_cert_path or os.environ.get("CA_CERT_PATH"))

    def _make_client(self) -> httpx.AsyncClient:
        """Return a client configured for HTTPS mTLS or HTTP header cert auth."""
        if (
            self._cert_path
            and self._key_path
            and Path(self._cert_path).exists()
            and Path(self._key_path).exists()
        ):
            if self._comm_hub_url.startswith("https://"):
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.load_cert_chain(self._cert_path, self._key_path)
                if self._ca_cert_path and Path(self._ca_cert_path).exists():
                    ssl_ctx.load_verify_locations(self._ca_cert_path)
                else:
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                return httpx.AsyncClient(verify=ssl_ctx, timeout=_DEFAULT_TIMEOUT)

            # Development (HTTP): forward the service cert via header.
            # Communication Hub middleware restores escaped newlines.
            cert_pem = Path(self._cert_path).read_text()
            cert_header_value = cert_pem.replace("\n", "\\n")
            logger.info(
                "Using X-Client-Certificate header for HTTP Communication Hub connection"
            )
            return httpx.AsyncClient(
                headers={"X-Client-Certificate": cert_header_value},
                timeout=_DEFAULT_TIMEOUT,
                verify=False,
            )

        if _allow_insecure_internal_fallback():
            logger.warning(
                "CC service cert not configured — using insecure development fallback for "
                "Communication Hub calls"
            )
            return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False)

        raise CommunicationHubClientError(
            "Control Center service certificate is required for Communication Hub internal calls"
        )

    async def dispatch_message(
        self,
        session_id: uuid.UUID,
        message_type: str,
        content: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
        tenant_context: TenantContext | None = None,
    ) -> dict[str, Any]:
        """POST a message dispatch request to Communication Hub.

        Calls ``POST /internal/dispatch`` on the Communication Hub service.
        The Hub publishes the message to the session's Redis pub/sub channel
        so that connected WebSocket subscribers receive it.

        When ``tenant_context`` is provided (multi-tenant mode), the signed
        tenant context headers are attached so the Hub can verify and bind
        the tenant; when it is None, no tenant headers are added.

        Args:
            session_id:     UUID of the session whose channel receives the message.
            message_type:   Semantic type label (e.g. ``"agent_result"``).
            content:        Message body — dict or pre-serialised string.
            metadata:       Optional extra key/value pairs attached to the message.
            tenant_context: Resolved tenant context (None in single-tenant mode).

        Returns:
            Response dict with ``dispatched``, ``channel``, and ``subscribers``.

        Raises:
            CommunicationHubClientError — on any HTTP or network failure.
        """
        url = f"{self._comm_hub_url}/internal/dispatch"
        body: dict[str, Any] = {
            "session_id": str(session_id),
            "message_type": message_type,
            "content": content,
        }
        if metadata:
            body["metadata"] = metadata

        headers = tenant_context_headers(tenant_context)

        async with self._make_client() as client:
            try:
                resp = await client.post(
                    url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                logger.info(
                    "Dispatched %s for session=%s via Communication Hub (%d subscribers)",
                    message_type,
                    session_id,
                    data.get("subscribers", 0),
                )
                return data
            except httpx.HTTPStatusError as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except CommunicationHubClientError:
                raise
            except Exception as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub call failed: {exc}"
                ) from exc

    async def trigger_execution(
        self,
        session_id: uuid.UUID,
        agent_type_id: uuid.UUID,
        input_data: dict[str, Any] | None = None,
        tenant_context: TenantContext | None = None,
    ) -> dict[str, Any]:
        """POST an agent execution trigger to Communication Hub.

        Calls ``POST /internal/agent/execute`` on the Communication Hub service,
        which forwards the request to Agent Runtime.

        When ``tenant_context`` is provided (multi-tenant mode), the signed
        tenant context headers are attached; when it is None, no tenant
        headers are added.

        Args:
            session_id:     UUID of the pre-created AgentJob in Control Center.
            agent_type_id:  UUID of the agent type to execute.
            input_data:     Optional input payload for the session.
            tenant_context: Resolved tenant context (None in single-tenant mode).

        Returns:
            Response dict with ``session_id`` and ``status``.

        Raises:
            CommunicationHubClientError — on any HTTP or network failure.
        """
        url = f"{self._comm_hub_url}/internal/agent/execute"
        body: dict[str, Any] = {
            "session_id": str(session_id),
            "agent_type_id": str(agent_type_id),
            "input_data": input_data or {},
        }
        headers = tenant_context_headers(tenant_context)

        async with self._make_client() as client:
            try:
                resp = await client.post(
                    url, json=body, headers=headers, timeout=_DEFAULT_TIMEOUT
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                logger.info(
                    "Triggered execution for session=%s via Communication Hub — status=%s",
                    session_id,
                    data.get("status"),
                )
                return data
            except httpx.HTTPStatusError as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except CommunicationHubClientError:
                raise
            except Exception as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub agent execute call failed: {exc}"
                ) from exc

    async def forward_live_test(
        self,
        *,
        live_test_request_id: str,
        conversation_session_id: str,
        target_agent_type_id: str,
        script_version_id: str | None,
        script_name: str | None,
        script_version_label: str | None,
        python_source: str,
        input_context: dict[str, Any] | None = None,
        tenant_context: TenantContext | None = None,
    ) -> dict[str, Any]:
        """Run ONE operator-approved live test through ``CH → AR``.

        A live test runs the approved **script** end to end — never individual
        MCP tool calls; MCP tools are assumed to work. This is the ONLY live
        route in the platform. Control Center has already validated the ledger
        (tenant, ``status``, single-shot claim, expiry) and forwards the
        approved version's source verbatim:

        1. CC → CH ``POST /internal/live-test/run`` (CC service certificate);
        2. CH → AR ``POST /internal/live-test/run`` (CH service certificate);
        3. AR executes the script once in the real sandbox through the subject
           agent type's own CH tool route — its own identity, tenant and
           existing grants, no override, no shared/elevated identity. The
           script's ``tools.call(...)`` lines are the only egress.

        ``input_context`` is the reference execution's input (server-derived, the
        same context replay uses) so the script runs the real scenario.

        Neither CH nor AR can originate a live test; AR/CH add no authorization
        of their own beyond their existing control-plane checks and the
        capability check against the subject's own grants.

        Returns AR's contract dict:
        ``{status, executed_operations[script_run], started_at, finished_at,
        error}``. A run failure surfaces as ``status="failed"`` — it is never
        retried here and never committed twice.

        Raises:
            CommunicationHubClientError — on any HTTP or network failure.
        """
        url = f"{self._comm_hub_url}/internal/live-test/run"
        body: dict[str, Any] = {
            "live_test_request_id": str(live_test_request_id),
            "conversation_session_id": str(conversation_session_id),
            "target_agent_type_id": str(target_agent_type_id),
            "script_version_id": (
                str(script_version_id) if script_version_id else None
            ),
            "script_name": script_name,
            "script_version_label": script_version_label,
            "python_source": python_source,
            "input_context": input_context or {},
        }
        headers = tenant_context_headers(tenant_context)
        # The run bound is enforced by AR too; this is the transport backstop.
        try:
            from app.core.config import get_settings

            _run_timeout = int(
                getattr(
                    get_settings(),
                    "optimizer_live_test_run_timeout_seconds",
                    120,
                )
            )
        except Exception:  # noqa: BLE001 — a missing setting must not block the call
            _run_timeout = 120
        timeout = float(max(30, _run_timeout))

        async with self._make_client() as client:
            try:
                resp = await client.post(
                    url, json=body, headers=headers, timeout=timeout
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                logger.info(
                    "Live test %s forwarded to Agent Runtime (status=%s, "
                    "script_version=%s, source_chars=%d)",
                    live_test_request_id,
                    data.get("status"),
                    script_version_id,
                    len(python_source or ""),
                )
                return data
            except httpx.HTTPStatusError as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except CommunicationHubClientError:
                raise
            except Exception as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub live-test call failed: {exc}"
                ) from exc

    async def forward_sandboxed_script(
        self,
        *,
        python_source: str,
        session_id: str,
        agent_type_id: str,
        input_context: dict[str, Any] | None = None,
        tenant_context: TenantContext | None = None,
        reference_tool_responses: list[dict[str, Any]] | None = None,
        replay_required: bool = False,
    ) -> dict[str, Any]:
        """Execute inline ``python_source`` in the Agent Runtime sandbox.

        Routes CC → CH ``POST /internal/script-tools/forward`` (this hop
        presents CC's service certificate — kept fresh by CC's own
        startup/daily self-renewal; ``/internal/tools/call`` is NOT usable
        from CC because ControlPlaneMiddleware only accepts agent-runtime
        certificates on ``/internal/tools/``). CH then forwards to Agent
        Runtime's ``/internal/script-tools/execute`` using CH's OWN service
        certificate — the exact same CH→AR hop ``script____<name>`` tools
        take — where the sandbox runs. Scripts execute ONLY in Agent Runtime
        (top-priority rule) — Control Center never runs the sandbox.

        Optimization verification is REPLAY-ONLY: when ``replay_required`` is
        set, AR uses its replay tool client and answers every ``tools.call``
        from ``reference_tool_responses`` (the recorded transcript) — it never
        reaches the live session-bound MCP client and never mutates data.

        Args:
            python_source:  Full script source (defines ``run(context, tools)``).
            session_id:     Session identity for the sandbox + tool calls.
            agent_type_id:  Agent type identity ("" when unresolvable).
            input_context:  Optional input dict — becomes the script's ``context``.
            tenant_context: Resolved tenant context (None in single-tenant mode).
            reference_tool_responses: Recorded ``{tool, arguments, response}``
                entries replayed for every script tool call.
            replay_required: Hard replay-only switch — AR refuses to fall back
                to live tool calls.

        Returns:
            AR contract dict: ``{"result": ..., "error": str | None}`` — a
            sandbox compile/violation/runtime failure surfaces as ``error``.

        Raises:
            CommunicationHubClientError — on any HTTP or network failure.
        """
        url = f"{self._comm_hub_url}/internal/script-tools/forward"
        body: dict[str, Any] = {
            "python_source": python_source,
            "session_id": str(session_id),
            "agent_type_id": str(agent_type_id or ""),
            "tool_args": {"input": input_context or {}},
        }
        if reference_tool_responses:
            body["reference_tool_responses"] = reference_tool_responses
        if replay_required:
            body["replay_required"] = True
        headers = tenant_context_headers(tenant_context)

        async with self._make_client() as client:
            try:
                # Sandbox wall-time caps can exceed the default 30s timeout.
                resp = await client.post(
                    url, json=body, headers=headers, timeout=120.0
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                logger.info(
                    "Executed sandboxed script for session=%s via Communication "
                    "Hub → Agent Runtime (error=%s)",
                    session_id,
                    data.get("error"),
                )
                return data
            except httpx.HTTPStatusError as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except CommunicationHubClientError:
                raise
            except Exception as exc:
                raise CommunicationHubClientError(
                    f"Communication Hub script-tool call failed: {exc}"
                ) from exc
