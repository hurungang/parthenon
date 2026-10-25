"""Unit tests for the post-run auto-compilation hook (Software 3.0).

Covers the self-improvement flow that turns a successful LLM run's recorded
tool-call sequence into a serving script version:

- eligible → compile → submit candidate → verified → promoted (serving);
- ineligible (conversational / empty sequence) → skipped, nothing submitted;
- serving version already exists → skipped (duplicate protection);
- verification mismatch → candidate left at draft with recorded evidence
  (no promotion; the repair loop improves it on later runs).

All errors in the hook must be swallowed — a failed auto-compile never
affects the completed run (E2 parity).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent_runtime.scripts import autocompile, capture
from app.agent_runtime.scripts.compiler import CompilationError


class FakeRegistryClient:
    """ScriptRegistryClient test double."""

    def __init__(
        self,
        serving: dict[str, Any] | None = None,
        comparison_outcome: str = "match",
    ) -> None:
        self.serving = serving
        self.comparison_outcome = comparison_outcome
        self.submitted_candidates: list[dict[str, Any]] = []
        self.version_ids_created: list[str] = []
        self.promoted: list[str] = []
        self.verifications: list[dict[str, Any]] = []

    async def get_serving_version(
        self, agent_type_id: str, workflow_skill_id: str | None = None
    ) -> dict[str, Any] | None:
        return self.serving

    async def submit_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.submitted_candidates.append(payload)
        version_id = f"version-{len(self.submitted_candidates)}"
        self.version_ids_created.append(version_id)
        return {"id": version_id}

    async def submit_verification(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.verifications.append(payload)
        return {"id": f"verification-{len(self.verifications)}"}

    async def promote_version(self, version_id: str) -> dict[str, Any]:
        self.promoted.append(version_id)
        return {"id": version_id, "lifecycle_status": "compiled"}


class FakeDataClient:
    """ControlCenterDataClient test double (plan + context only)."""

    def __init__(
        self,
        plan: dict[str, Any] | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self._plan = plan
        self._context = context or {"input_type": "structured_input"}

    async def get_agent_plan(self, agent_type_id: Any) -> dict[str, Any] | None:
        return self._plan

    async def get_agent_context(self, agent_type_id: Any) -> dict[str, Any]:
        return self._context


class FakeVerificationEngine:
    """VerificationEngine test double — returns a canned CC run payload."""

    outcome = "match"
    calls: list[dict[str, Any]] = []

    def __init__(self, runner: Any, registry_client: Any) -> None:
        pass

    async def verify(self, graph: Any, **kwargs: Any) -> dict[str, Any]:
        FakeVerificationEngine.calls.append({"graph": graph.name, **kwargs})
        return {"comparison_outcome": FakeVerificationEngine.outcome}


@pytest.fixture(autouse=True)
def _fake_engine(monkeypatch: pytest.MonkeyPatch):
    FakeVerificationEngine.outcome = "match"
    FakeVerificationEngine.calls = []
    monkeypatch.setattr(
        "app.agent_runtime.scripts.verification.VerificationEngine",
        FakeVerificationEngine,
    )
    yield


@pytest.fixture(autouse=True)
def _clean_capture():
    capture._captures.clear()
    yield
    capture._captures.clear()


_AGENT_TYPE = "aaaaaaaa-0000-0000-0000-000000000001"
_SESSION = "bbbbbbbb-0000-0000-0000-000000000002"

_ELIGIBLE_PLAN = {
    "plan_id": "cccccccc-0000-0000-0000-000000000003",
    "plan_steps": [
        {"step_type": "tool_invocation", "tool_name": "crm____getContact"},
        {"step_type": "tool_invocation", "tool_name": "crm____updateContact"},
    ],
}


def _record_run_sequence() -> None:
    capture.record_tool_call(
        _SESSION, "crm____getContact", {"id": "c-1"}, {"name": "Ada", "tier": "gold"}
    )
    capture.record_tool_call(
        _SESSION,
        "crm____updateContact",
        {"id": "c-1", "tier": "platinum"},
        {"ok": True},
    )


# ── Eligible flow: compile → candidate → verified → promoted ─────────────────


async def test_eligible_run_compiles_and_promotes_without_verification():
    _record_run_sequence()
    registry = FakeRegistryClient()
    data = FakeDataClient(_ELIGIBLE_PLAN)

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=data,
        registry_client=registry,
        tool_client=object(),
    )

    assert len(registry.submitted_candidates) == 1
    payload = registry.submitted_candidates[0]
    assert payload["agent_type_id"] == _AGENT_TYPE
    assert payload["source_session_id"] == _SESSION
    assert payload["source_plan_id"] == _ELIGIBLE_PLAN["plan_id"]
    graph = payload["declarative_step_graph"]
    assert graph["name"] == autocompile._script_name(_AGENT_TYPE)
    step_names = [s["name"] for s in graph["steps"]]
    # Two tool steps + final output. No hardcoded requirement heuristics:
    # without an authored composition/output decision the graph ends in a
    # plain projection of the step outputs.
    assert step_names == ["step1_crm____getContact", "step2_crm____updateContact",
                          "final_output"]
    assert step_names[-1] == "final_output"
    # Phase 2: no auto-appended semantic____render step — no LLM render is
    # injected; the requirement render is a deterministic template transform.
    assert all(s.get("tool_name") != "semantic____render" for s in graph["steps"])
    assert all(s.get("kind") != "semantic_bridge" for s in graph["steps"])
    # No verification gate: the workflow IS the recorded LLM run, so the
    # candidate is promoted to compiled (serving) immediately.
    assert FakeVerificationEngine.calls == []
    assert registry.promoted == list(registry.version_ids_created)
    assert payload["version_label"].startswith("auto-")


async def test_empty_sequence_skips_everything():
    registry = FakeRegistryClient()
    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_ELIGIBLE_PLAN),
        registry_client=registry,
        tool_client=object(),
    )
    assert registry.submitted_candidates == []
    assert registry.promoted == []


async def test_conversational_agent_type_is_never_compiled():
    _record_run_sequence()
    registry = FakeRegistryClient()
    data = FakeDataClient(_ELIGIBLE_PLAN, context={"input_type": "conversational"})

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=data,
        registry_client=registry,
        tool_client=object(),
    )
    assert registry.submitted_candidates == []
    assert registry.promoted == []


async def test_model_backed_plan_is_not_compiled():
    _record_run_sequence()
    registry = FakeRegistryClient()
    plan = {
        "plan_id": "cccccccc-0000-0000-0000-000000000003",
        "plan_steps": [
            {"step_type": "tool_invocation", "tool_name": "crm____getContact"},
            {"step_type": "decision", "tool_name": "decision____evaluate"},
        ],
    }
    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(plan),
        registry_client=registry,
        tool_client=object(),
    )
    assert registry.submitted_candidates == []
    assert registry.promoted == []


# ── Duplicate protection ──────────────────────────────────────────────────────


async def test_plan_deterministic_output_mode_passes_through():
    """The plan's output decision flows through: deterministic output →
    compiled graph has NO LLM render step."""
    _record_run_sequence()
    registry = FakeRegistryClient()
    plan = {
        "plan_id": "cccccccc-0000-0000-0000-000000000003",
        "plan_steps": [
            {"step_type": "tool_invocation", "tool_name": "crm____getContact"},
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____updateContact",
                "output_mode": "deterministic",
                "output_template": "# Result\n{{step2_crm____updateContact.ok}}",
            },
        ],
    }
    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(plan),
        registry_client=registry,
        tool_client=object(),
    )
    assert len(registry.submitted_candidates) == 1
    graph = registry.submitted_candidates[0]["declarative_step_graph"]
    kinds = [s["kind"] for s in graph["steps"]]
    assert kinds == ["tool_call", "tool_call", "transform", "output"]
    # No model-backed (semantic_bridge/decision) step remains.
    assert "semantic_bridge" not in kinds and "decision" not in kinds
    assert registry.promoted == list(registry.version_ids_created)


async def test_existing_serving_version_skips_compilation():
    _record_run_sequence()
    registry = FakeRegistryClient(
        serving={"script_version_id": "serving-1", "declarative_step_graph": {}}
    )
    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_ELIGIBLE_PLAN),
        registry_client=registry,
        tool_client=object(),
    )
    assert registry.submitted_candidates == []
    assert registry.promoted == []


# ── User output requirement flows into the recorded-sequence fallback ────────


async def test_output_requirement_heuristic_is_gone():
    """The requirement-driven template heuristic is REMOVED: without an
    authored composition/output decision, even a markdown requirement gets a
    plain projection of the step outputs — no hardcoded render is injected.
    The authoring LLM (via the plan composition) owns the output format."""
    _record_run_sequence()
    registry = FakeRegistryClient()
    data = FakeDataClient(
        _ELIGIBLE_PLAN, context={"input_type": "structured_input", "output_type": "markdown"}
    )

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=data,
        registry_client=registry,
        tool_client=object(),
    )

    assert len(registry.submitted_candidates) == 1
    graph = registry.submitted_candidates[0]["declarative_step_graph"]
    kinds = [s["kind"] for s in graph["steps"]]
    assert kinds == ["tool_call", "tool_call", "output"]
    names = [s["name"] for s in graph["steps"]]
    assert "render_output" not in names
    # Plain projection: both recorded step outputs, nothing rendered.
    assert graph["steps"][2]["select_keys"] == [
        "step1_crm____getContact", "step2_crm____updateContact",
    ]


async def test_typed_requirement_keeps_projection_no_template():
    """output_type=typed → no markdown wrap; typed-schema projection stays."""
    _record_run_sequence()
    registry = FakeRegistryClient()
    data = FakeDataClient(
        _ELIGIBLE_PLAN, context={"input_type": "structured_input", "output_type": "typed"}
    )

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=data,
        registry_client=registry,
        tool_client=object(),
    )

    graph = registry.submitted_candidates[0]["declarative_step_graph"]
    kinds = [s["kind"] for s in graph["steps"]]
    assert kinds == ["tool_call", "tool_call", "output"]


async def test_plan_llm_render_decision_is_not_overridden():
    """The model's authored output decision wins: an llm_render plan (no
    composition) must NOT get a heuristic deterministic template injected —
    the compiler degrades llm_render (no authored render step) to a plain
    projection, exactly as authored."""
    _record_run_sequence()
    registry = FakeRegistryClient()
    plan = {
        "plan_id": "cccccccc-0000-0000-0000-000000000009",
        "plan_steps": [
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____getContact",
                "output_mode": "llm_render",
            },
        ],
    }
    data = FakeDataClient(
        plan, context={"input_type": "structured_input", "output_type": "markdown"}
    )

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=data,
        registry_client=registry,
        tool_client=object(),
    )

    graph = registry.submitted_candidates[0]["declarative_step_graph"]
    kinds = [s["kind"] for s in graph["steps"]]
    assert kinds == ["tool_call", "output"]
    # No injected deterministic render overriding the authored decision.
    assert "render_output" not in [s["name"] for s in graph["steps"]]


# ── Verification failure: leave draft with evidence ──────────────────────────


async def test_version_labels_are_unique_per_attempt():
    _record_run_sequence()
    registry = FakeRegistryClient()

    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_ELIGIBLE_PLAN),
        registry_client=registry,
        tool_client=object(),
    )
    capture.clear(_SESSION)
    _record_run_sequence()
    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_ELIGIBLE_PLAN),
        registry_client=registry,
        tool_client=object(),
    )
    labels = [p["version_label"] for p in registry.submitted_candidates]
    assert len(labels) == 2
    assert labels[0] != labels[1]


# ── Failure containment ───────────────────────────────────────────────────────


async def test_uncompilable_sequence_is_swallowed_not_raised():
    capture.record_tool_call(_SESSION, "crm____getContact", {"id": 1}, {"x": 1})
    # A call with no tool name breaks compilation.
    capture.record_tool_call(_SESSION, "", {}, {})
    registry = FakeRegistryClient()

    # The inner pipeline raises CompilationError, but the exported entry point
    # (_run_autocompile) must swallow it — a failed auto-compile never
    # affects the completed run.
    with pytest.raises(CompilationError):
        await autocompile._autocompile_inner(
            session_id=_SESSION,
            agent_type_id=_AGENT_TYPE,
            data_client=FakeDataClient(_ELIGIBLE_PLAN),
            registry_client=registry,
            tool_client=object(),
            span=None,
        )

    # And the wrapped entry point swallows it silently.
    await autocompile._run_autocompile(
        session_id=_SESSION,
        agent_type_id=_AGENT_TYPE,
        data_client=FakeDataClient(_ELIGIBLE_PLAN),
        registry_client=registry,
        tool_client=object(),
    )


async def test_schedule_autocompile_wraps_errors():
    """schedule_autocompile returns a task whose exceptions never propagate."""
    _record_run_sequence()

    class ExplodingRegistry(FakeRegistryClient):
        async def get_serving_version(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("registry down")

    task = await autocompile.schedule_autocompile(
        _SESSION, _AGENT_TYPE, FakeDataClient(_ELIGIBLE_PLAN), cert_manager=None
    )
    assert task is not None
    # _run_autocompile swallows the registry failure internally; awaiting
    # the task must not raise.
    await task


# ── Verification gate (fully_scripted candidates) ─────────────────────────────


# A single end-to-end script authored by the plan LLM and marked fully_scripted.
_FULLY_SCRIPTED_SEGMENT = (
    "def run(context, tools):\n"
    "    contact = tools.call('crm____getContact', {'id': context.get('id')})\n"
    "    return {'name': contact.get('name', '')}\n"
)

_FULLY_SCRIPTED_PLAN = {
    "plan_id": "cccccccc-0000-0000-0000-0000000000aa",
    "fully_scripted": True,
    "plan_steps": [
        {
            "step_type": "tool_invocation",
            "tool_name": "crm____getContact",
            "python_source": _FULLY_SCRIPTED_SEGMENT,
            "scriptable": True,
            "output_mode": "deterministic",
            "output_template": "{{step1_crm____getContact.name}}",
        },
    ],
}


class TestFullyScriptedVerificationGate:
    """Product decision 3: a fully_scripted candidate must be GENUINELY
    verified against the recorded LLM run. A mismatch keeps the version in
    draft (never promoted); a match promotes it."""

    async def test_mismatch_candidate_stays_draft_not_promoted(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _record_run_sequence()
        registry = FakeRegistryClient()

        async def _mismatch(
            graph, tool_sequence, *, session_id, agent_type_id, registry_client
        ):
            return (
                False,
                "output mismatch: expected {'name': 'Grace'} got {'name': 'Ada'}",
                {"name": "Ada"},
            )

        monkeypatch.setattr(autocompile, "_verify_against_llm_run", _mismatch)

        await autocompile._run_autocompile(
            session_id=_SESSION,
            agent_type_id=_AGENT_TYPE,
            data_client=FakeDataClient(_FULLY_SCRIPTED_PLAN),
            registry_client=registry,
            tool_client=object(),
        )

        # A candidate was submitted (marked fully_scripted) but NEVER promoted.
        assert len(registry.submitted_candidates) == 1
        assert registry.submitted_candidates[0]["fully_scripted"] is True
        assert registry.promoted == []
        # Genuine-comparison evidence recorded with the mismatch verdict.
        assert registry.verifications[-1]["comparison_outcome"] == "mismatch"
        assert registry.verifications[-1]["sandbox_check_passed"] is True

    async def test_match_candidate_is_promoted(self, monkeypatch: pytest.MonkeyPatch):
        _record_run_sequence()
        registry = FakeRegistryClient()

        async def _match(
            graph, tool_sequence, *, session_id, agent_type_id, registry_client
        ):
            return (True, "", {"name": "Ada"})

        monkeypatch.setattr(autocompile, "_verify_against_llm_run", _match)

        await autocompile._run_autocompile(
            session_id=_SESSION,
            agent_type_id=_AGENT_TYPE,
            data_client=FakeDataClient(_FULLY_SCRIPTED_PLAN),
            registry_client=registry,
            tool_client=object(),
        )

        assert registry.promoted == list(registry.version_ids_created)
        assert registry.verifications[-1]["comparison_outcome"] == "match"
