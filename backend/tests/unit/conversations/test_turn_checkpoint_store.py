"""Unit tests — ConversationTurnCheckpointStore payload upsert/load/consume/purge.

Covers resumable-agent-turn-persistence (Phase 2.2): the payload is opaque,
size-capped, one row per resume (replace in place), consumable once, and
purgeable after its retention horizon.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.conversations.turn_checkpoint_store as checkpoint_module
from app.db.models.conversation_turn_resume import (
    CheckpointPayloadKind,
    ConversationTurnCheckpoint,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.turn_checkpoint_store import (
    CheckpointPayloadError,
    CheckpointTooLargeError,
    ConversationTurnCheckpointStore,
)
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore


@pytest.fixture
def store() -> ConversationTurnCheckpointStore:
    return ConversationTurnCheckpointStore()


async def _make_resume(db: AsyncSession):
    conv = ConversationSession(status=ConversationStatus.active)
    db.add(conv)
    await db.flush()
    return await ConversationTurnResumeStore().create_or_reuse(conv.id, db)


async def _checkpoint_rows(
    db: AsyncSession, resume_id=None
) -> list[ConversationTurnCheckpoint]:
    stmt = select(ConversationTurnCheckpoint)
    if resume_id is not None:
        stmt = stmt.where(ConversationTurnCheckpoint.resume_id == resume_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


class TestUpsert:
    @pytest.mark.asyncio
    async def test_upsert_stamps_byte_size_and_metadata(
        self, db_session: AsyncSession, store
    ):
        resume = await _make_resume(db_session)
        payload = {"messages": [{"role": "assistant", "content": "hello"}], "n": 1}

        checkpoint = await store.upsert_payload(
            resume.id,
            db_session,
            payload=payload,
            payload_kind=CheckpointPayloadKind.agent_turn_state,
            schema_version=3,
        )

        assert checkpoint.resume_id == resume.id
        assert checkpoint.schema_version == 3
        assert checkpoint.is_consumed is False
        assert checkpoint.payload_bytes > 0
        assert checkpoint.payload == payload

    @pytest.mark.asyncio
    async def test_oversized_payload_rejected(self, db_session: AsyncSession, store, monkeypatch):
        monkeypatch.setattr(
            checkpoint_module,
            "get_settings",
            lambda: SimpleNamespace(conversation_turn_checkpoint_max_bytes=16),
        )
        resume = await _make_resume(db_session)

        with pytest.raises(CheckpointTooLargeError):
            await store.upsert_payload(
                resume.id, db_session, payload={"blob": "x" * 64}
            )

    @pytest.mark.asyncio
    async def test_non_json_payload_rejected(self, db_session: AsyncSession, store):
        resume = await _make_resume(db_session)
        with pytest.raises(CheckpointPayloadError):
            await store.upsert_payload(
                resume.id, db_session, payload={"bad": object()}
            )

    @pytest.mark.asyncio
    async def test_second_upsert_replaces_payload_in_place(
        self, db_session: AsyncSession, store
    ):
        resume = await _make_resume(db_session)
        await store.upsert_payload(resume.id, db_session, payload={"v": 1})
        second = await store.upsert_payload(
            resume.id, db_session, payload={"v": 2, "more": True}
        )

        rows = await _checkpoint_rows(db_session, resume.id)
        assert len(rows) == 1
        assert rows[0].id == second.id
        assert rows[0].payload == {"v": 2, "more": True}

    @pytest.mark.asyncio
    async def test_upsert_after_consume_resets_consumed_flag(
        self, db_session: AsyncSession, store
    ):
        resume = await _make_resume(db_session)
        await store.upsert_payload(resume.id, db_session, payload={"v": 1})
        await store.mark_consumed(resume.id, db_session)
        re_paused = await store.upsert_payload(
            resume.id, db_session, payload={"v": 2}
        )
        assert re_paused.is_consumed is False


class TestLoadAndConsume:
    @pytest.mark.asyncio
    async def test_load_round_trips_payload_unchanged(
        self, db_session: AsyncSession, store
    ):
        resume = await _make_resume(db_session)
        payload = {"state": {"nested": [1, 2, 3]}, "unicode": "héllo"}
        await store.upsert_payload(resume.id, db_session, payload=payload)

        loaded = await store.load_payload(resume.id, db_session)
        assert loaded is not None
        assert loaded.payload == payload

    @pytest.mark.asyncio
    async def test_load_returns_none_when_missing_consumed_or_expired(
        self, db_session: AsyncSession, store
    ):
        resume = await _make_resume(db_session)
        assert await store.load_payload(resume.id, db_session) is None

        await store.upsert_payload(resume.id, db_session, payload={"v": 1})
        await store.mark_consumed(resume.id, db_session)
        assert await store.load_payload(resume.id, db_session) is None

        other = await _make_resume(db_session)
        await store.upsert_payload(
            other.id,
            db_session,
            payload={"v": 2},
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert await store.load_payload(other.id, db_session) is None

    @pytest.mark.asyncio
    async def test_mark_consumed_is_idempotent(self, db_session: AsyncSession, store):
        resume = await _make_resume(db_session)
        await store.upsert_payload(resume.id, db_session, payload={"v": 1})

        assert await store.mark_consumed(resume.id, db_session) is True
        assert await store.mark_consumed(resume.id, db_session) is False


class TestPurge:
    @pytest.mark.asyncio
    async def test_purge_removes_expired_and_consumed_keeps_live(
        self, db_session: AsyncSession, store
    ):
        now = datetime.now(timezone.utc)
        expired = await _make_resume(db_session)
        consumed = await _make_resume(db_session)
        live = await _make_resume(db_session)

        await store.upsert_payload(
            expired.id,
            db_session,
            payload={"v": "expired"},
            expires_at=now - timedelta(minutes=1),
        )
        await store.upsert_payload(consumed.id, db_session, payload={"v": "consumed"})
        await store.mark_consumed(consumed.id, db_session)
        await store.upsert_payload(
            live.id,
            db_session,
            payload={"v": "live"},
            expires_at=now + timedelta(hours=1),
        )

        removed = await store.purge_expired(db_session, now=now)

        assert removed >= 2
        assert (await store.get(expired.id, db_session)) is None
        assert (await store.get(consumed.id, db_session)) is None
        assert (await store.get(live.id, db_session)) is not None
