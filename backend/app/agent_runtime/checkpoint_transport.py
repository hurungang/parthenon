"""Agent Runtime → Communication Hub courier for durable paused-turn state.

A paused conversational turn is durably resumable because two Control
Center–owned records survive the Agent Runtime process:

* the **resume index** (``ConversationTurnResume``) — the authoritative
  lifecycle record of the paused turn, and
* the **checkpoint payload** (``ConversationTurnCheckpoint``) — the opaque,
  versioned agent-framework state needed to rebuild the turn.

Agent Runtime produces and consumes both, but **owns neither**.  This module
is AR's *only* path to them: every call is an HTTP call to Communication Hub,
built with the shared :func:`internal_httpx_client` egress helper (AR
certificate + forwarded signed tenant headers).  There is deliberately:

* no SQLAlchemy import, no database session, no connection string;
* no direct Control Center call — CH relays to CC over the CH service
  certificate;
* no credential / identity token in the checkpoint payload.

Routes target the CH relay surface planned for the "resumable-agent-turn-
persistence" change (Communication Hub phase):

===============================  ============================================
``PUT  /internal/checkpoint/{id}``   save the opaque checkpoint payload
``GET  /internal/checkpoint/{id}``   load the opaque checkpoint payload
``PUT  /internal/turn-resume/{id}``  create/refresh the resume index
``GET  /internal/turn-resume/{id}``  read the live resume index
``POST /internal/turn-resume/{id}/claim``     acquire/renew the turn claim
``POST /internal/turn-resume/{id}/release``   release the claim (best effort)
``POST /internal/turn-resume/{id}/complete``  single-transaction closer
===============================  ============================================

Failures raise a typed :class:`CheckpointTransportError` so the executor can
tell "the relay is not deployed (degrade to the legacy in-process pause)"
(:class:`CheckpointTransportUnavailableError`) apart from "the relay refused
this write" (fail the pause closed instead of pretending to wait).
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.internal_http import internal_httpx_client
from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

#: AR-facing Communication Hub relay route templates.
CH_CHECKPOINT_PATH = "/internal/checkpoint/{conv_session_id}"
CH_TURN_RESUME_PATH = "/internal/turn-resume/{conv_session_id}"
CH_TURN_RESUME_CLAIM_PATH = "/internal/turn-resume/{conv_session_id}/claim"
CH_TURN_RESUME_RELEASE_PATH = "/internal/turn-resume/{conv_session_id}/release"
CH_TURN_RESUME_COMPLETE_PATH = "/internal/turn-resume/{conv_session_id}/complete"

#: HTTP statuses that always mean "this relay surface is not deployed here".
#: (404 is handled separately: an unknown route answers ``{"detail": "Not
#: Found"}`` while the relay's resource 404s carry a specific detail.)
_RELAY_UNAVAILABLE_STATUSES = frozenset({405, 501, 503})

ClientFactory = Callable[[], Any]


def _is_route_missing(response: httpx.Response) -> bool:
    """True when the response means the relay route is not deployed.

    Communication Hub (FastAPI) answers an unknown path with
    ``404 {"detail": "Not Found"}``; the relay's *resource* 404s always carry a
    specific detail.  Plus the explicit "not implemented / unavailable"
    statuses.  This is what lets the executor tell "Phase-4 CH absent" apart
    from "the relay refused this write".
    """
    if response.status_code in _RELAY_UNAVAILABLE_STATUSES:
        return True
    if response.status_code != 404:
        return False
    try:
        detail = (response.json() or {}).get("detail")
    except Exception:  # noqa: BLE001 - non-JSON body
        return False
    return str(detail or "").strip().lower() in {"not found", "not_found"}


class CheckpointTransportError(Exception):
    """Base class for AR ↔ CH checkpoint/resume courier failures."""


class CheckpointTransportUnavailableError(CheckpointTransportError):
    """The CH checkpoint/resume relay is not reachable or not deployed.

    Raised for connection failures, timeouts, 405/501/503 responses, and an
    unknown-route 404 (``{"detail": "Not Found"}``).  The executor treats this
    as "durable path unavailable" and keeps the pre-existing in-process pause
    behaviour instead of failing the turn.
    """


class ResumeIndexNotFoundError(CheckpointTransportError):
    """No live resume record exists for the conversation session."""


class ResumeClaimContentionError(CheckpointTransportError):
    """Another Agent Runtime instance currently holds the turn claim."""

    def __init__(
        self,
        message: str,
        *,
        holder_instance_id: str | None = None,
        claim_expires_at: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.holder_instance_id = holder_instance_id
        self.claim_expires_at = claim_expires_at


class CheckpointNotFoundError(CheckpointTransportError):
    """The live resume record has no loadable checkpoint payload."""


class ResumeIndexRead(BaseModel):
    """The resume index read model returned by Control Center (no payload)."""

    resume_id: uuid.UUID
    conversation_session_id: uuid.UUID
    resume_key: str
    idempotency_key: str | None = None
    state: str
    resume_outcome: str | None = None
    expires_at: datetime | None = None
    write_applied: bool = False
    is_terminal: bool = False
    terminal_reason_code: str | None = None
    terminal_message_key: str | None = None
    attempt_count: int = 0
    outcome_turn_id: uuid.UUID | None = None
    active_resume_id: uuid.UUID | None = None

    @property
    def is_waiting(self) -> bool:
        return self.state == "waiting_for_human" and not self.is_terminal


class ResumeClaimRead(BaseModel):
    """Claim arbitration result (``acquired`` / ``already_held`` / ...)."""

    status: str
    resume: ResumeIndexRead | None = None
    holder_instance_id: str | None = None
    claim_expires_at: datetime | None = None


class CheckpointRead(BaseModel):
    """Opaque checkpoint envelope as returned on a load."""

    resume_id: uuid.UUID
    payload_kind: str
    schema_version: int
    payload_bytes: int
    is_consumed: bool = False
    expires_at: datetime | None = None
    payload: dict[str, Any] | None = None


class CheckpointSaveResult(BaseModel):
    """Metadata returned after a checkpoint write (payload never echoed)."""

    resume_id: uuid.UUID
    payload_kind: str
    schema_version: int
    payload_bytes: int
    is_consumed: bool = False
    expires_at: datetime | None = None


class CheckpointTransportClient:
    """Courier for the CC-owned resume index and checkpoint payload.

    Instantiate once per operation (it is cheap) and pass the Agent Runtime
    certificate paths resolved from ``app.state.certificate_manager``.  Tests
    inject ``client_factory`` (or an ``httpx`` transport via ``http_transport``)
    to run against a fake socket.
    """

    def __init__(
        self,
        *,
        comm_hub_url: str | None = None,
        cert_path: str | None = None,
        key_path: str | None = None,
        timeout_seconds: float = 30.0,
        client_factory: ClientFactory | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._comm_hub_url = (
            comm_hub_url
            or getattr(get_settings(), "communication_hub_url", "http://localhost:8002")
        ).rstrip("/")
        self._cert_path = cert_path
        self._key_path = key_path
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory
        self._http_transport = http_transport

    # ── Configuration ────────────────────────────────────────────────────────

    def set_certificate(self, cert_path: str, key_path: str) -> None:
        """Set the Agent Runtime instance certificate used for mTLS."""
        self._cert_path = cert_path
        self._key_path = key_path

    # ── Egress ───────────────────────────────────────────────────────────────

    def _build_client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "timeout": self._timeout_seconds,
            "verify": get_ssl_context(),
        }
        if self._http_transport is not None:
            kwargs["transport"] = self._http_transport
        return kwargs

    def _build_headers(self) -> dict[str, str]:
        """Transport-level headers only — tenant headers come from the hook."""
        headers: dict[str, str] = {}
        if not (self._cert_path and self._key_path):
            return headers
        if self._comm_hub_url.startswith("https://"):
            return headers
        # Development over plain HTTP: present the certificate as a header
        # (same convention as the tool-call / A2A clients).
        headers["X-Client-Certificate"] = (
            Path(self._cert_path).read_text().replace("\n", "\\n")
        )
        return headers

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client_factory is not None:
            async with self._client_factory() as client:  # type: ignore[misc]
                yield client
            return
        kwargs = self._build_client_kwargs()
        if (
            self._cert_path
            and self._key_path
            and self._comm_hub_url.startswith("https://")
        ):
            kwargs["cert"] = (self._cert_path, self._key_path)
        async with internal_httpx_client(**kwargs) as client:
            yield client

    def _url(self, template: str, conv_session_id: uuid.UUID) -> str:
        return f"{self._comm_hub_url}{template.format(conv_session_id=conv_session_id)}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Issue one relay request, mapping transport failures to typed errors."""
        try:
            async with self._client() as client:
                response = await client.request(
                    method, url, json=json_body, headers=self._build_headers()
                )
        except httpx.HTTPError as exc:
            raise CheckpointTransportUnavailableError(
                f"Communication Hub checkpoint relay unreachable ({method} {url}): {exc}"
            ) from exc

        if _is_route_missing(response):
            raise CheckpointTransportUnavailableError(
                f"Communication Hub checkpoint relay unavailable "
                f"({method} {url} → HTTP {response.status_code})"
            )
        return response

    @staticmethod
    def _json_or_none(response: httpx.Response) -> Any:
        """Return the decoded body, or ``None`` for an empty/``null`` body."""
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except Exception:  # noqa: BLE001 - empty/invalid body means "no value"
            return None

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, url: str) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:500]
        if response.status_code == 404:
            raise ResumeIndexNotFoundError(
                f"No live resume record ({url}): {detail}"
            )
        if response.status_code == 409:
            raise ResumeClaimContentionError(
                f"Turn claim contention ({url}): {detail}"
            )
        raise CheckpointTransportError(
            f"Checkpoint relay rejected {url}: HTTP {response.status_code} — {detail}"
        )

    # ── Checkpoint payload ───────────────────────────────────────────────────

    async def save_checkpoint(
        self,
        conv_session_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        schema_version: int = 1,
        payload_kind: str = "agent_turn_state",
        expires_at: datetime | None = None,
    ) -> CheckpointSaveResult:
        """Persist the opaque paused-turn payload for the live resume record."""
        url = self._url(CH_CHECKPOINT_PATH, conv_session_id)
        body: dict[str, Any] = {
            "payload": payload,
            "payload_kind": payload_kind,
            "schema_version": schema_version,
        }
        if expires_at is not None:
            body["expires_at"] = expires_at.isoformat()
        response = await self._request("PUT", url, json_body=body)
        self._raise_for_status(response, url=url)
        return CheckpointSaveResult.model_validate(response.json())

    async def load_checkpoint(
        self,
        conv_session_id: uuid.UUID,
    ) -> CheckpointRead | None:
        """Load the opaque payload; ``None`` when absent, consumed or expired."""
        url = self._url(CH_CHECKPOINT_PATH, conv_session_id)
        response = await self._request("GET", url)
        if response.status_code == 404:
            return None
        self._raise_for_status(response, url=url)
        data = self._json_or_none(response)
        if data is None:
            return None
        checkpoint = CheckpointRead.model_validate(data)
        if checkpoint.payload is None:
            return None
        return checkpoint

    # ── Resume index / claim lifecycle ───────────────────────────────────────

    async def save_resume_index(
        self,
        conv_session_id: uuid.UUID,
        *,
        intervene_request_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
        expires_at: datetime | None = None,
        resume_key: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResumeIndexRead:
        """Create or refresh the live resume index record for a pause.

        ``intervene_request_id`` is what makes the call idempotent: a replayed
        pause intent for the same confirmation reuses the existing record
        instead of superseding it.
        """
        url = self._url(CH_TURN_RESUME_PATH, conv_session_id)
        body: dict[str, Any] = {}
        if intervene_request_id is not None:
            body["intervene_request_id"] = str(intervene_request_id)
        if turn_id is not None:
            body["turn_id"] = str(turn_id)
        if expires_at is not None:
            body["expires_at"] = expires_at.isoformat()
        if resume_key:
            body["resume_key"] = resume_key
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        response = await self._request("PUT", url, json_body=body)
        self._raise_for_status(response, url=url)
        return ResumeIndexRead.model_validate(response.json())

    async def get_resume_index(
        self,
        conv_session_id: uuid.UUID,
    ) -> ResumeIndexRead | None:
        """Return the session's live resume record (``None`` when idle)."""
        url = self._url(CH_TURN_RESUME_PATH, conv_session_id)
        response = await self._request("GET", url)
        if response.status_code == 404:
            return None
        self._raise_for_status(response, url=url)
        data = self._json_or_none(response)
        if data is None:
            return None
        return ResumeIndexRead.model_validate(data)

    async def claim(
        self,
        conv_session_id: uuid.UUID,
        *,
        instance_id: str,
        lease_seconds: int | None = None,
    ) -> ResumeClaimRead:
        """Claim (or renew) the paused turn for this AR instance."""
        lease = int(
            lease_seconds
            if lease_seconds is not None
            else getattr(get_settings(), "conversation_turn_claim_ttl_seconds", 45)
        )
        url = self._url(CH_TURN_RESUME_CLAIM_PATH, conv_session_id)
        response = await self._request(
            "POST",
            url,
            json_body={"instance_id": instance_id, "lease_seconds": max(1, lease)},
        )
        self._raise_for_status(response, url=url)
        return ResumeClaimRead.model_validate(response.json())

    async def release(
        self,
        conv_session_id: uuid.UUID,
        *,
        instance_id: str | None = None,
    ) -> bool:
        """Release this instance's claim (best effort)."""
        url = self._url(CH_TURN_RESUME_RELEASE_PATH, conv_session_id)
        body: dict[str, Any] = {}
        if instance_id:
            body["instance_id"] = instance_id
        response = await self._request("POST", url, json_body=body)
        if response.status_code == 404:
            return False
        self._raise_for_status(response, url=url)
        data = self._json_or_none(response) or {}
        return bool(data.get("released", False))

    async def complete_resume(
        self,
        conv_session_id: uuid.UUID,
        *,
        outcome: str,
        write_applied: bool = False,
        applied_by_user_id: uuid.UUID | None = None,
        applied_effect_summary: dict[str, Any] | None = None,
        outcome_turn_id: uuid.UUID | None = None,
        outcome_turn_content: str | None = None,
        consume_checkpoint: bool = True,
        resume_id: uuid.UUID | None = None,
    ) -> ResumeIndexRead:
        """Close the paused turn exactly once with a terminal outcome."""
        url = self._url(CH_TURN_RESUME_COMPLETE_PATH, conv_session_id)
        body: dict[str, Any] = {
            "outcome": outcome,
            "write_applied": write_applied,
            "consume_checkpoint": consume_checkpoint,
        }
        if resume_id is not None:
            body["resume_id"] = str(resume_id)
        if applied_by_user_id is not None:
            body["applied_by_user_id"] = str(applied_by_user_id)
        if applied_effect_summary is not None:
            body["applied_effect_summary"] = applied_effect_summary
        if outcome_turn_id is not None:
            body["outcome_turn_id"] = str(outcome_turn_id)
        if outcome_turn_content is not None:
            body["outcome_turn_content"] = outcome_turn_content
        response = await self._request("POST", url, json_body=body)
        self._raise_for_status(response, url=url)
        return ResumeIndexRead.model_validate(response.json())


#: Explicit type alias kept for callers that only need the read model.
ResumeIndexRecord = ResumeIndexRead

#: Header carrying the paused turn's opaque idempotency key on the
#: confirmed-write tool call (AR → CH → CC).
TURN_IDEMPOTENCY_HEADER = "X-Turn-Idempotency-Key"


def turn_idempotency_headers(idempotency_key: str | None) -> dict[str, str]:
    """Return the idempotency header set (empty when not inside a paused turn)."""
    if not idempotency_key:
        return {}
    return {TURN_IDEMPOTENCY_HEADER: idempotency_key}


__all__ = [
    "CH_CHECKPOINT_PATH",
    "CH_TURN_RESUME_PATH",
    "CH_TURN_RESUME_CLAIM_PATH",
    "CH_TURN_RESUME_RELEASE_PATH",
    "CH_TURN_RESUME_COMPLETE_PATH",
    "CheckpointNotFoundError",
    "CheckpointRead",
    "CheckpointSaveResult",
    "CheckpointTransportClient",
    "CheckpointTransportError",
    "CheckpointTransportUnavailableError",
    "ResumeClaimContentionError",
    "ResumeClaimRead",
    "ResumeIndexNotFoundError",
    "ResumeIndexRead",
    "ResumeIndexRecord",
    "TURN_IDEMPOTENCY_HEADER",
    "turn_idempotency_headers",
]
