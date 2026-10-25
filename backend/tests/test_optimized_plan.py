"""Optimize & Verify as a command-prompt-driven special agent execution.

Covers the re-scoped model:

- the ``optimize-and-verify`` command mission text + interpolation + toolset;
- the optimization SYSTEM TOOLS (CC-side, routed by CH): reading the base plan,
  authoring (sandbox-validated) script versions, executing them in the REAL
  sandbox (the verification primitive), persisting the optimized plan; and
- the stripped ``OptimizedPlanService`` persistence (generate/record/feedback).

The bespoke optimizer (authoring prompt, generate→test→refine loop, composition
normalization/chaining/splitting) is removed — the agent does authoring +
verification through these tools.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission, require_service_certificate
from app.core.resource_types import RT_AGENT
from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentPlan,
    AgentPlanStatus,
    AgentType,
)
from app.db.models.optimized_plan import OptimizedImplementationPlan, OptimizedPlanStatus
from app.db.session import get_db
from app.main import create_app
from app.services.agents.command_prompts import (
    OPTIMIZE_AND_VERIFY_COMMAND,
    OPTIMIZE_AND_VERIFY_SLUG,
    OPTIMIZE_AND_VERIFY_TOOLS,
    build_command_mission,
    command_tool_names,
    get_command_prompt,
    seed_command_prompts,
)
from app.services.agents.optimized_plan_service import OptimizedPlanService
from app.services.tenancy.root_tenant import ensure_root_tenant, get_root_tenant_id

_GOOD_SOURCE = (
    "def run(context, tools):\n"
    "    return {'result': 'hello', 'value': context.get('x', 0)}\n"
)

_INVALID_SOURCE = "import os\n"


# ── Command prompt (pure) ─────────────────────────────────────────────────────


class TestCommandPrompt:
    def test_command_mission_interpolates_agent_type_id(self):
        agent_type_id = uuid.uuid4()
        mission = build_command_mission(OPTIMIZE_AND_VERIFY_COMMAND, agent_type_id=agent_type_id)
        assert str(agent_type_id) in mission
        assert "{agent_type_id}" not in mission

    def test_command_mission_describes_tools_and_rules(self):
        mission = build_command_mission(OPTIMIZE_AND_VERIFY_COMMAND, agent_type_id="x")
        # The mission names the tools and the mandatory authoring/verify rules.
        for tool in OPTIMIZE_AND_VERIFY_TOOLS:
            assert tool in mission
        assert "MINIMIZE STEPS" in mission
        assert "VERIFY" in mission
        assert "execute_script" in mission

    def test_command_mission_inline_source_save_on_success_flow(self):
        """The mission mandates: execute full inline source (no drafts),
        iterate on source, save ONLY after a successful execution."""
        mission = build_command_mission(OPTIMIZE_AND_VERIFY_COMMAND, agent_type_id="x")
        assert "do not save drafts" in mission
        assert "FULL source to `execute_script`" in mission
        assert "modify the source and execute" in mission
        assert "Only after a successful execution, save it via" in mission
        # No size/line constraints on the authored script.
        assert "line" not in mission.lower()

    def test_command_toolset(self):
        tools = command_tool_names(OPTIMIZE_AND_VERIFY_SLUG)
        assert tools == OPTIMIZE_AND_VERIFY_TOOLS
        assert "generate_script" in tools and "execute_script" in tools

    def test_unknown_command_has_no_toolset(self):
        assert command_tool_names("nope") == []

    async def test_get_command_prompt_falls_back_to_builtin(self, db_session):
        # No seed required — the in-code fallback serves the mission.
        prompt = await get_command_prompt(db_session, OPTIMIZE_AND_VERIFY_SLUG)
        assert prompt is not None
        assert prompt.prompt_text == OPTIMIZE_AND_VERIFY_COMMAND

    async def test_seed_command_prompts_is_idempotent(self, db_session):
        await seed_command_prompts(db_session)
        await seed_command_prompts(db_session)
        from sqlalchemy import select

        from app.db.models.command_prompt import CommandPrompt

        rows = (
            await db_session.execute(
                select(CommandPrompt).where(CommandPrompt.slug == OPTIMIZE_AND_VERIFY_SLUG)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].prompt_text == OPTIMIZE_AND_VERIFY_COMMAND


# ── Optimization system tools (via internal client, real SQLite DB) ───────────


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "agent-runtime"}

    return override


@pytest_asyncio.fixture
async def internal_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Client with service-cert + internal tenant deps overridden, real DB."""
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

    async with SessionLocal() as session:
        await ensure_root_tenant(session)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def agent_type_plan(test_engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an AgentType + base AgentPlan, returning (agent_type_id, plan_id)."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    agent_type_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    async with SessionLocal() as session:
        session.add(
            AgentType(
                id=agent_type_id,
                name=f"opt-{agent_type_id.hex[:8]}",
                input_type=AgentInputType.none,
                output_type=AgentOutputType.markdown,
            )
        )
        session.add(
            AgentPlan(
                id=plan_id,
                agent_type_id=agent_type_id,
                generation_status=AgentPlanStatus.success,
                plan_steps=[
                    {"order": 1, "type": "tool_call", "name": "Fetch contact",
                     "description": "Fetch the contact"},
                ],
            )
        )
        await session.commit()
    return agent_type_id, plan_id


@pytest_asyncio.fixture
async def ar_boundary(monkeypatch):
    """Stub the CC→CH→AR egress at the ``CommunicationHubClient`` seam.

    Emulates Agent Runtime's ``/internal/script-tools/execute`` inline path:
    the submitted ``python_source`` runs in the REAL sandbox with a
    session-bound tool client, returning the AR ``{"result", "error"}``
    contract. Captures the payload for boundary assertions.
    """
    import asyncio
    from types import SimpleNamespace

    from app.agent_runtime.scripts.sandbox import SandboxCaps, run_sandboxed_python
    from app.services.control_center import comm_hub_client

    class _FakeArToolClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def call_tool(
            self, tool_name: str, arguments: dict[str, Any], *,
            session_id: str, agent_type_id: str,
            provenance: str = "llm", script_version: str | None = None,
        ) -> Any:
            self.calls.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "session_id": session_id,
                    "agent_type_id": agent_type_id,
                }
            )
            return {"name": "Ada"}

    tool_client = _FakeArToolClient()
    captured: dict[str, Any] = {}

    async def fake_forward_sandboxed_script(
        self, *, python_source: str, session_id: str, agent_type_id: str,
        input_context: dict[str, Any] | None = None,
        tenant_context: Any = None,
    ) -> dict[str, Any]:
        captured["python_source"] = python_source
        captured["session_id"] = session_id
        captured["agent_type_id"] = agent_type_id
        captured["input_context"] = input_context
        try:
            loop = asyncio.get_running_loop()
            output = await asyncio.to_thread(
                run_sandboxed_python,
                python_source,
                tool_client=tool_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                script_version_label="inline",
                input_context=input_context,
                caps=SandboxCaps(),
                loop=loop,
            )
        except Exception as exc:  # emulate AR's structured error surfacing
            first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            return {"result": None, "error": f"{type(exc).__name__}: {first}"}
        return {"result": output, "error": None}

    monkeypatch.setattr(
        comm_hub_client.CommunicationHubClient,
        "forward_sandboxed_script",
        fake_forward_sandboxed_script,
    )
    return SimpleNamespace(captured=captured, tool_client=tool_client)


pytestmark = pytest.mark.usefixtures("ar_boundary")


async def _call(client: AsyncClient, tool: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/internal/system-tools/{tool}",
        json={"session_id": str(uuid.uuid4()), "tool_args": tool_args},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


class TestOptimizationSystemTools:
    async def test_get_implementation_plan(self, internal_client, agent_type_plan):
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "get-implementation-plan",
            {"agent_type_id": str(agent_type_id)},
        )
        assert result["agent_type_id"] == str(agent_type_id)
        assert result["steps"] and result["steps"][0]["name"] == "Fetch contact"

    async def test_generate_script_valid_source_returns_draft_version(
        self, internal_client, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "generate-script",
            {
                "agent_type_id": str(agent_type_id),
                "name": "fetch-contact",
                "description": "fetch + greet",
                "python_source": _GOOD_SOURCE,
            },
        )
        assert result["status"] == "draft"
        assert result["version_id"]
        assert result["definition_id"]

    async def test_generate_script_rejects_unsafe_source(
        self, internal_client, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "generate-script",
            {
                "agent_type_id": str(agent_type_id),
                "name": "bad",
                "python_source": _INVALID_SOURCE,
            },
        )
        assert result["status"] == "failed"
        assert result["reason"]
        assert result["version_id"]  # still persisted as a failed draft

    async def test_execute_script_is_the_verification_primitive(
        self, internal_client, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        generated = await _call(
            internal_client, "generate-script",
            {
                "agent_type_id": str(agent_type_id),
                "name": "greet",
                "python_source": _GOOD_SOURCE,
            },
        )
        version_id = generated["version_id"]

        result = await _call(
            internal_client, "execute-script",
            {"script_version_id": version_id, "input": {"x": 41}},
        )
        assert "error" not in result
        assert result["output"]["result"] == "hello"
        assert result["output"]["value"] == 41

    async def test_execute_script_reports_sandbox_error(
        self, internal_client, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        # A source that compiles but fails at runtime in the sandbox.
        broken = "def run(context, tools):\n    return {'r': missing_name}\n"
        generated = await _call(
            internal_client, "generate-script",
            {"agent_type_id": str(agent_type_id), "name": "broken", "python_source": broken},
        )
        result = await _call(
            internal_client, "execute-script",
            {"script_version_id": generated["version_id"]},
        )
        assert result.get("error")

    async def test_execute_script_inline_source_no_save_required(
        self, internal_client, agent_type_plan
    ):
        """execute_script accepts FULL inline python_source — no save required."""
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": _GOOD_SOURCE,
                "input": {"x": 41},
            },
        )
        assert "error" not in result
        assert result["output"]["result"] == "hello"
        assert result["output"]["value"] == 41

    async def test_execute_script_inline_compile_error_is_structured(
        self, internal_client, agent_type_plan
    ):
        """A sandbox compile failure on inline source returns a structured error."""
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": _INVALID_SOURCE,  # import os → compile error
            },
        )
        assert result.get("error")
        assert "Sandbox" in result["error"]  # structured sandbox rejection

    async def test_execute_script_inline_does_not_persist(
        self, internal_client, agent_type_plan, db_session
    ):
        """Executing inline source must NOT create any script definition/version."""
        from sqlalchemy import select

        from app.db.models.script_registry import ScriptDefinition

        agent_type_id, _ = agent_type_plan
        await _call(
            internal_client, "execute-script",
            {"agent_type_id": str(agent_type_id), "python_source": _GOOD_SOURCE},
        )
        result = await db_session.execute(
            select(ScriptDefinition).where(
                ScriptDefinition.agent_type_id == agent_type_id
            )
        )
        assert result.scalars().all() == []

    async def test_save_only_after_successful_execution(
        self, internal_client, agent_type_plan, db_session
    ):
        """Save-on-success flow: execute inline OK → generate_script persists
        the working source (no draft-first flow)."""
        agent_type_id, _ = agent_type_plan
        executed = await _call(
            internal_client, "execute-script",
            {"agent_type_id": str(agent_type_id), "python_source": _GOOD_SOURCE},
        )
        assert "error" not in executed

        saved = await _call(
            internal_client, "generate-script",
            {
                "agent_type_id": str(agent_type_id),
                "name": "verified-greet",
                "python_source": _GOOD_SOURCE,
            },
        )
        assert saved["status"] == "draft"
        assert saved["version_id"]

        # Round-trip: the saved version executes too.
        rerun = await _call(
            internal_client, "execute-script",
            {"script_version_id": saved["version_id"], "input": {"x": 7}},
        )
        assert rerun["output"]["value"] == 7

    async def test_execute_script_routes_inline_source_through_ar_boundary(
        self, internal_client, agent_type_plan, ar_boundary
    ):
        """The inline source reaches Agent Runtime verbatim with the session
        identity — CC does NOT execute it locally (segregation)."""
        agent_type_id, _ = agent_type_plan
        source = (
            "def run(context, tools):\n"
            "    return {'result': 'hello', 'value': context.get('x', 0)}\n"
        )
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": source,
                "input": {"x": 41},
            },
        )
        assert "error" not in result
        assert result["output"]["result"] == "hello"
        # The FULL source was forwarded — not re-executed in CC.
        assert ar_boundary.captured["python_source"] == source
        assert ar_boundary.captured["input_context"] == {"x": 41}

    async def test_execute_script_tools_facade_is_not_none(
        self, internal_client, agent_type_plan, ar_boundary
    ):
        """A script that calls MCP tools verifies: the sandbox's ``tools``
        facade is non-None and the tool call executes (live-defect
        regression: the facade was None → TypeError 'NoneType' not callable)."""
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": (
                    "def run(context, tools):\n"
                    "    project = tools.call('supabase____get_project', {'id': 'p-1'})\n"
                    "    return {'project': project['name']}\n"
                ),
            },
        )
        assert "error" not in result, result
        assert result["output"] == {"project": "Ada"}
        assert ar_boundary.tool_client.calls[0]["tool_name"] == "supabase____get_project"

    async def test_execute_script_surfaces_ar_structured_error(
        self, internal_client, agent_type_plan, monkeypatch
    ):
        """AR's structured sandbox error becomes the tool's error response."""
        from app.services.control_center import comm_hub_client

        async def fake_error(self, **kwargs):
            return {"result": None, "error": "SandboxCompileError: import forbidden"}

        monkeypatch.setattr(
            comm_hub_client.CommunicationHubClient,
            "forward_sandboxed_script",
            fake_error,
        )
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_plan[0]),
                "python_source": _INVALID_SOURCE,
            },
        )
        assert result.get("error") == "SandboxCompileError: import forbidden"

    async def test_generate_optimized_plan_persists_ready_plan(
        self, internal_client, agent_type_plan, db_session
    ):
        agent_type_id, plan_id = agent_type_plan
        generated = await _call(
            internal_client, "generate-script",
            {
                "agent_type_id": str(agent_type_id),
                "name": "optimized",
                "python_source": _GOOD_SOURCE,
            },
        )
        version_id = generated["version_id"]

        steps = [
            {
                "order": 1,
                "type": "tool_invocation",
                "name": "Execute workflow script",
                "python_source": _GOOD_SOURCE,
                "script_version_id": version_id,
                "output_mode": "deterministic",
            },
        ]
        plan_result = await _call(
            internal_client, "generate-optimized-plan",
            {
                "agent_type_id": str(agent_type_id),
                "steps": steps,
                "fully_scripted": True,
                "output_mode": "deterministic",
                "status": "ready",
            },
        )
        assert plan_result["status"] == "ready"
        assert plan_result["fully_scripted"] is True
        assert plan_result["steps_count"] == 1
        plan_id_str = plan_result["id"]

        # The persisted plan row carries the composition (no user-facing
        # verification log — verification happens inside the agent's REAL run).
        plan = await db_session.get(OptimizedImplementationPlan, uuid.UUID(plan_id_str))
        assert plan.status == OptimizedPlanStatus.ready
        assert not hasattr(plan, "verification_log") or plan.verification_log is None

    async def test_get_optimized_implementation_plan_and_list_scripts(
        self, internal_client, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        generated = await _call(
            internal_client, "generate-script",
            {"agent_type_id": str(agent_type_id), "name": "s1", "python_source": _GOOD_SOURCE},
        )
        # list_scripts surfaces the authored script + its source.
        listed = await _call(
            internal_client, "list-scripts", {"agent_type_id": str(agent_type_id)}
        )
        names = [s["name"] for s in listed["scripts"]]
        assert "s1" in names
        # get_script returns the single script with python_source.
        got = await _call(
            internal_client, "get-script",
            {"agent_type_id": str(agent_type_id), "name": "s1"},
        )
        assert got["found"] is True
        assert got["python_source"] == _GOOD_SOURCE

    async def test_get_optimized_plan_not_found(self, internal_client, agent_type_plan):
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "get-optimized-implementation-plan",
            {"agent_type_id": str(agent_type_id)},
        )
        assert result["found"] is False

    async def test_get_scripts_self_reflection(
        self, internal_client, agent_type_plan
    ):
        """get_scripts returns the agent's script definitions + versions +
        python_source + lifecycle (self-reflection surface)."""
        agent_type_id, _ = agent_type_plan
        await _call(
            internal_client, "generate-script",
            {"agent_type_id": str(agent_type_id), "name": "sr1", "python_source": _GOOD_SOURCE},
        )
        result = await _call(
            internal_client, "get-scripts", {"agent_type_id": str(agent_type_id)}
        )
        entry = next(s for s in result["scripts"] if s["name"] == "sr1")
        assert entry["python_source"] == _GOOD_SOURCE
        assert entry["version_id"] is not None
        assert entry["lifecycle_status"] is not None

    async def test_get_execution_log_returns_entries(
        self, internal_client, agent_type_plan
    ):
        """get_execution_log returns the agent's recent execution-log entries
        (self-reflection surface); empty state is a valid result."""
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "get-execution-log", {"agent_type_id": str(agent_type_id)}
        )
        assert result["agent_type_id"] == str(agent_type_id)
        assert isinstance(result["entries"], list)



# ── Stripped OptimizedPlanService persistence ────────────────────────────────


class _FakeResult:
    def scalar_one_or_none(self):
        return None

    def scalars(self):
        class _Empty:
            def all(self):
                return []

        return _Empty()


class _FakeDb:
    def __init__(self):
        self.added = []

    async def execute(self, *a, **k):
        return _FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None

    async def get(self, *a, **k):
        return None


class TestOptimizedPlanServicePersistence:
    async def test_generate_optimized_plan_upserts_and_associates(self, monkeypatch):
        service = OptimizedPlanService()

        associated: list[tuple[bool, list]] = []

        async def _fake_associate(db, agent_type, base_plan, optimized, steps, fully):
            associated.append((fully, steps))

        monkeypatch.setattr(service, "_associate_scripts", _fake_associate)

        agent_type = _agent_type()
        base_plan = _base_plan()
        steps = [{"order": 1, "name": "s", "python_source": _GOOD_SOURCE}]
        optimized = await service.generate_optimized_plan(
            _FakeDb(), agent_type=agent_type, base_plan=base_plan,
            steps=steps, fully_scripted=True, output_mode="deterministic",
        )
        assert optimized.status == OptimizedPlanStatus.ready
        assert optimized.fully_scripted is True
        assert optimized.plan_steps[-1]["output_mode"] == "deterministic"
        assert len(associated) == 1 and associated[0][0] is True

    async def test_non_ready_plan_does_not_promote_scripts(self, monkeypatch):
        """A failed / needs_feedback plan must never leave a serving artifact."""
        service = OptimizedPlanService()

        associated: list[int] = []

        async def _fake_associate(*a: Any, **k: Any) -> None:
            associated.append(1)

        monkeypatch.setattr(service, "_associate_scripts", _fake_associate)

        optimized = await service.generate_optimized_plan(
            _FakeDb(), agent_type=_agent_type(), base_plan=_base_plan(),
            steps=[], fully_scripted=False, status="needs_feedback",
        )
        assert optimized.status == OptimizedPlanStatus.needs_feedback
        assert associated == []

    async def test_feedback_requires_existing_plan(self):
        with pytest.raises(ValueError):
            await OptimizedPlanService().add_feedback(_agent_type(), _FakeDb(), "change it")


# ── fakes ─────────────────────────────────────────────────────────────────────


def _agent_type() -> Any:
    import types

    return types.SimpleNamespace(
        id=uuid.uuid4(), tenant_id=None, name="t", output_type="markdown",
    )


def _base_plan() -> Any:
    import types

    return types.SimpleNamespace(id=uuid.uuid4(), plan_steps=[])


def _existing_plan_row(**overrides: Any) -> Any:
    import types

    defaults = {
        "id": uuid.uuid4(),
        "agent_type_id": uuid.uuid4(),
        "agent_plan_id": uuid.uuid4(),
        "plan_steps": [],
        "fully_scripted": False,
        "status": OptimizedPlanStatus.ready,
        "error": None,
        "feedback_comments": None,
        "generated_at": None,
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


class _FakeResultWithRow:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDbWithRow(_FakeDb):
    def __init__(self, row):
        super().__init__()
        self._row = row

    async def execute(self, *a, **k):
        return _FakeResultWithRow(self._row)

    async def get(self, key, *a, **k):
        return self._row


# ── POST /agents/types/{id}/optimize-plan endpoint (launch/trigger outcome) ────


def _allow_agent_update():
    def override():
        return {"sub": "optimize-plan-test", "roles": ["admin"]}

    return override


@pytest.fixture
def _bypass_public_auth():
    from unittest.mock import patch

    from app.middleware.auth import JWTAuthMiddleware
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "optimize-plan-test"}
        return await call_next(request)

    async def passthrough_resolution(self, request, call_next):
        request.state.tenancy_enabled = False
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch), patch.object(
        TenantResolutionMiddleware, "dispatch", passthrough_resolution
    ):
        yield


@pytest_asyncio.fixture
async def public_client(
    test_engine, _bypass_public_auth
) -> AsyncGenerator[AsyncClient, None]:
    """App client for the public agent endpoints (JWT + permission bypassed)."""
    app = create_app()
    app.dependency_overrides[require_permission(RT_AGENT, "update")] = _allow_agent_update()
    app.dependency_overrides[require_permission(RT_AGENT, "read")] = _allow_agent_update()
    app.dependency_overrides[require_permission(RT_AGENT, "execute")] = _allow_agent_update()

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _query_plans(test_engine, agent_type_id):
    """Return all OptimizedImplementationPlan rows for an agent type."""
    from sqlalchemy import select

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        result = await session.execute(
            select(OptimizedImplementationPlan).where(
                OptimizedImplementationPlan.agent_type_id == agent_type_id
            )
        )
        return result.scalars().all()


class TestLaunchOptimizeInjection:
    async def test_optimize_launch_injects_command_markers_and_mission(
        self, public_client, agent_type_plan, monkeypatch
    ):
        """`optimize: true` on the launch turns the execution into the
        optimize-and-verify command: the ``__command`` markers are injected and
        the prompt is the command mission + the user's real task."""
        agent_type_id, _ = agent_type_plan
        from app.api.v1 import agents as agents_module

        captured: dict = {}

        async def fake_launch(**kwargs):
            captured.update(kwargs)
            return {
                "session_id": str(uuid.uuid4()),
                "triggered": True,
                "trigger_error": None,
            }

        monkeypatch.setattr(agents_module._lifecycle_handler, "launch", fake_launch)

        async def fake_get_session(session_id, db):
            from datetime import datetime, UTC

            return {
                "id": str(session_id),
                "agent_type_id": str(agent_type_id),
                "status": "queued",
                "started_at": None,
                "completed_at": None,
                "error_message": "",
                "created_at": datetime.now(UTC).isoformat(),
            }

        monkeypatch.setattr(agents_module._session_service, "get_session", fake_get_session)

        resp = await public_client.post(
            "/api/v1/agents/sessions",
            json={
                "agent_type_id": str(agent_type_id),
                "input_data": {"message": "compile the quarterly report"},
                "optimize": True,
            },
        )
        assert resp.status_code in (200, 202), resp.text

        input_data = captured["input_data"]
        assert input_data["__command"] == "optimize-and-verify"
        assert input_data["__command_agent_type_id"] == str(agent_type_id)
        assert "Real task for this run" in input_data["message"]
        # The user's real task is preserved in the mission prompt.
        assert "compile the quarterly report" in input_data["message"]

    async def test_optimize_false_launches_unchanged(
        self, public_client, agent_type_plan, monkeypatch
    ):
        """Without the opt-in flag the launch input_data passes through untouched."""
        agent_type_id, _ = agent_type_plan
        from app.api.v1 import agents as agents_module

        captured: dict = {}

        async def fake_launch(**kwargs):
            captured.update(kwargs)
            return {
                "session_id": str(uuid.uuid4()),
                "triggered": True,
                "trigger_error": None,
            }

        monkeypatch.setattr(agents_module._lifecycle_handler, "launch", fake_launch)

        async def fake_get_session(session_id, db):
            from datetime import datetime, UTC

            return {
                "id": str(session_id),
                "agent_type_id": str(agent_type_id),
                "status": "queued",
                "started_at": None,
                "completed_at": None,
                "error_message": "",
                "created_at": datetime.now(UTC).isoformat(),
            }

        monkeypatch.setattr(agents_module._session_service, "get_session", fake_get_session)

        resp = await public_client.post(
            "/api/v1/agents/sessions",
            json={
                "agent_type_id": str(agent_type_id),
                "input_data": {"message": "just run normally"},
            },
        )
        assert resp.status_code in (200, 202), resp.text
        assert "__command" not in (captured["input_data"] or {})


class TestRetireOptimizedPlanEndpoint:
    async def test_retire_marks_plans_retired_not_deleted(
        self, public_client, agent_type_plan, test_engine
    ):
        """Retiring MARKS the optimized plan rows `retired` (kept for
        reference) — it must NOT delete them. The next Run Agent flow finds no
        `ready` plan and offers optimization again."""
        agent_type_id, _ = agent_type_plan

        # Seed an optimized plan via the service.
        from sqlalchemy import select

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.agents.optimized_plan_service import OptimizedPlanService

        async with SessionLocal() as session:
            result = await session.execute(
                select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
            )
            base_plan = result.scalar_one()
            agent_type = await session.get(AgentType, agent_type_id)
            await OptimizedPlanService().generate_optimized_plan(
                session,
                agent_type=agent_type,
                base_plan=base_plan,
                steps=[{"name": "s1", "python_source": "def run(context, tools):\n    return {'result': 1}"}],
                fully_scripted=True,
                status=OptimizedPlanStatus.ready,
            )
            await session.commit()

        plans = await _query_plans(test_engine, agent_type_id)
        assert any(p.status == OptimizedPlanStatus.ready for p in plans)

        resp = await public_client.post(
            f"/api/v1/agents/types/{agent_type_id}/optimized-plan/retire"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["retired"] is True
        assert body["plans_removed"] >= 1

        # The rows REMAIN for reference, marked retired — never deleted.
        plans = await _query_plans(test_engine, agent_type_id)
        assert len(plans) >= 1
        assert all(p.status == OptimizedPlanStatus.retired for p in plans)

    async def test_retired_plan_does_not_gate_execution(
        self, public_client, agent_type_plan, test_engine
    ):
        """After retirement, the dispatcher freshness gate must NOT consider
        the retired plan — get_fresh_optimized_plan returns None."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from app.services.script_registry import ScriptRegistryService

        agent_type_id, _ = agent_type_plan

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.agents.optimized_plan_service import OptimizedPlanService

        async with SessionLocal() as session:
            result = await session.execute(
                select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
            )
            base_plan = result.scalar_one()
            # Base plan must be older than the optimized plan (freshness gate).
            base_plan.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            await session.flush()
            agent_type = await session.get(AgentType, agent_type_id)
            optimized = await OptimizedPlanService().generate_optimized_plan(
                session,
                agent_type=agent_type,
                base_plan=base_plan,
                steps=[{"name": "s1"}],
                fully_scripted=True,
                status=OptimizedPlanStatus.ready,
            )
            # Explicit tz-aware freshness stamp (server default is naive in tests).
            optimized.updated_at = datetime.now(timezone.utc)
            await session.commit()

            service = ScriptRegistryService()
            served = await service.get_fresh_optimized_plan(
                session, agent_type_id=agent_type_id
            )
            assert served is not None  # ready plan gates execution

        await public_client.post(
            f"/api/v1/agents/types/{agent_type_id}/optimized-plan/retire"
        )

        async with SessionLocal() as session:
            service = ScriptRegistryService()
            served = await service.get_fresh_optimized_plan(
                session, agent_type_id=agent_type_id
            )
            assert served is None  # retired plan never gates execution

    async def test_regeneration_retires_previous_ready_row_keeps_one_active(
        self, agent_type_plan, test_engine
    ):
        """The next optimization regenerates: the old ready row is marked
        retired (kept for reference) and the new ACTIVE (ready) row is
        inserted — exactly ONE active record per agent type."""
        from sqlalchemy import select

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from app.services.agents.optimized_plan_service import OptimizedPlanService

        agent_type_id, _ = agent_type_plan
        async with SessionLocal() as session:
            result = await session.execute(
                select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
            )
            base_plan = result.scalar_one()
            agent_type = await session.get(AgentType, agent_type_id)
            service = OptimizedPlanService()
            first = await service.generate_optimized_plan(
                session,
                agent_type=agent_type,
                base_plan=base_plan,
                steps=[{"name": "v1"}],
                fully_scripted=True,
                status=OptimizedPlanStatus.ready,
            )
            second = await service.generate_optimized_plan(
                session,
                agent_type=agent_type,
                base_plan=base_plan,
                steps=[{"name": "v2"}],
                fully_scripted=True,
                status=OptimizedPlanStatus.ready,
            )
            await session.commit()

            assert first.id != second.id
            plans = await _query_plans(test_engine, agent_type_id)
            ready = [p for p in plans if p.status == OptimizedPlanStatus.ready]
            retired = [p for p in plans if p.status == OptimizedPlanStatus.retired]
            # Exactly ONE active (ready) record; the previous one is retired.
            assert len(ready) == 1 and ready[0].id == second.id
            assert any(p.id == first.id for p in retired)


class TestScriptToolNameAuthoringValidation:
    """Authoring-time validation: every ``tools.call('name', ...)`` in a
    script's python_source must match the agent's ACTUAL allowed tool names.
    A mismatch is a structured validation error listing the valid names, so
    the authoring LLM repairs it in its next iteration instead of the script
    failing at serving time (live defect: two-underscore separator typo)."""

    @pytest_asyncio.fixture
    async def agent_type_with_tools(self, test_engine, agent_type_plan):
        """Agent type with a role granting supabase____list_projects."""
        from app.db.models.agents import AgentRole, AgentRoleSkill
        from app.db.models.mcp_hub import McpServer, McpTool
        from app.db.models.skills import Skill, SkillToolBinding

        agent_type_id, _ = agent_type_plan
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            server = McpServer(
                name="supabase",
                slug=f"supabase-{uuid.uuid4().hex[:8]}",
                base_url="https://supabase.example",
            )
            session.add(server)
            await session.flush()
            tool = McpTool(
                server_id=server.id,
                name="supabase____list_projects",
                original_name="list_projects",
            )
            session.add(tool)
            skill = Skill(name=f"list-projects-{uuid.uuid4().hex[:8]}")
            session.add(skill)
            await session.flush()
            session.add(SkillToolBinding(skill_id=skill.id, tool_id=tool.id))
            role = AgentRole(name=f"supabase-role-{uuid.uuid4().hex[:8]}")
            session.add(role)
            await session.flush()
            session.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
            agent_type = await session.get(AgentType, agent_type_id)
            agent_type.role_id = role.id
            await session.commit()
        return agent_type_id

    async def test_execute_script_rejects_wrong_tool_name_with_valid_names(
        self, internal_client, agent_type_with_tools
    ):
        agent_type_id = agent_type_with_tools
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": (
                    "def run(context, tools):\n"
                    "    projects = tools.call('supabase__list_projects', {})\n"
                    "    return {'result': projects}\n"
                ),
                "input": {},
            },
        )
        assert result["status"] == "validation_error"
        assert result["invalid_tool_names"] == ["supabase__list_projects"]
        assert any(
            name.endswith("____list_projects") for name in result["valid_tool_names"]
        )

    async def test_execute_script_accepts_exact_tool_name(
        self, internal_client, agent_type_with_tools
    ):
        agent_type_id = agent_type_with_tools
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": (
                    "def run(context, tools):\n"
                    "    return {'result': 'no tools needed'}\n"
                ),
                "input": {},
            },
        )
        assert "validation_error" not in result

    async def test_generate_script_rejects_wrong_tool_name(
        self, internal_client, agent_type_with_tools
    ):
        agent_type_id = agent_type_with_tools
        result = await _call(
            internal_client, "generate-script",
            {
                "agent_type_id": str(agent_type_id),
                "name": "fetch-projects",
                "python_source": (
                    "def run(context, tools):\n"
                    "    projects = tools.call('supabase__list_projects', {})\n"
                    "    return {'result': projects}\n"
                ),
            },
        )
        assert result["status"] == "validation_error"
        assert result["invalid_tool_names"] == ["supabase__list_projects"]
        assert any(
            name.endswith("____list_projects") for name in result["valid_tool_names"]
        )


class TestCommandMissionToolNameRule:
    def test_mission_demands_exact_tool_names_with_four_underscore_separator(self):
        """The capability contract/command prompt states tool names must be
        used EXACTLY as listed (four-underscore separator `____`) and that a
        wrong name is a validation error returning the valid names."""
        assert "____" in OPTIMIZE_AND_VERIFY_COMMAND
        assert "EXACTLY" in OPTIMIZE_AND_VERIFY_COMMAND
        assert "validation" in OPTIMIZE_AND_VERIFY_COMMAND.lower()

    async def test_retire_unknown_agent_type_404(self, public_client):
        resp = await public_client.post(
            f"/api/v1/agents/types/{uuid.uuid4()}/optimized-plan/retire"
        )
        assert resp.status_code == 404

    async def test_retire_marks_fresh_optimized_plan_retired_and_serving_versions(
        self, public_client, agent_type_plan, test_engine
    ):
        """End-to-end retirement: after the retire endpoint, (a) the plan rows
        REMAIN marked ``retired`` (never deleted), (b)
        ``get_fresh_optimized_plan`` (the Script-First Dispatcher serving
        lookup) no longer returns a plan, and (c) compiled serving script
        versions are retired — the next run takes the LLM path."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from app.db.models.script_registry import (
            ScriptDefinition,
            ScriptLifecycleStatus,
            ScriptVersion,
        )
        from app.services.script_registry import ScriptRegistryService

        agent_type_id, _ = agent_type_plan

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            result = await session.execute(
                select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
            )
            base_plan = result.scalar_one()
            agent_type = await session.get(AgentType, agent_type_id)
            # Base plan must be older than the optimized plan (freshness gate).
            base_plan.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            await session.flush()
            optimized = await OptimizedPlanService().generate_optimized_plan(
                session,
                agent_type=agent_type,
                base_plan=base_plan,
                steps=[{"name": "s1", "python_source": "def run(context, tools):\n    return {'result': 1}"}],
                fully_scripted=True,
                status=OptimizedPlanStatus.ready,
            )
            # Explicit tz-aware freshness stamp (server default is naive in tests).
            optimized.updated_at = datetime.now(timezone.utc)
            # A compiled serving script version (what the dispatcher serves).
            version = ScriptVersion(
                script_definition_id=uuid.uuid4(),
                version_label=f"retire-e2e-{uuid.uuid4().hex[:8]}",
                lifecycle_status=ScriptLifecycleStatus.compiled,
                created_by="test",
            )
            session.add(version)
            await session.flush()
            definition = ScriptDefinition(
                id=version.script_definition_id,
                name=f"retire-e2e-{uuid.uuid4().hex[:8]}",
                agent_type_id=agent_type_id,
                fully_scripted=True,
                current_version_id=version.id,
            )
            session.add(definition)
            version.script_definition_id = definition.id
            await session.flush()
            await session.commit()
            version_id = version.id

        # Sanity: the fresh-plan serving lookup finds the ready plan.
        async with SessionLocal() as session:
            served = await ScriptRegistryService().get_fresh_optimized_plan(
                session, agent_type_id=agent_type_id
            )
            assert served is not None
            assert served["status"] == "ready"

        resp = await public_client.post(
            f"/api/v1/agents/types/{agent_type_id}/optimized-plan/retire"
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["plans_removed"] >= 1

        async with SessionLocal() as session:
            plans = (await session.execute(
                select(OptimizedImplementationPlan).where(
                    OptimizedImplementationPlan.agent_type_id == agent_type_id
                )
            )).scalars().all()
            assert len(plans) >= 1
            assert all(p.status == OptimizedPlanStatus.retired for p in plans)

            served = await ScriptRegistryService().get_fresh_optimized_plan(
                session, agent_type_id=agent_type_id
            )
            assert served is None, (
                "get_fresh_optimized_plan must not return a plan after retirement"
            )

            retired_version = await session.get(ScriptVersion, version_id)
            assert retired_version is not None
            assert retired_version.lifecycle_status == ScriptLifecycleStatus.retired



class TestOptimizedPlanMarkFailed:
    async def test_mark_failed_persists_failed_plan(
        self, test_engine
    ):
        """mark_failed persists a `failed` plan (status + error)."""
        from sqlalchemy import select

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        agent_type_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        async with SessionLocal() as session:
            session.add(
                AgentType(
                    id=agent_type_id,
                    name=f"markfailed-{agent_type_id.hex[:8]}",
                    input_type=AgentInputType.none,
                    output_type=AgentOutputType.markdown,
                )
            )
            session.add(
                AgentPlan(
                    id=plan_id,
                    agent_type_id=agent_type_id,
                    generation_status=AgentPlanStatus.success,
                    plan_steps=[{"order": 1, "type": "tool_call", "name": "s"}],
                )
            )
            await session.commit()

            service = OptimizedPlanService()
            optimized = await service.mark_failed(
                session,
                agent_type_id=agent_type_id,
                agent_plan_id=plan_id,
                error="trigger failed",
            )
            await session.commit()
            optimized_id = optimized.id

        async with SessionLocal() as session:
            row = await session.get(OptimizedImplementationPlan, optimized_id)
            assert row.status == OptimizedPlanStatus.failed
            assert row.error == "trigger failed"
