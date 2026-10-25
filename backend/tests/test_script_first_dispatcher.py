"""Unit tests for the Script-First Dispatcher (Agent Runtime) — E1–E3, F1–F4.

The refinement removed execution modes entirely: script-first dispatch with
unconditional LLM fallback is the single fixed platform strategy. Covers:

- Serving-version lookup: script exists → script runs automatically; none
  exists → LLM path without error (E1, E3); registry failure degrades to the
  LLM path (SEC4 — AR never reads the DB).
- Unconditional fallback on every typed trigger (execution_error,
  tool_schema_mismatch, output_validation_failure) with reason capture
  (E2, F1, F2) — a run never fails solely because a script failed.
- **No mode resolution anywhere**: no ``mode`` parameter, no ``compiled-only``
  loud-failure path, no mode configuration lookup (E1–E3).
- Bounded repair-retry after fallback (E9/E10) — repair exhaustion still
  completes the run on the LLM path.
- Permission invariance: the LLM path runs with the same run context (SEC).
- Fallback reports carry reason, script version and failure detail (F2).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent_runtime.scripts.dispatch import (
    _get_serving_script,
    _ServingScript,
    reset_serving_cache,
)
from app.agent_runtime.scripts.fallback import (
    ACTION_LLM_COMPLETED,
    ACTION_REPAIR_NOT_PRODUCED,
    TRIGGER_EXECUTION_ERROR,
    TRIGGER_OUTPUT_VALIDATION,
    TRIGGER_SCHEMA_MISMATCH,
    FallbackController,
)
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
    ScriptExecutionError,
)


class FakeRegistryClient:
    def __init__(self, repaired_version_id: str | None = None):
        self.repaired_version_id = repaired_version_id
        self.executions: list[dict[str, Any]] = []
        self.fallbacks: list[dict[str, Any]] = []
        self.repairs: list[dict[str, Any]] = []

    async def report_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.executions.append(payload)
        return {"id": f"exec-{len(self.executions)}"}

    async def report_fallback(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.fallbacks.append(payload)
        return {"id": f"fb-{len(self.fallbacks)}"}

    async def report_repair(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.repairs.append(payload)
        return {"repaired_version_id": self.repaired_version_id}

    async def get_version(self, version_id: str) -> dict[str, Any]:
        return {"lifecycle_status": "draft"}


def _controller(registry: FakeRegistryClient) -> FallbackController:
    return FallbackController(registry_client=registry)  # type: ignore[arg-type]


def _failing_run(exc: Exception):
    async def _run() -> Any:
        raise exc

    return _run


# ── Fixed strategy: no mode resolution exists (E1–E3) ─────────────────────────


class TestNoModesExist:
    def test_run_with_fallback_has_no_mode_parameter(self):
        """The mode parameter is gone from the controller API — modes were
        removed; script-first + unconditional fallback is the only strategy."""
        import inspect

        params = inspect.signature(
            FallbackController.run_with_fallback
        ).parameters
        assert "mode" not in params

    def test_no_compiled_only_loud_failure_constant_exists(self):
        """``compiled-only`` loud-failure behavior must be absent: there are
        no modes, so no mode-conditional failure path can exist."""
        import app.agent_runtime.scripts.fallback as fallback_module

        assert not any(
            "compiled_only" in name or "compiled-only" in name
            for name in dir(fallback_module)
        )

    def test_dispatch_module_has_no_mode_references(self):
        import inspect

        from app.agent_runtime.scripts import dispatch

        source = inspect.getsource(dispatch)
        assert "execution_mode" not in source
        assert "compiled-only" not in source
        assert "resolve_mode" not in source


# ── Unconditional fallback on typed failures (E2, F1, F2) ─────────────────────


class TestUnconditionalFallback:
    @pytest.mark.parametrize(
        ("exc", "expected_trigger"),
        [
            (ExecutionError("tool transport failed"), TRIGGER_EXECUTION_ERROR),
            (SchemaMismatch("missing expected keys: ['id']"), TRIGGER_SCHEMA_MISMATCH),
            (OutputValidationFailure("bad shape"), TRIGGER_OUTPUT_VALIDATION),
        ],
    )
    async def test_any_script_failure_falls_back_and_run_completes(
        self, exc, expected_trigger
    ):
        registry = FakeRegistryClient()

        async def _llm(_ctx: dict) -> Any:
            return "llm-result"

        result = await _controller(registry).run_with_fallback(
            _failing_run(exc),
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="sess-9",
            agent_type_id="at-1",
            llm_fallback=_llm,
        )
        assert result == "llm-result"
        assert len(registry.fallbacks) == 1
        event = registry.fallbacks[0]
        assert event["trigger_reason"] == expected_trigger
        assert event["script_version_id"] == "ver-1"
        assert str(exc) in event["failure_detail"]
        # Execution recorded as fell_back first, and linked to the event
        assert registry.executions[0]["outcome"] == "fell_back"
        assert registry.executions[0]["session_id"] == "sess-9"
        assert event["execution_record_id"] == "exec-1"

    async def test_unclassified_script_error_subclass_classified_as_execution_error(self):
        class WeirdScriptFailure(ScriptExecutionError):
            pass

        registry = FakeRegistryClient()

        async def _llm(_ctx: dict) -> Any:
            return "x"

        await _controller(registry).run_with_fallback(
            _failing_run(WeirdScriptFailure("novel failure mode")),
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="s",
            agent_type_id="a",
            llm_fallback=_llm,
        )
        assert registry.fallbacks[0]["trigger_reason"] == TRIGGER_EXECUTION_ERROR

    async def test_non_script_exception_propagates_unmasked(self):
        registry = FakeRegistryClient()

        async def _llm(_ctx: dict) -> Any:
            return "x"

        with pytest.raises(RuntimeError, match="boom"):
            await _controller(registry).run_with_fallback(
                _failing_run(RuntimeError("boom")),
                script_version_id="ver-1",
                script_version_label="v1",
                session_id="s",
                agent_type_id="a",
                llm_fallback=_llm,
            )
        assert registry.fallbacks == []

    async def test_successful_script_run_returns_without_reports(self):
        registry = FakeRegistryClient()

        async def _run() -> Any:
            return {"result": "ok"}

        result = await _controller(registry).run_with_fallback(
            _run,
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="s",
            agent_type_id="a",
        )
        assert result == {"result": "ok"}
        assert registry.executions == []
        assert registry.fallbacks == []


# ── Repair handoff (E9/E10, F3) ───────────────────────────────────────────────


class TestRepairHandoff:
    async def test_no_llm_path_wired_is_a_wiring_error_reported_then_raised(self):
        """Unconditional fallback is the fixed strategy — a missing LLM path
        is a wiring error, not a mode-conditional outcome."""
        registry = FakeRegistryClient()
        with pytest.raises(ExecutionError):
            await _controller(registry).run_with_fallback(
                _failing_run(ExecutionError("x")),
                script_version_id="ver-1",
                script_version_label="v1",
                session_id="s",
                agent_type_id="a",
            )
        assert registry.fallbacks[0]["resulting_action"] == ACTION_REPAIR_NOT_PRODUCED

    async def test_repair_candidate_reported_when_produced(self):
        registry = FakeRegistryClient(repaired_version_id="repaired-1")

        async def _llm(_ctx: dict) -> Any:
            return "ok"

        await _controller(registry).run_with_fallback(
            _failing_run(ExecutionError("x")),
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="s",
            agent_type_id="a",
            llm_fallback=_llm,
        )
        # Repair reporting is the dispatcher/repair loop's job via report_repair;
        # the fallback event records the LLM completion here.
        assert registry.fallbacks[0]["resulting_action"] == ACTION_LLM_COMPLETED


# ── Serving-version lookup (E1, E3, SEC4) ─────────────────────────────────────


class _FakeServingRegistry:
    def __init__(self, payload: dict[str, Any] | None, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.calls: list[str] = []

    async def get_serving_version(self, agent_type_id: str) -> dict[str, Any] | None:
        self.calls.append(agent_type_id)
        if self.fail:
            raise RuntimeError("registry unavailable")
        return self.payload


class TestServingVersionLookup:
    def setup_method(self) -> None:
        reset_serving_cache()

    def teardown_method(self) -> None:
        reset_serving_cache()

    async def test_serving_script_built_from_registry_payload(self):
        registry = _FakeServingRegistry(
            {
                "script_definition_id": "def-1",
                "script_version_id": "ver-1",
                "script_version_label": "v1",
                "declarative_step_graph": {"name": "g", "steps": []},
            }
        )
        serving = await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        assert isinstance(serving, _ServingScript)
        assert serving.script_version_id == "ver-1"
        assert serving.script_definition_id == "def-1"
        assert serving.graph_json == {"name": "g", "steps": []}

    async def test_no_serving_version_returns_none_llm_path(self):
        registry = _FakeServingRegistry(None)
        serving = await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        assert serving is None  # → run_llm() without error (E3)

    async def test_registry_failure_degrades_to_llm_path_never_blocks(self):
        """A CC lookup failure must never block execution — AR never reads
        the DB and the run degrades to the LLM path (SEC4, E3). The registry
        client wraps all transport errors in ScriptRegistryClientError."""
        from app.agent_runtime.scripts.cc_client import ScriptRegistryClientError

        class _FailingRegistry(_FakeServingRegistry):
            async def get_serving_version(self, agent_type_id):
                raise ScriptRegistryClientError("registry unavailable")

        registry = _FailingRegistry(None)
        serving = await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        assert serving is None

    async def test_lookup_is_always_fresh_per_agent_type(self):
        """No serving-lookup cache: every call hits the registry, so a
        CC-side retirement is visible on the very next lookup."""
        registry = _FakeServingRegistry(
            {
                "script_definition_id": "def-1",
                "script_version_id": "ver-1",
                "script_version_label": "v1",
                "declarative_step_graph": {"name": "g", "steps": []},
            }
        )
        await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        assert registry.calls == ["at-1", "at-1"]


class TestRetireFreshness:
    """Retiring the optimized plan (or its serving script) in Control Center
    must be visible to the dispatcher on the NEXT run — no TTL cache may serve
    a stale lookup after retirement (the "Retire plan doesn't retire" defect:
    CC deletes the rows but the dispatcher's cached freshness check kept
    using the retired plan / serving script for the cache TTL)."""

    def setup_method(self) -> None:
        reset_serving_cache()

    def teardown_method(self) -> None:
        reset_serving_cache()

    async def test_retired_serving_version_not_served_from_cache(self):
        registry = _FakeServingRegistry(
            {
                "script_definition_id": "def-1",
                "script_version_id": "ver-1",
                "script_version_label": "v1",
                "declarative_step_graph": {"name": "g", "steps": []},
            }
        )
        first = await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        assert first is not None
        # Retire: the registry now serves nothing.
        registry.payload = None
        second = await _get_serving_script(registry, "at-1")  # type: ignore[arg-type]
        assert second is None
        assert registry.calls == ["at-1", "at-1"]

    async def test_retired_optimized_plan_not_served_from_cache(self):
        from app.agent_runtime.scripts.dispatch import _get_optimized_plan

        class _PlanRegistry:
            def __init__(self):
                self.payload: dict[str, Any] | None = {
                    "optimized_plan_id": "op-1",
                    "status": "ready",
                    "fully_scripted": True,
                }
                self.calls: list[str] = []

            async def get_optimized_plan(self, agent_type_id: str):
                self.calls.append(agent_type_id)
                return self.payload

        registry = _PlanRegistry()
        first = await _get_optimized_plan(registry, "at-1")  # type: ignore[arg-type]
        assert first is not None
        # Retire: CC now reports no fresh plan.
        registry.payload = None
        second = await _get_optimized_plan(registry, "at-1")  # type: ignore[arg-type]
        assert second is None
        assert registry.calls == ["at-1", "at-1"]


# ── Security invariance (SEC) ─────────────────────────────────────────────────


class TestPermissionInvariance:
    async def test_llm_path_receives_identical_run_context_no_widening(self):
        """Fallback never widens permissions: the LLM path gets exactly the
        run context the script path had — same identity, same agent type."""
        registry = FakeRegistryClient()
        seen: dict[str, Any] = {}

        async def _llm(ctx: dict) -> Any:
            seen.update(ctx)
            return "ok"

        run_context = {
            "session_id": "sess-1",
            "agent_type_id": "at-7",
            "identity": "agent-identity-token-placeholder",
        }
        await _controller(registry).run_with_fallback(
            _failing_run(SchemaMismatch("drift")),
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="sess-1",
            agent_type_id="at-7",
            llm_fallback=_llm,
            run_context=run_context,
        )
        assert seen == run_context


# ── Phase 3: sandbox fallback triggers (Flow C) & measured accounting ────────


class TestSandboxFallbackTriggers:
    async def test_sandbox_violation_triggers_sandbox_violation_reason(self):
        from app.agent_runtime.scripts.sandbox import SandboxViolationError

        registry = FakeRegistryClient()
        await _controller(registry).run_with_fallback(
            _failing_run(SandboxViolationError("import of 'os' is not allowed")),
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="sess-1",
            agent_type_id="at-1",
            llm_fallback=_ok_llm,
        )
        assert registry.fallbacks[0]["trigger_reason"] == "sandbox_violation"
        execution = registry.executions[0]
        assert execution["sandbox_termination"] is False
        assert "os" in execution["sandbox_violation_detail"]

    async def test_resource_limit_triggers_resource_limit_reason(self):
        from app.agent_runtime.scripts.sandbox import ResourceLimitExceededError

        registry = FakeRegistryClient()
        await _controller(registry).run_with_fallback(
            _failing_run(ResourceLimitExceededError("wall-time limit")),
            script_version_id="ver-2",
            script_version_label="v2",
            session_id="sess-2",
            agent_type_id="at-1",
            llm_fallback=_ok_llm,
        )
        assert registry.fallbacks[0]["trigger_reason"] == "resource_limit_exceeded"
        assert registry.executions[0]["sandbox_termination"] is True

    async def test_sandbox_failure_recorded_even_without_llm_path(self):
        from app.agent_runtime.scripts.sandbox import SandboxViolationError

        registry = FakeRegistryClient()
        with pytest.raises(SandboxViolationError):
            await _controller(registry).run_with_fallback(
                _failing_run(SandboxViolationError("dunder traversal")),
                script_version_id="ver-3",
                script_version_label="v3",
                session_id="sess-3",
                agent_type_id="at-1",
                llm_fallback=None,
            )
        assert registry.fallbacks[0]["trigger_reason"] == "sandbox_violation"
        assert (
            registry.fallbacks[0]["resulting_action"] == ACTION_REPAIR_NOT_PRODUCED
        )


async def _ok_llm(ctx: dict[str, Any] | None = None) -> str:
    return "llm-completed"


class TestTokensSavedActual:
    async def test_dispatch_reports_measured_tokens_when_reference_known(self):
        from app.agent_runtime.scripts.dispatch import _report_success_execution

        class _Registry(FakeRegistryClient):
            pass

        registry = _Registry()
        await _report_success_execution(
            registry,  # type: ignore[arg-type]
            script_version_id="ver-9",
            telemetry={"tools_invoked": [{"step": "s1"}], "model_backed_steps_used": []},
            session_id="sess-9",
            reference_tokens=5000,
        )
        payload = registry.executions[0]
        assert payload["tokens_saved_actual"] == 5000
        assert payload["tokens_saved_estimate"] == 1000

    async def test_dispatch_reports_estimate_only_without_reference(self):
        from app.agent_runtime.scripts.dispatch import _report_success_execution

        registry = FakeRegistryClient()
        await _report_success_execution(
            registry,  # type: ignore[arg-type]
            script_version_id="ver-9",
            telemetry={"tools_invoked": [], "model_backed_steps_used": []},
            session_id="sess-9",
        )
        payload = registry.executions[0]
        assert "tokens_saved_actual" not in payload
        assert payload["tokens_saved_estimate"] == 0


class TestSandboxedDispatchPath:
    async def test_python_source_version_routes_to_sandbox_path(self):
        """A serving payload carrying python_source is recognized (the
        dispatcher's sandboxed path uses it instead of the step graph)."""
        payload = {
            "script_definition_id": "def-1",
            "script_version_id": "ver-py",
            "script_version_label": "v1",
            "declarative_step_graph": None,
            "python_source": "def run(context, tools):\n    return {}",
            "sandbox_validation_status": "passed",
            "cpu_limit_seconds": 5,
            "memory_limit_mb": 256,
            "wall_time_limit_seconds": 10,
            "reference_tokens": None,
        }
        from app.agent_runtime.scripts.cc_client import ScriptRegistryClient

        class _Registry(ScriptRegistryClient):
            def __init__(self) -> None:
                super().__init__(cert_manager=None)  # type: ignore[arg-type]

            async def get_serving_version(self, agent_type_id, workflow_skill_id=None):
                return payload

        reset_serving_cache()
        serving = await _get_serving_script(_Registry(), "at-1")  # type: ignore[arg-type]
        assert serving is not None
        assert serving.python_source and "run(context, tools)" in serving.python_source
        assert serving.wall_time_limit_seconds == 10
        reset_serving_cache()


# ── String output passthrough (session output = raw string, not {"result": …}) ─


class _RecordingDataClient:
    """Minimal CC data client double for the script completion path."""

    def __init__(self) -> None:
        self.completed: list[Any] = []
        self._cert_manager: Any = None

    async def log_execution_event(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def mark_session_completed(
        self, session_id: str, output_data: Any
    ) -> None:
        self.completed.append(output_data)


class TestStringOutputPassthrough:
    async def test_string_render_output_stored_as_plain_string(self):
        """A string final result (render output) reaches mark_session_completed
        as the raw string — never wrapped as {"result": ...}."""
        from app.agent_runtime.scripts.dispatch import _ServingScript, _run_script_path

        graph = {
            "name": "g",
            "steps": [
                {"kind": "transform", "name": "t1", "op": "constant", "value": "world", "output_key": "who"},
                {"kind": "transform", "name": "t2", "op": "template", "template": "hello {{who}}", "output_key": "greeting"},
                {"kind": "output", "name": "out", "output_key": "greeting"},
            ],
        }
        data_client = _RecordingDataClient()
        called_llm = False

        async def run_llm() -> None:
            nonlocal called_llm
            called_llm = True

        await _run_script_path(
            session_id="sess-1",
            agent_type_id="at-1",
            data_client=data_client,
            cert_manager=None,
            registry_client=FakeRegistryClient(),  # type: ignore[arg-type]
            serving=_ServingScript(
                script_definition_id="def-1",
                script_version_id="ver-1",
                script_version_label="v1",
                graph_json=graph,
            ),
            run_llm=run_llm,
        )

        assert not called_llm
        assert data_client.completed == ["hello world"]

    async def test_dict_result_kept_as_is(self):
        """Dict results (deterministic outputs) are stored as-is."""
        from app.agent_runtime.scripts.dispatch import _ServingScript, _run_script_path

        graph = {
            "name": "g",
            "steps": [
                {"kind": "transform", "name": "t1", "op": "constant", "value": {"a": 1}, "output_key": "payload"},
                {"kind": "output", "name": "out", "output_key": "payload"},
            ],
        }
        data_client = _RecordingDataClient()

        async def run_llm() -> None:
            raise AssertionError("LLM path must not run")

        await _run_script_path(
            session_id="sess-2",
            agent_type_id="at-1",
            data_client=data_client,
            cert_manager=None,
            registry_client=FakeRegistryClient(),  # type: ignore[arg-type]
            serving=_ServingScript(
                script_definition_id="def-1",
                script_version_id="ver-1",
                script_version_label="v1",
                graph_json=graph,
            ),
            run_llm=run_llm,
        )

        assert data_client.completed == [{"a": 1}]


# ── fully_scripted dispatch gating (product decision) ─────────────────────────


class _LoadedCert:
    """Minimal cert manager double that reports as loaded (SEC1 parity)."""

    is_loaded = True


class _LoadedCertDataClient:
    """CC data client double whose cert manager is loaded (dispatch proceeds)."""

    def __init__(self) -> None:
        self._cert_manager = _LoadedCert()


class TestCommandExecutionBypass:
    """A command-driven side execution (``__command`` marker) must NEVER be
    intercepted by script-first dispatch or the optimized-plan preference — it
    runs the plain LLM loop with the command's mission prompt, even when a
    fully_scripted serving script / fresh optimized plan exists."""

    def _patch_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        calls: dict[str, int],
    ) -> None:
        from app.agent_runtime.scripts import dispatch

        async def _fake_get_serving(registry_client, agent_type_id):
            calls["serving"] += 1
            return _ServingScript(
                script_definition_id="def-1",
                script_definition_name="optimized-abc12345",
                script_version_id="ver-1",
                script_version_label="v1",
                graph_json={"name": "g", "steps": []},
                fully_scripted=True,
                is_optimized_artifact=True,
            )

        async def _fake_get_optimized(registry_client, agent_type_id):
            calls["optimized"] += 1
            return {
                "optimized_plan_id": "op-1",
                "status": "ready",
                "fully_scripted": True,
            }

        async def _fake_script_path(**kwargs):
            calls["script_path"] += 1

        async def _fake_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm):
            calls["llm_path"] += 1
            await run_llm()

        monkeypatch.setattr(dispatch, "_get_serving_script", _fake_get_serving)
        monkeypatch.setattr(dispatch, "_get_optimized_plan", _fake_get_optimized)
        monkeypatch.setattr(dispatch, "_run_script_path", _fake_script_path)
        monkeypatch.setattr(dispatch, "_run_llm_path", _fake_llm_path)

    async def test_command_session_bypasses_script_dispatch(self, monkeypatch):
        from app.agent_runtime.scripts import dispatch

        calls = {"serving": 0, "optimized": 0, "script_path": 0, "llm_path": 0}
        self._patch_dispatch(monkeypatch, calls)
        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-cmd", "at-1", _LoadedCertDataClient(), run_llm,
            input_data={"__command": "optimize-and-verify", "message": "author"},
        )

        assert ran_llm is True
        assert calls["serving"] == 0
        assert calls["optimized"] == 0
        assert calls["script_path"] == 0
        assert calls["llm_path"] == 0  # direct run_llm(), not the dispatcher LLM path

    async def test_non_command_session_still_follows_script_first(self, monkeypatch):
        """Regression: a NON-command session keeps script-first/optimized-plan
        preference (zero-LLM when a fresh fully_scripted optimized plan + serving
        script exist)."""
        from app.agent_runtime.scripts import dispatch

        calls = {"serving": 0, "optimized": 0, "script_path": 0, "llm_path": 0}
        self._patch_dispatch(monkeypatch, calls)
        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-normal", "at-1", _LoadedCertDataClient(), run_llm,
            input_data={"message": "run workflow"},
        )

        assert calls["script_path"] == 1
        assert calls["llm_path"] == 0
        assert ran_llm is False  # zero-LLM software mode


class TestFullyScriptedDispatchGating:
    """Execution semantics: only a ``fully_scripted=true`` serving script runs
    directly (zero-LLM software mode). A ``fully_scripted=false`` serving script
    is NOT served directly — it falls to the LLM path and is instead exposed to
    the agent as an invocable ``script____<name>`` virtual tool."""

    def _serving(self, *, fully_scripted: bool) -> _ServingScript:
        return _ServingScript(
            script_definition_id="def-1",
            script_definition_name="optimized-abc12345",
            script_version_id="ver-1",
            script_version_label="v1",
            graph_json={"name": "g", "steps": []},
            fully_scripted=fully_scripted,
            is_optimized_artifact=True,
        )

    def _legacy_serving(self, *, fully_scripted: bool) -> _ServingScript:
        """A legacy AUTO-COMPILED serving script (never an optimized artifact)."""
        return _ServingScript(
            script_definition_id="def-legacy",
            script_definition_name="auto-abc12345",
            script_version_id="ver-legacy",
            script_version_label="auto-1",
            graph_json={"name": "g", "steps": []},
            fully_scripted=fully_scripted,
            is_optimized_artifact=False,
        )

    def _patch_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        serving: _ServingScript,
        optimized: dict[str, Any] | None = ...,
    ) -> dict[str, int]:
        """Stub the serving lookup + optimized-plan freshness + both execution
        paths to count branches.

        ``optimized=...`` (default) leaves the optimized-plan lookup unstubbed
        only when the caller does not care; pass ``None`` for "no fresh
        optimized plan (stale/absent/failed)" or a payload dict for "fresh
        ready optimized plan".
        """
        from app.agent_runtime.scripts import dispatch

        calls = {"script_path": 0, "llm_path": 0}

        async def _fake_get_serving(registry_client, agent_type_id):
            return serving

        async def _fake_script_path(**kwargs):
            calls["script_path"] += 1

        async def _fake_llm_path(
            session_id, agent_type_id, data_client, cert_manager, run_llm
        ):
            calls["llm_path"] += 1
            await run_llm()

        monkeypatch.setattr(dispatch, "_get_serving_script", _fake_get_serving)
        monkeypatch.setattr(dispatch, "_run_script_path", _fake_script_path)
        monkeypatch.setattr(dispatch, "_run_llm_path", _fake_llm_path)
        if optimized is not ...:
            async def _fake_get_optimized(registry_client, agent_type_id):
                return optimized

            monkeypatch.setattr(
                dispatch, "_get_optimized_plan", _fake_get_optimized
            )
        return calls

    async def test_fully_scripted_true_runs_script_path_zero_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from app.agent_runtime.scripts import dispatch

        # A fully_scripted serving script is an optimized-plan artifact: the
        # fresh ready optimized plan gates the zero-LLM path.
        calls = self._patch_dispatch(
            monkeypatch,
            self._serving(fully_scripted=True),
            optimized={
                "optimized_plan_id": "op-1",
                "status": "ready",
                "fully_scripted": True,
            },
        )
        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-1", "at-1", _LoadedCertDataClient(), run_llm
        )

        assert calls["script_path"] == 1
        assert calls["llm_path"] == 0
        assert ran_llm is False  # zero-LLM software mode

    async def test_fully_scripted_false_falls_to_llm_path_exposed_as_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        from app.agent_runtime.scripts import dispatch

        calls = self._patch_dispatch(
            monkeypatch, self._serving(fully_scripted=False), optimized=None
        )
        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-2", "at-1", _LoadedCertDataClient(), run_llm
        )

        assert calls["llm_path"] == 1
        assert calls["script_path"] == 0
        assert ran_llm is True  # LLM orchestrates; script is only a tool

    async def test_fully_scripted_without_fresh_optimized_plan_falls_to_llm_path(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Absent/stale/failed optimized plan → base-plan LLM path."""
        from app.agent_runtime.scripts import dispatch

        for optimized in (None,):
            calls = self._patch_dispatch(
                monkeypatch,
                self._serving(fully_scripted=True),
                optimized=optimized,
            )
            ran_llm = False

            async def run_llm() -> None:
                nonlocal ran_llm
                ran_llm = True

            await dispatch.run_session_script_first(
                "sess-stale", "at-1", _LoadedCertDataClient(), run_llm
            )

            assert calls["llm_path"] == 1, f"optimized={optimized!r}"
            assert calls["script_path"] == 0
            assert ran_llm is True

    async def test_fresh_optimized_plan_beats_legacy_serving_script(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Bug regression: a legacy auto-compiled fully_scripted serving script
        must NEVER shadow a fresh optimized plan. With a fresh fully_scripted
        optimized plan but only a legacy serving script present, the run takes
        the LLM path — the legacy script is not served."""
        from app.agent_runtime.scripts import dispatch

        async def _fake_get_serving(registry_client, agent_type_id):
            return self._legacy_serving(fully_scripted=True)

        async def _fake_get_optimized(registry_client, agent_type_id):
            return {
                "optimized_plan_id": "op-new",
                "status": "ready",
                "fully_scripted": True,
            }

        calls = {"script_path": 0, "llm_path": 0}

        async def _fake_script_path(**kwargs):
            calls["script_path"] += 1

        async def _fake_llm_path(
            session_id, agent_type_id, data_client, cert_manager, run_llm
        ):
            calls["llm_path"] += 1
            await run_llm()

        monkeypatch.setattr(dispatch, "_get_serving_script", _fake_get_serving)
        monkeypatch.setattr(dispatch, "_get_optimized_plan", _fake_get_optimized)
        monkeypatch.setattr(dispatch, "_run_script_path", _fake_script_path)
        monkeypatch.setattr(dispatch, "_run_llm_path", _fake_llm_path)

        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-legacy", "at-1", _LoadedCertDataClient(), run_llm
        )

        assert calls["llm_path"] == 1
        assert calls["script_path"] == 0
        assert ran_llm is True

    async def test_fresh_tool_mode_optimized_plan_never_serves_a_script(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Bug regression: tool-mode optimized plan → no script is served
        directly, even a fully_scripted optimized artifact — the LLM
        orchestrates and scripts stay ``script____<name>`` tools."""
        from app.agent_runtime.scripts import dispatch

        async def _fake_get_serving(registry_client, agent_type_id):
            return self._serving(fully_scripted=False)

        async def _fake_get_optimized(registry_client, agent_type_id):
            return {
                "optimized_plan_id": "op-tool",
                "status": "ready",
                "fully_scripted": False,
            }

        calls = {"script_path": 0, "llm_path": 0}

        async def _fake_script_path(**kwargs):
            calls["script_path"] += 1

        async def _fake_llm_path(
            session_id, agent_type_id, data_client, cert_manager, run_llm
        ):
            calls["llm_path"] += 1
            await run_llm()

        monkeypatch.setattr(dispatch, "_get_serving_script", _fake_get_serving)
        monkeypatch.setattr(dispatch, "_get_optimized_plan", _fake_get_optimized)
        monkeypatch.setattr(dispatch, "_run_script_path", _fake_script_path)
        monkeypatch.setattr(dispatch, "_run_llm_path", _fake_llm_path)

        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-tool", "at-1", _LoadedCertDataClient(), run_llm
        )

        assert calls["llm_path"] == 1
        assert calls["script_path"] == 0
        assert ran_llm is True

    async def test_optimized_plan_lookup_failure_falls_to_llm_path(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Optimized-plan unavailability (client error → ``None`` payload)
        never blocks execution — base-plan LLM fallback."""
        from app.agent_runtime.scripts import dispatch

        calls = self._patch_dispatch(
            monkeypatch, self._serving(fully_scripted=True), optimized=None
        )

        async def _none(registry_client, agent_type_id):
            return None

        monkeypatch.setattr(dispatch, "_get_optimized_plan", _none)
        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-err", "at-1", _LoadedCertDataClient(), run_llm
        )

        assert calls["llm_path"] == 1
        assert calls["script_path"] == 0

    async def test_get_optimized_plan_handles_registry_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The optimized-plan lookup is ALWAYS fresh (no cache — retirement
        must be visible on the next run) and a client error degrades to
        ``None`` (never blocks execution)."""
        from app.agent_runtime.scripts import dispatch

        class _FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            async def get_optimized_plan(self, agent_type_id):
                self.calls += 1
                return {
                    "optimized_plan_id": "op-1",
                    "status": "ready",
                    "fully_scripted": True,
                }

        client = _FakeClient()
        first = await dispatch._get_optimized_plan(client, "at-cache")  # type: ignore[arg-type]
        second = await dispatch._get_optimized_plan(client, "at-cache")  # type: ignore[arg-type]
        assert first is not None and second is not None
        assert client.calls == 2  # always fresh — every lookup hits the registry

        class _BrokenClient:
            async def get_optimized_plan(self, agent_type_id):
                from app.agent_runtime.scripts.cc_client import (
                    ScriptRegistryClientError,
                )

                raise ScriptRegistryClientError("boom")

        payload = await dispatch._get_optimized_plan(_BrokenClient(), "at-broken")  # type: ignore[arg-type]
        assert payload is None


# ── Issue regression: optimized plan used on the NEXT run (lineage, not name) ─


class TestOptimizedPlanUsedOnNextRun:
    """Mirrors the live defect: the optimize command authors scripts under
    AGENT-CHOSEN definition names (e.g. ``fetch-orders``) linked to the
    optimized plan via ``source_optimized_plan_id`` — never ``optimized-<id8>``.
    The dispatcher must still serve the fresh fully_scripted plan zero-LLM on
    the next run."""

    def _serving_payload(self) -> dict[str, Any]:
        return {
            "script_definition_id": "def-opt",
            "script_definition_name": "fetch-orders",  # agent-chosen, NOT optimized-*
            "source_optimized_plan_id": "op-1",
            "script_version_id": "ver-opt",
            "script_version_label": "v1",
            "declarative_step_graph": None,
            "python_source": "def run(context, tools):\n    return {'result': 'ok'}",
            "sandbox_validation_status": "passed",
            "fully_scripted": True,
        }

    async def test_lineage_linked_serving_script_is_optimized_artifact(self):
        from app.agent_runtime.scripts.cc_client import ScriptRegistryClient

        payload = self._serving_payload()

        class _Registry(ScriptRegistryClient):
            def __init__(self) -> None:
                super().__init__(cert_manager=None)  # type: ignore[arg-type]

            async def get_serving_version(self, agent_type_id, workflow_skill_id=None):
                return payload

        reset_serving_cache()
        serving = await _get_serving_script(_Registry(), "at-1")  # type: ignore[arg-type]
        reset_serving_cache()
        assert serving is not None
        assert serving.is_optimized_artifact is True

    async def test_fresh_fully_scripted_plan_dispatches_zero_llm(self, monkeypatch):
        """Full dispatch path of the live state: fresh ready fully_scripted
        optimized plan + lineage-linked serving script → script path, LLM never
        runs."""
        from app.agent_runtime.scripts import dispatch

        optimized_payload = {
            "optimized_plan_id": "op-1",
            "status": "ready",
            "fully_scripted": True,
        }

        async def _fake_get_optimized(registry_client, agent_type_id):
            return optimized_payload

        async def _fake_get_serving(registry_client, agent_type_id):
            payload = self._serving_payload()
            return dispatch._ServingScript(
                script_definition_id=str(payload["script_definition_id"]),
                script_definition_name=payload["script_definition_name"],
                script_version_id=str(payload["script_version_id"]),
                script_version_label=payload["script_version_label"],
                graph_json=payload["declarative_step_graph"],
                python_source=payload["python_source"],
                sandbox_validation_status=payload["sandbox_validation_status"],
                fully_scripted=payload["fully_scripted"],
                is_optimized_artifact=True,
            )

        async def _fake_script_path(**kwargs):
            calls["script_path"] += 1

        async def _fake_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm):
            calls["llm_path"] += 1
            await run_llm()

        calls = {"script_path": 0, "llm_path": 0}
        monkeypatch.setattr(dispatch, "_get_optimized_plan", _fake_get_optimized)
        monkeypatch.setattr(dispatch, "_get_serving_script", _fake_get_serving)
        monkeypatch.setattr(dispatch, "_run_script_path", _fake_script_path)
        monkeypatch.setattr(dispatch, "_run_llm_path", _fake_llm_path)

        ran_llm = False

        async def run_llm() -> None:
            nonlocal ran_llm
            ran_llm = True

        await dispatch.run_session_script_first(
            "sess-next", "at-1", _LoadedCertDataClient(), run_llm,
            input_data={"message": "run the workflow"},
        )
        assert calls["script_path"] == 1
        assert calls["llm_path"] == 0
        assert ran_llm is False  # zero-LLM software mode on the NEXT run
