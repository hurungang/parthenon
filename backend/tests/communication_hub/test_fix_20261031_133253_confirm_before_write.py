"""FIX-20261031-133253 — mandatory confirmation before create/update + agent-creation completeness.

Root cause: the assistant created a bare-shell agent type (``model=None,
identity=None, role=None``) because (a) the model was never required to
confirm write operations with the user, (b) ``human_intervene`` was not in
the assistant's meta tool set, and (c) no knowledge/instruction rule pinned
the completeness workflow (model + identity/role + skill grants).

Contract pinned here:

1. ``human_intervene`` is exposed to the assistant context as the 5th meta
   tool (registry + per-tenant seeding + agent_context tool_definitions).
2. Knowledge corpus answers "do I need to confirm before creating?" and
   "what does an agent need to work?" with the confirmation / completeness
   rules.
3. The seeder instruction carries the confirmation + completeness rules and
   refreshes already-seeded rows (digest branch).
4. AR→CH→CC routing: ``system____human_intervene`` routes to the existing
   CC ``/internal/system-tools/human-intervene`` endpoint via the same
   signed-tenant-forwarding mechanism as every other system tool.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.session import Base
from app.db.models.agents import AgentType
from app.db.models.mcp_hub import McpServer, McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.models.tenant import Tenant
from app.services.agents.assistant_knowledge import search_knowledge
from app.services.agents.assistant_seeder import (
    ASSISTANT_AGENT_TYPE_NAME,
    ASSISTANT_SYSTEM_INSTRUCTION,
    MANAGEMENT_SKILL_NAME,
    AssistantSeeder,
)
from app.services.agents.system_tool_registry import SystemToolRegistry


# ── 1. human_intervene is a meta tool ────────────────────────────────────────


def test_human_intervene_is_in_meta_tool_set() -> None:
    """human_intervene must be part of the assistant meta tool set."""
    assert "human_intervene" in SystemToolRegistry.get_meta_tool_names()


def test_human_intervene_has_registry_schema() -> None:
    """The definition the assistant context loads must exist and carry the
    approval/choice/text intervention contract."""
    assert SystemToolRegistry.get_names() is not None
    assert "human_intervene" in SystemToolRegistry.get_names()
    schema = SystemToolRegistry.get_schema("human_intervene")
    assert schema is not None
    props = schema["function"]["parameters"]["properties"]
    assert "intervention_type" in props
    assert "prompt" in props


def test_meta_tools_still_carry_no_parity() -> None:
    """human_intervene becoming a meta tool must not leak into the
    management permission parity map (it is not a management action)."""
    parity = SystemToolRegistry.get_parity_map()
    assert "human_intervene" not in parity
    assert not SystemToolRegistry.is_management_tool("human_intervene")


# ── 2. agent_context exposes 5 meta definitions ─────────────────────────────


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    """Fresh in-memory engine per test (tenant isolation)."""
    from app.services.tenancy.root_tenant import invalidate_root_tenant_cache

    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )()
    session.add(
        Tenant(id=uuid.uuid4(), slug="root", name="Root", is_system_tenant=True)
    )
    await session.commit()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
    invalidate_root_tenant_cache()


async def _seed_root_management_tools(session: AsyncSession) -> None:
    from sqlalchemy import select as _select

    root = (
        await session.execute(_select(Tenant).where(Tenant.is_system_tenant.is_(True)))
    ).scalar_one()

    test_server_id = uuid.uuid5(uuid.NAMESPACE_OID, "test-root:system-server")
    if await session.get(McpServer, test_server_id) is None:
        session.add(
            McpServer(
                id=test_server_id,
                tenant_id=root.id,
                name="system",
                slug="system",
                description="Built-in system tools available to all agents",
                base_url="",
            )
        )
        await session.flush()

    seeded_names = (
        SystemToolRegistry.get_management_tool_names()
        | SystemToolRegistry.get_meta_tool_names()
    )
    from app.services.agents.assistant_seeder import _tenant_management_tool_id

    for entry in (
        SystemToolRegistry.get_mcp_hub_entries()
        + SystemToolRegistry.get_cc_mcp_hub_entries()
    ):
        if entry["original_name"] not in seeded_names:
            continue
        row_id = _tenant_management_tool_id(entry["id"], root.id)
        if await session.get(McpTool, row_id) is not None:
            continue
        session.add(
            McpTool(
                id=row_id,
                tenant_id=root.id,
                server_id=test_server_id,
                name=entry["name"],
                original_name=entry["original_name"],
                description=entry["description"],
                input_schema=entry["input_schema"],
                is_active=True,
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_assistant_context_definitions_include_human_intervene(
    isolated_db,
) -> None:
    """The role-less assistant context must load exactly the meta tool
    definitions — now 5, including human_intervene."""
    from app.api.v1.internal.agent_data import get_agent_context

    await _seed_root_management_tools(isolated_db)
    await AssistantSeeder().run(isolated_db)
    await isolated_db.commit()

    root_tenant = (
        await isolated_db.execute(
            select(Tenant).where(Tenant.is_system_tenant.is_(True))
        )
    ).scalar_one()
    assistant = (
        await isolated_db.execute(
            select(AgentType).where(
                AgentType.name == ASSISTANT_AGENT_TYPE_NAME,
                AgentType.tenant_id == root_tenant.id,
            )
        )
    ).scalar_one()

    context = await get_agent_context(agent_type_id=assistant.id, db=isolated_db)

    def_names = [
        d["function"]["name"]
        for d in context.tool_definitions
        if d.get("type") == "function"
    ]
    meta_names = set(SystemToolRegistry.get_meta_tool_names())

    def canonical_def(meta: str) -> str:
        prefix = (
            "cc"
            if SystemToolRegistry.get(meta).category == "management"
            else "system"
        )
        return f"{prefix}____{meta}".replace("____", "__")

    # FIX-20261101-000319: definitions carry category-aware sanitised
    # canonical names (cc__… / system__…).
    # FIX-20261101-120618: the inherent built-in skills are also injected
    # into every agent context (meta + inherent, gated default set — no
    # workflow-optimization authoring tools without an opt-in run).
    from app.services.agents.builtin_skills import (
        get_inherent_tool_names_for,
    )

    expected_defs = {canonical_def(m) for m in meta_names} | {
        f"system____{bare}".replace("____", "__")
        for bare in get_inherent_tool_names_for(optimization_enabled=False)
    }
    assert set(def_names) == expected_defs
    assert "system__human_intervene" in def_names
    assert len(meta_names) == 5

    # The management skill must also be bound to human_intervene so the
    # CH-side allowed-tools check admits the call.
    skill = (
        await isolated_db.execute(
            select(Skill).where(
                Skill.name == MANAGEMENT_SKILL_NAME,
                Skill.tenant_id == root_tenant.id,
            )
        )
    ).scalar_one()
    bindings = (
        await isolated_db.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill.id)
        )
    ).scalars().all()
    bound_tool_ids = {b.tool_id for b in bindings}
    hi_row = (
        await isolated_db.execute(
            select(McpTool).where(
                McpTool.tenant_id == root_tenant.id,
                McpTool.original_name == "human_intervene",
            )
        )
    ).scalars().first()
    assert hi_row is not None
    assert hi_row.id in bound_tool_ids


# ── 3. Knowledge rules ───────────────────────────────────────────────────────


def test_knowledge_confirmation_rule_retrievable() -> None:
    results = search_knowledge("do I need to confirm before creating a resource?")
    ids = {r["id"] for r in results}
    assert "confirm-before-write" in ids
    entry = next(r for r in results if r["id"] == "confirm-before-write")
    text = entry["rule_text"]
    assert "human_intervene" in text
    assert "approval" in text
    assert "table" in text
    # Rejection contract.
    assert "reject" in text.lower()


def test_knowledge_agent_completeness_rule_retrievable() -> None:
    """FIX-20261102-100704: the entry stays a REFERENCE FACT (what makes an
    agent type functional), not a case-scripted workflow."""
    # FIX-20261102-100704 + cc-assistant-management-tool-coverage (Phase 4
    # expanded the corpus, shifting top-3 ranking for vague queries): the
    # entry stays a REFERENCE FACT retrievable with a specific query.
    results = search_knowledge("agent creation completeness")
    ids = {r["id"] for r in results}
    assert "agent-creation-completeness" in ids
    entry = next(r for r in results if r["id"] == "agent-creation-completeness")
    text = entry["rule_text"]
    for token in (
        "list_agent_identities",
        "list_agent_roles",
        "list_model_configs",
        "non-functional",
        "enabled",
    ):
        assert token.lower() in text.lower(), f"completeness rule missing {token!r}"
    # Principle framing, and the grant level is stated generically.
    assert "reference fact" in text.lower()
    assert "role" in text.lower() and "grant" in text.lower()


def test_knowledge_completeness_principle_is_generic() -> None:
    """The generic completeness principle (not the agent-only case) is what a
    'how do I make anything work' question surfaces."""
    results = search_knowledge("how do I make an agent work", top_k=5)
    ids = [r["id"] for r in results]
    assert "resource-completeness" in ids
    entry = next(r for r in results if r["id"] == "resource-completeness")
    text = entry["rule_text"].lower()
    assert "every resource type" in text
    assert "complete" in text and "functional" in text
    # No hardcoded create-skill-first sequence.
    assert "create skill first" not in text


def test_knowledge_prerequisite_principle_is_generic() -> None:
    results = search_knowledge("what must exist before creating a resource", top_k=5)
    ids = [r["id"] for r in results]
    assert "prerequisite-ordering" in ids
    entry = next(r for r in results if r["id"] == "prerequisite-ordering")
    text = entry["rule_text"].lower()
    assert "derive" in text
    assert "dependency" in text


def test_knowledge_general_creation_completeness_retrievable() -> None:
    results = search_knowledge("required fields when creating any resource")
    texts = " ".join(r["rule_text"] for r in results)
    assert "preview" in texts.lower()
    assert "missing" in texts.lower()


# ── 4. Seeder instruction carries the rules; rows refresh ───────────────────


def test_seeder_instruction_has_confirmation_and_completeness() -> None:
    text = ASSISTANT_SYSTEM_INSTRUCTION
    assert "human_intervene" in text
    lowered = text.lower()
    assert "markdown" in lowered and "table" in lowered
    assert "list_agent_identities" in text
    assert "list_agent_roles" in text
    assert "list_model_configs" in text
    assert "non-functional" in text.lower()
    # FIX-20261102-100704: generic principles, and no fixed case script.
    assert "completeness principle" in lowered
    assert "prerequisite ordering" in lowered
    assert "grant at the right level" in lowered
    assert "reuse-first" in lowered
    assert "create the skill first" not in lowered
    assert "sequence: (1)" not in lowered


@pytest.mark.asyncio
async def test_seeder_refreshes_existing_skill_instructions(isolated_db) -> None:
    """An already-seeded (pre-fix) management skill must be refreshed with
    the confirmation + completeness digest on the next seeder run."""
    tenant = Tenant(id=uuid.uuid4(), slug="fix-133253", name="Fix133253", status="active")
    isolated_db.add(tenant)
    await isolated_db.flush()

    # Simulate a pre-fix skill row (stale digest without the new rules).
    stale_skill = Skill(
        tenant_id=tenant.id,
        name=MANAGEMENT_SKILL_NAME,
        description="old",
        instructions="stale pre-fix instructions without the confirmation rule",
        is_active=True,
        is_system=True,
    )
    isolated_db.add(stale_skill)
    await isolated_db.commit()

    await AssistantSeeder().run(isolated_db)
    await isolated_db.commit()

    refreshed = (
        await isolated_db.execute(
            select(Skill).where(
                Skill.name == MANAGEMENT_SKILL_NAME,
                Skill.tenant_id == tenant.id,
            )
        )
    ).scalar_one()
    assert refreshed.instructions != "stale pre-fix instructions without the confirmation rule"
    assert "human_intervene" in refreshed.instructions
    assert "confirm" in refreshed.instructions.lower()
    assert "model" in refreshed.instructions.lower()


# ── 5. AR→CH routing reaches the CC human-intervene endpoint ────────────────


@pytest.fixture(autouse=True)
def _insecure_fallback(monkeypatch):
    """Allow the no-certificate development path so the test reaches the
    HTTP layer without a CH service certificate."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "1")


def _wire_headers(request) -> dict[str, str]:
    from app.core.tenant_signature import TENANT_SIGNATURE_HEADERS

    lowered = {k.lower(): v for k, v in request.headers.items()}
    return {
        h: lowered[h.lower()]
        for h in TENANT_SIGNATURE_HEADERS
        if h.lower() in lowered
    }


def _client_factory(captured):
    import httpx as _httpx

    real_client = _httpx.AsyncClient

    def factory(**kw):
        def handler(request: _httpx.Request) -> _httpx.Response:
            captured.append(request)
            return _httpx.Response(200, json={"result": {}})

        transport = _httpx.MockTransport(handler)

        # Keep the internal_http egress hook so tenant-header forwarding
        # (client-level event hook) actually runs on the wire.
        return real_client(transport=transport, event_hooks=kw.get("event_hooks"))

    return factory


def _fake_request():
    from types import SimpleNamespace as _NS

    return _NS(app=_NS(state=_NS(certificate_manager=None)))


class TestHumanInterveneRouting:
    @pytest.fixture
    def bound(self):
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            build_tenant_signature_headers,
            reset_forwarded_tenant_headers,
        )

        ctx = SimpleNamespace(tenant_id=uuid.uuid4(), slug="routing-133253")
        signed = build_tenant_signature_headers(ctx)
        token = bind_forwarded_tenant_headers(dict(signed))
        yield signed
        reset_forwarded_tenant_headers(token)

    @pytest_asyncio.fixture
    async def routing_settings(self):
        from app.communication_hub.api.internal import tool_routing

        return tool_routing

    @pytest.mark.asyncio
    async def test_human_intervene_routes_to_cc_endpoint_with_signed_set(
        self, bound, routing_settings
    ):
        captured: list = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="system____human_intervene",
            tool_args={
                "intervention_type": "approval",
                "reason": "approve create_agent_type",
                "prompt": "| field | value |\n|---|---|",
            },
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory), patch.object(
            routing_settings, "_extract_user_sub"
        ) as _extract:
            async def _fake_sub(_jwt):
                return "user-123"

            _extract.side_effect = _fake_sub
            response = await routing_settings._route_to_system_tool(
                body, _fake_request()
            )

        assert "/api/v1/internal/system-tools/human-intervene" in str(
            captured[0].url.path
        )
        assert _wire_headers(captured[0]) == dict(bound)
        assert response.error in (None, "")
