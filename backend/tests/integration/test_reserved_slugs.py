"""Round-2 integration tests: reserved ``decision`` naming.

Covers:
- ``RESERVED_SERVER_NAMES`` contains "decision" (backend tool naming),
- MCP hub rejects creating a server with slug ``decision`` → HTTP 409
  (mirroring the ``system`` slug rejection),
- the virtual decision server appears in ``GET /mcp/servers``,
- saved decision tools are listed in ``GET /mcp/tools`` as
  ``decision____<name>`` (tenant-scoped),
- frontend-mirror check: the frontend toolNaming util also reserves it
  (constant contract only — asserted here against the backend constant).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import (
    RT_INTEGRATION_MCP_HUB,
    RT_SYSTEM_DECISION_TOOLS,
    RT_SYSTEM_SYSTEM_ONE,
)
from app.db.models.decision_tools import DecisionTool
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.agents.tool_naming import RESERVED_SERVER_NAMES

SERVERS_URL = "/api/v1/mcp/servers"
TOOLS_URL = "/api/v1/mcp/tools"
DECISION_TOOLS_URL = "/api/v1/decision-tools"
PROVIDERS_URL = "/api/v1/system-one/providers"

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


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


async def _clean(session: AsyncSession) -> None:
    from app.db.models.mcp_hub import McpServer
    from app.db.models.results import DecisionExecutionResult
    from app.db.models.system_one_provider_config import SystemOneProviderConfig

    await session.execute(DecisionExecutionResult.__table__.delete())
    await session.execute(DecisionTool.__table__.delete())
    await session.execute(SystemOneProviderConfig.__table__.delete())
    await session.execute(McpServer.__table__.delete())
    await session.commit()


@pytest_asyncio.fixture
async def hub_client(test_engine):
    """Client with MCP hub + decision tool permissions and the test-only
    ``X-Test-Tenant`` tenant context (mirrors the decision tools fixture)."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        await _clean(session)

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[
        require_permission(RT_INTEGRATION_MCP_HUB, "read")
    ] = _allow_all()
    app.dependency_overrides[
        require_permission(RT_INTEGRATION_MCP_HUB, "create")
    ] = _allow_all()
    for action in ("read", "create", "update", "delete"):
        app.dependency_overrides[
            require_permission(RT_SYSTEM_DECISION_TOOLS, action)
        ] = _allow_all()
    app.dependency_overrides[
        require_permission(RT_SYSTEM_SYSTEM_ONE, "read")
    ] = _allow_all()
    app.dependency_overrides[
        require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")
    ] = _allow_all()

    import app.api.v1.decision_tools as dt_api
    import app.api.v1.system_one as so_api
    import app.core.tenant_context as tc_module
    from app.core.tenant_context import TenantContext, get_tenant_context as real_get_ctx

    # mcp_hub imports get_tenant_context locally inside its routes, so patch
    # the source module; dt_api/so_api imported it at module scope.
    def fake_get_tenant_context(request):
        raw = request.headers.get("x-test-tenant")
        if not raw:
            return real_get_ctx(request)
        return TenantContext(
            tenant_id=uuid.UUID(raw), slug=f"t-{raw[:8]}", name=f"tenant-{raw[:8]}"
        )

    tc_module.get_tenant_context = fake_get_tenant_context
    dt_api.get_tenant_context = fake_get_tenant_context
    so_api.get_tenant_context = fake_get_tenant_context

    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    tc_module.get_tenant_context = real_get_ctx
    dt_api.get_tenant_context = real_get_ctx
    so_api.get_tenant_context = real_get_ctx


@pytest_asyncio.fixture
async def decision_tool_in_tenant_a(hub_client, test_engine):
    """An enabled provider + one decision tool in tenant A (READY — both
    data types attached, per the readiness gate)."""
    resp = await hub_client.post(
        PROVIDERS_URL,
        json={
            "provider_type": "typesafe",
            "display_name": "TypeSafe Jev (reserved slug tests)",
            "default_model": "jev-latest",
            "api_key": "sk-reserved-slug-test-key",
            "enabled": True,
        },
        headers={"x-test-tenant": str(TENANT_A)},
    )
    assert resp.status_code == 201, resp.text

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.db.models.agent_data_type import AgentDataType

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        suffix = uuid.uuid4().hex[:6]
        input_type = AgentDataType(
            tenant_id=TENANT_A,
            name=f"tool_a-input-{suffix}",
            slug=f"tool_a-input-{suffix}",
            fields=[{"name": "situation", "type": "string"}],
        )
        output_type = AgentDataType(
            tenant_id=TENANT_A,
            name=f"tool_a-output-{suffix}",
            slug=f"tool_a-output-{suffix}",
            fields=[{"name": "decision", "type": "string"}],
        )
        session.add_all([input_type, output_type])
        await session.commit()
        input_id, output_id = str(input_type.id), str(output_type.id)

    created = await hub_client.post(
        DECISION_TOOLS_URL,
        json={
            "name": "tool_a",
            "purpose": "Reserved-slug MCP exposure test tool",
            "input_data_type_id": input_id,
            "output_data_type_id": output_id,
            "questions": [
                {
                    "question_key": "approve",
                    "question_type": "choice",
                    "instructions": "Approve?",
                    "criteria_options": {"yes": "y", "no": "n"},
                    "ordering": 0,
                },
            ],
        },
        headers={"x-test-tenant": str(TENANT_A)},
    )
    assert created.status_code == 201, created.text
    return created.json()


# ── RESERVED_SERVER_NAMES constant ────────────────────────────────────────


class TestReservedServerNamesConstant:
    def test_decision_is_reserved(self):
        assert "decision" in RESERVED_SERVER_NAMES

    def test_system_is_still_reserved(self):
        assert "system" in RESERVED_SERVER_NAMES


# ── MCP hub slug rejection ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestReservedSlugRejection:
    @pytest.mark.parametrize("slug", ["decision", "system"])
    async def test_create_server_with_reserved_slug_409(self, hub_client, slug):
        resp = await hub_client.post(
            SERVERS_URL,
            json={
                "name": slug,
                "slug": slug,
                "base_url": "http://localhost:9999/mcp",
            },
        )
        assert resp.status_code == 409, resp.text
        assert "reserved" in resp.text

    async def test_non_reserved_slug_still_creatable(self, hub_client):
        resp = await hub_client.post(
            SERVERS_URL,
            json={
                "name": "weather",
                "slug": "weather",
                "base_url": "http://localhost:9999/mcp",
            },
        )
        assert resp.status_code == 201, resp.text


# ── Virtual decision server + tenant-scoped tool listing ──────────────────


@pytest.mark.asyncio
class TestVirtualDecisionServerAndTools:
    async def test_decision_server_in_mcp_servers_listing(self, hub_client):
        resp = await hub_client.get(SERVERS_URL)
        assert resp.status_code == 200
        slugs = [s["slug"] for s in resp.json()]
        assert "decision" in slugs
        assert "system" in slugs

    async def test_decision_tools_listed_as_decision____in_mcp_tools(
        self, hub_client, decision_tool_in_tenant_a
    ):
        resp = await hub_client.get(
            TOOLS_URL, headers={"x-test-tenant": str(TENANT_A)}
        )
        assert resp.status_code == 200
        tools = resp.json()
        names = [t["name"] for t in tools]
        assert "decision____tool_a" in names
        entry = next(t for t in tools if t["name"] == "decision____tool_a")
        assert entry["server_slug"] == "decision"
        # the auto-generated description is what MCP consumers see
        assert entry["description"] == decision_tool_in_tenant_a["description"]
        # structured input schema derived from the definition
        assert entry["input_schema"] is None or isinstance(entry["input_schema"], dict)

    async def test_mcp_tools_listing_is_tenant_scoped(
        self, hub_client, decision_tool_in_tenant_a
    ):
        resp_b = await hub_client.get(
            TOOLS_URL, headers={"x-test-tenant": str(TENANT_B)}
        )
        assert resp_b.status_code == 200
        names_b = [t["name"] for t in resp_b.json()]
        assert "decision____tool_a" not in names_b
