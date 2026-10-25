"""Script-First Dispatcher (Agent Runtime).

Fixed platform strategy — **no execution modes exist**:

- A verified/compiled serving script version exists for the workflow → run
  the script automatically.
- No serving script → run the existing LLM executor unchanged (no error).
- On **any** script failure → **unconditional** LLM fallback (a run never
  fails solely because a script failed, E2), then the bounded
  self-improvement repair loop (E9/E10): defect diagnosis → LLM-produced
  repaired candidate (``repaired_from`` lineage + ``RepairAttempt``) →
  re-verification → bounded retry of the repaired script. When the repair
  budget is exhausted the run stays on the LLM path.

Script tool calls traverse Communication Hub with the same mTLS certificate
and identity path as the agent's own tool calls (identity parity, SEC1);
nothing here touches the database — all registry access goes through the CC
internal API via ``ScriptRegistryClient``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from opentelemetry import trace

from app.agent_runtime.comm_hub_client import CommHubToolClient
from app.agent_runtime.scripts.cc_client import (
    ScriptRegistryClient,
    ScriptRegistryClientError,
)
from app.agent_runtime.scripts.fallback import FallbackController
from app.agent_runtime.scripts.repair import RepairContext, RepairLoop
from app.agent_runtime.scripts.runner import (
    ScriptExecutionError,
    ScriptRunner,
)
from app.agent_runtime.scripts.sandbox import SandboxError
from app.agent_runtime.scripts.schemas import StepGraph

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Rough LLM-token baseline saved per deterministic tool step (G3 estimate).
_TOKENS_SAVED_PER_STEP = 1000

# Freshness note (retire defect fix): optimized-plan and serving-version
# lookups are intentionally NEVER cached. Control Center retirement ("Retire
# plan" / plan regeneration) has no cross-process invalidation channel into
# Agent Runtime, so any TTL cache served a retired plan/script after the user
# retired it ("Retire plan doesn't retire"). The lookups are one lightweight
# GET per session start — always fetch fresh.

_serving_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

# Deprecated no-op: kept for backwards-compatible imports/tests. Lookups are
# always fresh (see freshness note above); there is nothing left to reset.
_optimized_plan_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def reset_serving_cache() -> None:
    """Historical cache-reset hook — now a no-op (lookups always fresh)."""
    _serving_cache.clear()
    _optimized_plan_cache.clear()


@dataclass
class _ServingScript:
    """A serving script version fetched from the CC registry."""

    script_definition_id: str
    script_version_id: str
    script_version_label: str | None
    graph_json: dict[str, Any]
    # Definition name distinguishes the optimized-plan composition
    # (``optimized-<id8>``) from legacy auto-compiled scripts (``auto-<id8>``).
    script_definition_name: str | None = None
    python_source: str | None = None
    sandbox_validation_status: str | None = None
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None
    # Measured reference-run token usage (N5) for tokens_saved_actual.
    reference_tokens: int | None = None
    # Auto-compiled legacy script definitions get the ``auto-<id8>`` name;
    # the optimized-plan composition is ``optimized-<id8>``.
    is_optimized_artifact: bool = False
    # Execution semantics (product decision): only fully_scripted versions are
    # served directly (zero-LLM software mode); all other scripts are simply
    # invocable virtual tools and the LLM path orchestrates.
    fully_scripted: bool = False


async def _get_serving_script(
    registry_client: ScriptRegistryClient,
    agent_type_id: str,
) -> _ServingScript | None:
    """Fetch the current serving script version (ALWAYS fresh — no cache).

    Retirement correctness: a CC-side retirement (plan regeneration, "Retire
    plan") must be visible on the very next run; see the freshness note above.
    """
    try:
        payload = await registry_client.get_serving_version(agent_type_id)
    except ScriptRegistryClientError as exc:
        # Registry unavailability must never block execution — LLM path.
        logger.warning(
            "Serving-version lookup failed for agent_type %s; using LLM path: %s",
            agent_type_id, exc,
        )
        payload = None
    if not payload:
        return None
    definition_name = payload.get("script_definition_name") or ""
    # Optimized-artifact detection by LINEAGE, not name (issue fix): the
    # command-driven flow authors scripts under agent-chosen definition names
    # and links them to the optimized plan via ``source_optimized_plan_id``.
    # A name-based ``optimized-`` prefix check rejected those valid serving
    # scripts and silently degraded every post-optimization run to the LLM
    # path. The legacy ``optimized-<id8>`` name stays accepted as a fallback.
    is_optimized_artifact = bool(
        payload.get("source_optimized_plan_id")
    ) or definition_name.startswith("optimized-")
    return _ServingScript(
        script_definition_id=str(payload.get("script_definition_id") or ""),
        script_definition_name=definition_name,
        script_version_id=str(payload["script_version_id"]),
        script_version_label=payload.get("script_version_label"),
        graph_json=payload.get("declarative_step_graph"),
        python_source=payload.get("python_source"),
        sandbox_validation_status=payload.get("sandbox_validation_status"),
        cpu_limit_seconds=payload.get("cpu_limit_seconds"),
        memory_limit_mb=payload.get("memory_limit_mb"),
        wall_time_limit_seconds=payload.get("wall_time_limit_seconds"),
        reference_tokens=payload.get("reference_tokens"),
        fully_scripted=bool(payload.get("fully_scripted")),
        is_optimized_artifact=is_optimized_artifact,
    )


async def _get_optimized_plan(
    registry_client: ScriptRegistryClient,
    agent_type_id: str,
) -> dict[str, Any] | None:
    """Fetch the fresh ready optimized plan (ALWAYS fresh — no cache).

    Execution preference (two-layer plan model): a ready OptimizedImplementation
    Plan newer than the base plan supersedes the base plan's serving script.
    Returns ``None`` when absent / stale / failed → base-plan fallback.
    """
    try:
        payload = await registry_client.get_optimized_plan(agent_type_id)
    except ScriptRegistryClientError as exc:
        # Unavailability never blocks execution — base-plan fallback.
        logger.warning(
            "Optimized-plan lookup failed for agent_type %s; using base-plan path: %s",
            agent_type_id, exc,
        )
        payload = None
    return payload


async def run_session_script_first(
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    run_llm: Callable[[], Awaitable[None]],
    input_data: dict[str, Any] | None = None,
) -> None:
    """Execute a session via the Script-First Dispatcher.

    Args:
        session_id:     Session UUID string.
        agent_type_id:  Agent type UUID string (scripts are bound per type).
        data_client:    ControlCenterDataClient (cert manager carrier; CC API access).
        run_llm:        Closure that runs the existing LLM executor to completion.
        input_data:     The session's input payload (``None`` for a resume).
                        Carries the ``__command`` marker for command-driven
                        side executions (e.g. "optimize-and-verify").
    """
    # Command-driven side executions (``__command`` marker) run the NORMAL LLM
    # agent loop with the command's mission prompt + the optimization system
    # tools. Script-first dispatch / the optimized-plan preference must NEVER
    # intercept them: the command is authoring the composition, not executing
    # an already-served script. The mission prompt is injected as the user
    # message by the executor itself.
    command = input_data.get("__command") if isinstance(input_data, dict) else None
    if command:
        logger.info(
            "command execution (%s) — running LLM loop, bypassing script dispatch",
            command,
        )
        await run_llm()
        return

    cert_manager = getattr(data_client, "_cert_manager", None)
    if not agent_type_id:
        # No agent-type context (e.g. HITL resume) — scripts are bound per
        # agent type, so continuation always takes the LLM path.
        logger.info(
            "Script dispatch: session %s has no agent-type context — LLM path",
            session_id,
        )
        await run_llm()
        return
    if cert_manager is None or not getattr(cert_manager, "is_loaded", False):
        # No service certificate — registry API unavailable; run LLM path.
        logger.info(
            "Script dispatch: session %s has no loaded cert manager — LLM path",
            session_id,
        )
        await run_llm()
        return

    registry_client = ScriptRegistryClient(cert_manager)
    logger.info(
        "Script dispatch: session %s agent_type %s — resolving execution "
        "preference (optimized plan vs serving script)",
        session_id, agent_type_id,
    )
    # Execution precedence (two-layer plan model): the fresh ready optimized
    # plan is resolved FIRST — a legacy auto-compiled serving script must
    # never shadow it.
    optimized = await _get_optimized_plan(registry_client, agent_type_id)
    if optimized is not None:
        if not optimized.get("fully_scripted"):
            # Tool mode: the LLM orchestrates and the optimized plan's scripts
            # stay invocable ``script____<name>`` tools — no script is ever
            # served directly for the whole session.
            logger.info(
                "Script dispatch: session %s fresh optimized plan %s is "
                "tool-mode — LLM path (scripts available as tools)",
                session_id, optimized.get("optimized_plan_id"),
            )
            await _run_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm)
            return
        # fully_scripted optimized plan → run its END-TO-END script (the
        # optimized-plan artifact). A legacy auto-compiled serving script is
        # never served in place of it.
        serving = await _get_serving_script(registry_client, agent_type_id)
        if (
            serving is None
            or not serving.is_optimized_artifact
            or not serving.fully_scripted
            or (serving.graph_json is None and serving.python_source is None)
        ):
            logger.info(
                "Script dispatch: session %s fresh optimized plan %s is "
                "fully_scripted but no optimized serving script exists — "
                "base-plan LLM path",
                session_id, optimized.get("optimized_plan_id"),
            )
            await _run_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm)
            return
    else:
        # No fresh optimized plan → legacy serving-script lookup (its
        # fully_scripted/freshness gates apply unchanged below).
        serving = await _get_serving_script(registry_client, agent_type_id)
        if serving is None or (
            serving.graph_json is None and serving.python_source is None
        ):
            # Script-first means automatic: no verified script → LLM, no error.
            await _run_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm)
            return
        if serving.fully_scripted:
            # A fully_scripted serving script is an optimized-plan artifact
            # (the base plan no longer authors one); without a fresh optimized
            # plan it must not serve — base implementation plan (LLM path).
            logger.info(
                "Script dispatch: session %s serving script %s is fully_scripted "
                "but no fresh optimized plan exists — base-plan LLM path",
                session_id, serving.script_version_id,
            )
            await _run_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm)
            return
        # Product decision — scripts are TOOLS by default: a serving script
        # that is not marked fully_scripted is never served directly. The LLM
        # orchestrates, invoking scripts via the virtual ``script____<name>``
        # tool surface; the recorded run still feeds auto-compilation.
        logger.info(
            "Script dispatch: session %s serving script %s is not fully_scripted "
            "— LLM path (script available as tool)",
            session_id, serving.script_version_id,
        )
        await _run_llm_path(session_id, agent_type_id, data_client, cert_manager, run_llm)
        return

    with tracer.start_as_current_span(
        "script.dispatch",
        attributes={
            "session_id": session_id,
            "agent_type_id": agent_type_id,
            "script.version": serving.script_version_id,
        },
    ):
        await _run_script_path(
            session_id=session_id,
            agent_type_id=agent_type_id,
            data_client=data_client,
            cert_manager=cert_manager,
            registry_client=registry_client,
            serving=serving,
            run_llm=run_llm,
        )


async def _run_llm_path(
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    cert_manager: Any,
    run_llm: Callable[[], Awaitable[None]],
) -> None:
    """Run the LLM path: drop stale capture, run, then auto-compile the
    recorded sequence (fire-and-forget) per the self-improvement loop."""
    from app.agent_runtime.scripts.capture import clear as _clear_capture

    _clear_capture(session_id)
    await run_llm()
    logger.info(
        "Script dispatch: session %s LLM run finished — scheduling auto-compile",
        session_id,
    )
    _schedule_autocompile(session_id, agent_type_id, data_client, cert_manager)


def _session_bound_tool_client(cert_manager: Any) -> CommHubToolClient:
    """Build a CommHubToolClient bound to the session's identity context.

    The script's MCP tool calls use the exact same mTLS certificate and CH
    path as the executing agent's own tool calls (identity parity, SEC1):
    same cert manager, same per-call token injection by CH, same CC
    permission resolution. Scripts never introduce a separate identity.
    """
    tool_client = CommHubToolClient()
    cert_path = getattr(cert_manager, "cert_path", None)
    key_path = getattr(cert_manager, "key_path", None)
    if cert_path and key_path:
        tool_client.set_certificate(str(cert_path), str(key_path))
    return tool_client


async def _execute_script(
    graph: StepGraph,
    *,
    tool_client: CommHubToolClient,
    session_id: str,
    agent_type_id: str,
    version_label: str | None,
    log_shipper: Callable[..., Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Run one script execution, returning (result, telemetry)."""
    runner = ScriptRunner(tool_client, log_shipper=log_shipper)
    result = await runner.execute(
        graph,
        session_id=session_id,
        agent_type_id=agent_type_id,
        script_version_label=version_label,
    )
    telemetry: dict[str, Any] = {}
    if isinstance(result, dict):
        telemetry = result.pop("__execution_telemetry__", {}) or {}
    return result, telemetry


async def _report_success_execution(
    registry_client: ScriptRegistryClient,
    *,
    script_version_id: str,
    telemetry: dict[str, Any],
    session_id: str,
    reference_tokens: int | None = None,
) -> None:
    """Report a successful script execution with token accounting (G3/N5).

    ``tokens_saved_actual`` is measured against the reference LLM run's real
    token usage when known (serving-version payload); otherwise only the
    per-step estimate is reported (historical semantics).
    """
    tools_invoked = telemetry.get("tools_invoked", [])
    payload: dict[str, Any] = {
        "script_version_id": script_version_id,
        "outcome": "success",
        "duration_ms": telemetry.get("duration_ms"),
        "tools_invoked": tools_invoked,
        "model_backed_steps_used": telemetry.get("model_backed_steps_used"),
        "session_id": session_id,
        # Identity parity: tool calls used the session's own mTLS/CH path.
        "identity_parity_confirmed": True,
        "tokens_saved_estimate": _TOKENS_SAVED_PER_STEP * len(tools_invoked),
    }
    if reference_tokens is not None:
        # Measured, not estimated (N5): the model-backed steps that DID run
        # consumed some tokens; everything avoided versus the reference run
        # is the measured saving.
        actual_used = sum(
            int(step.get("tokens_used") or 0)
            for step in telemetry.get("model_backed_steps_used", [])
            if isinstance(step, dict)
        )
        payload["tokens_saved_actual"] = max(reference_tokens - actual_used, 0)
    try:
        await registry_client.report_execution(payload)
    except Exception as exc:
        logger.warning("Failed to report script execution record: %s", exc)


@dataclass
class _ScriptOutcome:
    """Result of a script execution attempt."""

    ok: bool
    result: Any = None
    telemetry: dict[str, Any] = field(default_factory=dict)


def _script_log_shipper(data_client: Any, session_id: str) -> Any:
    """Build a best-effort execution-log shipper bound to the session.

    Wraps the CC data client ``log_execution_event``; the runner calls it for
    script-run start / step completion / model-backed steps / completion —
    logging failures never break the run (swallowed by the data client).
    """

    async def _ship(
        event_type: str, message: str, data: dict[str, Any], log_level: str = "INFO"
    ) -> None:
        await data_client.log_execution_event(
            session_id,
            event_type,
            message,
            data,
            log_level=log_level,
            event_category="functional",
            actor_type="system",
        )

    return _ship


async def _ship_fallback_log(log_shipper: Any, serving: _ServingScript, failure: Any) -> None:
    """Ship a fallback event so script→LLM handoff is visible in the log stream."""
    if log_shipper is None:
        return
    message = (
        f"Script version '{serving.script_version_label or serving.script_version_id}' "
        f"failed — falling back to the LLM path: {failure}"
    )
    try:
        await log_shipper(
            "script_fallback_to_llm",
            message[:800],
            {
                "script_version_id": serving.script_version_id,
                "script_version_label": serving.script_version_label,
                "failure": str(failure)[:800],
            },
            "WARNING",
        )
    except Exception as exc:  # never break the run
        logger.warning("Fallback log shipping failed for session: %s", exc)


async def _attempt_script(
    graph: StepGraph,
    *,
    tool_client: CommHubToolClient,
    session_id: str,
    agent_type_id: str,
    script_version_id: str | None,
    script_version_label: str | None,
    controller: FallbackController,
    log_shipper: Any = None,
) -> _ScriptOutcome:
    """Attempt a script run; typed failures are captured (never raised)."""
    try:
        result, telemetry = await controller.run_with_fallback(
            lambda: _execute_script(
                graph,
                tool_client=tool_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                version_label=script_version_label,
                log_shipper=log_shipper,
            ),
            script_version_id=script_version_id,
            script_version_label=script_version_label,
            session_id=session_id,
            agent_type_id=agent_type_id,
            llm_fallback=None,
        )
    except (ScriptExecutionError, SandboxError) as exc:
        return _ScriptOutcome(ok=False, result=exc)
    if isinstance(result, tuple) and len(result) == 2:
        return _ScriptOutcome(ok=True, result=result[0], telemetry=result[1])
    return _ScriptOutcome(ok=True, result=result)


def _schedule_autocompile(
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    cert_manager: Any,
) -> None:
    """Fire-and-forget post-run auto-compilation (never affects the run)."""
    from app.agent_runtime.scripts import autocompile

    try:
        coro = autocompile.schedule_autocompile(
            session_id, agent_type_id, data_client, cert_manager
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Auto-compile setup failed for session %s: %s", session_id, exc)
        return
    # schedule_autocompile is async (it awaits the session-bound tool client
    # setup); run it on the live loop as a detached task — the returned task
    # self-supervises via its done-callback.
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover — no loop, nothing we can do
        logger.warning(
            "Auto-compile skipped for session %s: no running event loop", session_id
        )
        coro.close()
        return
    asyncio.get_running_loop().create_task(coro)


async def _run_script_path(
    *,
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    cert_manager: Any,
    registry_client: ScriptRegistryClient,
    serving: _ServingScript,
    run_llm: Callable[[], Awaitable[None]],
) -> None:
    """Run the serving script; on any failure fall back unconditionally (E2)."""
    # Composition validation before execution (Phase 2.5): a sandboxed
    # python_source version must sandbox-compile; a declarative graph must
    # StepGraph-validate. Any failure → unconditional LLM fallback; the run
    # never fails solely because a script failed.
    if serving.python_source:
        try:
            from app.agent_runtime.scripts.sandbox import compile_sandbox

            compile_sandbox(serving.python_source)
        except Exception as exc:
            logger.warning(
                "Sandboxed source for version %s failed composition "
                "validation; using LLM path: %s",
                serving.script_version_id, exc,
            )
            await run_llm()
            return
        await _run_sandboxed_script_path(
            session_id=session_id,
            agent_type_id=agent_type_id,
            data_client=data_client,
            registry_client=registry_client,
            serving=serving,
            run_llm=run_llm,
        )
        return

    try:
        graph = StepGraph.model_validate(serving.graph_json)
    except Exception as exc:
        # An invalid stored graph is a script failure like any other —
        # unconditional LLM fallback; the run never fails for it.
        logger.error(
            "Stored step graph for version %s failed validation; using LLM path: %s",
            serving.script_version_id, exc,
        )
        await run_llm()
        return

    tool_client = _session_bound_tool_client(cert_manager)
    controller = FallbackController(registry_client)
    repair_loop = RepairLoop(registry_client)
    log_shipper = _script_log_shipper(data_client, session_id)

    logger.info(
        "Script execution: session %s running serving script version %s (%d steps, "
        "no LLM between steps) — tool calls will be tagged provenance=script",
        session_id, serving.script_version_id, len(graph.steps),
    )

    first = await _attempt_script(
        graph,
        tool_client=tool_client,
        session_id=session_id,
        agent_type_id=agent_type_id,
        script_version_id=serving.script_version_id,
        script_version_label=serving.script_version_label,
        controller=controller,
        log_shipper=log_shipper,
    )

    outcome: _ScriptOutcome = first
    serving_version_id = serving.script_version_id

    if not first.ok:
        # Unconditional LLM fallback first — the run completes regardless of
        # what the repair loop does afterwards (E2/F3).
        await _ship_fallback_log(
            log_shipper,
            serving,
            failure=first.result,
        )
        await run_llm()
        # LLM-path completion: record the sequence for auto-compilation
        # (skipped inside the hook while this serving version still serves).
        _schedule_autocompile(session_id, agent_type_id, data_client, cert_manager)

        # Bounded repair-retry (E9/E10): diagnose → LLM candidate →
        # re-verify → retry the repaired script path.
        repaired = await _try_repair_retry(
            repair_loop=repair_loop,
            tool_client=tool_client,
            context=RepairContext(
                script_definition_id=serving.script_definition_id,
                script_version_id=serving.script_version_id,
                graph_json=serving.graph_json,
                session_id=session_id,
                agent_type_id=agent_type_id,
            ),
            llm_repair_generator=None,
        )
        if repaired is not None:
            repaired_graph, repaired_version_id = repaired
            retry = await _attempt_script(
                repaired_graph,
                tool_client=tool_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                script_version_id=repaired_version_id,
                script_version_label=None,
                controller=controller,
                log_shipper=log_shipper,
            )
            if retry.ok:
                logger.info(
                    "Repaired script %s retry succeeded for session %s",
                    repaired_version_id, session_id,
                )
                outcome = retry
                serving_version_id = repaired_version_id
            else:
                logger.info(
                    "Repaired script retry failed for session %s; staying on LLM",
                    session_id,
                )
                return  # LLM path already completed the session.
        else:
            # Repair exhausted or unavailable — stay on the LLM path.
            return

    if outcome.result is None:
        # LLM fallback path owns the session lifecycle.
        return

    await _report_success_execution(
        registry_client,
        script_version_id=serving_version_id,
        telemetry=outcome.telemetry,
        session_id=session_id,
    )
    # The script's result is stored as-is: a string render output stays a
    # raw string end-to-end; dict results (deterministic outputs) are kept.
    await data_client.mark_session_completed(session_id, outcome.result)
    logger.info(
        "Session %s completed via script %s, tokens_saved≈%d",
        session_id, serving_version_id,
        _TOKENS_SAVED_PER_STEP * len(outcome.telemetry.get("tools_invoked", [])),
    )


async def _run_sandboxed_script_path(
    *,
    session_id: str,
    agent_type_id: str,
    data_client: Any,
    registry_client: ScriptRegistryClient,
    serving: _ServingScript,
    run_llm: Callable[[], Awaitable[None]],
) -> None:
    """Run a model-authored ``python_source`` version in the AR sandbox (N3).

    The script's only external binding is the session-bound MCP-only client
    injected by the runner (identity parity, SEC1/E8). Any sandbox violation
    or cap termination triggers the unconditional LLM fallback with the
    trigger reason recorded (Flow C) — the run never fails for the script.
    """
    from app.agent_runtime.scripts.sandbox import SandboxCaps

    cert_manager = getattr(data_client, "_cert_manager", None)
    tool_client = _session_bound_tool_client(cert_manager)
    log_shipper = _script_log_shipper(data_client, session_id)

    logger.info(
        "Script execution: session %s running sandboxed python_source version %s "
        "(MCP-only injected client, provenance=script)",
        session_id, serving.script_version_id,
    )

    controller = FallbackController(registry_client)

    async def _run() -> tuple[Any, dict[str, Any]]:
        runner = ScriptRunner(tool_client, log_shipper=log_shipper)
        result = await runner.execute_python_source(
            serving.python_source or "",
            session_id=session_id,
            agent_type_id=agent_type_id,
            script_version_label=serving.script_version_label,
            caps=SandboxCaps.from_version_fields(
                serving.cpu_limit_seconds,
                serving.memory_limit_mb,
                serving.wall_time_limit_seconds,
            ),
        )
        telemetry: dict[str, Any] = {}
        if isinstance(result, dict):
            telemetry = result.pop("__execution_telemetry__", {}) or {}
        return result, telemetry

    try:
        result = await controller.run_with_fallback(
            _run,
            script_version_id=serving.script_version_id,
            script_version_label=serving.script_version_label,
            session_id=session_id,
            agent_type_id=agent_type_id,
            llm_fallback=None,
        )
    except (ScriptExecutionError, SandboxError) as exc:
        # Unconditional LLM fallback (E2) — reason already recorded by the
        # controller (sandbox_violation / resource_limit_exceeded / ...).
        logger.warning(
            "Sandboxed script %s failed for session %s — LLM fallback: %s",
            serving.script_version_id, session_id, exc,
        )
        await run_llm()
        return

    telemetry: dict[str, Any] = {}
    output_payload: Any = result
    if isinstance(result, dict):
        telemetry = result.pop("__execution_telemetry__", {}) or {}
        output_payload = result
    await _report_success_execution(
        registry_client,
        script_version_id=serving.script_version_id,
        telemetry=telemetry,
        session_id=session_id,
        reference_tokens=serving.reference_tokens,
    )
    # Store the script result as-is: a string render output stays a raw
    # string end-to-end so the UI shows the rendered text, not a JSON
    # object; dict results (deterministic outputs) are kept as-is.
    await data_client.mark_session_completed(session_id, output_payload)
    logger.info(
        "Session %s completed via sandboxed script %s",
        session_id, serving.script_version_id,
    )


async def _try_repair_retry(
    *,
    repair_loop: RepairLoop,
    tool_client: CommHubToolClient,
    context: RepairContext,
    llm_repair_generator: Any = None,
) -> tuple[StepGraph, str] | None:
    """Bounded repair-retry: diagnose → LLM candidate → re-verify → candidate.

    Returns ``(repaired_graph, repaired_version_id)`` when a re-verified
    candidate is ready to retry, else ``None`` (exhaustion → stay on LLM).
    """
    from app.agent_runtime.scripts.runner import ScriptExecutionError

    with tracer.start_as_current_span(
        "script.repair_retry",
        attributes={"script.version": context.script_version_id},
    ) as span:
        failure = ScriptExecutionError(
            "script defect — classified via the recorded fallback event"
        )
        try:
            outcome = await repair_loop.run(
                context, failure, llm_repair_generator=llm_repair_generator
            )
        except Exception as exc:  # repair is best-effort; never blocks the run
            logger.warning("Repair loop failed unexpectedly: %s", exc)
            return None

        if not outcome.has_candidate or outcome.repaired_graph_json is None:
            span.set_attribute("script.repair_outcome", "exhausted")
            return None

        span.set_attribute("script.repaired_version", outcome.repaired_version_id or "")
        try:
            repaired_graph = StepGraph.model_validate(outcome.repaired_graph_json)
        except Exception as exc:
            logger.warning("Repaired candidate graph invalid: %s", exc)
            span.set_attribute("script.repair_outcome", "invalid_candidate")
            return None
        return repaired_graph, str(outcome.repaired_version_id)
