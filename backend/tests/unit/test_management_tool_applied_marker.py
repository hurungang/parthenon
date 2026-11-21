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

Per-call batching (bug-fix): one paused turn may approve a BATCH of management
writes.  Each write is deduped by its own effect key (tool + canonical args),
reads bypass the marker entirely, and a true retry replays only that call's
summary.
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
BASE = "/api/v1/internal/management-tools"
URL = f"{BASE}/create_skill"
META_URL = f"{BASE}/invoke_management_tool"


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
    # Meta (literal) routes must be registered before the dynamic
    # ``/{tool_name}`` router so ``invoke_management_tool`` does not match it.
    app.include_router(management_tools.meta_router, prefix="/api/v1")
    app.include_router(management_tools.router, prefix="/api/v1")

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


def _skill_payload(name: str, *, description: str = "confirmed skill") -> dict:
    return {
        "session_id": "assistant-session",
        "user_sub": "marker-user",
        "tool_args": {
            "name": name,
            "data": {"description": description, "instructions": "do it"},
        },
    }


def _sop_payload(name: str) -> dict:
    return {
        "session_id": "assistant-session",
        "user_sub": "marker-user",
        "tool_args": {
            "name": name,
            "data": {"description": "confirmed sop", "instructions": "run it"},
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


async def _refresh(
    db: AsyncSession, record: ConversationTurnResume
) -> ConversationTurnResume:
    refreshed = await db.get(ConversationTurnResume, record.id)
    await db.refresh(refreshed)
    assert refreshed is not None
    return refreshed


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
                json=_skill_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code == 200, response.text
        assert "record" in response.json()["result"]

        refreshed = await _refresh(db_session, record)
        assert refreshed.write_applied is True
        assert refreshed.applied_at is not None
        assert refreshed.applied_effect_summary is not None
        assert refreshed.applied_effect_summary["tool"] == "create_skill"
        assert refreshed.applied_effect_summary["verb"] == "create"
        assert refreshed.applied_effect_summary["resource"] == "skills"
        assert len(refreshed.applied_effect_summary["effects"]) == 1
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
            first = await client.post(URL, json=_skill_payload(name), headers=headers)
            second = await client.post(URL, json=_skill_payload(name), headers=headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        created_id = first.json()["result"]["record"]["id"]
        duplicate = second.json()["result"]
        assert duplicate["duplicate_dispatch"] is True
        assert duplicate["write_applied"] is True
        assert duplicate["applied_effect_summary"]["tool"] == "create_skill"
        assert duplicate["applied_effect_summary"]["record_id"] == created_id

        # Exactly one write: no second Skill row.
        assert await _skill_count(db_session, name) == 1

        refreshed = await _refresh(db_session, record)
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
                json=_skill_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code in (400, 409), response.text
        refreshed = await _refresh(db_session, record)
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
                json=_skill_payload(name),
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
            response = await client.post(URL, json=_skill_payload(name))
        assert response.status_code == 200, response.text
        assert await _skill_count(db_session, name) == 1


class TestPerCallAppliedMarker:
    """A paused turn approving a BATCH of writes dedupes per call, not per turn."""

    @pytest.mark.asyncio
    async def test_two_distinct_writes_both_apply_in_one_paused_turn(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        first_name = f"skill-a-{uuid.uuid4().hex[:8]}"
        second_name = f"skill-b-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async for client in _client(app):
            first = await client.post(
                URL, json=_skill_payload(first_name), headers=headers
            )
            second = await client.post(
                URL, json=_skill_payload(second_name), headers=headers
            )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        first_result = first.json()["result"]
        second_result = second.json()["result"]
        assert "duplicate_dispatch" not in first_result
        assert "duplicate_dispatch" not in second_result
        assert first_result["record"]["name"] == first_name
        assert second_result["record"]["name"] == second_name
        # Both writes actually landed.
        assert await _skill_count(db_session, first_name) == 1
        assert await _skill_count(db_session, second_name) == 1

        refreshed = await _refresh(db_session, record)
        summary = refreshed.applied_effect_summary
        assert refreshed.write_applied is True
        assert summary is not None
        # Two per-call effects recorded on ONE resume.
        assert len(summary["effects"]) == 2
        assert {entry["record_id"] for entry in summary["effects"].values()} == {
            first_result["record"]["id"],
            second_result["record"]["id"],
        }
        # Top-level compatibility mirror is still a valid summary.
        assert summary["tool"] == "create_skill"
        assert summary["verb"] == "create"
        assert summary["resource"] == "skills"
        assert summary["record_id"] == second_result["record"]["id"]

    @pytest.mark.asyncio
    async def test_sop_write_after_skill_write_also_applies(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        """SOP parity action is ``manage`` — it must still be treated as a write
        (this is the exact batched-turn shape from the production incident)."""
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        skill_name = f"skill-{uuid.uuid4().hex[:8]}"
        sop_name = f"sop-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async for client in _client(app):
            skill = await client.post(
                URL, json=_skill_payload(skill_name), headers=headers
            )
            sop = await client.post(
                f"{BASE}/create_sop", json=_sop_payload(sop_name), headers=headers
            )

        assert skill.status_code == 200, skill.text
        assert sop.status_code == 200, sop.text
        assert "duplicate_dispatch" not in sop.json()["result"]
        assert sop.json()["result"]["record"]["name"] == sop_name

        refreshed = await _refresh(db_session, record)
        effects = refreshed.applied_effect_summary["effects"]
        assert len(effects) == 2
        assert {entry["tool"] for entry in effects.values()} == {
            "create_skill",
            "create_sop",
        }

    @pytest.mark.asyncio
    async def test_repeating_each_batched_write_replays_its_own_summary(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        first_name = f"skill-a-{uuid.uuid4().hex[:8]}"
        second_name = f"skill-b-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async for client in _client(app):
            first = await client.post(
                URL, json=_skill_payload(first_name), headers=headers
            )
            second = await client.post(
                URL, json=_skill_payload(second_name), headers=headers
            )
            first_retry = await client.post(
                URL, json=_skill_payload(first_name), headers=headers
            )
            second_retry = await client.post(
                URL, json=_skill_payload(second_name), headers=headers
            )

        first_id = first.json()["result"]["record"]["id"]
        second_id = second.json()["result"]["record"]["id"]

        first_replay = first_retry.json()["result"]
        second_replay = second_retry.json()["result"]
        assert first_replay["duplicate_dispatch"] is True
        assert second_replay["duplicate_dispatch"] is True
        # Each retry replays ITS OWN summary, never the latest/top-level one.
        assert first_replay["applied_effect_summary"]["record_id"] == first_id
        assert second_replay["applied_effect_summary"]["record_id"] == second_id
        assert first_replay["applied_effect_summary"]["record_id"] != second_id

        # No duplicate rows.
        assert await _skill_count(db_session, first_name) == 1
        assert await _skill_count(db_session, second_name) == 1

    @pytest.mark.asyncio
    async def test_read_after_write_is_not_deduped(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async for client in _client(app):
            write = await client.post(URL, json=_skill_payload(name), headers=headers)
            listed = await client.post(
                f"{BASE}/list_skills",
                json={
                    "session_id": "assistant-session",
                    "user_sub": "marker-user",
                    "tool_args": {},
                },
                headers=headers,
            )
            fetched = await client.post(
                f"{BASE}/get_skill",
                json={
                    "session_id": "assistant-session",
                    "user_sub": "marker-user",
                    "tool_args": {"name": name},
                },
                headers=headers,
            )

        assert write.status_code == 200, write.text
        assert listed.status_code == 200, listed.text
        assert fetched.status_code == 200, fetched.text
        list_result = listed.json()["result"]
        get_result = fetched.json()["result"]
        # Reads never replay the write summary.
        assert "duplicate_dispatch" not in list_result
        assert "duplicate_dispatch" not in get_result
        assert list_result["count"] == len(list_result["records"])
        assert any(row["name"] == name for row in list_result["records"])
        assert get_result["record"]["name"] == name

    @pytest.mark.asyncio
    async def test_same_tool_different_args_applies_both(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        """Distinct arguments are distinct calls, even for the same tool."""
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        first_name = f"skill-{uuid.uuid4().hex[:8]}"
        second_name = f"skill-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        async for client in _client(app):
            first = await client.post(
                URL, json=_skill_payload(first_name), headers=headers
            )
            second = await client.post(
                URL,
                json=_skill_payload(second_name, description="a different call"),
                headers=headers,
            )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert "duplicate_dispatch" not in second.json()["result"]
        assert await _skill_count(db_session, first_name) == 1
        assert await _skill_count(db_session, second_name) == 1

        refreshed = await _refresh(db_session, record)
        assert len(refreshed.applied_effect_summary["effects"]) == 2

    @pytest.mark.asyncio
    async def test_meta_wrapper_keys_on_the_inner_tool_and_args(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        _conv, record = await _make_paused_turn(db_session)
        app = _build_app(db_session, tenant_ctx)
        first_name = f"skill-a-{uuid.uuid4().hex[:8]}"
        second_name = f"skill-b-{uuid.uuid4().hex[:8]}"
        headers = {"X-Turn-Idempotency-Key": record.idempotency_key}

        def meta(name: str) -> dict:
            inner = _skill_payload(name)
            return {
                "session_id": inner["session_id"],
                "user_sub": inner["user_sub"],
                "tool_args": {"tool_name": "create_skill", "args": inner["tool_args"]},
            }

        async for client in _client(app):
            first = await client.post(META_URL, json=meta(first_name), headers=headers)
            second = await client.post(META_URL, json=meta(second_name), headers=headers)
            replay = await client.post(META_URL, json=meta(first_name), headers=headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert "duplicate_dispatch" not in second.json()["result"]
        assert replay.json()["result"]["duplicate_dispatch"] is True
        assert (
            replay.json()["result"]["applied_effect_summary"]["record_id"]
            == first.json()["result"]["record"]["id"]
        )
        assert await _skill_count(db_session, first_name) == 1
        assert await _skill_count(db_session, second_name) == 1

    @pytest.mark.asyncio
    async def test_legacy_same_tool_record_still_replays(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        """A pre-effects record (write_applied, no map) keeps exactly-once for a
        same-tool retry without a restart."""
        _conv, record = await _make_paused_turn(db_session)
        record.write_applied = True
        record.applied_effect_summary = {
            "tool": "create_skill",
            "verb": "create",
            "resource": "skills",
            "record_id": str(uuid.uuid4()),
            "name": "legacy-skill",
        }
        await db_session.commit()

        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        async for client in _client(app):
            response = await client.post(
                URL,
                json=_skill_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["duplicate_dispatch"] is True
        assert result["applied_effect_summary"]["name"] == "legacy-skill"
        assert await _skill_count(db_session, name) == 0

    @pytest.mark.asyncio
    async def test_legacy_different_tool_is_allowed_and_seeds_the_map(
        self, db_session: AsyncSession, tenant_ctx: TenantContext
    ):
        """A live legacy record whose stored tool differs lets the next write of
        a batched turn proceed; the legacy summary is adopted into the map."""
        _conv, record = await _make_paused_turn(db_session)
        record.write_applied = True
        record.applied_effect_summary = {
            "tool": "create_sop",
            "verb": "create",
            "resource": "sops",
            "record_id": str(uuid.uuid4()),
            "name": "legacy-sop",
        }
        await db_session.commit()

        app = _build_app(db_session, tenant_ctx)
        name = f"skill-{uuid.uuid4().hex[:8]}"
        async for client in _client(app):
            response = await client.post(
                URL,
                json=_skill_payload(name),
                headers={"X-Turn-Idempotency-Key": record.idempotency_key},
            )

        assert response.status_code == 200, response.text
        assert "duplicate_dispatch" not in response.json()["result"]
        assert await _skill_count(db_session, name) == 1

        refreshed = await _refresh(db_session, record)
        effects = refreshed.applied_effect_summary["effects"]
        # Legacy create_sop adopted + the new create_skill.
        assert len(effects) == 2
        assert {entry["tool"] for entry in effects.values()} == {
            "create_sop",
            "create_skill",
        }
        assert any(key.startswith("legacy:") for key in effects)
