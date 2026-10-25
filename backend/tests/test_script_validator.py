"""Unit tests for the compiler-as-validator (Phase 5.2, N3).

Covers:
- Model-authored script validation (valid → normalized; unsafe → failed w/ reason)
- AST safety scan: imports, I/O calls, dunder traversal
- Secret-shape guard (SEC3)
- Plan emission with python_source segments → ScriptSegmentStep normalization
- Render-append removal regressions (no auto-appended semantic____render)
- Composition schema parsing (WorkflowComposition, CompositionSegment)
"""
from __future__ import annotations

import pytest

from app.agent_runtime.scripts.compiler import (
    CompilationError,
    ScriptCompiler,
    ScriptValidator,
    ValidationStatus,
)
from app.agent_runtime.scripts.schemas import (
    CompositionSegment,
    ScriptSegmentStep,
    SemanticBridgeStep,
    StepGraph,
    WorkflowComposition,
)

GOOD_SOURCE = """
def run(context, tools):
    items = context.get('items') or []
    return {'count': len(items)}
"""


@pytest.fixture()
def validator() -> ScriptValidator:
    return ScriptValidator()


@pytest.fixture()
def compiler() -> ScriptCompiler:
    return ScriptCompiler()


class TestValidator:
    def test_valid_source_passes_and_normalizes(self, validator):
        result = validator.validate(GOOD_SOURCE)
        assert result.status is ValidationStatus.passed
        assert result.normalized_source == GOOD_SOURCE
        assert result.reason is None

    def test_syntax_failure_fails_with_reason(self, validator):
        result = validator.validate("def run(")
        assert result.status is ValidationStatus.failed
        assert result.reason and "SyntaxError" in result.reason

    def test_import_statement_fails(self, validator):
        result = validator.validate(
            "import os\n" + GOOD_SOURCE
        )
        assert result.status is ValidationStatus.failed
        assert result.reason and "import" in result.reason.lower()

    def test_io_call_fails(self, validator):
        result = validator.validate(
            "def run(context, tools):\n    f = open('/etc/passwd')\n    return {}"
        )
        assert result.status is ValidationStatus.failed
        assert result.reason and "open" in result.reason

    def test_dunder_traversal_fails(self, validator):
        result = validator.validate(
            "def run(context, tools):\n    return {'c': tools.__class__}"
        )
        assert result.status is ValidationStatus.failed

    def test_empty_source_fails(self, validator):
        result = validator.validate("   ")
        assert result.status is ValidationStatus.failed

    def test_validate_or_raise_returns_normalized(self, validator):
        assert validator.validate_or_raise(GOOD_SOURCE) == GOOD_SOURCE

    def test_validate_or_raise_raises_compilation_error(self, validator):
        with pytest.raises(CompilationError):
            validator.validate_or_raise("import subprocess")


class TestSecretShapeGuard:
    @pytest.mark.parametrize(
        "source",
        [
            "def run(context, tools):\n    return {'k': 'api_key=sk-123'}",
            "def run(context, tools):\n    return {'h': 'Authorization: Bearer x'}",
            "def run(context, tools):\n    return {'p': context.get('password')}",
        ],
    )
    def test_credential_shaped_strings_rejected(self, validator, source):
        result = validator.validate(source)
        assert result.status is ValidationStatus.failed
        assert result.reason and "SEC3" in result.reason

    def test_clean_source_with_tools_use_passes(self, validator):
        source = """
def run(context, tools):
    result = tools.call('crm____getContact', {'id': context['id']})
    return {'name': result.get('name')}
"""
        assert validator.validate(source).status is ValidationStatus.passed


class TestPlanEmissionParsing:
    def test_plan_python_source_becomes_script_segment(self, compiler):
        plan = [
            {"step_type": "tool_invocation", "tool_name": "a____fetch"},
            {
                "step_type": "tool_invocation",
                "tool_name": "a____process",
                "python_source": GOOD_SOURCE,
            },
        ]
        graph = compiler.compile_from_plan(name="composed", plan_steps=plan)
        segment = graph.steps[1]
        assert isinstance(segment, ScriptSegmentStep)
        assert segment.python_source == GOOD_SOURCE

    def test_unsafe_plan_source_fails_compilation(self, compiler):
        plan = [
            {
                "step_type": "tool_invocation",
                "tool_name": "a____process",
                "python_source": "import os\n" + GOOD_SOURCE,
            },
        ]
        with pytest.raises(CompilationError, match="import"):
            compiler.compile_from_plan(name="unsafe", plan_steps=plan)

    def test_no_render_step_auto_appended_regression(self, compiler):
        """Regression: the hardcoded semantic____render append is gone."""
        plan = [
            {"step_type": "tool_invocation", "tool_name": "a____fetch",
             "output_mode": "llm_render"},
        ]
        graph = compiler.compile_from_plan(name="regress", plan_steps=plan)
        assert not [s for s in graph.steps if isinstance(s, SemanticBridgeStep)]
        assert "render_output" not in [s.name for s in graph.steps]

    def test_composition_schema_round_trip(self):
        composition = WorkflowComposition(
            name="composed-flow",
            segments=[
                CompositionSegment(
                    name="fetch", order=1,
                    step_type="tool_invocation", tool_name="a____fetch",
                ),
                CompositionSegment(
                    name="derive", order=2,
                    step_type="script_segment",
                    python_source=GOOD_SOURCE,
                ),
                CompositionSegment(
                    name="judge", order=3, scriptable=False,
                    step_type="decision", tool_name="decision____gate",
                ),
            ],
        )
        blob = composition.model_dump_json()
        parsed = WorkflowComposition.model_validate_json(blob)
        assert parsed.segments[1].python_source == GOOD_SOURCE
        assert parsed.segments[2].scriptable is False
