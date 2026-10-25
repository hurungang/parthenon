"""Internal CC↔AR API for the Software 3.0 script framework.

Service-certificate-only endpoints (agent-instance certificates are blocked
from ``/internal/*`` by the existing CC middleware). Agent Runtime completes
all registry interactions here — it never opens a DB connection.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import require_internal_tenant_context, require_service_certificate
from app.core.tenant_context import TenantContext
from app.db.models.conversations import ConversationSession
from app.db.session import DbSession
from app.schemas.scripts import (
    CandidateSubmitRequest,
    ExecutionReportRequest,
    ExecutionRecordResponse,
    FallbackReportRequest,
    FallbackEventResponse,
    RepairAttemptListResponse,
    RepairAttemptResponse,
    RepairCandidateRequest,
    PromoteVersionRequest,
    ScriptVersionResponse,
    ServingVersionResponse,
    VerificationRunResponse,
    VerificationSubmitRequest,
    InvocableScriptResponse,
)
from app.services.script_registry import ScriptRegistryService

logger = logging.getLogger(__name__)

InternalScriptsRouter = APIRouter(
    prefix="/internal/scripts",
    tags=["internal"],
    dependencies=[
        Depends(require_service_certificate),
        Depends(require_internal_tenant_context),
    ],
)

_service = ScriptRegistryService()

TenantCtx = Annotated[TenantContext, Depends(require_internal_tenant_context)]


@InternalScriptsRouter.get(
    "/invocable", response_model=list[InvocableScriptResponse]
)
async def list_invocable_scripts(
    db: DbSession,
    tenant_ctx: TenantCtx,
    agent_type_id: uuid.UUID = Query(...),
) -> list[InvocableScriptResponse]:
    """List the agent type's compiled scripts as invocable virtual tools
    (``script____<name>`` surface). Consumed by the Agent Runtime both to
    expose the tools to the agent LLM and to resolve executions by name."""
    items = await _service.list_invocable_scripts(
        db, agent_type_id=agent_type_id, tenant_id=tenant_ctx.tenant_id
    )
    return [InvocableScriptResponse(**item) for item in items]


@InternalScriptsRouter.get("/serving-version", response_model=ServingVersionResponse)
async def get_serving_version(
    db: DbSession,
    tenant_ctx: TenantCtx,
    agent_type_id: uuid.UUID = Query(...),
) -> ServingVersionResponse:
    """Fetch the current verified/compiled serving script version (script-first
    dispatch lookup). Absent → the AR dispatcher takes the LLM path; no mode
    is returned because no execution modes exist (E1–E3)."""
    serving = await _service.get_serving_version(
        db, agent_type_id=agent_type_id, tenant_id=tenant_ctx.tenant_id
    )
    if serving is None:
        return ServingVersionResponse(
            script_definition_id=None,
            script_version_id=None,
            script_version_label=None,
            declarative_step_graph=None,
        )
    return ServingVersionResponse(**serving)


@InternalScriptsRouter.get("/optimized-plan")
async def get_optimized_plan(
    db: DbSession,
    tenant_ctx: TenantCtx,
    agent_type_id: uuid.UUID = Query(...),
) -> dict:
    """Return the fresh ready OptimizedImplementationPlan (execution preference),
    or a null-shaped payload when absent / stale / failed → base-plan fallback."""
    optimized = await _service.get_fresh_optimized_plan(
        db, agent_type_id=agent_type_id, tenant_id=tenant_ctx.tenant_id
    )
    if optimized is None:
        return {
            "optimized_plan_id": None,
            "status": None,
            "fully_scripted": False,
        }
    return {
        "optimized_plan_id": optimized["optimized_plan_id"],
        "status": optimized["status"],
        "fully_scripted": optimized["fully_scripted"],
    }


@InternalScriptsRouter.get(
    "/versions/{version_id}", response_model=ScriptVersionResponse
)
async def get_compiled_version(
    version_id: uuid.UUID,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> ScriptVersionResponse:
    """Fetch a script version (step graph) for execution in Agent Runtime."""
    version = await _service.get_version(db, version_id, tenant_ctx.tenant_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"ScriptVersion {version_id} not found")
    return ScriptVersionResponse.from_model(version)


@InternalScriptsRouter.post("/candidates", response_model=ScriptVersionResponse, status_code=201)
async def submit_candidate(
    body: CandidateSubmitRequest,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> ScriptVersionResponse:
    """Agent Runtime compiler submits a candidate step graph (draft version)."""
    definition = await _service.get_definition_by_name_and_agent_type(
        db, name=body.name, agent_type_id=body.agent_type_id
    )
    if definition is None:
        definition = await _service.create_definition(
            db,
            name=body.name,
            agent_type_id=body.agent_type_id,
            description=body.description,
            source_plan_id=body.source_plan_id,
            source_session_id=body.source_session_id,
            tenant_id=tenant_ctx.tenant_id,
        )
    version = await _service.create_version(
        db,
        definition_id=definition.id,
        declarative_step_graph=body.declarative_step_graph,
        python_source=body.python_source,
        cpu_limit_seconds=body.cpu_limit_seconds,
        memory_limit_mb=body.memory_limit_mb,
        wall_time_limit_seconds=body.wall_time_limit_seconds,
        sandbox_validation_status=body.sandbox_validation_status,
        sandbox_validation_reason=body.sandbox_validation_reason,
        version_label=body.version_label,
        parent_version_id=body.parent_version_id,
        created_by=body.created_by or "agent-runtime-compiler",
        tenant_id=tenant_ctx.tenant_id,
    )
    # Execution semantics (product decision): the definition carries the
    # plan's fully_scripted mark — only fully_scripted definitions are
    # served directly; all others stay invocable virtual tools.
    if definition.fully_scripted != body.fully_scripted:
        definition.fully_scripted = body.fully_scripted
        await db.flush()
    # E4a: record the plan-step → script linkage so the plan API/UI can
    # expose per-step script references (only when compiled from a plan).
    await _service.link_plan_steps_to_version(db, definition=definition, version=version)
    return ScriptVersionResponse.from_model(version)


@InternalScriptsRouter.post("/promote", response_model=ScriptVersionResponse)
async def promote_version(
    body: PromoteVersionRequest,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> ScriptVersionResponse:
    """Promote a script version to the serving (compiled) version.

    Auto-compilation path: after a passing shadow verification the candidate
    is auto-promoted so the next run executes the script (script-first with
    unconditional LLM fallback makes this safe per the PRD). A still-draft
    version requires a passing verification run (V4) before the transition.
    """
    from app.db.models.script_registry import ScriptLifecycleStatus
    from app.services.script_registry.service import LifecycleTransitionError

    try:
        version = await _service.transition_version(
            db,
            body.script_version_id,
            ScriptLifecycleStatus.compiled,
            tenant_id=tenant_ctx.tenant_id,
            actor=body.actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LifecycleTransitionError:
        # Version may still be draft (verification ran but the auto-transition
        # did not apply). Promote draft → verified → compiled when evidence
        # allows; surface 409 otherwise.
        try:
            await _service.transition_version(
                db,
                body.script_version_id,
                ScriptLifecycleStatus.verified,
                tenant_id=tenant_ctx.tenant_id,
                actor=body.actor,
            )
            version = await _service.transition_version(
                db,
                body.script_version_id,
                ScriptLifecycleStatus.compiled,
                tenant_id=tenant_ctx.tenant_id,
                actor=body.actor,
            )
        except (LookupError, LifecycleTransitionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return ScriptVersionResponse.from_model(version)


@InternalScriptsRouter.post(
    "/verifications", response_model=VerificationRunResponse, status_code=201
)
async def submit_verification(
    body: VerificationSubmitRequest,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> VerificationRunResponse:
    """Submit verification evidence; verdict applied server-side (V2, V3)."""
    try:
        run = await _service.record_verification(
            db,
            version_id=body.script_version_id,
            comparison_outcome=body.comparison_outcome,
            input_context=body.input_context,
            expected_output=body.expected_output,
            actual_output=body.actual_output,
            verdict_reason=body.verdict_reason,
            reference_execution_id=body.reference_execution_id,
            sandbox_check_passed=body.sandbox_check_passed,
            tenant_id=tenant_ctx.tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return VerificationRunResponse.from_model(run)


@InternalScriptsRouter.post("/fallbacks", response_model=FallbackEventResponse, status_code=201)
async def report_fallback(
    body: FallbackReportRequest,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> FallbackEventResponse:
    """Report a fallback event; health degradation applied (F2, F4)."""
    event = await _service.record_fallback(
        db,
        execution_record_id=body.execution_record_id,
        script_version_id=body.script_version_id,
        trigger_reason=body.trigger_reason,
        resulting_action=body.resulting_action,
        failure_detail=body.failure_detail,
        repaired_version_id=body.repaired_version_id,
        tenant_id=tenant_ctx.tenant_id,
    )
    return FallbackEventResponse.from_model(event)


@InternalScriptsRouter.post(
    "/executions", response_model=ExecutionRecordResponse, status_code=201
)
async def report_execution(
    body: ExecutionReportRequest,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> ExecutionRecordResponse:
    """Report a script/fallback execution record (G2)."""
    record = await _service.record_execution(
        db,
        outcome=body.outcome,
        script_version_id=body.script_version_id,
        duration_ms=body.duration_ms,
        tools_invoked=body.tools_invoked,
        model_backed_steps_used=body.model_backed_steps_used,
        session_id=body.session_id,
        identity_parity_confirmed=body.identity_parity_confirmed,
        tokens_saved_estimate=body.tokens_saved_estimate,
        tokens_saved_actual=body.tokens_saved_actual,
        sandbox_termination=body.sandbox_termination,
        sandbox_violation_detail=body.sandbox_violation_detail,
        tenant_id=tenant_ctx.tenant_id,
    )
    return ExecutionRecordResponse.from_model(record)


@InternalScriptsRouter.post(
    "/repairs", response_model=RepairAttemptResponse, status_code=201
)
async def submit_repair(
    body: RepairCandidateRequest,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> RepairAttemptResponse:
    """Report a repair attempt: CC persists the RepairAttempt record (defect
    diagnosis, diff, retry outcome) and spawns the repaired candidate as a
    new draft version with ``repaired_from`` lineage (E9/E10, F3, V4)."""
    try:
        attempt = await _service.record_repair_attempt(
            db,
            script_version_id=body.script_version_id,
            defect_diagnosis=body.defect_diagnosis,
            declarative_step_graph=body.declarative_step_graph,
            diff_applied=body.diff_applied,
            attempt_number=body.attempt_number,
            retry_outcome=body.retry_outcome,
            created_by=body.created_by,
            tenant_id=tenant_ctx.tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RepairAttemptResponse.from_model(attempt)


@InternalScriptsRouter.get("/repairs", response_model=RepairAttemptListResponse)
async def list_repairs(
    db: DbSession,
    tenant_ctx: TenantCtx,
    script_id: uuid.UUID = Query(..., description="Script definition id"),
) -> RepairAttemptListResponse:
    """List repair attempts for a script (bounded-retry bookkeeping, E10/G2)."""
    attempts = await _service.list_repairs(
        db, definition_id=script_id, tenant_id=tenant_ctx.tenant_id
    )
    return RepairAttemptListResponse(
        items=[RepairAttemptResponse.from_model(a) for a in attempts],
        total=len(attempts),
    )


@InternalScriptsRouter.get("/llm-reference/{session_id}")
async def get_llm_reference(
    session_id: uuid.UUID,
    db: DbSession,
    tenant_ctx: TenantCtx,
) -> dict:
    """Fetch a recorded LLM execution for shadow comparison (V1).

    Returns recorded inputs and outputs of the reference session — metadata
    and I/O records only; never identity tokens.
    """
    stmt = select(ConversationSession).where(ConversationSession.id == session_id)
    if tenant_ctx.tenant_id is not None:
        stmt = stmt.where(ConversationSession.tenant_id == tenant_ctx.tenant_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Recorded execution I/O lives on the session's turn/tool-call records;
    # expose only non-sensitive fields for verification comparison. No tokens.
    from app.db.models.conversations import ConversationTurn, ToolCallRecord

    turn_rows = await db.execute(
        select(ConversationTurn)
        .where(ConversationTurn.session_id == session.id)
        .order_by(ConversationTurn.created_at.asc())
    )
    turns = list(turn_rows.scalars().all())

    tool_rows = await db.execute(
        select(ToolCallRecord)
        .join(ConversationTurn, ConversationTurn.id == ToolCallRecord.turn_id)
        .where(ConversationTurn.session_id == session.id)
        .order_by(ToolCallRecord.created_at.asc())
    )
    tool_calls = list(tool_rows.scalars().all())

    return {
        "session_id": session.id,
        "agent_type_id": session.agent_type_id,
        "turn_count": session.turn_count,
        "created_at": session.created_at,
        "turns": [
            {
                "id": turn.id,
                "role": turn.role.value if turn.role else None,
                "content": turn.content,
                "created_at": turn.created_at,
            }
            for turn in turns
        ],
        "tool_calls": [
            {
                "tool_name": call.tool_name,
                "tool_input": call.tool_input,
                "tool_output": call.tool_output,
                "error": call.error,
                "duration_ms": call.duration_ms,
                "created_at": call.created_at,
            }
            for call in tool_calls
        ],
    }
