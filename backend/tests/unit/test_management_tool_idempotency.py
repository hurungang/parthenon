"""Exactly-once confirmed write — turn idempotency key at the dispatch chokepoint.

Task 7.5 (gaps closed here; the applied-marker baseline lives in
``tests/unit/test_management_tool_applied_marker.py``):

* a **crash-style retry after the write committed** (a fresh dispatch with the
  same key) returns the stored effect summary and never runs the handler again;
* the meta wrapper (``invoke_management_tool``) carries the same key and obeys
  the same exactly-once contract as the per-tool endpoint;
* a **denied / expired / superseded** turn never applies a late dispatch, even
  with the correct key, and ``write_applied`` stays false;
* the applied-marker read takes a row lock on PostgreSQL so two concurrent
  duplicates serialise (the loser observes the committed marker).
"""
from __future__ import annotations

import inspect
import uuid
from typing import Any

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
TOOL_URL = "/api/v1/internal/management-tools/create_skill"
META_URL = "/api/v1/internal/management-tools/invoke_management_tool"


@pytest.fixture
def tenant_ctx() -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, slug="idem-tenant", name="idem-tenant")


@pytest.fixture
def app(db_session: AsyncSession, tenant_ctx: TenantContext, monkeypatch) -> FastAPI:
    from app.api.deps import require_internal_tenant_context, require_service_certificate
    from app.api.v1.internal import management_tools

    app = FastAPI()
    app.include_router(management_tools.meta_router, prefix="/api/v1")
    app.include_router(management_tools.router, prefix="/api/v1")

    async def _override_db():
        yield db_session

    async def _allow(*_args: Any, **_kwargs: Any) -> None:
        return None

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_service_certificate] = lambda: None
    app.dependency_overrides[require_internal_tenant_context] = lambda: tenant_ctx
    # Authorization parity is covered elsewhere; this suite exercises the
    # exactly-once chokepoint.
    monkeypatch.setattr(management_tools, "_authorize", _allow)
    return app


def _client(app: FastAPI):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _make_paused_turn(
    db: AsyncSession, *, state: ResumeState = ResumeState.resuming
) -> tuple[ConversationSession, ConversationTurnResume]:
    from app.db.models.agents import AgentInputType, AgentType

    conv = ConversationSession(status=ConversationStatus.active, tenant_id=TENANT_ID)
    db.add(conv)
    await db.flush()

    agent_type = AgentType(
        name=f"idem-at-{uuid.uuid4().hex}",
        input_type=AgentInputType.conversation,
    )
    db.add(agent_type)
    await db.flush()

    req = InterveneRequest(
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="**Create Skill: Idempotency**",
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
        record = await store.mark_resuming(record.id, db, applied_by_user_id=None)
    await db.commit()
    return conv, record


def _payload(name: str) -> dict:
    return {
        "session_id": "assistant-session",
        "user_sub": "idem-user",
        "tool_args": {
            "name": name,
            "data": {"description": "confirmed skill", "instructions": "do it"},
        },
    }


def _meta_payload(name: str) -> dict:
    return {
        "session_id": "assistant-session",
        "user_sub": "idem-user",
        "tool_args": {
            "tool_name": "create_skill",
            "args": {
                "name": name,
                "data": {"description": "confirmed skill", "instructions": "do it"},
            },
        },
    }


async def _skill_count(db: AsyncSession, name: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Skill)
            .where(Skill.tenant_id == TENANT_ID, Skill.name == name)
        )
    ).scalar_one()


async def _refresh(
    db: AsyncSession, record: ConversationTurnResume
) -> ConversationTurnResume:
    refreshed = await db.get(ConversationTurnResume, record.id)
    assert refreshed is not None
    await db.refresh(refreshed)
    return refreshed


class TestCrashRetryAfterCommit:
    @pytest.mark.asyncio
    async def test_retry_with_same_key_returns_stored_summary_without_the_handler(
        self, app: FastAPI, db_session: AsyncSession, monkeypatch
    ):
        """A crash after commit leaves write + marker; the retry must not re-run
        the write (it returns the stored effect summary instead)."""
        from app.api.v1.internal import management_tools

        _conv, record = await _make_paused_turn(db_session)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async with _client(app) as client:
            first = await client.post(TOOL_URL, json=_payload(name), headers=headers)
        assert first.status_code == 200, first.text
        assert await _skill_count(db_session, name) == 1
        stored = await _refresh(db_session, record)
        assert stored.write_applied is True
        first_summary = stored.applied_effect_summary
        assert first_summary is not None
        # The per-call summary lives in the effects map (top-level fields are
        # the compatibility mirror of the latest effect).
        assert len(first_summary["effects"]) == 1
        (first_effect,) = first_summary["effects"].values()

        # Simulate the process crash + retry: the handler must never run again.
        async def _boom(*_args: Any, **_kwargs: Any) -> dict:
            raise AssertionError("the confirmed write must not be re-executed")

        monkeypatch.setattr(management_tools, "_dispatch", _boom)

        async with _client(app) as client:
            retry = await client.post(TOOL_URL, json=_payload(name), headers=headers)

        assert retry.status_code == 200, retry.text
        replay = retry.json()["result"]
        assert replay["duplicate_dispatch"] is True
        assert replay["write_applied"] is True
        assert replay["applied_effect_summary"] == first_effect
        assert await _skill_count(db_session, name) == 1

    @pytest.mark.asyncio
    async def test_meta_wrapper_replays_the_stored_summary_too(
        self, app: FastAPI, db_session: AsyncSession, monkeypatch
    ):
        """The progressive-disclosure wrapper obeys the same contract."""
        from app.api.v1.internal import management_tools

        _conv, record = await _make_paused_turn(db_session)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async with _client(app) as client:
            first = await client.post(META_URL, json=_meta_payload(name), headers=headers)
            assert first.status_code == 200, first.text
            assert "record" in first.json()["result"]
            assert await _skill_count(db_session, name) == 1

            async def _boom(*_args: Any, **_kwargs: Any) -> dict:
                raise AssertionError("meta replay must not re-execute the write")

            monkeypatch.setattr(management_tools, "_dispatch", _boom)
            second = await client.post(META_URL, json=_meta_payload(name), headers=headers)

        assert second.status_code == 200, second.text
        assert second.json()["result"]["duplicate_dispatch"] is True
        assert await _skill_count(db_session, name) == 1


class TestTerminalTurnNeverWrites:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("outcome", "resolver"),
        [
            ("denied", "resolve"),
            ("cancelled", "resolve"),
            ("expired", "resolve_unresumable"),
            ("resume_failed", "resolve_unresumable"),
        ],
    )
    async def test_late_dispatch_for_a_terminal_turn_is_refused(
        self, app: FastAPI, db_session: AsyncSession, outcome, resolver
    ):
        _conv, record = await _make_paused_turn(db_session)
        store = ConversationTurnResumeStore()
        if resolver == "resolve_unresumable":
            closed = await store.resolve_unresumable(
                record.id, db_session, reason_code=outcome
            )
        else:
            closed = await store.resolve(
                record.id, db_session, ResumeOutcome(outcome)
            )
        await db_session.commit()
        assert closed.is_terminal is True
        assert closed.write_applied is False

        name = f"skill-{uuid.uuid4().hex[:8]}"
        async with _client(app) as client:
            response = await client.post(
                TOOL_URL,
                json=_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["error"] == "resume_terminal_no_write"
        assert detail["write_applied"] is False
        assert detail["resume_id"] == str(record.id)

        # Nothing was written and the marker stayed false — under any retry.
        assert await _skill_count(db_session, name) == 0
        after = await _refresh(db_session, record)
        assert after.write_applied is False
        assert after.applied_at is None


class TestRowLockSerialisation:
    def test_applied_check_takes_a_row_lock_outside_sqlite(self):
        """Two concurrent duplicates must serialise on the resume row so the
        loser sees the committed marker (rather than both passing the check)."""
        source = inspect.getsource(
            ConversationTurnResumeStore.lock_for_applied_check
        )
        assert "with_for_update" in source
        assert "sqlite" in source
