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

    ``execute_script`` is the VERIFICATION primitive. Segregation (top-priority
    rule): the sandbox executes ONLY in Agent Runtime — CC routes every
    execution (inline and saved) through ``CommunicationHubClient.
    forward_sandboxed_script`` (CC → CH ``/internal/script-tools/forward`` →
    AR ``/internal/script-tools/execute`` — the CH→AR hop presents CH's own
    service certificate, identical to the ``script____<name>`` route), where
    AR runs the source in the real sandbox with the SESSION-BOUND tool client
    (identity parity, SEC1). CC never imports or executes the sandbox
    (guarded by
    ``tests/api/v1/internal/test_execute_script_sandbox_segregation.py``).
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.models.agents import AgentPlan, AgentType
from app.db.models.optimized_plan import OptimizedImplementationPlan
from app.db.session import get_db

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


# ── Authoring-time tool-name validation (live-defect regression) ─────────────


def extract_tools_call_names(python_source: str) -> list[str]:
    """Return the literal tool names from ``tools.call('<name>', ...)`` calls.

    Only constant-string first arguments are collected (dynamic names cannot
    be validated at authoring time).
    """
    import ast

    try:
        tree = ast.parse(python_source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "call"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.append(node.args[0].value)
    return names


async def _allowed_tool_names_for_agent(
    db: AsyncSession, agent_type_id: uuid.UUID
) -> set[str]:
    """Resolve the agent's ACTUAL allowed MCP tool names (role → skills → tools).

    Mirrors the agent-context permission resolution: agent-type SOP/Skill
    bindings override the role scope when bindings exist.
    """
    from app.db.models.agents import (
        AgentType,
        AgentTypeSkillBinding,
        AgentTypeSopBinding,
    )
    from app.services.agents.permission_manager import AgentPermissionManager

    agent_type = await db.get(AgentType, agent_type_id)
    if agent_type is None or not agent_type.role_id:
        return set()

    sop_rows = await db.execute(
        select(AgentTypeSopBinding.sop_id).where(
            AgentTypeSopBinding.agent_type_id == agent_type_id
        )
    )
    bound_sop_ids = {row[0] for row in sop_rows.fetchall()}
    skill_rows = await db.execute(
        select(AgentTypeSkillBinding.skill_id).where(
            AgentTypeSkillBinding.agent_type_id == agent_type_id
        )
    )
    bound_skill_ids = {row[0] for row in skill_rows.fetchall()}

    has_bindings = bool(bound_sop_ids or bound_skill_ids)
    manager = AgentPermissionManager()
    return await manager.calculate_allowed_tools(
        agent_type.role_id,
        db,
        override_skill_ids=bound_skill_ids if has_bindings else None,
        override_sop_ids=bound_sop_ids if has_bindings else None,
    )


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

    result = await db.execute(
        select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
    )
    plan = result.scalar_one_or_none()
    return SystemToolResponse(
        result={
            "agent_type_id": str(agent_type_id),
            "agent_plan_id": str(plan.id) if plan else None,
            "steps": (plan.plan_steps or []) if plan else [],
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
    return SystemToolResponse(result=_optimized_plan_result(reloaded))


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
    """Run a script through the REAL sandbox in Agent Runtime (verify).

    Two paths — BOTH execute in Agent Runtime via the CC→CH→AR internal-call
    mechanism (the sandbox never runs in the CC process):
    - **inline** (preferred by the optimize-and-verify command): pass the FULL
      ``python_source`` (+ optional ``input``) — executed directly on the
      agent's identity, NO save required. The agent keeps the source in its
      own context and iterates by passing modified source.
    - **saved**: pass ``script_version_id`` — the persisted version's source
      is forwarded to AR (unchanged legacy semantics).

    Returns ``{"output": <result>}`` on success, or ``{"error": <reason>}`` on
    a sandbox compile/violation/resource-cap failure (AR's structured error is
    surfaced as-is). THIS is the verification primitive: a script that runs
    here runs at serving time.
    """
    from app.services.control_center.comm_hub_client import (
        CommunicationHubClient,
        CommunicationHubClientError,
    )

    input_context = body.tool_args.get("input")
    if not isinstance(input_context, dict):
        input_context = {}

    async def _execute_in_agent_runtime(
        python_source: str, agent_type_id: uuid.UUID | None
    ) -> dict[str, Any]:
        """Forward the source to AR's sandbox via CH; map the AR contract
        (``{"result", "error"}``) to this tool's response shape."""
        try:
            ar_resp = await CommunicationHubClient().forward_sandboxed_script(
                python_source=python_source,
                session_id=body.session_id,
                agent_type_id=str(agent_type_id) if agent_type_id else "",
                input_context=input_context,
                tenant_context=tenant_ctx,
            )
        except CommunicationHubClientError as exc:
            return {"error": f"Agent Runtime script execution failed: {exc}"}
        if ar_resp.get("error"):
            return {"error": str(ar_resp["error"])}
        return {"output": ar_resp.get("result")}

    raw_source = body.tool_args.get("python_source")
    if isinstance(raw_source, str) and raw_source.strip():
        # Inline path: execute the working source without persisting it.
        agent_type_id = _resolve_agent_type_id(body)
        # Authoring-time tool-name validation: a malformed tool name (e.g. a
        # two-underscore separator typo) is a STRUCTURED validation error
        # listing the valid names — the LLM repairs it in its next iteration
        # instead of the script failing at serving time.
        validation_error = await _validate_script_tool_names(
            db, agent_type_id, raw_source
        )
        if validation_error is not None:
            return SystemToolResponse(result=validation_error)
        return SystemToolResponse(
            result=await _execute_in_agent_runtime(raw_source, agent_type_id)
        )

    from app.services.script_registry import ScriptRegistryService

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

    service = ScriptRegistryService()
    version = await service.get_version(db, version_id, tenant_ctx.tenant_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Script version not found")
    if not version.python_source:
        raise HTTPException(
            status_code=422, detail="Script version has no python_source to execute"
        )

    return SystemToolResponse(
        result=await _execute_in_agent_runtime(
            version.python_source, _resolve_agent_type_id(body)
        )
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
    """Self-reflection tool: the agent's recent execution logs (most recent
    first, including failures) so the optimization run can learn from past
    errors instead of blindly re-authoring."""
    from app.db.models.agents import AgentJob
    from app.db.models.session_logs import ExecutionLogEntry

    agent_type_id = _resolve_agent_type_id(body)
    if agent_type_id is None:
        raise HTTPException(status_code=400, detail="agent_type_id is required")

    raw_limit = body.tool_args.get("limit")
    try:
        limit = min(max(int(raw_limit), 1), 100) if raw_limit else 30
    except (ValueError, TypeError):
        limit = 30

    result = await db.execute(
        select(ExecutionLogEntry, AgentJob.status)
        .join(AgentJob, AgentJob.id == ExecutionLogEntry.session_id)
        .where(AgentJob.agent_type_id == agent_type_id)
        .order_by(ExecutionLogEntry.timestamp.desc())
        .limit(limit)
    )
    entries: list[dict[str, Any]] = []
    for entry, job_status in result.all():
        entries.append(
            {
                "session_id": str(entry.session_id),
                "session_status": (
                    job_status.value if hasattr(job_status, "value") else str(job_status)
                ),
                "timestamp": (
                    entry.timestamp.isoformat() if entry.timestamp else None
                ),
                "log_level": entry.log_level,
                "event_type": entry.event_type,
                "message": entry.message,
            }
        )
    return SystemToolResponse(
        result={"agent_type_id": str(agent_type_id), "entries": entries}
    )


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
