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

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


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
        self._cert_path = cert_path or os.environ.get("CC_CERT_PATH")
        self._key_path = key_path or os.environ.get("CC_KEY_PATH")
        self._ca_cert_path = ca_cert_path or os.environ.get("CA_CERT_PATH")

    def _make_client(self) -> httpx.AsyncClient:
        """Return an mTLS-configured client, or plain HTTP fallback for dev."""
        if (
            self._cert_path
            and self._key_path
            and Path(self._cert_path).exists()
            and Path(self._key_path).exists()
        ):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.load_cert_chain(self._cert_path, self._key_path)
            if self._ca_cert_path and Path(self._ca_cert_path).exists():
                ssl_ctx.load_verify_locations(self._ca_cert_path)
            else:
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
            return httpx.AsyncClient(verify=ssl_ctx, timeout=_DEFAULT_TIMEOUT)

        logger.warning(
            "CC service cert not configured — using plain HTTP for Communication Hub calls "
            "(set CC_CERT_PATH and CC_KEY_PATH for production mTLS)"
        )
        return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, verify=False)

    async def dispatch_message(
        self,
        session_id: uuid.UUID,
        message_type: str,
        content: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST a message dispatch request to Communication Hub.

        Calls ``POST /internal/dispatch`` on the Communication Hub service.
        The Hub publishes the message to the session's Redis pub/sub channel
        so that connected WebSocket subscribers receive it.

        Args:
            session_id:    UUID of the session whose channel receives the message.
            message_type:  Semantic type label (e.g. ``"agent_result"``).
            content:       Message body — dict or pre-serialised string.
            metadata:      Optional extra key/value pairs attached to the message.

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

        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
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
    ) -> dict[str, Any]:
        """POST an agent execution trigger to Communication Hub.

        Calls ``POST /internal/agent/execute`` on the Communication Hub service,
        which forwards the request to Agent Runtime.

        Args:
            session_id:    UUID of the pre-created AgentJob in Control Center.
            agent_type_id: UUID of the agent type to execute.
            input_data:    Optional input payload for the session.

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

        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
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
