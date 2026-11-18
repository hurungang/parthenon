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
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission, require_service_certificate
from app.core.resource_types import RT_AGENT
from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentPlan,
    AgentPlanStatus,
    AgentType,
)
from app.db.models.optimized_plan import OptimizedImplementationPlan, OptimizedPlanStatus
from app.db.models.session_logs import ExecutionLogEntry
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
async def reference_execution(
    test_engine, agent_type_plan
) -> dict[str, Any]:
    """Seed a completed NORMAL execution with recorded tool data.

    Optimization verification is REPLAY-ONLY: ``execute_script`` needs a real
    execution's input plus its recorded tool calls/responses — it never calls
    live MCP tools. The transcript here uses the LLM path pair
    (``tool_call``/``tool_response`` matched by ``run_id``).
    """
    agent_type_id, _ = agent_type_plan
    job_id = uuid.uuid4()
    started = datetime.now(UTC) - timedelta(minutes=5)
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        session.add(
            AgentJob(
                id=job_id,
                agent_type_id=agent_type_id,
                status=AgentJobStatus.completed,
                input_data={"x": 41},
                created_at=started,
                started_at=started,
                completed_at=started + timedelta(seconds=30),
            )
        )
        await session.flush()
        session.add(
            ExecutionLogEntry(
                session_id=job_id,
                timestamp=started + timedelta(seconds=1),
                log_level="INFO",
                event_type="tool_call",
                message="Tool call: supabase____get_project",
                data={
                    "tool": "supabase____get_project",
                    "arguments": {"id": "p-1"},
                    "input": '{"id": "p-1"}',
                    "input_truncated": False,
                    "run_id": "run-1",
                },
            )
        )
        session.add(
            ExecutionLogEntry(
                session_id=job_id,
                timestamp=started + timedelta(seconds=2),
                log_level="INFO",
                event_type="tool_response",
                message="Tool response (0.10s)",
                data={
                    "output": '{"name": "Ada", "id": "p-1"}',
                    "output_truncated": False,
                    "run_id": "run-1",
                },
            )
        )
        await session.commit()
    return {"session_id": job_id, "agent_type_id": agent_type_id}


@pytest_asyncio.fixture
async def ar_boundary(monkeypatch):
    """Stub the CC→CH→AR egress at the ``CommunicationHubClient`` seam.

    Emulates Agent Runtime's ``/internal/script-tools/execute`` endpoint
    faithfully: a ``replay_required`` request runs the submitted
    ``python_source`` in the REAL sandbox with AR's ``ReplayToolClient``
    (recorded responses only); a non-replay request runs with a live-style
    fake client. Optimization must NEVER take the live path —
    ``captured["live_runs"]`` counts it.
    """
    import asyncio
    from types import SimpleNamespace

    from app.agent_runtime.api.script_tools import ReplayToolClient
    from app.agent_runtime.scripts.sandbox import SandboxCaps, run_sandboxed_python
    from app.services.control_center import comm_hub_client

    class _FakeArLiveToolClient:
        """Live session-bound client double (must stay unused by optimization)."""

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

    live_client = _FakeArLiveToolClient()
    captured: dict[str, Any] = {"live_runs": 0, "replay_runs": 0}
    replay_clients: list[ReplayToolClient] = []

    async def fake_forward_sandboxed_script(
        self, *, python_source: str, session_id: str, agent_type_id: str,
        input_context: dict[str, Any] | None = None,
        tenant_context: Any = None,
        reference_tool_responses: list[dict[str, Any]] | None = None,
        replay_required: bool = False,
    ) -> dict[str, Any]:
        captured["python_source"] = python_source
        captured["session_id"] = session_id
        captured["agent_type_id"] = agent_type_id
        captured["input_context"] = input_context
        captured["reference_tool_responses"] = reference_tool_responses
        captured["replay_required"] = replay_required
        if replay_required:
            captured["replay_runs"] += 1
            tool_client: Any = ReplayToolClient(reference_tool_responses or [])
            replay_clients.append(tool_client)
        else:
            captured["live_runs"] += 1
            tool_client = live_client
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
    return SimpleNamespace(
        captured=captured,
        live_client=live_client,
        replay_clients=replay_clients,
    )


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
        assert result["auto_generated"] is False

    async def test_get_implementation_plan_auto_generates_when_missing(
        self, internal_client, db_session, monkeypatch
    ):
        """Optimization must not dead-end when the agent has no base plan.

        The read tool generates the base plan with the authoring model first.
        """
        from app.services.agents.plan_generation_service import PlanGenerationService

        agent_type_id = uuid.uuid4()
        db_session.add(
            AgentType(
                id=agent_type_id,
                name=f"autoplan-{agent_type_id.hex[:8]}",
                input_type=AgentInputType.none,
                output_type=AgentOutputType.markdown,
            )
        )
        await db_session.commit()

        async def _fake_generate(self, agent_type, db, **kwargs):
            plan = AgentPlan(
                id=uuid.uuid4(),
                agent_type_id=agent_type.id,
                generation_status=AgentPlanStatus.success,
                plan_steps=[
                    {"order": 1, "type": "tool_call", "name": "Auto step"}
                ],
            )
            db.add(plan)
            await db.flush()
            return plan

        monkeypatch.setattr(PlanGenerationService, "generate_plan", _fake_generate)

        result = await _call(
            internal_client,
            "get-implementation-plan",
            {"agent_type_id": str(agent_type_id)},
        )

        assert result["auto_generated"] is True
        assert result["steps"][0]["name"] == "Auto step"

    async def test_get_implementation_plan_reports_unavailable_base_plan(
        self, internal_client, db_session, monkeypatch
    ):
        """If the base plan cannot be generated, the optimizer is told to ask."""
        from app.services.agents.plan_generation_service import PlanGenerationService

        agent_type_id = uuid.uuid4()
        db_session.add(
            AgentType(
                id=agent_type_id,
                name=f"autoplan-fail-{agent_type_id.hex[:8]}",
                input_type=AgentInputType.none,
                output_type=AgentOutputType.markdown,
            )
        )
        await db_session.commit()

        async def _fail(self, agent_type, db, **kwargs):
            raise RuntimeError("authoring model offline")

        monkeypatch.setattr(PlanGenerationService, "generate_plan", _fail)

        result = await _call(
            internal_client,
            "get-implementation-plan",
            {"agent_type_id": str(agent_type_id)},
        )

        assert result["status"] == "needs_user_input"
        assert result["blockers"] == ["base_plan_unavailable"]
        assert "authoring model offline" in result["error"]

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
        self, internal_client, agent_type_plan, reference_execution
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
        self, internal_client, agent_type_plan, reference_execution
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
        self, internal_client, agent_type_plan, reference_execution
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

    async def test_execute_script_rejects_input_missing_required_typed_keys(
        self, internal_client, agent_type_plan, db_session, reference_execution
    ):
        """A guessed/renamed input context is rejected before execution.

        Guards the flight-search class of bug: the optimizer authored a script
        against ``date`` while the agent's typed input requires
        ``travel_date``. Verification must fail on the missing required key
        instead of persisting a plan that cannot serve real input.
        """
        agent_type_id, _ = agent_type_plan
        agent_type = await db_session.get(AgentType, agent_type_id)
        agent_type.input_type = AgentInputType.typed
        agent_type.input_schema = {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "travel_date": {"type": "string"},
            },
            "required": ["origin", "destination", "travel_date"],
        }
        await db_session.commit()

        result = await _call(
            internal_client,
            "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": _GOOD_SOURCE,
                "input": {
                    "origin": "MEL",
                    "destination": "SYD",
                    "date": "2026-11-15",
                },
            },
        )

        assert result["status"] == "validation_error"
        assert result["missing_input_keys"] == ["travel_date"]
        assert set(result["valid_input_keys"]) == {
            "origin",
            "destination",
            "travel_date",
        }
        assert "travel_date" in result["error"]

    async def test_execute_script_inline_compile_error_is_structured(
        self, internal_client, agent_type_plan, reference_execution
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
        self, internal_client, agent_type_plan, db_session, reference_execution
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
        self, internal_client, agent_type_plan, db_session, reference_execution
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

        # Round-trip: the saved version replays too. The replay uses the
        # REFERENCE execution's input ({"x": 41}), never a re-typed context.
        rerun = await _call(
            internal_client, "execute-script",
            {"script_version_id": saved["version_id"], "input": {"x": 7}},
        )
        assert rerun["output"]["value"] == 41

    async def test_execute_script_routes_inline_source_through_ar_boundary(
        self, internal_client, agent_type_plan, ar_boundary, reference_execution
    ):
        """The inline source reaches Agent Runtime verbatim with the session
        identity — CC does NOT execute it locally (segregation), and the run is
        flagged replay-only (no live tool invocation)."""
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
        # Replay-only: the reference input + recorded transcript were sent and
        # the live client was NEVER used.
        assert ar_boundary.captured["input_context"] == {"x": 41}
        assert ar_boundary.captured["replay_required"] is True
        assert ar_boundary.captured["reference_tool_responses"]
        assert ar_boundary.captured["live_runs"] == 0
        assert result["replayed"] is True

    async def test_execute_script_tools_facade_is_not_none(
        self, internal_client, agent_type_plan, ar_boundary, reference_execution
    ):
        """A script that calls MCP tools verifies: the sandbox's ``tools``
        facade is non-None and the tool call is answered from the recorded
        reference transcript (live-defect regression: the facade was None →
        TypeError 'NoneType' not callable)."""
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
        # The response came from the REPLAY client, never the live one.
        assert ar_boundary.live_client.calls == []
        replay_calls = ar_boundary.replay_clients[-1].calls
        assert replay_calls[0]["tool_name"] == "supabase____get_project"
        assert replay_calls[0]["arguments"] == {"id": "p-1"}

    async def test_execute_script_no_reference_data_asks_user(
        self, internal_client, agent_type_plan, ar_boundary
    ):
        """Without a recorded reference execution nothing may run.

        Replay-only verification: with no reference tool data ``execute_script``
        returns a TERMINAL ``needs_user_input`` (so the optimizer stops and asks
        the user instead of looping) and never forwards the source to AR.
        """
        agent_type_id, _ = agent_type_plan
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": _GOOD_SOURCE,
                "input": {"x": 41},
            },
        )
        assert result["status"] == "needs_user_input"
        assert result["blockers"] == ["no_reference_tool_data"]
        assert "reference execution recorded no tool calls" in result["error"]
        assert result["tool_calls"] == []
        assert ar_boundary.captured == {"live_runs": 0, "replay_runs": 0}

    async def test_execute_script_replay_miss_asks_user(
        self, internal_client, agent_type_plan, ar_boundary, reference_execution
    ):
        """A tool call absent from the reference transcript is terminal.

        It must surface as ``needs_user_input`` (blocker
        ``reference_transcript_incomplete``) — NOT a retryable error, and never
        a live fallback. The reference recorded only
        ``supabase____get_project``; this script calls another tool.
        """
        agent_type_id, _ = agent_type_plan
        source = (
            "def run(context, tools):\n"
            "    return {'r': tools.call('supabase____list_projects', {})}\n"
        )
        result = await _call(
            internal_client, "execute-script",
            {
                "agent_type_id": str(agent_type_id),
                "python_source": source,
                "input": {"x": 41},
            },
        )
        assert result["status"] == "needs_user_input"
        assert result["blockers"] == ["reference_transcript_incomplete"]
        assert "No recorded response" in result["error"]
        assert result["recorded_tools"] == ["supabase____get_project"]
        assert ar_boundary.captured["live_runs"] == 0

    async def test_execute_script_surfaces_ar_structured_error(
        self, internal_client, agent_type_plan, monkeypatch, reference_execution
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


def _plan_session_factory(test_engine):
    return async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_optimized_plan(
    test_engine,
    agent_type_id: uuid.UUID,
    *,
    status: OptimizedPlanStatus = OptimizedPlanStatus.ready,
    feedback_comments: list[dict[str, Any]] | None = None,
    error: str | None = None,
    generated_at=None,
) -> uuid.UUID:
    """Create one optimized plan row (with its base AgentPlan) for a type."""
    from sqlalchemy import select

    from app.db.models.agents import (
        AgentInputType,
        AgentOutputType,
        AgentPlan,
        AgentPlanStatus,
        AgentType,
    )

    async with _plan_session_factory(test_engine)() as session:
        agent_type = await session.get(AgentType, agent_type_id)
        if agent_type is None:
            agent_type = AgentType(
                id=agent_type_id,
                name=f"requires-fix-{agent_type_id.hex[:8]}",
                input_type=AgentInputType.none,
                output_type=AgentOutputType.markdown,
            )
            session.add(agent_type)
            await session.flush()
        base = (
            await session.execute(
                select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
            )
        ).scalar_one_or_none()
        if base is None:
            base = AgentPlan(
                agent_type_id=agent_type_id,
                generation_status=AgentPlanStatus.success,
                plan_steps=[{"order": 1, "type": "tool_call", "name": "s"}],
            )
            session.add(base)
            await session.flush()
        plan = OptimizedImplementationPlan(
            agent_type_id=agent_type_id,
            agent_plan_id=base.id,
            plan_steps=[{"order": 1, "name": "s1"}],
            fully_scripted=False,
            status=status,
            error=error,
            feedback_comments=feedback_comments,
            generated_at=generated_at,
        )
        session.add(plan)
        await session.commit()
        return plan.id


class TestMarkRequiresFix:
    """Execution-side state: a later fallback flags the live plan."""

    async def test_sets_status_and_appends_execution_derived_feedback(
        self, test_engine, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        execution_id = uuid.uuid4()
        fallback_event_id = uuid.uuid4()
        plan_id = await _seed_optimized_plan(
            test_engine,
            agent_type_id,
            feedback_comments=[
                {"created_at": "2026-01-01T00:00:00+00:00",
                 "raw_feedback": "older manual note",
                 "summary": "older manual note",
                 "source": "manual"},
            ],
        )

        async with _plan_session_factory(test_engine)() as session:
            service = OptimizedPlanService()
            flagged = await service.mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="Execution fell back to the LLM path (execution_error): boom",
                raw_feedback="boom\nsecond line",
                source_execution_id=execution_id,
                source_fallback_event_id=fallback_event_id,
            )
            await session.commit()
            assert flagged is not None
            assert flagged.id == plan_id

        async with _plan_session_factory(test_engine)() as session:
            plan = await session.get(OptimizedImplementationPlan, plan_id)
            assert plan.status == OptimizedPlanStatus.requires_fix
            comments = plan.feedback_comments
            # Prior feedback preserved verbatim.
            assert comments[0]["source"] == "manual"
            assert len(comments) == 2
            entry = comments[-1]
            assert entry["source"] == "execution_derived"
            assert entry["summary"].startswith(
                "Execution fell back to the LLM path (execution_error)"
            )
            assert entry["raw_feedback"] == "boom\nsecond line"
            assert entry["source_execution_id"] == str(execution_id)
            assert entry["source_fallback_event_id"] == str(fallback_event_id)
            assert entry["created_at"]

    async def test_empty_execution_id_is_omitted_from_entry(
        self, test_engine, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        plan_id = await _seed_optimized_plan(test_engine, agent_type_id)

        async with _plan_session_factory(test_engine)() as session:
            await OptimizedPlanService().mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="fell back",
                raw_feedback="fell back",
            )
            await session.commit()

        async with _plan_session_factory(test_engine)() as session:
            plan = await session.get(OptimizedImplementationPlan, plan_id)
            entry = plan.feedback_comments[-1]
            assert "source_execution_id" not in entry
            assert "source_fallback_event_id" not in entry

    async def test_never_touches_error_field(self, test_engine, agent_type_plan):
        """``error`` is authoring-side (needs_feedback) — the fallback reason
        lives in the execution-derived feedback entry."""
        agent_type_id, _ = agent_type_plan
        plan_id = await _seed_optimized_plan(
            test_engine, agent_type_id, error="old authoring error"
        )

        async with _plan_session_factory(test_engine)() as session:
            await OptimizedPlanService().mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="fell back",
                raw_feedback="detail",
            )
            await session.commit()

        async with _plan_session_factory(test_engine)() as session:
            plan = await session.get(OptimizedImplementationPlan, plan_id)
            assert plan.status == OptimizedPlanStatus.requires_fix
            assert plan.error == "old authoring error"

    async def test_no_live_plan_is_a_noop(self, test_engine, agent_type_plan):
        agent_type_id, _ = agent_type_plan
        async with _plan_session_factory(test_engine)() as session:
            result = await OptimizedPlanService().mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="fell back",
                raw_feedback="detail",
            )
            await session.commit()
        assert result is None
        assert await _query_plans(test_engine, agent_type_id) == []

    async def test_retired_plan_is_not_flagged(self, test_engine, agent_type_plan):
        """A late-arriving fallback must never resurrect a retired plan."""
        agent_type_id, _ = agent_type_plan
        plan_id = await _seed_optimized_plan(
            test_engine,
            agent_type_id,
            status=OptimizedPlanStatus.retired,
            feedback_comments=None,
        )

        async with _plan_session_factory(test_engine)() as session:
            result = await OptimizedPlanService().mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="fell back",
                raw_feedback="detail",
            )
            await session.commit()
        assert result is None

        async with _plan_session_factory(test_engine)() as session:
            plan = await session.get(OptimizedImplementationPlan, plan_id)
            assert plan.status == OptimizedPlanStatus.retired
            assert not plan.feedback_comments

    async def test_latest_live_plan_is_the_target_when_multiple_exist(
        self, test_engine, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        await _seed_optimized_plan(
            test_engine, agent_type_id, status=OptimizedPlanStatus.retired
        )
        latest_id = await _seed_optimized_plan(
            test_engine, agent_type_id, status=OptimizedPlanStatus.ready
        )

        async with _plan_session_factory(test_engine)() as session:
            flagged = await OptimizedPlanService().mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="fell back",
                raw_feedback="detail",
            )
            await session.commit()
        assert flagged is not None and flagged.id == latest_id

    async def test_repeated_fallback_keeps_requires_fix_and_appends(
        self, test_engine, agent_type_plan
    ):
        """Multiple fallbacks on the same plan: no crash, still
        ``requires_fix``, feedback accumulates (never silently re-served)."""
        agent_type_id, _ = agent_type_plan
        plan_id = await _seed_optimized_plan(test_engine, agent_type_id)

        async with _plan_session_factory(test_engine)() as session:
            service = OptimizedPlanService()
            for index in range(2):
                await service.mark_requires_fix(
                    session,
                    agent_type_id,
                    feedback_summary=f"fallback-{index}",
                    raw_feedback=f"detail-{index}",
                    source_execution_id=uuid.uuid4(),
                )
            await session.commit()

        async with _plan_session_factory(test_engine)() as session:
            plan = await session.get(OptimizedImplementationPlan, plan_id)
            assert plan.status == OptimizedPlanStatus.requires_fix
            assert len(plan.feedback_comments) == 2
            assert {c["source"] for c in plan.feedback_comments} == {
                "execution_derived"
            }

    async def test_requires_fix_plan_is_never_served(self, test_engine, agent_type_plan):
        """Serving predicate stays ``status == ready`` — a flagged plan is not
        silently re-served."""
        from datetime import datetime, timezone

        from app.services.script_registry import ScriptRegistryService

        agent_type_id, _ = agent_type_plan
        await _seed_optimized_plan(
            test_engine,
            agent_type_id,
            status=OptimizedPlanStatus.requires_fix,
            generated_at=datetime.now(timezone.utc),
        )
        async with _plan_session_factory(test_engine)() as session:
            served = await ScriptRegistryService().get_fresh_optimized_plan(
                session, agent_type_id=agent_type_id
            )
        assert served is None

    async def test_plan_id_of_another_agent_type_is_a_noop(
        self, test_engine, agent_type_plan
    ):
        agent_type_id, _ = agent_type_plan
        other_plan_id = await _seed_optimized_plan(test_engine, uuid.uuid4())

        async with _plan_session_factory(test_engine)() as session:
            result = await OptimizedPlanService().mark_requires_fix(
                session,
                agent_type_id,
                feedback_summary="fell back",
                raw_feedback="detail",
                plan_id=other_plan_id,
            )
            await session.commit()
        assert result is None


class TestAuthoringStatusContract:
    """``requires_fix`` is execution-side only — the authoring tool advertises
    only ``ready | failed | needs_feedback`` (it is set exclusively by the
    fallback reaction)."""

    def test_generate_optimized_plan_schema_excludes_requires_fix(self):
        from app.services.agents.system_tool_registry import SystemToolRegistry

        tool = SystemToolRegistry.get("generate_optimized_plan")
        assert tool is not None
        status_desc = tool.parameters["properties"]["status"]["description"]
        assert "ready" in status_desc
        assert "failed" in status_desc
        assert "needs_feedback" in status_desc
        assert "requires_fix" not in status_desc

    def test_mission_carries_authoring_failure_reason_in_error(self):
        """The mission mandates ``needs_feedback`` + a non-empty ``error``."""
        mission = " ".join(OPTIMIZE_AND_VERIFY_COMMAND.split())
        assert "status `needs_feedback`" in mission
        assert "`error` argument set to a concise failure reason" in mission


class TestFeedbackSourceShape:
    """Feedback entries carry a ``source`` discriminator (manual vs derived)."""

    async def test_add_feedback_tags_manual_source(
        self, test_engine, agent_type_plan, monkeypatch
    ):
        agent_type_id, _ = agent_type_plan
        plan_id = await _seed_optimized_plan(
            test_engine,
            agent_type_id,
            # Legacy entry predating the ``source`` field.
            feedback_comments=[{"raw_feedback": "legacy note"}],
        )

        async def fake_summarize(self, agent_type, db, raw_feedback):
            return "requested change"

        monkeypatch.setattr(
            OptimizedPlanService, "_summarize_feedback", fake_summarize
        )

        async with _plan_session_factory(test_engine)() as session:
            agent_type = await session.get(AgentType, agent_type_id)
            plan = await OptimizedPlanService().add_feedback(
                agent_type, session, "please use the other endpoint"
            )
            await session.commit()
            comments = plan.feedback_comments

        assert len(comments) == 2
        # Legacy entries stay untouched (readers default a missing source).
        assert "source" not in comments[0]
        entry = comments[-1]
        assert entry["source"] == "manual"
        assert entry["summary"] == "requested change"
        assert entry["raw_feedback"] == "please use the other endpoint"
        assert entry["created_at"]

        async with _plan_session_factory(test_engine)() as session:
            reloaded = await session.get(OptimizedImplementationPlan, plan_id)
            assert reloaded.feedback_comments[-1]["source"] == "manual"

    async def test_feedback_endpoint_returns_manual_source(
        self, public_client, agent_type_plan, test_engine, monkeypatch
    ):
        agent_type_id, _ = agent_type_plan
        await _seed_optimized_plan(test_engine, agent_type_id)

        async def fake_summarize(self, agent_type, db, raw_feedback):
            return "requested change"

        monkeypatch.setattr(
            OptimizedPlanService, "_summarize_feedback", fake_summarize
        )

        resp = await public_client.post(
            f"/api/v1/agents/types/{agent_type_id}/optimize-plan/feedback",
            json={"feedback": "make it faster"},
        )
        assert resp.status_code == 200, resp.text
        comments = resp.json()["feedback_comments"]
        assert len(comments) == 1
        assert comments[0]["source"] == "manual"
        assert comments[0]["summary"] == "requested change"

    async def test_optimized_plan_payload_exposes_status_and_feedback_source(
        self, public_client, agent_type_plan, test_engine
    ):
        agent_type_id, _ = agent_type_plan
        await _seed_optimized_plan(
            test_engine,
            agent_type_id,
            status=OptimizedPlanStatus.requires_fix,
            feedback_comments=[
                {
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "raw_feedback": "boom",
                    "summary": "Execution fell back to the LLM path",
                    "source": "execution_derived",
                    "source_execution_id": str(uuid.uuid4()),
                }
            ],
        )

        resp = await public_client.get(
            f"/api/v1/agents/types/{agent_type_id}/optimized-plan"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "requires_fix"
        assert body["feedback_comments"][0]["source"] == "execution_derived"
        assert body["feedback_comments"][0]["summary"]


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
        self, internal_client, agent_type_with_tools, reference_execution
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
        self, internal_client, agent_type_with_tools, reference_execution
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


# ── Replay-only verification (reference transcript + replay client) ──────────


def _transcript_session_factory(test_engine):
    return async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_transcript_job(
    test_engine,
    agent_type_id: uuid.UUID,
    *,
    entries: list[dict[str, Any]],
    input_data: dict[str, Any] | None = None,
    command: bool = False,
) -> uuid.UUID:
    """Seed one completed job plus raw execution-log entries (in order)."""
    job_id = uuid.uuid4()
    started = datetime.now(UTC) - timedelta(minutes=4)
    payload: dict[str, Any] = dict(input_data or {"x": 41})
    if command:
        payload["__command"] = "optimize-and-verify"
    async with _transcript_session_factory(test_engine)() as session:
        session.add(
            AgentJob(
                id=job_id,
                agent_type_id=agent_type_id,
                status=AgentJobStatus.completed,
                input_data=payload,
                created_at=started,
                started_at=started,
                completed_at=started + timedelta(seconds=30),
            )
        )
        await session.flush()
        for index, entry in enumerate(entries):
            session.add(
                ExecutionLogEntry(
                    session_id=job_id,
                    timestamp=started + timedelta(seconds=index + 1),
                    log_level="INFO",
                    event_type=entry["event_type"],
                    message=entry.get("message", entry["event_type"]),
                    data=entry.get("data", {}),
                )
            )
        await session.commit()
    return job_id


class TestBuildReferenceTranscript:
    """The replay transcript: exactly what ``execute_script`` is allowed to run."""

    async def test_prefers_script_tool_call_events(
        self, test_engine, agent_type_plan
    ):
        """``script_tool_call`` events carry the full recorded result + args."""
        from app.api.v1.internal.optimization_tools import _build_reference_transcript

        agent_type_id, _ = agent_type_plan
        job_id = await _seed_transcript_job(
            test_engine,
            agent_type_id,
            input_data={"origin": "MEL", "__conv_session_id": "internal"},
            entries=[
                {"event_type": "script_run_started", "data": {}},
                {
                    "event_type": "script_tool_call",
                    "message": "Script tool call: demo____searchFlights",
                    "data": {
                        "tool": "demo____searchFlights",
                        "arguments": {"origin": "MEL"},
                        "result": {"results": [{"flight_id": "FL-1"}]},
                        "result_preview": '{"results": [...',
                        "result_truncated": False,
                        "error": None,
                    },
                },
                # An LLM-path pair in the same run must NOT be used when the
                # script recorded its own calls.
                {
                    "event_type": "tool_call",
                    "data": {
                        "tool": "other____tool",
                        "arguments": {},
                        "run_id": "run-9",
                    },
                },
                {
                    "event_type": "tool_response",
                    "data": {"output": "1", "run_id": "run-9"},
                },
            ],
        )

        async with _transcript_session_factory(test_engine)() as session:
            transcript = await _build_reference_transcript(session, agent_type_id)

        assert transcript["session_id"] == str(job_id)
        # Internal routing keys are stripped; the real input is the context.
        assert transcript["input"] == {"origin": "MEL"}
        assert transcript["tool_calls"] == [
            {
                "tool": "demo____searchFlights",
                "arguments": {"origin": "MEL"},
                "response": {"results": [{"flight_id": "FL-1"}]},
            }
        ]
        assert transcript["truncated"] is False

    async def test_pairs_llm_tool_calls_with_responses_by_run_id(
        self, test_engine, agent_type_plan
    ):
        """LLM-path runs: call/response pairs match on ``run_id`` in call order."""
        from app.api.v1.internal.optimization_tools import _build_reference_transcript

        agent_type_id, _ = agent_type_plan
        await _seed_transcript_job(
            test_engine,
            agent_type_id,
            input_data={"project_id": "p-1"},
            entries=[
                {
                    "event_type": "tool_call",
                    "data": {
                        "tool": "supabase____list_projects",
                        "arguments": {"limit": 1},
                        "run_id": "run-a",
                    },
                },
                {
                    "event_type": "tool_call",
                    "data": {
                        "tool": "supabase____get_project",
                        "arguments": {"id": "p-1"},
                        # No structured arguments → parsed from the text input.
                        "input": '{"id": "p-1"}',
                        "run_id": "run-b",
                    },
                },
                # Responses arrive out of order — replay must keep CALL order.
                {
                    "event_type": "tool_response",
                    "data": {"output": '{"name": "Ada"}', "run_id": "run-b"},
                },
                {
                    "event_type": "tool_response",
                    "data": {"output": '[{"id": "p-1"}]', "run_id": "run-a"},
                },
            ],
        )

        async with _transcript_session_factory(test_engine)() as session:
            transcript = await _build_reference_transcript(session, agent_type_id)

        assert transcript["tool_calls"] == [
            {
                "tool": "supabase____list_projects",
                "arguments": {"limit": 1},
                "response": [{"id": "p-1"}],
            },
            {
                "tool": "supabase____get_project",
                "arguments": {"id": "p-1"},
                "response": {"name": "Ada"},
            },
        ]

    async def test_command_runs_and_current_session_are_never_references(
        self, test_engine, agent_type_plan
    ):
        from app.api.v1.internal.optimization_tools import _build_reference_transcript

        agent_type_id, _ = agent_type_plan
        command_job = await _seed_transcript_job(
            test_engine,
            agent_type_id,
            command=True,
            entries=[
                {
                    "event_type": "script_tool_call",
                    "data": {"tool": "x____y", "arguments": {}, "result": 1},
                }
            ],
        )

        async with _transcript_session_factory(test_engine)() as session:
            transcript = await _build_reference_transcript(
                session, agent_type_id, current_session_id=command_job
            )

        assert transcript["session_id"] is None
        assert transcript["tool_calls"] == []

    async def test_empty_history_yields_no_tool_calls(self, test_engine, agent_type_plan):
        from app.api.v1.internal.optimization_tools import _build_reference_transcript

        agent_type_id, _ = agent_type_plan
        async with _transcript_session_factory(test_engine)() as session:
            transcript = await _build_reference_transcript(session, agent_type_id)

        assert transcript == {
            "session_id": None,
            "input": None,
            "input_schema": None,
            "tool_calls": [],
            "truncated": False,
        }


class TestReplayToolClient:
    """AR's replay client: recorded responses only, typed miss when absent."""

    async def test_exact_arguments_preferred_then_name_fallback(self):
        from app.agent_runtime.api.script_tools import ReplayToolClient

        client = ReplayToolClient(
            [
                {"tool": "crm____get", "arguments": {"id": 2}, "response": {"n": 2}},
                {"tool": "crm____get", "arguments": {"id": 1}, "response": {"n": 1}},
            ]
        )

        # Exact arguments win even when out of order.
        assert await client.call_tool("crm____get", {"id": 1}) == {"n": 1}
        # No exact match left → the next unconsumed entry for that tool.
        assert await client.call_tool("crm____get", {"id": 99}) == {"n": 2}
        assert [call["arguments"] for call in client.calls] == [{"id": 1}, {"id": 99}]

    async def test_miss_raises_typed_error_naming_the_tool(self):
        from app.agent_runtime.api.script_tools import ReplayToolClient
        from app.agent_runtime.scripts.sandbox import SandboxViolationError

        client = ReplayToolClient(
            [{"tool": "crm____get", "arguments": {}, "response": {"ok": True}}]
        )

        with pytest.raises(SandboxViolationError) as exc_info:
            await client.call_tool("crm____create", {})

        assert "No recorded response for tool 'crm____create'" in str(exc_info.value)
        assert "never calls live tools" in str(exc_info.value)
        # The recorded tool names are surfaced so the optimizer can repair.
        assert "crm____get" in str(exc_info.value)

    async def test_exhausted_transcript_cannot_be_reused(self):
        from app.agent_runtime.api.script_tools import ReplayToolClient
        from app.agent_runtime.scripts.sandbox import SandboxViolationError

        client = ReplayToolClient(
            [{"tool": "crm____get", "arguments": {"id": 1}, "response": {"n": 1}}]
        )
        assert await client.call_tool("crm____get", {"id": 1}) == {"n": 1}
        with pytest.raises(SandboxViolationError):
            await client.call_tool("crm____get", {"id": 1})


class TestReplayOnlyMission:
    def test_mission_mandates_replay_not_live_tools(self):
        """Verification is a REPLAY of recorded input + tool responses."""
        normalized = " ".join(OPTIMIZE_AND_VERIFY_COMMAND.split())
        assert "NEVER calls live tools and NEVER changes data" in normalized
        assert "REPLAYING" in normalized
        assert "`execute_script` REPLAYS ONLY the recorded tool responses" in normalized
        assert "tool_calls" in normalized
        # A missing recorded tool call is never invented — bounded stop that
        # asks the user (terminal needs_user_input, not a retry loop).
        assert "do NOT invent the call" in normalized
        assert "needs_user_input" in normalized
        assert "Asking the user is the correct stop" in normalized
        assert "needs_feedback" in normalized

    def test_mission_keeps_reference_input_instruction(self):
        normalized = " ".join(OPTIMIZE_AND_VERIFY_COMMAND.split())
        assert "pass the returned `input` object EXACTLY" in normalized
        assert "Never invent, rename, or substitute input keys" in normalized
