"""Conversational turn resume from the durable checkpoint (Agent Runtime).

The operator's answer arrives at Control Center, which dispatches **one**
resume through Communication Hub.  Whatever Agent Runtime instance receives it
must be able to continue the paused turn even if it never saw the original
execution.  This service performs that continuation:

1. **claim** the paused turn (one instance at a time; contention → 409);
2. read the live **resume index** (authoritative: state, idempotency key);
3. **load** the opaque checkpoint payload and deserialize it (a payload that
   cannot be understood resolves the turn as ``unresumable``/``resume_failed``);
4. rebuild the same agent context/model/callback wiring and the same tool set;
5. ``ainvoke(Command(resume=<operator response>))`` with the durable
   checkpointer seeded from the payload;
6. stream status events and finish with ``final`` — or, if the resumed turn
   pauses again, persist the new pause and finish with ``paused``.

AR remains a courier: the checkpoint and resume index are reached only through
:class:`CheckpointTransportClient` (AR → CH → CC).  Nothing here imports a
database session, and no credential is read from or written to the payload.

The caller (``api/conversation.py``) turns the returned
:class:`ConversationResumeOutcome` into an NDJSON stream or a JSON response.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.agent_runtime.checkpoint_transport import (
    CheckpointTransportClient,
    CheckpointTransportError,
    ResumeClaimRead,
    ResumeClaimContentionError,
    ResumeIndexRead,
)
from app.agent_runtime.durable_checkpointer import (
    CheckpointUnavailableError,
    DurableCheckpointSaver,
)
from app.core.config import get_settings
from app.services.agents.runtime_executor import (
    AgentRuntimeExecutor,
    ConversationTurnPause,
)

logger = logging.getLogger(__name__)

#: Stable-ish identity used as ``claimed_by_instance_id`` when the certificate
#: manager cannot expose an instance id (tests / development certificates).
_FALLBACK_INSTANCE_ID = f"ar-{uuid.uuid4().hex[:12]}"

#: Per-PROCESS token appended to the claim identity so that two Agent Runtime
#: processes sharing a service-level id (e.g. ``agent-runtime``) still have
#: distinct claims — otherwise both would consider themselves the holder and
#: self-renewal could cross-contaminate across instances.
_PROCESS_TOKEN = uuid.uuid4().hex[:8]


@dataclass
class ConversationResumeOutcome:
    """Result of one resume attempt.

    ``status`` vocabulary (also the legacy ``/internal/resume`` contract):
    ``resumed`` (the turn continued — a reply or a new pause follows),
    ``already_resolved`` (terminal success already recorded),
    ``unresumable`` (cannot continue — reason code set), ``not_awaiting``
    (there is no resume record at all).
    """

    status: str
    reason: str | None = None
    response: str = ""
    guardrail_usage: dict[str, Any] | None = None
    status_events: list[dict[str, str]] = field(default_factory=list)
    pause: ConversationTurnPause | None = None
    resume_id: str | None = None
    write_applied: bool = False

    @property
    def paused(self) -> bool:
        return self.pause is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "response": self.response,
            "guardrail_usage": self.guardrail_usage,
            "status_events": self.status_events,
            "pause": self.pause.as_dict() if self.pause is not None else None,
            "resume_id": self.resume_id,
            "write_applied": self.write_applied,
        }


class ConversationTurnResumeService:
    """Claim → load → rebuild → continue a paused conversational turn."""

    def __init__(
        self,
        *,
        transport: CheckpointTransportClient,
        data_client: Any,
        cert_path: str | None = None,
        key_path: str | None = None,
        instance_id: str | None = None,
        lease_seconds: int | None = None,
        renew_interval_seconds: float | None = None,
        executor_factory: Callable[..., AgentRuntimeExecutor] = AgentRuntimeExecutor,
    ) -> None:
        self._transport = transport
        self._data_client = data_client
        self._cert_path = cert_path
        self._key_path = key_path
        self._instance_id = f"{instance_id or _FALLBACK_INSTANCE_ID}-{_PROCESS_TOKEN}"
        self._lease_seconds = int(
            lease_seconds
            if lease_seconds is not None
            else getattr(get_settings(), "conversation_turn_claim_ttl_seconds", 45)
        )
        #: Claim renewal cadence (defaults to a third of the lease, min 5s).
        self._renew_interval_seconds = renew_interval_seconds
        self._executor_factory = executor_factory

    # ── Public API ───────────────────────────────────────────────────────────

    async def claim(self, conv_session_id: uuid.UUID) -> ResumeClaimRead:
        """Claim (or renew) the paused turn for this instance.

        Raises :class:`ResumeClaimContentionError` when another instance holds
        a live lease — callers map that to HTTP 409 *before* opening a stream.
        """
        claim = await self._transport.claim(
            conv_session_id,
            instance_id=self._instance_id,
            lease_seconds=self._lease_seconds,
        )
        if claim.status == "already_held":
            raise ResumeClaimContentionError(
                "Paused turn is being resumed by another Agent Runtime instance",
                holder_instance_id=claim.holder_instance_id,
                claim_expires_at=claim.claim_expires_at,
            )
        return claim

    def outcome_for_claim(
        self, claim: ResumeClaimRead
    ) -> ConversationResumeOutcome | None:
        """Return a terminal outcome when the claim cannot continue."""
        return self._terminal_outcome(claim)

    async def resume(
        self,
        conv_session_id: uuid.UUID,
        response_value: dict[str, Any] | None,
        *,
        status_event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None,
    ) -> ConversationResumeOutcome:
        """Claim, then continue a paused turn from its durable checkpoint."""
        claim = await self.claim(conv_session_id)
        done = self._terminal_outcome(claim)
        if done is not None:
            return done
        return await self.resume_claimed(
            conv_session_id,
            claim,
            response_value,
            status_event_callback=status_event_callback,
        )

    async def resume_claimed(
        self,
        conv_session_id: uuid.UUID,
        claim: ResumeClaimRead,
        response_value: dict[str, Any] | None,
        *,
        status_event_callback: Callable[[dict[str, str]], Awaitable[None]] | None = None,
    ) -> ConversationResumeOutcome:
        """Continue a paused turn whose claim this instance already holds."""
        record = claim.resume or await self._transport.get_resume_index(conv_session_id)
        if record is None:
            # The claim was acquired but the record disappeared (superseded in
            # between).  Nothing to continue — do not pretend ownership.
            await self._release(conv_session_id)
            return ConversationResumeOutcome(
                status="not_awaiting", reason="resume_record_missing"
            )

        try:
            checkpoint = await self._transport.load_checkpoint(conv_session_id)
        except CheckpointTransportError as exc:
            logger.error(
                "Resume %s: checkpoint load failed (%s)", conv_session_id, exc
            )
            await self._close_unresumable(conv_session_id, reason="checkpoint_unavailable")
            return ConversationResumeOutcome(
                status="unresumable",
                reason="checkpoint_unavailable",
                resume_id=str(record.resume_id),
            )

        if checkpoint is None or not checkpoint.payload:
            logger.warning(
                "Resume %s: no loadable checkpoint — marking unresumable",
                conv_session_id,
            )
            await self._close_unresumable(conv_session_id, reason="checkpoint_unavailable")
            return ConversationResumeOutcome(
                status="unresumable",
                reason="checkpoint_unavailable",
                resume_id=str(record.resume_id),
            )

        try:
            # Validate/decode the envelope BEFORE building the agent: a schema
            # mismatch or corrupt payload is a terminal failure, never a
            # half-restored graph.
            probe = DurableCheckpointSaver(
                self._transport,
                conv_session_id,
                payload=checkpoint.payload,
            )
        except CheckpointUnavailableError as exc:
            logger.error("Resume %s: checkpoint unusable (%s)", conv_session_id, exc)
            await self._close_unresumable(conv_session_id, reason="resume_failed")
            return ConversationResumeOutcome(
                status="unresumable",
                reason="resume_failed",
                resume_id=str(record.resume_id),
            )

        agent_type_id = probe.agent_type_id
        if agent_type_id is None:
            logger.error(
                "Resume %s: checkpoint carries no agent_type_id", conv_session_id
            )
            await self._close_unresumable(conv_session_id, reason="resume_failed")
            return ConversationResumeOutcome(
                status="unresumable",
                reason="resume_failed",
                resume_id=str(record.resume_id),
            )
        await probe.aclose()

        try:
            agent_context = await self._data_client.get_agent_context(
                agent_type_id, conv_session_id=conv_session_id
            )
            if not agent_context.get("is_active", False):
                raise ValueError("agent type is not active")
            if not agent_context.get("identity_role_valid", False):
                raise ValueError("agent identity is not assigned to role")
            model_config_id = agent_context.get("model_config_id")
            if not model_config_id:
                raise ValueError("agent model is not configured")
            model_config = await self._data_client.get_model_config(
                uuid.UUID(str(model_config_id))
            )
        except Exception as exc:  # noqa: BLE001 - any rebuild failure is terminal
            logger.error(
                "Resume %s: unable to rebuild agent context (%s)", conv_session_id, exc
            )
            await self._close_unresumable(conv_session_id, reason="resume_failed")
            return ConversationResumeOutcome(
                status="unresumable",
                reason="resume_failed",
                resume_id=str(record.resume_id),
            )

        return await self._continue_turn(
            conv_session_id=conv_session_id,
            record=record,
            agent_type_id=agent_type_id,
            agent_context=agent_context,
            model_config=model_config,
            checkpoint_payload=checkpoint.payload,
            response_value=response_value or {},
            status_event_callback=status_event_callback,
        )

    def _terminal_outcome(
        self, claim: ResumeClaimRead
    ) -> ConversationResumeOutcome | None:
        """Map a non-continuable claim result to a terminal outcome."""
        if claim.status == "not_found":
            return ConversationResumeOutcome(
                status="not_awaiting", reason="no_resume_record"
            )
        if claim.status == "terminal":
            record = claim.resume
            if record is not None and record.state == "resolved":
                return ConversationResumeOutcome(
                    status="already_resolved",
                    reason=record.resume_outcome,
                    resume_id=str(record.resume_id),
                    write_applied=record.write_applied,
                )
            return ConversationResumeOutcome(
                status="unresumable",
                reason=(
                    record.terminal_reason_code
                    if record is not None and record.terminal_reason_code
                    else (record.resume_outcome if record is not None else None)
                )
                or "resume_failed",
                resume_id=str(record.resume_id) if record is not None else None,
            )
        return None

    # ── Continuation ─────────────────────────────────────────────────────────

    async def _continue_turn(
        self,
        *,
        conv_session_id: uuid.UUID,
        record: ResumeIndexRead,
        agent_type_id: uuid.UUID,
        agent_context: dict[str, Any],
        model_config: dict[str, Any],
        checkpoint_payload: dict[str, Any],
        response_value: dict[str, Any],
        status_event_callback: Callable[[dict[str, str]], Awaitable[None]] | None,
    ) -> ConversationResumeOutcome:
        """Run the resumed turn under lease renewal, without double-applying."""
        executor = self._executor_factory(
            data_client=self._data_client, checkpoint_transport=self._transport
        )
        idempotency_key = record.idempotency_key
        turn_task: asyncio.Task | None = None
        contention = asyncio.Event()
        keeper = asyncio.create_task(
            self._keep_claim(
                conv_session_id,
                contention=contention,
                holder_task=lambda: turn_task,
            ),
            name=f"resume-claim-{conv_session_id}",
        )

        try:
            if status_event_callback is not None:
                await status_event_callback({"status": "thinking"})

            turn_task = asyncio.create_task(
                executor.resume_conversation_turn_from_context(
                    agent_type_id=agent_type_id,
                    agent_context=agent_context,
                    model_config=model_config,
                    conv_session_id=conv_session_id,
                    response_value=response_value,
                    checkpoint_payload=checkpoint_payload,
                    cert_path=self._cert_path,
                    key_path=self._key_path,
                    status_event_callback=status_event_callback,
                    turn_idempotency_key=idempotency_key,
                ),
                name=f"resume-turn-{conv_session_id}",
            )
            contention_task = asyncio.create_task(contention.wait())
            done, _pending = await asyncio.wait(
                {turn_task, contention_task}, return_when=asyncio.FIRST_COMPLETED
            )
            contention_task.cancel()
            if contention.is_set() and turn_task not in done:
                # Another instance took the turn over mid-run.  Abort without
                # writing a terminal outcome — the holder owns that decision,
                # and completing here could double-apply a confirmed write.
                logger.warning(
                    "Resume %s: claim lost mid-run — aborting without completing",
                    conv_session_id,
                )
                turn_task.cancel()
                try:
                    await turn_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                return ConversationResumeOutcome(
                    status="unresumable",
                    reason="resume_failed",
                    resume_id=str(record.resume_id),
                )

            try:
                response_text, guardrail_usage, status_events = await turn_task
            except CheckpointUnavailableError as exc:
                logger.error("Resume %s failed: %s", conv_session_id, exc)
                await self._close_unresumable(
                    conv_session_id, reason="resume_failed"
                )
                return ConversationResumeOutcome(
                    status="unresumable",
                    reason="resume_failed",
                    resume_id=str(record.resume_id),
                )
            except Exception:
                logger.exception("Resume %s raised during the resumed turn", conv_session_id)
                await self._close_unresumable(
                    conv_session_id, reason="resume_failed"
                )
                return ConversationResumeOutcome(
                    status="unresumable",
                    reason="resume_failed",
                    resume_id=str(record.resume_id),
                )

            pause = executor.pop_conversation_pause()
            if pause is not None:
                # The resumed turn paused again: the executor already persisted
                # the new checkpoint and resume index.  Release our (now
                # superseded) claim and report the new pause.
                await self._release(conv_session_id)
                return ConversationResumeOutcome(
                    status="resumed",
                    response="",
                    guardrail_usage=guardrail_usage,
                    status_events=status_events,
                    pause=pause,
                    resume_id=str(record.resume_id),
                )

            await self._release(conv_session_id)
            return ConversationResumeOutcome(
                status="resumed",
                response=response_text,
                guardrail_usage=guardrail_usage,
                status_events=status_events,
                resume_id=str(record.resume_id),
            )
        finally:
            keeper.cancel()
            try:
                await keeper
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _keep_claim(
        self,
        conv_session_id: uuid.UUID,
        *,
        contention: asyncio.Event,
        holder_task: Callable[[], asyncio.Task | None],
    ) -> None:
        """Renew the turn claim while the resumed turn runs.

        A renewal answered with ``already_held``/``terminal`` means another
        instance owns the turn now — signal contention so the caller aborts
        without completing (no double-apply).  Transport errors are ignored:
        the lease simply expires, and lease expiry never changes the lifecycle.
        """
        interval = (
            self._renew_interval_seconds
            if self._renew_interval_seconds is not None
            else max(5.0, self._lease_seconds / 3.0)
        )
        while True:
            await asyncio.sleep(interval)
            if holder_task() is None:
                return
            try:
                renewed = await self._transport.claim(
                    conv_session_id,
                    instance_id=self._instance_id,
                    lease_seconds=self._lease_seconds,
                )
            except CheckpointTransportError as exc:
                logger.warning(
                    "Resume %s: claim renewal failed (%s) — lease will expire",
                    conv_session_id,
                    exc,
                )
                continue
            if renewed.status != "acquired":
                logger.warning(
                    "Resume %s: claim lost (%s, holder=%s) — aborting",
                    conv_session_id,
                    renewed.status,
                    renewed.holder_instance_id,
                )
                contention.set()
                return

    # ── Best-effort cleanup ──────────────────────────────────────────────────

    async def _release(self, conv_session_id: uuid.UUID) -> None:
        try:
            await self._transport.release(
                conv_session_id, instance_id=self._instance_id
            )
        except CheckpointTransportError as exc:
            logger.info(
                "Resume %s: claim release failed (best effort): %s",
                conv_session_id,
                exc,
            )

    async def _close_unresumable(
        self, conv_session_id: uuid.UUID, *, reason: str
    ) -> None:
        """Record a terminal ``resume_failed`` outcome (best effort)."""
        try:
            await self._transport.complete_resume(
                conv_session_id,
                outcome="resume_failed",
                consume_checkpoint=False,
            )
        except CheckpointTransportError as exc:
            logger.warning(
                "Resume %s: could not record unresumable outcome (%s)",
                conv_session_id,
                exc,
            )


def build_transport_for_app(app_state: Any) -> CheckpointTransportClient:
    """Build the AR checkpoint courier from FastAPI application state."""
    cert_manager = getattr(app_state, "certificate_manager", None)
    transport = CheckpointTransportClient()
    cert_path = (
        str(cert_manager.cert_path)
        if cert_manager is not None and getattr(cert_manager, "cert_path", None)
        else None
    )
    key_path = (
        str(cert_manager.key_path)
        if cert_manager is not None and getattr(cert_manager, "key_path", None)
        else None
    )
    if cert_path and key_path:
        transport.set_certificate(cert_path, key_path)
    return transport


def build_resume_service(
    app_state: Any,
    data_client: Any,
    *,
    transport: CheckpointTransportClient | None = None,
    executor_factory: Callable[..., AgentRuntimeExecutor] = AgentRuntimeExecutor,
) -> ConversationTurnResumeService:
    """Build the resume service (single construction point for tests to patch)."""
    cert_manager = getattr(app_state, "certificate_manager", None)
    cert_path = (
        str(cert_manager.cert_path)
        if cert_manager is not None and getattr(cert_manager, "cert_path", None)
        else None
    )
    key_path = (
        str(cert_manager.key_path)
        if cert_manager is not None and getattr(cert_manager, "key_path", None)
        else None
    )
    instance_id = (
        getattr(cert_manager, "instance_id", None) if cert_manager is not None else None
    )
    return ConversationTurnResumeService(
        transport=transport or build_transport_for_app(app_state),
        data_client=data_client,
        cert_path=cert_path,
        key_path=key_path,
        instance_id=instance_id,
        executor_factory=executor_factory,
    )


__all__ = [
    "ConversationResumeOutcome",
    "ConversationTurnResumeService",
    "build_resume_service",
    "build_transport_for_app",
]
