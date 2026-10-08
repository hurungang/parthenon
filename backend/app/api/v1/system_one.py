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
from app.db.session import DbSession
from app.schemas.system_one import (
    SystemOneProviderCreate,
    SystemOneProviderRead,
    SystemOneProviderUpdate,
    SystemOneStatus,
    SystemOneTestConnectionResult,
)
from app.services.system_one.provider_config_service import (
    SystemOneProviderConfigService,
    SystemOneProviderError,
)

logger = logging.getLogger(__name__)

SystemOneRouter = APIRouter(prefix="/system-one", tags=["System One"])

_service = SystemOneProviderConfigService()


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
    config = await _service.create(db, body, _tenant_id(request))
    return _service.to_read(config)


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
        raise HTTPException(status_code=404, detail=str(exc))
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
        raise HTTPException(status_code=404, detail=str(exc))
