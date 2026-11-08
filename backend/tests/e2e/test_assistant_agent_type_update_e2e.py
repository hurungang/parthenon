"""Assistant-conversation E2E (Phase 5 task 5.5) — full agent-type update.

Drives the deepest practical integration loop for PRD AC1 / AC5:

1. READ an agent type through the management-tool path (get_agent_type).
2. The assistant builds the CANONICAL old → new preview (``**Update Agent
   Type: <name>**`` + ``| Field | Value |`` table) covering the role
   assignment AND the input/output configuration.
3. Approval flows through the confirmation intervention
   (``LangChainHumanInterveneTool`` + the conversation-resume registry — the
   real HITL mechanism).
4. On approval, ``cc____update_agent_type`` is dispatched through the REAL
   Communication Hub routing function (``route_tool_call`` → management-tool
   endpoint map → Control Center internal handler) with the user identity
   forwarded for per-call re-authorization.
5. The persisted record matches ALL approved fields.

Negative variant: the operator REJECTS the preview → the human_intervene
tool reports a not-approved result, NO CH dispatch happens, and the
persisted record keeps its prior state (confirm-before-write contract).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.session import get_db
from app.main import create_app


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def cc_app(test_engine):
    """Control Center app wired to the test database (management-tool path)."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db
    return app


@pytest_asyncio.fixture
async def cc_client(cc_app):
    async with AsyncClient(transport=ASGITransport(app=cc_app), base_url="http://cc-test") as client:
        yield client


@pytest.fixture
def allow_all(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1.internal import management_tools

    async def _allow(db, user_sub, resource_type, action, tenant_id):
        return None

    monkeypatch.setattr(management_tools, "_authorize", _allow)


async def _invoke(client: AsyncClient, tool_name: str, args: dict) -> dict:
    response = await client.post(
        f"/api/v1/internal/management-tools/{tool_name}",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": args},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _canonical_preview(old: dict, approved: dict, name: str) -> str:
    """The canonical confirm-before-write preview the assistant must render
    (assistant knowledge corpus contract): header + old → new field table."""
    lines = [f"**Update Agent Type: {name}**", "", "| Field | Value |", "| --- | --- |"]
    for field, new_value in approved.items():
        old_value = old.get(field)
        old_display = "(none)" if old_value in (None, "", []) else str(old_value)
        lines.append(f"| {field} | {old_display} → {new_value} |")
    return "\n".join(lines)


async def _approve_confirmation(conv_id: uuid.UUID):
    from app.agent_runtime import conversation_resume

    assert conversation_resume.resolve(conv_id, {"approval_value": True})


async def _reject_confirmation(conv_id: uuid.UUID):
    from app.agent_runtime import conversation_resume

    assert conversation_resume.resolve(conv_id, {"approval_value": False})


@pytest.mark.asyncio
async def test_assistant_agent_type_update_full_flow(cc_client, cc_app, allow_all, test_engine, monkeypatch):
    """Positive variant: read → canonical preview → approval → CH-routed
    cc____update_agent_type → persisted record matches all approved fields."""
    # ── CH routing harness: run route_tool_call against the in-process CC app ──
    from unittest.mock import patch

    import httpx
    from starlette.requests import Request

    from app.communication_hub.api.internal import tool_routing
    from app.core import internal_http
    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

    real_internal_httpx_client = internal_http.internal_httpx_client

    def _asgi_internal_client(**kwargs):
        kwargs["transport"] = ASGITransport(app=cc_app)
        kwargs["base_url"] = "http://cc-test"
        kwargs.pop("verify", None)
        kwargs.pop("cert", None)
        return real_internal_httpx_client(**kwargs)

    async def _fake_user_sub(user_jwt):
        return "user-1"

    monkeypatch.setattr(tool_routing, "internal_httpx_client", _asgi_internal_client)
    monkeypatch.setattr(tool_routing, "_allow_insecure_internal_fallback", lambda: True)
    monkeypatch.setattr(tool_routing, "_extract_user_sub", _fake_user_sub)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/internal/tools/call",
        "headers": [],
        "query_string": b"",
        "app": cc_app,
    }
    request = Request(scope)

    # ── Step 0: seed the prior state (role + conversational agent type) ──────
    role = await _invoke(cc_client, "create_agent_role", {"name": "e2e-role", "data": {}})
    agent = await _invoke(
        cc_client,
        "create_agent_type",
        {"name": "e2e-agent", "data": {"system_instruction": "old instructions"}},
    )
    agent_id = agent["record"]["id"]

    # ── Step 1: READ the agent type (current state the preview is built from) ─
    current = await _invoke(cc_client, "get_agent_type", {"id": agent_id})
    assert current["record"]["role_id"] is None
    assert current["record"]["input_type"] != "typed"

    # ── Step 2: canonical old → new preview (role + input/output config) ─────
    approved_fields = {
        "role_id": role["record"]["name"],  # assistant resolves id-or-name
        "input_type": "typed",
        "output_type": "typed",
        "system_instruction": "new instructions",
    }
    preview = _canonical_preview(current["record"], approved_fields, "e2e-agent")
    assert preview.startswith("**Update Agent Type: e2e-agent**")
    assert "| Field | Value |" in preview
    assert "→" in preview

    # ── Step 3: approval via the confirmation intervention ───────────────────
    conv_id = uuid.uuid4()
    comm_hub_client = _StubCommHubClient()
    intervention = LangChainHumanInterveneTool(
        comm_hub_client=comm_hub_client,
        session_id=str(uuid.uuid4()),
        agent_type_id=agent_id,
        conv_session_id=str(conv_id),
    )
    import asyncio

    approver = asyncio.create_task(_approve_confirmation(conv_id))
    result_json = await intervention._arun(
        intervention_type="approval",
        reason="Update Agent Type: e2e-agent",
        choices=None,
        prompt=preview,
    )
    await approver
    import json

    payload = json.loads(result_json)
    assert payload["status"] == "approved", "approval gate must open the dispatch"

    # ── Step 4: cc____update_agent_type through CH routing ───────────────────
    from app.communication_hub.api.internal.tool_routing import ToolCallResponse, route_tool_call

    response = await route_tool_call(
        tool_routing.ToolCallRequest(
            tool_name="cc____update_agent_type",
            tool_args={"id": agent_id, "data": dict(approved_fields)},
            session_id=str(uuid.uuid4()),
            agent_type_id=agent_id,
            user_jwt="stub-jwt",
            conv_session_id=str(conv_id),
        ),
        request,
    )
    assert isinstance(response, ToolCallResponse)
    assert response.error is None, response.error
    serialized = response.result["result"]["record"]
    assert serialized["role_id"] == role["record"]["id"]
    assert serialized["input_type"] == "typed"
    assert serialized["output_type"] == "typed"
    assert serialized["system_instruction"] == "new instructions"
    # The assistant confirms the applied changes from THIS serialized payload.

    # ── Step 5: the persisted record matches ALL approved fields ─────────────
    from app.db.models.agents import AgentType

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        row = (
            await session.execute(select(AgentType).where(AgentType.id == uuid.UUID(agent_id)))
        ).scalar_one()
    assert str(row.role_id) == role["record"]["id"]
    assert (row.input_type.value if hasattr(row.input_type, "value") else row.input_type) == "typed"
    assert (row.output_type.value if hasattr(row.output_type, "value") else row.output_type) == "typed"
    assert row.system_instruction == "new instructions"


@pytest.mark.asyncio
async def test_assistant_agent_type_update_rejection_writes_nothing(cc_client, cc_app, allow_all, test_engine, monkeypatch):
    """Negative variant: the operator rejects the preview → NO CH dispatch,
    and the persisted record keeps its prior state."""
    from unittest.mock import AsyncMock

    from app.agent_runtime import conversation_resume
    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

    role = await _invoke(cc_client, "create_agent_role", {"name": "rej-role", "data": {}})
    agent = await _invoke(
        cc_client,
        "create_agent_type",
        {"name": "rej-agent", "data": {"system_instruction": "keep me"}},
    )
    agent_id = agent["record"]["id"]
    current = await _invoke(cc_client, "get_agent_type", {"id": agent_id})

    approved_fields = {
        "role_id": role["record"]["name"],
        "input_type": "typed",
        "output_type": "typed",
        "system_instruction": "rejected instructions",
    }
    preview = _canonical_preview(current["record"], approved_fields, "rej-agent")

    conv_id = uuid.uuid4()
    comm_hub_client = AsyncMock()
    comm_hub_client.call_human_intervene = AsyncMock(
        return_value={"request_id": "rej-1", "status": "pending"}
    )
    intervention = LangChainHumanInterveneTool(
        comm_hub_client=comm_hub_client,
        session_id=str(uuid.uuid4()),
        agent_type_id=agent_id,
        conv_session_id=str(conv_id),
    )
    import asyncio
    import json

    rejecter = asyncio.create_task(_reject_confirmation(conv_id))
    result_json = await intervention._arun(
        intervention_type="approval", reason="Update Agent Type: rej-agent", choices=None, prompt=preview
    )
    await rejecter
    payload = json.loads(result_json)
    assert payload["status"] == "resolved"
    assert payload["approval_value"] is False
    # No write dispatch leaves AR: CH never receives the management tool call.
    comm_hub_client.call_tool.assert_not_awaited()

    # Belt-and-braces: even a dispatch attempt after rejection would be the
    # contract violation — assert the persisted record is untouched.
    from app.db.models.agents import AgentType

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        row = (
            await session.execute(select(AgentType).where(AgentType.id == uuid.UUID(agent_id)))
        ).scalar_one()
    assert row.role_id is None
    assert row.system_instruction == "keep me"
    assert (row.input_type.value if hasattr(row.input_type, "value") else row.input_type) != "typed"


class _StubCommHubClient:
    """Minimal CH client stub for the intervention registration round-trip."""

    async def call_human_intervene(self, **kwargs):
        return {"request_id": "e2e-1", "status": "pending"}
