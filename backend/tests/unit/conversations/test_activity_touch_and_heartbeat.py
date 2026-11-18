"""Activity heartbeat touch + stale-bound semantics (FIX-20261113).

A live conversational turn keeps its persisted activity fresh through the
Communication Hub heartbeat (``POST .../activity/touch`` every ~15s) so the
reaper's staleness bound can mean "the heartbeat stopped → the turn is dead"
instead of "the model is quiet → assume it failed".

Covered here:

- the staleness default is short (180s) and stays operator-configurable;
- ``ConversationActivityStore.touch`` refreshes *only* ``last_updated_at`` on a
  live working row, and is a no-op for terminal / ``waiting_for_human`` rows;
- a touched (live) working row survives a reaper sweep, a dead one resolves;
- the CH heartbeat loop issues one touch per beat and stops with the turn;
- ``ControlCenterDataClient.touch_conversation_activity`` uses the standard
  internal egress path (POST, no body) and never raises.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.conversations.activity_reaper as reaper_module
from app.communication_hub.data_client import (
    ControlCenterDataClient,
    ControlCenterDataError,
)
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.activity_reaper import (
    DEFAULT_STALE_SECONDS,
    ConversationActivityReaper,
    get_stale_threshold_seconds,
)
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)


async def _make_session(
    db: AsyncSession, status: ConversationStatus = ConversationStatus.active
) -> ConversationSession:
    session = ConversationSession(status=status)
    db.add(session)
    await db.flush()
    return session


async def _make_activity(
    db: AsyncSession,
    conv: ConversationSession,
    state: ActivityState,
    *,
    last_updated: datetime = NOW,
) -> None:
    activity = await ConversationActivityStore().upsert(conv.id, db, state=state)
    activity.last_updated_at = last_updated
    await db.flush()


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TestStaleThresholdDefault:
    def test_default_is_short(self, monkeypatch):
        monkeypatch.delenv("CONVERSATION_ACTIVITY_STALE_SECONDS", raising=False)
        assert DEFAULT_STALE_SECONDS == 180
        assert get_stale_threshold_seconds() == DEFAULT_STALE_SECONDS

    def test_stays_configurable(self, monkeypatch):
        monkeypatch.setenv("CONVERSATION_ACTIVITY_STALE_SECONDS", "600")
        assert get_stale_threshold_seconds() == 600

    def test_invalid_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("CONVERSATION_ACTIVITY_STALE_SECONDS", "soon")
        assert get_stale_threshold_seconds() == DEFAULT_STALE_SECONDS


class TestActivityTouch:
    @pytest.mark.asyncio
    async def test_touch_refreshes_a_working_row_without_state_change(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        await _make_activity(
            db_session, conv, ActivityState.using_tool, last_updated=stale
        )

        touched = await ConversationActivityStore().touch(conv.id, db_session)

        assert touched is not None
        assert touched.state is ActivityState.using_tool
        assert touched.is_terminal is False
        assert _aware(touched.last_updated_at) > stale

    @pytest.mark.asyncio
    async def test_touch_is_a_noop_for_a_terminal_row(self, db_session: AsyncSession):
        conv = await _make_session(db_session)
        finished_at = NOW - timedelta(minutes=30)
        await _make_activity(
            db_session, conv, ActivityState.finished, last_updated=finished_at
        )

        touched = await ConversationActivityStore().touch(conv.id, db_session)

        assert touched is not None
        assert touched.state is ActivityState.finished
        assert touched.is_terminal is True
        assert _aware(touched.last_updated_at) == finished_at

    @pytest.mark.asyncio
    async def test_touch_never_refreshes_a_paused_row(self, db_session: AsyncSession):
        """A paused turn stops emitting beats: refreshing it would defeat the
        answered-but-lost-resume staleness detection."""
        conv = await _make_session(db_session)
        resume = await ConversationTurnResumeStore().create_or_reuse(conv.id, db_session)
        await ConversationActivityStore().upsert(
            conv.id,
            db_session,
            state=ActivityState.waiting_for_human,
            active_resume_id=resume.id,
        )
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        paused_beat = NOW - timedelta(minutes=30)
        activity.last_updated_at = paused_beat
        await db_session.flush()

        touched = await ConversationActivityStore().touch(conv.id, db_session)

        assert touched is not None
        assert touched.state is ActivityState.waiting_for_human
        assert _aware(touched.last_updated_at) == paused_beat

    @pytest.mark.asyncio
    async def test_touch_returns_none_for_an_idle_session(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        assert await ConversationActivityStore().touch(conv.id, db_session) is None


class TestReaperUsesTheTouchedHeartbeat:
    """A live (touched) working row survives; a dead one resolves."""

    @pytest.fixture(autouse=True)
    def _short_stale_bound(self, monkeypatch):
        # Explicit bound so the test is independent of the env default.
        monkeypatch.setattr(reaper_module, "get_stale_threshold_seconds", lambda: 180)

    @pytest.fixture
    def reaper(self) -> ConversationActivityReaper:
        return ConversationActivityReaper()

    @pytest.mark.asyncio
    async def test_recently_touched_using_tool_is_protected(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.using_tool,
            last_updated=NOW - timedelta(seconds=15),
        )

        # The shared test DB may hold rows from other committed tests, so the
        # assertion is about THIS row surviving the sweep.
        await reaper.reap(db_session, now=NOW)
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.using_tool

    @pytest.mark.asyncio
    async def test_dead_using_tool_heartbeat_resolves_to_terminal(
        self, db_session: AsyncSession, reaper
    ):
        """The production defect: a turn emitted ``using_tool`` then stopped,
        leaving a forever-spinning bubble. With the short bound the dead row
        resolves within a few minutes — as ``failed`` with the dedicated
        ``unexpectedly_terminated`` reason (the turn died mid-flight)."""
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.using_tool,
            last_updated=NOW - timedelta(seconds=181),
        )

        await reaper.reap(db_session, now=NOW)
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.failed
        assert activity.is_terminal is True
        assert (
            activity.detail["terminal_reason_code"] == "unexpectedly_terminated"
        )

    @pytest.mark.asyncio
    async def test_dead_thinking_heartbeat_resolves_to_terminal(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.thinking,
            last_updated=NOW - timedelta(minutes=10),
        )

        await reaper.reap(db_session, now=NOW)
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.failed

    @pytest.mark.asyncio
    async def test_dead_delegating_heartbeat_resolves_to_terminal(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.delegating,
            last_updated=NOW - timedelta(minutes=10),
        )

        await reaper.reap(db_session, now=NOW)
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.failed


class _FakeDataClient:
    def __init__(self) -> None:
        self.touched: list[uuid.UUID] = []

    async def touch_conversation_activity(self, conv_session_id):
        self.touched.append(conv_session_id)
        return {"state": "using_tool"}


class TestHeartbeatLoopTouch:
    @pytest.mark.asyncio
    async def test_each_beat_touches_the_activity(self, monkeypatch):
        import app.api.ws.chat as chat_module
        from app.api.ws.chat import _thinking_heartbeat_loop

        monkeypatch.setattr(
            chat_module, "CONVERSATION_HEARTBEAT_INTERVAL_SECONDS", 0.01
        )
        # The socket delivery helper is unrelated to this fix; keep it inert.
        async def _noop_send(*_args, **_kwargs):
            return None

        monkeypatch.setattr(chat_module, "_send_to_live_socket", _noop_send)

        data_client = _FakeDataClient()
        app = SimpleNamespace(state=SimpleNamespace(data_client=data_client))
        conv_session_id = uuid.uuid4()
        stop = asyncio.Event()

        task = asyncio.create_task(
            _thinking_heartbeat_loop(
                "session-1",
                None,
                stop,
                app=app,
                conv_session_id=conv_session_id,
            )
        )
        try:
            for _ in range(200):
                if data_client.touched:
                    break
                await asyncio.sleep(0.01)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=5)

        assert data_client.touched
        assert set(data_client.touched) == {conv_session_id}

    @pytest.mark.asyncio
    async def test_no_app_or_session_is_tolerated(self, monkeypatch):
        import app.api.ws.chat as chat_module
        from app.api.ws.chat import _thinking_heartbeat_loop

        monkeypatch.setattr(
            chat_module, "CONVERSATION_HEARTBEAT_INTERVAL_SECONDS", 0.01
        )

        async def _noop_send(*_args, **_kwargs):
            return None

        monkeypatch.setattr(chat_module, "_send_to_live_socket", _noop_send)

        stop = asyncio.Event()
        task = asyncio.create_task(
            _thinking_heartbeat_loop("session-1", None, stop)
        )
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=5)


class TestChDataClientTouch:
    @pytest.mark.asyncio
    async def test_touch_posts_to_the_touch_route_with_no_body(self):
        client = ControlCenterDataClient(
            cert_manager=None, control_center_url="https://cc.test"
        )
        captured = {}

        async def fake_post(path, body, user_jwt=None):
            captured["path"] = path
            captured["body"] = body
            return {"state": "using_tool"}

        client._post = fake_post  # type: ignore[assignment]
        conv_id = uuid.uuid4()

        result = await client.touch_conversation_activity(conv_id)

        assert result == {"state": "using_tool"}
        assert captured["path"] == f"/internal/data/conversations/{conv_id}/activity/touch"
        assert captured["body"] == {}

    @pytest.mark.asyncio
    async def test_touch_never_raises_on_transport_failure(self):
        client = ControlCenterDataClient(
            cert_manager=None, control_center_url="https://cc.test"
        )

        async def failing_post(path, body, user_jwt=None):
            raise ControlCenterDataError(f"CC POST {path} failed: boom")

        client._post = failing_post  # type: ignore[assignment]
        assert await client.touch_conversation_activity(uuid.uuid4()) is None
