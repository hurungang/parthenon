"""Unit tests for the Script Compiler (Agent Runtime) — C1, C2, C4, SEC3.

Covers:
- Compiling a recorded tool-call sequence into a candidate StepGraph (C2)
- Compiling an implementation plan into a candidate StepGraph (C1)
- Sequential data-flow templating between steps
- Decision-tool detection (``decision____`` prefix → DecisionStep)
- Typed rejection of empty sequences / unresolvable plan steps (opportunistic
  compilation — never forced)
- SEC3: credential-shaped fields are rejected from candidate graphs
- StepGraph schema validation rejections (unknown kind, duplicate names)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent_runtime.scripts.compiler import (
    DECISION_TOOL_PREFIX,
    CompilationError,
    ScriptCompiler,
)
from app.agent_runtime.scripts.schemas import (
    DecisionStep,
    OutputStep,
    SemanticBridgeStep,
    StepGraph,
    ToolCallStep,
)


@pytest.fixture()
def compiler() -> ScriptCompiler:
    return ScriptCompiler()


# ── C2: recorded tool-call sequence → candidate graph ────────────────────────


class TestCompileFromToolSequence:
    async def test_compiles_each_recorded_call_into_a_step(self, compiler):
        calls = [
            {"tool_name": "jira____search_issues", "tool_input": {"jql": "x"}, "tool_output": {"issues": []}},
            {"tool_name": "slack____post_message", "tool_input": {"text": "hi"}, "tool_output": {"ok": True}},
        ]
        graph = compiler.compile_from_tool_sequence(name="notify-flow", tool_calls=calls)

        assert isinstance(graph, StepGraph)
        tool_steps = [s for s in graph.steps if isinstance(s, ToolCallStep)]
        assert [s.tool_name for s in tool_steps] == [
            "jira____search_issues",
            "slack____post_message",
        ]
        # Phase 2: no auto-appended render step — the output step projects
        # exactly the authored steps (render steps only when model-authored).
        assert not [s for s in graph.steps if isinstance(s, SemanticBridgeStep)]
        outputs = [s for s in graph.steps if isinstance(s, OutputStep)]
        assert len(outputs) == 1
        assert outputs[0].output_key == "result"
        assert outputs[0].select_keys == [
            "step1_jira____search_issues",
            "step2_slack____post_message",
        ]

    async def test_expected_output_keys_captured_from_recorded_output(self, compiler):
        calls = [
            {
                "tool_name": "jira____search_issues",
                "tool_input": {},
                "tool_output": {"issues": [1, 2], "total": 2},
            },
        ]
        graph = compiler.compile_from_tool_sequence(name="cap", tool_calls=calls)
        step = next(s for s in graph.steps if isinstance(s, ToolCallStep))
        assert sorted(step.expected_output_keys) == ["issues", "total"]

    async def test_decision_tool_recorded_as_decision_step(self, compiler):
        calls = [
            {
                "tool_name": f"{DECISION_TOOL_PREFIX}approve",
                "tool_input": {"question": "ship?"},
                "tool_output": {"answer": "yes", "confidence": 0.9},
            },
        ]
        graph = compiler.compile_from_tool_sequence(name="gate", tool_calls=calls)
        decisions = [s for s in graph.steps if isinstance(s, DecisionStep)]
        assert len(decisions) == 1
        assert decisions[0].model_backed is True

    async def test_sequential_data_flow_becomes_template_reference(self, compiler):
        # Step 2's argument value equals step 1's output key → {{step1_...}}
        calls = [
            {"tool_name": "a____first", "tool_input": {}, "tool_output": {}},
            {
                "tool_name": "b____second",
                "tool_input": {"payload": "step1_a____first"},
                "tool_output": {},
            },
        ]
        graph = compiler.compile_from_tool_sequence(name="chained", tool_calls=calls)
        second = [s for s in graph.steps if isinstance(s, ToolCallStep)][1]
        assert second.argument_templates == {"payload": "{{step1_a____first}}"}

    async def test_empty_sequence_raises_compilation_error(self, compiler):
        with pytest.raises(CompilationError):
            compiler.compile_from_tool_sequence(name="empty", tool_calls=[])

    async def test_recorded_call_without_tool_name_raises(self, compiler):
        with pytest.raises(CompilationError, match="tool_name"):
            compiler.compile_from_tool_sequence(
                name="broken", tool_calls=[{"tool_input": {}}]
            )

    async def test_credential_shaped_recorded_input_rejected(self, compiler):
        calls = [
            {
                "tool_name": "api____call",
                "tool_input": {"api_key": "sk-secret"},
                "tool_output": {},
            },
        ]
        with pytest.raises(CompilationError, match="api_key"):
            compiler.compile_from_tool_sequence(name="leaky", tool_calls=calls)

    async def test_compiler_never_promotes_or_executes(self, compiler):
        """Compiler output is always a draft candidate graph — no lifecycle status,
        no execution side effects (C2 boundary)."""
        calls = [{"tool_name": "x____y", "tool_input": {}, "tool_output": {}}]
        graph = compiler.compile_from_tool_sequence(name="c", tool_calls=calls)
        assert not hasattr(graph, "lifecycle_status")
        assert not hasattr(graph, "execute")


# ── C1: implementation plan → candidate graph ────────────────────────────────


class TestCompileFromPlan:
    async def test_compiles_plan_steps_in_order(self, compiler):
        plan = [
            {"step_type": "tool_invocation", "tool_name": "a____query", "arguments": {"q": "x"}},
            {"step_type": "decision", "tool_name": "decision____gate", "arguments": {}},
            {"step_type": "tool_invocation", "tool_name": "b____act", "arguments": {}},
        ]
        graph = compiler.compile_from_plan(name="plan-flow", plan_steps=plan)
        assert len(graph.steps) == 4  # 3 plan steps + output step (no auto-render)
        kinds = [type(s).__name__ for s in graph.steps]
        assert kinds == [
            "ToolCallStep", "DecisionStep", "ToolCallStep", "OutputStep",
        ]

    async def test_decision_step_type_without_decision_prefix(self, compiler):
        plan = [{"step_type": "decision", "tool_name": "decision____choose", "arguments": {}}]
        graph = compiler.compile_from_plan(name="d", plan_steps=plan)
        assert isinstance(graph.steps[0], DecisionStep)

    async def test_skill_invocation_without_tool_name_raises(self, compiler):
        plan = [{"step_type": "skill_invocation"}]
        with pytest.raises(CompilationError, match="skill_invocation"):
            compiler.compile_from_plan(name="s", plan_steps=plan)

    async def test_tool_invocation_without_tool_name_raises(self, compiler):
        plan = [{"step_type": "tool_invocation"}]
        with pytest.raises(CompilationError, match="no tool_name"):
            compiler.compile_from_plan(name="t", plan_steps=plan)

    async def test_empty_plan_raises(self, compiler):
        with pytest.raises(CompilationError, match="empty"):
            compiler.compile_from_plan(name="e", plan_steps=[])

    async def test_plan_with_secret_argument_rejected(self, compiler):
        plan = [
            {
                "step_type": "tool_invocation",
                "tool_name": "x____y",
                "arguments": {"authorization": "Bearer abc"},
            },
        ]
        with pytest.raises(CompilationError, match="authorization"):
            compiler.compile_from_plan(name="sec", plan_steps=plan)

    async def test_all_deterministic_plan_has_zero_model_backed_steps(self, compiler):
        """Software 3.0: a fully deterministic plan compiles to a pure script —
        no LLM render step at all; typed JSON flows through unchanged."""
        plan = [
            {
                "step_type": "tool_invocation",
                "tool_name": "jira____search",
                "arguments": {"jql": "x"},
                "scriptable": True,
            },
            {
                "step_type": "tool_invocation",
                "tool_name": "slack____post",
                "output_mode": "deterministic",
                "scriptable": True,
            },
        ]
        graph = compiler.compile_from_plan(name="pure", plan_steps=plan)
        assert graph.model_backed_steps() == []
        kinds = [type(s).__name__ for s in graph.steps]
        assert kinds == ["ToolCallStep", "ToolCallStep", "OutputStep"]
        output = graph.steps[-1]
        assert output.select_keys == [
            "step1_jira____search", "step2_slack____post",
        ]

    async def test_deterministic_template_renders_without_llm(self, compiler):
        """output_template → deterministic TransformStep, still zero model calls."""
        plan = [
            {
                "step_type": "tool_invocation",
                "tool_name": "crm____getContact",
                "output_mode": "deterministic",
                "output_template": "# Contact\n{{step1_crm____getContact.name}}",
            },
        ]
        graph = compiler.compile_from_plan(name="tmpl", plan_steps=plan)
        assert graph.model_backed_steps() == []
        from app.agent_runtime.scripts.schemas import TransformOp, TransformStep

        transform = graph.steps[-2]
        assert isinstance(transform, TransformStep)
        assert transform.op == TransformOp.template
        assert transform.template == "# Contact\n{{step1_crm____getContact.name}}"
        assert transform.input_key == "step1_crm____getContact"
        assert "render_output" in graph.steps[-1].select_keys

    async def test_mixed_plan_llm_step_between_tool_segments(self, compiler):
        """scriptable:false in the middle → semantic-bridge step BETWEEN tool
        segments, then an LLM-render final output as the plan requested."""
        plan = [
            {"step_type": "tool_invocation", "tool_name": "a____fetch", "scriptable": True},
            {
                "step_type": "semantic_bridge",
                "scriptable": False,
                "description": "Classify the fetched record",
            },
            {"step_type": "tool_invocation", "tool_name": "b____act", "scriptable": True,
             "output_mode": "llm_render"},
        ]
        graph = compiler.compile_from_plan(name="mixed", plan_steps=plan)
        kinds = [type(s).__name__ for s in graph.steps]
        assert kinds == [
            "ToolCallStep", "SemanticBridgeStep", "ToolCallStep", "OutputStep",
        ]
        mid = graph.steps[1]
        assert mid.model_backed is True
        assert mid.input_key == "step1_a____fetch"
        # Phase 2: the requested llm_render output mode no longer auto-appends
        # a semantic____render step — only the output projection is appended.
        assert not isinstance(graph.steps[-2], SemanticBridgeStep)

    async def test_scriptable_false_plain_type_becomes_semantic_bridge(self, compiler):
        plan = [
            {
                "step_type": "tool_invocation",
                "tool_name": "a____fetch",
                "scriptable": False,
                "description": "Needs judgment",
            },
        ]
        graph = compiler.compile_from_plan(name="mark", plan_steps=plan)
        assert isinstance(graph.steps[0], SemanticBridgeStep)
        assert graph.steps[0].prompt_template == "Needs judgment"

    async def test_typed_schema_fallback_defaults_to_deterministic(self, compiler):
        """No plan output_mode + typed output schema → deterministic (no LLM)."""
        plan = [
            {"step_type": "tool_invocation", "tool_name": "a____fetch"},
        ]
        graph = compiler.compile_from_plan(
            name="typed",
            plan_steps=plan,
            typed_output_schema={"type": "object", "properties": {"x": {}}},
        )
        assert graph.model_backed_steps() == []
        assert isinstance(graph.steps[-1], OutputStep)

    async def test_unset_output_mode_projects_outputs_deterministically(
        self, compiler
    ):
        """Phase 2: unset output mode no longer auto-appends an LLM render
        step — outputs are projected deterministically (render steps exist
        only when the model's composition authors one)."""
        plan = [{"step_type": "tool_invocation", "tool_name": "a____fetch"}]
        graph = compiler.compile_from_plan(name="prose", plan_steps=plan)
        assert graph.model_backed_steps() == []
        assert graph.steps[-1].select_keys == ["step1_a____fetch"]

    async def test_tool_sequence_deterministic_output_mode_drops_render_step(
        self, compiler,
    ):
        calls = [
            {"tool_name": "crm____getContact", "tool_input": {}, "tool_output": {}},
            {"tool_name": "crm____updateContact", "tool_input": {}, "tool_output": {}},
        ]
        graph = compiler.compile_from_tool_sequence(
            name="det",
            tool_calls=calls,
            output_mode="deterministic",
        )
        assert graph.model_backed_steps() == []
        assert len(graph.steps) == 3


# ── StepGraph schema validation (S3) ─────────────────────────────────────────


class TestStepGraphSchema:
    def test_unknown_step_kind_rejected(self):
        with pytest.raises(ValidationError):
            StepGraph.model_validate(
                {
                    "name": "g",
                    "steps": [{"kind": "quantum_leap", "name": "s1"}],
                }
            )

    def test_duplicate_step_names_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            StepGraph.model_validate(
                {
                    "name": "g",
                    "steps": [
                        {"kind": "tool_call", "name": "dup", "tool_name": "a____b"},
                        {"kind": "transform", "name": "dup", "op": "passthrough"},
                    ],
                }
            )

    def test_empty_steps_rejected(self):
        with pytest.raises(ValidationError):
            StepGraph(name="g", steps=[])

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            StepGraph.model_validate(
                {
                    "name": "g",
                    "unexpected": True,
                    "steps": [{"kind": "tool_call", "name": "s", "tool_name": "a____b"}],
                }
            )

    def test_round_trips_through_json(self):
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
                "comparison_tolerance": {"numeric_abs_tolerance": 0.5},
            }
        )
        restored = StepGraph.model_validate_json(graph.model_dump_json())
        assert restored == graph
        assert restored.comparison_tolerance.numeric_abs_tolerance == 0.5

    def test_model_backed_steps_and_tool_names_helpers(self):
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {"kind": "tool_call", "name": "s1", "tool_name": "a____b"},
                    {"kind": "decision", "name": "s2", "tool_name": "decision____d"},
                ],
            }
        )
        assert [s.name for s in graph.model_backed_steps()] == ["s2"]
        assert graph.tool_names() == ["a____b", "decision____d"]


# ── Plan-time compilability analysis (E4–E6) ──────────────────────────────────


class TestCompilabilityAnalysis:
    def test_all_deterministic_steps_are_scriptable_and_compilable(self):
        from app.agent_runtime.scripts.compiler import (
            CompilabilityVerdict,
            analyze_compilability,
        )

        analysis = analyze_compilability(
            [
                {"step_type": "tool_invocation", "tool_name": "jira____search"},
                {"step_type": "tool_invocation", "tool_name": "slack____post"},
            ]
        )
        assert analysis.verdict == CompilabilityVerdict.compilable
        assert analysis.eligible
        assert all(mark["scriptable"] for mark in analysis.marks)
        assert not any(mark["model_backed"] for mark in analysis.marks)
        assert [m["step_index"] for m in analysis.marks] == [0, 1]

    def test_each_step_is_marked_scriptable_or_model_backed(self):
        """E4: every plan step carries a scriptable/model-backed mark."""
        from app.agent_runtime.scripts.compiler import analyze_compilability

        analysis = analyze_compilability(
            [{"step_type": "tool_invocation", "tool_name": "a____b"}]
        )
        for mark in analysis.marks:
            assert mark["scriptable"] != mark["model_backed"]

    def test_decision_step_marked_model_backed_not_eligible(self):
        from app.agent_runtime.scripts.compiler import (
            CompilabilityVerdict,
            analyze_compilability,
        )

        analysis = analyze_compilability(
            [
                {"step_type": "tool_invocation", "tool_name": "a____b"},
                {"step_type": "decision", "tool_name": "decision____judge"},
            ]
        )
        assert analysis.verdict == CompilabilityVerdict.model_backed_steps
        assert not analysis.eligible
        assert analysis.marks[1]["model_backed"]
        assert "model-backed" in analysis.reason

    def test_interactive_input_step_is_model_backed(self):
        from app.agent_runtime.scripts.compiler import (
            CompilabilityVerdict,
            analyze_compilability,
        )

        analysis = analyze_compilability(
            [{"step_type": "interactive_input", "tool_name": "form____x"}]
        )
        assert analysis.verdict == CompilabilityVerdict.model_backed_steps
        assert not analysis.eligible

    def test_conversational_agent_never_compiled(self):
        """E6: conversational/interactive agents are never compiled — no
        script produced, regardless of how deterministic the steps look."""
        from app.agent_runtime.scripts.compiler import (
            CompilabilityVerdict,
            analyze_compilability,
        )

        analysis = analyze_compilability(
            [
                {"step_type": "tool_invocation", "tool_name": "a____b"},
                {"step_type": "tool_invocation", "tool_name": "c____d"},
            ],
            agent_traits={"interaction_mode": "conversational"},
        )
        assert analysis.verdict == CompilabilityVerdict.never_compiled
        assert not analysis.eligible
        assert analysis.marks == []  # no script is produced at all
        assert "never compiled" in analysis.reason

    def test_hitl_trait_never_compiled(self):
        from app.agent_runtime.scripts.compiler import (
            CompilabilityVerdict,
            analyze_compilability,
        )

        analysis = analyze_compilability(
            [{"step_type": "tool_invocation", "tool_name": "a____b"}],
            agent_traits={"is_interactive": True},
        )
        assert analysis.verdict == CompilabilityVerdict.never_compiled
        assert not analysis.eligible

    def test_non_conversational_agent_with_deterministic_steps_is_eligible(self):
        from app.agent_runtime.scripts.compiler import analyze_compilability

        analysis = analyze_compilability(
            [{"step_type": "tool_invocation", "tool_name": "a____b"}],
            agent_traits={"interaction_mode": "task"},
        )
        assert analysis.eligible

    def test_empty_plan_defaults_to_compilable(self):
        from app.agent_runtime.scripts.compiler import analyze_compilability

        analysis = analyze_compilability([])
        assert analysis.eligible
        assert analysis.marks == []
