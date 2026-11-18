"""Conversation Turn Checkpoint Store — opaque paused-turn payload persistence.

The checkpoint is the agent-framework state that lets a *different* Agent
Runtime instance rebuild a paused conversational turn.  Control Center owns the
row; this store is the only writer.

Deliberate non-responsibilities:

* the payload is **never inspected** — it is framework-owned serialization with
  no business semantics here (and must never contain tokens/credentials);
* exactly one row per resume record — a re-pause replaces the payload in place;
* a payload is consumed once (after a successful resume rebuilt the turn) and
  is purgeable after its retention horizon.  The resume index row always
  survives, so audit and outcome remain intact.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.conversation_turn_resume import (
    CheckpointPayloadKind,
    ConversationTurnCheckpoint,
)

logger = logging.getLogger(__name__)


class CheckpointStoreError(Exception):
    """Base class for checkpoint store failures."""


class CheckpointTooLargeError(CheckpointStoreError, ValueError):
    """The serialized payload exceeds the configured byte cap."""


class CheckpointPayloadError(CheckpointStoreError, ValueError):
    """The caller supplied a payload that is not JSON-serializable."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_tz(value: datetime | None) -> datetime | None:
    """Normalize a naive DB timestamp to UTC-aware for comparisons."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def payload_size_bytes(payload: Any) -> int:
    """Return the canonical serialized size used for the byte cap."""
    try:
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise CheckpointPayloadError(
            f"Checkpoint payload is not JSON-serializable: {exc}"
        ) from exc
    return len(serialized.encode("utf-8"))


class ConversationTurnCheckpointStore:
    """Upsert / load / consume / purge the opaque checkpoint payload."""

    async def get(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnCheckpoint | None:
        """Return the checkpoint row for a resume record (including consumed)."""
        result = await db.execute(
            select(ConversationTurnCheckpoint).where(
                ConversationTurnCheckpoint.resume_id == resume_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert_payload(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        *,
        payload: dict[str, Any],
        payload_kind: CheckpointPayloadKind = CheckpointPayloadKind.agent_turn_state,
        schema_version: int = 1,
        expires_at: datetime | None = None,
    ) -> ConversationTurnCheckpoint:
        """Create or replace the payload for a resume record (one row per resume).

        A re-pause replaces the payload in place and clears ``is_consumed`` —
        the new payload has not been consumed by any resume attempt.
        """
        size = payload_size_bytes(payload)
        max_bytes = get_settings().conversation_turn_checkpoint_max_bytes
        if size > max_bytes:
            raise CheckpointTooLargeError(
                f"Checkpoint payload is {size} bytes, exceeding the "
                f"{max_bytes}-byte cap"
            )

        record = await self.get(resume_id, db)
        if record is None:
            record = ConversationTurnCheckpoint(
                resume_id=resume_id,
                payload_kind=payload_kind,
                schema_version=schema_version,
                payload=payload,
                payload_bytes=size,
                is_consumed=False,
                expires_at=expires_at,
            )
            db.add(record)
        else:
            record.payload_kind = payload_kind
            record.schema_version = schema_version
            record.payload = payload
            record.payload_bytes = size
            record.is_consumed = False
            record.expires_at = expires_at

        await db.flush()
        logger.info(
            "Checkpoint for resume %s persisted (%s bytes, schema v%s)",
            resume_id,
            size,
            schema_version,
        )
        return record

    async def load_payload(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnCheckpoint | None:
        """Return a loadable checkpoint (``None`` when absent/consumed/expired)."""
        record = await self.get(resume_id, db)
        if record is None or record.is_consumed:
            return None
        expires_at = _ensure_tz(record.expires_at)
        if expires_at is not None and expires_at < _utcnow():
            return None
        return record

    async def mark_consumed(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
    ) -> bool:
        """Mark the payload consumed (idempotent). Returns ``True`` if changed."""
        record = await self.get(resume_id, db)
        if record is None or record.is_consumed:
            return False
        record.is_consumed = True
        await db.flush()
        return True

    async def purge_expired(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
    ) -> int:
        """Delete payloads past their retention horizon. Returns rows removed."""
        current = now or _utcnow()
        result = await db.execute(
            delete(ConversationTurnCheckpoint)
            .where(
                or_(
                    ConversationTurnCheckpoint.is_consumed.is_(True),
                    and_(
                        ConversationTurnCheckpoint.expires_at.is_not(None),
                        ConversationTurnCheckpoint.expires_at < current,
                    ),
                )
            )
            .execution_options(synchronize_session=False)
        )
        removed = result.rowcount or 0
        if removed:
            logger.info("Purged %d consumed/expired checkpoint payload(s)", removed)
        return removed

    async def purge(
        self,
        db: AsyncSession,
        *,
        now: datetime | None = None,
        terminal_grace_seconds: int | None = None,
    ) -> int:
        """Delete payloads that can never be loaded again.

        A payload is purgeable when

        * it was consumed by a resume that rebuilt the turn,
        * it is past its own ``expires_at`` horizon, or
        * its resume record is terminal and the retention grace (default
          ``conversation_turn_checkpoint_purge_after_seconds``) elapsed since
          resolution.

        Only the payload row is deleted: the resume index row survives, so the
        audit trail, the applied marker, and the stored outcome remain intact.
        Returns the number of rows removed.
        """
        from app.db.models.conversation_turn_resume import ConversationTurnResume

        current = now or _utcnow()
        grace_seconds = (
            terminal_grace_seconds
            if terminal_grace_seconds is not None
            else get_settings().conversation_turn_checkpoint_purge_after_seconds
        )
        grace_cutoff = current - timedelta(seconds=max(0, grace_seconds))

        terminal_resume_ids = (
            select(ConversationTurnResume.id)
            .where(
                ConversationTurnResume.is_terminal.is_(True),
                or_(
                    ConversationTurnResume.resolved_at.is_(None),
                    ConversationTurnResume.resolved_at < grace_cutoff,
                ),
            )
            .scalar_subquery()
        )
        result = await db.execute(
            delete(ConversationTurnCheckpoint)
            .where(
                or_(
                    ConversationTurnCheckpoint.is_consumed.is_(True),
                    and_(
                        ConversationTurnCheckpoint.expires_at.is_not(None),
                        ConversationTurnCheckpoint.expires_at < current,
                    ),
                    ConversationTurnCheckpoint.resume_id.in_(terminal_resume_ids),
                )
            )
            .execution_options(synchronize_session=False)
        )
        removed = result.rowcount or 0
        if removed:
            logger.info(
                "Purged %d checkpoint payload(s) (consumed / expired / terminal)",
                removed,
            )
        return removed
