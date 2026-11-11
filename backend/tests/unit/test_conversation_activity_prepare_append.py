"""prepare-turn / append-turn activity wiring (persistent-agent-activity-state).

- ``prepare-turn`` sets the session activity to ``thinking`` (with the new user
  turn as ``current_turn_id``) so a reconnecting client hydrates a working state.
- ``append-turn`` resolves the activity to a terminal state derived from the
  final status event: normal reply -> ``finished``, watchdog/provider timeout ->
  ``timed_out``, guardrail stop -> ``failed``.
"""
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import TenantContext
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.session import get_db
from app.services.conversations.activity_store import ConversationActivityStore

PREPARE_URL = "/api/v1/internal/data/conversations/{sid}/prepare-turn"
APPEND_URL = "/api/v1/internal/data/conversations/{sid}/append-turn"


def _tenant_ctx() -> TenantContext:
    return TenantContext(tenant_id=uuid.uuid4(), slug="test-tenant", name="test-tenant")


def _build_app(db: AsyncSession) -> FastAPI:
    from app.api.deps import require_internal_tenant_context, require_service_certificate
    from app.api.v1.internal.session_data import InternalSessionDataRouter

    app = FastAPI()
    app.include_router(InternalSessionDataRouter, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_service_certificate] = lambda: None
    app.dependency_overrides[require_internal_tenant_context] = _tenant_ctx
    return app


@pytest.fixture
async def client(db_session):
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_session(db: AsyncSession) -> ConversationSession:
    conv = ConversationSession(status=ConversationStatus.active)
    db.add(conv)
    await db.flush()
    return conv


class TestPrepareSetsThinking:
    @pytest.mark.asyncio
    async def test_prepare_turn_sets_thinking_with_current_turn(self, client, db_session):
        conv = await _make_session(db_session)
        response = await client.post(PREPARE_URL.format(sid=conv.id), json={"user_message": "hello"})
        assert response.status_code == 200

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state == ActivityState.thinking
        assert activity.current_turn_id is not None
        assert activity.is_terminal is False

    @pytest.mark.asyncio
    async def test_prepare_turn_unknown_session_still_returns_gracefully(self, client):
        response = await client.post(
            PREPARE_URL.format(sid=uuid.uuid4()), json={"user_message": "hello"}
        )
        assert response.status_code == 200
        assert response.json().get("no_agent_message")


class TestAppendResolvesTerminal:
    @pytest.mark.asyncio
    async def test_append_normal_reply_resolves_finished(self, client, db_session):
        conv = await _make_session(db_session)
        await client.post(PREPARE_URL.format(sid=conv.id), json={"user_message": "hi"})
        response = await client.post(
            APPEND_URL.format(sid=conv.id), json={"agent_reply": "all done"}
        )
        assert response.status_code == 200

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state == ActivityState.finished
        assert activity.is_terminal is True
        assert activity.finished_at is not None

    @pytest.mark.asyncio
    async def test_append_timeout_resolves_timed_out(self, client, db_session):
        conv = await _make_session(db_session)
        await client.post(PREPARE_URL.format(sid=conv.id), json={"user_message": "hi"})
        response = await client.post(
            APPEND_URL.format(sid=conv.id),
            json={"agent_reply": "timed out", "status_events": [{"status": "timeout_or_failed"}]},
        )
        assert response.status_code == 200
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state == ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_append_guardrail_stop_resolves_failed(self, client, db_session):
        conv = await _make_session(db_session)
        await client.post(PREPARE_URL.format(sid=conv.id), json={"user_message": "hi"})
        response = await client.post(
            APPEND_URL.format(sid=conv.id),
            json={
                "agent_reply": "stopped",
                "status_events": [{"status": "guardrail_iteration_limit"}],
            },
        )
        assert response.status_code == 200
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state == ActivityState.failed

    @pytest.mark.asyncio
    async def test_append_uses_last_status_event(self, client, db_session):
        """Only the final status event decides the terminal state."""
        conv = await _make_session(db_session)
        await client.post(PREPARE_URL.format(sid=conv.id), json={"user_message": "hi"})
        await client.post(
            APPEND_URL.format(sid=conv.id),
            json={
                "agent_reply": "done",
                "status_events": [
                    {"status": "timeout_or_failed"},
                    {"status": "thinking"},
                ],
            },
        )
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state == ActivityState.finished
