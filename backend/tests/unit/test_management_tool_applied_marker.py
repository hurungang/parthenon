"""Unit tests — exactly-once confirmed write (Phase 5.1 applied marker).

The confirmed management-tool dispatch is the single chokepoint that records
``write_applied`` on the paused turn's resume record **in the same transaction
as the write**:

- one confirmed dispatch applies the write once and stamps the marker;
- a duplicate/retried dispatch with the same idempotency key applies nothing a
  second time and returns the stored effect summary;
- a write that fails (or a denial / expiry, which never reaches this path)
  leaves ``write_applied`` false;
- a key that belongs to no paused turn applies normally without a marker.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import TenantContext
from app.db.models.conversation_turn_resume import (
    ConversationTurnResume,
    ResumeOutcome,
    ResumeState,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import InterveneRequest, InterventionType
from app.db.models.skills import Skill
from app.db.session import get_db
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

TENANT_ID = uuid.uuid4()
URL = "/api/v1/internal/management-tools/create_skill"
HEADER = {"X-Turn-Idempotency-Key": ""}  # value injected per test


@pytest.fixture
def tenant_ctx() -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, slug="marker-tenant", name="marker-tenant")


def _build_app(db: AsyncSession, tenant_ctx: TenantContext) -> FastAPI:
    from app.api.deps import (
        require_internal_tenant_context,
        require_service_certificate,
    )
    from app.api.v1.internal import management_tools

    app = FastAPI()
    app.include_router(management_tools.router, prefix="/api/v1")
    app.include_router(management_tools.meta_router, prefix="/api/v1")

    async def _override_db():
        yield db

    async def _allow(*_args, **_kwargs) -> None:
        return None

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_service_certificate] = lambda: None
    app.dependency_overrides[require_internal_tenant_context] = lambda: tenant_ctx
    # Authorization parity is covered elsewhere; this suite exercises the
    # applied-marker chokepoint.
    management_tools._authorize = _allow  # type: ignore[assignment]
    return app


async def _client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _make_paused_turn(
    db: AsyncSession, *, state: ResumeState = ResumeState.resuming
) -> tuple[ConversationSession, ConversationTurnResume]:
    conv = ConversationSession(status=ConversationStatus.active, tenant_id=TENANT_ID)
    db.add(conv)
    await db.flush()

    from app.db.models.agents import AgentInputType, AgentType

    agent_type = AgentType(
        name=f"marker-at-{uuid.uuid4().hex}",
        input_type=AgentInputType.conversation,
    )
    db.add(agent_type)
    await db.flush()

    req = InterveneRequest(
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="**Create Skill: Marker**",
        conversation_session_id=conv.id,
    )
    db.add(req)
    await db.flush()

    store = ConversationTurnResumeStore()
    record = await store.create_or_reuse(
        conv.id,
        db,
        intervene_request_id=req.id,
        idempotency_key=f"turn-{uuid.uuid4().hex}",
    )
    if state is ResumeState.resuming:
        record = await store.mark_resuming(
            record.id, db, applied_by_user_id=None
        )
    await db.commit()
    return conv, record


def _payload(name: str) -> dict:
    return {
        "session_id": "assistant-session",
        "user_sub": "marker-user",
        "tool_args": {
            "name": name,
            "data": {"description": "confirmed skill", "instructions": "do it"},
        },
    }


async def _skill_count(db: AsyncSession, name: str) -> int:
    """Count rows for one skill name (the test engine is shared per session)."""
    return (
        await db.execute(
            select(func.count())
            .select_from(Skill)
            .where(Skill.tenant_id == TENANT_ID, Skill.name == name)
        )
    ).scalar_one()


class TestExactlyOnceAppliedMarker:
    @pytest.mark.asyncio
    async def test_confirmed_write_commits_the_applied_marker(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"

        async for client in _client(app):
            response = await client.post(
                URL,
                json=_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code == 200, response.text
        assert "record" in response.json()["result"]

        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.write_applied is True
        assert refreshed.applied_at is not None
        assert refreshed.applied_effect_summary is not None
        assert refreshed.applied_effect_summary["tool"] == "create_skill"
        assert refreshed.applied_effect_summary["verb"] == "create"
        assert refreshed.applied_effect_summary["resource"] == "skills"
        assert await _skill_count(db_session, name) == 1

    @pytest.mark.asyncio
    async def test_duplicate_dispatch_applies_once_and_returns_stored_summary(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async for client in _client(app):
            first = await client.post(URL, json=_payload(name), headers=headers)
            second = await client.post(URL, json=_payload(name), headers=headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        duplicate = second.json()["result"]
        assert duplicate["duplicate_dispatch"] is True
        assert duplicate["write_applied"] is True
        assert duplicate["applied_effect_summary"]["tool"] == "create_skill"

        # Exactly one write: no second Skill row.
        assert await _skill_count(db_session, name) == 1

        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.write_applied is True

    @pytest.mark.asyncio
    async def test_failed_write_leaves_write_applied_false(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        """A rejected write rolls the marker back with it (same transaction)."""
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        # Pre-create the name so the confirmed write fails the uniqueness check.
        db_session.add(Skill(tenant_id=TENANT_ID, name=name, is_active=True))
        await db_session.flush()

        async for client in _client(app):
            response = await client.post(
                URL,
                json=_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code in (400, 409), response.text
        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.write_applied is False
        assert refreshed.applied_at is None
        assert await _skill_count(db_session, name) == 1

    @pytest.mark.asyncio
    async def test_unresumable_turn_never_sets_write_applied(
        self, db_session: AsyncSession
    ):
        _conv, record = await _make_paused_turn(db_session)
        store = ConversationTurnResumeStore()
        resolved = await store.resolve_unresumable(
            record.id, db_session, reason_code="expired"
        )
        await db_session.commit()

        assert resolved.is_terminal is True
        assert resolved.resume_outcome is ResumeOutcome.expired
        assert resolved.write_applied is False
        assert resolved.applied_at is None

        # `approved_applied` without the marker stays forbidden.
        from app.services.conversations.turn_resume_store import (
            TurnResumeTransitionError,
        )

        with pytest.raises(TurnResumeTransitionError):
            await store.resolve(record.id, db_session, ResumeOutcome.approved_applied)

    @pytest.mark.asyncio
    async def test_unknown_key_applies_without_a_marker(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        async for client in _client(app):
            response = await client.post(
                URL,
                json=_payload(name),
                headers={"X-Turn-Idempotency-Key": "not-a-paused-turn"},
            )
        assert response.status_code == 200, response.text
        assert await _skill_count(db_session, name) == 1

    @pytest.mark.asyncio
    async def test_no_key_applies_without_a_marker(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        async for client in _client(app):
            response = await client.post(
                URL, json=_payload(name)
            )
        assert response.status_code == 200, response.text
        assert await _skill_count(db_session, name) == 1
