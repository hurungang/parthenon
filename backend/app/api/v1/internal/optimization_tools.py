"""Optimization system tools — CC-side handlers for the "Optimize & Verify" command.

These are the system tools the ``optimize-and-verify`` command makes available
to a command-driven special agent execution:

- ``get_implementation_plan`` — read the base (high-level) plan steps
- ``get_optimized_implementation_plan`` — read the current optimized plan
- ``generate_optimized_plan`` — upsert the optimized plan + associate scripts
- ``generate_script`` — sandbox-validate then save a draft script version
- ``execute_script`` — run FULL inline python_source (no save) or a saved
  script version's python_source in the REAL sandbox
- ``list_scripts`` / ``get_script`` — read authored scripts for reuse/repair

Each is exposed to agents through the existing SystemToolRegistry / CH tool
routing / LangChain-tool machinery (registered in ``system_tool_registry.py``;
routed by Communication Hub to the ``system____<name>`` endpoints below). All
endpoints require mTLS service-certificate auth + signed internal tenant
context, exactly like the other internal system tools.

    ``execute_script`` is the VERIFICATION primitive and it is REPLAY-ONLY:
    it never calls live MCP tools and never mutates data. It replays the exact
    reference input and the recorded tool responses of the selected execution
    (built from the execution log by ``_build_reference_transcript``).
    Segregation (top-priority rule): the sandbox executes ONLY in Agent
    Runtime — CC routes every execution (inline and saved) through
    ``CommunicationHubClient.forward_sandboxed_script`` (CC → CH
    ``/internal/script-tools/forward`` → AR ``/internal/script-tools/execute``
    — the CH→AR hop presents CH's own service certificate, identical to the
    ``script____<name>`` route), where AR runs the source in the real sandbox
    with its REPLAY tool client (recorded responses only, ``replay_required``).
    CC never imports or executes the sandbox (guarded by
    ``tests/api/v1/internal/test_execute_script_sandbox_segregation.py``).
"""
from __future__ import annotations

import ast
import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.models.agents import AgentPlan, AgentPlanStatus, AgentType
from app.db.models.optimized_plan import OptimizedImplementationPlan
from app.db.session import get_db
from app.services.agents.optimization_mode import require_subject_match

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/system-tools",
    tags=["Internal - Optimization Tools"],
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
)


class SystemToolRequest(BaseModel):
    """Request to execute an optimization system tool."""

    session_id: str
    agent_type_id: str | None = None
    tool_args: dict[str, Any]
    conversation_session_id: str | None = None


class SystemToolResponse(BaseModel):
    """Response from system tool execution."""

    result: dict[str, Any]


def _resolve_agent_type_id(body: SystemToolRequest) -> uuid.UUID | None:
    raw = body.tool_args.get("agent_type_id") or body.agent_type_id
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _parse_uuid(value: Any) -> uuid.UUID | None:
    """Parse a UUID-ish value, returning None instead of raising."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# ── Reference execution selection + replay transcript ───────────────────────
#
# Optimization verification is REPLAY-ONLY: ``execute_script`` never calls live
# MCP tools and never mutates data. It validates a script against the EXACT
# reference input and the recorded tool responses of a real (normal, completed)
# execution. Everything below derives that transcript from execution-log
# entries — no new table, no new column.

#: Log-entry window used to build a replay transcript. The whole reference
#: run's tool activity must be captured — a truncated window would silently
#: drop recorded responses a script needs.
REFERENCE_TRANSCRIPT_LOG_LIMIT = 500
#: Caps mirroring the execution-log capture (execution_logging_callback).
REFERENCE_INPUT_MAX_CHARS = 10_000
REFERENCE_OUTPUT_MAX_CHARS = 50_000


def _job_status(job: Any) -> str:
    """Normalise an AgentJob status to its string value."""
    return job.status.value if hasattr(job.status, "value") else str(job.status)


def _reference_input(input_data: Any) -> dict[str, Any] | None:
    """The execution's typed input, with internal routing keys stripped.

    Guessing or renaming input fields produces a script that verifies but
    fails at serving time — the reference input IS the script ``context``.
    """
    if not isinstance(input_data, dict):
        return None
    return {
        str(key): value
        for key, value in input_data.items()
        if not str(key).startswith("__")
    }


async def _recent_normal_jobs(
    db: AsyncSession,
    agent_type_id: uuid.UUID,
    current_session_id: uuid.UUID | None,
) -> list[Any]:
    """Recent NORMAL executions, newest first.

    Command (optimization side) runs and the current session are excluded: the
    optimizer must learn from a real reference run, never from its own
    in-flight command execution.
    """
    from app.db.models.agents import AgentJob

    jobs_result = await db.execute(
        select(AgentJob)
        .where(AgentJob.agent_type_id == agent_type_id)
        .order_by(AgentJob.created_at.desc())
        .limit(100)
    )
    normal_jobs: list[Any] = []
    for job in jobs_result.scalars().all():
        if current_session_id is not None and job.id == current_session_id:
            continue
        if isinstance(job.input_data, dict) and job.input_data.get("__command"):
            continue
        normal_jobs.append(job)
    return normal_jobs


def _select_reference_job(
    normal_jobs: list[Any],
    requested_session_id: uuid.UUID | None,
) -> tuple[Any | None, str]:
    """Pick the reference execution: explicit session, else latest completed.

    Returns ``(job, selection)`` where ``selection`` is one of
    ``explicit_session`` / ``explicit_session_not_found`` /
    ``latest_successful_execution`` / ``latest_execution_no_success`` / ``none``.
    """
    if requested_session_id is not None:
        selected = next(
            (j for j in normal_jobs if j.id == requested_session_id), None
        )
        return selected, (
            "explicit_session" if selected is not None else "explicit_session_not_found"
        )
    completed = [j for j in normal_jobs if _job_status(j) == "completed"]
    if completed:
        return completed[0], "latest_successful_execution"  # newest first
    if normal_jobs:
        return normal_jobs[0], "latest_execution_no_success"
    return None, "none"


def _coerce_jsonish(value: Any) -> Any:
    """Parse a JSON / Python-repr string payload; pass structured values through.

    Tool responses are logged as text. Replay must hand the script the actual
    payload (dict/list), not a string — otherwise ``payload['results']`` fails
    exactly like the flight-search ``str(dict)`` defect.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except ValueError:
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return value


def _coerce_arguments(raw: Any) -> dict[str, Any]:
    """Normalise recorded tool arguments to a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = _coerce_jsonish(raw)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _tool_calls_from_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Build the replayable ``tool_calls`` list from execution-log entries.

    Two sources, in preference order:

    1. ``script_tool_call`` events (a fully-scripted run): each carries the
       tool, the structured arguments and the full recorded ``result``.
    2. LLM-path pairs: ``tool_call`` (tool + arguments + ``run_id``) matched
       with its ``tool_response`` (``run_id`` + output), in call order.

    Returns ``(tool_calls, truncated)`` where every entry has the shape
    ``{"tool", "arguments", "response"}``.
    """
    script_calls: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("event_type") != "script_tool_call":
            continue
        data = entry.get("data") or {}
        tool = data.get("tool") or data.get("tool_name")
        if not tool:
            continue
        response = (
            data["result"]
            if "result" in data
            else _coerce_jsonish(data.get("result_preview"))
        )
        script_calls.append(
            {
                "tool": str(tool),
                "arguments": _coerce_arguments(data.get("arguments")),
                "response": response,
            }
        )
    if script_calls:
        return script_calls, False

    pending: list[dict[str, Any]] = []
    paired: list[tuple[int, dict[str, Any]]] = []
    truncated = False
    sequence = 0
    for entry in entries:
        event_type = entry.get("event_type")
        data = entry.get("data") or {}
        if event_type == "tool_call":
            tool = data.get("tool")
            if not tool:
                continue
            pending.append(
                {
                    "sequence": sequence,
                    "run_id": data.get("run_id"),
                    "tool": str(tool),
                    "arguments": _coerce_arguments(
                        data.get("arguments")
                        if data.get("arguments") is not None
                        else data.get("input")
                    ),
                }
            )
            sequence += 1
            raw_input = data.get("input")
            if data.get("input_truncated") or (
                isinstance(raw_input, str)
                and len(raw_input) >= REFERENCE_INPUT_MAX_CHARS
            ):
                truncated = True
        elif event_type == "tool_response":
            run_id = data.get("run_id")
            if run_id:
                index = next(
                    (i for i, call in enumerate(pending) if call["run_id"] == run_id),
                    None,
                )
            else:
                index = 0 if pending else None
            if index is None:
                continue
            call = pending.pop(index)
            if data.get("output_truncated") or (
                isinstance(data.get("output"), str)
                and len(data["output"]) >= REFERENCE_OUTPUT_MAX_CHARS
            ):
                truncated = True
            paired.append(
                (
                    call["sequence"],
                    {
                        "tool": call["tool"],
                        "arguments": call["arguments"],
                        "response": _coerce_jsonish(data.get("output")),
                    },
                )
            )
    paired.sort(key=lambda item: item[0])
    return [call for _, call in paired], truncated


async def _build_reference_transcript(
    db: AsyncSession,
    agent_type_id: uuid.UUID,
    *,
    session_id: uuid.UUID | None = None,
    current_session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Build the REPLAY transcript of one reference execution.

    Returns ``{session_id, input, input_schema, tool_calls, truncated}`` where
    ``tool_calls`` entries are ``{tool, arguments, response}``. An empty
    ``tool_calls`` list means replay verification is impossible (nothing was
    recorded) — the caller must NOT execute.
    """
    from app.db.models.session_logs import ExecutionLogEntry

    agent_type = await db.get(AgentType, agent_type_id)
    input_schema = (
        agent_type.input_schema
        if agent_type is not None and isinstance(agent_type.input_schema, dict)
        else None
    )

    normal_jobs = await _recent_normal_jobs(db, agent_type_id, current_session_id)
    selected, _selection = _select_reference_job(normal_jobs, session_id)

    transcript: dict[str, Any] = {
        "session_id": str(selected.id) if selected is not None else None,
        "input": _reference_input(selected.input_data) if selected is not None else None,
        "input_schema": input_schema,
        "tool_calls": [],
        "truncated": False,
    }
    if selected is None:
        return transcript

    # Newest-first DB window (one extra row detects a truncated window), then
    # reverse for chronological replay order.
    rows = await db.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == selected.id)
        .order_by(ExecutionLogEntry.timestamp.desc())
        .limit(REFERENCE_TRANSCRIPT_LOG_LIMIT + 1)
    )
    ordered = list(rows.scalars().all())
    window_truncated = len(ordered) > REFERENCE_TRANSCRIPT_LOG_LIMIT
    if window_truncated:
        ordered = ordered[:REFERENCE_TRANSCRIPT_LOG_LIMIT]
    ordered.reverse()

    entries = [
        {
            "event_type": entry.event_type,
            "message": entry.message,
            "data": entry.data if isinstance(entry.data, dict) else {},
        }
        for entry in ordered
    ]
    tool_calls, truncated = _tool_calls_from_entries(entries)
    transcript["tool_calls"] = tool_calls
    transcript["truncated"] = bool(window_truncated or truncated)
    return transcript


# ── Authoring-time tool-name validation (live-defect regression) ─────────────


def extract_tools_call_names(python_source: str) -> list[str]:
    """Return the literal tool names from ``tools.call('<name>', ...)`` calls.

    Only constant-string first arguments are collected (dynamic names cannot
    be validated at authoring time). The AST walk lives in the neutral
    ``app.services.agents.script_tool_names`` module so the Agent Runtime
    live-test runner can reuse it without importing a Control Center API
    module (three-service segregation).
    """
    from app.services.agents.script_tool_names import extract_tools_call_names as _extract

    return _extract(python_source)


async def _allowed_tool_names_for_agent(
    db: AsyncSession, agent_type_id: uuid.UUID
) -> set[str]:
    """Resolve the agent's ACTUAL allowed MCP tool names.

    Mirrors the agent-context permission resolution: visibility from the
    agent type's own bindings, permission gated by the role grants.
    """
    from app.db.models.agents import (
        AgentType,
    )
    from app.services.agents.permission_manager import AgentPermissionManager

    agent_type = await db.get(AgentType, agent_type_id)
    if agent_type is None or not agent_type.role_id:
        return set()

    # Agent-type-scoped resolution: visibility from the agent type's own
    # bindings, permission gated by the role grants. LEGACY FALLBACK: agent
    # types with no own bindings (role-only, pre-visibility-model configs)
    # validate against the ROLE's granted tools — script tool-name
    # validation must never silently degrade to no scope.
    manager = AgentPermissionManager()
    allowed = await manager.calculate_agent_allowed_tools(agent_type_id, db)
    if allowed:
        return allowed
    if agent_type is not None and agent_type.role_id:
        return await manager.calculate_allowed_tools(agent_type.role_id, db)
    return set()


async def _validate_script_tool_names(
    db: AsyncSession, agent_type_id: uuid.UUID | None, python_source: str
) -> dict[str, Any] | None:
    """Check every literal ``tools.call('name', ...)`` against the agent's
    allowed tool names. Returns a structured validation-error payload (with
    the valid names, so the authoring LLM can repair the source in its next
    iteration) or ``None`` when the source is clean / not validatable."""
    called = extract_tools_call_names(python_source)
    if not called:
        return None
    allowed = await _allowed_tool_names_for_agent(db, agent_type_id)
    if not allowed:
        return None  # no resolvable permission scope — nothing to check against
    invalid = sorted({name for name in called if name not in allowed})
    if not invalid:
        return None
    return {
        "status": "validation_error",
        "error": (
            "Unknown MCP tool name(s) in python_source: "
            f"{', '.join(invalid)}. Tool names must be used EXACTLY as "
            "listed for this agent (four-underscore separator `____` "
            "between server slug and tool name). Re-run with a corrected "
            "python_source."
        ),
        "invalid_tool_names": invalid,
        "valid_tool_names": sorted(allowed),
    }


async def _validate_script_input_context(
    db: AsyncSession,
    agent_type_id: uuid.UUID | None,
    input_context: dict[str, Any],
) -> dict[str, Any] | None:
    """Validate ``execute_script`` input against the agent's typed input schema.

    A script authored against guessed/renamed input keys (e.g. ``date``
    instead of ``travel_date``) verifies against the wrong context and then
    fails at serving time. Return a structured validation error listing the
    missing required keys so the optimizer repairs the context (and the
    script) instead of persisting a plan that cannot serve real input.
    """
    if agent_type_id is None:
        return None
    from app.db.models.agents import AgentType

    agent_type = await db.get(AgentType, agent_type_id)
    schema = getattr(agent_type, "input_schema", None) if agent_type else None
    if not isinstance(schema, dict):
        return None
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    if not isinstance(required, list) or not required:
        return None
    missing = [str(key) for key in required if key not in input_context]
    if not missing:
        return None
    return {
        "status": "validation_error",
        "error": (
            "Script input is missing the agent's required typed input key(s): "
            f"{', '.join(missing)}. Use the agent's exact input keys / the "
            "reference `input` returned by `get_execution_log`; never invent "
            "or rename input fields."
        ),
        "missing_input_keys": missing,
        "required_input_keys": [str(key) for key in required],
        "valid_input_keys": [str(key) for key in properties.keys()],
    }


# ── get_implementation_plan ──────────────────────────────────────────────────


@router.post("/get-implementation-plan", response_model=SystemToolResponse)
async def get_implementation_plan_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Return the base (high-level) implementation plan steps for an agent type."""
    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")
    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    result = await db.execute(
        select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
    )
    plan = result.scalar_one_or_none()
    auto_generated = False
    # Optimization needs a base implementation plan to work from. When the
    # agent has none (or only a failed/empty one), generate it now with the
    # workspace authoring model — before the optimizer authors anything — so
    # the run never dead-ends on "No base implementation plan exists".
    if (
        plan is None
        or plan.generation_status != AgentPlanStatus.success
        or not (plan.plan_steps or [])
    ):
        from app.services.agents.plan_generation_service import PlanGenerationService

        agent_type = await db.get(AgentType, agent_type_id)
        if agent_type is None:
            raise HTTPException(status_code=404, detail="Agent type not found")
        try:
            generated = await PlanGenerationService().generate_plan(agent_type, db)
        except Exception as exc:  # noqa: BLE001 — surfaced as an ask, not a 500
            logger.warning(
                "Base plan auto-generation failed for agent_type=%s: %s",
                agent_type_id,
                exc,
            )
            return SystemToolResponse(
                result={
                    "status": "needs_user_input",
                    "blockers": ["base_plan_unavailable"],
                    "agent_type_id": str(agent_type_id),
                    "steps": [],
                    "error": (
                        "I couldn't generate the base implementation plan for "
                        f"this agent: {exc}. Generate the implementation plan "
                        "from the Plan Preview, then retry optimization."
                    ),
                }
            )
        if (
            generated.generation_status != AgentPlanStatus.success
            or not (generated.plan_steps or [])
        ):
            return SystemToolResponse(
                result={
                    "status": "needs_user_input",
                    "blockers": ["base_plan_generation_failed"],
                    "agent_type_id": str(agent_type_id),
                    "steps": [],
                    "error": (
                        generated.error
                        or "Base implementation plan generation failed."
                    ),
                }
            )
        plan = generated
        auto_generated = True

    return SystemToolResponse(
        result={
            "agent_type_id": str(agent_type_id),
            "agent_plan_id": str(plan.id) if plan else None,
            "steps": (plan.plan_steps or []) if plan else [],
            "auto_generated": auto_generated,
        }
    )


# ── get_optimized_implementation_plan ────────────────────────────────────────


@router.post("/get-optimized-implementation-plan", response_model=SystemToolResponse)
async def get_optimized_implementation_plan_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Return the current optimized plan (steps, scripts, verification log)."""
    from app.services.agents.optimized_plan_service import OptimizedPlanService

    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")
    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    service = OptimizedPlanService()
    optimized = await service.get_latest_optimized_plan(db, agent_type_id)
    if optimized is None:
        return SystemToolResponse(
            result={"agent_type_id": str(agent_type_id), "found": False}
        )
    return SystemToolResponse(
        result=_optimized_plan_result(optimized)
    )


# ── generate_optimized_plan ──────────────────────────────────────────────────


@router.post("/generate-optimized-plan", response_model=SystemToolResponse)
async def generate_optimized_plan_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Upsert the optimized plan and associate/promote the authored scripts."""
    from app.db.models.optimized_plan import OptimizedPlanStatus
    from app.services.agents.optimized_plan_service import OptimizedPlanService

    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")
    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    result = await db.execute(select(AgentType).where(AgentType.id == agent_type_id))
    agent_type = result.scalar_one_or_none()
    if agent_type is None:
        raise HTTPException(status_code=404, detail="Agent type not found")

    base_result = await db.execute(
        select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
    )
    base_plan = base_result.scalar_one_or_none()
    if base_plan is None:
        raise HTTPException(status_code=409, detail="No base implementation plan exists")

    steps = body.tool_args.get("steps") or []
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="steps must be a list")

    fully_scripted = bool(body.tool_args.get("fully_scripted", False))
    output_mode = body.tool_args.get("output_mode")
    output_template = body.tool_args.get("output_template")
    raw_status = body.tool_args.get("status") or "ready"
    failure_error = body.tool_args.get("error") or None

    # Authoring may only persist a terminal authoring status. `requires_fix` is
    # set exclusively by the execution-fallback path, so an explicit allow-list
    # prevents a caller from writing it directly through this tool.
    if str(raw_status) not in {"ready", "failed", "needs_feedback"}:
        return SystemToolResponse(
            result={
                "status": "validation_error",
                "error": (
                    f"Invalid optimized-plan status '{raw_status}'. The "
                    "authoring tool may only persist 'ready', 'failed', or "
                    "'needs_feedback'; 'requires_fix' is set only by an "
                    "execution fallback."
                ),
            }
        )

    service = OptimizedPlanService()
    optimized = await service.generate_optimized_plan(
        db,
        agent_type=agent_type,
        base_plan=base_plan,
        steps=steps,
        fully_scripted=fully_scripted,
        output_mode=output_mode,
        output_template=output_template,
        status=OptimizedPlanStatus(str(raw_status)),
        error=failure_error,
    )
    await db.commit()
    reloaded = await db.get(OptimizedImplementationPlan, optimized.id)
    result_payload = _optimized_plan_result(reloaded)
    if str(raw_status) == "needs_feedback":
        # Bounded stop: the conversation ends this turn with a readable,
        # machine-checkable outcome instead of a retry loop. The plan's `error`
        # is the single source of "what is missing"; these are the operator's
        # next actions.
        result_payload["stop"] = {
            "outcome": "needs_feedback",
            "missing": failure_error,
            "next_actions": [
                "answer_or_steer",
                "request_one_live_test",
                "keep_current_plan",
            ],
            "retry_recommended": False,
        }
    return SystemToolResponse(result=result_payload)


# ── generate_script ──────────────────────────────────────────────────────────


@router.post("/generate-script", response_model=SystemToolResponse)
async def generate_script_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Sandbox-compile validate then save a draft script version; return version id.

    Rejects ``SandboxCompileError`` with the reason (the agent retries with a
    fixed source). The version starts at ``draft``; ``generate_optimized_plan``
    promotes it to ``compiled`` once the whole composition is verified.
    """
    from app.agent_runtime.scripts.compiler import ScriptValidator
    from app.db.models.script_registry import SandboxValidationStatus
    from app.services.script_registry import ScriptRegistryService

    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")

    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    name = str(body.tool_args.get("name") or "").strip()
    description = str(body.tool_args.get("description") or "") or None
    python_source = body.tool_args.get("python_source")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not isinstance(python_source, str) or not python_source.strip():
        raise HTTPException(status_code=400, detail="python_source is required")

    # Sandbox-validation (N3): RestrictedPython compile check + AST safety scan
    # (no imports, no I/O, no secret-shaped strings). Unsafe/broken source stays
    # draft with a recorded reason.
    validation = ScriptValidator().validate(python_source)
    if validation.status.value == "passed":
        validation_status = SandboxValidationStatus.passed
        validation_reason = None
    else:
        validation_status = SandboxValidationStatus.failed
        validation_reason = validation.reason

    # Authoring-time tool-name validation (BEFORE persisting a version): a
    # malformed tool name is a structured validation error listing the valid
    # names — no draft version is created for a source that cannot run.
    tool_name_error = await _validate_script_tool_names(
        db, agent_type_id, python_source
    )
    if tool_name_error is not None:
        return SystemToolResponse(result=tool_name_error)

    service = ScriptRegistryService()
    definition = await service.get_definition_by_name_and_agent_type(
        db, name=name, agent_type_id=agent_type_id, tenant_id=tenant_ctx.tenant_id
    )
    if definition is None:
        definition = await service.create_definition(
            db,
            name=name,
            agent_type_id=agent_type_id,
            tenant_id=tenant_ctx.tenant_id,
            description=description,
        )

    version = await service.create_version(
        db,
        definition_id=definition.id,
        declarative_step_graph=None,
        python_source=python_source,
        sandbox_validation_status=validation_status,
        sandbox_validation_reason=validation_reason,
        created_by="optimize-and-verify-command",
        tenant_id=tenant_ctx.tenant_id,
    )
    await db.commit()

    if validation_status == SandboxValidationStatus.failed:
        return SystemToolResponse(
            result={
                "version_id": str(version.id),
                "definition_id": str(definition.id),
                "name": name,
                "status": "failed",
                "reason": validation_reason,
            }
        )
    return SystemToolResponse(
        result={
            "version_id": str(version.id),
            "definition_id": str(definition.id),
            "name": name,
            "status": "draft",
        }
    )


# ── execute_script ───────────────────────────────────────────────────────────


@router.post("/execute-script", response_model=SystemToolResponse)
async def execute_script_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Validate a script by REPLAYING the reference execution (verify).

    **Replay only.** This tool NEVER calls live MCP tools and NEVER mutates
    data. It replays the EXACT reference input and the recorded tool responses
    of the selected execution (see ``get_execution_log``) inside the REAL
    sandbox — so a script can no longer "pass" verification against live data
    and then fail at serving time on a different payload shape.

    Two paths — BOTH execute in Agent Runtime via the CC→CH→AR internal-call
    mechanism (the sandbox never runs in the CC process) with AR's replay tool
    client:
    - **inline** (preferred by the optimize-and-verify command): pass the FULL
      ``python_source`` — executed directly, NO save required. The agent keeps
      the source in its own context and iterates by passing modified source.
    - **saved**: pass ``script_version_id`` — the persisted version's source
      is forwarded to AR.

    The reference execution is the latest successful NORMAL execution, or the
    one named by ``reference_session_id`` in the tool args. With no recorded
    tool data there is nothing to replay: a structured ``validation_error`` is
    returned and the script is NOT executed.

    Returns ``{"output": <result>}`` on success, or ``{"error": <reason>}`` on
    a sandbox compile/violation/resource-cap failure or a replay miss (a tool
    call with no recorded response); AR's structured error is surfaced as-is.
    """
    from app.services.control_center.comm_hub_client import (
        CommunicationHubClient,
        CommunicationHubClientError,
    )
    from app.services.script_registry import ScriptRegistryService

    explicit_input = body.tool_args.get("input")
    if not isinstance(explicit_input, dict):
        explicit_input = {}

    agent_type_id = _resolve_agent_type_id(body)

    # Subject guard BEFORE any source/registry read when the subject is known:
    # an out-of-scope call must be refused consistently even when the source
    # argument is missing (otherwise a 400 would mask the scope refusal).
    if agent_type_id is not None:
        out_of_scope = await require_subject_match(
            db, body.conversation_session_id, agent_type_id
        )
        if out_of_scope is not None:
            return SystemToolResponse(result=out_of_scope)

    # ── Resolve the source to verify (inline or a saved version) ────────────
    raw_source = body.tool_args.get("python_source")
    is_inline = isinstance(raw_source, str) and bool(raw_source.strip())
    service = ScriptRegistryService()
    if is_inline:
        python_source = str(raw_source)
    else:
        raw_version_id = body.tool_args.get("script_version_id")
        if not raw_version_id:
            raise HTTPException(
                status_code=400,
                detail="python_source or script_version_id is required",
            )
        try:
            version_id = uuid.UUID(str(raw_version_id))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid script_version_id")

        version = await service.get_version(db, version_id, tenant_ctx.tenant_id)
        if version is None:
            raise HTTPException(status_code=404, detail="Script version not found")
        if not version.python_source:
            raise HTTPException(
                status_code=422,
                detail="Script version has no python_source to execute",
            )
        python_source = version.python_source
        if agent_type_id is None and version.script_definition_id:
            # Saved-version callers may omit the agent type: the registry
            # definition already knows which agent the script belongs to.
            definition = await service.get_definition(
                db, version.script_definition_id, tenant_ctx.tenant_id
            )
            if definition is not None and definition.agent_type_id:
                agent_type_id = definition.agent_type_id

    if agent_type_id is None:
        raise HTTPException(
            status_code=400,
            detail="agent_type_id is required to resolve the reference execution",
        )

    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    # ── Resolve the reference execution + its REPLAY transcript ─────────────
    # Without recorded tool data a replay is impossible — never fall back live.
    transcript = await _build_reference_transcript(
        db,
        agent_type_id,
        session_id=_parse_uuid(body.tool_args.get("reference_session_id")),
        current_session_id=_parse_uuid(body.session_id),
    )
    reference_tool_calls: list[dict[str, Any]] = transcript["tool_calls"]
    if not reference_tool_calls:
        # TERMINAL for the optimizer: there is nothing to replay. Do not let the
        # model loop on retries — it must stop and ask the user for a real run.
        return SystemToolResponse(
            result={
                "status": "needs_user_input",
                "blockers": ["no_reference_tool_data"],
                "error": (
                    "I can't verify this script: the reference execution recorded "
                    "no tool calls. Verification is replay-only and never calls "
                    "live tools. Run the agent once with a real scenario (at least "
                    "one tool call), then re-optimize — or tell me which scenario "
                    "to use."
                ),
                "reference_session_id": transcript.get("session_id"),
                "tool_calls": [],
                # Bounded stop: at most one decision point, never a retry loop
                # to force a match (and never a live call on this path).
                "stop": {
                    "outcome": "needs_feedback",
                    "missing": "no recorded tool calls in the reference execution",
                    "next_actions": [
                        "answer_or_steer",
                        "request_one_live_test",
                        "keep_current_plan",
                    ],
                    "retry_recommended": False,
                },
            }
        )

    # The reference input is the script's ``context``: replay must use the real
    # payload, never a re-typed one. A caller-supplied context is still
    # schema-validated so guessed/renamed keys are rejected up front.
    reference_input = transcript.get("input")
    if not isinstance(reference_input, dict):
        reference_input = {}
    for candidate in (explicit_input, reference_input):
        if not candidate:
            continue
        input_validation_error = await _validate_script_input_context(
            db, agent_type_id, candidate
        )
        if input_validation_error is not None:
            return SystemToolResponse(result=input_validation_error)
    input_context = reference_input or explicit_input

    if is_inline:
        # Authoring-time tool-name validation: a malformed tool name (e.g. a
        # two-underscore separator typo) is a STRUCTURED validation error
        # listing the valid names — the LLM repairs it in its next iteration
        # instead of the script failing at serving time.
        validation_error = await _validate_script_tool_names(
            db, agent_type_id, python_source
        )
        if validation_error is not None:
            return SystemToolResponse(result=validation_error)

    # ── Forward to AR: REPLAY ONLY ──────────────────────────────────────────
    try:
        ar_resp = await CommunicationHubClient().forward_sandboxed_script(
            python_source=python_source,
            session_id=body.session_id,
            agent_type_id=str(agent_type_id),
            input_context=input_context,
            tenant_context=tenant_ctx,
            # REPLAY-ONLY (hard safety requirement): AR must never reach the
            # live session-bound MCP client for optimization runs.
            reference_tool_responses=reference_tool_calls,
            replay_required=True,
        )
    except CommunicationHubClientError as exc:
        return SystemToolResponse(
            result={"error": f"Agent Runtime script execution failed: {exc}"}
        )
    if ar_resp.get("error"):
        error_text = str(ar_resp["error"])
        # A replay miss means the script needs a tool/response the reference
        # run never recorded. That is a TERMINAL "ask the user" condition — not
        # a retryable error (retrying can never make the recorded data appear).
        if "No recorded response" in error_text:
            return SystemToolResponse(
                result={
                    "status": "needs_user_input",
                    "blockers": ["reference_transcript_incomplete"],
                    "error": error_text,
                    "message": (
                        "The script calls a tool/response the reference execution "
                        "did not record. Verification is replay-only. Either use "
                        "only the recorded workflow, or ask the user to run the "
                        "agent once with the scenario that exercises this tool, "
                        "then re-optimize."
                    ),
                    "recorded_tools": [
                        str(call.get("tool")) for call in reference_tool_calls
                    ],
                    "reference_session_id": transcript.get("session_id"),
                    # Bounded stop (see the no-reference branch above).
                    "stop": {
                        "outcome": "needs_feedback",
                        "missing": (
                            "the script needs a tool/response the reference "
                            "execution did not record"
                        ),
                        "next_actions": [
                            "answer_or_steer",
                            "request_one_live_test",
                            "keep_current_plan",
                        ],
                        "retry_recommended": False,
                    },
                }
            )
        return SystemToolResponse(result={"error": error_text})
    return SystemToolResponse(
        result={
            "output": ar_resp.get("result"),
            "replayed": True,
            "reference_session_id": transcript.get("session_id"),
            "transcript_truncated": transcript["truncated"],
        }
    )


# ── list_scripts / get_script ────────────────────────────────────────────────


def _script_payload(definition: Any, version: Any) -> dict[str, Any]:
    return {
        "definition_id": str(definition.id),
        "name": definition.name,
        "description": definition.description,
        "lifecycle_status": (
            version.lifecycle_status.value if version else None
        ),
        "version_id": str(version.id) if version else None,
        "version_label": version.version_label if version else None,
        "python_source": version.python_source if version else None,
        "sandbox_validation_status": (
            version.sandbox_validation_status.value if version else None
        ),
        "sandbox_validation_reason": (
            version.sandbox_validation_reason if version else None
        ),
    }


async def _latest_version(db: AsyncSession, definition: Any, service: Any) -> Any:
    """Return the most recent version for a definition (draft or otherwise)."""
    versions = await service.list_versions(db, definition.id)
    return versions[-1] if versions else None


async def _list_scripts_impl(
    db: AsyncSession, tenant_ctx: TenantContext, agent_type_id: uuid.UUID
) -> dict[str, Any]:
    """Shared implementation for list_scripts / get_scripts."""
    from app.services.script_registry import ScriptRegistryService

    service = ScriptRegistryService()
    definitions = await service.list_definitions(
        db, tenant_id=tenant_ctx.tenant_id, agent_type_id=agent_type_id
    )
    items: list[dict[str, Any]] = []
    for definition in definitions:
        current = await _latest_version(db, definition, service)
        items.append(_script_payload(definition, current))
    return {"scripts": items}


async def _run_list_scripts(
    body: SystemToolRequest,
    tenant_ctx: TenantContext,
    db: AsyncSession,
) -> SystemToolResponse:
    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")
    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)
    return SystemToolResponse(
        result=await _list_scripts_impl(db, tenant_ctx, agent_type_id)
    )


@router.post("/list-scripts", response_model=SystemToolResponse)
async def list_scripts_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """List authored script definitions + current version for an agent type."""
    return await _run_list_scripts(body, tenant_ctx, db)


@router.post("/get-scripts", response_model=SystemToolResponse)
async def get_scripts_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Self-reflection tool: read the agent's OWN script definitions —
    versions, python_source, sandbox validation and lifecycle — so the
    optimization run can assess the current state before (re-)authoring."""
    return await _run_list_scripts(body, tenant_ctx, db)


@router.post("/get-execution-log", response_model=SystemToolResponse)
async def get_execution_log_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Self-reflection tool: list the agent's recent executions and return the
    TEXT LOG of the latest successful (completed) NORMAL execution.

    The current optimization session is excluded — the optimizer must learn
    from a real reference run, not from its own in-flight command run. A
    command run (``__command`` marker) is never a reference execution. Pass
    ``session_id`` to read a specific execution's log.

    The result also carries the REPLAY transcript (``tool_calls``: recorded
    tool name + arguments + response) of the selected execution — this is what
    ``execute_script`` replays during verification.
    """
    from app.db.models.agents import AgentType
    from app.db.models.session_logs import ExecutionLogEntry

    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")
    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    # `limit` caps the log lines of the SELECTED execution (default 100,
    # max 500); `executions_limit` caps the recent-execution list.
    raw_limit = body.tool_args.get("limit")
    try:
        log_limit = min(max(int(raw_limit), 1), 500) if raw_limit else 100
    except (ValueError, TypeError):
        log_limit = 100

    raw_exec_limit = body.tool_args.get("executions_limit")
    try:
        executions_limit = (
            min(max(int(raw_exec_limit), 1), 50) if raw_exec_limit else 10
        )
    except (ValueError, TypeError):
        executions_limit = 10

    current_session_id = _parse_uuid(body.session_id)
    requested_session_id = _parse_uuid(body.tool_args.get("session_id"))

    # Recent jobs for the agent type, newest first. Command (optimization
    # side) runs and the current session are excluded.
    normal_jobs = await _recent_normal_jobs(db, agent_type_id, current_session_id)

    executions = [
        {
            "session_id": str(job.id),
            "status": _job_status(job),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": (
                job.completed_at.isoformat() if job.completed_at else None
            ),
        }
        for job in normal_jobs[:executions_limit]
    ]

    selected, selection = _select_reference_job(normal_jobs, requested_session_id)

    # Reference input: the selected execution's actual typed input, with
    # internal routing keys (``__conv_session_id`` etc.) stripped. The
    # optimizer MUST use these exact keys/values as the script ``context`` —
    # guessing or renaming input fields produces a script that verifies but
    # fails at serving time.
    selected_input = (
        _reference_input(selected.input_data) if selected is not None else None
    )

    agent_type = await db.get(AgentType, agent_type_id)
    input_schema = (
        agent_type.input_schema
        if agent_type is not None and isinstance(agent_type.input_schema, dict)
        else None
    )

    entries: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    transcript_truncated = False
    text = ""
    if selected is not None:
        # Newest-first DB window, then reverse for a chronological text log.
        # The window is the FULL transcript window (so replayable tool calls
        # are never silently dropped); the returned text log stays bounded by
        # ``log_limit``.
        rows = await db.execute(
            select(ExecutionLogEntry)
            .where(ExecutionLogEntry.session_id == selected.id)
            .order_by(ExecutionLogEntry.timestamp.desc())
            .limit(REFERENCE_TRANSCRIPT_LOG_LIMIT + 1)
        )
        ordered = list(rows.scalars().all())
        window_truncated = len(ordered) > REFERENCE_TRANSCRIPT_LOG_LIMIT
        if window_truncated:
            ordered = ordered[:REFERENCE_TRANSCRIPT_LOG_LIMIT]
        ordered.reverse()

        raw_entries = [
            {
                "event_type": entry.event_type,
                "message": entry.message,
                "data": entry.data if isinstance(entry.data, dict) else {},
            }
            for entry in ordered
        ]
        tool_calls, calls_truncated = _tool_calls_from_entries(raw_entries)
        transcript_truncated = bool(window_truncated or calls_truncated)

        for entry in ordered[-log_limit:]:
            entries.append(
                {
                    "timestamp": (
                        entry.timestamp.isoformat() if entry.timestamp else None
                    ),
                    "log_level": entry.log_level,
                    "event_type": entry.event_type,
                    "message": entry.message,
                }
            )
        text = "\n".join(
            f"[{e['timestamp'] or '-'}] {e['log_level']} "
            f"{e['event_type']}: {e['message']}"
            for e in entries
        )
        if len(text) > 20_000:
            text = "...(earlier log truncated)\n" + text[-20_000:]

    result: dict[str, Any] = {
        "agent_type_id": str(agent_type_id),
        "executions": executions,
        "selected_session_id": str(selected.id) if selected is not None else None,
        "selected_status": _job_status(selected) if selected is not None else None,
        "selection": selection,
        "input": selected_input,
        "input_schema": input_schema,
        # The REPLAY transcript of the selected execution: each recorded tool
        # call with its arguments and response. ``execute_script`` replays
        # exactly this (never live tools).
        "tool_calls": tool_calls,
        "transcript_truncated": transcript_truncated,
        "entry_count": len(entries),
        "entries": entries,
        "text": text,
    }
    if selected is None:
        result["message"] = (
            "No normal (non-optimization) execution is available for this agent "
            "type yet. Run the agent successfully first so the optimizer has a "
            "reference execution to learn from."
        )
    return SystemToolResponse(result=result)


@router.post("/get-script", response_model=SystemToolResponse)
async def get_script_tool(
    body: SystemToolRequest,
    tenant_ctx: Annotated[TenantContext, Depends(require_internal_tenant_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemToolResponse:
    """Return one script definition (with python_source + lifecycle) by name/id."""
    from app.services.script_registry import ScriptRegistryService

    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")
    out_of_scope = await require_subject_match(
        db, body.conversation_session_id, agent_type_id
    )
    if out_of_scope is not None:
        return SystemToolResponse(result=out_of_scope)

    name = str(body.tool_args.get("name") or "").strip()
    definition_id_raw = body.tool_args.get("definition_id")
    if not name and not definition_id_raw:
        raise HTTPException(status_code=400, detail="name or definition_id is required")

    service = ScriptRegistryService()
    definition = None
    if definition_id_raw:
        try:
            definition = await service.get_definition(
                db, uuid.UUID(str(definition_id_raw)), tenant_ctx.tenant_id
            )
        except (ValueError, TypeError):
            definition = None
    if definition is None and name:
        definition = await service.get_definition_by_name_and_agent_type(
            db, name=name, agent_type_id=agent_type_id, tenant_id=tenant_ctx.tenant_id
        )
    if definition is None:
        return SystemToolResponse(result={"found": False})

    current = await _latest_version(db, definition, service)
    return SystemToolResponse(
        result={"found": True, **_script_payload(definition, current)}
    )


# ── request_live_test ───────────────────────────────────────────────────────
#
# The handler lives in ``internal/system_tools.py`` (``POST /request-live-test``)
# next to the other generic system tools: it creates the live-test ledger row
# and the approval intervention, which is CC-domain work rather than an
# optimization read tool. The subject guard (``require_subject_match``) runs
# there first, exactly as it does for every handler in this module.

# ── Shared result payload ────────────────────────────────────────────────────


def _optimized_plan_result(optimized: Any) -> dict[str, Any]:
    """Serialize an OptimizedImplementationPlan for the tool result."""
    plan_steps = optimized.plan_steps or []
    return {
        "id": str(optimized.id),
        "agent_type_id": str(optimized.agent_type_id),
        "agent_plan_id": str(optimized.agent_plan_id),
        "status": optimized.status.value,
        "fully_scripted": optimized.fully_scripted,
        "error": optimized.error,
        "steps": plan_steps,
        "steps_count": len(plan_steps),
        "scripts_authored": sum(
            1 for step in plan_steps
            if isinstance(step, dict) and step.get("python_source")
        ),
        "feedback_comments": optimized.feedback_comments or [],
        "generated_at": optimized.generated_at.isoformat()
        if optimized.generated_at
        else None,
    }
