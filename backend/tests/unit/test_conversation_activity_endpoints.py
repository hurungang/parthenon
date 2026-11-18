"""Unit tests — internal conversation activity endpoints (PUT/GET).

``/api/v1/internal/data/conversations/{conv_session_id}/activity``:

- fail closed (401) without a valid service certificate / signed tenant
  context — a security boundary, not just a data path
- valid PUT upserts the single live activity row and echoes the record
- valid PUT with an unknown state → 422; unknown session → 404
- valid GET returns the persisted record; idle session → explicit ``null``
- GET for an unknown session → 404
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

ACTIVITY_URL = "/api/v1/internal/data/conversations/{sid}/activity"


def _tenant_ctx() -> TenantContext:
    return TenantContext(tenant_id=uuid.uuid4(), slug="test-tenant", name="test-tenant")


async def _make_session(db: AsyncSession) -> ConversationSession:
    conv = ConversationSession(status=ConversationStatus.active)
    db.add(conv)
    await db.flush()
    return conv


def _build_app(db: AsyncSession, *, bypass_security: bool) -> FastAPI:
    from app.api.deps import require_internal_tenant_context, require_service_certificate
    from app.api.v1.internal.session_data import InternalSessionDataRouter

    app = FastAPI()
    app.include_router(InternalSessionDataRouter, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    if bypass_security:
        app.dependency_overrides[require_service_certificate] = lambda: None
        app.dependency_overrides[require_internal_tenant_context] = lambda: _tenant_ctx()
    return app


async def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def secured_client(db_session):
    """Router with the REAL service-cert + tenant-context dependencies — fail closed."""
    app = _build_app(db_session, bypass_security=False)
    async for c in _client(app):
        yield c


@pytest.fixture
async def open_client(db_session):
    """Router with security dependencies bypassed — exercises the data path."""
    app = _build_app(db_session, bypass_security=True)
    async for c in _client(app):
        yield c


class TestFailClosed:
    @pytest.mark.asyncio
    async def test_put_without_service_cert_is_401(self, secured_client):
        response = await secured_client.put(
            ACTIVITY_URL.format(sid=uuid.uuid4()), json={"state": "thinking"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_without_service_cert_is_401(self, secured_client):
        response = await secured_client.get(ACTIVITY_URL.format(sid=uuid.uuid4()))
        assert response.status_code == 401


class TestUpsertEndpoint:
    @pytest.mark.asyncio
    async def test_put_upserts_and_echoes_record(self, open_client, db_session):
        conv = await _make_session(db_session)
        response = await open_client.put(
            ACTIVITY_URL.format(sid=conv.id),
            json={"state": "using_tool", "tool_name": "cc____list_agents"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "using_tool"
        assert body["tool_name"] == "cc____list_agents"
        assert body["is_terminal"] is False

        stored = await ConversationActivityStore().get(conv.id, db_session)
        assert stored is not None
        assert stored.state == ActivityState.using_tool

    @pytest.mark.asyncio
    async def test_put_unknown_state_is_422(self, open_client, db_session):
        conv = await _make_session(db_session)
        response = await open_client.put(
            ACTIVITY_URL.format(sid=conv.id), json={"state": "teleporting"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_put_unknown_session_is_404(self, open_client):
        response = await open_client.put(
            ACTIVITY_URL.format(sid=uuid.uuid4()), json={"state": "thinking"}
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_repeated_put_keeps_one_live_row(self, open_client, db_session):
        from app.services.conversations.turn_resume_store import (
            ConversationTurnResumeStore,
        )

        conv = await _make_session(db_session)
        for state in ("thinking", "delegating"):
            response = await open_client.put(
                ACTIVITY_URL.format(sid=conv.id), json={"state": state}
            )
            assert response.status_code == 200

        resume = await ConversationTurnResumeStore().create_or_reuse(
            conv.id, db_session
        )
        response = await open_client.put(
            ACTIVITY_URL.format(sid=conv.id),
            json={"state": "waiting_for_human", "active_resume_id": str(resume.id)},
        )
        assert response.status_code == 200
        assert response.json()["state"] == "waiting_for_human"
        assert response.json()["active_resume_id"] == str(resume.id)

        from sqlalchemy import select

        from app.db.models.conversation_activity import ConversationActivity

        rows = (
            (
                await db_session.execute(
                    select(ConversationActivity).where(
                        ConversationActivity.conversation_session_id == conv.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


TOUCH_URL = "/api/v1/internal/data/conversations/{sid}/activity/touch"


class TestTouchEndpoint:
    """POST /activity/touch — live-turn heartbeat refresh (no state change)."""

    @pytest.mark.asyncio
    async def test_touch_without_service_cert_is_401(self, secured_client):
        response = await secured_client.post(TOUCH_URL.format(sid=uuid.uuid4()))
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_touch_refreshes_last_updated_at_without_changing_state(
        self, open_client, db_session
    ):
        from datetime import datetime, timedelta, timezone

        conv = await _make_session(db_session)
        await ConversationActivityStore().upsert(
            conv.id, db_session, state=ActivityState.using_tool, tool_name="cc____x"
        )
        stored = await ConversationActivityStore().get(conv.id, db_session)
        assert stored is not None
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        stored.last_updated_at = stale
        await db_session.flush()

        response = await open_client.post(TOUCH_URL.format(sid=conv.id))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "using_tool"
        assert body["tool_name"] == "cc____x"
        assert body["is_terminal"] is False

        refreshed = await ConversationActivityStore().get(conv.id, db_session)
        assert refreshed is not None
        stored_last_updated = refreshed.last_updated_at
        if stored_last_updated.tzinfo is None:
            stored_last_updated = stored_last_updated.replace(tzinfo=timezone.utc)
        assert stored_last_updated > stale
        assert refreshed.state == ActivityState.using_tool

    @pytest.mark.asyncio
    async def test_touch_does_not_refresh_a_paused_row(self, open_client, db_session):
        from datetime import datetime, timedelta, timezone

        from app.services.conversations.turn_resume_store import (
            ConversationTurnResumeStore,
        )

        conv = await _make_session(db_session)
        resume = await ConversationTurnResumeStore().create_or_reuse(conv.id, db_session)
        await ConversationActivityStore().upsert(
            conv.id,
            db_session,
            state=ActivityState.waiting_for_human,
            active_resume_id=resume.id,
        )
        stored = await ConversationActivityStore().get(conv.id, db_session)
        assert stored is not None
        paused_beat = datetime.now(timezone.utc) - timedelta(minutes=30)
        stored.last_updated_at = paused_beat
        await db_session.flush()

        response = await open_client.post(TOUCH_URL.format(sid=conv.id))
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "waiting_for_human"

        unchanged = await ConversationActivityStore().get(conv.id, db_session)
        assert unchanged is not None
        stored_last_updated = unchanged.last_updated_at
        if stored_last_updated.tzinfo is None:
            stored_last_updated = stored_last_updated.replace(tzinfo=timezone.utc)
        assert stored_last_updated == paused_beat

    @pytest.mark.asyncio
    async def test_touch_idle_session_returns_explicit_null(self, open_client, db_session):
        conv = await _make_session(db_session)
        response = await open_client.post(TOUCH_URL.format(sid=conv.id))
        assert response.status_code == 200
        assert response.json() is None

    @pytest.mark.asyncio
    async def test_touch_unknown_session_is_404(self, open_client):
        response = await open_client.post(TOUCH_URL.format(sid=uuid.uuid4()))
        assert response.status_code == 404


class TestReadEndpoint:
    @pytest.mark.asyncio
    async def test_get_returns_persisted_record(self, open_client, db_session):
        conv = await _make_session(db_session)
        await ConversationActivityStore().upsert(
            conv.id, db_session, state=ActivityState.delegating
        )
        response = await open_client.get(ACTIVITY_URL.format(sid=conv.id))
        assert response.status_code == 200
        assert response.json()["state"] == "delegating"

    @pytest.mark.asyncio
    async def test_get_idle_session_returns_explicit_null(self, open_client, db_session):
        conv = await _make_session(db_session)
        response = await open_client.get(ACTIVITY_URL.format(sid=conv.id))
        assert response.status_code == 200
        assert response.json() is None

    @pytest.mark.asyncio
    async def test_get_unknown_session_is_404(self, open_client):
        response = await open_client.get(ACTIVITY_URL.format(sid=uuid.uuid4()))
        assert response.status_code == 404
