"""Agent Runtime — Script Tool Execution Endpoint.

Communication Hub forwards ``script____<name>`` virtual-tool invocations here
(top-priority rule: scripts execute ONLY in Agent Runtime). The endpoint
resolves the script by name for the session's agent type via the CC registry
(``ScriptRegistryClient.get_script_tool``), then executes the script's
``python_source`` (or declarative step graph) with a **session-bound** MCP-only
tool client — the SAME identity (mTLS cert + tenant headers) as the agent's
own tool calls (identity parity, SEC1). The script's ``tools.call(...)`` runs
on the agent's behalf, indistinguishable from the agent's own calls at the
permission layer.

Optimization verification (CC ``execute_script``) is REPLAY-ONLY: such a
request carries ``replay_required`` plus the recorded transcript, and the
script runs against ``ReplayToolClient`` — recorded responses only, no live
MCP call, no data mutation, and no fallback to the live client.

Route: POST /internal/script-tools/execute

Security:
    The global ``ControlCenterCertificateMiddleware`` (registered in
    ``agent_runtime/main.py``) validates that the inbound certificate is
    ``service:communication-hub`` before this handler runs — CH calls this
    endpoint with its own service certificate, exactly like the other AR
    ``/internal/...`` endpoints. The script itself runs under the session's
    agent identity via the AR agent-instance certificate (the same cert the
    agent's own tool calls use).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agent_runtime.scripts.cc_client import ScriptRegistryClient
from app.agent_runtime.scripts.dispatch import _session_bound_tool_client
from app.agent_runtime.scripts.runner import (
    ScriptExecutionError,
    ScriptRunner,
)
from app.agent_runtime.scripts.sandbox import (
    SandboxCaps,
    SandboxError,
    SandboxViolationError,
)
from app.agent_runtime.scripts.schemas import StepGraph

logger = logging.getLogger(__name__)

script_tools_router = APIRouter(
    prefix="/internal/script-tools", tags=["internal"]
)

#: Canonical virtual-tool prefix (mirrors Communication Hub's
#: ``SCRIPT_TOOL_PREFIX``); the suffix is the script definition name.
SCRIPT_TOOL_PREFIX = "script____"


class ScriptToolExecuteRequest(BaseModel):
    """Forwarded script-tool invocation from Communication Hub.

    Carries the session's agent identity (``session_id`` + ``agent_type_id``)
    so AR executes the sandbox with the same identity as the agent's own tool
    calls (SEC1 parity).

    Optimization verification is REPLAY-ONLY: with ``replay_required`` set,
    every ``tools.call`` is answered from ``reference_tool_responses`` (the
    recorded transcript of a real execution) and a miss fails the run — the
    live session-bound MCP client is never used.
    """

    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    session_id: str
    agent_type_id: str
    # Inline verification path (CC optimize-and-verify): when present, THIS
    # source executes directly in the sandbox — the CC script-registry lookup
    # is skipped entirely (there is no saved version yet). The normal
    # ``tool_name`` path is unchanged.
    python_source: str | None = None
    # Audit metadata: the LLM is the invoker of a script tool.
    provenance: str | None = None
    conv_session_id: str | None = None
    # Replay-only verification contract (optimization): recorded
    # ``{tool, arguments, response}`` entries + the hard replay switch.
    reference_tool_responses: list[dict[str, Any]] | None = None
    replay_required: bool = False


class ReplayToolClient:
    """Replay-only MCP tool client for optimization verification.

    Answers every ``call_tool`` from the recorded reference transcript — it
    NEVER performs a live MCP call (hard safety requirement: optimization may
    not mutate data). Matching prefers an unconsumed entry with the same tool
    AND the same arguments, then falls back to the next unconsumed entry with
    the same tool name (recorded arguments can legitimately differ slightly,
    e.g. server-side defaults).

    A miss raises ``SandboxViolationError`` with an explicit "no recorded
    response for tool X" message — the optimizer must use a tool call that the
    reference execution actually made (or stop with ``needs_feedback``).
    """

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries: list[dict[str, Any]] = [
            entry for entry in entries if isinstance(entry, dict)
        ]
        self._consumed: set[int] = set()
        #: Replayed calls (mirrors ``CommHubToolClient`` observability).
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _entry_tool(entry: dict[str, Any]) -> str | None:
        tool = entry.get("tool") or entry.get("tool_name")
        return str(tool) if tool else None

    @staticmethod
    def _entry_arguments(entry: dict[str, Any]) -> dict[str, Any]:
        arguments = entry.get("arguments")
        return arguments if isinstance(arguments, dict) else {}

    @staticmethod
    def _normalize_tool_name(name: str) -> str:
        """Normalize canonical/sanitized tool names for comparison.

        Older transcripts recorded provider-sanitized names
        (``mcp_demo__searchFlights``) while scripts call the canonical form
        (``mcp-demo____searchFlights``). Comparing the normalized forms keeps
        those references replayable without a live call.
        """
        return name.replace("-", "_").replace("____", "__")

    def _match_index(self, tool_name: str, arguments: dict[str, Any]) -> int | None:
        """First unconsumed exact match, else a normalized-name match."""
        wanted = self._normalize_tool_name(tool_name)
        # 1. Exact name + exact arguments.
        for index, entry in enumerate(self._entries):
            if index in self._consumed:
                continue
            if self._entry_tool(entry) != tool_name:
                continue
            if self._entry_arguments(entry) == arguments:
                return index
        # 2. Canonical/sanitized-equivalent name + exact arguments.
        for index, entry in enumerate(self._entries):
            if index in self._consumed:
                continue
            recorded = self._entry_tool(entry)
            if (
                recorded is not None
                and self._normalize_tool_name(recorded) == wanted
                and self._entry_arguments(entry) == arguments
            ):
                return index
        # 3. Exact name (arguments legitimately differ, e.g. defaults).
        for index, entry in enumerate(self._entries):
            if index in self._consumed:
                continue
            if self._entry_tool(entry) == tool_name:
                return index
        # 4. Canonical/sanitized-equivalent name.
        for index, entry in enumerate(self._entries):
            if index in self._consumed:
                continue
            recorded = self._entry_tool(entry)
            if recorded is not None and self._normalize_tool_name(recorded) == wanted:
                return index
        return None

    def _recorded_tool_names(self) -> list[str]:
        names = {
            tool
            for tool in (self._entry_tool(entry) for entry in self._entries)
            if tool
        }
        return sorted(names)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Return the recorded response for this call — never a live call."""
        args = dict(arguments or {})
        index = self._match_index(tool_name, args)
        if index is None:
            recorded = self._recorded_tool_names()
            detail = (
                f" (recorded tools: {', '.join(recorded)})" if recorded else ""
            )
            raise SandboxViolationError(
                f"No recorded response for tool '{tool_name}' in the reference "
                "execution — replay-only verification never calls live tools. "
                "Use a tool call that appears in the reference transcript, or "
                f"record a real execution that makes it{detail}."
            )
        self._consumed.add(index)
        entry = self._entries[index]
        self.calls.append(
            {
                "tool_name": tool_name,
                "arguments": args,
                "session_id": kwargs.get("session_id"),
                "agent_type_id": kwargs.get("agent_type_id"),
            }
        )
        return entry.get("response")


class ScriptToolExecuteResponse(BaseModel):
    """Result of a script-tool execution (CH ``call_tool`` contract shape).

    ``result`` holds the script's output; ``error`` is set (and ``result``
    empty) when the script failed — surfaced as a tool error, never a 502.
    """

    result: Any = None
    error: str | None = None


def _strip_telemetry(result: Any) -> Any:
    """Drop the internal ``__execution_telemetry__`` key from dict results."""
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if k != "__execution_telemetry__"}
    return result


@script_tools_router.post("/execute", response_model=ScriptToolExecuteResponse)
async def execute_script_tool(
    body: ScriptToolExecuteRequest,
    request: Request,
) -> ScriptToolExecuteResponse:
    """Resolve and execute a ``script____<name>`` tool on the agent's behalf."""
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    cert_loaded = cert_manager is not None and getattr(
        cert_manager, "is_loaded", False
    )
    if not cert_loaded and not body.replay_required:
        return ScriptToolExecuteResponse(
            error="Agent Runtime service certificate not loaded; cannot execute script tool"
        )

    if not body.tool_name.startswith(SCRIPT_TOOL_PREFIX):
        return ScriptToolExecuteResponse(
            error=f"Not a script tool: {body.tool_name!r}"
        )
    name = body.tool_name[len(SCRIPT_TOOL_PREFIX):]
    if not name:
        return ScriptToolExecuteResponse(
            error=f"Script tool name has no suffix: {body.tool_name!r}"
        )

    # Inline verification path: execute the submitted source directly —
    # no registry lookup (there is no saved version).
    inline_source = (body.python_source or "").strip() or None
    script: dict[str, Any] | None = None
    if inline_source is not None:
        python_source: str | None = inline_source
        graph_json: Any = None
        version_label: str | None = "inline"
        caps = SandboxCaps()
    else:
        registry_client = ScriptRegistryClient(cert_manager)
        try:
            script = await registry_client.get_script_tool(body.agent_type_id, name)
        except Exception as exc:  # noqa: BLE001 — fail closed to a tool error
            logger.warning(
                "Script tool lookup failed for %r (agent_type=%s): %s",
                body.tool_name, body.agent_type_id, exc,
            )
            return ScriptToolExecuteResponse(error=f"Script lookup failed: {exc}")

        if script is None:
            return ScriptToolExecuteResponse(
                error=f"Script tool '{name}' not found for agent type"
            )

        python_source = script.get("python_source")
        graph_json = script.get("declarative_step_graph")
        if python_source is None and graph_json is None:
            return ScriptToolExecuteResponse(
                error=f"Script tool '{name}' has no executable content"
            )
        version_label = script.get("script_version_label")
        caps = SandboxCaps.from_version_fields(
            script.get("cpu_limit_seconds"),
            script.get("memory_limit_mb"),
            script.get("wall_time_limit_seconds"),
        )

    # REPLAY-ONLY (optimization verification): answer every tools.call from the
    # recorded reference transcript — never the live session-bound client, and
    # never a fallback to live when the transcript is missing.
    if body.replay_required:
        recorded = body.reference_tool_responses or []
        if not recorded:
            return ScriptToolExecuteResponse(
                error=(
                    "Replay verification requires the reference execution's "
                    "recorded tool responses, and none were provided. Live tool "
                    "calls are never used for optimization verification."
                )
            )
        tool_client: Any = ReplayToolClient(recorded)
        logger.info(
            "Replay-only script verification (session=%s, recorded_calls=%d)",
            body.session_id,
            len(recorded),
        )
    else:
        # Session-bound MCP-only tool client (identity parity, SEC1): the
        # script's tools.call(...) uses the exact same mTLS cert + tenant
        # headers as the agent's own tool calls.
        tool_client = _session_bound_tool_client(cert_manager)
    # Execution-log shipper (observability): script-run start/step/completion
    # events are shipped to the Control Center execution log stream so
    # tool-mode script runs are as visible as dispatcher-served ones. The
    # data client may be absent (early startup) — logs are best-effort.
    # Conversational turns SKIP shipping entirely: execution_log_entries
    # only accepts AgentJob sessions (FK), and conversation sessions don't
    # need execution-log persistence.
    from app.agent_runtime.scripts.dispatch import _script_log_shipper

    data_client = getattr(request.app.state, "data_client", None)
    is_conversation_turn = bool(body.conv_session_id)
    log_shipper = (
        _script_log_shipper(data_client, body.session_id)
        if data_client is not None and not is_conversation_turn
        else None
    )
    runner = ScriptRunner(tool_client, log_shipper=log_shipper)
    if inline_source is not None:
        # CC verification sends ``{"input": {...}}`` — the input dict IS the
        # script's context (same semantics as the legacy CC inline path).
        raw_input = body.tool_args.get("input")
        initial_context = raw_input if isinstance(raw_input, dict) else body.tool_args
    else:
        initial_context = body.tool_args

    try:
        if python_source:
            result = await runner.execute_python_source(
                python_source,
                session_id=body.session_id,
                agent_type_id=body.agent_type_id,
                script_version_label=version_label,
                caps=caps,
                initial_context=initial_context,
            )
        else:
            graph = StepGraph.model_validate(graph_json)
            result = await runner.execute(
                graph,
                session_id=body.session_id,
                agent_type_id=body.agent_type_id,
                script_version_label=version_label,
                initial_context=body.tool_args,
            )
    except (ScriptExecutionError, SandboxError) as exc:
        logger.warning(
            "Script tool %r execution failed (session=%s): %s",
            body.tool_name, body.session_id, exc,
        )
        return ScriptToolExecuteResponse(error=str(exc))
    except Exception as exc:  # noqa: BLE001 — never let a script 500 the caller
        logger.exception("Script tool %r execution error", body.tool_name)
        return ScriptToolExecuteResponse(error=f"Script execution failed: {exc}")

    return ScriptToolExecuteResponse(result=_strip_telemetry(result))
