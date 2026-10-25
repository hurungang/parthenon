"""Control Center REST API for the Software 3.0 script registry.

JWT-authenticated, permission-gated via ``require_permission()`` against the
``agent::scripts`` resource type. The underlying registry service is the only
code path that touches the script tables.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_SCRIPTS
from app.db.models.script_registry import (
    ScriptHealthStatus,
    ScriptLifecycleStatus,
)
from app.db.session import DbSession
from app.schemas.scripts import (
    CandidateSubmitRequest,
    CostReportResponse,
    ExecutionReportRequest,
    ExecutionRecordListResponse,
    ExecutionRecordResponse,
    FallbackEventListResponse,
    FallbackEventResponse,
    FallbackReportRequest,
    HealthSummaryResponse,
    LifecycleTransitionRequest,
    RepairAttemptListResponse,
    RepairAttemptResponse,
    RepairCandidateRequest,
    ScriptDefinitionCreate,
    ScriptDefinitionListResponse,
    ScriptDefinitionResponse,
    ScriptVersionCreate,
    ScriptVersionResponse,
    VerificationRunListResponse,
    VerificationRunResponse,
    VerificationSubmitRequest,
    VersionDiffResponse,
)
from app.services.script_registry import (
    LifecycleTransitionError,
    ScriptRegistryService,
)

logger = logging.getLogger(__name__)

ScriptsRouter = APIRouter(
    prefix="/scripts",
    tags=["Scripts"],
)

_service = ScriptRegistryService()


def _tenant_id(request: Request) -> uuid.UUID | None:
    from app.core.tenant_context import get_tenant_context, tenant_id_or_none

    return tenant_id_or_none(get_tenant_context(request))


def _get_or_404(exc: LookupError) -> None:
    raise HTTPException(status_code=404, detail=str(exc))


# ── Definitions ───────────────────────────────────────────────────────────────


@ScriptsRouter.get("", response_model=ScriptDefinitionListResponse)
async def list_scripts(
    request: Request,
    db: DbSession,
    agent_type_id: uuid.UUID | None = Query(None),
    lifecycle_status: ScriptLifecycleStatus | None = Query(None),
    health_status: ScriptHealthStatus | None = Query(None),
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> ScriptDefinitionListResponse:
    items = await _service.list_definitions(
        db,
        tenant_id=_tenant_id(request),
        agent_type_id=agent_type_id,
        lifecycle_status=lifecycle_status,
        health_status=health_status,
    )
    return ScriptDefinitionListResponse(
        items=[ScriptDefinitionResponse.from_model(d) for d in items],
        total=len(items),
    )


@ScriptsRouter.post("", response_model=ScriptDefinitionResponse, status_code=201)
async def create_script(
    body: ScriptDefinitionCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "manage")),
) -> ScriptDefinitionResponse:
    definition = await _service.create_definition(
        db,
        name=body.name,
        agent_type_id=body.agent_type_id,
        description=body.description,
        source_plan_id=body.source_plan_id,
        source_session_id=body.source_session_id,
        tenant_id=_tenant_id(request),
    )
    return ScriptDefinitionResponse.from_model(
        await _service.get_definition(db, definition.id, _tenant_id(request))
    )


# ── Audit & cost reporting (G2–G4) ────────────────────────────────────────────


@ScriptsRouter.get("/executions", response_model=ExecutionRecordListResponse)
async def list_script_executions(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> ExecutionRecordListResponse:
    """Per-execution audit: script version, outcome, identity parity (G2)."""
    from sqlalchemy import select

    from app.db.models.script_execution import ScriptExecutionRecord

    tenant_id = _tenant_id(request)
    stmt = select(ScriptExecutionRecord).order_by(
        ScriptExecutionRecord.created_at.desc()
    ).limit(500)
    if tenant_id is not None:
        stmt = stmt.where(ScriptExecutionRecord.tenant_id == tenant_id)
    result = await db.execute(stmt)
    records = list(result.scalars().all())
    return ExecutionRecordListResponse(
        items=[ExecutionRecordResponse.from_model(r) for r in records],
        total=len(records),
    )


@ScriptsRouter.get("/reports/compilation", response_model=CostReportResponse)
async def compilation_report(
    request: Request,
    db: DbSession,
    agent_type_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> CostReportResponse:
    """Compilation rate / script hit rate / fallback rate (G4)."""
    report = await _service.cost_report(
        db,
        agent_type_id=agent_type_id,
        since=since,
        until=until,
        tenant_id=_tenant_id(request),
    )
    return CostReportResponse(**report)


@ScriptsRouter.get("/reports/cost-savings", response_model=CostReportResponse)
async def cost_savings_report(
    request: Request,
    db: DbSession,
    agent_type_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> CostReportResponse:
    """Tokens saved vs LLM baseline with residual model usage (G3)."""
    report = await _service.cost_report(
        db,
        agent_type_id=agent_type_id,
        since=since,
        until=until,
        tenant_id=_tenant_id(request),
    )
    return CostReportResponse(**report)


@ScriptsRouter.get("/{definition_id}", response_model=ScriptDefinitionResponse)
async def get_script(
    definition_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> ScriptDefinitionResponse:
    definition = await _service.get_definition(db, definition_id, _tenant_id(request))
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Script {definition_id} not found")
    return ScriptDefinitionResponse.from_model(definition)


@ScriptsRouter.get("/{definition_id}/versions", response_model=list[ScriptVersionResponse])
async def list_script_versions(
    definition_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> list[ScriptVersionResponse]:
    versions = await _service.list_versions(db, definition_id, _tenant_id(request))
    return [ScriptVersionResponse.from_model(v) for v in versions]


@ScriptsRouter.post("/{definition_id}/versions", response_model=ScriptVersionResponse, status_code=201)
async def create_script_version(
    definition_id: uuid.UUID,
    body: ScriptVersionCreate,
    request: Request,
    db: DbSession,
    __: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "manage")),
) -> ScriptVersionResponse:
    try:
        version = await _service.create_version(
            db,
            definition_id=definition_id,
            declarative_step_graph=body.declarative_step_graph,
            python_source=body.python_source,
            cpu_limit_seconds=body.cpu_limit_seconds,
            memory_limit_mb=body.memory_limit_mb,
            wall_time_limit_seconds=body.wall_time_limit_seconds,
            sandbox_validation_status=body.sandbox_validation_status,
            sandbox_validation_reason=body.sandbox_validation_reason,
            version_label=body.version_label,
            parent_version_id=body.parent_version_id,
            content_reference=body.content_reference,
            compiled_from_source=body.compiled_from_source,
            created_by=body.created_by,
            tenant_id=_tenant_id(request),
        )
    except LookupError as exc:
        _get_or_404(exc)
    # E4a: record the plan-step → script linkage when the version was
    # compiled from the definition's source plan (no-op otherwise).
    definition = await _service.get_definition(db, definition_id, _tenant_id(request))
    if definition is not None:
        await _service.link_plan_steps_to_version(db, definition=definition, version=version)
    return ScriptVersionResponse.from_model(version)


@ScriptsRouter.get(
    "/{definition_id}/versions/{version_id}/diff",
    response_model=VersionDiffResponse,
)
async def diff_script_versions(
    definition_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    db: DbSession,
    against: uuid.UUID = Query(..., description="Version id to diff against"),
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> VersionDiffResponse:
    try:
        diff = await _service.version_diff(
            db, version_id, against, _tenant_id(request)
        )
    except LookupError as exc:
        _get_or_404(exc)
    return VersionDiffResponse(**diff)


@ScriptsRouter.post(
    "/{definition_id}/versions/{version_id}/promote",
    response_model=ScriptVersionResponse,
)
async def promote_script_version(
    definition_id: uuid.UUID,
    version_id: uuid.UUID,
    body: LifecycleTransitionRequest,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "manage")),
) -> ScriptVersionResponse:
    """Operator lifecycle transition (promote/demote) — rules enforced in service."""
    try:
        version = await _service.transition_version(
            db,
            version_id,
            body.target_status,
            tenant_id=_tenant_id(request),
            actor="operator",
        )
    except LifecycleTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError as exc:
        _get_or_404(exc)
    return ScriptVersionResponse.from_model(version)


@ScriptsRouter.post(
    "/{definition_id}/versions/{version_id}/retire",
    response_model=ScriptVersionResponse,
)
async def retire_script_version(
    definition_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "manage")),
) -> ScriptVersionResponse:
    try:
        version = await _service.transition_version(
            db,
            version_id,
            ScriptLifecycleStatus.retired,
            tenant_id=_tenant_id(request),
            actor="operator",
        )
    except LifecycleTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError as exc:
        _get_or_404(exc)
    return ScriptVersionResponse.from_model(version)


# ── Verification, fallbacks, health ───────────────────────────────────────────


@ScriptsRouter.get("/{definition_id}/verifications", response_model=VerificationRunListResponse)
async def list_script_verifications(
    definition_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> VerificationRunListResponse:
    runs = await _service.list_verifications(db, definition_id, _tenant_id(request))
    return VerificationRunListResponse(
        items=[VerificationRunResponse.from_model(r) for r in runs],
        total=len(runs),
    )


@ScriptsRouter.get("/{definition_id}/fallbacks", response_model=FallbackEventListResponse)
async def list_script_fallbacks(
    definition_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> FallbackEventListResponse:
    events = await _service.list_fallbacks(db, definition_id, _tenant_id(request))
    return FallbackEventListResponse(
        items=[FallbackEventResponse.from_model(e) for e in events],
        total=len(events),
    )


@ScriptsRouter.get("/{definition_id}/repairs", response_model=RepairAttemptListResponse)
async def list_script_repairs(
    definition_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> RepairAttemptListResponse:
    """Repair attempts for a script: defect diagnosis, diff, retry outcome,
    repaired candidate lineage (E10, G2)."""
    attempts = await _service.list_repairs(db, definition_id, _tenant_id(request))
    return RepairAttemptListResponse(
        items=[RepairAttemptResponse.from_model(a) for a in attempts],
        total=len(attempts),
    )


@ScriptsRouter.get("/{definition_id}/health", response_model=HealthSummaryResponse)
async def get_script_health(
    definition_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCRIPTS, "read")),
) -> HealthSummaryResponse:
    try:
        summary = await _service.health_summary(db, definition_id, _tenant_id(request))
    except LookupError as exc:
        _get_or_404(exc)
    return HealthSummaryResponse(**summary)


# ── Shared body types reused by the internal router ──────────────────────────

__all__ = [
    "ScriptsRouter",
    "CandidateSubmitRequest",
    "ExecutionReportRequest",
    "FallbackReportRequest",
    "RepairCandidateRequest",
    "VerificationSubmitRequest",
]
