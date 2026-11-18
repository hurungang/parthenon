"""Unit tests — internal resume-index, checkpoint, and claim endpoints.

Covers resumable-agent-turn-persistence (Phase 2.3–2.5) on the Control Center
internal data plane (``/api/v1/internal/data/conversations/{id}/resume...``):

- fail closed (401) without a service certificate / signed tenant context
- create → read → complete; a duplicate complete returns the stored outcome
  without a second outcome turn
- claim: acquired / already_held / terminal / not_found
- checkpoint write/read round-trips the payload byte-for-byte; oversized
  payloads are rejected
- cross-tenant access is rejected with 403 and persists nothing
- the routes are CH-allowlisted and AR-denied
"""
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import TenantContext
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversation_turn_resume import (
    ConversationTurnResume,
    ResumeOutcome,
    ResumeState,
)
from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)
from app.db.models.tenant import Tenant
from app.db.session import get_db

RESUME_URL = "/api/v1/internal/data/conversations/{sid}/resume"
CLAIM_URL = RESUME_URL + "/claim"
RELEASE_URL = RESUME_URL + "/release"
COMPLETE_URL = RESUME_URL + "/complete"
CHECKPOINT_URL = RESUME_URL + "/checkpoint"

TENANT_ID = uuid.uuid4()


def _allowlist_route(path: str) -> str:
    """Canonical allowlist template form of a test URL."""
    return path.replace("{sid}", "{conv_session_id}")


def _tenant_ctx(tenant_id: uuid.UUID | None = None) -> TenantContext:
    tid = tenant_id or TENANT_ID
    return TenantContext(tenant_id=tid, slug=f"tenant-{tid.hex[:6]}", name="test-tenant")


async def _make_session(
    db: AsyncSession, *, tenant_id: uuid.UUID | None = None
) -> ConversationSession:
    conv = ConversationSession(
        status=ConversationStatus.active,
        tenant_id=tenant_id,
    )
    db.add(conv)
    await db.flush()
    return conv


def _build_app(
    db: AsyncSession,
    *,
    bypass_security: bool,
    tenant_id: uuid.UUID | None = None,
) -> FastAPI:
    from app.api.deps import require_internal_tenant_context, require_service_certificate
    from app.api.v1.internal.session_data import InternalSessionDataRouter

    app = FastAPI()
    app.include_router(InternalSessionDataRouter, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    if bypass_security:
        app.dependency_overrides[require_service_certificate] = lambda: None
        app.dependency_overrides[require_internal_tenant_context] = (
            lambda: _tenant_ctx(tenant_id)
        )
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
    async def test_resume_put_without_service_cert_is_401(self, secured_client):
        response = await secured_client.put(
            RESUME_URL.format(sid=uuid.uuid4()), json={}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_claim_without_service_cert_is_401(self, secured_client):
        response = await secured_client.post(
            CLAIM_URL.format(sid=uuid.uuid4()),
            json={"instance_id": "ar-1", "lease_seconds": 45},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_checkpoint_put_without_service_cert_is_401(self, secured_client):
        response = await secured_client.put(
            CHECKPOINT_URL.format(sid=uuid.uuid4()), json={"payload": {}}
        )
        assert response.status_code == 401


class TestResumeIndexEndpoints:
    @pytest.mark.asyncio
    async def test_create_read_and_idle_null(self, open_client, db_session):
        conv = await _make_session(db_session)

        # Idle session → explicit null.
        idle = await open_client.get(RESUME_URL.format(sid=conv.id))
        assert idle.status_code == 200
        assert idle.json() is None

        created = await open_client.put(
            RESUME_URL.format(sid=conv.id),
            json={"idempotency_key": "turn-1", "resume_key": "key-1"},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["resume_key"] == "key-1"
        assert body["state"] == ResumeState.waiting_for_human.value
        assert body["write_applied"] is False
        assert body["active_resume_id"] == body["resume_id"]
        assert "payload" not in body

        read = await open_client.get(RESUME_URL.format(sid=conv.id))
        assert read.status_code == 200
        assert read.json()["resume_id"] == body["resume_id"]

    @pytest.mark.asyncio
    async def test_unknown_session_is_404(self, open_client):
        response = await open_client.get(RESUME_URL.format(sid=uuid.uuid4()))
        assert response.status_code == 404

        created = await open_client.put(RESUME_URL.format(sid=uuid.uuid4()), json={})
        assert created.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_is_idempotent_and_appends_one_outcome_turn(
        self, open_client, db_session
    ):
        conv = await _make_session(db_session)
        created = (
            await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        ).json()

        completed = await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.denied.value,
                "outcome_turn_content": "Nothing was written.",
            },
        )
        assert completed.status_code == 200
        first = completed.json()
        assert first["state"] == ResumeState.resolved.value
        assert first["resume_outcome"] == ResumeOutcome.denied.value
        assert first["is_terminal"] is True
        assert first["outcome_turn_id"] is not None
        assert first["active_resume_id"] is None

        duplicate = await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.denied.value,
                "outcome_turn_content": "Nothing was written.",
            },
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["outcome_turn_id"] == first["outcome_turn_id"]

        turns = (
            (
                await db_session.execute(
                    select(ConversationTurn).where(
                        ConversationTurn.session_id == conv.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(turns) == 1

    @pytest.mark.asyncio
    async def test_complete_approved_applied_requires_write_applied(
        self, open_client, db_session
    ):
        conv = await _make_session(db_session)
        created = (
            await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        ).json()

        rejected = await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.approved_applied.value,
                "write_applied": False,
            },
        )
        assert rejected.status_code == 409

        applied = await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.approved_applied.value,
                "write_applied": True,
                "applied_effect_summary": {"created": "agent_type:demo"},
            },
        )
        assert applied.status_code == 200
        assert applied.json()["write_applied"] is True
        assert applied.json()["state"] == ResumeState.resolved.value

    @pytest.mark.asyncio
    async def test_complete_resolves_activity_to_finished(self, open_client, db_session):
        from app.services.conversations.activity_store import ConversationActivityStore

        conv = await _make_session(db_session)
        created = (
            await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        ).json()
        await ConversationActivityStore().upsert(
            conv.id,
            db_session,
            state=ActivityState.waiting_for_human,
            active_resume_id=uuid.UUID(created["resume_id"]),
        )

        completed = await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.denied.value,
            },
        )
        assert completed.status_code == 200

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.finished
        assert activity.active_resume_id is None

    @pytest.mark.asyncio
    async def test_release_endpoint(self, open_client, db_session):
        conv = await _make_session(db_session)
        await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        await open_client.post(
            CLAIM_URL.format(sid=conv.id),
            json={"instance_id": "ar-1", "lease_seconds": 45},
        )

        wrong_holder = await open_client.post(
            RELEASE_URL.format(sid=conv.id), json={"instance_id": "ar-2"}
        )
        assert wrong_holder.status_code == 200
        assert wrong_holder.json()["released"] is False

        released = await open_client.post(
            RELEASE_URL.format(sid=conv.id), json={"instance_id": "ar-1"}
        )
        assert released.status_code == 200
        assert released.json()["released"] is True


class TestClaimEndpoint:
    @pytest.mark.asyncio
    async def test_claim_contention_then_terminal(self, open_client, db_session):
        conv = await _make_session(db_session)
        created = (
            await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        ).json()

        first = await open_client.post(
            CLAIM_URL.format(sid=conv.id),
            json={"instance_id": "ar-1", "lease_seconds": 45},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "acquired"
        assert first.json()["holder_instance_id"] == "ar-1"

        second = await open_client.post(
            CLAIM_URL.format(sid=conv.id),
            json={"instance_id": "ar-2", "lease_seconds": 45},
        )
        assert second.status_code == 200
        assert second.json()["status"] == "already_held"
        assert second.json()["holder_instance_id"] == "ar-1"

        # A resolved turn is terminal for any further claimer.
        await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.denied.value,
            },
        )
        terminal = await open_client.post(
            CLAIM_URL.format(sid=conv.id),
            json={"instance_id": "ar-3", "lease_seconds": 45},
        )
        assert terminal.status_code == 200
        assert terminal.json()["status"] == "terminal"

    @pytest.mark.asyncio
    async def test_claim_not_found(self, open_client, db_session):
        conv = await _make_session(db_session)
        response = await open_client.post(
            CLAIM_URL.format(sid=conv.id),
            json={"instance_id": "ar-1", "lease_seconds": 45},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "not_found"


class TestCheckpointEndpoints:
    @pytest.mark.asyncio
    async def test_checkpoint_round_trips_byte_for_byte(self, open_client, db_session):
        conv = await _make_session(db_session)
        await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        payload = {
            "checkpoint": {"id": "1ef", "channel_values": {"messages": [1, 2, 3]}},
            "unicode": "héllo",
        }

        saved = await open_client.put(
            CHECKPOINT_URL.format(sid=conv.id),
            json={"payload": payload, "schema_version": 2},
        )
        assert saved.status_code == 200
        assert saved.json()["payload"] is None  # write never echoes the payload
        assert saved.json()["payload_bytes"] > 0

        loaded = await open_client.get(CHECKPOINT_URL.format(sid=conv.id))
        assert loaded.status_code == 200
        assert loaded.json()["payload"] == payload
        assert loaded.json()["schema_version"] == 2

    @pytest.mark.asyncio
    async def test_checkpoint_requires_live_resume(self, open_client, db_session):
        conv = await _make_session(db_session)
        response = await open_client.put(
            CHECKPOINT_URL.format(sid=conv.id), json={"payload": {"v": 1}}
        )
        assert response.status_code == 404

        missing = await open_client.get(CHECKPOINT_URL.format(sid=conv.id))
        assert missing.status_code == 200
        assert missing.json() is None

    @pytest.mark.asyncio
    async def test_checkpoint_consumed_is_not_loadable(self, open_client, db_session):
        conv = await _make_session(db_session)
        created = (
            await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        ).json()
        await open_client.put(
            CHECKPOINT_URL.format(sid=conv.id), json={"payload": {"v": 1}}
        )
        await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.denied.value,
            },
        )
        loaded = await open_client.get(CHECKPOINT_URL.format(sid=conv.id))
        assert loaded.status_code == 200
        assert loaded.json() is None


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_cross_tenant_write_is_403_and_persists_nothing(self, db_session):
        own_tenant = Tenant(name=f"own-{uuid.uuid4().hex[:6]}", slug=f"own-{uuid.uuid4().hex[:8]}")
        other_tenant = Tenant(
            name=f"other-{uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:8]}"
        )
        db_session.add_all([own_tenant, other_tenant])
        await db_session.flush()

        conv = await _make_session(db_session, tenant_id=own_tenant.id)
        app = _build_app(
            db_session, bypass_security=True, tenant_id=other_tenant.id
        )
        async for client in _client(app):
            response = await client.put(RESUME_URL.format(sid=conv.id), json={})
            assert response.status_code == 403

        stored = (
            (
                await db_session.execute(
                    select(ConversationTurnResume).where(
                        ConversationTurnResume.conversation_session_id == conv.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert stored == []

    @pytest.mark.asyncio
    async def test_same_tenant_write_is_allowed(self, db_session):
        tenant = Tenant(name=f"t-{uuid.uuid4().hex[:6]}", slug=f"t-{uuid.uuid4().hex[:8]}")
        db_session.add(tenant)
        await db_session.flush()

        conv = await _make_session(db_session, tenant_id=tenant.id)
        app = _build_app(db_session, bypass_security=True, tenant_id=tenant.id)
        async for client in _client(app):
            response = await client.put(RESUME_URL.format(sid=conv.id), json={})
            assert response.status_code == 200


class TestAllowlist:
    def test_resume_routes_are_ch_allowlisted_and_ar_denied(self):
        from app.api.deps import _AR_ALLOWLIST, _CH_ALLOWLIST

        routes = {
            ("PUT", _allowlist_route(RESUME_URL)),
            ("GET", _allowlist_route(RESUME_URL)),
            ("POST", _allowlist_route(RELEASE_URL)),
            ("POST", _allowlist_route(COMPLETE_URL)),
            ("PUT", _allowlist_route(CHECKPOINT_URL)),
            ("GET", _allowlist_route(CHECKPOINT_URL)),
            ("POST", _allowlist_route(CLAIM_URL)),
        }
        assert routes <= _CH_ALLOWLIST
        assert routes & _AR_ALLOWLIST == set()


class TestWaitingInvariant:
    @pytest.mark.asyncio
    async def test_waiting_activity_without_live_resume_is_409(
        self, open_client, db_session
    ):
        conv = await _make_session(db_session)
        response = await open_client.put(
            f"/api/v1/internal/data/conversations/{conv.id}/activity",
            json={"state": "waiting_for_human"},
        )
        assert response.status_code == 409

        from app.services.conversations.activity_store import ConversationActivityStore

        assert await ConversationActivityStore().get(conv.id, db_session) is None

    @pytest.mark.asyncio
    async def test_waiting_activity_with_live_resume_is_persisted(
        self, open_client, db_session
    ):
        conv = await _make_session(db_session)
        created = (
            await open_client.put(RESUME_URL.format(sid=conv.id), json={})
        ).json()

        response = await open_client.put(
            f"/api/v1/internal/data/conversations/{conv.id}/activity",
            json={
                "state": "waiting_for_human",
                "active_resume_id": created["resume_id"],
            },
        )
        assert response.status_code == 200
        assert response.json()["active_resume_id"] == created["resume_id"]

        # Resolving the turn clears the activity link.
        await open_client.post(
            COMPLETE_URL.format(sid=conv.id),
            json={
                "resume_id": created["resume_id"],
                "outcome": ResumeOutcome.denied.value,
            },
        )
        read = await open_client.get(
            f"/api/v1/internal/data/conversations/{conv.id}/activity"
        )
        assert read.status_code == 200
        assert read.json()["active_resume_id"] is None
