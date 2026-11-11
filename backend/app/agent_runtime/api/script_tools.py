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
from app.agent_runtime.scripts.sandbox import SandboxCaps, SandboxError
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
    """

    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    session_id: str
    agent_type_id: str
    # Inline verification path (CC optimize-and-verify): when present, THIS
    # source executes directly in the sandbox with the session-bound tool
    # client — the CC script-registry lookup is skipped entirely (there is
    # no saved version yet). The normal ``tool_name`` path is unchanged.
    python_source: str | None = None
    # Audit metadata: the LLM is the invoker of a script tool.
    provenance: str | None = None
    conv_session_id: str | None = None


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
    if cert_manager is None or not getattr(cert_manager, "is_loaded", False):
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
    # no registry lookup (there is no saved version), session-bound identity.
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

    # Session-bound MCP-only tool client (identity parity, SEC1): the script's
    # tools.call(...) uses the exact same mTLS cert + tenant headers as the
    # agent's own tool calls.
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
