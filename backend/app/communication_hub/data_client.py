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
        try:
            return self._cert_manager.configure_mtls_client()
        except Exception:
            logger.warning("CH certificate not loaded; using plain HTTP client (dev only)")
            return httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)

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

        Calls ``GET /internal/certificates/revocation-status?serial={serial}``.
        Returns False on any error (fail-open for now; Phase 4 hardens this).
        """
        try:
            data = await self._get(
                f"/internal/certificates/revocation-status?serial={serial}"
            )
            return bool(data.get("revoked", False))
        except Exception as exc:
            logger.warning(
                "Revocation check for serial %s failed: %s — treating as not revoked",
                serial,
                exc,
            )
            return False

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
