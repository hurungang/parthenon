"""Communication Hub — AR-facing checkpoint / resume-index relay.

Agent Runtime is a courier: it produces and consumes the durable paused-turn
state (a Control Center–owned resume index plus an opaque checkpoint payload)
but holds no database access and never calls Control Center directly.  This
router is the AR → CH → CC relay that gives AR its only path to that state:

=========================================  ==================================
AR-facing route (Communication Hub)        Control Center internal route
=========================================  ==================================
``PUT  /internal/checkpoint/{id}``         ``PUT  .../{id}/resume/checkpoint``
``GET  /internal/checkpoint/{id}``         ``GET  .../{id}/resume/checkpoint``
``PUT  /internal/turn-resume/{id}``        ``PUT  .../{id}/resume``
``GET  /internal/turn-resume/{id}``        ``GET  .../{id}/resume``
``POST /internal/turn-resume/{id}/claim``  ``POST .../{id}/resume/claim``
``POST /internal/turn-resume/{id}/release``  ``POST .../{id}/resume/release``
``POST /internal/turn-resume/{id}/complete``  ``POST .../{id}/resume/complete``
=========================================  ==================================

Transport rules enforced here (the service boundary is structural):

* **Byte-for-byte relay** — a successful upstream body is replayed unchanged;
  Communication Hub never parses, rewrites or re-serialises the checkpoint
  payload (the only inspection is the configured byte-size guard).
* **Forward-only** — the tenant header set is attached by the single shared
  egress hook (``internal_httpx_client``): the set Control Center signed and
  Communication Hub's middleware verified is forwarded verbatim.  Nothing here
  signs, and no client-supplied tenant is ever accepted.
* **No silent empties** — an upstream 4xx/5xx is surfaced as a typed relay
  error (upstream status preserved) instead of an empty payload; an
  unreachable Control Center maps to 503 so Agent Runtime can tell "relay
  unavailable" from "this write was refused".

Route templates match :data:`app.agent_runtime.checkpoint_transport` exactly.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from app.communication_hub.data_client import (
    ControlCenterDataClient,
    ControlCenterDataError,
    InternalRelayResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["Internal - Turn Checkpoint Relay"])

#: CC 5xx / transport failure → "the relay cannot serve this request right now".
_RELAY_UNAVAILABLE_STATUS = 503
#: Upstream statuses we relay verbatim (everything else collapses to 502).
_RELAYED_UPSTREAM_STATUSES = frozenset({400, 403, 404, 409, 413, 422})


class TurnCheckpointRelayError(Exception):
    """A typed relay failure carrying the upstream status and detail.

    Raised instead of returning an empty payload; the route converts it into
    an HTTP response that mirrors the upstream failure so Agent Runtime's
    transport maps it to its own typed errors (404 → no record, 409 →
    contention, 413 → payload too large, ...).
    """

    def __init__(self, *, upstream_status: int, detail: str, path: str) -> None:
        super().__init__(detail)
        self.upstream_status = upstream_status
        self.detail = detail
        self.path = path

    @property
    def relay_status(self) -> int:
        """HTTP status Communication Hub returns for this upstream failure."""
        if self.upstream_status >= 500:
            return _RELAY_UNAVAILABLE_STATUS
        if self.upstream_status in _RELAYED_UPSTREAM_STATUSES:
            return self.upstream_status
        return 502


def _data_client(request: Request) -> ControlCenterDataClient:
    client: ControlCenterDataClient | None = getattr(
        request.app.state, "data_client", None
    )
    if client is None:
        raise HTTPException(
            status_code=_RELAY_UNAVAILABLE_STATUS,
            detail="Control Center data client is unavailable",
        )
    return client


async def _relay(
    request: Request,
    method: str,
    cc_path: str,
    *,
    raw_body: bytes | None = None,
) -> Response:
    """Relay one call to Control Center and replay its status/body unchanged."""
    client = _data_client(request)
    try:
        result: InternalRelayResponse = await client.relay_internal(
            method, cc_path, raw_body=raw_body
        )
    except ControlCenterDataError as exc:
        # Never a silent empty payload: the caller must see the relay failure.
        logger.warning(
            "Turn resume relay failed: %s /api/v1%s — %s", method, cc_path, exc
        )
        raise HTTPException(
            status_code=_RELAY_UNAVAILABLE_STATUS,
            detail={"error": "relay_unavailable", "detail": str(exc)},
        ) from exc

    if not result.is_success:
        error = TurnCheckpointRelayError(
            upstream_status=result.status_code,
            detail=result.content.decode("utf-8", errors="replace")[:500],
            path=cc_path,
        )
        logger.info(
            "Turn resume relay upstream rejection: %s /api/v1%s → HTTP %s",
            method,
            cc_path,
            result.status_code,
        )
        raise HTTPException(
            status_code=error.relay_status,
            detail={
                "error": "relay_error",
                "upstream_status": error.upstream_status,
                "detail": error.detail,
            },
        )

    logger.debug(
        "Turn resume relay: %s /api/v1%s → HTTP %s (%d bytes)",
        method,
        cc_path,
        result.status_code,
        len(result.content),
    )
    return Response(
        content=result.content,
        status_code=result.status_code,
        media_type=result.media_type or "application/json",
    )


# ── Opaque checkpoint payload ────────────────────────────────────────────────


@router.put("/checkpoint/{conv_session_id}")
async def save_turn_checkpoint(
    conv_session_id: uuid.UUID, request: Request
) -> Response:
    """Relay an opaque paused-turn checkpoint write (size-guarded, unread)."""
    from app.core.config import get_settings

    raw_body = await request.body()
    guard_bytes = int(get_settings().conversation_turn_checkpoint_max_bytes)
    if guard_bytes > 0 and len(raw_body) > guard_bytes:
        logger.warning(
            "Checkpoint relay rejected oversized payload for conversation %s: "
            "%d bytes > %d byte guard",
            conv_session_id,
            len(raw_body),
            guard_bytes,
        )
        raise HTTPException(
            status_code=413,
            detail={
                "error": "checkpoint_payload_too_large",
                "payload_bytes": len(raw_body),
                "guard_bytes": guard_bytes,
            },
        )
    return await _relay(
        request,
        "PUT",
        f"/internal/data/conversations/{conv_session_id}/resume/checkpoint",
        raw_body=raw_body,
    )


@router.get("/checkpoint/{conv_session_id}")
async def load_turn_checkpoint(
    conv_session_id: uuid.UUID, request: Request
) -> Response:
    """Relay an opaque paused-turn checkpoint read (body never inspected)."""
    return await _relay(
        request,
        "GET",
        f"/internal/data/conversations/{conv_session_id}/resume/checkpoint",
    )


# ── Resume index lifecycle ───────────────────────────────────────────────────


@router.put("/turn-resume/{conv_session_id}")
async def save_turn_resume(conv_session_id: uuid.UUID, request: Request) -> Response:
    """Relay a pause intent (create-or-reuse the live resume record)."""
    return await _relay(
        request,
        "PUT",
        f"/internal/data/conversations/{conv_session_id}/resume",
        raw_body=await request.body(),
    )


@router.get("/turn-resume/{conv_session_id}")
async def get_turn_resume(conv_session_id: uuid.UUID, request: Request) -> Response:
    """Relay a read of the live resume record (explicit ``null`` when idle)."""
    return await _relay(
        request,
        "GET",
        f"/internal/data/conversations/{conv_session_id}/resume",
    )


@router.post("/turn-resume/{conv_session_id}/claim")
async def claim_turn_resume(conv_session_id: uuid.UUID, request: Request) -> Response:
    """Relay turn-claim arbitration (acquired / already_held / terminal / not_found)."""
    return await _relay(
        request,
        "POST",
        f"/internal/data/conversations/{conv_session_id}/resume/claim",
        raw_body=await request.body(),
    )


@router.post("/turn-resume/{conv_session_id}/release")
async def release_turn_resume(
    conv_session_id: uuid.UUID, request: Request
) -> Response:
    """Relay a best-effort claim release."""
    return await _relay(
        request,
        "POST",
        f"/internal/data/conversations/{conv_session_id}/resume/release",
        raw_body=await request.body(),
    )


@router.post("/turn-resume/{conv_session_id}/complete")
async def complete_turn_resume(
    conv_session_id: uuid.UUID, request: Request
) -> Response:
    """Relay the single-transaction closer (outcome turn + terminal state)."""
    return await _relay(
        request,
        "POST",
        f"/internal/data/conversations/{conv_session_id}/resume/complete",
        raw_body=await request.body(),
    )


__all__ = [
    "TurnCheckpointRelayError",
    "claim_turn_resume",
    "complete_turn_resume",
    "get_turn_resume",
    "load_turn_checkpoint",
    "release_turn_resume",
    "router",
    "save_turn_checkpoint",
    "save_turn_resume",
]
