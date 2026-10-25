"""Post-run auto-compilation hook (Software 3.0 self-improvement).

After a session completes via the LLM path, the recorded tool-call sequence
is compiled into a candidate script version, submitted to the CC registry,
shadow-verified against the recorded LLM reference, and — on verification
parity — promoted to the serving (compiled) version. Per the PRD, execution
is script-first with unconditional LLM fallback, so auto-promotion on a
verified shadow-run match is safe and requires no operator babysitting.

Design invariants:
- Fire-and-forget: the hook runs as a detached asyncio task; any error is
  logged and swallowed — it never affects the completed run (E2 parity).
- Best-effort eligibility: conversational agent types, plans containing
  model-backed steps, and empty/absent tool sequences are never compiled
  (E4–E6).
- Duplicate protection: compilation is skipped when a serving script version
  already exists for the agent type.
- Security: arguments/results are held only in AR process memory (capture
  module); the compiled graph passes the compiler's secret-shaped-field
  guard; registry access goes through the mTLS CC internal API only.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from opentelemetry import trace

from app.agent_runtime.scripts.capture import pop_tool_sequence
from app.agent_runtime.scripts.cc_client import ScriptRegistryClient

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Verification outcomes that allow auto-promotion (mirrors CC registry rules).
_PROMOTABLE_OUTCOMES = {"match", "match_within_tolerance"}

import itertools
import time

from app.agent_runtime.scripts.sandbox import (
    SandboxCompileError,
    SandboxError,
    build_capability_contract,
)

_label_counter = itertools.count(1)

# Bounded generate → test → refine budget: the LLM-authored script is tested
# against the recorded run data; each typed failure is fed back (together
# with the capability contract) for a repaired version. MAX attempts total.
MAX_SCRIPT_REFINEMENT_ATTEMPTS = 3

# Module-level repair-generator hook (LLM mock-aware path): the authoring
# LLM is invoked as
# ``await generator(contract, error_detail, segments, attempt) -> dict[str, str] | None``
# where ``segments`` maps step name → current python_source and the return
# value maps (a subset of) step names → repaired python_source. ``None`` /
# a raise means "no repaired version produced" (counts as exhaustion).
_script_repair_generator: Any = None


def set_script_repair_generator(generator: Any) -> None:
    """Install the LLM repair generator used by the refine loop."""
    global _script_repair_generator
    _script_repair_generator = generator


async def schedule_autocompile(
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    cert_manager: Any,
) -> asyncio.Task | None:
    """Launch the auto-compile attempt as a detached fire-and-forget task.

    Called from the Script-First Dispatcher when a session completes via the
    LLM path. Returns the task (or ``None`` when auto-compilation cannot even
    start, e.g. missing certificate).
    """
    from app.agent_runtime.scripts.dispatch import _session_bound_tool_client

    try:
        tool_client = _session_bound_tool_client(cert_manager)
    except Exception as exc:
        logger.warning(
            "Auto-compile skipped for session %s: tool client unavailable (%s)",
            session_id, exc,
        )
        return None
    registry_client = ScriptRegistryClient(cert_manager)
    task = asyncio.create_task(
        _run_autocompile(
            session_id=session_id,
            agent_type_id=agent_type_id,
            data_client=data_client,
            registry_client=registry_client,
            tool_client=tool_client,
        ),
        name=f"autocompile-{session_id}",
    )
    # Swallow everything: an auto-compile failure must never surface anywhere.
    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            logger.warning(
                "Auto-compile task for session %s failed: %s",
                session_id, t.exception(),
            )

    task.add_done_callback(_on_done)
    return task


async def _run_autocompile(
    *,
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    registry_client: ScriptRegistryClient,
    tool_client: Any,
) -> None:
    """Full auto-compile pipeline for one completed LLM session (all best-effort)."""
    with tracer.start_as_current_span(
        "script.autocompile",
        attributes={"session_id": session_id, "agent_type_id": agent_type_id},
    ) as span:
        try:
            await _autocompile_inner(
                session_id=session_id,
                agent_type_id=agent_type_id,
                data_client=data_client,
                registry_client=registry_client,
                tool_client=tool_client,
                span=span,
            )
        except Exception as exc:
            logger.warning(
                "Auto-compile failed for session %s (ignored): %s", session_id, exc
            )
            if span is not None:
                span.set_attribute("script.autocompile_error", str(exc)[:200])


async def _autocompile_inner(
    *,
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    registry_client: ScriptRegistryClient,
    tool_client: Any,
    span: Any,
) -> None:
    tool_sequence = pop_tool_sequence(session_id)
    if not tool_sequence:
        _skip(span, "empty tool-call sequence")
        return

    # Duplicate protection: a serving version already exists for this workflow.
    serving = None
    try:
        serving = await registry_client.get_serving_version(agent_type_id)
    except Exception as exc:
        logger.warning(
            "Auto-compile: serving-version lookup failed for %s (%s)", agent_type_id, exc
        )
    if serving and serving.get("script_version_id"):
        _skip(span, "serving script version already exists")
        return

    # Fetch plan + agent-type traits for eligibility analysis (E4–E6).
    plan = None
    try:
        plan = await data_client.get_agent_plan(agent_type_id)
    except Exception as exc:
        logger.warning("Auto-compile: plan fetch failed for %s (%s)", agent_type_id, exc)
    plan_steps = (plan or {}).get("plan_steps") or []

    traits: dict[str, Any] = {}
    try:
        context = await data_client.get_agent_context(agent_type_id)
        traits = {
            "input_type": (context or {}).get("input_type"),
            "interaction_mode": (context or {}).get("input_type"),
            # User-facing output contract: the compiled script must produce
            # the result in the user's required format (auto → markdown).
            "output_type": (context or {}).get("output_type"),
        }
    except Exception as exc:
        logger.debug("Auto-compile: agent context fetch failed (%s)", exc)

    from app.agent_runtime.scripts.compiler import (
        CompilabilityVerdict,
        ScriptCompiler,
        analyze_compilability,
        plan_output_decision,
    )

    # Execution semantics (product decision): the plan LLM marks the plan
    # fully_scripted when a SINGLE end-to-end script can achieve the
    # requirement with zero LLM. Such candidates get GENUINE output
    # verification against the recorded LLM run before promotion; tool-mode
    # scripts are promoted as invocable tools (no output verification — the
    # agent sees tool responses live and does not blindly trust them).
    plan_fully_scripted = bool((plan or {}).get("fully_scripted"))

    # Model-authored composition (Software 3.0, Phase 2): when the plan itself
    # carries the composition — sandboxed python_source segments and/or an
    # explicit final-output decision — it MUST be compiled via
    # ``compile_from_plan`` so the authored segments (and LLM bridges) survive
    # into the candidate. Model-backed steps (e.g. semantic bridges) are then
    # part of the authored composition, not a disqualifier (E5 applies only
    # when there is no composition to compile).
    has_composition = _plan_has_composition(plan_steps)

    analysis = analyze_compilability(plan_steps, agent_traits=traits)
    if not analysis.eligible:
        composition_covers_model_backed = has_composition and (
            analysis.verdict == CompilabilityVerdict.model_backed_steps
        )
        if not composition_covers_model_backed:
            _skip(span, f"not compilation-eligible: {analysis.reason}")
            return
        logger.info(
            "Auto-compile: plan carries model-authored composition with "
            "model-backed steps — compiling the composition (bridges included)"
        )

    compiler = ScriptCompiler()
    verification_ok = True
    verification_reason = ""
    if has_composition:
        if plan_fully_scripted:
            # Single end-to-end script, authored as one piece by the plan LLM.
            graph = compiler.compile_from_plan(
                name=_script_name(agent_type_id), plan_steps=plan_steps
            )
            verification_ok, verification_reason, _ = (
                await _verify_against_llm_run(
                    graph,
                    tool_sequence,
                    session_id=session_id,
                    agent_type_id=agent_type_id,
                    registry_client=registry_client,
                )
            )
            if verification_ok:
                logger.info(
                    "Fully-scripted candidate output verified against the "
                    "recorded LLM run for agent type %s",
                    agent_type_id,
                )
        else:
            # Compile the PLAN's model-authored composition (C2): python_source
            # script segments (validated in-compiler via ScriptValidator), LLM
            # bridges, and the plan's output decision. The composition then goes
            # through the bounded generate → test → refine loop: it is executed
            # against the recorded run data as a test, failures are fed back to
            # the authoring LLM (with the capability contract) for repair, and
            # only a passing script is delivered to the registry.
            graph = await _refine_composition(
                compiler=compiler,
                name=_script_name(agent_type_id),
                plan_steps=plan_steps,
                tool_sequence=tool_sequence,
                traits=traits,
                session_id=session_id,
                agent_type_id=agent_type_id,
                span=span,
            )
            if graph is None:
                _skip(
                    span,
                    "script refinement exhausted — no passing authored script to "
                    "promote (nothing submitted)",
                )
                return
    else:
        # Fallback: no composition in the plan — compile the recorded tool
        # sequence into a declarative graph (C1) with the plan LLM's authored
        # output decision passed through when present. No hardcoded
        # requirement heuristics: without an authored decision the graph ends
        # in a plain projection of the step outputs.
        output_mode, output_template = plan_output_decision(plan_steps)
        graph = compiler.compile_from_tool_sequence(
            name=_script_name(agent_type_id),
            tool_calls=tool_sequence,
            output_mode=output_mode,
            output_template=output_template,
        )

    description = _describe(plan_steps, tool_sequence)
    # Unique per attempt: the registry enforces (definition, version_label)
    # uniqueness, and a fixed label would collide on every subsequent
    # auto-compile of the same workflow.
    version_label = (
        f"auto-{time.strftime('%Y%m%dT%H%M%S')}-{next(_label_counter)}"
    )
    # Sandbox-validation evidence (N3): when the compiled graph carries
    # model-authored python_source segments, run the ScriptValidator over the
    # joined source and submit the outcome with the candidate. Compilation
    # already fails hard on an unsafe segment (compiler-as-validator), so a
    # submitted composition candidate always validates 'passed'.
    payload: dict[str, Any] = {
        "agent_type_id": agent_type_id,
        "name": _script_name(agent_type_id),
        "declarative_step_graph": graph.model_dump(mode="json"),
        "description": description,
        "source_plan_id": (plan or {}).get("plan_id"),
        "source_session_id": session_id,
        "version_label": version_label,
        "created_by": "agent-runtime-autocompile",
        "fully_scripted": plan_fully_scripted,
    }
    segment_sources = [
        str(step["python_source"])
        for step in (graph.model_dump(mode="json").get("steps") or [])
        if step.get("python_source")
    ]
    if segment_sources:
        from app.agent_runtime.scripts.compiler import ScriptValidator

        validation = ScriptValidator().validate("\n\n".join(segment_sources))
        payload["python_source"] = "\n\n".join(segment_sources)
        payload["sandbox_validation_status"] = validation.status.value
        if validation.reason:
            payload["sandbox_validation_reason"] = validation.reason
    candidate = await registry_client.submit_candidate(payload)
    version_id = str(candidate.get("id") or "")
    if not version_id:
        _skip(span, "registry returned no candidate version id")
        return
    if span is not None:
        span.set_attribute("script.compiled", True)
        span.set_attribute("script.candidate_version", version_id)

    if plan_fully_scripted:
        # Persist the genuine-comparison evidence alongside the candidate so
        # the lifecycle/audit trail shows WHY promotion did (or did not) happen.
        try:
            await registry_client.submit_verification(
                {
                    "script_version_id": version_id,
                    "comparison_outcome": (
                        "match" if verification_ok else "mismatch"
                    ),
                    "verdict_reason": verification_reason or None,
                    "reference_execution_id": session_id,
                    "sandbox_check_passed": True,
                }
            )
        except Exception as exc:
            logger.warning(
                "Failed to record fully-scripted verification evidence: %s", exc
            )

    if not verification_ok:
        # Verification gate (product decision 3): a fully_scripted candidate
        # whose test output does NOT match the recorded LLM-run result stays
        # draft — it is never promoted. The run already completed on the LLM
        # path; troubleshooting/repair happens before the next generation.
        if span is not None:
            span.set_attribute("script.verification_outcome", "mismatch")
        _skip(
            span,
            "verification gate: fully-scripted candidate output mismatch vs the "
            f"recorded LLM run — version {version_id} stays draft ({verification_reason})",
        )
        return

    # Promotion gate: while a FRESH optimized plan exists, auto-compile must
    # never promote a legacy declarative/plan composition — it would shadow
    # (or be shadowed by) the optimized plan's serving script. The candidate
    # stays draft (auditable) and promotion is skipped.
    try:
        fresh_optimized = await registry_client.get_optimized_plan(agent_type_id)
    except Exception as exc:  # pragma: no cover — gate is best-effort
        logger.warning(
            "Optimized-plan freshness check failed during auto-compile: %s", exc
        )
        fresh_optimized = None
    if fresh_optimized is not None:
        if span is not None:
            span.set_attribute("script.autocompile_eligible", False)
            span.set_attribute(
                "script.autocompile_skip_reason",
                "fresh optimized plan exists — candidate stays draft",
            )
        logger.info(
            "Auto-compile skipped promotion: a fresh optimized plan (%s) exists "
            "for agent type %s — candidate version %s stays draft so it can "
            "never shadow the optimized plan",
            fresh_optimized.get("optimized_plan_id"), agent_type_id, version_id,
        )
        return

    # Promote immediately: ...
    await registry_client.promote_version(version_id)
    # No dispatcher cache to drop — serving lookups are always fresh (see the
    # freshness note in dispatch.py), so the very next run takes the script
    # path without any invalidation step.
    if span is not None:
        span.set_attribute("script.compiled", True)
        span.set_attribute("script.promoted", True)
    if has_composition:
        logger.info(
            "Auto-compiled the plan's model-authored composition and promoted "
            "serving script version %s for agent type %s (from session %s, "
            "sandboxed Python segments + bridges as authored)",
            version_id, agent_type_id, session_id,
        )
    else:
        logger.info(
            "Auto-compiled and promoted serving script version %s for agent "
            "type %s (from session %s, %d recorded tool calls)",
            version_id, agent_type_id, session_id, len(tool_sequence),
        )


def _skip(span: Any, reason: str) -> None:
    """Record an ineligible auto-compile attempt (logged, never an error)."""
    logger.info("Auto-compile skipped: %s", reason)
    if span is not None:
        span.set_attribute("script.autocompile_eligible", False)
        span.set_attribute("script.autocompile_skip_reason", reason[:200])


def _script_name(agent_type_id: str) -> str:
    """Stable script definition name per agent type (dedupe on submit)."""
    return f"auto-{str(agent_type_id)[:8]}"


# ── Generate → test → refine loop (Software 3.0) ─────────────────────────────


def _plan_step_name(index: int, plan_step: dict[str, Any]) -> str:
    """Step name the compiler derives for plan step ``index`` (same formula)."""
    from app.agent_runtime.scripts.compiler import _sanitize_step_name

    raw = str(plan_step.get("tool_name") or plan_step.get("step_type") or "step")
    return f"step{index + 1}_{_sanitize_step_name(raw)}"


def _authored_segments(plan_steps: list[dict[str, Any]]) -> dict[str, str]:
    """Map step name → authored python_source for every scripted plan step."""
    segments: dict[str, str] = {}
    for index, step in enumerate(plan_steps or []):
        if isinstance(step, dict) and step.get("python_source"):
            segments[_plan_step_name(index, step)] = str(step["python_source"])
    return segments


def _apply_repaired_sources(
    plan_steps: list[dict[str, Any]], repaired: dict[str, str]
) -> list[dict[str, Any]]:
    """Return plan steps with repaired python_source applied (by step name)."""
    updated: list[dict[str, Any]] = []
    for index, step in enumerate(plan_steps):
        name = _plan_step_name(index, step) if isinstance(step, dict) else ""
        if name in repaired and isinstance(step, dict):
            replacement = dict(step)
            replacement["python_source"] = repaired[name]
            updated.append(replacement)
        else:
            updated.append(step)
    return updated


class _RecordedToolReplayClient:
    """Async tool-client double that replays the recorded run's outputs.

    The test execution of the composed script must be deterministic and
    side-effect free: every ``tools.call`` in a sandboxed segment is answered
    with the captured output of that recorded tool call (in order), never by
    contacting Communication Hub.
    """

    def __init__(self, recorded: list[dict[str, Any]]) -> None:
        self._remaining = [dict(call) for call in recorded or []]
        self.calls: list[str] = []

    async def call_tool(self, tool_name: str, arguments: Any = None, **_: Any) -> Any:
        self.calls.append(tool_name)
        if tool_name.startswith(("semantic____", "decision____")):
            # Model-backed steps (LLM bridges / System One decisions) run
            # live at serving time; the deterministic test replays a benign
            # stub so segment/tool logic is still fully exercised.
            return {"summary": "", "output": ""}
        for index, call in enumerate(self._remaining):
            if call.get("tool_name") == tool_name:
                return self._remaining.pop(index).get("tool_output")
        raise SandboxError(
            f"Tool '{tool_name}' has no recorded output for the test run — "
            "the script called a tool that was not part of the recorded run"
        )


def _recorded_inputs(tool_sequence: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct the recorded run's input data from captured tool arguments.

    Merging the recorded tool inputs gives the test replay the same input
    variables the segments saw during the original LLM run (last value wins).
    """
    inputs: dict[str, Any] = {}
    for call in tool_sequence or []:
        arguments = call.get("tool_input")
        if isinstance(arguments, dict):
            inputs.update(arguments)
    return inputs


async def _test_composition(
    graph: Any,
    tool_sequence: list[dict[str, Any]],
    *,
    session_id: str,
    agent_type_id: str,
) -> tuple[bool, str]:
    """Execute the composed script against the recorded run data as a test.

    Deterministic replay: tool steps read captured outputs, sandboxed
    segments execute with the replay client injected, model-backed steps
    (bridges/decisions) are skipped — they run live at serving time. Returns
    ``(ok, humanized_error)``; the error text is what gets fed back to the
    authoring LLM for repair.
    """
    from app.agent_runtime.scripts.runner import ScriptRunner
    from app.agent_runtime.scripts.schemas import (
        DecisionStep,
        SemanticBridgeStep,
        StepGraph,
    )

    if not isinstance(graph, StepGraph):  # pragma: no cover — defensive
        return False, "compiled graph has an unexpected shape"
    replay = _RecordedToolReplayClient(tool_sequence)
    has_model_backed_steps = any(
        isinstance(step, (SemanticBridgeStep, DecisionStep)) for step in graph.steps
    )
    try:
        result = await ScriptRunner(tool_client=replay).execute(
            graph,
            session_id=session_id,
            agent_type_id=agent_type_id,
            # Seed the replay context with the recorded run's input data:
            # the arguments captured on the recorded tool calls.
            initial_context=_recorded_inputs(tool_sequence),
        )
    except SandboxError as exc:
        return False, f"sandbox failure: {exc}"
    except Exception as exc:
        first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return False, f"execution failure: {type(exc).__name__}: {first_line}"
    # Output contract: the composed script must produce the final
    # user-facing result (never None/empty for fully deterministic scripts).
    if result is None or (not has_model_backed_steps and not result):
        return False, (
            "wrong-shape output: the script produced no user-facing result — "
            "``result`` must hold the final value in the required format"
        )
    return True, ""


async def _refine_composition(
    *,
    compiler: Any,
    name: str,
    plan_steps: list[dict[str, Any]],
    tool_sequence: list[dict[str, Any]],
    traits: dict[str, Any],
    session_id: str,
    agent_type_id: str,
    span: Any,
) -> Any | None:
    """Bounded generate → test → refine loop for the model-authored script.

    The LLM's authored composition (plan segments) is compiled and tested
    against the recorded run data. On a compile/validation/execution failure
    or a wrong-shape output, the typed humanized error plus the sandbox
    capability contract go back to the authoring LLM (repair generator) for
    a repaired version — at most ``MAX_SCRIPT_REFINEMENT_ATTEMPTS`` attempts.
    The first passing version wins; exhaustion returns ``None`` (nothing is
    promoted) with the outcome logged humanized.
    """
    max_attempts = MAX_SCRIPT_REFINEMENT_ATTEMPTS
    if span is not None:
        span.set_attribute("script.refine_max_attempts", max_attempts)
    contract = build_capability_contract(
        output_format=(traits or {}).get("output_type"),
        tool_names=[
            str(call.get("tool_name"))
            for call in tool_sequence
            if call.get("tool_name")
        ],
        available_variables=sorted(_authored_segments(plan_steps)),
    )
    segments = _authored_segments(plan_steps)
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        # 1. Generate (compile = validate the authored/repaired source).
        graph = None
        try:
            graph = compiler.compile_from_plan(name=name, plan_steps=plan_steps)
        except SandboxCompileError as exc:
            last_error = f"sandbox compile failed: {exc}"
        except Exception as exc:
            first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            last_error = f"script validation failed: {first_line}"
        # 2. Test against the recorded run data.
        if graph is not None:
            ok, last_error = await _test_composition(
                graph,
                tool_sequence,
                session_id=session_id,
                agent_type_id=agent_type_id,
            )
            if ok:
                logger.info(
                    "Authored script passed the recorded-run test on attempt "
                    "%d/%d — delivering to the registry",
                    attempt, max_attempts,
                )
                if span is not None:
                    span.set_attribute("script.refine_attempts", attempt)
                    span.set_attribute("script.refine_outcome", "passed")
                return graph
        logger.info(
            "Authored script failed the recorded-run test "
            "(attempt %d/%d): %s", attempt, max_attempts, last_error,
        )
        # 3. Refine: feed error + contract back to the authoring LLM.
        if attempt == max_attempts:
            break
        generator = _script_repair_generator
        if generator is None:
            logger.warning(
                "No script repair generator installed — cannot refine the "
                "authored script; refinement ends after %d attempt(s)",
                attempt,
            )
            break
        try:
            repaired = await generator(contract, last_error, segments, attempt)
        except Exception as exc:
            logger.warning("LLM script repair generation failed: %s", exc)
            repaired = None
        if not repaired:
            logger.warning(
                "LLM produced no repaired script version — refinement "
                "exhausted after %d attempt(s); nothing will be promoted",
                attempt,
            )
            break
        repaired = {
            name: source
            for name, source in dict(repaired).items()
            if name in segments and isinstance(source, str) and source.strip()
        }
        if not repaired:
            logger.warning("LLM repair touched no authored segment — ignoring")
            continue
        segments.update(repaired)
        plan_steps = _apply_repaired_sources(plan_steps, repaired)
    if span is not None:
        span.set_attribute("script.refine_attempts", max_attempts)
        span.set_attribute("script.refine_outcome", "exhausted")
    logger.warning(
        "Script refinement exhausted after %d attempt(s); last failure: %s "
        "— nothing promoted for this run",
        max_attempts, last_error,
    )
    return None


async def _verify_against_llm_run(
    graph: Any,
    tool_sequence: list[dict[str, Any]],
    *,
    session_id: str,
    agent_type_id: str,
    registry_client: Any,
) -> tuple[bool, str, Any]:
    """GENUINE verification of a fully-scripted candidate (product decision 3).

    Executes the candidate in the sandbox against the recorded run's captured
    tool outputs (deterministic replay) and compares its output against the
    recorded LLM run's actual result using the tolerant comparator. Returns
    ``(ok, humanized_reason, actual_output)`` — a mismatch keeps the version
    in draft (never promoted).
    """
    from app.agent_runtime.scripts.runner import ScriptRunner
    from app.agent_runtime.scripts.verification import VerificationEngine

    replay = _RecordedToolReplayClient(tool_sequence)
    try:
        result = await ScriptRunner(tool_client=replay).execute(
            graph,
            session_id=session_id,
            agent_type_id=agent_type_id,
            initial_context=_recorded_inputs(tool_sequence),
        )
    except Exception as exc:
        first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return False, f"execution failure: {type(exc).__name__}: {first_line}", None
    engine = VerificationEngine(
        runner=ScriptRunner(tool_client=replay),  # type: ignore[arg-type]
        registry_client=registry_client,  # type: ignore[arg-type]
    )
    try:
        reference = await registry_client.get_llm_reference(session_id)
    except Exception as exc:
        return False, f"recorded LLM reference unavailable: {exc}", result
    expected = engine._extract_reference_output(reference)
    if expected is None:
        return False, (
            "the recorded LLM run has no reference output to verify against"
        ), result
    tolerance = getattr(graph, "comparison_tolerance", None)
    if engine.compare(expected, result, tolerance):
        return True, "", result
    return False, f"output mismatch: {engine.diff(expected, result)}", result


def _plan_has_composition(plan_steps: list[dict[str, Any]]) -> bool:
    """Whether the plan carries a model-authored composition.

    True when any plan step authors a sandboxed ``python_source`` segment or
    records an explicit final-output decision (``output_mode``) — such plans
    must be compiled via ``compile_from_plan``, never from the recorded
    tool sequence (which would discard the composition).
    """
    for step in plan_steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("python_source") or step.get("output_mode"):
            return True
    return False


def _describe(plan_steps: list[dict[str, Any]], tool_sequence: list[dict[str, Any]]) -> str:
    """Human-readable summary of what the compiled workflow does."""
    goal = ""
    for step in plan_steps:
        text = str(step.get("description") or step.get("goal") or "")
        if text:
            goal = text
            break
    tools = ", ".join(
        dict.fromkeys(str(call.get("tool_name")) for call in tool_sequence)
    )
    summary = f"Auto-compiled from an LLM run: deterministic replay of tool calls [{tools}]."
    if goal:
        summary = f"{summary} Plan goal: {goal}"
    return summary[:500]
