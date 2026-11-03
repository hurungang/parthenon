"""Assistant meta tools — progressive tool disclosure (Enhancement 1).

Verifies the O(1)-context contract end to end against the real CC handlers:

- ``invoke_management_tool`` dispatches any registered management tool
  through the existing ``management_tools._dispatch`` (in-process), with
  permission parity re-enforced per invocation (allow → success end to end;
  deny → structured 403 and no write);
- delete-shaped requests are declined (no delete verb in the registry);
- unknown target tools return a clear structured 404;
- ``get_management_tool_schema`` returns one tool's exact OpenAI schema;
- ``list_management_tools`` returns the cheap catalog (name + description +
  permission requirement) and never includes the meta tools themselves;
- ``search_assistant_knowledge`` returns relevant domain rules
  (Enhancement 2) without touching tenant data.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.session import get_db
from app.main import create_app
from app.services.agents.system_tool_registry import SystemToolRegistry


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def allow_all(monkeypatch: pytest.MonkeyPatch):
    """Make the permission gate a no-op (user authorized for everything)."""
    from app.api.v1.internal import management_tools

    async def _allow(db, user_sub, resource_type, action, tenant_id):
        return None

    monkeypatch.setattr(management_tools, "_authorize", _allow)


@pytest.fixture
def deny_all(monkeypatch: pytest.MonkeyPatch):
    """Make the permission gate always deny (403)."""
    from fastapi import HTTPException

    from app.api.v1.internal import management_tools

    async def _deny(db, user_sub, resource_type, action, tenant_id):
        raise HTTPException(status_code=403, detail="permission denied")

    monkeypatch.setattr(management_tools, "_authorize", _deny)


async def _post_meta(client: AsyncClient, meta_tool: str, tool_args: dict) -> dict:
    response = await client.post(
        f"/api/v1/internal/management-tools/{meta_tool}",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": tool_args},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


# ── Wrapper dispatch: permitted action succeeds end to end ───────────────────


@pytest.mark.asyncio
async def test_invoke_wrapper_creates_and_lists_skills(authed_client, allow_all) -> None:
    """create_skill through the wrapper performs the real create; the new
    skill is visible via list_skills through the wrapper."""
    created = await _post_meta(
        authed_client,
        "invoke_management_tool",
        {
            "tool_name": "create_skill",
            "args": {"name": "wrapper-skill", "data": {"description": "via wrapper"}},
        },
    )
    assert created["record"]["name"] == "wrapper-skill"
    assert created["record"]["description"] == "via wrapper"
    skill_id = created["record"]["id"]

    listed = await _post_meta(
        authed_client,
        "invoke_management_tool",
        {"tool_name": "list_skills", "args": {}},
    )
    names = [r["name"] for r in listed["records"]]
    assert "wrapper-skill" in names

    fetched = await _post_meta(
        authed_client,
        "invoke_management_tool",
        {"tool_name": "get_skill", "args": {"id": skill_id}},
    )
    assert fetched["record"]["id"] == skill_id


# ── Wrapper dispatch: permission parity enforced per invocation ──────────────


@pytest.mark.asyncio
async def test_invoke_wrapper_denied_action_is_structured_403(
    authed_client, deny_all
) -> None:
    """A permission-denied wrapped invocation returns HTTP 403 — the same
    parity gate the per-tool endpoint enforces."""
    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {"tool_name": "create_skill", "args": {"name": "nope"}},
        },
    )
    assert response.status_code == 403


# ── Wrapper dispatch: delete-shaped and unknown requests declined ────────────


@pytest.mark.asyncio
async def test_invoke_wrapper_declines_delete_shaped_request(authed_client, allow_all) -> None:
    """No delete verb exists in the registry — a delete-shaped request is
    declined (404), never dispatched."""
    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {"tool_name": "delete_skill", "args": {"id": str(uuid.uuid4())}},
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invoke_wrapper_unknown_tool_is_clear_404(authed_client, allow_all) -> None:
    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {"tool_name": "not_a_real_tool", "args": {}},
        },
    )
    assert response.status_code == 404
    assert "Unknown management tool" in response.text
    assert "list_management_tools" in response.text  # actionable hint


# ── Schema-on-demand and cheap catalog ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_management_tool_schema_returns_full_schema(authed_client) -> None:
    result = await _post_meta(
        authed_client,
        "get_management_tool_schema",
        {"tool_name": "create_skill"},
    )
    schema = result["schema"]
    assert schema["function"]["name"] == "create_skill"
    assert "name" in schema["function"]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_list_management_tools_returns_catalog_without_meta(authed_client) -> None:
    result = await _post_meta(authed_client, "list_management_tools", {})
    tools = result["tools"]
    names = {t["name"] for t in tools}
    assert names == set(SystemToolRegistry.get_management_tool_names())
    assert not (names & SystemToolRegistry.get_meta_tool_names()), (
        "meta tools must never appear in the management catalog"
    )
    for entry in tools:
        assert entry["description"]
        assert ":" in entry["requires_permission"]


# ── Knowledge search (Enhancement 2) via the system tool ─────────────────────


@pytest.mark.asyncio
async def test_search_knowledge_returns_skills_first_rule(authed_client) -> None:
    result = await _post_meta(
        authed_client,
        "search_assistant_knowledge",
        {"query": "how do I attach MCP tools to an agent type"},
    )
    topics = [r["topic"] for r in result["results"]]
    assert topics, "expected at least one rule for MCP-tools-on-agent-type query"
    combined = " ".join(r["rule_text"] for r in result["results"])
    assert "never" in combined.lower() and "raw mcp" in combined.lower(), (
        "must surface the 'agent types bind skills/SOPs, never raw MCP tools' rule"
    )


@pytest.mark.asyncio
async def test_search_knowledge_returns_model_config_rule(authed_client) -> None:
    result = await _post_meta(
        authed_client,
        "search_assistant_knowledge",
        {"query": "the model I want is not available for my agent"},
    )
    combined = " ".join(r["rule_text"] for r in result["results"])
    assert "enabled" in combined.lower() and "model config" in combined.lower(), (
        "must surface the per-tenant Model Config enabled-models rule"
    )


@pytest.mark.asyncio
async def test_search_knowledge_requires_query(authed_client) -> None:
    response = await authed_client.post(
        "/api/v1/internal/management-tools/search_assistant_knowledge",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": {}},
    )
    assert response.status_code == 400


# ── Registry contract: meta tools carry no parity ────────────────────────────


def test_meta_tools_are_not_parity_tools() -> None:
    """Meta tools must never enter the permission parity map (the map drives
    the resolve endpoint and the REST-parity structural tests)."""
    parity = SystemToolRegistry.get_parity_map()
    for meta in SystemToolRegistry.get_meta_tool_names():
        assert meta not in parity
        assert not SystemToolRegistry.is_management_tool(meta)
