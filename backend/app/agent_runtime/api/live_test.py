"""Agent Runtime — approved optimization live-test runner (script run).

Route: ``POST /internal/live-test/run``

This is the single place where an operator-approved live test actually contacts
real integrations during optimization. It is reached only through
``CC → CH → AR`` after Control Center's ledger has consumed the approval
(single-use) and claimed the execution; neither Communication Hub nor Agent
Runtime can originate a live test, and nothing here is LLM-driven.

**A live test runs the SCRIPT end-to-end — never an individual MCP tool call.**
MCP tools are assumed to work; the point of the approval is to prove that the
whole script the optimizer wrote executes correctly against live systems. So
this handler executes the approved version's ``python_source`` exactly once in
the real sandbox with the **live** session-bound tool client (the same
``CommHubToolClient`` an agent's own tool calls use), and the script's own
``tools.call(...)`` is the only egress.

Hard guarantees enforced by this handler:

* **The approved script, once.** One sandbox execution of the approved
  source. No per-operation execution, no added/substituted calls, no retry.
* **The subject's own capability.** The script's statically extracted
  ``tools.call`` names are checked against the SUBJECT agent type's own granted
  tools (its context is fetched unscoped by ``agent_type_id`` only). If any is
  not permitted, the run fails before a single call is made — a permission
  denial starts no work. (Dynamic tool names cannot be previewed; they are
  still refused per call by the normal CH permission layer, which stops the
  run.)
* **The subject's own identity/tenant.** The sandbox tool client is the
  session-bound CH client with ``session_id``/``agent_type_id`` = the
  conversation and subject, so Communication Hub injects that agent's own
  identity per call. No override, no shared or elevated identity, no identity
  material in the payload.
* **Stop on first error.** A sandbox violation, resource-cap termination or
  denied/failed tool call ends the run; the ledger becomes ``failed``.
* **Bounded.** A hard per-run wall clock and the sandbox's own caps apply.
* **Auditable.** Each ``tools.call`` the script made is recorded as a
  ``RuntimeToolCall`` carrying ``optimization_live_test_request_id`` so live
  work is distinguishable from replay verification in the raw tool log.
* **Run record.** The response carries one script-run record (status, bounded
  result summary, per-call outcomes, telemetry, duration) — the ledger stores
  it as-is.

Security: the global ``ControlCenterCertificateMiddleware`` (AR main) accepts
only ``service:communication-hub`` on ``/internal/*``; CH calls this endpoint
with its own service certificate, exactly like the other AR internal routes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.agent_runtime.comm_hub_client import (
    CommHubToolClient,
    CommHubToolClientError,
)
from app.agent_runtime.scripts.runner import (
    ScriptExecutionError,
    ScriptRunner,
)
from app.agent_runtime.scripts.sandbox import (
    ResourceLimitExceededError,
    SandboxCaps,
    SandboxViolationError,
)
from app.services.agents.script_tool_names import extract_tools_call_names

logger = logging.getLogger(__name__)

live_test_router = APIRouter(prefix="/internal/live-test", tags=["internal"])

#: Structured error code returned when the script calls an out-of-grant tool.
ERROR_PERMISSION_DENIED = "live_test_permission_denied"
#: Structured error code returned when the run exceeds its wall clock.
ERROR_RUN_TIMEOUT = "live_test_run_timeout"
#: Structured error code returned when the approved script source is gone.
ERROR_SCRIPT_UNAVAILABLE = "live_test_script_unavailable"

#: Bounded result summary cap (the ledger keeps evidence, not payloads).
_RESULT_SUMMARY_LIMIT = 4000


class LiveTestRunRequest(BaseModel):
    """Forwarded, already-authorized live-test run (CC → CH → AR).

    ``python_source`` is the approved saved script version's own source — the
    unit of execution. The script's ``tools.call(...)`` lines are the only
    egress; no operation list is executed here.
    """

    live_test_request_id: str
    conversation_session_id: str
    target_agent_type_id: str
    script_version_id: str | None = None
    script_name: str | None = None
    script_version_label: str | None = None
    python_source: str = ""
    #: The reference execution's input (the same context replay uses), so the
    #: script runs the real scenario. State context only — never credentials.
    input_context: dict[str, Any] | None = None


class LiveTestRunResponse(BaseModel):
    """Evidence of one live-test run (one script-run record)."""

    status: str  # "executed" | "failed"
    #: Exactly one ``{kind: "script_run", …}`` entry describing the run.
    executed_operations: list[dict[str, Any]] = Field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


def _canonical_tool_name(name: str) -> str:
    """Canonicalize a tool identifier to ``server____tool`` where possible."""
    try:
        from app.services.agents.tool_naming import build_tool_name, parse_tool_name

        server_slug, bare = parse_tool_name(name)
        return build_tool_name(server_slug, bare)
    except Exception:  # noqa: BLE001 — unknown shapes stay verbatim
        return name


def _summarize_result(result: Any) -> str:
    """Compact, bounded rendering of one result (never secrets)."""
    try:
        text = json.dumps(result, default=str) if not isinstance(result, str) else result
    except (TypeError, ValueError):
        text = str(result)
    if len(text) > _RESULT_SUMMARY_LIMIT:
        return text[:_RESULT_SUMMARY_LIMIT] + "...(truncated)"
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveTestScriptToolClient:
    """Session-bound CH tool client, tagged as an approved live-test egress.

    Wraps the same client the agent's own script runs use (identity parity,
    SEC1) and forces ``provenance="live_test"`` so the call is not an LLM
    decision and is kept out of the authoring capture buffer. Nothing else is
    overridden: the script's own ``tools.call`` is the only egress.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def call_tool(
        self, tool_name: str, arguments: Any = None, **kwargs: Any
    ) -> Any:
        kwargs["provenance"] = "live_test"
        return await self._inner.call_tool(tool_name, arguments, **kwargs)


@live_test_router.post("/run", response_model=LiveTestRunResponse)
async def run_live_test(
    body: LiveTestRunRequest,
    request: Request,
) -> LiveTestRunResponse:
    """Run the approved script once, end to end, as the subject agent."""
    from app.core.config import get_settings

    settings = get_settings()
    run_timeout = float(
        max(10, int(getattr(settings, "optimizer_live_test_run_timeout_seconds", 120)))
    )

    started_at = _now_iso()
    started_monotonic = time.monotonic()
    script_version_id = body.script_version_id
    script_name = body.script_name
    script_version_label = body.script_version_label or body.script_version_id

    def _run_record(
        *,
        status: str,
        result_summary: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        telemetry: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "kind": "script_run",
            "script_version_id": script_version_id,
            "script_name": script_name,
            "script_version_label": script_version_label,
            "status": status,
            "result_summary": result_summary,
            "error": error,
            "duration_ms": int((time.monotonic() - started_monotonic) * 1000),
            "tool_calls": list(tool_calls or []),
            "telemetry": dict(telemetry or {}),
        }

    def _fail(
        error: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> LiveTestRunResponse:
        return LiveTestRunResponse(
            status="failed",
            executed_operations=[
                _run_record(
                    status="error",
                    result_summary=None,
                    tool_calls=tool_calls,
                    telemetry=telemetry,
                    error=error,
                )
            ],
            started_at=started_at,
            finished_at=_now_iso(),
            error=error,
        )

    try:
        conversation_session_id = str(uuid.UUID(body.conversation_session_id))
        target_agent_type_id = uuid.UUID(body.target_agent_type_id)
        live_test_request_id = str(uuid.UUID(body.live_test_request_id))
    except (ValueError, TypeError):
        return _fail("Malformed live-test run request")

    python_source = str(body.python_source or "").strip()
    if not python_source:
        return _fail(
            f"{ERROR_SCRIPT_UNAVAILABLE}: the approved script version has no "
            "source to run; nothing was executed"
        )

    data_client = getattr(request.app.state, "data_client", None)
    if data_client is None:
        return _fail("Agent Runtime data client is unavailable; nothing was executed")

    cert_manager = getattr(request.app.state, "certificate_manager", None)
    cert_loaded = cert_manager is not None and getattr(cert_manager, "is_loaded", False)
    if not cert_loaded:
        return _fail("Agent Runtime service certificate not loaded; nothing was executed")

    # ── 1. Capability: the SUBJECT's own grants (unscoped context) ───────────
    # The preview is the script's own literal ``tools.call`` set, so a script
    # that names a tool this agent was never granted starts no work at all.
    tool_preview = extract_tools_call_names(python_source)
    try:
        context = await data_client.get_agent_context(
            agent_type_id=target_agent_type_id,
            # Unscoped on purpose: this asks for the agent's BUSINESS grant
            # envelope (its own tools), not the optimization-mode turn tool set.
            conv_session_id=None,
        )
    except Exception as exc:  # noqa: BLE001 — fail closed, execute nothing
        logger.warning(
            "Live test %s: could not load the subject context: %s",
            live_test_request_id,
            exc,
        )
        return _fail("Could not resolve the subject agent type's capability; nothing was executed")

    allowed = {
        _canonical_tool_name(str(name))
        for name in (context.get("allowed_tools") or [])
    }
    if allowed:
        denied = [
            name
            for name in tool_preview
            if _canonical_tool_name(name) not in allowed
        ]
        if denied:
            logger.warning(
                "Live test %s refused before execution — script calls tool(s) not "
                "granted to agent type %s: %s",
                live_test_request_id,
                target_agent_type_id,
                denied,
            )
            return _fail(
                f"{ERROR_PERMISSION_DENIED}: this agent type has no grant for "
                f"{', '.join(sorted(set(denied)))}; nothing was executed"
            )

    # ── 2. Execute the approved SCRIPT once, end to end ─────────────────────
    # The same session-bound CH client the script-tool path builds (identity
    # parity, SEC1), tagged as an approved live-test egress.
    session_tool_client = CommHubToolClient()
    if cert_manager.cert_path and cert_manager.key_path:
        session_tool_client.set_certificate(
            str(cert_manager.cert_path), str(cert_manager.key_path)
        )
    tool_client = LiveTestScriptToolClient(session_tool_client)
    runner = ScriptRunner(tool_client)
    tool_calls: list[dict[str, Any]] = []
    initial_context = body.input_context if isinstance(body.input_context, dict) else {}

    try:
        result = await asyncio.wait_for(
            runner.execute_python_source(
                python_source,
                session_id=conversation_session_id,
                agent_type_id=str(target_agent_type_id),
                script_version_label=script_version_label,
                caps=SandboxCaps(),
                initial_context=initial_context,
                tool_calls_out=tool_calls,
            ),
            timeout=run_timeout,
        )
    except asyncio.TimeoutError:
        return _fail(
            f"{ERROR_RUN_TIMEOUT}: the script exceeded its {int(run_timeout)}s "
            "bound and was stopped; nothing else was attempted",
            tool_calls=_live_tool_call_records(tool_calls),
        )
    except (SandboxViolationError, ResourceLimitExceededError) as exc:
        logger.warning("Live test %s sandbox stop: %s", live_test_request_id, exc)
        return _fail(
            f"{type(exc).__name__}: {exc}",
            tool_calls=_live_tool_call_records(tool_calls),
        )
    except CommHubToolClientError as exc:
        return _fail(
            f"{_permission_prefix(exc)}script tool call failed: {exc}",
            tool_calls=_live_tool_call_records(tool_calls),
        )
    except ScriptExecutionError as exc:
        return _fail(
            str(exc),
            tool_calls=_live_tool_call_records(tool_calls),
        )
    except Exception as exc:  # noqa: BLE001 — one failed run ends the live test
        logger.exception("Live test %s script run failed", live_test_request_id)
        return _fail(
            f"Script execution failed: {exc}",
            tool_calls=_live_tool_call_records(tool_calls),
        )

    telemetry = (
        result.get("__execution_telemetry__") if isinstance(result, dict) else None
    )
    if not isinstance(telemetry, dict):
        telemetry = {}
    stripped_result = result
    if isinstance(result, dict):
        stripped_result = {
            key: value for key, value in result.items() if key != "__execution_telemetry__"
        }

    call_records = _live_tool_call_records(tool_calls)
    # Raw tool log: every ``tools.call`` the script made is flagged with the
    # ledger pointer, so live contact is distinguishable from replay work.
    for call in tool_calls:
        await _record_live_call(
            data_client,
            conversation_session_id=conversation_session_id,
            live_test_request_id=live_test_request_id,
            tool_name=str(call.get("tool_name") or ""),
            duration_ms=call.get("duration_ms"),
            error=call.get("error"),
        )

    logger.info(
        "Live test %s ran script %s (%s) once as agent type %s — %d tool call(s), "
        "%d ms",
        live_test_request_id,
        script_name or "?",
        script_version_id or "?",
        target_agent_type_id,
        len(tool_calls),
        int((time.monotonic() - started_monotonic) * 1000),
    )
    return LiveTestRunResponse(
        status="executed",
        executed_operations=[
            _run_record(
                status="success",
                result_summary=_summarize_result(stripped_result),
                tool_calls=call_records,
                telemetry=telemetry,
            )
        ],
        started_at=started_at,
        finished_at=_now_iso(),
        error=None,
    )


def _permission_prefix(exc: Exception) -> str:
    """Prefix a denial-shaped failure with the structured permission code."""
    detail = str(exc).lower()
    denied = any(
        marker in detail
        for marker in ("permission", "denied", "forbidden", "not authorized", "403")
    )
    return f"{ERROR_PERMISSION_DENIED}: " if denied else ""


def _live_tool_call_records(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-``tools.call`` outcomes for the ledger's script-run record."""
    records: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        records.append(
            {
                "tool_name": str(call.get("tool_name") or ""),
                "status": "error" if call.get("error") else "success",
                "duration_ms": call.get("duration_ms"),
                "result_summary": str(call.get("result_preview") or "") or None,
                "error": call.get("error"),
            }
        )
    return records


async def _record_live_call(
    data_client: Any,
    *,
    conversation_session_id: str,
    live_test_request_id: str,
    tool_name: str,
    duration_ms: int | None,
    error: str | None,
) -> None:
    """Flag the raw tool-log row as part of this approved live test (best effort)."""
    try:
        from app.services.agents.tool_naming import is_system_tool, parse_tool_name

        try:
            route = "system" if is_system_tool(tool_name) else "mcp"
            mcp_slug = parse_tool_name(tool_name)[0] if route == "mcp" else None
        except Exception:  # noqa: BLE001
            route, mcp_slug = "mcp", None
        await data_client.record_tool_call(
            session_id=uuid.UUID(conversation_session_id),
            session_kind="conversation",
            tool_name=tool_name,
            route_type=route,
            status="error" if error else "success",
            duration_ms=duration_ms,
            mcp_slug=mcp_slug,
            error=error,
            optimization_live_test_request_id=uuid.UUID(live_test_request_id),
        )
    except Exception as exc:  # noqa: BLE001 — recording must never break the run
        logger.warning(
            "Failed to record live tool call %s for live test %s: %s",
            tool_name,
            live_test_request_id,
            exc,
        )


__all__ = ["live_test_router", "LiveTestRunRequest", "LiveTestRunResponse"]
