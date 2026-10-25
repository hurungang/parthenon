"""Script Compiler (Agent Runtime).

Converts an implementation plan and/or a recorded tool-call sequence from a
successful LLM run into a candidate declarative step graph (C1, C2).

Produces candidates only — never promotes and never executes. Candidate
submission to the Control Center registry happens via the internal API
(``ScriptRegistryClient.submit_candidate``), never via the database.
"""
from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from opentelemetry import trace

from app.agent_runtime.scripts.schemas import (
    ComparisonTolerance,
    DecisionStep,
    OutputStep,
    ScriptSegmentStep,
    SemanticBridgeStep,
    StepGraph,
    ToolCallStep,
    TransformOp,
    TransformStep,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Template reference form: {{step_name.field.path}} or {{step_name}}
_TEMPLATE_REF = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")

# Decision tool namespace prefix (mirrors CC System One tool naming)
DECISION_TOOL_PREFIX = "decision____"

# Semantic-bridge tool namespace prefix (virtual CC one-shot LLM completion;
# same virtual-tool pattern as ``decision____`` — routed CH → CC). Only used
# for model-AUTHORED bridge steps; no step is ever auto-appended anymore.
SEMANTIC_TOOL_PREFIX = "semantic____"


class CompilationError(ValueError):
    """Raised when a plan/tool-call sequence cannot be compiled/validated."""


# ── Plan-time compilability analysis (E4–E6) ─────────────────────────────────


class CompilabilityVerdict(str, Enum):
    """Verdict of plan-time compilability analysis."""

    compilable = "compilable"                      # every step scriptable
    model_backed_steps = "model_backed_steps"      # contains model-backed steps
    never_compiled = "never_compiled"              # conversational/interactive (E6)


# Agent-type traits that mark a workflow as conversational/interactive —
# such agents are never compiled (E6). These mirror characteristics already
# available to Agent Runtime about the agent type.
_CONVERSATIONAL_TRAITS = {"conversational", "interactive", "hitl"}
_MODEL_BACKED_STEP_TYPES = {"decision", "semantic_bridge", "interactive_input"}


@dataclass
class CompilabilityAnalysis:
    """Plan-time compilability marks fed to eligibility (E4, E5)."""

    verdict: CompilabilityVerdict
    eligible: bool
    reason: str
    marks: list[dict[str, Any]] = field(default_factory=list)


def analyze_compilability(
    plan_steps: list[dict[str, Any]],
    *,
    agent_traits: dict[str, Any] | None = None,
) -> CompilabilityAnalysis:
    """Classify each plan step as scriptable vs model-backed (E4).

    A workflow is compilation-eligible only when every step is scriptable
    (deterministic MCP tool calls + local data processing). Conversational/
    interactive agent types are never compiled (E6).
    """
    traits = agent_traits or {}
    interaction_mode = str(
        traits.get("interaction_mode") or traits.get("input_type") or ""
    ).lower()
    is_conversational = bool(
        traits.get("is_conversational")
        or traits.get("is_interactive")
        or interaction_mode in _CONVERSATIONAL_TRAITS
    )

    span = trace.get_current_span()

    def _finish(verdict: CompilabilityVerdict, eligible: bool, reason: str,
                marks: list[dict[str, Any]]) -> CompilabilityAnalysis:
        if span is not None:
            span.set_attribute("script.compilability_verdict", verdict.value)
            span.set_attribute("script.compilability_eligible", eligible)
        return CompilabilityAnalysis(
            verdict=verdict, eligible=eligible, reason=reason, marks=marks
        )

    if is_conversational:
        return _finish(
            CompilabilityVerdict.never_compiled,
            False,
            "Conversational/interactive agent types are never compiled (E6)",
            [],
        )

    marks: list[dict[str, Any]] = []
    for index, plan_step in enumerate(plan_steps or []):
        step_type = str(plan_step.get("step_type") or "tool_invocation").lower()
        tool_name = plan_step.get("tool_name")
        model_backed = step_type in _MODEL_BACKED_STEP_TYPES or bool(
            tool_name
            and (
                tool_name.startswith(DECISION_TOOL_PREFIX)
                or tool_name.startswith(SEMANTIC_TOOL_PREFIX)
            )
        )
        marks.append(
            {
                "step_index": index,
                "scriptable": not model_backed,
                "model_backed": model_backed,
                "step_type": step_type,
            }
        )

    if any(mark["model_backed"] for mark in marks):
        return _finish(
            CompilabilityVerdict.model_backed_steps,
            False,
            "Plan contains model-backed steps (semantic bridging / System One "
            "judgment / interactive input) — not fully compilable (E5)",
            marks,
        )

    return _finish(
        CompilabilityVerdict.compilable,
        True,
        "All plan steps are deterministic MCP tool calls / local processing",
        marks,
    )


def plan_output_decision(
    plan_steps: list[dict[str, Any]] | None,
) -> tuple[str | None, str | None]:
    """Extract the plan's final-output decision (Software 3.0).

    Returns ``(output_mode, output_template)`` from the last step that carries
    an explicit ``output_mode`` (normally the final plan step). Returns
    ``(None, None)`` when the plan says nothing — the compiler then applies
    its typed-output-schema heuristic.
    """
    for step in reversed(plan_steps or []):
        if isinstance(step, dict) and step.get("output_mode"):
            return step.get("output_mode"), step.get("output_template")
    return None, None


def _sanitize_step_name(name: str) -> str:
    """Canonical step-name sanitizer (shared with autocompile's requirement
    renderer, which must compute the same ``step{N}_{sanitized}`` keys the
    compiler produces)."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
    return sanitized[:80] or "step"


class ScriptCompiler:
    """Compiles recorded LLM executions into candidate step graphs."""

    def _append_final_output(
        self,
        steps: list[Any],
        output_keys: list[str],
        output_mode: str | None = None,
        output_template: str | None = None,
        typed_output_schema: dict[str, Any] | None = None,
    ) -> list[str]:
        """Append the final output step (deterministic projection only).

        Phase 2 (model-authored composition): the compiler no longer appends
        any hardcoded ``semantic____render`` step — workflows contain a
        summary/render step only when the model's composition explicitly
        authors one. ``llm_render`` output_mode with no authored render step
        degrades to a plain deterministic projection of the step outputs.
        """
        mode = (output_mode or "").strip().lower() or None
        if mode not in (None, "deterministic", "llm_render"):
            mode = None

        select_keys = list(output_keys)
        if mode == "deterministic" and output_template:
            # Deterministic template render of the prior steps' data.
            last_step_name = output_keys[-1]
            steps.append(
                TransformStep(
                    name="render_output",
                    op=TransformOp.template,
                    input_key=last_step_name,
                    template=output_template,
                    output_key="render_output",
                )
            )
            # The rendered document IS the result — raw step outputs
            # stay internal to the run.
            select_keys = ["render_output"]

        steps.append(
            OutputStep(
                name="final_output",
                output_key="result",
                select_keys=select_keys,
            )
        )
        return select_keys

    def _model_backed_plan_step(
        self, step_type: str, tool_name: str | None, scriptable: bool = True
    ) -> bool:
        """Whether a plan step must become a model-backed graph step.

        The plan's own ``scriptable: False`` mark wins; recognized model-backed
        step types and decision/semantic virtual-tool prefixes also qualify.
        """
        if scriptable is False:
            return True
        return (
            step_type in _MODEL_BACKED_STEP_TYPES
            or bool(
                tool_name
                and (
                    tool_name.startswith(DECISION_TOOL_PREFIX)
                    or tool_name.startswith(SEMANTIC_TOOL_PREFIX)
                )
            )
        )

    def compile_from_tool_sequence(
        self,
        *,
        name: str,
        tool_calls: list[dict[str, Any]],
        comparison_tolerance: ComparisonTolerance | None = None,
        final_output_keys: list[str] | None = None,
        output_mode: str | None = None,
        output_template: str | None = None,
    ) -> StepGraph:
        """Compile a recorded tool-call sequence into a step graph (C1).

        Each recorded call is expected as::

            {"tool_name": "...", "tool_input": {...}, "tool_output": {...}}

        Sequential data-flow is wired by templating: arguments that exactly
        match a prior step's output shape become ``{{step}}`` references.
        """
        with tracer.start_as_current_span("script.compile") as span:
            span.set_attribute("script.name", name)
            span.set_attribute("script.recorded_calls", len(tool_calls))
            if not tool_calls:
                raise CompilationError("Cannot compile an empty tool-call sequence")

            steps: list[Any] = []
            output_keys: list[str] = []
            for index, call in enumerate(tool_calls):
                tool_name = call.get("tool_name")
                if not tool_name:
                    raise CompilationError(
                        f"Recorded call at index {index} has no tool_name"
                    )
                step_name = f"step{index + 1}_{self._sanitize(tool_name)}"
                arguments = dict(call.get("tool_input") or {})
                templates = self._derive_templates(
                    arguments, output_keys
                )
                if tool_name.startswith(DECISION_TOOL_PREFIX):
                    steps.append(
                        DecisionStep(
                            name=step_name,
                            tool_name=tool_name,
                            arguments=arguments,
                            argument_templates=templates,
                            output_key=step_name,
                        )
                    )
                else:
                    expected_keys = self._top_level_keys(call.get("tool_output"))
                    steps.append(
                        ToolCallStep(
                            name=step_name,
                            tool_name=tool_name,
                            arguments=arguments,
                            argument_templates=templates,
                            expected_output_keys=expected_keys,
                            output_key=step_name,
                        )
                    )
                output_keys.append(step_name)

            self._append_final_output(
                steps,
                output_keys,
                output_mode=output_mode,
                output_template=output_template,
            )
            select_keys = steps[-1].select_keys
            graph = StepGraph(
                name=name,
                steps=steps,
                comparison_tolerance=comparison_tolerance or ComparisonTolerance(),
            )
            self._assert_no_secrets(graph)
            span.set_attribute("script.steps", len(graph.steps))
            logger.info(
                "Compiled candidate step graph '%s' with %d steps",
                name, len(graph.steps),
            )
            return graph

    def compile_from_plan(
        self,
        *,
        name: str,
        plan_steps: list[dict[str, Any]],
        comparison_tolerance: ComparisonTolerance | None = None,
        typed_output_schema: dict[str, Any] | None = None,
    ) -> StepGraph:
        """Compile an implementation plan (ordered structured steps) into a graph (C2).

        Plan step fields: ``step_type`` (``tool_invocation`` | ``skill_invocation`` |
        ``decision`` | ``semantic_bridge`` | ``interactive_input``), ``tool_name``,
        ``arguments``, ``description``, plus the plan LLM's scriptability marks:
        ``scriptable`` (default true), and on the final step ``output_mode``
        (``deterministic`` | ``llm_render``) and optional ``output_template``.

        Steps marked ``scriptable: false`` (or recognized model-backed types)
        become model-backed graph steps; everything else becomes tool steps —
        so the graph can be tool-segment / LLM-step / tool-segment.
        """
        with tracer.start_as_current_span("script.compile_plan") as span:
            span.set_attribute("script.name", name)
            if not plan_steps:
                raise CompilationError("Cannot compile an empty plan")

            steps: list[Any] = []
            output_keys: list[str] = []
            for index, plan_step in enumerate(plan_steps):
                step_type = (plan_step.get("step_type") or "tool_invocation").lower()
                tool_name = plan_step.get("tool_name")
                step_name = (
                    f"step{index + 1}_{self._sanitize(tool_name or step_type)}"
                )
                arguments = dict(plan_step.get("arguments") or {})
                templates = self._derive_templates(arguments, output_keys)
                scriptable = plan_step.get("scriptable", True)
                python_source = plan_step.get("python_source")
                model_backed = self._model_backed_plan_step(
                    step_type, tool_name, scriptable
                )
                if step_type == "decision" or (
                    tool_name and tool_name.startswith(DECISION_TOOL_PREFIX)
                ):
                    steps.append(
                        DecisionStep(
                            name=step_name,
                            tool_name=tool_name or "",
                            arguments=arguments,
                            argument_templates=templates,
                            output_key=step_name,
                        )
                    )
                elif python_source:
                    # Model-authored sandboxed Python segment (N3) — validated
                    # at normalization time (validator = compiler); executed in
                    # the sandbox by the runner with the injected MCP-only
                    # client. Unsafe source fails compilation (stays draft).
                    python_source = ScriptValidator().validate_or_raise(
                        python_source
                    )
                    steps.append(
                        ScriptSegmentStep(
                            name=step_name,
                            python_source=python_source,
                            cpu_limit_seconds=plan_step.get("cpu_limit_seconds"),
                            memory_limit_mb=plan_step.get("memory_limit_mb"),
                            wall_time_limit_seconds=plan_step.get(
                                "wall_time_limit_seconds"
                            ),
                            output_key=step_name,
                        )
                    )
                elif model_backed and step_type == "semantic_bridge":
                    steps.append(
                        SemanticBridgeStep(
                            name=step_name,
                            tool_name=tool_name
                            or f"{SEMANTIC_TOOL_PREFIX}{self._sanitize(step_type)}",
                            prompt_template=plan_step.get("prompt_template")
                            or plan_step.get("description"),
                            input_key=output_keys[-1] if output_keys else None,
                            output_key=step_name,
                        )
                    )
                elif model_backed:
                    # interactive_input / scriptable:false generic step —
                    # routed through the semantic-bridge virtual tool.
                    steps.append(
                        SemanticBridgeStep(
                            name=step_name,
                            tool_name=tool_name
                            or f"{SEMANTIC_TOOL_PREFIX}{self._sanitize(step_type)}",
                            prompt_template=plan_step.get("prompt_template")
                            or plan_step.get("description"),
                            input_key=output_keys[-1] if output_keys else None,
                            output_key=step_name,
                        )
                    )
                elif step_type == "skill_invocation" and not tool_name:
                    raise CompilationError(
                        f"Plan step {index} (skill_invocation) lacks a resolvable tool_name"
                    )
                else:
                    if not tool_name:
                        raise CompilationError(
                            f"Plan step {index} has no tool_name"
                        )
                    steps.append(
                        ToolCallStep(
                            name=step_name,
                            tool_name=tool_name,
                            arguments=arguments,
                            argument_templates=templates,
                            output_key=step_name,
                        )
                    )
                output_keys.append(step_name)

            # Final output decision: the plan's last step may carry
            # output_mode / output_template; otherwise fall back heuristically
            # (typed output schema → deterministic, else LLM render).
            final_plan_step = plan_steps[-1] or {}
            self._append_final_output(
                steps,
                output_keys,
                output_mode=final_plan_step.get("output_mode"),
                output_template=final_plan_step.get("output_template"),
                typed_output_schema=typed_output_schema,
            )
            graph = StepGraph(
                name=name,
                steps=steps,
                comparison_tolerance=comparison_tolerance or ComparisonTolerance(),
            )
            self._assert_no_secrets(graph)
            span.set_attribute("script.steps", len(graph.steps))
            return graph

    # ── Internals ─────────────────────────────────────────────────────────

    def _derive_templates(
        self, arguments: dict[str, Any], prior_output_keys: list[str]
    ) -> dict[str, str]:
        """Turn argument values that reference prior steps into templates.

        A string argument equal to a prior step's output key becomes
        ``{{key}}``. Nested dict values are matched on their string leaves.
        """
        templates: dict[str, str] = {}
        for key, value in arguments.items():
            if isinstance(value, str) and value in prior_output_keys:
                templates[key] = f"{{{{{value}}}}}"
        return templates

    def _top_level_keys(self, output: Any) -> list[str]:
        if isinstance(output, dict):
            return [str(k) for k in list(output.keys())[:20]]
        return []

    def _sanitize(self, name: str) -> str:
        return _sanitize_step_name(name)

    def _assert_no_secrets(self, graph: StepGraph) -> None:
        """Defense-in-depth: candidate graphs must carry no credential-shaped fields (SEC3)."""
        forbidden = ("api_key", "token", "secret", "password", "authorization", "credential")
        blob = graph.model_dump_json().lower()
        for marker in forbidden:
            if f'"{marker}"' in blob:
                raise CompilationError(
                    f"Compiled candidate contains forbidden credential-shaped field '{marker}' (SEC3)"
                )


# ── Validator/Normalizer of model-authored Python (Phase 2, N3) ──────────────

# Credential-shaped string patterns that must never appear in script source.
_SECRET_SHAPE_PATTERNS = (
    "api_key", "apikey", "secret", "password", "authorization",
    "credential", "bearer ", "sk-", "x-api-key", "private_key",
    "connection_string", "set_cookie", "access_token",
)


class ValidationStatus(str, Enum):
    """Mirror of CC ``SandboxValidationStatus`` for validator outcomes."""

    pending = "pending"
    passed = "passed"
    failed = "failed"


@dataclass
class SourceValidationResult:
    """Outcome of validating one model-authored Python script source."""

    status: ValidationStatus
    reason: str | None = None
    # Normalized (validated) source — carried for candidate submission.
    normalized_source: str | None = None


class ScriptValidator:
    """Validates/normalizes model-authored Python for sandboxed execution.

    Layers (defense in depth):
    1. RestrictedPython compile check (``sandbox.compile_sandbox``).
    2. AST safety scan — no import statements, no I/O calls
       (``open``/``eval``/``exec``/``compile``/``__import__``),
       no forbidden attribute access (dunder traversal).
    3. Secret-shape guard — credential-shaped strings rejected (SEC3).
    4. Resource-cap annotations — per-segment caps captured for execution.

    On failure the candidate stays in draft with a recorded
    ``sandbox_validation_reason`` (never promoted, never executed).
    """

    _FORBIDDEN_CALLS = frozenset({
        "open", "exec", "eval", "compile", "__import__", "globals",
        "locals", "vars", "dir", "breakpoint", "input",
    })
    _FORBIDDEN_IMPORT_ROOTS = frozenset({
        "os", "sys", "subprocess", "socket", "io", "ctypes", "importlib",
        "multiprocessing", "threading", "signal", "resource", "requests",
        "httpx", "urllib", "http", "asyncio", "pickle", "sqlite3", "ssl",
    })

    def validate(
        self,
        source: str,
        *,
        cpu_limit_seconds: int | None = None,
        memory_limit_mb: int | None = None,
        wall_time_limit_seconds: int | None = None,
    ) -> SourceValidationResult:
        """Validate model-authored source; returns a typed outcome."""
        # 1. Restricted compile check.
        try:
            from app.agent_runtime.scripts.sandbox import (
                SandboxCompileError,
                SandboxViolationError,
                compile_sandbox,
            )

            compile_sandbox(source)
        except SandboxCompileError as exc:
            return SourceValidationResult(
                ValidationStatus.failed, str(exc), None
            )
        except SandboxViolationError as exc:  # pragma: no cover — compile-time
            return SourceValidationResult(ValidationStatus.failed, str(exc), None)

        # 2. AST safety scan.


        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover — compile check first
            return SourceValidationResult(
                ValidationStatus.failed,
                f"Script syntax error: {exc.msg} (line {exc.lineno})",
                None,
            )
        violation = self._scan_ast(tree)
        if violation:
            return SourceValidationResult(ValidationStatus.failed, violation, None)

        # 3. Secret-shape guard (SEC3).
        lowered = source.lower()
        for marker in _SECRET_SHAPE_PATTERNS:
            if marker in lowered:
                return SourceValidationResult(
                    ValidationStatus.failed,
                    "Script source contains a credential-shaped string "
                    f"'{marker}' — scripts never hold secrets (SEC3)",
                    None,
                )

        return SourceValidationResult(
            ValidationStatus.passed,
            None,
            source,
        )

    def validate_or_raise(self, source: str, **caps: Any) -> str:
        """Validate and return the normalized source, or raise CompilationError."""
        result = self.validate(source, **caps)
        if result.status is not ValidationStatus.passed:
            raise CompilationError(
                result.reason or "Script failed sandbox validation"
            )
        assert result.normalized_source is not None
        return result.normalized_source

    def _scan_ast(self, tree: ast.AST) -> str | None:
        """Return a one-line violation reason, or ``None`` when clean."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in self._FORBIDDEN_IMPORT_ROOTS:
                        return (
                            f"import of '{alias.name}' is not allowed — scripts "
                            "have no I/O; use the injected tools facade"
                        )
                    return (
                        "import statements are not allowed — safe modules "
                        "(json, math, statistics) are pre-bound"
                    )
            if isinstance(node, ast.ImportFrom):
                return (
                    "import statements are not allowed — safe modules "
                    "(json, math, statistics) are pre-bound"
                )
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if isinstance(name, str) and name in self._FORBIDDEN_CALLS:
                    return f"call to '{name}()' is not allowed — no I/O in scripts"
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                return (
                    f"access to attribute '{node.attr}' is not allowed — "
                    "no dunder traversal in sandboxed scripts"
                )
        return None
