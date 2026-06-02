"""Control Center → Agent Runtime HTTP client.

Provides ``AgentRuntimeClient`` — the outbound HTTP client used by Control
Center to trigger agent execution on the Agent Runtime service via
mTLS-authenticated HTTP.

Control Center uses its own service certificate (``CC_CERT_PATH`` /
``CC_KEY_PATH``) for outbound peer calls so that Agent Runtime's
``ControlCenterCertificateMiddleware`` can validate the caller's identity.

Phase 5.3 — Control Flow Implementation.
"""
from __future__ import annotations

import logging
import os
import ssl
import uuid
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


class AgentRuntimeClientError(Exception):
    """Raised when an Agent Runtime HTTP call fails."""


class AgentRuntimeClient:
    """Async HTTP client for triggering execution on the Agent Runtime service.

    Uses Control Center's own service certificate for mTLS so that Agent
    Runtime's ``ControlCenterCertificateMiddleware`` can validate the caller.

    In development or when no certificate files are configured, the client
    falls back to plain HTTP so local testing works without a full PKI setup.

    Usage::

        client = AgentRuntimeClient()
        await client.trigger_execution(session_id, agent_type_id, input_data)

    Environment variables consumed:
        ``AGENT_RUNTIME_URL``     — base URL of the Agent Runtime service.
        ``COMMUNICATION_HUB_URL`` — base URL of the Communication Hub service
                                    (used to forward termination requests).
        ``CC_CERT_PATH``          — Control Center's PEM service certificate.
        ``CC_KEY_PATH``           — Control Center's PEM private key.
        ``CA_CERT_PATH``          — CA certificate for peer verification.
    """

    def __init__(
        self,
        agent_runtime_url: str | None = None,
        communication_hub_url: str | None = None,
        cert_path: str | None = None,
        key_path: str | None = None,
        ca_cert_path: str | None = None,
    ) -> None:
        self._agent_runtime_url = (
            agent_runtime_url
            or os.environ.get("AGENT_RUNTIME_URL", "http://localhost:8001")
        ).rstrip("/")
        self._communication_hub_url = (
            communication_hub_url
            or os.environ.get("COMMUNICATION_HUB_URL", "http://localhost:8002")
        ).rstrip("/")
        self._cert_path = cert_path or os.environ.get("CC_CERT_PATH")
        self._key_path = key_path or os.environ.get("CC_KEY_PATH")
        self._ca_cert_path = ca_cert_path or os.environ.get("CA_CERT_PATH")

    def _make_client(self) -> httpx.AsyncClient:
        """Return a client configured for the target URL scheme.

        - HTTPS: mTLS with CC service cert files (production).
        - HTTP:  plain client with ``X-Client-Certificate`` header carrying the
          CC service cert PEM (development/localhost).  Agent Runtime's
          ``ControlCenterCertificateMiddleware`` reads this header rather than
          the TLS handshake, so the header must be present for HTTP targets.
        """
        if (
            self._cert_path
            and self._key_path
            and Path(self._cert_path).exists()
            and Path(self._key_path).exists()
        ):
            if self._agent_runtime_url.startswith("https://"):
                # Production: use mTLS — cert is validated via TLS handshake
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.load_cert_chain(self._cert_path, self._key_path)
                if self._ca_cert_path and Path(self._ca_cert_path).exists():
                    ssl_ctx.load_verify_locations(self._ca_cert_path)
                else:
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                return httpx.AsyncClient(verify=ssl_ctx, timeout=_DEFAULT_TIMEOUT)
            else:
                # Development (HTTP): send cert as X-Client-Certificate header.
                # Newlines are escaped so the PEM is safe to carry in an HTTP header;
                # AR middleware converts them back with .replace("\\n", "\n").
                cert_pem = Path(self._cert_path).read_text()
                cert_header_value = cert_pem.replace("\n", "\\n")
                logger.info(
                    "Using X-Client-Certificate header for HTTP Agent Runtime connection"
                )
                return httpx.AsyncClient(
                    headers={"X-Client-Certificate": cert_header_value},
                    timeout=_DEFAULT_TIMEOUT,
                    verify=False,
                )

        logger.warning(
            "CC service cert not configured — using plain HTTP for Agent Runtime calls "
            "(set CC_CERT_PATH and CC_KEY_PATH for production mTLS)"
        )
        return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False)

    async def trigger_execution(
        self,
        session_id: uuid.UUID,
        agent_type_id: uuid.UUID,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST an execution trigger to Agent Runtime.

        Calls ``POST /execute`` on the Agent Runtime service, providing the
        session ID, agent type, and input data.  Agent Runtime enqueues the
        session for immediate dispatch.

        Args:
            session_id:    UUID of the pre-created AgentJob in Control Center.
            agent_type_id: UUID of the agent type to execute.
            input_data:    Optional input payload for the session.

        Returns:
            Response dict with ``session_id`` and ``status``.

        Raises:
            AgentRuntimeClientError — on any HTTP or network failure.
        """
        url = f"{self._agent_runtime_url}/execute"
        body: dict[str, Any] = {
            "session_id": str(session_id),
            "agent_type_id": str(agent_type_id),
            "input_data": input_data or {},
        }

        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                logger.info(
                    "Triggered execution for session=%s on Agent Runtime — status=%s",
                    session_id,
                    data.get("status"),
                )
                return data
            except httpx.HTTPStatusError as exc:
                raise AgentRuntimeClientError(
                    f"Agent Runtime returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except AgentRuntimeClientError:
                raise
            except Exception as exc:
                raise AgentRuntimeClientError(
                    f"Agent Runtime call failed: {exc}"
                ) from exc

    async def terminate_session(
        self,
        session_id: uuid.UUID,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Cancel an in-flight session on Agent Runtime.

        Routes through Communication Hub's
        ``POST /internal/agent/terminate/{session_id}`` endpoint, which
        forwards to Agent Runtime with mTLS using CH's
        ``service:communication-hub`` certificate.

        Direct CC → AR calls are rejected by Agent Runtime's
        ``ControlCenterCertificateMiddleware`` (which only accepts the
        communication-hub service cert), so we must go through CH — the
        same pattern used for ``/execute``.

        Phase 3.11: closes the cross-process termination gap exposed when
        an operator hits "Terminate" in the UI but the agent kept running
        because no one was telling the Agent Runtime to stop the
        in-memory task.

        Args:
            session_id: UUID of the session whose background task to cancel.
            reason:     Optional human-readable reason for logging.

        Returns:
            Response dict with ``session_id`` and ``cancelled`` on success,
            or ``None`` if Agent Runtime has no in-flight task for the
            session (e.g. it already completed) — this is the success
            case for the orchestrator because the operator's intent
            (stop the session) is satisfied either way.

        Raises:
            AgentRuntimeClientError — on any HTTP or network failure other
            than a 404 (no in-flight task).
        """
        url = f"{self._communication_hub_url}/internal/agent/terminate/{session_id}"
        body: dict[str, Any] = {}
        if reason:
            body["reason"] = reason

        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                logger.info(
                    "Terminated session=%s via Communication Hub — cancelled=%s",
                    session_id,
                    data.get("cancelled"),
                )
                return data
            except httpx.HTTPStatusError as exc:
                # 404 — no in-flight task.  This is the success case for
                # the orchestrator (the session already finished), so we
                # swallow it and return None.  Any other non-2xx is a
                # real error and propagates.
                if exc.response.status_code == 404:
                    logger.info(
                        "Agent Runtime has no in-flight task for session %s "
                        "(already completed) — operator intent is satisfied",
                        session_id,
                    )
                    return None
                raise AgentRuntimeClientError(
                    f"Communication Hub returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except AgentRuntimeClientError:
                raise
            except Exception as exc:
                raise AgentRuntimeClientError(
                    f"Communication Hub call failed: {exc}"
                ) from exc
