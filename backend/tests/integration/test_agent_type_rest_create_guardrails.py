"""REST agent-type create persists the submitted guardrail policy.

Regression guard for `remove-delegation-depth-cap`: `POST /agents/types` must
store the guardrail values supplied at creation — in particular Max Delegation
Depth, whose configured value is the sole delegation depth limit. Schema-level
acceptance alone is insufficient: a value silently replaced by the column
default on create would contradict the configuration screen and the runtime
limit.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT, RT_AGENT_SKILLS
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


def _bypass_auth():
    """Patch JWTAuthMiddleware so every request carries an admin identity."""

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


@pytest_asyncio.fixture
async def client(test_engine) -> AsyncClient:
    """App client with agent / skill permissions overridden for the test DB."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    for action in ("read", "create", "update", "delete"):
        app.dependency_overrides[require_permission(RT_AGENT, action)] = _allow_all()
        app.dependency_overrides[require_permission(RT_AGENT_SKILLS, action)] = _allow_all()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        yield http_client


async def _create_bindable_role(client: AsyncClient, suffix: str) -> tuple[str, str]:
    """Create a skill + role so the agent-type binding rule can be satisfied."""
    skill_resp = await client.post(
        "/api/v1/skills",
        json={"name": f"e2e-depth-skill-{suffix}", "tool_ids": []},
    )
    assert skill_resp.status_code == 201, skill_resp.text
    skill_id = skill_resp.json()["id"]

    role_resp = await client.post(
        "/api/v1/agents/roles",
        json={
            "name": f"e2e-depth-role-{suffix}",
            "skill_ids": [skill_id],
            "sop_ids": [],
        },
    )
    assert role_resp.status_code == 201, role_resp.text
    return skill_id, role_resp.json()["id"]


@pytest.mark.asyncio
async def test_rest_create_persists_configured_delegation_depth(
    client: AsyncClient,
) -> None:
    """POST /agents/types stores depth 64 (above the former 32 ceiling) unchanged."""
    suffix = uuid.uuid4().hex[:8]

    with _bypass_auth():
        skill_id, role_id = await _create_bindable_role(client, suffix)

        created = await client.post(
            "/api/v1/agents/types",
            json={
                "name": f"e2e-depth-create-{suffix}",
                "role_id": role_id,
                "skill_bindings": [{"skill_id": skill_id, "order": 1}],
                "guardrail_max_iterations": 24,
                "guardrail_max_delegation_depth": 64,
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["guardrail_max_delegation_depth"] == 64, (
            "Configured Max Delegation Depth must be persisted on create, "
            "not replaced by the column default"
        )
        # Other submitted guardrails are persisted too (same construction site).
        assert body["guardrail_max_iterations"] == 24

        # Fresh read — proves the stored row, not an echoed request value.
        read = await client.get(f"/api/v1/agents/types/{body['id']}")
        assert read.status_code == 200, read.text
        assert read.json()["guardrail_max_delegation_depth"] == 64


@pytest.mark.asyncio
async def test_rest_update_accepts_large_depth_and_rejects_negative(
    client: AsyncClient,
) -> None:
    """The update path has no ceiling and still enforces the non-negative floor."""
    suffix = uuid.uuid4().hex[:8]

    with _bypass_auth():
        skill_id, role_id = await _create_bindable_role(client, suffix)

        created = await client.post(
            "/api/v1/agents/types",
            json={
                "name": f"e2e-depth-update-{suffix}",
                "role_id": role_id,
                "skill_bindings": [{"skill_id": skill_id, "order": 1}],
            },
        )
        assert created.status_code == 201, created.text
        agent_type_id = created.json()["id"]

        updated = await client.put(
            f"/api/v1/agents/types/{agent_type_id}",
            json={"guardrail_max_delegation_depth": 1000},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["guardrail_max_delegation_depth"] == 1000

        negative = await client.put(
            f"/api/v1/agents/types/{agent_type_id}",
            json={"guardrail_max_delegation_depth": -1},
        )
        assert negative.status_code == 422, negative.text
        assert "guardrail_max_delegation_depth" in negative.text

        # The rejected write left the stored value untouched.
        read = await client.get(f"/api/v1/agents/types/{agent_type_id}")
        assert read.json()["guardrail_max_delegation_depth"] == 1000
