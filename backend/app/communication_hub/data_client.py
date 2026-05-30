"""Communication Hub — Control Center data client.

Fetches session data, user permissions, and revocation status from Control Center
via HTTP calls authenticated with the Communication Hub service mTLS certificate.

Communication Hub has ZERO direct database access.  All data flows through this client.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0  # seconds


def _allow_insecure_internal_fallback() -> bool:
    """Return True only for explicit development-mode insecure fallback opt-in."""
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


class ControlCenterDataError(Exception):
    """Raised when a Control Center data API call fails."""


class ControlCenterDataClient:
    """HTTP client for Control Center internal data APIs using service mTLS.

    Usage::

        manager = CommHubCertificateManager()
        client = ControlCenterDataClient(cert_manager=manager)

        session = await client.get_session(session_id)
        history = await client.get_conversation_history(session_id)
        perms = await client.get_user_permissions(user_id)
        revoked = await client.check_revocation_status(serial)

    The client reuses the mTLS-configured ``httpx.AsyncClient`` from the
    ``CommHubCertificateManager`` so certificate rotation is transparent.
    """

    def __init__(
        self,
        cert_manager: Any,  # app.communication_hub.certificate_manager.CommHubCertificateManager
        control_center_url: str | None = None,
    ) -> None:
        self._cert_manager = cert_manager
        self._control_center_url = (
            control_center_url
            or os.environ.get("CONTROL_CENTER_URL", "http://localhost:8000")
        ).rstrip("/")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _make_client(self) -> httpx.AsyncClient:
        """Return an mTLS-configured HTTP client using the current service cert."""
        if self._cert_manager is None:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "CH data client using insecure HTTP fallback because "
                    "ALLOW_INSECURE_INTERNAL_CALL_FALLBACK is enabled in development"
                )
                return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
            raise RuntimeError(
                "Communication Hub certificate manager is unavailable; "
                "internal Control Center calls fail closed"
            )
        try:
            return self._cert_manager.configure_mtls_client()
        except Exception as exc:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "CH certificate not loaded; using insecure HTTP fallback in development: %s",
                    exc,
                )
                return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
            raise RuntimeError(
                "Communication Hub service certificate is required for internal calls"
            ) from exc

    def _url(self, path: str) -> str:
        return f"{self._control_center_url}/api/v1{path}"

    async def _get(self, path: str) -> dict[str, Any]:
        url = self._url(path)
        async with self._make_client() as client:
            try:
                resp = await client.get(url, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise ControlCenterDataError(
                    f"CC GET {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(f"CC GET {url} failed: {exc}") from exc

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self._url(path)
        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise ControlCenterDataError(
                    f"CC POST {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(f"CC POST {url} failed: {exc}") from exc

    # ── Session data ──────────────────────────────────────────────────────────

    async def get_session(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        """Return session metadata, or None if not found.

        Calls ``GET /internal/data/sessions/{session_id}``.
        Returns dict with: id, agent_type_id, triggered_by_user_id, input_data,
        status, started_at, completed_at, output_data, error_message,
        conversation_history, created_at.
        """
        try:
            return await self._get(f"/internal/data/sessions/{session_id}")
        except ControlCenterDataError as exc:
            if "404" in str(exc):
                return None
            raise

    async def get_conversation_history(
        self, session_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Return ordered conversation messages for a session.

        Calls ``GET /internal/data/sessions/{session_id}/history``.
        Returns a list of message dicts (role + content).
        """
        data = await self._get(f"/internal/data/sessions/{session_id}/history")
        return data.get("messages", [])

    # ── Permissions ───────────────────────────────────────────────────────────

    async def get_user_permissions(self, user_id: uuid.UUID) -> list[str]:
        """Return the resolved MCP tool permission set for a user.

        Calls ``GET /internal/data/users/{user_id}/permissions``.
        Returns a sorted list of allowed tool identifier strings.
        """
        data = await self._get(f"/internal/data/users/{user_id}/permissions")
        return data.get("allowed_tools", [])

    # ── Certificate revocation ────────────────────────────────────────────────

    async def check_revocation_status(self, serial: str) -> bool:
        """Return True if the certificate serial is revoked.

        Calls ``GET /internal/certificates/revoked/{serial}``.
        Returns True on error (fail-closed) unless explicit dev-only opt-in enables
        insecure fallback behavior.
        """
        try:
            data = await self._get(f"/internal/certificates/revoked/{serial}")
            return bool(data.get("revoked", False))
        except Exception as exc:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "Revocation check for serial %s failed: %s — insecure dev fallback treats as not revoked",
                    serial,
                    exc,
                )
                return False
            logger.error(
                "Revocation check for serial %s failed: %s — fail-closed treats certificate as revoked",
                serial,
                exc,
            )
            return True

    # ── Auto-naming ───────────────────────────────────────────────────────────

    async def auto_name_conversation(
        self,
        conv_session_id: uuid.UUID,
        first_user_message: str,
        agent_type_id: uuid.UUID | None = None,
    ) -> str | None:
        """Generate and persist a conversation session title via Control Center.

        Calls ``POST /internal/data/conversations/{conv_session_id}/auto-name``.
        Returns the generated title, or None if generation failed.
        """
        body: dict[str, Any] = {"first_user_message": first_user_message}
        if agent_type_id is not None:
            body["agent_type_id"] = str(agent_type_id)

        try:
            data = await self._post(
                f"/internal/data/conversations/{conv_session_id}/auto-name",
                body,
            )
            return data.get("title")
        except Exception as exc:
            logger.warning(
                "Auto-naming for conversation %s failed: %s", conv_session_id, exc
            )
            return None

    async def prepare_conversation_turn(
        self,
        conv_session_id: uuid.UUID,
        user_message: str,
    ) -> dict[str, Any]:
        """Persist user turn and fetch prepared message history for execution."""
        return await self._post(
            f"/internal/data/conversations/{conv_session_id}/prepare-turn",
            {"user_message": user_message},
        )

    async def append_conversation_turn(
        self,
        conv_session_id: uuid.UUID,
        agent_reply: str,
        is_first_message: bool = False,
        first_user_message: str | None = None,
        guardrail_usage: dict[str, Any] | None = None,
        status_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist agent turn and optionally auto-name the session title."""
        body: dict[str, Any] = {
            "agent_reply": agent_reply,
            "is_first_message": is_first_message,
        }
        if first_user_message is not None:
            body["first_user_message"] = first_user_message
        if guardrail_usage is not None:
            body["guardrail_usage"] = guardrail_usage
        if status_events:
            body["status_events"] = status_events

        return await self._post(
            f"/internal/data/conversations/{conv_session_id}/append-turn",
            body,
        )

    # ── A2A orchestration ────────────────────────────────────────────────────

    async def prepare_a2a_request(
        self,
        *,
        target_agent_type_slug: str,
        requester_instance_id: str,
        requester_role_id: str | None,
        request_payload: dict[str, Any],
        session_link_id: str | None,
        active_receiver_instance_id: str | None,
    ) -> dict[str, Any]:
        """Prepare an A2A request in Control Center.

        Calls ``POST /internal/data/a2a/request`` and returns:
        receiver_instance_id, session_link_id, status, receiver_session_id.
        """
        body: dict[str, Any] = {
            "target_agent_type_slug": target_agent_type_slug,
            "requester_instance_id": requester_instance_id,
            "request_payload": request_payload,
            "session_link_id": session_link_id,
            "active_receiver_instance_id": active_receiver_instance_id,
        }
        if requester_role_id:
            body["requester_role_id"] = requester_role_id

        return await self._post("/internal/data/a2a/request", body)

    async def disconnect_a2a_session(self, session_link_id: str) -> dict[str, Any]:
        """Mark an A2A session as disconnected in Control Center."""
        return await self._post(
            f"/internal/data/a2a/sessions/{session_link_id}/disconnect",
            {},
        )
