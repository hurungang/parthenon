"""Durable LangGraph checkpointer for conversational turns.

A conversational turn executes inside LangGraph with ``thread_id =
conv_session_id``.  Historically that graph used an in-memory ``MemorySaver``
so a ``human_intervene`` pause lived in the Agent Runtime process — a restart
erased it and the operator's confirmation could never be applied.

This module replaces the in-memory saver with a checkpointer whose *authority*
is the Control Center–owned checkpoint payload, reached through
:class:`~app.agent_runtime.checkpoint_transport.CheckpointTransportClient`
(AR → CH → CC, mTLS).  Only the **latest** snapshot is kept:

* intermediate super-step writes coalesce into the latest checkpoint id —
  a paused turn only ever resumes from the pause point, so keeping a history
  would be pure payload bloat;
* :meth:`DurableCheckpointSaver.flush` persists that snapshot and blocks until
  Control Center acknowledged it.  The executor calls it at the pause point
  *before* reporting ``waiting_for_human``, so "shown as waiting" can never
  mean "checkpoint never made it out of this process".

Serialization uses LangGraph's own JSON+ serializer (``self.serde``) with a
tiny JSON envelope (typed bytes base64-encoded, plus ``schema_version``).
The payload carries conversation/agent-framework state only — never identity
tokens, credentials, or decrypted secrets.

A payload that cannot be decoded, or whose ``schema_version`` is not the one
this module writes, raises :class:`CheckpointUnavailableError`; the resume
handler maps that to a terminal ``resume_failed`` outcome rather than
continuing a half-restored graph.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)

from app.agent_runtime.checkpoint_transport import (
    CheckpointTransportClient,
    CheckpointTransportError,
)

logger = logging.getLogger(__name__)

#: Envelope version written by this module.  A resume may only rebuild a turn
#: from a payload it understands; anything else is a terminal failure.
CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_FORMAT = "langgraph-jsonplus-v1"

#: Envelope keys that must be present for a payload to be resumable.
_REQUIRED_KEYS = frozenset(
    {"schema_version", "format", "checkpoint", "metadata", "pending_writes"}
)


class CheckpointUnavailableError(Exception):
    """The durable checkpoint cannot be loaded or understood.

    Raised on a transport failure while loading, a missing payload, a corrupt
    envelope, or a schema-version mismatch.  Callers treat it as "this turn
    cannot be continued" (terminal ``resume_failed``) — never as a transient
    retry signal.
    """


def _encode_typed(typed: tuple[str, bytes]) -> dict[str, str]:
    kind, blob = typed
    return {"t": kind, "d": base64.b64encode(blob).decode("ascii")}


def _decode_typed(value: Any) -> tuple[str, bytes]:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("t"), str)
        or not isinstance(value.get("d"), str)
    ):
        raise CheckpointUnavailableError(
            "Checkpoint payload contains a malformed typed value"
        )
    try:
        return value["t"], base64.b64decode(value["d"].encode("ascii"))
    except Exception as exc:  # noqa: BLE001 - any decode failure is fatal here
        raise CheckpointUnavailableError(
            f"Checkpoint payload contains an undecodable typed value: {exc}"
        ) from exc


class DurableCheckpointSaver(BaseCheckpointSaver[str]):
    """LangGraph checkpointer backed by the Control Center checkpoint payload.

    Args:
        transport: AR → CH courier for checkpoint save/load.
        conv_session_id: Conversation session id — also the LangGraph
            ``thread_id``.
        agent_type_id: Owning agent type, stored in the payload so a *different*
            Agent Runtime instance can rebuild the agent context on resume
            (agent/model configuration are re-fetched, never stored).
        turn_idempotency_key: Opaque per-paused-turn key, stored so a resume can
            bind it to confirmed-write tool calls even before reading the index.
        payload: A previously persisted envelope to resume from.
        autosave: Persist on every checkpoint transition in the background.
            Default off — the executor flushes explicitly at the pause point.

    A saver created for a **new** turn starts empty and never loads older CC
    state for the same thread: each conversational turn passes the full
    conversation history as input, so restoring a previous turn's channels
    would duplicate it.  Only the resume path seeds a saver via ``payload``.
    """

    def __init__(
        self,
        transport: CheckpointTransportClient,
        conv_session_id: uuid.UUID,
        *,
        agent_type_id: uuid.UUID | None = None,
        turn_idempotency_key: str | None = None,
        payload: dict[str, Any] | None = None,
        autosave: bool = False,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._conv_session_id = conv_session_id
        self._thread_id = str(conv_session_id)
        self._agent_type_id = agent_type_id
        self._turn_idempotency_key = turn_idempotency_key
        self._autosave = autosave

        self._checkpoint: Checkpoint | None = None
        self._metadata: CheckpointMetadata = {}  # type: ignore[typeddict-item]
        self._checkpoint_id: str | None = None
        self._parent_checkpoint_id: str | None = None
        self._checkpoint_ns: str = ""
        #: (task_id, channel, value) keyed by (task_id, write_idx)
        self._writes: dict[tuple[str, int], tuple[str, str, Any]] = {}

        self._save_task: asyncio.Task[None] | None = None
        self._dirty = False
        self._last_save_error: CheckpointTransportError | None = None

        if payload is not None:
            self._load_envelope(payload)

    # ── Introspection / lifecycle ────────────────────────────────────────────

    @property
    def has_checkpoint(self) -> bool:
        """True when a checkpoint snapshot is held (fresh or resumed)."""
        return self._checkpoint is not None

    @property
    def checkpoint_id(self) -> str | None:
        return self._checkpoint_id

    @property
    def agent_type_id(self) -> uuid.UUID | None:
        """Agent type recorded in the envelope (used to rebuild the agent)."""
        return self._agent_type_id

    @property
    def turn_idempotency_key(self) -> str | None:
        return self._turn_idempotency_key

    def set_turn_idempotency_key(self, key: str | None) -> None:
        self._turn_idempotency_key = key

    def _thread_matches(self, config: RunnableConfig) -> bool:
        configurable = config.get("configurable") or {}
        return str(configurable.get("thread_id", "")) == self._thread_id

    # ── Envelope (de)serialization ───────────────────────────────────────────

    def _load_envelope(self, payload: dict[str, Any]) -> None:
        """Restore the latest checkpoint snapshot from a persisted envelope."""
        missing = _REQUIRED_KEYS - set(payload.keys())
        if missing:
            raise CheckpointUnavailableError(
                f"Checkpoint payload is missing required keys: {sorted(missing)}"
            )
        if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointUnavailableError(
                "Checkpoint schema version mismatch: "
                f"payload has {payload.get('schema_version')!r}, "
                f"this runtime writes {CHECKPOINT_SCHEMA_VERSION}"
            )
        if payload.get("format") != CHECKPOINT_FORMAT:
            raise CheckpointUnavailableError(
                f"Unsupported checkpoint format {payload.get('format')!r}"
            )
        thread_id = payload.get("thread_id")
        if thread_id is not None and str(thread_id) != self._thread_id:
            raise CheckpointUnavailableError(
                f"Checkpoint belongs to thread {thread_id!r}, "
                f"not {self._thread_id!r}"
            )

        try:
            checkpoint = self.serde.loads_typed(_decode_typed(payload["checkpoint"]))
            metadata = self.serde.loads_typed(_decode_typed(payload["metadata"]))
        except CheckpointUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - any serde failure is fatal
            raise CheckpointUnavailableError(
                f"Checkpoint payload could not be deserialized: {exc}"
            ) from exc

        if not isinstance(checkpoint, dict) or "id" not in checkpoint:
            raise CheckpointUnavailableError(
                "Checkpoint payload does not contain a LangGraph checkpoint"
            )

        writes: dict[tuple[str, int], tuple[str, str, Any]] = {}
        raw_writes = payload.get("pending_writes") or []
        if not isinstance(raw_writes, list):
            raise CheckpointUnavailableError(
                "Checkpoint payload pending_writes is not a list"
            )
        for item in raw_writes:
            if not isinstance(item, dict):
                raise CheckpointUnavailableError(
                    "Checkpoint payload contains a malformed pending write"
                )
            task_id = item.get("task_id")
            channel = item.get("channel")
            idx = item.get("idx")
            if not isinstance(task_id, str) or not isinstance(channel, str) or not isinstance(idx, int):
                raise CheckpointUnavailableError(
                    "Checkpoint payload contains an incomplete pending write"
                )
            try:
                value = self.serde.loads_typed(_decode_typed(item.get("value")))
            except CheckpointUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise CheckpointUnavailableError(
                    f"Checkpoint pending write could not be deserialized: {exc}"
                ) from exc
            writes[(task_id, idx)] = (task_id, channel, value)

        self._checkpoint = checkpoint  # type: ignore[assignment]
        self._metadata = metadata  # type: ignore[assignment]
        self._checkpoint_id = str(checkpoint["id"])
        self._parent_checkpoint_id = payload.get("parent_checkpoint_id")
        self._checkpoint_ns = str(payload.get("checkpoint_ns") or "")
        self._writes = writes
        if payload.get("agent_type_id"):
            try:
                self._agent_type_id = uuid.UUID(str(payload["agent_type_id"]))
            except ValueError:
                self._agent_type_id = None
        if payload.get("turn_idempotency_key"):
            self._turn_idempotency_key = str(payload["turn_idempotency_key"])

    def build_payload(self) -> dict[str, Any] | None:
        """Serialize the current snapshot into the JSON envelope (``None`` if empty)."""
        if self._checkpoint is None or self._checkpoint_id is None:
            return None
        checkpoint = self.serde.dumps_typed(self._checkpoint)
        metadata = self.serde.dumps_typed(self._metadata)
        pending_writes = [
            {
                "task_id": task_id,
                "channel": channel,
                "idx": idx,
                "value": _encode_typed(self.serde.dumps_typed(value)),
            }
            for (task_id, idx), (_, channel, value) in sorted(
                self._writes.items(), key=lambda kv: (kv[0][0], kv[0][1])
            )
        ]
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "format": CHECKPOINT_FORMAT,
            "agent_type_id": str(self._agent_type_id) if self._agent_type_id else None,
            "turn_idempotency_key": self._turn_idempotency_key,
            "thread_id": self._thread_id,
            "checkpoint_ns": self._checkpoint_ns,
            "checkpoint_id": self._checkpoint_id,
            "parent_checkpoint_id": self._parent_checkpoint_id,
            "checkpoint": _encode_typed(checkpoint),
            "metadata": _encode_typed(metadata),
            "pending_writes": pending_writes,
        }

    # ── Persistence ──────────────────────────────────────────────────────────

    async def flush(self, *, expires_at: datetime | None = None) -> None:
        """Persist the latest snapshot and wait until Control Center has it.

        Blocks on any outstanding background autosave first, then performs the
        authoritative write so a returned ``flush()`` means "durable".  Raises
        :class:`CheckpointTransportError` when the write is refused.
        """
        task = self._save_task
        if task is not None and not task.done():
            try:
                await task
            except CheckpointTransportError:
                # Superseded by the authoritative write below; its failure is
                # not fatal if the explicit write succeeds.
                pass

        payload = self.build_payload()
        if payload is None:
            raise CheckpointUnavailableError(
                "No checkpoint was captured for this turn — nothing to persist"
            )
        await self._transport.save_checkpoint(
            self._conv_session_id,
            payload,
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            expires_at=expires_at,
        )
        self._last_save_error = None
        logger.info(
            "Durable checkpoint flushed for conversation %s (checkpoint=%s, %d pending write(s))",
            self._conv_session_id,
            self._checkpoint_id,
            len(self._writes),
        )

    def _schedule_autosave(self) -> None:
        if not self._autosave:
            return
        self._dirty = True
        if self._save_task is None or self._save_task.done():
            self._save_task = asyncio.create_task(self._autosave_loop())

    async def _autosave_loop(self) -> None:
        while self._dirty:
            self._dirty = False
            payload = self.build_payload()
            if payload is None:
                continue
            try:
                await self._transport.save_checkpoint(
                    self._conv_session_id,
                    payload,
                    schema_version=CHECKPOINT_SCHEMA_VERSION,
                )
                self._last_save_error = None
            except CheckpointTransportError as exc:
                # Recorded for diagnostics only — ``flush()`` is authoritative
                # and will retry (or raise) at the pause point.
                self._last_save_error = exc
                logger.warning(
                    "Background checkpoint autosave failed for conversation %s: %s",
                    self._conv_session_id,
                    exc,
                )

    async def aclose(self) -> None:
        """Cancel any outstanding autosave task (never raises)."""
        task = self._save_task
        self._save_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ── BaseCheckpointSaver contract (async variant) ─────────────────────────

    def _to_tuple(self, checkpoint_id: str) -> CheckpointTuple:
        assert self._checkpoint is not None  # guarded by callers
        config: RunnableConfig = {
            "configurable": {
                "thread_id": self._thread_id,
                "checkpoint_ns": self._checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }
        parent_config: RunnableConfig | None = (
            {
                "configurable": {
                    "thread_id": self._thread_id,
                    "checkpoint_ns": self._checkpoint_ns,
                    "checkpoint_id": self._parent_checkpoint_id,
                }
            }
            if self._parent_checkpoint_id
            else None
        )
        return CheckpointTuple(
            config=config,
            checkpoint=self._checkpoint,
            metadata=self._metadata,
            parent_config=parent_config,
            pending_writes=[
                (task_id, channel, value)
                for (task_id, _idx), (_task_id, channel, value) in sorted(
                    self._writes.items(), key=lambda kv: (kv[0][0], kv[0][1])
                )
            ],
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Return the latest (or requested) checkpoint tuple for this thread."""
        if not self._thread_matches(config) or self._checkpoint is None:
            return None
        requested_id = get_checkpoint_id(config)
        if requested_id and requested_id != self._checkpoint_id:
            # Only the latest checkpoint is authoritative by design.
            return None
        return self._to_tuple(str(self._checkpoint_id))

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store the newest checkpoint, coalescing away older super-steps."""
        if not self._thread_matches(config):
            raise CheckpointUnavailableError(
                "Checkpoint saver is bound to conversation "
                f"{self._thread_id!r}, refusing thread "
                f"{(config.get('configurable') or {}).get('thread_id')!r}"
            )
        configurable = config.get("configurable") or {}
        parent_id = configurable.get("checkpoint_id")
        self._checkpoint = dict(checkpoint)  # type: ignore[assignment]
        self._metadata = dict(metadata)  # type: ignore[assignment]
        self._checkpoint_id = str(checkpoint["id"])
        self._parent_checkpoint_id = str(parent_id) if parent_id else None
        self._checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
        # Writes belong to the checkpoint that produced them; once a newer
        # checkpoint exists they are no longer authoritative for a resume.
        self._writes = {}
        self._schedule_autosave()
        return {
            "configurable": {
                "thread_id": self._thread_id,
                "checkpoint_ns": self._checkpoint_ns,
                "checkpoint_id": self._checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store the writes for the current checkpoint (idempotent by index)."""
        if not self._thread_matches(config):
            return
        configurable = config.get("configurable") or {}
        checkpoint_id = configurable.get("checkpoint_id")
        if self._checkpoint_id is None:
            return
        if checkpoint_id is not None and str(checkpoint_id) != self._checkpoint_id:
            # Writes for a superseded super-step are already coalesced away.
            return
        for idx, (channel, value) in enumerate(writes):
            key = (task_id, WRITES_IDX_MAP.get(channel, idx))
            if key[1] >= 0 and key in self._writes:
                continue
            self._writes[key] = (task_id, channel, value)
        self._schedule_autosave()

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - LangGraph contract
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Yield the single authoritative (latest) checkpoint, if it matches."""
        if self._checkpoint is None or self._checkpoint_id is None:
            return
        if config is not None:
            if not self._thread_matches(config):
                return
            checkpoint_ns = (config.get("configurable") or {}).get("checkpoint_ns")
            if checkpoint_ns is not None and str(checkpoint_ns) != self._checkpoint_ns:
                return
            requested_id = get_checkpoint_id(config)
            if requested_id and requested_id != self._checkpoint_id:
                return
        if before is not None:
            before_id = get_checkpoint_id(before)
            if before_id and self._checkpoint_id >= before_id:
                return
        if filter and not all(
            self._metadata.get(key) == value for key, value in filter.items()
        ):
            return
        if limit is not None and limit <= 0:
            return
        yield self._to_tuple(self._checkpoint_id)

    async def adelete_thread(self, thread_id: str) -> None:
        """Drop the local snapshot.

        Control Center owns the persisted payload and consumes/purges it on
        resolution; AR has no delete route and must not invent one.
        """
        if str(thread_id) != self._thread_id:
            return
        await self.aclose()
        self._checkpoint = None
        self._metadata = {}  # type: ignore[typeddict-item]
        self._checkpoint_id = None
        self._parent_checkpoint_id = None
        self._writes = {}


__all__ = [
    "CHECKPOINT_FORMAT",
    "CHECKPOINT_SCHEMA_VERSION",
    "CheckpointUnavailableError",
    "DurableCheckpointSaver",
]
