"""FULL-JOURNEY test: agent calls a virtual decision tool end-to-end.

Live failure this pins:

    AR ``decision____severity-decision`` tool call
      → AR ``CommHubToolClient.call_tool`` → CH ``POST /internal/tools/call``
      → CH ``tool_routing`` routed it to CC ``/internal/mcp/proxy-tool``
      ← CC "MCP tool not found: decision____severity-decision" (decision
        tools are virtual — no mcp_tools row) → CH 502 → AR tool failure.

One test (``test_full_journey_decision_tool_end_to_end``) walks EVERY hop
in order against real PostgreSQL (``parthenon_test``, strict-tenant
pattern), stubbing ONLY the System One model inference (``TypeSafeJevClient``)
and the external IdP (no OIDC involved — internal hops use the real signed
tenant header machinery):

  a. toolset build: ``get_agent_context`` includes ``decision____<name>``
     in allowed_tools with a real function definition;
  b. AR dispatch: the simulated LLM tool call runs through the real
     ``runtime_executor._execute_mcp_tool_ar`` → real
     ``CommHubToolClient.call_tool`` (MockTransport at the AR egress
     serving the REAL CH ``tool_routing`` router) → the CH→CC wire call
     carries the signed tenant headers AND hits
     ``/internal/system-tools/decision/execute`` (not the MCP proxy);
  c. CC handler: the REAL ``execute_decision_tool_internal`` runs against
     the real DB — the tenant is recovered from the SIGNED headers, the
     tool resolves within that tenant, the result persists;
  d. result propagation: the AR wrapper receives a successful structured
     decision result (no 502 / "MCP tool not found");
  e. tenant isolation: the same-named tool in ANOTHER tenant is a
     different row — executing under the other tenant's signed set
     resolves and returns the OTHER tenant's tool, never tenant A's.
"""
from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.integration._strict_tenant_utils import (  # noqa: F401
    TEST_DB_URL,
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()


# ── helpers (mirroring test_decision_tools_in_conversation patterns) ─────────


async def _create_data_type(db, tenant_id, name: str, field_names: list[str]):
    """Seed an AgentDataType with one field per given name."""
    from app.db.models.agent_data_type import AgentDataType

    data_type = AgentDataType(
        tenant_id=tenant_id,
        name=name,
        slug=f"{name}-{uuid.uuid4().hex[:6]}",
        fields=[{"name": f, "type": "string"} for f in field_names],
    )
    db.add(data_type)
    await db.commit()
    await db.refresh(data_type)
    return data_type


async def _create_decision_tool(
    db, tenant_id, name: str, question_key: str, *, ready: bool = True
):
    """Seed a decision tool with ONE question (key differs per tenant so
    same-named tools in different tenants produce distinguishable results).

    By default BOTH data types are attached (READY — the enable gate);
    ``ready=False`` seeds the legacy unready shape (NULL types) directly
    via the ORM, bypassing service validation (pre-gate rows)."""
    from app.db.models.decision_tools import DecisionTool, DecisionToolQuestion

    input_type_id = output_type_id = None
    if ready:
        input_type = await _create_data_type(
            db, tenant_id, f"{name}-input", ["situation", "severity"]
        )
        output_type = await _create_data_type(
            db, tenant_id, f"{name}-output", ["decision"]
        )
        input_type_id = input_type.id
        output_type_id = output_type.id

    tool = DecisionTool(
        tenant_id=tenant_id,
        name=name,
        purpose=f"Decide {name} [{question_key}]",
        input_data_type_id=input_type_id,
        output_data_type_id=output_type_id,
        enabled=True,
    )
    tool.questions.append(
        DecisionToolQuestion(
            question_key=question_key,
            question_type="choice",
            instructions="Approve?",
            criteria_options={"yes": "approve", "no": "reject"},
            ordering=0,
        )
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


async def _create_agent_with_decision_skill(db, tenant_id, decision_tool, name: str):
    """Skill + virtual decision-tool binding + role + agent type chain."""
    from app.db.models.agents import (
        AgentInputType,
        AgentOutputType,
        AgentRole,
        AgentRoleSkill,
        AgentType,
    )
    from app.db.models.skills import Skill, SkillToolBinding
    from app.services.system_one.decision_tool_service import (
        decision_tool_virtual_tool_id,
    )

    skill = Skill(name=f"skill-{decision_tool.name}-{uuid.uuid4().hex[:6]}")
    if hasattr(Skill, "tenant_id"):
        skill.tenant_id = tenant_id
    db.add(skill)
    await db.flush()
    db.add(
        SkillToolBinding(
            skill_id=skill.id,
            tool_id=decision_tool_virtual_tool_id(decision_tool.id),
        )
    )
    role = AgentRole(name=name, description=name)
    if hasattr(AgentRole, "tenant_id"):
        role.tenant_id = tenant_id
    db.add(role)
    await db.flush()
    db.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
    agent_type = AgentType(
        tenant_id=tenant_id,
        name=name,
        role_id=role.id,
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
    )
    db.add(agent_type)
    await db.commit()
    await db.refresh(agent_type)
    return skill, agent_type


async def _seed_provider(db, tenant_id) -> None:
    """Enabled System One provider for the tenant (key encrypted via vault)."""
    from app.core.credential_vault import get_vault
    from app.db.models.system_one_provider_config import (
        SystemOneProviderConfig,
        SystemOneProviderType,
    )

    db.add(
        SystemOneProviderConfig(
            tenant_id=tenant_id,
            provider_type=SystemOneProviderType.typesafe,
            display_name="Test TypeSafe Jev",
            base_url="http://localhost:9999/v1",
            default_model="jev-latest",
            encrypted_api_key=get_vault().encrypt("sk-journey-test-key"),
            enabled=True,
        )
    )
    await db.commit()


class FakeJevClient:
    """Stub at the System One model-inference boundary: records the dispatch
    and returns typed answers for whichever question keys it receives."""

    def __init__(self):
        self.calls: list[dict] = []

    async def evaluate(self, *, base_url, api_key, model, state, questions, **kw):
        self.calls.append(
            {"model": model, "state": state, "questions": sorted(questions)}
        )
        answers = {}
        for key in questions:
            if key == "risk":
                answers[key] = {
                    "type": "choice",
                    "choice": "no",
                    "probabilities": {"yes": 0.05, "no": 0.95},
                    "confidence": 0.95,
                }
            else:
                answers[key] = {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 0.95, "no": 0.05},
                    "confidence": 0.95,
                }
        return {"model": model, "answers": answers}


# ── the ONE full-journey test ─────────────────────────────────────────────────


class TestDecisionToolFullJourney:
    async def test_full_journey_decision_tool_end_to_end(
        self, db: AsyncSession, monkeypatch
    ):
        """Walk every hop: toolset build → AR dispatch → CH routing → CC
        execution (real DB) → result back at the AR wrapper — plus the
        tenant-isolation leg for the same-named tool in the other tenant."""
        # ── development-mode insecure fallback so the CH router reaches its
        #    CC egress without a CH service certificate (test-only).
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "1")

        from app.core.tenant_context import TenantContext
        from app.core.tenant_signature import (
            TENANT_SIGNATURE_HEADERS,
            bind_forwarded_tenant_headers,
            build_tenant_signature_headers,
            reset_forwarded_tenant_headers,
            verify_tenant_signature_headers,
        )

        # ── 1. Seed: two tenants; "test-com" analog (A) gets the agent +
        #        skill + decision tool; the other tenant (B) has the SAME-
        #        NAMED tool with a DIFFERENT question key.
        tenant_a, tenant_b = await create_two_tenants(db)
        tool_a = await _create_decision_tool(db, tenant_a.id, "severity-decision", "approve")
        skill_a, agent_type_a = await _create_agent_with_decision_skill(
            db, tenant_a.id, tool_a, "severity-agent-a"
        )
        tool_b = await _create_decision_tool(db, tenant_b.id, "severity-decision", "risk")
        await _seed_provider(db, tenant_a.id)
        await _seed_provider(db, tenant_b.id)

        assert tool_a.id != tool_b.id  # same name, independent rows

        # ── (a) toolset build: allowed_tools + real function definition ────
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        apply_tenant_scope(db, tenant_a.id)
        agent_ctx = await get_agent_context(agent_type_id=agent_type_a.id, db=db)
        assert "decision____severity-decision" in agent_ctx.allowed_tools
        defs = [
            d
            for d in agent_ctx.tool_definitions
            if "severity" in d["function"]["name"]
        ]
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["description"]
        assert any(
            v == "decision____severity-decision" for v in agent_ctx.tool_name_map.values()
        )

        # ── wire harness: ONE MockTransport at the AR egress serving (i)
        #    the REAL CH tool_routing router and (ii) the REAL CC decision
        #    execute handler against the real DB (fresh CC-side session).
        from app.agent_runtime.comm_hub_client import CommHubToolClient
        from app.api.v1.internal.system_tools import (
            DecisionToolExecuteRequest,
            execute_decision_tool_internal,
        )
        from app.communication_hub.api.internal import tool_routing
        from app.services.agents.runtime_executor import AgentRuntimeExecutor
        from app.services.system_one import decision_engine as engine_module

        real_async_client = httpx.AsyncClient
        captured_cc: list[httpx.Request] = []
        fake_jev = FakeJevClient()
        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake_jev)

        async def cc_hop(request: httpx.Request) -> httpx.Response:
            """CC leg: recover the tenant from the SIGNED headers (exactly
            what ``require_internal_tenant_context`` does) and run the REAL
            decision execute handler against the real DB."""
            captured_cc.append(request)
            assert request.url.path == "/api/v1/internal/system-tools/decision/execute"
            verified = verify_tenant_signature_headers(request.headers)
            body = DecisionToolExecuteRequest(**json.loads(request.content))
            engine = create_async_engine(TEST_DB_URL)
            SessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with SessionLocal() as cc_db:
                    response = await execute_decision_tool_internal(
                        body=body,
                        tenant_ctx=TenantContext(
                            tenant_id=verified.tenant_id,
                            slug=verified.slug,
                            name=f"cc-hop-{verified.slug}",
                        ),
                        db=cc_db,
                    )
                    return httpx.Response(200, json={"result": response.result})
            finally:
                await engine.dispose()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/internal/tools/call":
                # Serve the REAL Communication Hub tool_routing router.
                ch_app = _build_ch_app()
                async with real_async_client(
                    transport=httpx.ASGITransport(app=ch_app),
                    base_url="http://ch-test:8002",
                ) as ch_client:
                    ch_response = await ch_client.post(
                        request.url.path,
                        content=request.content,
                        headers=dict(request.headers),
                    )
                return httpx.Response(
                    ch_response.status_code,
                    content=ch_response.content,
                    headers=ch_response.headers,
                )
            return await cc_hop(request)

        def factory(**kw):
            # Preserve the internal_http egress hook (tenant-header
            # forwarding is a client-level event hook) but force the
            # MockTransport.
            return real_async_client(
                transport=httpx.MockTransport(handler),
                event_hooks=kw.get("event_hooks"),
            )

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        monkeypatch.setattr(
            tool_routing.settings, "control_center_url", "http://cc-test:8000"
        )

        async def run_dispatch(signed: dict[str, str]) -> dict:
            token = bind_forwarded_tenant_headers(signed)
            try:
                executor = AgentRuntimeExecutor(data_client=None)
                return await executor._execute_mcp_tool_ar(
                    tool_name="decision____severity-decision",
                    tool_args={"state": {"severity": "high"}},
                    role_mcp_sessions={},
                    agent_type_id=str(agent_type_a.id),
                    session_id=str(uuid.uuid4()),
                    comm_hub_client=CommHubToolClient(),
                )
            finally:
                reset_forwarded_tenant_headers(token)

        def signed_headers_of(request: httpx.Request) -> dict[str, str]:
            lowered = {k.lower(): v for k, v in request.headers.items()}
            return {
                h: lowered[h.lower()]
                for h in TENANT_SIGNATURE_HEADERS
                if h.lower() in lowered
            }

        # ── (b)+(c)+(d) tenant A journey ───────────────────────────────────
        signed_a = build_tenant_signature_headers(
            TenantContext(
                tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name
            )
        )
        result_a = await run_dispatch(signed_a)

        # (b) exactly ONE CH→CC wire hop, to decision/execute (NOT the MCP
        #     proxy — the live-failure regression), carrying the signed set.
        assert len(captured_cc) == 1
        wire = captured_cc[0]
        assert wire.url.path == "/api/v1/internal/system-tools/decision/execute"
        wire_headers = signed_headers_of(wire)
        assert wire_headers == signed_a
        wire_payload = json.loads(wire.content)
        assert wire_payload["tool_name"] == "severity-decision"
        assert wire_payload["input_state"] == {"severity": "high"}

        # (c) the CC handler ran against the real DB: the model-inference
        #     stub saw ONE dispatch carrying the tenant's provider model.
        assert len(fake_jev.calls) == 1
        assert fake_jev.calls[0]["model"] == "jev-latest"

        # (d) the result propagated back to the AR wrapper — a successful
        #     structured decision, NOT the "MCP tool not found" 502.
        assert isinstance(result_a, dict) and not result_a.get("error")
        assert result_a["tool_name"] == "severity-decision"
        assert result_a["decision_tool_id"] == str(tool_a.id)
        assert result_a["status"] == "completed"
        assert "approve" in result_a["answers"]
        assert result_a["input_state_snapshot"] == {"severity": "high"}

        # ── (e) tenant isolation: same journey under tenant B's signed set
        #        resolves B's SAME-NAMED tool — never tenant A's row.
        signed_b = build_tenant_signature_headers(
            TenantContext(
                tenant_id=tenant_b.id, slug=tenant_b.slug, name=tenant_b.name
            )
        )
        result_b = await run_dispatch(signed_b)

        assert len(captured_cc) == 2
        wire_b_headers = signed_headers_of(captured_cc[1])
        assert wire_b_headers == signed_b
        assert not result_b.get("error")
        assert result_b["decision_tool_id"] == str(tool_b.id)
        assert result_b["decision_tool_id"] != str(tool_a.id)
        assert "risk" in result_b["answers"]  # B's own question schema
        assert "approve" not in result_b["answers"]
        # Tenant B's dispatch never reached tenant A's tool identity.
        assert all(
            call["questions"] == ["risk"] for call in fake_jev.calls[1:]
        )

        # And tenant A's tool is not callable under B's tenant by identity:
        # the CC payloads carried no cross-tenant tool ids — resolution was
        # strictly name-within-signed-tenant (already asserted via tool ids).

    async def test_flat_llm_kwargs_reach_engine_input_state(
        self, db: AsyncSession, monkeypatch
    ):
        """Live failure (2026-10-11): the LLM called the tool with FLAT kwargs
        ``{"situation": "..."}`` (decision tool WITHOUT an input data type →
        empty ``parameters`` schema) and the engine received an EMPTY input
        state — LangChain's ``_to_args_and_kwargs`` short-circuits fieldless
        BaseModel schemas to "no args", silently dropping every key before
        CommHub.  This walks the REAL chain with the real LLM-style arg shape:

        LangChain tool.invoke (flat kwargs) → wrapper ``_arun`` →
        ``CommHubToolClient.call_tool`` → real CH ``tool_routing`` →
        real CC ``execute_decision_tool_internal`` → engine input state.
        """
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "1")

        from app.core.tenant_context import TenantContext
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            build_tenant_signature_headers,
            reset_forwarded_tenant_headers,
            verify_tenant_signature_headers,
        )

        tenant_a, _tenant_b = await create_two_tenants(db)
        tool_a = await _create_decision_tool(db, tenant_a.id, "flat-decision", "approve")
        # State preset requires 'situation' from the input — proves the key
        # actually ARRIVED in the engine's input state.
        tool_a.state_preset = {"situation": {"source": "input", "key": "situation"}}
        db.add(tool_a)
        await db.commit()
        _skill, agent_type_a = await _create_agent_with_decision_skill(
            db, tenant_a.id, tool_a, "flat-kwargs-agent"
        )
        await _seed_provider(db, tenant_a.id)

        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        apply_tenant_scope(db, tenant_a.id)
        agent_ctx = await get_agent_context(agent_type_id=agent_type_a.id, db=db)
        defs = [d for d in agent_ctx.tool_definitions if "flat-decision" in d["function"]["name"]]
        assert len(defs) == 1
        # The live failure involved a tool definition with EMPTY parameters
        # (legacy unready rows). Validated tools can no longer produce that
        # shape, so simulate it directly at the wrapper boundary (the
        # passthrough fallback stays as defense in depth for legacy rows).
        defs[0]["function"]["parameters"] = {"type": "object", "properties": {}}

        # ── wire harness (same as the main journey test) ──────────────────
        from app.agent_runtime.comm_hub_client import CommHubToolClient
        from app.api.v1.internal.system_tools import (
            DecisionToolExecuteRequest,
            execute_decision_tool_internal,
        )
        from app.communication_hub.api.internal import tool_routing
        from app.services.agents.runtime_executor import AgentRuntimeExecutor
        from app.services.system_one import decision_engine as engine_module

        real_async_client = httpx.AsyncClient
        captured_cc: list[httpx.Request] = []
        fake_jev = FakeJevClient()
        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake_jev)

        async def cc_hop(request: httpx.Request) -> httpx.Response:
            captured_cc.append(request)
            verified = verify_tenant_signature_headers(request.headers)
            # Tenant binding: the bound tenant is the signed one — NOT None.
            assert verified.tenant_id == tenant_a.id
            body = DecisionToolExecuteRequest(**json.loads(request.content))
            engine = create_async_engine(TEST_DB_URL)
            SessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with SessionLocal() as cc_db:
                    response = await execute_decision_tool_internal(
                        body=body,
                        tenant_ctx=TenantContext(
                            tenant_id=verified.tenant_id,
                            slug=verified.slug,
                            name=f"cc-hop-{verified.slug}",
                        ),
                        db=cc_db,
                    )
                    return httpx.Response(200, json={"result": response.result})
            finally:
                await engine.dispose()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/internal/tools/call":
                ch_app = _build_ch_app()
                async with real_async_client(
                    transport=httpx.ASGITransport(app=ch_app),
                    base_url="http://ch-test:8002",
                ) as ch_client:
                    ch_response = await ch_client.post(
                        request.url.path,
                        content=request.content,
                        headers=dict(request.headers),
                    )
                return httpx.Response(
                    ch_response.status_code,
                    content=ch_response.content,
                    headers=ch_response.headers,
                )
            return await cc_hop(request)

        def factory(**kw):
            return real_async_client(
                transport=httpx.MockTransport(handler),
                event_hooks=kw.get("event_hooks"),
            )

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        monkeypatch.setattr(
            tool_routing.settings, "control_center_url", "http://cc-test:8000"
        )

        # ── the REAL LangChain tool wrapper, invoked exactly like ToolNode ──
        from app.services.agents.langchain_tool_wrapper import (
            build_langchain_tools_for_ar_path,
        )

        lc_tools = build_langchain_tools_for_ar_path(
            tool_definitions=defs,
            comm_hub_client=CommHubToolClient(),
            data_client=None,
            session_id=str(uuid.uuid4()),
            agent_type_id=str(agent_type_a.id),
            conv_session_id=None,
            tool_name_map=dict(agent_ctx.tool_name_map),
        )
        assert len(lc_tools) == 1

        signed_a = build_tenant_signature_headers(
            TenantContext(
                tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name
            )
        )
        token = bind_forwarded_tenant_headers(signed_a)
        try:
            # LLM-style flat kwargs — what the model actually emitted live,
            # through the REAL ToolNode-style invocation path (arg validation
            # + dispatch) via the tool's async entrypoint.
            await lc_tools[0].ainvoke(
                {
                    "type": "tool_call",
                    "name": lc_tools[0].name,
                    "args": {"situation": "production database outage"},
                    "id": "call-flat-1",
                }
            )
        finally:
            reset_forwarded_tenant_headers(token)

        # Exactly ONE CC hop; flat kwargs landed in the engine input state.
        assert len(captured_cc) == 1
        wire_payload = json.loads(captured_cc[0].content)
        assert wire_payload["input_state"] == {"situation": "production database outage"}
        assert len(fake_jev.calls) == 1
        assert fake_jev.calls[0]["state"]["situation"] == "production database outage"

    async def test_validation_error_fails_fast_single_attempt(
        self, db: AsyncSession, monkeypatch
    ):
        """A decision-input validation failure must NOT retry: the engine
        persists ONE failed result, CH returns it in-band (4xx-class, no
        502), and exactly ONE CC hop occurs (no retry storm)."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "1")

        from app.core.tenant_context import TenantContext
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            build_tenant_signature_headers,
            reset_forwarded_tenant_headers,
            verify_tenant_signature_headers,
        )

        tenant_a, _tenant_b = await create_two_tenants(db)
        tool_a = await _create_decision_tool(db, tenant_a.id, "strict-decision", "approve")
        tool_a.state_preset = {"situation": {"source": "input", "key": "situation"}}
        db.add(tool_a)
        await db.commit()
        _skill, agent_type_a = await _create_agent_with_decision_skill(
            db, tenant_a.id, tool_a, "strict-agent"
        )
        await _seed_provider(db, tenant_a.id)

        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        apply_tenant_scope(db, tenant_a.id)
        agent_ctx = await get_agent_context(agent_type_id=agent_type_a.id, db=db)
        defs = [d for d in agent_ctx.tool_definitions if "strict-decision" in d["function"]["name"]]

        from app.agent_runtime.comm_hub_client import CommHubToolClient
        from app.api.v1.internal.system_tools import (
            DecisionToolExecuteRequest,
            execute_decision_tool_internal,
        )
        from app.communication_hub.api.internal import tool_routing
        from app.services.agents.runtime_executor import AgentRuntimeExecutor
        from app.services.system_one import decision_engine as engine_module

        real_async_client = httpx.AsyncClient
        captured_cc: list[httpx.Request] = []
        fake_jev = FakeJevClient()
        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake_jev)

        async def cc_hop(request: httpx.Request) -> httpx.Response:
            captured_cc.append(request)
            verified = verify_tenant_signature_headers(request.headers)
            assert verified.tenant_id == tenant_a.id
            body = DecisionToolExecuteRequest(**json.loads(request.content))
            engine = create_async_engine(TEST_DB_URL)
            SessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with SessionLocal() as cc_db:
                    response = await execute_decision_tool_internal(
                        body=body,
                        tenant_ctx=TenantContext(
                            tenant_id=verified.tenant_id,
                            slug=verified.slug,
                            name=f"cc-hop-{verified.slug}",
                        ),
                        db=cc_db,
                    )
                    return httpx.Response(200, json={"result": response.result})
            finally:
                await engine.dispose()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/internal/tools/call":
                ch_app = _build_ch_app()
                async with real_async_client(
                    transport=httpx.ASGITransport(app=ch_app),
                    base_url="http://ch-test:8002",
                ) as ch_client:
                    ch_response = await ch_client.post(
                        request.url.path,
                        content=request.content,
                        headers=dict(request.headers),
                    )
                return httpx.Response(
                    ch_response.status_code,
                    content=ch_response.content,
                    headers=ch_response.headers,
                )
            return await cc_hop(request)

        def factory(**kw):
            return real_async_client(
                transport=httpx.MockTransport(handler),
                event_hooks=kw.get("event_hooks"),
            )

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        monkeypatch.setattr(
            tool_routing.settings, "control_center_url", "http://cc-test:8000"
        )

        signed_a = build_tenant_signature_headers(
            TenantContext(
                tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name
            )
        )
        token = bind_forwarded_tenant_headers(signed_a)
        try:
            executor = AgentRuntimeExecutor(data_client=None)
            # Missing required 'situation' → validation error at the engine.
            result = await executor._execute_mcp_tool_ar(
                tool_name="decision____strict-decision",
                tool_args={},
                role_mcp_sessions={},
                agent_type_id=str(agent_type_a.id),
                session_id=str(uuid.uuid4()),
                comm_hub_client=CommHubToolClient(),
            )
        finally:
            reset_forwarded_tenant_headers(token)

        # Fail fast: exactly ONE CC hop — no retry loop anywhere in the path.
        assert len(captured_cc) == 1
        # The model-inference stub was NEVER called (validation precedes it).
        assert len(fake_jev.calls) == 0
        # The error surfaced in-band (no 502 raised through) with the
        # actionable validation message.
        assert result.get("status") == "failed"
        assert "situation" in (result.get("error_message") or "")

    async def test_full_journey_without_skill_binding_is_not_in_toolset(
        self, db: AsyncSession
    ):
        """Companion leg: without the SkillToolBinding the tool never
        enters the agent's toolset (the permission gate is the source of
        allowed tools, not the mere existence of the decision tool)."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.models.agents import (
            AgentInputType,
            AgentOutputType,
            AgentType,
        )
        from app.db.tenant_scoping import apply_tenant_scope

        tenant_a, _tenant_b = await create_two_tenants(db)
        await _create_decision_tool(db, tenant_a.id, "unbound-decision", "approve")
        agent_type = AgentType(
            tenant_id=tenant_a.id,
            name="no-binding-agent",
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.auto,
        )
        db.add(agent_type)
        await db.commit()

        apply_tenant_scope(db, tenant_a.id)
        ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)
        assert "decision____unbound-decision" not in ctx.allowed_tools

    async def test_unready_tool_execution_returns_inband_not_ready_error(
        self, db: AsyncSession, monkeypatch
    ):
        """An enabled-but-unready decision tool (NULL input/output data
        types) is a registered STUB in the toolset; executing it through
        the FULL dispatch chain (AR → CH → CC) returns the actionable
        not-ready error IN-BAND — no 502, no engine run, no model
        inference, exactly ONE CC hop (no retry storm)."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "1")

        from app.core.tenant_context import TenantContext
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            build_tenant_signature_headers,
            reset_forwarded_tenant_headers,
            verify_tenant_signature_headers,
        )

        tenant_a, _tenant_b = await create_two_tenants(db)
        tool_a = await _create_decision_tool(
            db, tenant_a.id, "unready-decision", "approve", ready=False
        )
        _skill, agent_type_a = await _create_agent_with_decision_skill(
            db, tenant_a.id, tool_a, "unready-agent"
        )
        await _seed_provider(db, tenant_a.id)

        # (i) the unready tool IS in the toolset — with the unavailable note.
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        apply_tenant_scope(db, tenant_a.id)
        agent_ctx = await get_agent_context(agent_type_id=agent_type_a.id, db=db)
        assert "decision____unready-decision" in agent_ctx.allowed_tools
        defs = [
            d
            for d in agent_ctx.tool_definitions
            if "unready-decision" in d["function"]["name"]
        ]
        assert len(defs) == 1
        assert "currently unavailable" in defs[0]["function"]["description"]
        # Permissive empty schema — the input data type is unknown.
        assert defs[0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }

        # (ii) execute it through the dispatch chain.
        from app.agent_runtime.comm_hub_client import CommHubToolClient
        from app.api.v1.internal.system_tools import (
            DecisionToolExecuteRequest,
            execute_decision_tool_internal,
        )
        from app.communication_hub.api.internal import tool_routing
        from app.services.agents.runtime_executor import AgentRuntimeExecutor
        from app.services.system_one import decision_engine as engine_module

        real_async_client = httpx.AsyncClient
        captured_cc: list[httpx.Request] = []
        fake_jev = FakeJevClient()
        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake_jev)

        async def cc_hop(request: httpx.Request) -> httpx.Response:
            captured_cc.append(request)
            verified = verify_tenant_signature_headers(request.headers)
            body = DecisionToolExecuteRequest(**json.loads(request.content))
            engine = create_async_engine(TEST_DB_URL)
            SessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            try:
                async with SessionLocal() as cc_db:
                    response = await execute_decision_tool_internal(
                        body=body,
                        tenant_ctx=TenantContext(
                            tenant_id=verified.tenant_id,
                            slug=verified.slug,
                            name=f"cc-hop-{verified.slug}",
                        ),
                        db=cc_db,
                    )
                    return httpx.Response(200, json={"result": response.result})
            finally:
                await engine.dispose()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/internal/tools/call":
                ch_app = _build_ch_app()
                async with real_async_client(
                    transport=httpx.ASGITransport(app=ch_app),
                    base_url="http://ch-test:8002",
                ) as ch_client:
                    ch_response = await ch_client.post(
                        request.url.path,
                        content=request.content,
                        headers=dict(request.headers),
                    )
                return httpx.Response(
                    ch_response.status_code,
                    content=ch_response.content,
                    headers=ch_response.headers,
                )
            return await cc_hop(request)

        def factory(**kw):
            return real_async_client(
                transport=httpx.MockTransport(handler),
                event_hooks=kw.get("event_hooks"),
            )

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        monkeypatch.setattr(
            tool_routing.settings, "control_center_url", "http://cc-test:8000"
        )

        signed_a = build_tenant_signature_headers(
            TenantContext(
                tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name
            )
        )
        token = bind_forwarded_tenant_headers(signed_a)
        try:
            executor = AgentRuntimeExecutor(data_client=None)
            result = await executor._execute_mcp_tool_ar(
                tool_name="decision____unready-decision",
                tool_args={"state": {"severity": "high"}},
                role_mcp_sessions={},
                agent_type_id=str(agent_type_a.id),
                session_id=str(uuid.uuid4()),
                comm_hub_client=CommHubToolClient(),
            )
        finally:
            reset_forwarded_tenant_headers(token)

        # In-band structured error (HTTP 200 through the whole chain —
        # no 502 raised, no retry), with the actionable message.
        assert isinstance(result, dict)
        error = result.get("error") or ""
        assert "unready-decision" in error
        assert "not ready" in error
        assert "Decision Tools" in error
        # Exactly ONE CC hop — no retry storm.
        assert len(captured_cc) == 1
        # The engine NEVER ran: no model inference (stub saw nothing).
        assert len(fake_jev.calls) == 0

    async def test_full_journey_without_skill_binding_is_not_in_toolset(
        self, db: AsyncSession
    ):
        """Companion leg: without the SkillToolBinding the tool never
        enters the agent's toolset (the permission gate is the source of
        allowed tools, not the mere existence of the decision tool)."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.models.agents import (
            AgentInputType,
            AgentOutputType,
            AgentType,
        )
        from app.db.tenant_scoping import apply_tenant_scope

        tenant_a, _tenant_b = await create_two_tenants(db)
        await _create_decision_tool(db, tenant_a.id, "unbound-decision", "approve")
        agent_type = AgentType(
            tenant_id=tenant_a.id,
            name="no-binding-agent",
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.auto,
        )
        db.add(agent_type)
        await db.commit()

        apply_tenant_scope(db, tenant_a.id)
        ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)
        assert "decision____unbound-decision" not in ctx.allowed_tools


class TestDecisionToolReadinessGate:
    """Product-owner rule: a decision tool must be READY (input AND output
    data types configured) before it can be enabled/used."""

    def _question(self, key: str = "approve") -> dict:
        return {
            "ordering": 0,
            "question_key": key,
            "question_type": "choice",
            "instructions": "Approve?",
            "criteria_options": {"yes": "approve", "no": "reject"},
            "is_required": True,
        }

    async def test_create_enabled_without_types_rejected(
        self, db: AsyncSession
    ):
        from app.schemas.decision_tools import DecisionToolCreate
        from app.services.system_one.decision_tool_service import (
            DecisionToolService,
            DecisionToolValidationError,
        )

        tenant_a, _ = await create_two_tenants(db)
        payload = DecisionToolCreate(
            name="no-types-decision", questions=[self._question()]
        )
        with pytest.raises(DecisionToolValidationError) as excinfo:
            await DecisionToolService().create(db, payload, tenant_a.id)
        message = "; ".join(excinfo.value.errors)
        assert "input data type" in message and "output data type" in message

    async def test_enable_without_types_rejected_disable_first_then_clear_works(
        self, db: AsyncSession
    ):
        from app.schemas.decision_tools import DecisionToolCreate, DecisionToolUpdate
        from app.services.system_one.decision_tool_service import (
            DecisionToolService,
            DecisionToolValidationError,
        )

        service = DecisionToolService()
        tenant_a, _ = await create_two_tenants(db)
        input_type = await _create_data_type(
            db, tenant_a.id, "gate-input", ["situation"]
        )
        output_type = await _create_data_type(
            db, tenant_a.id, "gate-output", ["decision"]
        )
        tool = await service.create(
            db,
            DecisionToolCreate(
                name="gate-decision",
                input_data_type_id=input_type.id,
                output_data_type_id=output_type.id,
                questions=[self._question()],
            ),
            tenant_a.id,
        )

        # Clearing a type while enabled → rejected (disable first).
        with pytest.raises(DecisionToolValidationError) as excinfo:
            await service.update(
                db, tool.id, DecisionToolUpdate(input_data_type_id=None), tenant_a.id
            )
        assert "input data type" in "; ".join(excinfo.value.errors)

        # Disabling first, then clearing → allowed (draft shape).
        await service.update(
            db, tool.id, DecisionToolUpdate(enabled=False), tenant_a.id
        )
        tool = await service.update(
            db, tool.id, DecisionToolUpdate(input_data_type_id=None), tenant_a.id
        )
        assert tool.enabled is False and tool.input_data_type_id is None

        # Re-enabling without types → rejected with actionable message.
        with pytest.raises(DecisionToolValidationError) as excinfo:
            await service.update(
                db, tool.id, DecisionToolUpdate(enabled=True), tenant_a.id
            )
        message = "; ".join(excinfo.value.errors)
        assert "cannot be enabled" in message and "input data type" in message

    async def test_update_with_raw_dict_questions_succeeds_and_sets_types(
        self, db: AsyncSession
    ):
        """Live 500 regression: PUT update returned
        ``AttributeError: 'dict' object has no attribute 'question_key'``.

        Root cause: ``DecisionToolService.update`` called
        ``payload.model_dump(exclude_unset=True)`` which re-serialized the
        nested pydantic question models into PLAIN DICTS, then
        ``_build_questions`` accessed ``.question_key`` on them.

        Exactly what the router passes (a pydantic ``DecisionToolUpdate``
        whose questions pydantic coerces from raw dicts) must succeed, set
        the input/output data types, and leave the tool READY + enabled.
        """
        from app.db.models.decision_tools import DecisionTool
        from app.schemas.decision_tools import DecisionToolUpdate
        from app.services.system_one.decision_tool_service import (
            DecisionToolService,
            is_decision_tool_ready,
        )

        service = DecisionToolService()
        tenant_a, _ = await create_two_tenants(db)
        input_type = await _create_data_type(
            db, tenant_a.id, "upd-input", ["situation"]
        )
        output_type = await _create_data_type(
            db, tenant_a.id, "upd-output", ["decision"]
        )

        # Unready draft: no types, disabled, one question.
        tool = DecisionTool(
            tenant_id=tenant_a.id,
            name="dict-questions-decision",
            purpose="draft",
            enabled=False,
        )
        db.add(tool)
        await db.commit()
        await db.refresh(tool)

        # RAW DICT question — what a router/payload round-trip produces.
        payload = DecisionToolUpdate.model_validate(
            {
                "input_data_type_id": str(input_type.id),
                "output_data_type_id": str(output_type.id),
                "enabled": True,
                "questions": [self._question("approve")],
            }
        )
        tool = await service.update(db, tool.id, payload, tenant_a.id)

        assert tool.input_data_type_id == input_type.id
        assert tool.output_data_type_id == output_type.id
        assert tool.enabled is True
        assert is_decision_tool_ready(tool)
        assert [q.question_key for q in tool.questions] == ["approve"]
        assert tool.questions[0].criteria_options == {
            "yes": "approve", "no": "reject"
        }

    async def test_update_accepts_plain_dict_questions_directly(
        self, db: AsyncSession
    ):
        """Service-boundary robustness: questions supplied to
        ``DecisionToolService.update`` as raw dicts (no pydantic coercion)
        must also work — no AttributeError, questions persisted."""
        from app.schemas.decision_tools import (
            DecisionToolCreate,
            DecisionToolUpdate,
        )
        from app.services.system_one.decision_tool_service import (
            DecisionToolService,
        )

        service = DecisionToolService()
        tenant_a, _ = await create_two_tenants(db)
        input_type = await _create_data_type(
            db, tenant_a.id, "raw-in", ["situation"]
        )
        output_type = await _create_data_type(
            db, tenant_a.id, "raw-out", ["decision"]
        )
        tool = await service.create(
            db,
            DecisionToolCreate(
                name="raw-dict-decision",
                input_data_type_id=input_type.id,
                output_data_type_id=output_type.id,
                enabled=True,
                questions=[self._question("approve")],
            ),
            tenant_a.id,
        )

        # Build the update payload, then force questions back to plain
        # dicts (simulating a stored/dumped shape reaching the service).
        # model_copy(update=...) bypasses validation, so the dicts survive.
        payload = DecisionToolUpdate(purpose="updated via dicts").model_copy(
            update={"questions": [self._question("approve2")]}
        )

        updated = await service.update(db, tool.id, payload, tenant_a.id)
        # Question set is REPLACED atomically (delete + rebuild).
        assert [q.question_key for q in updated.questions] == ["approve2"]
        # state_preset as raw dicts also tolerated (dict-vs-model hazard).
        payload2 = DecisionToolUpdate().model_copy(
            update={
                "state_preset": {
                    "situation": {"source": "input", "key": "situation"}
                }
            }
        )
        updated = await service.update(db, tool.id, payload2, tenant_a.id)
        assert updated.state_preset == {
            "situation": {"source": "input", "key": "situation"}
        }

    async def test_ready_tool_in_toolset_with_populated_schema(
        self, db: AsyncSession
    ):
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        tenant_a, _ = await create_two_tenants(db)
        tool = await _create_decision_tool(
            db, tenant_a.id, "ready-decision", "approve"
        )
        skill, agent_type = await _create_agent_with_decision_skill(
            db, tenant_a.id, tool, "ready-agent"
        )

        apply_tenant_scope(db, tenant_a.id)
        ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)
        assert "decision____ready-decision" in ctx.allowed_tools
        defs = [
            d for d in ctx.tool_definitions if "ready-decision" in d["function"]["name"]
        ]
        assert len(defs) == 1
        params = defs[0]["function"]["parameters"]
        # Schema is populated from the input data type fields.
        assert set(params["properties"]) == {"situation", "severity"}
        assert params["required"] == ["situation", "severity"]

    async def test_unready_enabled_tool_stubbed_in_toolset_with_warning(
        self, db: AsyncSession, caplog
    ):
        """Enabled-but-unready tools are registered as STUBS (not excluded):
        they stay in allowed_tools with a definition whose description
        carries the unavailable note, so the LLM knows the tool exists but
        must REPORT its unavailability instead of calling it."""
        import logging

        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.tenant_scoping import apply_tenant_scope

        tenant_a, _ = await create_two_tenants(db)
        tool = await _create_decision_tool(
            db, tenant_a.id, "legacy-decision", "approve", ready=False
        )
        skill, agent_type = await _create_agent_with_decision_skill(
            db, tenant_a.id, tool, "legacy-agent"
        )

        apply_tenant_scope(db, tenant_a.id)
        with caplog.at_level(logging.WARNING):
            ctx = await get_agent_context(agent_type_id=agent_type.id, db=db)
        assert "decision____legacy-decision" in ctx.allowed_tools
        defs = [
            d
            for d in ctx.tool_definitions
            if "legacy-decision" in d["function"]["name"]
        ]
        assert len(defs) == 1
        assert "currently unavailable" in defs[0]["function"]["description"]
        # Permissive empty schema (input data type unknown).
        assert defs[0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }
        assert any(
            "legacy-decision" in rec.message and "not ready" in rec.message
            for rec in caplog.records
        )

    async def test_unready_tool_not_stubbed_via_load_tool_definitions(
        self, db
    ):
        """The AR ``_load_tool_definitions`` decision branch mirrors the
        stub: the unready tool resolves with the unavailable note in its
        description instead of being dropped."""
        from app.db.tenant_scoping import apply_tenant_scope
        from app.services.agents.runtime_executor import AgentRuntimeExecutor

        tenant_a, _ = await create_two_tenants(db)
        await _create_decision_tool(
            db, tenant_a.id, "unready-exec-tool", "approve", ready=False
        )

        apply_tenant_scope(db, tenant_a.id)
        executor = AgentRuntimeExecutor(data_client=None)
        defs, name_map = await executor._load_tool_definitions(
            {"decision____unready-exec-tool"}, db, include_all_system_tools=False
        )

        matching = [
            d for d in defs if "unready-exec-tool" in d["function"]["name"]
        ]
        assert len(matching) == 1
        assert "currently unavailable" in matching[0]["function"]["description"]
        assert matching[0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }
        assert any(
            v == "decision____unready-exec-tool" for v in name_map.values()
        )


class TestDerivedQuestionsJourney:
    """Owner-approved auto-derivation: a READY tool with NO manual questions
    executes using questions derived 1:1 from its OUTPUT data type."""

    async def test_executed_decision_uses_output_type_derived_questions(
        self, db: AsyncSession, monkeypatch
    ):
        from app.db.models.decision_tools import DecisionTool
        from app.services.system_one import decision_engine as engine_module
        from app.services.system_one.decision_engine import (
            DecisionExecutionEngine,
        )

        tenant_a, _tenant_b = await create_two_tenants(db)

        # Output type: enum (with descriptions) + number + string + boolean.
        from app.db.models.agent_data_type import AgentDataType

        output_type = AgentDataType(
            tenant_id=tenant_a.id,
            name=f"derived-out-{uuid.uuid4().hex[:6]}",
            slug=f"derived-out-{uuid.uuid4().hex[:6]}",
            fields=[
                {
                    "name": "verdict",
                    "type": "enum",
                    "enum_values": [
                        {"value": "go", "description": "proceed"},
                        "hold",
                    ],
                },
                {"name": "confidence_score", "type": "number"},
                {"name": "rationale", "type": "string"},
                {"name": "escalate", "type": "boolean"},
            ],
        )
        input_type = await _create_data_type(
            db, tenant_a.id, "derived-input", ["situation"]
        )
        db.add(output_type)
        await db.commit()
        await db.refresh(output_type)

        tool = DecisionTool(
            tenant_id=tenant_a.id,
            name="derived-decision",
            purpose="Decide with derived questions",
            input_data_type_id=input_type.id,
            output_data_type_id=output_type.id,
            enabled=True,
            # NO questions — derivation kicks in.
        )
        db.add(tool)
        await db.commit()

        await _seed_provider(db, tenant_a.id)

        # Stub model inference returning answers matching the derived keys.
        class DerivedFakeJev:
            def __init__(self):
                self.calls = []

            async def evaluate(self, *, base_url, api_key, model, state, questions, **kw):
                self.calls.append({"questions": sorted(questions)})
                answers = {
                    "verdict": {
                        "type": "choice",
                        "choice": "go",
                        "probabilities": {"go": 0.9, "hold": 0.1},
                        "confidence": 0.9,
                    },
                    "confidence_score": {
                        "type": "score", "score": 4, "confidence": 0.9,
                    },
                    "rationale": {"type": "choice", "choice": "all clear", "confidence": 0.9},
                    "escalate": {"type": "noul", "noul": 0, "confidence": 1.0},
                }
                return {
                    "model": model,
                    "answers": {k: answers[k] for k in questions},
                }

        fake = DerivedFakeJev()
        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake)

        from app.services.system_one.decision_tool_service import DecisionToolService

        # Re-fetch with eager loading (questions + joined data types) so the
        # engine never lazy-loads in async context.
        tool = await DecisionToolService().get(db, tool.id, tenant_a.id)
        engine = DecisionExecutionEngine()
        result = await engine.execute(
            db,
            tool,
            input_state={"situation": "production outage"},
            tenant_id=tenant_a.id,
        )

        assert result.status.value == "completed"
        assert len(fake.calls) == 1
        # Questions derived from the output data type fields:
        assert fake.calls[0]["questions"] == [
            "confidence_score", "escalate", "rationale", "verdict",
        ]
        answers = result.answers["answers"]
        assert set(answers) == {
            "verdict", "confidence_score", "rationale", "escalate",
        }
        assert answers["verdict"]["choice"] == "go"
        assert answers["confidence_score"]["score"] == 4
        assert answers["escalate"]["noul"] == 0
        assert result.outcome.value == "act"

    async def test_engine_without_questions_or_output_type_fails(
        self, db: AsyncSession, monkeypatch
    ):
        from app.db.models.decision_tools import DecisionTool
        from app.services.system_one import decision_engine as engine_module
        from app.services.system_one.decision_engine import (
            DecisionExecutionEngine,
        )

        tenant_a, _ = await create_two_tenants(db)
        tool = DecisionTool(
            tenant_id=tenant_a.id,
            name="empty-decision",
            purpose="no questions, no output type",
            enabled=True,
        )
        db.add(tool)
        await db.commit()
        await db.refresh(tool)

        class NeverCalled:
            async def evaluate(self, **kw):  # pragma: no cover
                raise AssertionError("provider must not be called")

        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: NeverCalled())

        from app.services.system_one.decision_tool_service import DecisionToolService

        tool = await DecisionToolService().get(db, tool.id, tenant_a.id)
        result = await DecisionExecutionEngine().execute(
            db, tool, input_state={}, tenant_id=tenant_a.id
        )
        assert result.status.value == "failed"
        assert "no output data type" in (result.error_message or "")

    async def test_manual_questions_override_derivation(
        self, db: AsyncSession, monkeypatch
    ):
        """Manual questions win: a tool WITH authored questions ignores the
        output data type fields for the question set."""
        from app.db.models.decision_tools import DecisionTool, DecisionToolQuestion
        from app.db.models.agent_data_type import AgentDataType
        from app.services.system_one import decision_engine as engine_module
        from app.services.system_one.decision_engine import (
            DecisionExecutionEngine,
        )

        tenant_a, _ = await create_two_tenants(db)
        output_type = AgentDataType(
            tenant_id=tenant_a.id,
            name=f"override-out-{uuid.uuid4().hex[:6]}",
            slug=f"override-out-{uuid.uuid4().hex[:6]}",
            fields=[{"name": "should_not_be_asked", "type": "string"}],
        )
        input_type = await _create_data_type(
            db, tenant_a.id, "override-input", ["situation"]
        )
        db.add(output_type)
        await db.commit()
        await db.refresh(output_type)

        tool = DecisionTool(
            tenant_id=tenant_a.id,
            name="override-decision",
            purpose="manual wins",
            input_data_type_id=input_type.id,
            output_data_type_id=output_type.id,
            enabled=True,
        )
        tool.questions.append(
            DecisionToolQuestion(
                question_key="manual_q",
                question_type="choice",
                instructions="Manual?",
                criteria_options={"yes": "y", "no": "n"},
                ordering=0,
            )
        )
        db.add(tool)
        await db.commit()
        await db.refresh(tool)

        await _seed_provider(db, tenant_a.id)

        class ManualFakeJev:
            def __init__(self):
                self.calls = []

            async def evaluate(self, *, model, questions, **kw):
                self.calls.append({"questions": sorted(questions)})
                return {
                    "model": model,
                    "answers": {
                        "manual_q": {
                            "type": "choice", "choice": "yes", "confidence": 0.95,
                        }
                    },
                }

        fake = ManualFakeJev()
        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake)
        from app.services.system_one.decision_tool_service import DecisionToolService

        tool = await DecisionToolService().get(db, tool.id, tenant_a.id)
        result = await DecisionExecutionEngine().execute(
            db, tool, input_state={"situation": "x"}, tenant_id=tenant_a.id
        )
        assert result.status.value == "completed"
        assert fake.calls[0]["questions"] == ["manual_q"]
        assert "should_not_be_asked" not in result.answers["answers"]


def _build_ch_app():
    """FastAPI app hosting the REAL CH tool_routing router (no middleware —
    the signed header binding the ControlPlaneMiddleware would perform is
    applied directly via bind_forwarded_tenant_headers)."""
    from fastapi import FastAPI

    from app.communication_hub.api.internal import tool_routing

    app = FastAPI()
    app.include_router(tool_routing.router)
    return app


# ── Guardrail/budget enforcement + usage metering on decision executions ─────


class TestDecisionGuardrailAndMetering:
    """Decision calls must hit the same pre-call guardrail checks as
    regular model usage (blocked BEFORE the vendor call) and record usage +
    provider/model identity on the persisted execution result."""

    async def _seed_provider_row(self, db, tenant_id, model="jev-latest"):
        from app.core.credential_vault import get_vault
        from app.db.models.system_one_provider_config import (
            SystemOneProviderConfig,
            SystemOneProviderType,
        )

        provider = SystemOneProviderConfig(
            tenant_id=tenant_id,
            provider_type=SystemOneProviderType.typesafe,
            display_name=f"Guardrail Provider {uuid.uuid4().hex[:6]}",
            base_url="http://localhost:9999/v1",
            default_model=model,
            encrypted_api_key=get_vault().encrypt("sk-guardrail-journey-key"),
            enabled=True,
        )
        db.add(provider)
        await db.commit()
        await db.refresh(provider)
        return provider

    async def _seed_breached_guardrail(self, db, provider, model_name):
        """ACTIVE terminate-posture guardrail whose latest posture snapshot
        is BREACHED (budget/spend exhausted)."""
        from app.db.models.model_guardrail_configuration import (
            ModelGuardrailConfiguration,
            ModelGuardrailEnforcementPosture,
            ModelGuardrailPeriod,
            ModelUsageUnit,
        )
        from app.db.models.model_usage_posture import (
            ModelUsagePosture,
            ModelUsagePosturePeriod,
            ModelUsagePostureState,
        )
        from app.db.models.agents import ModelConfig, ModelProvider

        # FIX-20261014-003000: decision guardrails are keyed via
        # decision_provider_id with config_source='decision_provider' —
        # exactly the rows the decision pre-call check evaluates.
        guard = ModelGuardrailConfiguration(
            config_source="decision_provider",
            decision_provider_id=provider.id,
            model_id=None,
            model_name=model_name,
            period=ModelGuardrailPeriod.day,
            limit_value=100,
            unit=ModelUsageUnit.k,
            enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
            is_active=True,
        )
        db.add(guard)
        await db.flush()
        db.add(
            ModelUsagePosture(
                model_guardrail_configuration_id=guard.id,
                model_id=provider.id,
                posture_period=ModelUsagePosturePeriod.day,
                posture_state=ModelUsagePostureState.breached,
                usage_value=150,
                limit_value=100,
            )
        )
        await db.commit()
        await db.refresh(guard)
        return guard

    async def test_breached_guardrail_blocks_decision_before_vendor_call(
        self, db: AsyncSession, monkeypatch
    ):
        from app.db.models.decision_tools import DecisionTool, DecisionToolQuestion
        from app.services.system_one import decision_engine as engine_module
        from app.services.system_one.decision_engine import DecisionExecutionEngine
        from app.services.system_one.decision_tool_service import DecisionToolService

        tenant_a, _ = await create_two_tenants(db)
        provider = await self._seed_provider_row(db, tenant_a.id)
        await self._seed_breached_guardrail(db, provider, provider.default_model)

        tool = DecisionTool(
            tenant_id=tenant_a.id,
            name="guardrailed-decision",
            purpose="blocked pre-call",
            enabled=True,
        )
        tool.questions.append(
            DecisionToolQuestion(
                question_key="approve",
                question_type="noul",
                instructions="Approve?",
                ordering=0,
            )
        )
        db.add(tool)
        await db.commit()
        await db.refresh(tool)

        class MustNotDispatch:
            calls: list = []

            async def evaluate(self, **kw):
                MustNotDispatch.calls.append(kw)
                raise AssertionError("vendor must not be called")

        monkeypatch.setattr(
            engine_module, "get_system_one_client", lambda pt: MustNotDispatch()
        )

        tool = await DecisionToolService().get(db, tool.id, tenant_a.id)
        result = await DecisionExecutionEngine().execute(
            db, tool, input_state={}, tenant_id=tenant_a.id
        )

        assert MustNotDispatch.calls == [], "no vendor call when blocked"
        assert result.status.value == "failed"
        assert "blocked" in (result.error_message or "").lower()
        assert "guardrail" in (result.error_message or "").lower()
        # blocked attempts persist NO answers / no usage
        assert result.answers is None

    async def test_successful_execution_records_usage_and_provider_identity(
        self, db: AsyncSession, monkeypatch
    ):
        from app.db.models.decision_tools import DecisionTool, DecisionToolQuestion
        from app.services.system_one import decision_engine as engine_module
        from app.services.system_one.decision_engine import DecisionExecutionEngine
        from app.services.system_one.decision_tool_service import DecisionToolService

        tenant_a, _ = await create_two_tenants(db)
        provider = await self._seed_provider_row(db, tenant_a.id)

        tool = DecisionTool(
            tenant_id=tenant_a.id,
            name="metered-decision",
            purpose="usage metering",
            enabled=True,
        )
        tool.questions.append(
            DecisionToolQuestion(
                question_key="approve",
                question_type="noul",
                instructions="Approve?",
                ordering=0,
            )
        )
        db.add(tool)
        await db.commit()
        await db.refresh(tool)

        class MeteredFakeJev:
            async def evaluate(self, *, base_url, api_key, model, state, questions, **kw):
                return {
                    "model": model,
                    "usage": {"total_tokens": 321},
                    "answers": {
                        "approve": {"type": "noul", "noul": 1.0},
                    },
                }

        monkeypatch.setattr(
            engine_module, "get_system_one_client", lambda pt: MeteredFakeJev()
        )

        tool = await DecisionToolService().get(db, tool.id, tenant_a.id)
        result = await DecisionExecutionEngine().execute(
            db, tool, input_state={}, tenant_id=tenant_a.id
        )

        assert result.status.value == "completed"
        provider_identity = result.answers["provider"]
        assert provider_identity["provider_id"] == str(provider.id)
        assert provider_identity["model_name"] == provider.default_model
        assert provider_identity["provider_display_name"] == provider.display_name
        assert provider_identity["usage"] == {"total_tokens": 321}
        # no credential material anywhere in the persisted answers
        assert "sk-guardrail-journey-key" not in repr(result.answers)
        # the result survives a reload (persisted, not just in-memory)
        result_id = result.id
        expected_model = provider.default_model
        expected_display = provider.display_name
        db.expire_all()
        from sqlalchemy import select as _select

        from app.db.models.results import DecisionExecutionResult

        reloaded = (
            await db.execute(
                _select(DecisionExecutionResult).where(
                    DecisionExecutionResult.id == result_id
                )
            )
        ).scalar_one()
        assert reloaded.answers["provider"]["model_name"] == expected_model
        assert reloaded.answers["provider"]["provider_display_name"] == expected_display
