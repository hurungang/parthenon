"""WebSocket server — authenticates connections, runs conversational agent, persists turns."""
import asyncio
import contextlib
import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.communication_hub.api.internal.tool_routing import cache_user_jwt, get_user_jwt

from app.core.config import get_settings
from app.core.oidc_client import OIDCError, get_oidc_client
from app.core.ssl_context import get_ssl_context
from app.communication_hub.data_client import ControlCenterDataClient
from app.services.agents.model_binding import ModelBindingError

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["WebSocket"])

# ── Structured chat error codes ──────────────────────────────────────────────
# Surfaced to the client as {"type": "chat_error", "code": ..., "message": ...}
# payloads so the frontend can recognize actionable failure modes (e.g. the
# assistant surface renders setup guidance) instead of a generic crash string.
ERROR_CODE_ASSISTANT_MODEL_NOT_CONFIGURED = "assistant_model_not_configured"
ERROR_CODE_MODEL_BINDING_ERROR = "model_binding_error"

# FIX-20261031-091657: app-level WS keepalive cadence while a turn is in
# flight — keeps idle proxies from closing the socket and lets the UI keep
# the "thinking" indicator alive during long agentic turns.
CONVERSATION_HEARTBEAT_INTERVAL_SECONDS = 15.0


class ConversationTurnTimeoutError(Exception):
    """Raised when the whole conversational turn exceeds the watchdog bound."""

ASSISTANT_MODEL_NOT_CONFIGURED_MESSAGE = (
    "No model is configured for this workspace yet. An administrator can "
    "select one under System Config → Assistant model."
)


class ConversationTurnError(Exception):
    """Typed, structured failure of one conversation turn.

    Carries a stable machine-readable ``code`` the frontend can map to
    dedicated guidance UI, plus a human-friendly ``message``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _conversation_turn_error_from_http_status(exc: httpx.HTTPStatusError) -> ConversationTurnError | None:
    """Map an Agent Runtime 4xx rejection onto a structured turn error.

    AR rejects a turn with 400 "Agent model is not configured" BEFORE calling
    the model when the agent type has no ``model_id`` / ``model_config_id`` —
    that becomes the dedicated ``assistant_model_not_configured`` code.
    """
    response = exc.response
    if response.status_code != 400:
        return None
    try:
        detail = str((response.json() or {}).get("detail") or "")
    except Exception:
        detail = ""
    if "model" in detail.lower() and "not configured" in detail.lower():
        return ConversationTurnError(
            ERROR_CODE_ASSISTANT_MODEL_NOT_CONFIGURED,
            ASSISTANT_MODEL_NOT_CONFIGURED_MESSAGE,
        )
    return None


#: FIX-20261101-111439: user-comprehensible message for guardrail iteration
#: stops. ``{limit}`` is filled from the AR-forwarded guardrail details when
#: available. Message text lives backend-side (i18n-safe English baseline).
ITERATION_LIMIT_MESSAGE_TEMPLATE = (
    "This task needed more steps than allowed (limit {limit}). Try breaking it "
    "into smaller requests or ask an administrator to raise the step limit."
)
ITERATION_LIMIT_MESSAGE_NO_LIMIT = (
    "This task needed more steps than allowed. Try breaking it into smaller "
    "requests or ask an administrator to raise the step limit."
)

#: Guardrail stop reasons AR may forward on the streaming error chunk
#: (``GuardrailStop.reason`` from both the callback and the executor).
_GUARDRAIL_STOP_CODES = {
    "iteration_limit",
    "iteration_limit_exceeded",
    "token_budget",
    "token_budget_exceeded_non_conversational",
    "delegation_depth",
    "delegation_depth_exceeded",
    "delegated_steps_exceeded",
    "cycle_detected",
    "timeout",
    "execution_timeout_exceeded",
}

_GENERIC_GUARDRAIL_MESSAGE_TEMPLATE = (
    "The assistant stopped because a safety limit was reached ({reason}). "
    "Please try again or contact your administrator."
)


def _conversation_turn_error_from_guardrail_stop(
    reason: str,
    details: dict[str, Any] | None = None,
) -> ConversationTurnError:
    """Map an AR-forwarded guardrail stop reason onto a structured turn error."""
    safe_details = details if isinstance(details, dict) else {}
    if reason in {"iteration_limit", "iteration_limit_exceeded"}:
        limit = safe_details.get("max_iterations")
        message = (
            ITERATION_LIMIT_MESSAGE_TEMPLATE.format(limit=limit)
            if isinstance(limit, int)
            else ITERATION_LIMIT_MESSAGE_NO_LIMIT
        )
        return ConversationTurnError("iteration_limit", message)
    return ConversationTurnError(
        f"guardrail_{reason}",
        _GENERIC_GUARDRAIL_MESSAGE_TEMPLATE.format(reason=reason),
    )


class ActiveSessionTracker:
    """Tracks active WebSocket connections for intervention routing.

    Maps conversation session IDs to connected WebSocket instances so the
    InterventionRouter can deliver intervention messages directly to the
    conversation UI instead of the operator dashboard.
    """

    _connections: dict[str, WebSocket] = {}
    _intervention_active: set[str] = set()

    @classmethod
    def register(cls, session_id: str, websocket: WebSocket) -> None:
        cls._connections[str(session_id)] = websocket

    @classmethod
    def unregister(cls, session_id: str, websocket: WebSocket | None = None) -> None:
        """Remove a session's connection entry.

        When ``websocket`` is given, the entry is only removed if it still
        points at THAT socket — a reconnecting client registers a NEW socket
        for the same session id while the old handler is still finishing, and
        the old connection's cleanup must not evict the new registration
        (FIX-20261031-071721 follow-up).
        """
        key = str(session_id)
        if websocket is not None and cls._connections.get(key) is not websocket:
            cls._intervention_active.discard(key)
            return
        cls._connections.pop(key, None)
        cls._intervention_active.discard(key)

    @classmethod
    def is_connected(cls, session_id: str) -> bool:
        return str(session_id) in cls._connections

    @classmethod
    def get_ws(cls, session_id: str) -> WebSocket | None:
        return cls._connections.get(str(session_id))

    @classmethod
    def set_intervention_active(cls, session_id: str, active: bool) -> None:
        key = str(session_id)
        if active:
            cls._intervention_active.add(key)
        else:
            cls._intervention_active.discard(key)

    @classmethod
    def has_pending_intervention(cls, session_id: str) -> bool:
        return str(session_id) in cls._intervention_active

    @classmethod
    async def send_to_session(
        cls, session_id: str, message: dict[str, Any]
    ) -> None:
        """Send a JSON message to a specific WebSocket session."""
        ws = cls._connections.get(str(session_id))
        if ws and ws.client_state.name == "CONNECTED":
            await ws.send_json(message)
        else:
            raise RuntimeError(
                f"No connected WebSocket for session {session_id}"
            )


async def _send_to_live_socket(
    session_id: str,
    fallback_ws: WebSocket | None,
    payload: dict[str, Any],
) -> None:
    """Send a JSON payload over the CURRENT live socket for ``session_id``.

    Long agentic turns can outlive the original WebSocket connection: the
    client reconnects with the same session id and a NEW socket is
    registered in ``ActiveSessionTracker``. Sends must therefore resolve the
    live socket from the tracker at send time instead of using the socket
    captured at connection start (FIX-20261031-071721 follow-up); the
    captured socket is only a fallback for flows without a tracker entry.
    Send failures (dead socket) are logged and swallowed — a transport error
    must never crash the turn pipeline. Persistence is unaffected.
    """
    ws = ActiveSessionTracker.get_ws(session_id) or fallback_ws
    if ws is None:
        return
    logger.info(
        "WS->client session=%s type=%s status=%s state=%s role=%s tool=%s final=%s len=%s",
        session_id,
        payload.get("type"),
        payload.get("status"),
        payload.get("state"),
        payload.get("sender_role"),
        payload.get("tool_name"),
        payload.get("final"),
        len(payload.get("content") or ""),
    )
    try:
        await ws.send_json(payload)
    except Exception as exc:
        logger.warning(
            "WebSocket send failed for session %s (socket=%r): %s",
            session_id,
            getattr(ws, "name", type(ws).__name__),
            exc,
        )


def _build_chat_status_event(
    status_value: str,
    agent_type: str | None = None,
    tool_name: str | None = None,
    receiver_session_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Build a normalized websocket status event payload for chat UI."""
    payload = {"status": status_value}
    if agent_type:
        payload["agent_type"] = agent_type
    if tool_name:
        payload["tool_name"] = tool_name
    if receiver_session_id:
        payload["receiver_session_id"] = receiver_session_id
    payload["timestamp"] = timestamp or datetime.now(timezone.utc).isoformat()
    return payload


# ── Persistent agent activity state (AR transition → CC activity row) ────────
# Wire status values from Agent Runtime mapped onto the persisted ``ActivityState``
# enum. ``waiting`` is context-dependent (delegating when an agent_type is
# present, thinking otherwise) and is resolved at forward time.
_WIRE_STATUS_TO_ACTIVITY_STATE: dict[str, str] = {
    "thinking": "thinking",
    "using_tool": "using_tool",
    "delegating": "delegating",
    "waiting_for_human": "waiting_for_human",
    "timeout_or_failed": "timed_out",
    "failed": "failed",
}

_TERMINAL_ACTIVITY_STATES = {"finished", "failed", "timed_out"}


def _map_wire_status_to_activity_state(
    status_value: str,
    agent_type: str | None = None,
) -> str | None:
    """Map an AR wire status onto a persisted ``ActivityState`` value (None = skip)."""
    if status_value == "waiting":
        return "delegating" if agent_type else "thinking"
    return _WIRE_STATUS_TO_ACTIVITY_STATE.get(status_value)


async def _persist_activity_transition(
    app: Any,
    conv_session_id: uuid.UUID,
    status_value: str,
    agent_type: str | None,
    tool_name: str | None,
) -> None:
    """Forward one AR status transition to the CC activity endpoint.

    Communication Hub never writes the database — the transition is persisted
    by Control Center via the internal data API. Failures are logged and
    swallowed: a CC hiccup must never crash the turn pipeline (same spirit as
    ``_send_to_live_socket``).
    """
    data_client: ControlCenterDataClient | None = getattr(app.state, "data_client", None)
    if data_client is None:
        return
    state = _map_wire_status_to_activity_state(status_value, agent_type)
    if state is None:
        return
    detail: dict[str, Any] | None = None
    if agent_type:
        detail = {"agent_type": agent_type}
    if status_value == "waiting_for_human":
        detail = {**(detail or {}), "pending_intervention": True}
    try:
        with _signed_tenant_forwarding():
            await data_client.upsert_conversation_activity(
                conv_session_id,
                state,
                tool_name=tool_name if state == "using_tool" else None,
                detail=detail,
            )
    except Exception as exc:
        logger.warning(
            "Activity upsert failed for conversation %s (state=%s): %s",
            conv_session_id,
            state,
            exc,
        )


def _activity_state_message(activity: dict[str, Any] | None) -> dict[str, Any]:
    """Build a normalized ``activity_state`` message from a CC activity record.

    An idle session (no live activity row) pushes ``state: null``.
    """
    detail = (
        activity.get("detail")
        if isinstance(activity, dict) and isinstance(activity.get("detail"), dict)
        else {}
    )
    pending_intervention = bool(
        activity
        and (
            activity.get("pending_intervene_request_id")
            or detail.get("pending_intervention")
        )
    )
    return {
        "type": "activity_state",
        "state": activity.get("state") if isinstance(activity, dict) else None,
        "tool_name": activity.get("tool_name") if isinstance(activity, dict) else None,
        "agent_type": detail.get("agent_type") if detail else None,
        "pending_intervention": pending_intervention,
        "is_terminal": bool(activity.get("is_terminal", False))
        if isinstance(activity, dict)
        else False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _fetch_conversation_activity(
    websocket: WebSocket,
    conv_session_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Hydrate the persisted activity for ``conv_session_id`` from CC (or None).

    Failures are logged and swallowed — hydration is best-effort and must
    never reject the connection or crash the message loop.
    """
    app = getattr(websocket, "app", None)
    if app is None:
        return None
    data_client: ControlCenterDataClient | None = getattr(
        app.state, "data_client", None
    )
    if data_client is None:
        return None
    try:
        with _signed_tenant_forwarding():
            return await data_client.get_conversation_activity(conv_session_id)
    except Exception as exc:
        logger.warning(
            "Activity hydration failed for conversation %s: %s", conv_session_id, exc
        )
        return None


# FIX-20261031-091657 (Defect B): in-flight CH-side turn tasks per session so
# the session-end termination path (CC → CH ``/internal/agent/terminate``) can
# cancel a pending turn promptly instead of waiting out the full watchdog.
_pending_turn_tasks: dict[str, "asyncio.Task[None]"] = {}


def cancel_pending_conversation_turn(session_id: str) -> bool:
    """Cancel a pending conversational turn task for ``session_id`` (best-effort)."""
    task = _pending_turn_tasks.pop(str(session_id), None)
    if task is None or task.done():
        return False
    task.cancel()
    logger.info(
        "Cancelled pending conversation turn for session %s (session ended)", session_id
    )
    return True


async def _thinking_heartbeat_loop(
    session_id: str,
    fallback_ws: WebSocket | None,
    stop: asyncio.Event,
) -> None:
    """Emit a lightweight keepalive status event while a turn is in flight."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=CONVERSATION_HEARTBEAT_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            return
        await _send_to_live_socket(
            session_id,
            fallback_ws,
            {
                "type": "chat_status",
                **_build_chat_status_event("thinking_heartbeat"),
            },
        )


async def run_conversation_turn(
    *,
    session_id: str,
    conv_session_id: uuid.UUID,
    user_message: str,
    is_first_message: bool,
    app: Any,
    websocket: WebSocket | None,
    message_count: int,
) -> None:
    """Execute one conversational turn under the whole-turn watchdog.

    FIX-20261031-091657 (Defect A): the delegated AR call uses a disabled HTTP
    timeout on the streaming path, so an Agent Runtime hang would previously
    leave this turn awaiting forever. The whole turn is now bounded by
    ``agent_question_timeout_seconds``; on watchdog fire (or end-session
    cancellation) the pipeline emits the existing ``timeout_or_failed`` status
    event, delivers a clear error message and persists the error turn exactly
    once (the normal path never persists a duplicate error).
    """
    settings = get_settings()
    configured_timeout = int(getattr(settings, "agent_question_timeout_seconds", 300))
    timeout_seconds = float(max(1, configured_timeout))

    data_client = getattr(app.state, "data_client", None)
    error_persisted = False
    reply_delivered = False

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _thinking_heartbeat_loop(session_id, websocket, stop_heartbeat)
    )

    async def send_status_event(status_event: dict[str, str]) -> None:
        event_timestamp = status_event.get("timestamp")
        await _send_to_live_socket(
            session_id,
            websocket,
            {
                "type": "chat_status",
                **status_event,
                "timestamp": event_timestamp or datetime.now(timezone.utc).isoformat(),
            },
        )

    async def deliver_reply(agent_reply: str) -> None:
        nonlocal reply_delivered
        reply_delivered = True
        await _send_to_live_socket(
            session_id,
            websocket,
            {
                "sender_role": "agent",
                "content": agent_reply,
                "final": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.debug(
            "Conversation agent response sent: message=%d session=%s length=%d",
            message_count,
            session_id,
            len(agent_reply),
            extra={"data": {"agent_response": agent_reply}},
        )

    try:
        # Guardrail-panel regression fix: emit guardrail_update the moment the
        # delegation returns (before persistence) so a hung/failing
        # append_conversation_turn can no longer swallow the event.
        guardrail_usage_sent = False

        async def deliver_guardrail_usage(usage: dict[str, Any]) -> None:
            nonlocal guardrail_usage_sent
            if guardrail_usage_sent:
                return
            guardrail_usage_sent = True
            await _send_to_live_socket(
                session_id,
                websocket,
                {"type": "guardrail_update", "guardrail_usage": usage},
            )

        agent_reply, session_title, guardrail_usage, status_events = await asyncio.wait_for(
            _process_message(
                conv_session_id=conv_session_id,
                user_message=user_message,
                is_first_message=is_first_message,
                app=app,
                on_status_event=send_status_event,
                on_reply=deliver_reply,
                on_guardrail_usage=deliver_guardrail_usage,
            ),
            timeout=timeout_seconds,
        )

        if not reply_delivered:
            await deliver_reply(agent_reply)

        if session_title:
            await _send_to_live_socket(
                session_id,
                websocket,
                {"type": "title_update", "title": session_title},
            )

        if guardrail_usage:
            await deliver_guardrail_usage(guardrail_usage)

        # Authoritative turn completion. The client clears its processing bubble
        # from a terminal status rather than guessing from the agent message
        # (which may be an intermediate message mid-turn, e.g. during the
        # confirm-before-write tool-calling phase). Only emit ``finished`` when
        # the turn actually completed successfully — an error/guardrail
        # terminal status was already streamed and must not be overwritten.
        _completed_ok = True
        for _ev in status_events or []:
            _sv = _ev.get("status") if isinstance(_ev, dict) else None
            if isinstance(_sv, str) and (
                _sv == "timeout_or_failed" or _sv.startswith("guardrail_")
            ):
                _completed_ok = False
                break
        if _completed_ok:
            await _send_to_live_socket(
                session_id,
                websocket,
                {"type": "chat_status", **_build_chat_status_event("finished")},
            )
    except asyncio.TimeoutError:
        if reply_delivered:
            # Reply already reached the user — only the persistence tail hung.
            # Never send a duplicate error message / status event.
            logger.warning(
                "Conversation turn persistence exceeded the watchdog for session %s "
                "after %.0fs (reply already delivered)",
                session_id,
                timeout_seconds,
            )
        else:
            logger.warning(
                "Conversation turn watchdog fired for session %s after %.0fs",
                session_id,
                timeout_seconds,
            )
            error_persisted = await _persist_and_surface_turn_error(
                session_id=session_id,
                conv_session_id=conv_session_id,
                user_message=user_message,
                is_first_message=is_first_message,
                websocket=websocket,
                data_client=data_client,
                error_text=(
                    "Your request timed out because the assistant took too long to "
                    "respond. Please try again."
                ),
            )
    except asyncio.CancelledError:
        # End-session termination path (Defect B): surface the same bounded
        # failure UX, then let the cancellation unwind. A delivered reply is
        # never followed by a duplicate error message.
        if not reply_delivered and not error_persisted:
            with contextlib.suppress(Exception):
                await _persist_and_surface_turn_error(
                    session_id=session_id,
                    conv_session_id=conv_session_id,
                    user_message=user_message,
                    is_first_message=is_first_message,
                    websocket=websocket,
                    data_client=data_client,
                    error_text=(
                        "This conversation session was ended while the assistant "
                        "was still processing your request."
                    ),
                )
        raise
    except ConversationTurnError as turn_exc:
        logger.warning(
            "Conversation turn blocked for session %s: code=%s",
            session_id,
            turn_exc.code,
        )
        await _send_to_live_socket(
            session_id,
            websocket,
            {
                "type": "chat_error",
                "code": turn_exc.code,
                "message": turn_exc.message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        # FIX-20261101-111439: structured errors (e.g. guardrail iteration
        # stops) must surface as a clear, persisted error turn instead of the
        # generic "An error occurred" message. Follows the timeout_or_failed
        # pattern: emit status + deliver + persist exactly once.
        if not reply_delivered:
            await _persist_and_surface_turn_error(
                session_id=session_id,
                conv_session_id=conv_session_id,
                user_message=user_message,
                is_first_message=is_first_message,
                websocket=websocket,
                data_client=data_client,
                error_text=turn_exc.message,
                status_value=turn_exc.code,
            )
    except Exception:
        logger.exception("Background conversation turn failed for session %s", session_id)
        await _send_to_live_socket(
            session_id,
            websocket,
            {
                "sender_role": "agent",
                "content": "I encountered an error processing your request. Please try again.",
                "final": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    finally:
        stop_heartbeat.set()
        with contextlib.suppress(Exception):
            await heartbeat_task


async def _persist_and_surface_turn_error(
    *,
    session_id: str,
    conv_session_id: uuid.UUID,
    user_message: str,
    is_first_message: bool,
    websocket: WebSocket | None,
    data_client: Any,
    error_text: str,
    status_value: str = "timeout_or_failed",
) -> bool:
    """Emit a terminal status + deliver and persist the error turn.

    Returns True when the error turn was persisted (dedupe guard so a
    watchdog fire and a cancellation never double-persist).
    """
    await _send_to_live_socket(
        session_id,
        websocket,
        {
            "type": "chat_status",
            **_build_chat_status_event(status_value),
        },
    )
    await _send_to_live_socket(
        session_id,
        websocket,
        {
            "sender_role": "agent",
            "content": error_text,
            "final": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    if data_client is None:
        return False
    try:
        with _signed_tenant_forwarding():
            await data_client.append_conversation_turn(
                conv_session_id=conv_session_id,
                agent_reply=error_text,
                is_first_message=is_first_message,
                first_user_message=user_message if is_first_message else None,
                guardrail_usage=None,
                status_events=[_build_chat_status_event(status_value)],
            )
        return True
    except Exception:
        logger.warning(
            "Failed to persist watchdog error turn for session %s", session_id, exc_info=True
        )
        return False


@contextmanager
def _signed_tenant_forwarding():
    """Bind a FRESHLY signed tenant header set for one outbound CC call.

    WebSocket connections bypass the HTTP tenant-resolution middleware, so no
    CC-signed forwarded header set is ever bound for them — the loopback
    data-client calls to ``/internal/data/conversations/*`` would otherwise go
    out headerless and fail closed with 401 ("Signed tenant context headers
    are required").  The tenant context was resolved at connection time from
    the VERIFIED user token and bound via ``set_current_tenant_context``; here
    we mint a per-call signature (a signature minted once at connect time
    would exceed CC's replay window on a long-lived conversation).

    No tenant context (single-tenant mode) → yields unchanged: headerless
    traffic, and CC binds the root tenant as before.
    """
    from app.core.tenant_context import get_current_tenant_context
    from app.core.tenant_signature import (
        bind_forwarded_tenant_headers,
        reset_forwarded_tenant_headers,
        sign_context_for_authenticated_session,
    )

    context = get_current_tenant_context()
    if context is None:
        yield
        return
    token = bind_forwarded_tenant_headers(
        sign_context_for_authenticated_session(context)
    )
    try:
        yield
    finally:
        reset_forwarded_tenant_headers(token)


async def _resolve_oidc_tenant_slug(db: Any, sub: str) -> str | None:
    """Resolve an OIDC user's tenant slug from their active membership.

    Mirrors the REST login-context resolution used by the tenant-membership
    endpoints (``/auth/tenant-memberships``): the ``PlatformUser`` record is
    looked up by the verified token's ``sub`` (identity-plane, unscoped),
    then the user's ACTIVE membership in an ACTIVE tenant is selected
    (default tenant first).  Returns None when no membership resolves —
    callers must fail closed.
    """
    if not sub:
        return None
    from sqlalchemy import select

    from app.db.models.platform_user import PlatformUser
    from app.db.models.tenant import Tenant, TenantStatus
    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )
    from app.db.tenant_scoping import execute_unscoped

    user_result = await execute_unscoped(
        db, select(PlatformUser).where(PlatformUser.sub == sub)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return None

    result = await db.execute(
        select(Tenant.slug)
        .join(TenantUserMembership, TenantUserMembership.tenant_id == Tenant.id)
        .where(
            TenantUserMembership.user_id == user.id,
            TenantUserMembership.status == TenantUserMembershipStatus.active,
            Tenant.status == TenantStatus.active,
        )
        .order_by(
            TenantUserMembership.is_default.desc(),
            Tenant.name.asc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _bind_connection_tenant_context(claims: dict[str, Any]) -> str | None:
    """Resolve and bind the tenant context for a WebSocket connection.

    WebSockets bypass the HTTP tenant-resolution middleware, so the context
    must be bound here from the VERIFIED token claims:

    - Platform-account JWTs carry a native ``tenant`` slug claim → resolved
      exactly as before (unchanged behaviour).
    - OIDC tokens (Keycloak/EntraID) return claims verbatim with NO
      ``tenant`` claim on this direct-validation path → the tenant is
      resolved server-side from the user's active membership, the SAME
      mechanism REST uses for OIDC sessions (see
      ``_resolve_oidc_tenant_slug``).
    - Multi-tenancy off → no binding: root-tenant binding, headerless
      traffic, single-tenant behaviour unchanged.
    - Fail-closed: when multi-tenancy is on and no tenant can be resolved,
      a reason string is returned and the caller MUST reject the
      connection (no headerless pipeline).

    Returns None on success (context bound, or single-tenant no-op), or a
    close-reason string on failure.
    """
    from app.core.tenant_context import set_current_tenant_context
    from app.db.session import AsyncSessionLocal
    from app.services.tenancy.platform_settings_service import (
        get_platform_settings_service,
    )
    from app.services.tenancy.tenant_resolution_service import (
        TenantResolutionError,
        get_tenant_resolution_service,
    )

    tenant_slug = claims.get("tenant")
    oidc_fallback = not (isinstance(tenant_slug, str) and tenant_slug.strip())

    async with AsyncSessionLocal() as db:
        if oidc_fallback:
            settings_service = get_platform_settings_service()
            if not await settings_service.is_multi_tenancy_enabled(db):
                return None  # single-tenant mode: unchanged, headerless
            resolved = await _resolve_oidc_tenant_slug(
                db, str(claims.get("sub", "") or "")
            )
            if not resolved:
                return "No active tenant membership"
            tenant_slug = resolved
        try:
            context = await get_tenant_resolution_service().resolve_slug(
                db, tenant_slug.strip()
            )
        except TenantResolutionError:
            return "Unknown tenant"

    set_current_tenant_context(context)
    return None


class WebSocketServer:
    """
    WebSocket endpoint handler.
    Authenticates the connection via token query param and returns claims.
    """

    @staticmethod
    async def authenticate(websocket: WebSocket) -> dict[str, Any] | None:
        """Validate the token query param and return claims, or None if invalid.

        Tries OIDC (Keycloak/external IdP) first, then platform-account
        JWTs (self-managed email+password users — HS256 platform-issued
        tokens carrying the ``tenant`` slug claim).  REST requests accept
        both via the auth middleware tiers; the WebSocket must too, or
        platform-account users can never connect to a conversation.
        """
        token = websocket.query_params.get("token")
        if not token:
            return None
        try:
            client = get_oidc_client()
            claims = await client.validate_token(token)
            return claims
        except OIDCError:
            pass
        except Exception:
            logger.warning("WebSocket auth: unexpected OIDC error", exc_info=True)
        # Fallback: platform-issued account token (carries ``tenant`` slug)
        try:
            from app.services.tenancy.platform_account_auth_service import (
                validate_platform_account_token,
            )

            return validate_platform_account_token(token)
        except Exception:
            logger.warning("WebSocket auth: platform token validation failed", exc_info=True)
            return None


@ws_router.websocket("/ws/sessions/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """
    Conversational agent WebSocket endpoint.

    Authenticates the connection, processes each inbound user message by:
      1. Persisting a ConversationTurn (user role)
      2. Building message history from all session turns
      3. Calling the configured LLM via ModelBindingLayer
      4. Persisting the agent response as a ConversationTurn
      5. Returning the agent response to the client

    Auto-names the session on the first message.
    """
    server = WebSocketServer()
    claims = await server.authenticate(websocket)
    if not claims:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected: invalid token for session %s", session_id)
        return

    await websocket.accept()
    subject = claims.get("sub", "unknown")

    # Bind the tenant context for this connection: WebSockets bypass the
    # HTTP tenant-resolution middleware, so all in-connection queries and
    # model/tool resolution would otherwise run context-less (fail-closed
    # under strict tenant scoping).  Platform-account JWTs carry ``tenant``
    # natively; OIDC tokens are resolved server-side from the user's active
    # membership (the same mechanism REST uses).  Fail-closed: an
    # unresolvable tenant under multi-tenancy rejects the connection.
    tenant_error = await _bind_connection_tenant_context(claims)
    if tenant_error:
        await websocket.close(code=4003, reason=tenant_error)
        logger.warning(
            "WebSocket rejected: %s for session %s (subject=%s)",
            tenant_error, session_id, claims.get("sub", "unknown"),
        )
        return

    # Register this WebSocket connection for intervention routing
    ActiveSessionTracker.register(session_id, websocket)

    # Cache the raw user JWT for dual-identity MCP tool calls
    user_jwt = websocket.query_params.get("token")
    if user_jwt:
        cache_user_jwt(session_id, user_jwt)
        logger.debug("Cached user JWT for session %s", session_id[:8])

    logger.info(
        "WebSocket connected: session=%s subject=%s",
        session_id,
        subject,
    )

    try:
        conv_session_id = uuid.UUID(session_id)
    except ValueError:
        await websocket.close(code=4003, reason="Invalid session ID format")
        return

    # Hydrate the persisted activity on connect (persistent agent activity
    # state): a fresh/restarted CH pushes the authoritative status immediately
    # so a reload/reconnect restores the processing indicator without an empty
    # window. Idle sessions (no live row) push ``state: null``. Best-effort.
    hydrated_activity = await _fetch_conversation_activity(websocket, conv_session_id)
    await _send_to_live_socket(
        session_id,
        websocket,
        _activity_state_message(hydrated_activity),
    )

    message_count = 0

    try:
        while True:
            raw_text = await websocket.receive_text()

            # Parse JSON payload
            try:
                payload = json.loads(raw_text)
            except (json.JSONDecodeError, AttributeError):
                # If payload is not JSON, treat as a plain text chat message
                payload = {"message": raw_text}

            # ── Handle intervention messages ───────────────────────────────
            msg_type = payload.get("type") if isinstance(payload, dict) else None

            if msg_type == "intervene_response":
                await _handle_intervention_response(
                    websocket, session_id, payload, subject,
                )
                continue

            if msg_type == "intervene_cancel":
                await _handle_intervention_cancel(
                    websocket, session_id, payload
                )
                continue

            # ── Client status watchdog ──────────────────────────────────────
            # The client sends this when no WS traffic was observed for the
            # stale threshold (e.g. after a sleep/wake or a dropped but not
            # yet detected socket). Reply with the server-side truth so the
            # client can reconcile its indicator (missing replies, pending
            # interventions) without waiting for the next natural event.
            if msg_type == "status_ping":
                # Source of truth is the PERSISTED activity in CC — the
                # in-memory task registry is kept only for cancellation. A
                # non-terminal persisted state means a turn is in flight even
                # when this CH process has no local task (restart/failover).
                activity = await _fetch_conversation_activity(websocket, conv_session_id)
                activity_state = (
                    activity.get("state")
                    if isinstance(activity, dict)
                    else None
                )
                turn_in_flight = bool(
                    activity_state and activity_state not in _TERMINAL_ACTIVITY_STATES
                )
                pong = _activity_state_message(activity)
                pong.update({
                    "type": "status_pong",
                    "turn_in_flight": turn_in_flight,
                    "intervention_pending": pong.get("pending_intervention", False),
                })
                await _send_to_live_socket(session_id, websocket, pong)
                continue

            # ── Handle live JWT refresh ────────────────────────────────────
            # OIDC access tokens expire while a conversation (or its pending
            # intervention) is still open; the frontend silently renews its
            # token but the renewed JWT never reached the WS-layer cache used
            # for CC management tool identity resolution. Pushing the fresh
            # token here keeps the cached JWT valid for the session lifetime.
            if msg_type == "token_refresh":
                token = payload.get("token") if isinstance(payload, dict) else None
                if not isinstance(token, str) or not token.strip():
                    await _send_to_live_socket(session_id, websocket, {
                        "type": "token_refresh_failed",
                        "message": "Missing token",
                    })
                    continue
                token = token.strip()
                valid = False
                try:
                    await get_oidc_client().validate_token(token)
                    valid = True
                except OIDCError:
                    pass
                except Exception:
                    logger.warning(
                        "token_refresh: unexpected OIDC error for session %s",
                        session_id[:8], exc_info=True,
                    )
                if not valid:
                    # Fallback: platform-issued account token (same tiers as
                    # the connection handshake in `authenticate` above).
                    try:
                        from app.services.tenancy.platform_account_auth_service import (
                            validate_platform_account_token,
                        )

                        if validate_platform_account_token(token):
                            valid = True
                    except Exception:
                        logger.warning(
                            "token_refresh: platform token validation failed for session %s",
                            session_id[:8], exc_info=True,
                        )
                if not valid:
                    # Do NOT overwrite the cached token on failure.
                    await _send_to_live_socket(session_id, websocket, {
                        "type": "token_refresh_failed",
                    })
                    continue
                cache_user_jwt(session_id, token)
                logger.debug(
                    "Refreshed cached user JWT for session %s", session_id[:8],
                )
                await _send_to_live_socket(session_id, websocket, {
                    "type": "token_refreshed",
                })
                continue

            # ── Block chat messages when intervention is pending ───────────
            if ActiveSessionTracker.has_pending_intervention(session_id):
                await _send_to_live_socket(session_id, websocket, {
                    "type": "chat_blocked",
                    "reason": "intervention_pending",
                    "message": "An intervention request is pending. Please respond to the intervention before sending new messages.",
                })
                continue

            # ── Process chat message ───────────────────────────────────────
            user_message: str = (
                payload.get("message", raw_text)
                if isinstance(payload, dict)
                else raw_text
            )

            user_message = user_message.strip()
            if not user_message:
                continue

            message_count += 1
            logger.debug(
                "Conversation user prompt received: message=%d session=%s length=%d",
                message_count,
                session_id,
                len(user_message),
                extra={"data": {"user_prompt": user_message}},
            )

            await _send_to_live_socket(
                session_id,
                websocket,
                {
                    "type": "chat_status",
                    **_build_chat_status_event("thinking"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Run the conversation turn as a background task so the WebSocket
            # loop is not blocked — this allows intervention response messages
            # to be processed while the turn waits for delegated agents.
            def _run_turn_and_reply() -> "asyncio.Task[None]":
                task = asyncio.create_task(
                    run_conversation_turn(
                        session_id=session_id,
                        conv_session_id=conv_session_id,
                        user_message=user_message,
                        is_first_message=(message_count == 1),
                        app=websocket.app,
                        websocket=websocket,
                        message_count=message_count,
                    )
                )
                _pending_turn_tasks[session_id] = task

                def _cleanup(done: "asyncio.Task[None]") -> None:
                    if _pending_turn_tasks.get(session_id) is done:
                        _pending_turn_tasks.pop(session_id, None)

                task.add_done_callback(_cleanup)
                return task

            _run_turn_and_reply()

    except WebSocketDisconnect as exc:
        # FIX-20261031-091657: log close code + reason so idle-proxy closes
        # are diagnosable instead of a silent drop.
        logger.info(
            "WebSocket disconnected: session=%s code=%s reason=%r",
            session_id,
            exc.code,
            exc.reason,
        )
    except Exception as exc:
        logger.error("WebSocket error for session %s: %s", session_id, exc, exc_info=True)
    finally:
        ActiveSessionTracker.unregister(session_id, websocket)


async def _handle_intervention_response(
    websocket: WebSocket, session_id: str, payload: dict[str, Any], subject: str = "",
) -> None:
    """Handle an intervene_response message from the WebSocket client."""
    request_id = payload.get("request_id")
    if not request_id:
        await _send_to_live_socket(session_id, websocket, {
            "type": "intervene_status",
            "status": "error",
            "message": "Missing request_id in intervention response",
        })
        return

    logger.info(
        "Received intervention response for request %s from session %s",
        request_id,
        session_id,
    )

    # Forward to Control Center via data client
    data_client: ControlCenterDataClient | None = getattr(
        websocket.app.state, "data_client", None
    )
    if data_client:
        try:
            # Build response payload matching InterveneResponseSubmit schema
            response_body: dict[str, Any] = {"request_id": request_id}
            approval = payload.get("approval_value")
            choice = payload.get("selected_choice")
            text = payload.get("text_value")
            if approval is not None:
                response_body["approval_value"] = approval
            elif choice is not None:
                response_body["selected_choice"] = choice
            elif text is not None:
                response_body["text_value"] = text

            # Submit via CC internal intervene endpoint (service cert, no JWT needed)
            response_body["operator_subject"] = subject
            with _signed_tenant_forwarding():
                await data_client._post(
                    "/internal/data/intervene/respond",
                    response_body,
                )
            logger.info("Intervention response %s persisted via CC", request_id)
        except Exception as exc:
            logger.error(
                "Failed to persist intervention response %s: %s",
                request_id,
                exc,
            )
            await _send_to_live_socket(session_id, websocket, {
                "type": "intervene_status",
                "request_id": request_id,
                "status": "error",
                "message": "Failed to submit intervention response",
            })
            return

    # Clear intervention active state
    ActiveSessionTracker.set_intervention_active(session_id, False)

    # Notify client of success
    await _send_to_live_socket(session_id, websocket, {
        "type": "intervene_status",
        "request_id": request_id,
        "status": "responded",
    })


async def _handle_intervention_cancel(
    websocket: WebSocket, session_id: str, payload: dict[str, Any]
) -> None:
    """Handle an intervene_cancel message from the WebSocket client."""
    request_id = payload.get("request_id")
    if not request_id:
        logger.warning("Received intervene_cancel without request_id from session %s", session_id)
        return

    logger.info(
        "Received intervention cancel for request %s from session %s",
        request_id,
        session_id,
    )

    # Forward cancellation to Control Center
    data_client: ControlCenterDataClient | None = getattr(
        websocket.app.state, "data_client", None
    )
    if data_client:
        try:
            with _signed_tenant_forwarding():
                await data_client._post(
                    f"/intervene/requests/{request_id}/cancel",
                    {},
                )
        except Exception as exc:
            logger.warning(
                "Failed to cancel intervention request %s via CC: %s",
                request_id,
                exc,
            )

    # Clear intervention state
    ActiveSessionTracker.set_intervention_active(session_id, False)

    # Notify client
    await _send_to_live_socket(session_id, websocket, {
        "type": "intervene_status",
        "request_id": request_id,
        "status": "cancelled",
    })


async def _process_message(
    conv_session_id: uuid.UUID,
    user_message: str,
    is_first_message: bool,
    app: Any,
    on_status_event: Callable[[dict[str, str]], Awaitable[None]] | None = None,
    on_reply: Callable[[str], Awaitable[None]] | None = None,
    on_guardrail_usage: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> tuple[str, str | None, dict[str, Any] | None, list[dict[str, str]]]:
    """
    Persist user turn, call LLM, persist agent turn, optionally auto-name the session.

    ``on_reply`` (FIX-20261031-091657) is invoked with the agent reply the
    moment the LLM delegation returns — BEFORE the persistence call — so a
    slow/hung persistence path can never delay or swallow the live reply.

    ``on_guardrail_usage`` (guardrail-panel regression fix) is invoked with
    the guardrail usage the moment the LLM delegation returns — also BEFORE
    the persistence call — so a slow/failing ``append_conversation_turn``
    can never swallow the ``guardrail_update`` websocket event (the panel
    previously went dark whenever persistence hung after a delivered reply).

    Returns:
        (agent_reply, session_title, guardrail_usage, status_events) — session_title is set only on the first message.
    """
    data_client: ControlCenterDataClient | None = getattr(app.state, "data_client", None)
    if data_client is None:
        logger.error("Control Center data client is unavailable in Communication Hub app state")
        return "Service temporarily unavailable. Please try again.", None, None, []

    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, str]] = []

    with _signed_tenant_forwarding():
        prepared = await data_client.prepare_conversation_turn(conv_session_id, user_message)

    no_agent_message = prepared.get("no_agent_message")
    agent_type_id_raw = prepared.get("agent_type_id")
    prepared_messages = prepared.get("messages") or []

    if no_agent_message:
        agent_reply = str(no_agent_message)
    elif agent_type_id_raw:
        # The conversational dispatch into Agent Runtime must carry the
        # signed tenant context too: AR's execution binds the forwarded set
        # and replays it on every AR→CC data call (PATCH status, result
        # submission, execution logs).  Mint fresh at delegate time so a
        # long turn never reuses a stale signature from the connect-time
        # bind.
        with _signed_tenant_forwarding():
            agent_reply, guardrail_usage, status_events = await _call_llm(
                conv_session_id=conv_session_id,
                agent_type_id=uuid.UUID(str(agent_type_id_raw)),
                messages=prepared_messages,
                app=app,
                on_status_event=on_status_event,
            )
    else:
        agent_reply = "No model is configured for this agent."

    if on_guardrail_usage is not None and guardrail_usage:
        with contextlib.suppress(Exception):
            await on_guardrail_usage(guardrail_usage)

    if on_reply is not None:
        await on_reply(agent_reply)

    with _signed_tenant_forwarding():
        appended = await data_client.append_conversation_turn(
            conv_session_id=conv_session_id,
            agent_reply=agent_reply,
            is_first_message=is_first_message,
            first_user_message=user_message if is_first_message else None,
            guardrail_usage=guardrail_usage,
            status_events=status_events,
        )
    session_title = appended.get("title")
    return agent_reply, (str(session_title) if session_title else None), guardrail_usage, status_events


async def _call_llm(
    conv_session_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    messages: list[dict[str, str]],
    app: Any,
    on_status_event: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any] | None, list[dict[str, str]]]:
    """Execute one conversation turn using the deep agent framework.

    Returns the agent's text response, or a friendly error string on failure.
    """
    try:
        logger.debug(
            "Conversation message history assembled for session %s",
            conv_session_id,
            extra={
                "data": {
                    "message_count": len(messages),
                    "user_message_count": sum(1 for m in messages if m.get("role") == "user"),
                    "assistant_message_count": sum(1 for m in messages if m.get("role") == "assistant"),
                    "system_message_count": sum(1 for m in messages if m.get("role") == "system"),
                    "latest_user_prompt": next(
                        (
                            m.get("content")
                            for m in reversed(messages)
                            if m.get("role") == "user"
                        ),
                        None,
                    ),
                }
            },
        )

        logger.debug(
            "Delegating session %s conversation turn to Agent Runtime (%d messages, system=%s)",
            conv_session_id,
            len(messages),
            any(m.get("role") == "system" for m in messages),
        )
        return await _delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=messages,
            on_status_event=on_status_event,
        )

    except ConversationTurnError:
        # Structured, actionable error (e.g. assistant_model_not_configured) —
        # propagated so the WebSocket loop can surface the typed payload.
        raise
    except ModelBindingError as exc:
        logger.warning("Model binding error for session %s: %s", conv_session_id, exc)
        return (
            "Unable to process your message: the model for this workspace is not "
            "available or not configured correctly. Please contact your administrator.",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )
    except httpx.HTTPStatusError as exc:
        mapped = _conversation_turn_error_from_http_status(exc)
        if mapped is not None:
            raise mapped
        logger.warning(
            "Conversation turn rejected for session %s: %s", conv_session_id, exc
        )
        return (
            "An error occurred while processing your message. Please try again.",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )
    except httpx.TimeoutException as exc:
        logger.warning("Conversation timeout for session %s: %s", conv_session_id, exc)
        return (
            "An error occurred while processing your message. Please try again.",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )
    except Exception as exc:
        logger.error(
            "LLM call error for session %s: %s",
            conv_session_id,
            exc,
            exc_info=True,
        )
        return (
            "An error occurred while processing your message. Please try again.",
            None,
            [_build_chat_status_event("timeout_or_failed")],
        )


async def _delegate_conversation_turn_to_agent_runtime(
    app: Any,
    conv_session_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    messages: list[dict[str, str]],
    on_status_event: Callable[[dict[str, str]], Awaitable[None]] | None = None,
) -> tuple[str, dict[str, Any] | None, list[dict[str, str]]]:
    """Call Agent Runtime to execute one conversation turn.

    Communication Hub owns websocket transport but delegates execution logic to
    Agent Runtime so the runtime boundary remains explicit.
    """
    settings = get_settings()
    ar_base = (settings.agent_runtime_url or "http://localhost:8001").rstrip("/")
    endpoint = f"{ar_base}/internal/conversation/turn"
    # When streaming status events, disable the HTTP timeout — the connection
    # is kept alive by the NDJSON stream and HITL pauses may last indefinitely.
    # The WebSocket disconnect or AR failure will close the TCP connection.
    if on_status_event is not None:
        timeout_seconds = None  # No timeout for streaming connections
    else:
        configured_timeout = int(getattr(settings, "agent_question_timeout_seconds", 300))
        timeout_seconds = float(max(30, configured_timeout))

    payload = {
        "conv_session_id": str(conv_session_id),
        "agent_type_id": str(agent_type_id),
        "messages": messages,
        "stream_status_events": bool(on_status_event),
    }

    cert_manager = getattr(app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": timeout_seconds,
        "verify": get_ssl_context(),
    }
    # Multi-tenancy: forward the signed tenant header set minted by
    # ``_signed_tenant_forwarding`` (single-tenant mode → {}, unchanged).
    # Agent Runtime verifies this set, binds it, and forwards it verbatim
    # on its AR→CC data calls — without it, AR's first PATCH of the
    # session status fails closed with 401 once multi-tenancy is on.
    from app.core.tenant_signature import forward_tenant_headers

    headers: dict[str, str] = dict(forward_tenant_headers())

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if ar_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            from pathlib import Path

            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")

    async with httpx.AsyncClient(**client_kwargs) as client:
        if on_status_event is not None:
            status_events: list[dict[str, str]] = []
            final_response = ""
            final_guardrail_usage: dict[str, Any] | None = None

            async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    chunk_type = chunk.get("type")
                    if chunk_type == "status_event":
                        item = chunk.get("event")
                        logger.info(
                            "CH received status event for session %s: %s",
                            conv_session_id,
                            item,
                        )
                        if not isinstance(item, dict):
                            continue
                        status_value = item.get("status")
                        if not isinstance(status_value, str) or not status_value:
                            continue
                        agent_type = item.get("agent_type")
                        tool_name = item.get("tool_name")
                        normalized = _build_chat_status_event(
                            status_value,
                            agent_type if isinstance(agent_type, str) and agent_type else None,
                            tool_name if isinstance(tool_name, str) and tool_name else None,
                            item.get("receiver_session_id")
                            if isinstance(item.get("receiver_session_id"), str)
                            and item.get("receiver_session_id")
                            else None,
                            item.get("timestamp")
                            if isinstance(item.get("timestamp"), str) and item.get("timestamp")
                            else None,
                        )
                        status_events.append(normalized)
                        # Persist the transition via CC (best-effort) so the
                        # authoritative activity state survives CH restarts
                        # and reconnects — before/alongside the live push.
                        await _persist_activity_transition(
                            app,
                            conv_session_id,
                            status_value,
                            normalized.get("agent_type"),
                            normalized.get("tool_name"),
                        )
                        await on_status_event(normalized)
                        continue

                    if chunk_type == "final":
                        final_response = str(chunk.get("response") or "")
                        guardrail_raw = chunk.get("guardrail_usage")
                        final_guardrail_usage = (
                            guardrail_raw if isinstance(guardrail_raw, dict) else None
                        )
                        break

                    if chunk_type == "error":
                        # FIX-20261101-111439: AR now forwards guardrail stop
                        # reasons (e.g. ``iteration_limit``) so Control Center
                        # can raise a structured, user-comprehensible turn
                        # error instead of a generic RuntimeError.
                        error_type = chunk.get("error_type")
                        if isinstance(error_type, str) and error_type in _GUARDRAIL_STOP_CODES:
                            details = (
                                chunk.get("error_details")
                                if isinstance(chunk.get("error_details"), dict)
                                else {}
                            )
                            raise _conversation_turn_error_from_guardrail_stop(
                                error_type, details
                            )
                        raise RuntimeError("Agent Runtime streaming error")

            return final_response, final_guardrail_usage, status_events

        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        status_events_raw = body.get("status_events")
        status_events: list[dict[str, str]] = []
        if isinstance(status_events_raw, list):
            for item in status_events_raw:
                if not isinstance(item, dict):
                    continue
                status_value = item.get("status")
                if not isinstance(status_value, str) or not status_value:
                    continue
                agent_type = item.get("agent_type")
                tool_name = item.get("tool_name")
                status_events.append(
                    _build_chat_status_event(
                        status_value,
                        agent_type if isinstance(agent_type, str) and agent_type else None,
                        tool_name if isinstance(tool_name, str) and tool_name else None,
                        item.get("receiver_session_id")
                        if isinstance(item.get("receiver_session_id"), str)
                        and item.get("receiver_session_id")
                        else None,
                    )
                )

        return str(body.get("response") or ""), body.get("guardrail_usage"), status_events


