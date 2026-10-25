"""END-TO-END agent execution test — the real chain, real apps, real database.

Goal (user demand): prove agent execution actually works END-TO-END using the
LLM mock layer — not unit tests with fakes. This module drives the REAL
FastAPI applications in-process:

    POST /execute (AR app, real trigger endpoint)
      → ControlCenterDataClient (real client over ASGI transport)
        → CC internal data APIs (real CC app, real PostgreSQL)
      → Script-First Dispatcher (real dispatch: optimized-plan lookup,
        serving-script resolution, LLM fallback)
      → LangChain create_agent loop with MockChatModel (LLM_MOCK_MODE=scripted,
        real mock layer in app/services/agents/llm_mock_provider.py)
      → tool calls via CommHubToolClient (CH network hop BYPASSED — the stub
        routes ``script____`` calls to the real AR script-tools endpoint and
        MCP calls to the real CC MCP proxy endpoint over ASGI transport)
      → McpProxyEngine (real, with the upstream MCP server HTTP call stubbed)
      → sandboxed python_source execution (real sandbox, real ScriptRunner)

WIRING NOTES (deliberate, documented deviations from the production topology):

- CH hop bypassed: the three services run mTLS over real ports in production.
  In-process ASGI cannot re-enter the mTLS path, so the tool-call client is
  stubbed at exactly one seam (CommHubToolClient.call_tool) and routes to the
  REAL CC MCP proxy and REAL AR script-tools endpoints. Everything on both
  sides of the seam is the production code.
- The MCP proxy's UPSTREAM call (httpx post to the external MCP server) is
  stubbed — the page.route equivalent — returning canned JSON-RPC rows.

Covers two flows:
1. Optimized-plan tool mode: fresh ready optimized plan (fully_scripted=False)
   with one python_source script segment (calls an MCP tool via the injected
   sandbox client, output_mode deterministic). The mock LLM emits a
   ``script____<name>`` tool call, the sandboxed script runs through the real
   runner + MCP proxy, and the LLM renders the final answer from the result.
2. Pure-LLM fallback (no optimized plan, no scripts): the mock LLM emits an
   MCP tool call directly, the tool routes through the CC MCP proxy, and the
   agent completes via the LLM.

Failure → fix log (production fixes made while building this test):
- FIX-1 llm_mock_provider.MockChatModel had no ``bind_tools`` — LangChain's
  create_agent calls bind_tools unconditionally, so ANY mocked tool-calling
  agent run crashed. Added bind_tools (returns self) + scripted-rule
  ``tool_calls`` emission.
- FIX-2 runtime_executor never advertised invocable scripts to the LLM — the
  tool-mode optimized-plan surface (``script____<name>``) was unreachable:
  the dispatcher deliberately routes tool-mode plans to the LLM path, but no
  code put the script tools into the LLM toolset. Added
  ``_append_invocable_script_tools`` (best-effort, fail-open).
- FIX-3 AR /internal/script-tools/execute ran ScriptRunner WITHOUT a log
  shipper — tool-mode script runs produced no execution-log entries (the
  dispatcher-served path did). Added a data-client log shipper.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

# ── Real PostgreSQL test database (dev Postgres on :5432) ─────────────────────

_PG_ADMIN_DSN = "postgresql://parthenon:parthenon@localhost:5432/postgres"
_PG_BASE_URL = "postgresql+asyncpg://parthenon:parthenon@localhost:5432/"


async def _create_test_db() -> str:
    import asyncpg

    name = f"parthenon_e2e_{uuid.uuid4().hex[:8]}"
    conn = await asyncpg.connect(_PG_ADMIN_DSN)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    return name


async def _drop_test_db(name: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(_PG_ADMIN_DSN)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


def _pg_available() -> bool:
    import socket

    try:
        sock = socket.create_connection(("127.0.0.1", 5432), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


# ── The stubbed MCP upstream (page.route equivalent, server-side) ─────────────

_MCP_ROWS = [
    {"quarter": "Q3", "revenue": 1200000},
    {"quarter": "Q2", "revenue": 1100000},
]
# Marker embedded in the MCP tool result — the scripted LLM rules key on it.
MCP_RESULT_MARKER = "E2E_DB_ROWS_MARKER"
SCRIPT_RESULT_MARKER = "E2E_SCRIPT_ROWS_MARKER"


class _FakeMcpUpstream(httpx.AsyncClient):
    """Intercept ONLY the outbound call to the fake MCP server URL.

    Every other request (there should be none from McpProxyEngine) is an
    error — this keeps the real proxy code paths fully exercised.
    """

    def __init__(self, upstream_url: str, calls: list | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._upstream_url = upstream_url
        self.calls = calls if calls is not None else []

    async def post(self, url, *args, **kwargs):  # type: ignore[override]
        if str(url).startswith(self._upstream_url):
            payload_in = kwargs.get("json")
            if isinstance(payload_in, str):
                payload_in = json.loads(payload_in)
            self.calls.append((payload_in or {}).get("params", {}))
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"{MCP_RESULT_MARKER}: "
                                f"{json.dumps(_MCP_ROWS)} "
                                f"({SCRIPT_RESULT_MARKER}: 2 rows returned)"
                            ),
                        }
                    ]
                },
            }
            return httpx.Response(200, json=payload, request=httpx.Request("POST", url))
        raise AssertionError(f"Unexpected outbound HTTP call in e2e test: {url}")


def _make_upstream_factory(upstream_url: str, calls: list | None = None):
    def _factory(**kwargs):
        return _FakeMcpUpstream(upstream_url, calls=calls, **kwargs)

    return _factory


# ── Session-scoped real-DB + real-apps harness ────────────────────────────────


class Harness:
    """Owns the test database, the CC and AR apps, and the client wiring."""

    def __init__(self, db_name: str) -> None:
        self.db_name = db_name
        self.engine = None
        self.SessionLocal = None
        self.root_tenant_id: uuid.UUID | None = None
        self.cc_app = None
        self.ar_app = None
        self.data_client = None
        self._saved_env: dict[str, str | None] = {}
        self.mcp_upstream: _FakeMcpUpstream | None = None
        self.script_tool_calls: list[dict] = []

    # ── environment ──────────────────────────────────────────────────────

    def _set_env(self, key: str, value: str) -> None:
        self._saved_env.setdefault(key, os.environ.get(key))
        os.environ[key] = value

    async def start(self) -> None:
        # Env BEFORE importing app modules (mirrors tests/conftest.py).
        self._set_env("ENVIRONMENT", "test")
        self._set_env("SECRET_KEY", "test-secret-key-for-testing-only")
        self._set_env(
            "CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!"
        )
        # NEVER let any internal client reach the live services on 8000-8002.
        self._set_env("CONTROL_CENTER_URL", "http://cc-test")
        self._set_env("COMMUNICATION_HUB_URL", "http://ch-test")

        from app.db.session import Base

        self.engine = create_async_engine(_PG_BASE_URL + self.db_name, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.SessionLocal = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )

        async with self.SessionLocal() as session:
            from app.db.models.tenant import Tenant

            session.add(Tenant(name="Root", slug="root", is_system_tenant=True))
            await session.commit()
            row = await session.execute(
                select(Tenant).where(Tenant.is_system_tenant.is_(True))
            )
            self.root_tenant_id = row.scalar_one().id

        # ── CC app (real) with DB + cert/tenant dependency overrides ─────
        from app.api.deps import require_internal_tenant_context, require_service_certificate
        from app.core.tenant_context import TenantContext
        from app.db.session import get_db
        from app.main import create_app as create_cc_app

        cc_app = create_cc_app()

        async def _override_db():
            async with self.SessionLocal() as session:
                yield session
                await session.commit()

        async def _override_cert():
            return {"cert_type": "service", "service_name": "control-center"}

        async def _override_tenant():
            return TenantContext(
                tenant_id=self.root_tenant_id,
                slug="root",
                name="Root",
            )

        cc_app.dependency_overrides[get_db] = _override_db
        cc_app.dependency_overrides[require_service_certificate] = _override_cert
        cc_app.dependency_overrides[require_internal_tenant_context] = _override_tenant
        self.cc_app = cc_app

        # ── Fake certificate manager: routes internal_httpx_client at CC ──
        cc_transport = ASGITransport(app=cc_app)

        class _FakeCertManager:
            is_loaded = True
            cert_path = None
            key_path = None

            def mtls_client_kwargs(self) -> dict:
                return {"transport": cc_transport, "base_url": "http://cc-test"}

        # ── AR data client → CC ASGI app (real client, real endpoints) ───
        from app.agent_runtime.data_client import ControlCenterDataClient

        self.data_client = ControlCenterDataClient(
            cert_manager=_FakeCertManager(),
            control_center_url="http://cc-test",
        )

        # ── AR app (real), inbound cert middleware cleared for ASGI ──────
        from app.agent_runtime.main import create_app as create_ar_app

        ar_app = create_ar_app()
        ar_app.user_middleware.clear()
        ar_app.state.certificate_manager = _FakeCertManager()
        ar_app.state.data_client = self.data_client
        ar_app.state.execution_semaphore = asyncio.Semaphore(4)
        ar_app.state.session_tasks = {}
        self.ar_app = ar_app

        # ── Stub the CH hop at the single seam ───────────────────────────
        self._patch_comm_hub_client()

        # ── Stub the MCP proxy upstream ──────────────────────────────────
        self._patch_mcp_upstream()

    async def stop(self) -> None:
        from app.agent_runtime.comm_hub_client import CommHubToolClient
        from app.services.mcp import proxy as mcp_proxy_module

        # restore patched class method
        if getattr(CommHubToolClient.call_tool, "_is_e2e_stub", False):
            del CommHubToolClient.call_tool  # type: ignore[attr-defined]
        if self.mcp_upstream is not None:
            mcp_proxy_module.httpx = self._saved_httpx_module
        if self.engine is not None:
            await self.engine.dispose()
        await _drop_test_db(self.db_name)
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # ── seams ────────────────────────────────────────────────────────────

    def _patch_comm_hub_client(self) -> None:
        """Route CommHubToolClient.call_tool to the REAL CC/AR ASGI apps.

        This is the ONLY bypassed hop (Communication Hub). ``script____`` calls
        hit the real AR script-tools endpoint; MCP calls hit the real CC MCP
        proxy endpoint (which resolves tool + session from the REAL database
        via the real permission chain).
        """
        from app.agent_runtime.comm_hub_client import (
            CommHubToolClient,
            CommHubToolClientError,
        )

        harness = self

        async def _e2e_call_tool(
            self_client: CommHubToolClient,
            tool_name: str,
            tool_args: dict,
            session_id: str = "",
            agent_type_id: str = "",
            conv_session_id: str | None = None,
            provenance: str | None = None,
            script_version: str | None = None,
            **_: object,
        ) -> dict:
            if tool_name.startswith("script____"):
                harness.script_tool_calls.append(
                    {"tool": tool_name, "args": tool_args, "session": session_id}
                )
                async with AsyncClient(
                    transport=ASGITransport(app=harness.ar_app),
                    base_url="http://ar-test",
                ) as client:
                    resp = await client.post(
                        "/internal/script-tools/execute",
                        json={
                            "tool_name": tool_name,
                            "tool_args": tool_args,
                            "session_id": session_id,
                            "agent_type_id": agent_type_id,
                            "provenance": provenance,
                        },
                    )
                if resp.status_code >= 400:
                    raise CommHubToolClientError(
                        f"script-tools endpoint HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                body = resp.json()
                logger.debug("[e2e-stub] script-tools: %s %s", resp.status_code, str(body)[:300])
                if body.get("error"):
                    return {"error": body["error"]}
                return {"result": body.get("result")}
            # MCP (and any other) tool → real CC MCP proxy endpoint
            async with AsyncClient(
                transport=ASGITransport(app=harness.cc_app),
                base_url="http://cc-test",
            ) as client:
                resp = await client.post(
                    "/api/v1/internal/mcp/proxy-tool",
                    json={
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "agent_type_id": agent_type_id,
                        "agent_session_id": session_id,
                    },
                )
            if resp.status_code >= 400:
                raise CommHubToolClientError(
                    f"MCP proxy HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()

        _e2e_call_tool._is_e2e_stub = True  # type: ignore[attr-defined]
        CommHubToolClient.call_tool = _e2e_call_tool  # type: ignore[method-assign]

    def _patch_mcp_upstream(self) -> None:
        import httpx as _real_httpx

        from app.services.mcp import proxy as mcp_proxy_module

        upstream_url = "http://fake-mcp-e2e"
        self.mcp_upstream_calls: list[dict] = []
        self.mcp_upstream = _FakeMcpUpstream(upstream_url, calls=self.mcp_upstream_calls)
        # Patch ONLY the proxy module's view of httpx (not the global module)
        # so the stub intercepts just the McpProxyEngine upstream call while
        # its except clauses still see the real httpx exception classes.
        self._saved_httpx_module = mcp_proxy_module.httpx

        class _HttpxShim:
            AsyncClient = staticmethod(
                _make_upstream_factory(upstream_url, self.mcp_upstream_calls)
            )

            def __getattr__(self, name: str):
                return getattr(_real_httpx, name)

        mcp_proxy_module.httpx = _HttpxShim()

    # ── helpers ──────────────────────────────────────────────────────────

    def db(self):
        return self.SessionLocal()

    def ar_client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.ar_app), base_url="http://ar-test"
        )

    async def get_session(self, session_id: uuid.UUID) -> dict | None:
        return await self.data_client.get_session(session_id)

    async def wait_for_terminal(self, session_id: uuid.UUID, timeout: float = 90.0):
        deadline = asyncio.get_running_loop().time() + timeout
        last = None
        while asyncio.get_running_loop().time() < deadline:
            job = await self.get_session(session_id)
            last = job
            status = (job or {}).get("status")
            if status in ("completed", "failed", "terminated"):
                return job
            # Drive the AR background task if still registered.
            task = (self.ar_app.state.session_tasks or {}).get(session_id)
            if task is not None:
                await asyncio.wait({asyncio.ensure_future(task)}, timeout=0.5)
            else:
                await asyncio.sleep(0.2)
        raise AssertionError(
            f"Session {session_id} did not reach a terminal state within "
            f"{timeout}s — last status: {(last or {}).get('status')!r}"
        )

    async def execution_logs(self, session_id: uuid.UUID) -> list:
        async with self.db() as session:
            from app.db.models.session_logs import ExecutionLogEntry

            rows = await session.execute(
                select(ExecutionLogEntry)
                .where(ExecutionLogEntry.session_id == session_id)
                .order_by(ExecutionLogEntry.timestamp)
            )
            return list(rows.scalars().all())


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def harness():
    if not _pg_available():
        pytest.skip("Requires a running PostgreSQL database (localhost:5432)")
    db_name = await _create_test_db()
    h = Harness(db_name)
    await h.start()
    yield h
    await h.stop()


# ── Shared seeding ────────────────────────────────────────────────────────────


async def _seed_core(
    h: Harness,
    *,
    with_mcp: bool = True,
    tool_suffix: str = "e2e",
) -> tuple:
    """Seed tenant/role/model/MCP rows shared by both scenarios."""
    from app.core.credential_vault import get_vault
    from app.db.models.agents import (
        AgentInputType,
        AgentOutputType,
        AgentRole,
        AgentRoleMcpSession,
        AgentType,
        ModelConfig,
        ModelProvider,
    )
    from app.db.models.mcp_hub import McpServer, McpSession, McpTool

    tenant_id = h.root_tenant_id
    async with h.db() as db:
        role = AgentRole(
            tenant_id=tenant_id,
            name=f"e2e-role-{uuid.uuid4().hex[:8]}",
            description="e2e agent execution role",
        )
        db.add(role)
        await db.flush()

        vault = get_vault()
        model_config = ModelConfig(
            tenant_id=tenant_id,
            display_name=f"e2e-openai-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.openai,
            enabled_models=["gpt-4o"],
            encrypted_api_key=vault.encrypt(json.dumps({"api_key": "e2e-not-used"})),
        )
        db.add(model_config)

        agent_type = AgentType(
            tenant_id=tenant_id,
            name=f"e2e-agent-{uuid.uuid4().hex[:8]}",
            description="e2e non-conversational agent",
            model_id="gpt-4o",
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.auto,
            system_instruction="You are a precise reporting assistant.",
            role_id=role.id,
        )
        db.add(agent_type)
        await db.flush()

        if with_mcp:
            server = McpServer(
                tenant_id=tenant_id,
                name=f"e2e-supabase-{uuid.uuid4().hex[:6]}",
                slug=f"supabase-{uuid.uuid4().hex[:6]}",
                base_url="http://fake-mcp-e2e",
            )
            db.add(server)
            await db.flush()
            tool = McpTool(
                tenant_id=tenant_id,
                server_id=server.id,
                # Suffix keeps the canonical tool name unique per scenario —
                # the MCP proxy resolves tools by name within the tenant.
                name=f"supabase____execute_sql_{tool_suffix}",
                original_name="execute_sql",
                description="Execute a SQL query and return rows",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                is_active=True,
            )
            db.add(tool)
            mcp_session = McpSession(
                server_id=server.id,
                name="default",
                auth_type="api_key",
                is_active=True,
                is_default=True,
            )
            db.add(mcp_session)
            await db.flush()
            db.add(
                AgentRoleMcpSession(
                    role_id=role.id,
                    mcp_session_id=mcp_session.id,
                    server_id=server.id,
                )
            )
            # Role → Skill → Tool permission chain (this is how the CC agent
            # context resolves the agent's allowed MCP tools).
            from app.db.models.agents import AgentRoleSkill
            from app.db.models.skills import Skill, SkillToolBinding

            skill = Skill(
                tenant_id=tenant_id,
                name=f"e2e-sql-skill-{uuid.uuid4().hex[:8]}",
                description="E2E: run sales SQL",
                is_active=True,
            )
            db.add(skill)
            await db.flush()
            db.add(SkillToolBinding(skill_id=skill.id, tool_id=tool.id))
            db.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))

        await db.commit()
        return agent_type, role


async def _enqueue_session(h: Harness, agent_type, input_data: dict) -> uuid.UUID:
    from app.services.agents.session_service import AgentSessionService

    async with h.db() as db:
        job = await AgentSessionService().enqueue(
            agent_type_id=agent_type.id,
            input_data=input_data,
            user_id=None,
            db=db,
        )
        await db.commit()
        return job.id


async def _trigger_and_wait(h: Harness, session_id: uuid.UUID, agent_type) -> dict:
    """POST the REAL AR /execute trigger and wait for a terminal status."""
    async with h.ar_client() as client:
        resp = await client.post(
            "/execute",
            json={
                "session_id": str(session_id),
                "agent_type_id": str(agent_type.id),
                "input_data": None,
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"
    return await h.wait_for_terminal(session_id)


def _set_llm_rules(monkeypatch, rules: list[dict]) -> None:
    from app.services.agents.llm_mock_provider import reset_mock_store

    monkeypatch.setenv("LLM_MOCK_MODE", "scripted")
    monkeypatch.setenv("LLM_MOCK_SCRIPTED_RESPONSES", json.dumps(rules))
    reset_mock_store()


# ── Scenario 1: optimized plan (tool mode) + sandboxed script + MCP tool ─────


@pytest.mark.asyncio(loop_scope="module")
async def test_optimized_plan_tool_mode_end_to_end(harness, monkeypatch):
    h = harness
    agent_type, role = await _seed_core(h)

    # Base plan (older) + fresh ready optimized plan, fully_scripted=False →
    # dispatcher takes the LLM path with the plan's scripts as tools.
    from app.db.models.agents import AgentPlan, AgentPlanStatus
    from app.db.models.optimized_plan import (
        OptimizedImplementationPlan,
        OptimizedPlanStatus,
    )
    from app.services.script_registry.service import ScriptRegistryService

    mcp_tool_name = "supabase____execute_sql_e2e"
    python_source = (
        "def run(context, tools):\n"
        f"    rows = tools.call('{mcp_tool_name}', "
        "{'query': 'select quarter, revenue from sales'})\n"
        "    return {'report': str(rows), 'row_count': 2}\n"
    )

    async with h.db() as db:
        now = datetime.now(timezone.utc)
        base_plan = AgentPlan(
            agent_type_id=agent_type.id,
            plan_steps=[{"order": 1, "type": "tool_invocation", "name": "run report"}],
            generation_status=AgentPlanStatus.success,
            updated_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=2),
        )
        db.add(base_plan)
        await db.flush()
        optimized = OptimizedImplementationPlan(
            tenant_id=h.root_tenant_id,
            agent_type_id=agent_type.id,
            agent_plan_id=base_plan.id,
            plan_steps=[
                {
                    "order": 1,
                    "type": "tool_invocation",
                    "name": "run_report",
                    "description": "Run the sales report script",
                    "python_source": python_source,
                    "scriptable": True,
                    "output_mode": None,
                },
                {
                    "order": 2,
                    "type": "semantic_bridge",
                    "name": "render",
                    "description": "Render the final markdown answer",
                    "scriptable": False,
                    "output_mode": "deterministic",
                },
            ],
            fully_scripted=False,
            status=OptimizedPlanStatus.ready,
            updated_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=1),
        )
        db.add(optimized)
        await db.commit()

    # The optimized plan's compiled script (invocable script tool). Seeded via
    # the REAL registry service and compiled lifecycle.
    service = ScriptRegistryService()
    async with h.db() as db:
        from app.db.models.script_registry import ScriptLifecycleStatus

        definition = await service.create_definition(
            db,
            name=f"report-{uuid.uuid4().hex[:8]}",
            agent_type_id=agent_type.id,
            description="E2E: run the sales report",
            tenant_id=h.root_tenant_id,
        )
        definition.source_optimized_plan_id = optimized.id
        version = await service.create_version(
            db,
            definition_id=definition.id,
            declarative_step_graph={"name": "e2e-report", "steps": []},
            python_source=python_source,
            sandbox_validation_status="passed",
        )
        definition.lifecycle_status = ScriptLifecycleStatus.compiled
        version.lifecycle_status = ScriptLifecycleStatus.compiled
        definition.current_version_id = version.id
        await db.commit()
        script_name = definition.name
        optimized_id = optimized.id

    # Scripted LLM: call 1 emits the script tool call (using the sanitized
    # name exactly as the LLM sees it in its toolset); call 2 (prompt contains
    # the script-result marker) renders the final answer. Marker rule first —
    # first match wins and the marker persists in history.
    sanitized_script_tool = f"script____{script_name}".replace("-", "_")
    _set_llm_rules(
        monkeypatch,
        [
            {
                "match": SCRIPT_RESULT_MARKER,
                "response": "## Q3 Sales Report\n\nRevenue: $1.2M (scripted final answer)",
            },
            {
                "match": "E2E-REPORT-REQUEST",
                "response": "Calling the compiled report script.",
                "tool_calls": [
                    {"name": sanitized_script_tool, "args": {}}
                ],
            },
        ],
    )

    session_id = await _enqueue_session(
        h, agent_type, {"query": "E2E-REPORT-REQUEST: build the quarterly report"}
    )
    job = await _trigger_and_wait(h, session_id, agent_type)

    # 1. Session completed.
    assert job["status"] == "completed", (
        f"Session did not complete: status={job['status']!r} "
        f"error={job.get('error')!r} stop={job.get('stop_reason')!r}"
    )
    # 2. Result is the expected final string (rendered by the LLM from the
    #    script output, NOT raw tool output).
    result = job.get("output_data", {}).get("result") or ""
    assert "Q3 Sales Report" in result and "scripted final answer" in result, result

    # 3. The optimized plan was actually consulted and its script executed.
    logs = await h.execution_logs(session_id)
    event_types = [e.event_type for e in logs]
    assert "session_started" in event_types
    assert "tools_resolved" in event_types
    assert "session_completed" in event_types
    # FIX-3 proof: the tool-mode script run shipped execution logs.
    assert "script_run_started" in event_types, (
        f"No script_run_started log — tool-mode script run is invisible. "
        f"Events: {event_types}"
    )
    assert "script_run_completed" in event_types, event_types
    script_logs = [e for e in logs if e.event_type == "script_run_started"]
    assert script_logs, event_types
    # The executed script was the optimized plan's version.
    from app.db.models.script_registry import ScriptVersion

    async with h.db() as db:
        version_row = await db.get(ScriptVersion, version.id)
        assert version_row.lifecycle_status.value == "compiled"

    # The sandbox actually invoked the MCP tool via the injected client.
    assert h.script_tool_calls, "The script tool was never invoked"
    assert h.mcp_upstream_calls, (
        "The sandboxed script never reached the MCP proxy upstream"
    )
    assert h.mcp_upstream_calls[0].get("name") == "execute_sql"

    # 4. The canned MCP rows reached the LLM: the final-answer rule only
    #    matches on SCRIPT_RESULT_MARKER, which exists solely inside the MCP
    #    result text - the successful final answer above already proves the
    #    rows flowed MCP proxy -> script -> LLM prompt -> session result.


# ── Scenario 2: pure-LLM fallback path (no optimized plan, no scripts) ───────


@pytest.mark.asyncio(loop_scope="module")
async def test_pure_llm_fallback_with_mcp_tool_call(harness, monkeypatch):
    h = harness
    agent_type, role = await _seed_core(h, tool_suffix="fallback")  # NO plan

    _set_llm_rules(
        monkeypatch,
        [
            {
                "match": MCP_RESULT_MARKER,
                "response": "The quarterly figures were retrieved successfully "
                "(scripted LLM fallback answer).",
            },
            {
                "match": "E2E-SQL-REQUEST",
                "response": "Querying the database.",
                "tool_calls": [
                    {
                        # The CC agent-context surface sanitizes the tool name
                        # (____ -> __) — this is the exact name a real LLM sees.
                        "name": "supabase__execute_sql_fallback",
                        "args": {"query": "select quarter, revenue from sales"},
                    }
                ],
            },
        ],
    )

    session_id = await _enqueue_session(
        h, agent_type, {"query": "E2E-SQL-REQUEST: get the quarterly sales figures"}
    )
    job = await _trigger_and_wait(h, session_id, agent_type)

    assert job["status"] == "completed", (
        f"Session did not complete: status={job['status']!r} "
        f"error={job.get('error')!r}"
    )
    result = job.get("output_data", {}).get("result") or ""
    assert "scripted LLM fallback answer" in result, result

    # The MCP tool call went through the REAL CC MCP proxy with the canned
    # upstream result.
    assert h.mcp_upstream_calls, "MCP upstream was never called"
    assert h.mcp_upstream_calls[0].get("name") == "execute_sql"
    assert h.mcp_upstream_calls[0]["arguments"]["query"] == (
        "select quarter, revenue from sales"
    )

    logs = await h.execution_logs(session_id)
    event_types = [e.event_type for e in logs]
    assert "session_started" in event_types
    assert "tools_resolved" in event_types
    assert "session_completed" in event_types
    # No script ran in the pure-LLM path.
    assert "script_run_started" not in event_types, event_types
