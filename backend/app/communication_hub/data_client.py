"""Communication Hub — Control Center data client.

Fetches session data, user permissions, and revocation status from Control Center
via HTTP calls authenticated with the Communication Hub service mTLS certificate.

Communication Hub has ZERO direct database access.  All data flows through this client.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, TypedDict

import httpx

from app.core.internal_http import internal_httpx_client

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0  # seconds


class ConversationActivityData(TypedDict, total=False):
    """Read model of ``GET /internal/data/conversations/{id}/activity``.

    Only the keys Communication Hub consumes are typed; Control Center may
    return more (and older builds return fewer), so every key is optional.
    ``active_resume_id`` / ``resume_state`` / ``terminal_reason_code`` are the
    durable paused-turn projection: a ``waiting_for_human`` activity is only
    answerable while ``active_resume_id`` is set.
    """

    conversation_session_id: str
    state: str
    current_turn_id: str | None
    tool_name: str | None
    target_agent_type_id: str | None
    pending_intervene_request_id: str | None
    active_resume_id: str | None
    resume_state: str | None
    resume_outcome: str | None
    terminal_reason_code: str | None
    terminal_message_key: str | None
    detail: dict[str, Any] | None
    is_terminal: bool
    started_at: str | None
    last_updated_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class ConversationResumeLookup:
    """Result of reading a session's live resume record from Control Center.

    ``is_conversation_session`` distinguishes "this id is a conversation
    session with no live resume record" (idle / already terminal) from "this id
    is not a conversation session at all" (an ``AgentJob`` — the legacy resume
    path), which Control Center answers with a 404.
    """

    is_conversation_session: bool
    record: dict[str, Any] | None = None

    @property
    def live_record(self) -> dict[str, Any] | None:
        """The live resume record, or ``None`` when the session is idle."""
        return self.record


@dataclass(frozen=True)
class InternalRelayResponse:
    """Raw upstream response returned by :meth:`ControlCenterDataClient.relay_internal`.

    Communication Hub relays the body **byte-for-byte** and never inspects it
    (the checkpoint payload is opaque); callers surface upstream 4xx/5xx as a
    typed relay error instead of an empty payload.
    """

    status_code: int
    content: bytes
    media_type: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status_code < 400


def _allow_insecure_internal_fallback() -> bool:
    """Return True only for explicit development-mode insecure fallback opt-in."""
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


def _decode_json(content: bytes) -> Any:
    """Decode a relayed JSON body; ``None`` for empty / ``null`` / non-JSON."""
    if not content:
        return None
    try:
        return json.loads(content)
    except Exception:  # noqa: BLE001 - opaque/non-JSON body means "no value"
        return None



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
        """Return an mTLS-configured HTTP client using the current service cert.

        Built via ``internal_httpx_client`` — the single egress mechanism
        that attaches forwarded tenant headers (no per-call merging).
        """
        if self._cert_manager is None:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "CH data client using insecure HTTP fallback because "
                    "ALLOW_INSECURE_INTERNAL_CALL_FALLBACK is enabled in development"
                )
                return internal_httpx_client(timeout=_DEFAULT_TIMEOUT)
            raise RuntimeError(
                "Communication Hub certificate manager is unavailable; "
                "internal Control Center calls fail closed"
            )
        try:
            return internal_httpx_client(
                **self._cert_manager.mtls_client_kwargs(),
                timeout=_DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            if _allow_insecure_internal_fallback():
                logger.warning(
                    "CH certificate not loaded; using insecure HTTP fallback in development: %s",
                    exc,
                )
                return internal_httpx_client(timeout=_DEFAULT_TIMEOUT)
            raise RuntimeError(
                "Communication Hub service certificate is required for internal calls"
            ) from exc

    def _url(self, path: str) -> str:
        return f"{self._control_center_url}/api/v1{path}"

    async def _get(self, path: str) -> dict[str, Any]:
        """GET with automatic tenant-header forwarding (via the client hook)."""
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

    async def _post(self, path: str, body: dict[str, Any], user_jwt: str | None = None) -> dict[str, Any]:
        url = self._url(path)
        headers: dict[str, str] = {}
        if user_jwt:
            headers["Authorization"] = f"Bearer {user_jwt}"
        # Tenant headers are attached by the internal_httpx_client egress hook.
        async with self._make_client() as client:
            try:
                resp = await client.post(url, json=body, timeout=_DEFAULT_TIMEOUT, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise ControlCenterDataError(
                    f"CC POST {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(f"CC POST {url} failed: {exc}") from exc

    async def _put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """PUT with automatic tenant-header forwarding (via the client hook)."""
        url = self._url(path)
        async with self._make_client() as client:
            try:
                resp = await client.put(url, json=body, timeout=_DEFAULT_TIMEOUT)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise ControlCenterDataError(
                    f"CC PUT {url} returned {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                ) from exc
            except Exception as exc:
                raise ControlCenterDataError(f"CC PUT {url} failed: {exc}") from exc

    async def relay_internal(
        self,
        method: str,
        path: str,
        *,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> InternalRelayResponse:
        """Relay one internal data-plane call **without interpreting the body**.

        Used by the AR-facing checkpoint relay: the request body is forwarded
        byte-for-byte and the upstream status/content are returned so the
        route can replay them unchanged.  Tenant headers are attached by the
        single shared egress hook (CH forwards the verified CC-signed set and
        never signs).  Transport failures raise :class:`ControlCenterDataError`.
        """
        url = self._url(path)
        headers: dict[str, str] = {}
        if raw_body is not None:
            headers["Content-Type"] = content_type
        async with self._make_client() as client:
            try:
                resp = await client.request(
                    method,
                    url,
                    content=raw_body,
                    headers=headers,
                    timeout=_DEFAULT_TIMEOUT,
                )
            except Exception as exc:
                raise ControlCenterDataError(
                    f"CC {method} {url} failed: {exc}"
                ) from exc
        return InternalRelayResponse(
            status_code=resp.status_code,
            content=resp.content,
            media_type=resp.headers.get("content-type"),
        )

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

    # ── Conversation activity (persistent agent activity state) ──────────────

    async def upsert_conversation_activity(
        self,
        conv_session_id: uuid.UUID,
        state: str,
        *,
        current_turn_id: uuid.UUID | None = None,
        tool_name: str | None = None,
        target_agent_type_id: uuid.UUID | None = None,
        pending_intervene_request_id: uuid.UUID | None = None,
        active_resume_id: uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Upsert the persisted conversation activity row via Control Center.

        Calls ``PUT /internal/data/conversations/{conv_session_id}/activity``.
        ``state`` must be a valid ``ActivityState`` value (validated CC-side).
        ``active_resume_id`` pins the durable resume record backing a
        ``waiting_for_human`` state; Control Center resolves the session's live
        record when it is omitted.
        """
        body: dict[str, Any] = {"state": state}
        if current_turn_id is not None:
            body["current_turn_id"] = str(current_turn_id)
        if tool_name is not None:
            body["tool_name"] = tool_name
        if target_agent_type_id is not None:
            body["target_agent_type_id"] = str(target_agent_type_id)
        if pending_intervene_request_id is not None:
            body["pending_intervene_request_id"] = str(pending_intervene_request_id)
        if active_resume_id is not None:
            body["active_resume_id"] = str(active_resume_id)
        if detail is not None:
            body["detail"] = detail

        return await self._put(
            f"/internal/data/conversations/{conv_session_id}/activity",
            body,
        )

    async def touch_conversation_activity(
        self, conv_session_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Refresh the persisted activity heartbeat of a live working turn.

        Calls ``POST /internal/data/conversations/{conv_session_id}/activity/touch``
        from the conversation heartbeat loop (~15s). Only ``last_updated_at``
        moves — the state never changes, and Control Center ignores the touch
        for terminal / paused rows. Fire-and-forget: a CC hiccup must never
        break the heartbeat.
        """
        try:
            return await self._post(
                f"/internal/data/conversations/{conv_session_id}/activity/touch",
                {},
            )
        except ControlCenterDataError as exc:
            logger.debug(
                "Activity touch for conversation %s failed (ignored): %s",
                conv_session_id,
                exc,
            )
            return None

    async def get_conversation_activity(
        self, conv_session_id: uuid.UUID
    ) -> ConversationActivityData | None:
        """Return the persisted current activity, or None when idle/not found.

        Calls ``GET /internal/data/conversations/{conv_session_id}/activity``.
        Returns the persisted activity (``state``, ``current_turn_id``,
        ``tool_name``, ``target_agent_type_id``, ``pending_intervene_request_id``,
        ``active_resume_id``, ``resume_state``, ``terminal_reason_code``,
        ``detail``, ``is_terminal``, timestamps).
        """
        try:
            return await self._get(
                f"/internal/data/conversations/{conv_session_id}/activity"
            )
        except ControlCenterDataError as exc:
            if "404" in str(exc):
                return None
            raise

    # ── Durable paused-turn resume index / checkpoint payload ────────────────
    # CH is transport for these calls only: it relays AR's writes/reads to CC
    # and never inspects the checkpoint payload (beyond the route's size guard).

    async def get_conversation_turn_resume(
        self, conv_session_id: uuid.UUID
    ) -> ConversationResumeLookup:
        """Read the session's live resume record (explicit ``null`` when idle).

        Calls ``GET /internal/data/conversations/{conv_session_id}/resume``.
        A 404 means the id is not a conversation session (an ``AgentJob``);
        a ``null`` body means the session exists but nothing is paused.
        """
        result = await self.relay_internal(
            "GET", f"/internal/data/conversations/{conv_session_id}/resume"
        )
        if result.status_code == 404:
            return ConversationResumeLookup(is_conversation_session=False)
        if result.status_code >= 400:
            raise ControlCenterDataError(
                f"CC GET resume for {conv_session_id} returned "
                f"{result.status_code}: {result.content[:200]!r}"
            )
        payload = _decode_json(result.content)
        return ConversationResumeLookup(
            is_conversation_session=True,
            record=payload if isinstance(payload, dict) else None,
        )

    async def save_conversation_turn_resume(
        self,
        conv_session_id: uuid.UUID,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Create/refresh the live resume record (relay of AR's pause intent)."""
        return await self._put(
            f"/internal/data/conversations/{conv_session_id}/resume", body
        )

    async def complete_conversation_turn_resume(
        self,
        conv_session_id: uuid.UUID,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Close a paused turn exactly once (outcome turn + terminal state)."""
        return await self._post(
            f"/internal/data/conversations/{conv_session_id}/resume/complete", body
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
        conv_session_id: str | None = None,
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
        if conv_session_id:
            body["conv_session_id"] = conv_session_id

        return await self._post("/internal/data/a2a/request", body)

    async def disconnect_a2a_session(self, session_link_id: str) -> dict[str, Any]:
        """Mark an A2A session as disconnected in Control Center."""
        return await self._post(
            f"/internal/data/a2a/sessions/{session_link_id}/disconnect",
            {},
        )

    # ── Execution logging ─────────────────────────────────────────────────────

    async def log_execution_event(
        self,
        session_id: uuid.UUID | str,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
        log_level: str = "INFO",
        event_category: str = "functional",
    ) -> None:
        """Write a structured execution log entry to Control Center.

        Calls ``POST /internal/data/sessions/{session_id}/log``.
        Failures are swallowed — logging must never abort execution.
        """
        session_uuid = uuid.UUID(str(session_id)) if isinstance(session_id, str) else session_id
        try:
            await self._post(
                f"/internal/data/sessions/{session_uuid}/log",
                {
                    "event_type": event_type,
                    "log_level": log_level,
                    "message": message,
                    "data": data or {},
                    "event_category": event_category,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist execution log for session %s: %s",
                session_id, exc,
            )
