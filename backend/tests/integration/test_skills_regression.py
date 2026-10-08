"""Skills revert-regression tests.

The decision-skills feature was reverted: skills behave exactly as before.
Verifies:
- the Skill model has no ``skill_type`` discriminator column
- no ``decision_skill`` tables exist
- the skills API accepts the original payload only (a ``skill_type`` /
  ``decision`` payload is not part of the contract; unknown fields are
  ignored and never persisted)
- the skill executor has no decision routing/delegation
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_SKILLS
from app.db.models.skills import Skill
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware

SKILLS_URL = "/api/v1/skills"

SKILL_BODY = {
    "name": "regression-skill",
    "description": "Pre-change baseline skill",
    "instructions": "Do the usual thing.",
    "tool_ids": [],
}


def _bypass_jwt_middleware():
    from unittest.mock import patch as _patch

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


@pytest_asyncio.fixture
async def skills_client(test_engine):
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_permission(RT_AGENT_SKILLS, "read")] = _allow_all()
    app.dependency_overrides[require_permission(RT_AGENT_SKILLS, "create")] = _allow_all()
    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ── Model / schema level ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_model_has_no_skill_type_column(test_engine):
    async def get_columns(conn):
        return {c["name"] for c in sa_inspect(conn).get_columns("skills")}

    async with test_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda c: {col["name"] for col in sa_inspect(c).get_columns("skills")}
        )
    assert "skill_type" not in columns


@pytest.mark.asyncio
async def test_decision_skill_tables_absent(test_engine):
    async with test_engine.connect() as conn:
        names = await conn.run_sync(
            lambda c: sa_inspect(c).get_table_names()
        )
    assert [n for n in names if n.startswith("decision_skill")] == []


def test_no_source_references_to_skill_type():
    """No code references the removed discriminator."""
    import pathlib

    backend = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for pattern in ("backend/app/db/models/skills.py", "backend/app/services/skills/executor.py"):
        text = (backend.parent / pattern).read_text()
        if "skill_type" in text:
            offenders.append(pattern)
    assert offenders == []


def test_executor_has_no_decision_skill_routing():
    """Skills carry no decision SKILL TYPE after the revert.

    Decision TOOL bindings are legitimate (round 2): the executor dispatches
    virtual decision-tool bindings through DecisionExecutionEngine, exactly
    like system-tool bindings. What must NOT exist is a decision skill_type
    discriminator or decision-skill authoring payload handling.
    """
    import pathlib

    executor = (pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "skills" / "executor.py").read_text()
    assert "skill_type" not in executor
    assert "decision skill" not in executor.lower()
    # Decision tool bindings route through the decision engine (round 2).
    assert "DecisionExecutionEngine" in executor


# ── API level ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_original_contract(skills_client):
    resp = await skills_client.post(SKILLS_URL, json=SKILL_BODY)
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert body["name"] == SKILL_BODY["name"]
    assert "skill_type" not in body


@pytest.mark.asyncio
async def test_create_skill_ignores_decision_type_field(skills_client, test_engine):
    """A legacy/decision payload field must not change behavior or persist."""
    resp = await skills_client.post(
        SKILLS_URL, json={**SKILL_BODY, "name": "with-type-field", "skill_type": "decision"}
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert "skill_type" not in body

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession)
    async with SessionLocal() as session:
        row = (
            await session.execute(select(Skill).where(Skill.name == "with-type-field"))
        ).scalar_one()
    assert not hasattr(row, "skill_type")


@pytest.mark.asyncio
async def test_list_skills_has_no_decision_types(skills_client):
    resp = await skills_client.get(SKILLS_URL)
    assert resp.status_code == 200
    for skill in resp.json():
        assert "skill_type" not in skill
        assert skill.get("type") != "decision"
