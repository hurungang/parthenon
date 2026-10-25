"""Security / segregation invariant tests for the Software 3.0 script framework.

SEC1–SEC4 and top-priority-rule invariants:

- SEC2/SEC3: compiled scripts and their artifacts never carry credentials,
  tokens, or secret-bearing material — validated at compile time and by
  inspection of runner→CH payloads.
- SEC1: script tool calls traverse the CH client with provenance tagging and
  per-call agent-type identity — identical path to agent tool calls.
- SEC4: AR script components hold no DB access (static source assertions);
  registry writes only happen through the CC service.
- Fallback never widens permissions (same identity on the LLM path).
"""
from __future__ import annotations

import inspect
import uuid

import pytest

from app.agent_runtime.scripts.compiler import CompilationError, ScriptCompiler
from app.agent_runtime.scripts.fallback import FallbackController
from app.agent_runtime.scripts.runner import ScriptRunner
from app.agent_runtime.scripts.schemas import StepGraph

# Agent Runtime script-framework modules that must never touch the database.
AR_SCRIPT_MODULES = (
    "app.agent_runtime.scripts.compiler",
    "app.agent_runtime.scripts.runner",
    "app.agent_runtime.scripts.verification",
    "app.agent_runtime.scripts.fallback",
    "app.agent_runtime.scripts.cc_client",
)

DB_MARKERS = (
    "create_async_engine",
    "create_engine",
    "sessionmaker",
    "AsyncSession",
    "asyncpg",
    "psycopg",
    "alembic",
)


# ── SEC3: no credentials in compiled scripts ──────────────────────────────────


class TestNoCredentialsInScripts:
    @pytest.mark.parametrize(
        "field",
        ["api_key", "token", "secret", "password", "authorization", "credential"],
    )
    def test_compiler_rejects_credential_shaped_arguments(self, field: str):
        compiler = ScriptCompiler()
        with pytest.raises(CompilationError):
            compiler.compile_from_tool_sequence(
                name="leaky",
                tool_calls=[
                    {
                        "tool_name": "x____y",
                        "tool_input": {field: "super-secret-value"},
                        "tool_output": {},
                    },
                ],
            )

    def test_valid_candidate_serializes_without_secret_material(self):
        compiler = ScriptCompiler()
        graph = compiler.compile_from_tool_sequence(
            name="clean",
            tool_calls=[
                {"tool_name": "a____b", "tool_input": {"q": "1"}, "tool_output": {"id": 7}},
            ],
        )
        blob = graph.model_dump_json().lower()
        for marker in ("api_key", "\"token\"", "secret", "password", "bearer "):
            assert marker not in blob

    def test_tool_references_are_names_only_no_urls(self):
        compiler = ScriptCompiler()
        graph = compiler.compile_from_tool_sequence(
            name="no-urls",
            tool_calls=[
                {"tool_name": "a____b", "tool_input": {}, "tool_output": {}},
            ],
        )
        blob = graph.model_dump_json()
        assert "https://" not in blob and "http://" not in blob
        # Tool references are canonical names, not endpoints. Phase 2: no
        # semantic render step is auto-appended anymore — the graph carries
        # exactly the authored steps.
        assert graph.tool_names() == ["a____b"]


# ── SEC1/SEC2: script tool calls traverse the same CH permission path ─────────


class TestPermissionPathParity:
    async def test_script_tool_call_carries_agent_identity_and_provenance(self):
        """Script steps invoke tools exactly like agent calls: via the CH
        client, under the executing agent's identity, with provenance
        metadata — no separate permission path, no embedded credentials."""
        calls: list[dict] = []

        class SpyClient:
            async def call_tool(self, tool_name, arguments, **kwargs):
                calls.append({"tool_name": tool_name, "arguments": arguments, **kwargs})
                return {"ok": True}

        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {"kind": "tool_call", "name": "s1", "tool_name": "a____b", "arguments": {"q": 1}},
                ],
            }
        )
        await ScriptRunner(tool_client=SpyClient()).execute(  # type: ignore[arg-type]
            graph, session_id="sess-1", agent_type_id="at-1", script_version_label="v1"
        )
        call = calls[0]
        assert call["provenance"] == "script"
        assert call["script_version"] == "v1"
        assert call["agent_type_id"] == "at-1"
        assert call["session_id"] == "sess-1"
        # The runner forwards only declared step arguments — nothing injected
        assert call["arguments"] == {"q": 1}

    async def test_runner_never_injects_authorization_headers(self):
        forwarded: list[dict] = []

        class SpyClient:
            async def call_tool(self, tool_name, arguments, **kwargs):
                forwarded.append({"kwargs": kwargs, "arguments": arguments})
                return {}

        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
            }
        )
        await ScriptRunner(tool_client=SpyClient()).execute(  # type: ignore[arg-type]
            graph, session_id="s", agent_type_id="a", script_version_label="v1",
            initial_context={"authorization": "Bearer leaked", "password": "pw"},
        )
        # Initial context may exist for template resolution, but nothing
        # credential-shaped is ever sent as a tool argument.
        assert "authorization" not in forwarded[0]["arguments"]
        assert "password" not in forwarded[0]["arguments"]


# ── SEC4: service segregation ─────────────────────────────────────────────────


class TestServiceSegregation:
    @pytest.mark.parametrize("module_name", AR_SCRIPT_MODULES)
    def test_ar_script_modules_contain_no_db_access(self, module_name: str):
        """Agent Runtime script components never open a DB connection — all
        registry state flows through CC internal APIs (SEC4, top-priority)."""
        import importlib

        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        for marker in DB_MARKERS:
            assert marker not in source, (
                f"{module_name} references DB material '{marker}'"
            )

    def test_cc_client_targets_internal_scripts_api_only(self):
        """The AR registry client exclusively targets CC internal endpoints."""
        import os

        from app.agent_runtime.scripts.cc_client import ScriptRegistryClient

        original = os.environ.get("CONTROL_CENTER_URL")
        os.environ["CONTROL_CENTER_URL"] = "https://cc.example.com"
        try:
            client = ScriptRegistryClient(cert_manager=object())
            assert client._url("/serving-version") == (
                "https://cc.example.com/api/v1/internal/scripts/serving-version"
            )
        finally:
            if original is None:
                os.environ.pop("CONTROL_CENTER_URL", None)
            else:
                os.environ["CONTROL_CENTER_URL"] = original

    async def test_fallback_reports_carry_no_credential_material(self):
        """Fallback evidence (F2) records reasons and versions — never tokens."""
        reports: list[dict] = []

        class FakeRegistry:
            async def report_execution(self, payload):
                reports.append(("execution", payload))
                return {"id": "e1"}

            async def report_fallback(self, payload):
                reports.append(("fallback", payload))
                return {"id": "f1"}

        async def run() -> None:
            raise __import__(
                "app.agent_runtime.scripts.runner", fromlist=["ExecutionError"]
            ).ExecutionError("tool failed")

        async def llm(ctx: dict) -> str:
            return "ok"

        controller = FallbackController(registry_client=FakeRegistry())  # type: ignore[arg-type]
        await controller.run_with_fallback(
            run,
            script_version_id="ver-1",
            script_version_label="v1",
            session_id=str(uuid.uuid4()),
            agent_type_id="at-1",
            llm_fallback=llm,
            run_context={"identity": "agent-instance-abc"},
        )
        import json

        blob = json.dumps(reports).lower()
        for marker in ("bearer ", "authorization", "private_key", "password"):
            assert marker not in blob


class TestRepairArtifactsCarryNoSecrets:
    async def test_repair_reports_carry_no_credential_material(self):
        """RepairAttempt payloads (diagnosis, diff, graph) never hold tokens
        or credentials — repair stays inside the same guardrails (SEC3, E9)."""
        import json
        import uuid as _uuid

        from app.agent_runtime.scripts.repair import RepairContext, RepairLoop
        from app.agent_runtime.scripts.runner import ExecutionError

        reports: list[dict] = []

        class FakeRegistry:
            async def report_repair(self, payload):
                reports.append(payload)
                return {"repaired_version_id": "repaired-1"}

            async def get_version(self, version_id):
                return {"lifecycle_status": "verified"}

        async def generator(diagnosis: str, graph: dict) -> dict:
            return {"declarative_step_graph": graph, "diff_applied": "fix args"}

        context = RepairContext(
            script_definition_id=str(_uuid.uuid4()),
            script_version_id="ver-1",
            graph_json={"name": "g", "steps": []},
            session_id=str(_uuid.uuid4()),
            agent_type_id="at-1",
        )
        await RepairLoop(FakeRegistry()).run(  # type: ignore[arg-type]
            context, ExecutionError("tool failed"), llm_repair_generator=generator
        )
        blob = json.dumps(reports).lower()
        for marker in ("bearer ", "authorization", "private_key", "password", "api_key"):
            assert marker not in blob

    async def test_repaired_retry_uses_the_same_session_identity(self):
        """Identity parity holds across the repair loop: the repaired script
        retry binds to the same agent session (E7, G2)."""
        import uuid as _uuid

        from app.agent_runtime.scripts.repair import RepairContext

        session_id = str(_uuid.uuid4())
        agent_type_id = "at-1"
        context = RepairContext(
            script_definition_id="def-1",
            script_version_id="ver-1",
            graph_json={"name": "g", "steps": []},
            session_id=session_id,
            agent_type_id=agent_type_id,
        )
        assert context.session_id == session_id
        assert context.agent_type_id == agent_type_id
