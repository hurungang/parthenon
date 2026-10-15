"""System One provider configuration API router.

JWT-protected; all endpoints require ``system::system_one`` permissions.
API key material is accepted on create/update only and NEVER appears in any
response (write-only secret, AES-256 encrypted at rest).
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_permission
from app.core.resource_types import RT_SYSTEM_SYSTEM_ONE
from app.core.tenant_context import get_tenant_context
from app.db.models.system_one_provider_config import SystemOneProviderType
from app.db.session import DbSession
from app.schemas.agents import ModelUsagePostureRead
from app.schemas.system_one import (
    DecisionEnabledModelRead,
    DecisionGuardrailCreate,
    DecisionGuardrailRead,
    DecisionGuardrailUpdate,
    DecisionModelAvailabilityUpdate,
    DecisionModelHierarchyEntry,
    SystemOneProviderCreate,
    SystemOneProviderRead,
    SystemOneProviderTypeRead,
    SystemOneProviderUpdate,
    SystemOneStatus,
    SystemOneTestConnectionResult,
    VendorModelImportRequest,
    VendorModelSyncResult,
)
from app.services.control_center.model_usage_guardrail_service import (
    ModelGuardrailDecisionProviderNotFoundError,
    ModelGuardrailDuplicatePeriodError,
    ModelUsageGuardrailService,
)
from app.services.system_one.decision_model_availability_service import (
    DecisionModelCatalogueError,
    DecisionModelCatalogueService,
)
from app.services.system_one.provider_config_service import (
    SystemOneProviderConfigService,
    SystemOneProviderDuplicateError,
    SystemOneProviderError,
    SystemOneProviderInUseError,
    SystemOneProviderValidationError,
)

logger = logging.getLogger(__name__)

SystemOneRouter = APIRouter(prefix="/system-one", tags=["System One"])

_service = SystemOneProviderConfigService()
_catalogue = DecisionModelCatalogueService(_service)


def _provider_error_status(exc: SystemOneProviderError) -> int:
    """Map provider service errors to structured HTTP statuses."""
    if isinstance(exc, SystemOneProviderValidationError):
        return 422
    if isinstance(exc, SystemOneProviderDuplicateError):
        return 409
    if isinstance(exc, SystemOneProviderInUseError):
        return 409
    return 404


def _tenant_id(request: Request) -> uuid.UUID | None:
    """Resolve the caller's tenant id from the request tenant context.

    ``None`` means multi-tenancy is off (single-tenant / root deployment).
    """
    context = get_tenant_context(request)
    return context.tenant_id if context.is_set else None


@SystemOneRouter.get("/providers", response_model=list[SystemOneProviderRead])
async def list_providers(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> list[SystemOneProviderRead]:
    configs = await _service.list_all(db, _tenant_id(request))
    return [_service.to_read(c) for c in configs]


@SystemOneRouter.post(
    "/providers",
    response_model=SystemOneProviderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    body: SystemOneProviderCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> SystemOneProviderRead:
    try:
        config = await _service.create(db, body, _tenant_id(request))
    except SystemOneProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc), detail=str(exc)
        )
    return _service.to_read(config)


@SystemOneRouter.get("/provider-types", response_model=list[SystemOneProviderTypeRead])
async def list_provider_types(
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> list[SystemOneProviderTypeRead]:
    """Selectable vendor (provider) types for the create dialog.

    Sourced from the backend ``SystemOneProviderType`` enum — the frontend
    never hardcodes the value list.
    """
    return [
        SystemOneProviderTypeRead(value=t.value, label=t.value)
        for t in SystemOneProviderType
    ]


@SystemOneRouter.get("/status", response_model=SystemOneStatus)
async def get_status(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> SystemOneStatus:
    """Whether an enabled System One model is configured (decision tool authoring gate).

    Tenant-scoped: reflects only the caller's tenant configuration.
    Returns provider/model identifiers only — never key material.
    """
    return await _service.get_status(db, _tenant_id(request))


@SystemOneRouter.patch("/providers/{provider_id}", response_model=SystemOneProviderRead)
async def update_provider(
    provider_id: uuid.UUID,
    body: SystemOneProviderUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> SystemOneProviderRead:
    try:
        config = await _service.update(db, provider_id, body, _tenant_id(request))
    except SystemOneProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc), detail=str(exc)
        )
    return _service.to_read(config)


@SystemOneRouter.post(
    "/providers/{provider_id}/test", response_model=SystemOneTestConnectionResult
)
async def test_provider_connection(
    provider_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> SystemOneTestConnectionResult:
    """Provider Test-connection: lightweight validation probe with the stored key.

    Returns a status-only result (``ok``/``message``/``latency_ms``) — no key
    material is ever returned or logged.
    """
    try:
        return await _service.test_connection(db, provider_id, _tenant_id(request))
    except SystemOneProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@SystemOneRouter.get(
    "/providers/{provider_id}/vendor-models",
    response_model=VendorModelSyncResult,
)
async def list_vendor_models(
    provider_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> VendorModelSyncResult:
    """Discover the vendor's model catalogue via its OpenAI-compatible
    ``GET {base_url}/models`` endpoint (bearer auth with the stored key,
    decrypted at call time only). Returns model ids — never key material.
    """
    try:
        models = await _service.list_vendor_models(
            db, provider_id, _tenant_id(request)
        )
    except SystemOneProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return VendorModelSyncResult(models=models)


@SystemOneRouter.post(
    "/providers/{provider_id}/import-models",
    response_model=SystemOneProviderRead,
)
async def import_vendor_models(
    provider_id: uuid.UUID,
    body: VendorModelImportRequest,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> SystemOneProviderRead:
    """Import vendor model ids as the provider's catalogue (enabled by
    default); seeds availability rows and keeps ``default_model`` valid."""
    try:
        config = await _service.import_vendor_models(
            db, provider_id, body.models, _tenant_id(request)
        )
    except SystemOneProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc), detail=str(exc)
        )
    return _service.to_read(config)


@SystemOneRouter.delete(
    "/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_provider(
    provider_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> None:
    try:
        await _service.delete(db, provider_id, _tenant_id(request))
    except SystemOneProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc), detail=str(exc)
        )


# ── Decision model catalogue endpoints (provider/model hierarchy) ────────────


@SystemOneRouter.get("/models", response_model=list[DecisionModelHierarchyEntry])
async def list_model_hierarchy(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> list[DecisionModelHierarchyEntry]:
    """Provider → model hierarchy with effective availability state."""
    hierarchy = await _catalogue.list_hierarchy(db, _tenant_id(request))
    return [DecisionModelHierarchyEntry.model_validate(entry) for entry in hierarchy]


@SystemOneRouter.get("/enabled-models", response_model=list[DecisionEnabledModelRead])
async def list_enabled_models(
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> list[DecisionEnabledModelRead]:
    """Flat enabled-models list (provider enabled + model enabled)."""
    enabled = await _catalogue.list_enabled_models(db, _tenant_id(request))
    return [
        DecisionEnabledModelRead(
            availability_id=m.availability_id,
            provider_id=m.provider_id,
            provider_type=m.provider_type,
            provider_display_name=m.provider_display_name,
            model_name=m.model_name,
        )
        for m in enabled
    ]


@SystemOneRouter.put(
    "/providers/{provider_id}/availability",
    response_model=SystemOneProviderRead,
)
async def set_provider_availability(
    provider_id: uuid.UUID,
    body: DecisionModelAvailabilityUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> SystemOneProviderRead:
    """Vendor-level enable/disable — cascades to the provider's models
    (manual per-model disables are preserved across the cascade)."""
    try:
        config = await _catalogue.set_vendor_disabled(
            db, provider_id, body.is_disabled, _tenant_id(request)
        )
    except SystemOneProviderError as exc:
        raise HTTPException(
            status_code=_provider_error_status(exc), detail=str(exc)
        )
    return _service.to_read(config)


@SystemOneRouter.put("/models/{availability_id}/availability")
async def set_model_availability(
    availability_id: uuid.UUID,
    body: DecisionModelAvailabilityUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> dict:
    """Per-model manual disable/enable (``disabled_reason=manual``)."""
    tenant_id = _tenant_id(request)
    # Resolve the row's provider within the tenant first (404 containment).
    from sqlalchemy import select

    from app.db.models.decision_model_availability import DecisionModelAvailability

    result = await db.execute(
        select(DecisionModelAvailability).where(
            DecisionModelAvailability.id == availability_id,
            DecisionModelAvailability.tenant_id == tenant_id
            if tenant_id is not None
            else DecisionModelAvailability.tenant_id.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Decision model {availability_id} not found",
        )
    updated = await _catalogue.set_model_disabled(
        db, row.decision_model_provider_id, row.model_name, body.is_disabled, tenant_id
    )
    return {
        "availability_id": str(updated.id),
        "model_name": updated.model_name,
        "is_disabled": updated.is_disabled,
        "disabled_reason": updated.disabled_reason.value,
    }


# ── Decision guardrails (FIX-20261014-003000) ────────────────────────────────
# Guardrail management embedded in the Decision Model Providers module.
# Reuses the existing model-usage guardrail stack (same
# ``model_guardrail_configurations`` table + ``model_usage_postures``), with
# ``config_source='decision_provider'`` so LLM guardrails are never mixed in
# and the decision pre-call check (``check_pre_call``) evaluates exactly
# these rows.

_guardrails = ModelUsageGuardrailService()


@SystemOneRouter.get(
    "/providers/{provider_id}/guardrails",
    response_model=list[DecisionGuardrailRead],
)
async def list_decision_guardrails(
    provider_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> list[DecisionGuardrailRead]:
    """Guardrails configured for one Decision Model Provider's models."""
    config = await _service.get(db, provider_id, _tenant_id(request))
    if config is None:
        raise HTTPException(
            status_code=404, detail=f"Decision provider {provider_id} not found"
        )
    configs = await _guardrails.list_decision_configurations(db, provider_id)
    return [DecisionGuardrailRead.model_validate(c) for c in configs]


@SystemOneRouter.post(
    "/providers/{provider_id}/guardrails",
    response_model=DecisionGuardrailRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decision_guardrail(
    provider_id: uuid.UUID,
    body: DecisionGuardrailCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> DecisionGuardrailRead:
    """Create one per-period guardrail for a decision provider model.

    A duplicate (provider, model, period) returns 409 with a deterministic
    error code (same contract as the LLM guardrail API).
    """
    tenant_id = _tenant_id(request)
    config = await _service.get(db, provider_id, tenant_id)
    if config is None:
        raise HTTPException(
            status_code=404, detail=f"Decision provider {provider_id} not found"
        )
    try:
        created = await _guardrails.create_decision_configuration(
            provider_id=provider_id,
            model_name=body.model_name,
            period=body.period,
            limit_value=body.limit_value,
            unit=body.unit,
            enforcement_posture=body.enforcement_posture,
            is_active=body.is_active,
            details=body.details,
            db=db,
        )
    except ModelGuardrailDuplicatePeriodError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "guardrail_period_conflict",
                "decision_provider_id": str(provider_id),
                "period": body.period.value,
            },
        )
    except ModelGuardrailDecisionProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return DecisionGuardrailRead.model_validate(created)


@SystemOneRouter.get(
    "/providers/{provider_id}/guardrails/posture",
    response_model=list[ModelUsagePostureRead],
)
async def get_decision_guardrail_posture(
    provider_id: uuid.UUID,
    request: Request,
    db: DbSession,
    refresh: bool = True,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "read")),
) -> list[ModelUsagePostureRead]:
    """Usage posture snapshots for one decision provider's guardrails."""
    config = await _service.get(db, provider_id, _tenant_id(request))
    if config is None:
        raise HTTPException(
            status_code=404, detail=f"Decision provider {provider_id} not found"
        )
    if refresh:
        await _guardrails.refresh_decision_posture_snapshots(db, provider_id)
    postures = await _guardrails.get_current_decision_posture(db, provider_id)
    return [ModelUsagePostureRead.model_validate(p) for p in postures]


@SystemOneRouter.put(
    "/guardrails/{config_id}",
    response_model=DecisionGuardrailRead,
)
async def update_decision_guardrail(
    config_id: uuid.UUID,
    body: DecisionGuardrailUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> DecisionGuardrailRead:
    """Partially update one decision guardrail (period is immutable)."""
    existing = await _guardrails.get_decision_configuration_scoped(
        config_id, db, _tenant_id(request)
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Decision guardrail not found")
    payload = body.model_dump(exclude_unset=True)
    updated = await _guardrails.update_configuration(config_id, db=db, **payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Decision guardrail not found")
    return DecisionGuardrailRead.model_validate(updated)


@SystemOneRouter.delete(
    "/guardrails/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_decision_guardrail(
    config_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")),
) -> None:
    """Hard-delete one decision guardrail (LLM rows are not reachable here)."""
    existing = await _guardrails.get_decision_configuration_scoped(
        config_id, db, _tenant_id(request)
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Decision guardrail not found")
    await _guardrails.delete_configuration(config_id, db)
