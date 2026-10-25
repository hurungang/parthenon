"""Script Runner (Agent Runtime).

Executes compiled step graphs step-by-step. Every tool call goes through
Communication Hub exactly like an agent tool call (same mTLS path, same
permission resolution via Control Center, per-call token injection by CH —
SEC1/SEC2). Scripts carry no credentials.

Failures raise typed errors consumed by the Fallback Controller:
``ExecutionError``, ``SchemaMismatch``, ``OutputValidationFailure``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable

from opentelemetry import trace

from app.agent_runtime.comm_hub_client import CommHubToolClient, CommHubToolClientError
from app.agent_runtime.scripts.sandbox import (
    ResourceLimitExceededError,
    SandboxViolationError,
    run_sandboxed_python,
    unwrap_mcp_tool_result,
    SandboxCaps,
)
from app.agent_runtime.scripts.schemas import (
    DecisionStep,
    OutputStep,
    ScriptSegmentStep,
    SemanticBridgeStep,
    StepGraph,
    ToolCallStep,
    TransformStep,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_TEMPLATE_REF = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


# ── Typed failures (F1) ───────────────────────────────────────────────────────


class ScriptExecutionError(Exception):
    """Base typed failure for script runs."""


class ExecutionError(ScriptExecutionError):
    """Tool invocation failed (transport, permission denial, tool error)."""


class SchemaMismatch(ScriptExecutionError):
    """Tool result shape did not match the declared expectation."""


class OutputValidationFailure(ScriptExecutionError):
    """Final output failed validation against the declared output step."""


class ScriptRunner:
    """Deterministic executor for compiled step graphs.

    Session-bound: every execution must carry the session's identity context
    (session id + agent type); its MCP tool calls use the identical mTLS/CH
    path and dual OIDC identities as the executing agent's own tool calls
    (identity parity, E7/SEC1). Scripts never introduce a separate or
    anonymous identity.
    """

    # MCP-only boundary (E8, defense in depth on top of the StepGraph schema):
    # credential-shaped or network-target-shaped fields are rejected before
    # execution — external access flows exclusively through CH tool calls.
    _FORBIDDEN_FIELD_MARKERS = (
        "api_key", "apikey", "token", "secret", "password",
        "authorization", "credential", "connection_string",
    )

    # Brief outcome summaries shipped in execution logs — never full payloads
    # (large tool results must not flood the execution log stream).
    _BRIEF_MAX_CHARS = 300

    def __init__(
        self,
        tool_client: CommHubToolClient,
        log_shipper: Callable[[str, str, dict[str, Any], str], Awaitable[None]] | None = None,
    ) -> None:
        """``log_shipper(event_type, message, data, log_level)`` — best-effort
        execution-log sink (CC data client ``log_execution_event``). Logging
        failures never break the run (swallowed in ``_ship_log``)."""
        self._tool_client = tool_client
        self._log_shipper = log_shipper
        # Set by _run_tool_step when the MCP content envelope was unwrapped —
        # surfaced in the step's log entry for observability.
        self._last_tool_step_unwrapped = False
        self._last_tool_step_raw_envelope: Any = None

    async def _ship_log(
        self,
        event_type: str,
        message: str,
        data: dict[str, Any],
        log_level: str = "INFO",
    ) -> None:
        """Ship one execution log entry; failures are swallowed (best-effort)."""
        if self._log_shipper is None:
            return
        try:
            await self._log_shipper(event_type, message, data, log_level)
        except Exception as exc:  # logging must never abort execution
            logger.warning("Script execution log shipping failed: %s", exc)

    @classmethod
    def _brief(cls, result: Any) -> str:
        """Humanized one-line outcome summary (N5) — no raw JSON blobs.

        Produces a short natural-language description of what a step
        produced (shape + salient content), never a truncated JSON dump.
        """
        try:
            if result is None:
                return "no output"
            if isinstance(result, str):
                text = result.strip() or "empty text"
                if len(text) > cls._BRIEF_MAX_CHARS:
                    return f"text ({len(text)} chars): {text[: cls._BRIEF_MAX_CHARS]}…"
                return f"text: {text}"
            if isinstance(result, bool):
                return f"flag: {result}"
            if isinstance(result, (int, float)):
                return f"number: {result}"
            if isinstance(result, dict):
                if result and len(result) <= 4 and all(
                    isinstance(v, (str, int, float, bool)) or v is None
                    for v in result.values()
                ):
                    pairs = ", ".join(
                        f"{k}={'' if v is None else v}" for k, v in result.items()
                    )
                    return f"object with {len(result)} key(s) [{pairs}]"
                keys = ", ".join(str(k) for k in list(result.keys())[:8])
                more = (
                    f" (+{len(result) - 8} more)" if len(result) > 8 else ""
                )
                nested = [
                    v for v in result.values()
                    if isinstance(v, (list, dict))
                ]
                shape = (
                    f", includes {len(nested)} nested collection(s)" if nested else ""
                )
                return f"object with {len(result)} key(s) [{keys}{more}]{shape}"
            if isinstance(result, list):
                kinds = {type(item).__name__ for item in result[:10]}
                return (
                    f"list of {len(result)} item(s)"
                    f" ({', '.join(sorted(kinds)) if kinds else 'empty'})"
                )
            text = str(result)
        except Exception:  # pragma: no cover — defensive
            text = str(result)
        if len(text) > cls._BRIEF_MAX_CHARS:
            return text[: cls._BRIEF_MAX_CHARS] + f"… ({len(text)} chars total)"
        return text

    def _brief_raw_envelope(self) -> str:
        """One-line truncated raw MCP envelope for the step log (observability)."""
        text = json.dumps(
            self._last_tool_step_raw_envelope, ensure_ascii=False, default=str
        )
        if len(text) > self._BRIEF_MAX_CHARS:
            return text[: self._BRIEF_MAX_CHARS] + f"… ({len(text)} chars total)"
        return text

    def _enforce_mcp_only_boundary(self, graph: StepGraph) -> None:
        """Reject graphs that attempt non-MCP I/O or carry secrets (E8/SEC3).

        The StepGraph schema already restricts step kinds to MCP tool calls
        and local transforms; this is defense in depth at execution time:
        tool-call steps must target an MCP tool (name reference — never a
        network target), and no credential-shaped fields may appear.
        """
        for step in graph.steps:
            tool_name = getattr(step, "tool_name", None)
            if tool_name is not None and (not tool_name or "://" in tool_name):
                raise ExecutionError(
                    f"Step '{step.name}' has a non-MCP tool target "
                    f"'{tool_name}' — scripts may only call MCP tools (E8)"
                )
        blob = graph.model_dump_json().lower()
        for marker in self._FORBIDDEN_FIELD_MARKERS:
            if f'"{marker}"' in blob:
                raise ExecutionError(
                    f"Step graph contains forbidden field '{marker}' — scripts "
                    "never hold credentials (SEC3)"
                )

    async def execute(
        self,
        graph: StepGraph,
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the graph and return the final output payload.

        The run is bound to the agent session: ``session_id`` and
        ``agent_type_id`` are mandatory and carried on every CH tool call so
        the script's tool calls are indistinguishable from the agent's own at
        the identity/permission layer (SEC1). Raises a typed
        ``ScriptExecutionError`` subclass on any failure so the Script-First
        Dispatcher can classify and unconditionally fall back (F1).
        """
        if not session_id or not agent_type_id:
            # Identity parity is mandatory: refuse unbound execution.
            raise ExecutionError(
                "Script execution requires a session identity context "
                "(session_id and agent_type_id) — no anonymous identity path "
                "exists (SEC1)"
            )
        self._enforce_mcp_only_boundary(graph)
        started = time.monotonic()
        context: dict[str, Any] = dict(initial_context or {})
        model_backed_steps_used: list[dict[str, Any]] = []
        tools_invoked: list[dict[str, Any]] = []
        current_step: Any = None

        await self._ship_log(
            "script_run_started",
            f"Script '{graph.name}' started (version {script_version_label or 'n/a'}, "
            f"{len(graph.steps)} steps)",
            {
                "script_name": graph.name,
                "script_version": script_version_label,
                "step_count": len(graph.steps),
            },
        )

        with tracer.start_as_current_span("script.run") as span:
            span.set_attribute("script.name", graph.name)
            span.set_attribute("script.version_label", script_version_label or "")
            span.set_attribute("script.steps", len(graph.steps))

            try:
                for step in graph.steps:
                    current_step = step
                    if isinstance(step, ToolCallStep):
                        result = await self._run_tool_step(
                            step,
                            context,
                            session_id=session_id,
                            agent_type_id=agent_type_id,
                            script_version_label=script_version_label,
                        )
                        tools_invoked.append(
                            {"step": step.name, "tool_name": step.tool_name}
                        )
                    elif isinstance(step, DecisionStep):
                        result = await self._run_decision_step(
                            step,
                            context,
                            session_id=session_id,
                            agent_type_id=agent_type_id,
                            script_version_label=script_version_label,
                        )
                        tools_invoked.append(
                            {"step": step.name, "tool_name": step.tool_name}
                        )
                        model_backed_steps_used.append(
                            {"step": step.name, "kind": step.kind.value}
                        )
                    elif isinstance(step, SemanticBridgeStep):
                        result = await self._run_semantic_bridge_step(
                            step,
                            context,
                            session_id=session_id,
                            agent_type_id=agent_type_id,
                            script_version_label=script_version_label,
                        )
                        tools_invoked.append(
                            {"step": step.name, "tool_name": step.tool_name}
                        )
                        model_backed_steps_used.append(
                            {"step": step.name, "kind": step.kind.value}
                        )
                    elif isinstance(step, TransformStep):
                        result = self._run_transform_step(step, context)
                    elif isinstance(step, ScriptSegmentStep):
                        result = await self._run_script_segment_step(
                            step,
                            context,
                            session_id=session_id,
                            agent_type_id=agent_type_id,
                            script_version_label=script_version_label,
                        )
                    elif isinstance(step, OutputStep):
                        result = self._project_output(step, context)
                    else:  # pragma: no cover — schema forbids unknown kinds
                        raise ExecutionError(
                            f"Unsupported step kind in step '{step.name}'"
                        )

                    if step.output_key:
                        context[step.output_key] = result

                    kind = getattr(step, "kind", None)
                    envelope_note = (
                        " (MCP content envelope unwrapped — raw envelope: "
                        f"{self._brief_raw_envelope()})"
                        if isinstance(step, ToolCallStep)
                        and self._last_tool_step_unwrapped
                        else ""
                    )
                    await self._ship_log(
                        "script_step_completed",
                        f"Step '{step.name}' ({kind.value if kind else 'unknown'}) "
                        f"completed{envelope_note}: {self._brief(result)}",
                        {
                            "step_name": step.name,
                            "step_kind": kind.value if kind else "unknown",
                            "outcome_brief": self._brief(result),
                            "model_backed": getattr(step, "model_backed", False),
                            "envelope_unwrapped": (
                                self._last_tool_step_unwrapped
                                if isinstance(step, ToolCallStep)
                                else False
                            ),
                        },
                    )
                    if isinstance(step, (DecisionStep, SemanticBridgeStep)):
                        # LLM/model-backed steps are logged explicitly so
                        # script↔LLM segment iterations stay visible in the
                        # execution log stream.
                        await self._ship_log(
                            "script_model_backed_step",
                            f"Model-backed step '{step.name}' "
                            f"({step.kind.value}) executed",
                            {
                                "step_name": step.name,
                                "step_kind": step.kind.value,
                                "tool_name": step.tool_name,
                            },
                        )

            except ScriptExecutionError as exc:
                span.set_attribute("script.failed", True)
                span.set_attribute("script.failure", type(exc).__name__)
                await self._ship_log(
                    "script_run_failed",
                    f"Script '{graph.name}' failed at step "
                    f"'{getattr(current_step, 'name', '?')}': "
                    f"{type(exc).__name__}: {exc}",
                    {
                        "script_name": graph.name,
                        "script_version": script_version_label,
                        "failure_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    log_level="WARNING",
                )
                raise
            finally:
                context["__execution_telemetry__"] = {
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "tools_invoked": tools_invoked,
                    "model_backed_steps_used": model_backed_steps_used,
                }

            span.set_attribute("script.model_backed_steps", len(model_backed_steps_used))
            result = self._final_result(graph, context)
            await self._ship_log(
                "script_run_completed",
                f"Script '{graph.name}' completed in "
                f"{int((time.monotonic() - started) * 1000)} ms: {self._brief(result)}",
                {
                    "script_name": graph.name,
                    "script_version": script_version_label,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "outcome_brief": self._brief(result),
                    "tools_invoked": tools_invoked,
                    "model_backed_steps_used": model_backed_steps_used,
                },
            )
            # Attach execution telemetry to the returned payload so the
            # dispatch layer can report tools/model-backed usage (G2/G3).
            if isinstance(result, dict):
                result.setdefault("__execution_telemetry__", context["__execution_telemetry__"])
            return result

    # ── Step handlers ─────────────────────────────────────────────────────

    async def execute_python_source(
        self,
        source: str,
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None = None,
        caps: SandboxCaps | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a whole model-authored script (``ScriptVersion.python_source``)
        in the sandbox (N3) with the session's MCP-only client injected.

        Returns the script's result payload with ``__execution_telemetry__``
        attached (tools invoked through the facade, duration). Typed sandbox
        failures propagate for fallback classification (Flow C).
        """
        if not session_id or not agent_type_id:
            raise ExecutionError(
                "Script execution requires a session identity context "
                "(session_id and agent_type_id) — no anonymous identity path "
                "exists (SEC1)"
            )
        started = time.monotonic()
        await self._ship_log(
            "script_run_started",
            f"Sandboxed script started (version {script_version_label or 'n/a'})",
            {"script_version": script_version_label, "sandboxed": True},
        )
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.to_thread(
                run_sandboxed_python,
                source,
                tool_client=self._tool_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                script_version_label=script_version_label,
                input_context=initial_context,
                caps=caps,
                loop=loop,
            )
        except (SandboxViolationError, ResourceLimitExceededError) as exc:
            await self._ship_log(
                "script_run_failed",
                f"Sandboxed script failed: {exc}",
                {
                    "script_version": script_version_label,
                    "failure_type": type(exc).__name__,
                    "sandbox_violation_detail": str(exc),
                },
                log_level="WARNING",
            )
            raise
        except CommHubToolClientError as exc:
            # A failed MCP tool call inside the sandboxed script (e.g. a
            # malformed tool name → CH 404/502 "MCP tool not found") is a
            # script execution error — converted to the typed ExecutionError
            # so the fallback controller routes to the LLM path and the run
            # NEVER fails on the raw transport error (live defect).
            detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            await self._ship_log(
                "script_run_failed",
                f"Sandboxed script tool call failed: {detail}",
                {
                    "script_version": script_version_label,
                    "failure_type": "ExecutionError",
                    "error": detail,
                },
                log_level="WARNING",
            )
            raise ExecutionError(
                f"Tool call inside sandboxed script failed: {detail}"
            ) from exc
        telemetry = {
            "duration_ms": int((time.monotonic() - started) * 1000),
            "sandboxed": True,
        }
        if isinstance(result, dict):
            result.setdefault("__execution_telemetry__", telemetry)
        await self._ship_log(
            "script_run_completed",
            f"Sandboxed script completed in {telemetry['duration_ms']} ms: "
            f"{self._brief(result)}",
            {
                "script_version": script_version_label,
                "duration_ms": telemetry["duration_ms"],
                "outcome_brief": self._brief(result),
            },
        )
        return result

    async def _run_tool_step(
        self,
        step: ToolCallStep,
        context: dict[str, Any],
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None,
    ) -> Any:
        """Invoke a tool through CH — identical path to agent tool calls."""
        args = self._resolve_arguments(step.arguments, step.argument_templates, context)
        try:
            result = await self._tool_client.call_tool(
                step.tool_name,
                args,
                session_id=session_id,
                agent_type_id=agent_type_id,
                provenance="script",
                script_version=script_version_label,
            )
        except CommHubToolClientError as exc:
            detail = str(exc)
            if "permission" in detail.lower() or "403" in detail:
                # Permission rejection: the script attempted a tool the agent
                # identity is not permitted for — never widened, surfaces as
                # an execution error to the fallback controller (SEC2).
                raise ExecutionError(
                    f"Permission denied for tool '{step.tool_name}': {detail}"
                ) from exc
            raise ExecutionError(f"Tool call '{step.tool_name}' failed: {detail}") from exc

        # Unwrap the MCP content envelope before the result is stored into the
        # step's output_key: the script sees the parsed payload, never the
        # envelope (live-defect regression). isError → ExecutionError so the
        # fallback controller triggers.
        unwrapped_error = isinstance(result, dict) and result.get("isError")
        self._last_tool_step_raw_envelope = result
        result, unwrapped = unwrap_mcp_tool_result(result)
        if unwrapped and unwrapped_error:
            detail = result if isinstance(result, str) else json.dumps(result, default=str)
            raise ExecutionError(
                f"Tool '{step.tool_name}' reported an error: {detail[:300]}"
            )
        if unwrapped:
            logger.info(
                "Tool '%s' MCP content envelope unwrapped (payload type: %s)",
                step.tool_name,
                type(result).__name__,
            )
        self._last_tool_step_unwrapped = unwrapped
        self._validate_expected_keys(step, result)
        return result

    async def _run_decision_step(
        self,
        step: DecisionStep,
        context: dict[str, Any],
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None,
    ) -> Any:
        """System One decision step — structured result + confidence downstream (S1)."""
        args = self._resolve_arguments(step.arguments, step.argument_templates, context)
        try:
            result = await self._tool_client.call_tool(
                step.tool_name,
                args,
                session_id=session_id,
                agent_type_id=agent_type_id,
                provenance="script",
                script_version=script_version_label,
            )
        except CommHubToolClientError as exc:
            raise ExecutionError(f"Decision step '{step.name}' failed: {exc}") from exc
        if not isinstance(result, dict):
            raise OutputValidationFailure(
                f"Decision step '{step.name}' returned a non-structured result"
            )
        return result

    async def _run_semantic_bridge_step(
        self,
        step: SemanticBridgeStep,
        context: dict[str, Any],
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None,
    ) -> Any:
        """Semantic-bridge sub-agent step routed via CH (S1, S2)."""
        args: dict[str, Any] = {}
        if step.prompt_template:
            args["prompt"] = self._render_template(step.prompt_template, context)
        if step.input_key:
            args["input"] = context.get(step.input_key)
        try:
            return await self._tool_client.call_tool(
                step.tool_name,
                args,
                session_id=session_id,
                agent_type_id=agent_type_id,
                provenance="script",
                script_version=script_version_label,
            )
        except CommHubToolClientError as exc:
            raise ExecutionError(
                f"Semantic bridge step '{step.name}' failed: {exc}"
            ) from exc

    async def _run_script_segment_step(
        self,
        step: ScriptSegmentStep,
        context: dict[str, Any],
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None,
    ) -> Any:
        """Execute a model-authored sandboxed Python segment (N3).

        The segment's ONLY external binding is the session-bound tool client
        (injected as ``tools``) — MCP-only egress, identity parity (SEC1/E8).
        Sandbox violations and cap terminations surface as typed errors the
        fallback controller classifies (Flow C).
        """
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.to_thread(
                run_sandboxed_python,
                step.python_source,
                tool_client=self._tool_client,
                session_id=session_id,
                agent_type_id=agent_type_id,
                script_version_label=script_version_label,
                input_context=context,
                caps=SandboxCaps.from_version_fields(
                    step.cpu_limit_seconds,
                    step.memory_limit_mb,
                    step.wall_time_limit_seconds,
                ),
                loop=loop,
            )
        except (SandboxViolationError, ResourceLimitExceededError):
            # Typed, fail-closed — re-raised for fallback classification.
            raise
        except ScriptExecutionError:
            raise
        except Exception as exc:
            raise SandboxViolationError(
                f"Sandboxed segment '{step.name}' failed: {exc}"
            ) from exc
        return result

    def _run_transform_step(self, step: TransformStep, context: dict[str, Any]) -> Any:
        source = context.get(step.input_key) if step.input_key else None
        try:
            if step.op.value == "passthrough":
                return source
            if step.op.value == "select_keys":
                if not isinstance(source, dict):
                    raise OutputValidationFailure(
                        f"Transform '{step.name}' requires a dict input"
                    )
                return {k: source[k] for k in step.keys if k in source}
            if step.op.value == "json_path_get":
                return self._json_path_get(source, step.path or "")
            if step.op.value == "template":
                return self._render_template(step.template or "", context)
            if step.op.value == "constant":
                return step.value
            if step.op.value == "count":
                if isinstance(source, (list, dict, str)):
                    return len(source)
                raise OutputValidationFailure(
                    f"Transform '{step.name}' count requires an array or object input"
                )
            if step.op.value == "pluck":
                if not isinstance(source, list):
                    raise OutputValidationFailure(
                        f"Transform '{step.name}' pluck requires an array input"
                    )
                field = step.field or ""
                return [
                    item.get(field) for item in source if isinstance(item, dict) and field in item
                ]
            if step.op.value == "merge":
                other = context.get(step.input_key_b) if step.input_key_b else None
                if isinstance(source, dict) and isinstance(other, dict):
                    return {**source, **other}
                if isinstance(source, list) and isinstance(other, list):
                    return [*source, *other]
                raise OutputValidationFailure(
                    f"Transform '{step.name}' merge requires two arrays or two objects"
                )
            if step.op.value == "sum":
                if not isinstance(source, list):
                    raise OutputValidationFailure(
                        f"Transform '{step.name}' sum requires an array input"
                    )
                field = step.field or ""
                total = 0
                for item in source:
                    if isinstance(item, dict):
                        value = item.get(field)
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            total += value
                return total
            if step.op.value in ("first", "last"):
                if not isinstance(source, list):
                    raise OutputValidationFailure(
                        f"Transform '{step.name}' {step.op.value} requires an array input"
                    )
                if not source:
                    raise OutputValidationFailure(
                        f"Transform '{step.name}' {step.op.value} on empty array"
                    )
                return source[0] if step.op.value == "first" else source[-1]
        except ScriptExecutionError:
            raise
        except Exception as exc:  # malformed path/template etc.
            raise ExecutionError(f"Transform '{step.name}' failed: {exc}") from exc
        raise ExecutionError(f"Unknown transform op '{step.op}'")

    def _project_output(self, step: OutputStep, context: dict[str, Any]) -> Any:
        if step.select_keys:
            return {k: context[k] for k in step.select_keys if k in context}
        return context.get(step.output_key) if step.output_key in context else None

    def _final_result(self, graph: StepGraph, context: dict[str, Any]) -> Any:
        output_steps = [s for s in graph.steps if isinstance(s, OutputStep)]
        if output_steps:
            key = output_steps[-1].output_key
            if key in context:
                result = context[key]
                # Deterministic-template convention (compiler): the rendered
                # document IS the result — unwrap the single projection key
                # so a string render output stays a raw string end-to-end.
                if (
                    isinstance(result, dict)
                    and set(result.keys()) == {"render_output"}
                ):
                    return result["render_output"]
                return result
        return context.get("result")

    # ── Resolution & validation helpers ───────────────────────────────────

    def _resolve_arguments(
        self,
        arguments: dict[str, Any],
        templates: dict[str, str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = dict(arguments)
        for key, template in templates.items():
            match = _TEMPLATE_REF.fullmatch(template.strip())
            if not match:
                continue
            value = self._lookup_path(context, match.group(1))
            if value is not None:
                resolved[key] = value
        return resolved

    def _render_template(self, template: str, context: dict[str, Any]) -> str:
        def _substitute(match: re.Match[str]) -> str:
            value = self._lookup_path(context, match.group(1))
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                # Structured data renders as JSON — the requirement-driven
                # fallback template wraps the last tool step's output, and a
                # readable JSON block beats a Python repr in the document.
                return json.dumps(value, ensure_ascii=False, default=str)
            return str(value)

        return _TEMPLATE_REF.sub(_substitute, template)

    def _lookup_path(self, context: dict[str, Any], dotted: str) -> Any:
        parts = dotted.split(".")
        value: Any = context
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value

    def _json_path_get(self, source: Any, path: str) -> Any:
        if not path:
            return source
        return self._lookup_path(_nest(path, source), path)

    def _validate_expected_keys(self, step: ToolCallStep, result: Any) -> None:
        """Output validation: declared top-level keys must be present (F1)."""
        if not step.expected_output_keys:
            return
        if not isinstance(result, dict):
            raise OutputValidationFailure(
                f"Tool '{step.tool_name}' returned {type(result).__name__}; "
                "expected an object"
            )
        missing = [k for k in step.expected_output_keys if k not in result]
        if missing:
            raise SchemaMismatch(
                f"Tool '{step.tool_name}' result missing expected keys: {missing}"
            )


def _nest(path: str, source: Any) -> dict[str, Any]:
    """Nest ``source`` under a dotted path for _lookup_path traversal."""
    parts = path.split(".")
    nested: Any = source
    for part in reversed(parts[1:]):
        nested = {part: nested}
    return {parts[0]: nested}
