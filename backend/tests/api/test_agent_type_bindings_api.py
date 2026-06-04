"""Integration tests for Agent Type SOP/Skill binding CRUD and validation.

Tests the POST /api/v1/agents/types, PUT /api/v1/agents/types/{id},
GET /api/v1/agents/types/{id}, GET /api/v1/agents/types, and
DELETE /api/v1/agents/types/{id} endpoints with sop_bindings and
skill_bindings in the request/response cycle.

Uses a real SQLite in-memory database via the ``db_session`` fixture and
creates the FastAPI app manually for each test.  Auth is bypassed via
``_bypass_auth()`` and ``_mock_permission_allow()``.

The PlatformUser table must have a row matching the sub claim injected by
``_bypass_auth()`` (``admin-sub``) otherwise the ``require_permission``
dependency raises 403.  Instead of mocking the dependency, we seed the row
in a helper so the integration test exercises the real permission middleware.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentRole,
    AgentRoleSOP,
    AgentRoleSkill,
    AgentType,
    AgentTypeSopBinding,
    AgentTypeSkillBinding,
)
from app.db.models.platform_user import PlatformUser
from app.db.models.skills import Skill, Sop
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


# ── Auth / Permission helpers ──────────────────────────────────────────────────


def _bypass_auth():
    """Patch JWTAuthMiddleware so every request carries a valid admin identity."""

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        request.state.claims = {"platform_user_id": str(uuid.uuid4())}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_allow():
    """Patch PermissionEngine.authorize to unconditionally allow all actions."""
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_app(db_session: AsyncSession):
    """Create a FastAPI app that uses *db_session* for all DB access."""
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


async def _seed_platform_user(db: AsyncSession) -> PlatformUser:
    """Create a PlatformUser row for the ``admin-sub`` identity used by ``_bypass_auth``.

    This is required because ``require_permission`` (in ``app/api/deps.py``)
    queries ``PlatformUser`` by the ``sub`` claim and raises 403 if no row exists.

    Uses get-or-create so it is safe to call from multiple tests sharing the
    same session-scoped in-memory database.
    """
    from sqlalchemy import select

    existing = await db.execute(select(PlatformUser).where(PlatformUser.sub == "admin-sub"))
    user = existing.scalar_one_or_none()
    if user is not None:
        return user

    user = PlatformUser(
        id=uuid.uuid4(),
        sub="admin-sub",
        email="admin@test.local",
        display_name="Admin Tester",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(user)
    return user


def _patch_side_effects():
    """Return context managers that silence recursion validation & plan generation.

    These services make real DB/LLM calls that we don't want in integration tests.
    """
    return (
        patch(
            "app.api.v1.agents.get_recursion_validation_service",
            return_value=SimpleNamespace(validate_agent_type=AsyncMock()),
        ),
        patch(
            "app.api.v1.agents._plan_generation_service.generate_plan",
            AsyncMock(),
        ),
    )


def _unique_name(prefix: str = "sop") -> str:
    """Return a unique name for a SOP/Skill/AgentType (avoids UNIQUE violations)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def _seed_role_with_sop(
    db: AsyncSession,
    skill_name: str | None = None,
) -> tuple[AgentRole, Sop, Skill | None]:
    """Create a role with one SOP and optionally one Skill.

    Returns (role, sop, skill_or_None).
    """
    role = AgentRole(name=_unique_name("role"), description="Test role")
    db.add(role)
    await db.flush()

    sop = Sop(
        name=_unique_name("sop"),
        description="Test SOP description",
        instructions="Do the thing.",
    )
    db.add(sop)
    await db.flush()

    db.add(AgentRoleSOP(role_id=role.id, sop_id=sop.id))
    await db.flush()

    skill = None
    if skill_name:
        skill = Skill(name=_unique_name("skill"), description="Test skill description")
        db.add(skill)
        await db.flush()
        db.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
        await db.flush()

    await db.commit()
    return role, sop, skill


async def _seed_agent_type_with_binding(
    db: AsyncSession,
) -> tuple[AgentType, Sop, AgentRole]:
    """Create a full AgentType with one SOP binding ready for GET/DELETE tests.

    Returns (agent_type, sop, role).
    """
    role, sop, _ = await _seed_role_with_sop(db)
    agent_type = AgentType(
        name=_unique_name("agent"),
        model_id="gpt-4o-mini",
        input_type=AgentInputType.conversation,
        output_type=AgentOutputType.auto,
        role_id=role.id,
    )
    db.add(agent_type)
    await db.flush()

    binding = AgentTypeSopBinding(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        sop_id=sop.id,
        order=0,
    )
    db.add(binding)
    await db.flush()
    await db.commit()
    # Refresh so relationships are available
    await db.refresh(agent_type)
    return agent_type, sop, role


async def _setup_db_for_create(db: AsyncSession) -> tuple[AgentRole, Sop, Skill | None]:
    """Seed PlatformUser + role + SOP + Skill.  Commit everything.

    Returns (role, sop, skill_or_None).
    """
    await _seed_platform_user(db)
    role, sop, skill = await _seed_role_with_sop(db, skill_name="a-skill")
    return role, sop, skill


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestCreateAgentTypeWithBindings:
    """POST /api/v1/agents/types — create agent type with sop/skill bindings."""

    @pytest.mark.asyncio
    async def test_create_with_sop_and_skill_bindings(self, db_session: AsyncSession):
        """2.1 — Create AgentType with SOP + Skill bindings → 201 with bindings."""
        role, sop, skill = await _setup_db_for_create(db_session)
        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                    "role_id": str(role.id),
                    "sop_bindings": [{"sop_id": str(sop.id), "order": 0}],
                    "skill_bindings": [{"skill_id": str(skill.id), "order": 0}],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data["sop_bindings"]) == 1
        assert data["sop_bindings"][0]["sop_id"] == str(sop.id)
        assert data["sop_bindings"][0]["order"] == 0
        assert data["sop_bindings"][0]["sop_name"] == sop.name
        assert "id" in data["sop_bindings"][0]
        assert "created_at" in data["sop_bindings"][0]

        assert len(data["skill_bindings"]) == 1
        assert data["skill_bindings"][0]["skill_id"] == str(skill.id)
        assert data["skill_bindings"][0]["order"] == 0
        assert data["skill_bindings"][0]["skill_name"] == skill.name

    @pytest.mark.asyncio
    async def test_create_with_skill_bindings_only(self, db_session: AsyncSession):
        """2.2 — Create AgentType with skill bindings only (no SOP bindings) → 201."""
        await _seed_platform_user(db_session)
        role = AgentRole(name=_unique_name("role"), description="Test role")
        db_session.add(role)
        await db_session.flush()

        skill = Skill(name=_unique_name("skill"), description="A skill without SOP")
        db_session.add(skill)
        await db_session.flush()

        db_session.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                    "role_id": str(role.id),
                    "sop_bindings": [],
                    "skill_bindings": [{"skill_id": str(skill.id), "order": 0}],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["sop_bindings"] == []
        assert len(data["skill_bindings"]) == 1
        assert data["skill_bindings"][0]["skill_id"] == str(skill.id)

    @pytest.mark.asyncio
    async def test_create_conversation_without_bindings(self, db_session: AsyncSession):
        """2.3 — Create AgentType with conversation input_type and no bindings → 201."""
        await _seed_platform_user(db_session)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["sop_bindings"] == []
        assert data["skill_bindings"] == []

    @pytest.mark.asyncio
    async def test_create_none_input_without_sop_bindings_fails(self, db_session: AsyncSession):
        """2.4 — Create AgentType with input_type=none and no sop_bindings → 400."""
        await _seed_platform_user(db_session)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "none",
                    "output_type": "auto",
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", "")
        assert "SOP binding" in detail, f"Expected SOP binding error, got: {detail!r}"

    @pytest.mark.asyncio
    async def test_create_none_input_with_explicit_empty_list_fails(self, db_session: AsyncSession):
        """Explicit empty sop_bindings for none input_type also fails."""
        await _seed_platform_user(db_session)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "none",
                    "output_type": "auto",
                    "sop_bindings": [],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_none_input_with_sop_bindings_succeeds(self, db_session: AsyncSession):
        """Create with none input_type and valid sop_bindings → 201."""
        role, sop, _ = await _setup_db_for_create(db_session)
        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "none",
                    "output_type": "auto",
                    "role_id": str(role.id),
                    "sop_bindings": [{"sop_id": str(sop.id), "order": 0}],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data["sop_bindings"]) == 1


class TestUpdateAgentTypeBindings:
    """PUT /api/v1/agents/types/{id} — update agent type bindings."""

    @pytest.mark.asyncio
    async def test_update_bindings(self, db_session: AsyncSession):
        """2.5 — Update AgentType bindings via PUT → response reflects new bindings."""
        await _seed_platform_user(db_session)
        role, sop1, _ = await _seed_role_with_sop(db_session)
        # Add a second SOP for the update
        sop2 = Sop(name=_unique_name("sop"), description="Second SOP")
        db_session.add(sop2)
        await db_session.flush()
        db_session.add(AgentRoleSOP(role_id=role.id, sop_id=sop2.id))
        await db_session.commit()

        # Create agent type with first SOP binding
        agent_type = AgentType(
            name=_unique_name("agent"),
            model_id="gpt-4o-mini",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
            role_id=role.id,
        )
        db_session.add(agent_type)
        await db_session.flush()

        binding1 = AgentTypeSopBinding(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            sop_id=sop1.id,
            order=0,
        )
        db_session.add(binding1)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Update: switch to sop2 only
                resp = await client.put(
                    f"/api/v1/agents/types/{agent_type.id}",
                    json={
                        "sop_bindings": [{"sop_id": str(sop2.id), "order": 0}],
                    },
                )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data["sop_bindings"]) == 1
        assert data["sop_bindings"][0]["sop_id"] == str(sop2.id)

    @pytest.mark.asyncio
    async def test_update_bindings_clears_old(self, db_session: AsyncSession):
        """PUT with sop_bindings=[] clears all bindings."""
        await _seed_platform_user(db_session)
        agent_type, sop, role = await _seed_agent_type_with_binding(db_session)
        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.put(
                    f"/api/v1/agents/types/{agent_type.id}",
                    json={
                        "sop_bindings": [],
                        "skill_bindings": [],
                    },
                )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["sop_bindings"] == []
        assert data["skill_bindings"] == []


class TestGetAgentTypeWithBindings:
    """GET /api/v1/agents/types — read bindings in single and list responses."""

    @pytest.mark.asyncio
    async def test_get_agent_type_includes_bindings(self, db_session: AsyncSession):
        """2.6 — GET /api/v1/agents/types/{id} includes bindings in response."""
        await _seed_platform_user(db_session)
        agent_type, sop, _ = await _seed_agent_type_with_binding(db_session)
        app = _build_app(db_session)

        with _bypass_auth(), _mock_permission_allow():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/v1/agents/types/{agent_type.id}")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data["sop_bindings"]) == 1
        assert data["sop_bindings"][0]["sop_id"] == str(sop.id)
        assert data["sop_bindings"][0]["sop_name"] == sop.name
        assert data["sop_bindings"][0]["order"] == 0
        assert "id" in data["sop_bindings"][0]
        assert "created_at" in data["sop_bindings"][0]

    @pytest.mark.asyncio
    async def test_list_agent_types_includes_bindings(self, db_session: AsyncSession):
        """2.7 — GET /api/v1/agents/types includes bindings in list response."""
        await _seed_platform_user(db_session)
        agent_type, sop, _ = await _seed_agent_type_with_binding(db_session)
        app = _build_app(db_session)

        with _bypass_auth(), _mock_permission_allow():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/agents/types")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        # Find our agent in the list
        matching = [at for at in data if at["id"] == str(agent_type.id)]
        assert len(matching) == 1, f"Agent type {agent_type.id} not found in list"
        item = matching[0]
        assert len(item["sop_bindings"]) == 1
        assert item["sop_bindings"][0]["sop_id"] == str(sop.id)

    @pytest.mark.asyncio
    async def test_get_agent_type_no_bindings(self, db_session: AsyncSession):
        """GET agent type with no bindings returns empty lists."""
        await _seed_platform_user(db_session)
        agent_type = AgentType(
            name=_unique_name("agent"),
            model_id="gpt-4o-mini",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
        )
        db_session.add(agent_type)
        await db_session.commit()

        app = _build_app(db_session)
        with _bypass_auth(), _mock_permission_allow():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/v1/agents/types/{agent_type.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sop_bindings"] == []
        assert data["skill_bindings"] == []


class TestDeleteAgentTypeBindingsCascade:
    """DELETE /api/v1/agents/types/{id} — cascades binding rows."""

    @pytest.mark.asyncio
    async def test_delete_cascades_bindings(self, db_session: AsyncSession):
        """2.8 — Delete AgentType removes its binding rows."""
        await _seed_platform_user(db_session)
        agent_type, sop, _ = await _seed_agent_type_with_binding(db_session)
        at_id = agent_type.id
        app = _build_app(db_session)

        with _bypass_auth(), _mock_permission_allow():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.delete(f"/api/v1/agents/types/{at_id}")

        assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"

        # Verify the AgentType is gone (cascade will have removed bindings in same session)
        from sqlalchemy import select as sa_select

        agent_check = await db_session.execute(
            sa_select(AgentType).where(AgentType.id == at_id)
        )
        assert agent_check.scalar_one_or_none() is None, "AgentType should be deleted"

        binding_check = await db_session.execute(
            sa_select(AgentTypeSopBinding).where(
                AgentTypeSopBinding.agent_type_id == at_id
            )
        )
        assert binding_check.scalars().all() == [], (
            "SOP bindings should have been cascade-deleted"
        )


class TestValidationErrors:
    """Validation: role-access checks for bindings."""

    @pytest.mark.asyncio
    async def test_reject_sop_not_in_role(self, db_session: AsyncSession):
        """2.9 — Create with SOP not in role permissions → 422."""
        await _seed_platform_user(db_session)
        # Create a role with a limited set of SOPs
        role = AgentRole(name=_unique_name("role"), description="Limited role")
        db_session.add(role)
        await db_session.flush()

        allowed_sop = Sop(name=_unique_name("sop"), description="This SOP is in the role")
        db_session.add(allowed_sop)
        await db_session.flush()
        db_session.add(AgentRoleSOP(role_id=role.id, sop_id=allowed_sop.id))
        await db_session.flush()

        forbidden_sop = Sop(
            name=_unique_name("sop"),
            description="This SOP is NOT in the role",
        )
        db_session.add(forbidden_sop)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                    "role_id": str(role.id),
                    "sop_bindings": [{"sop_id": str(forbidden_sop.id), "order": 0}],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", {})
        assert detail.get("error") == "binding_validation_failed"
        messages = detail.get("messages", [])
        assert any("not accessible" in m and "SOP" in m for m in messages), (
            f"Expected SOP access error, got: {messages}"
        )

    @pytest.mark.asyncio
    async def test_reject_skill_not_in_role(self, db_session: AsyncSession):
        """Create with Skill not in role permissions → 422."""
        await _seed_platform_user(db_session)
        role = AgentRole(name=_unique_name("role"), description="Limited role")
        db_session.add(role)
        await db_session.flush()

        allowed_sop = Sop(name=_unique_name("sop"), description="SOP in role")
        db_session.add(allowed_sop)
        await db_session.flush()
        db_session.add(AgentRoleSOP(role_id=role.id, sop_id=allowed_sop.id))
        await db_session.flush()

        forbidden_skill = Skill(
            name=_unique_name("skill"),
            description="This skill is not assigned to the role",
        )
        db_session.add(forbidden_skill)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                    "role_id": str(role.id),
                    "skill_bindings": [{"skill_id": str(forbidden_skill.id), "order": 0}],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", {})
        assert detail.get("error") == "binding_validation_failed"
        messages = detail.get("messages", [])
        assert any("not accessible" in m and "Skill" in m for m in messages), (
            f"Expected Skill access error, got: {messages}"
        )

    @pytest.mark.asyncio
    async def test_reject_duplicate_sop_binding(self, db_session: AsyncSession):
        """Bind the same SOP twice in one request → 422."""
        await _seed_platform_user(db_session)
        role, sop, _ = await _seed_role_with_sop(db_session)
        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                    "role_id": str(role.id),
                    "sop_bindings": [
                        {"sop_id": str(sop.id), "order": 0},
                        {"sop_id": str(sop.id), "order": 1},
                    ],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", {})
        messages = detail.get("messages", [])
        assert any("Duplicate" in m for m in messages), f"Expected duplicate error, got: {messages}"

    @pytest.mark.asyncio
    async def test_reject_binding_without_role(self, db_session: AsyncSession):
        """Bindings require a role to be assigned → 422."""
        await _seed_platform_user(db_session)
        sop = Sop(name=_unique_name("sop"), description="No role assigned")
        db_session.add(sop)
        await db_session.commit()

        app = _build_app(db_session)

        patch1, patch2 = _patch_side_effects()
        with _bypass_auth(), _mock_permission_allow(), patch1, patch2:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "name": _unique_name("agent"),
                    "model_id": "gpt-4o-mini",
                    "input_type": "conversation",
                    "output_type": "auto",
                    "sop_bindings": [{"sop_id": str(sop.id), "order": 0}],
                }
                resp = await client.post("/api/v1/agents/types", json=payload)

        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
        detail = resp.json().get("detail", {})
        messages = detail.get("messages", [])
        assert any("role" in m.lower() for m in messages), (
            f"Expected role-related error, got: {messages}"
        )
