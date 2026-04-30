"""Policy utility endpoints."""
from typing import List

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.core.resource_types import RT_ROLE, ResourceTypeManifest
from app.schemas.perm_roles import ResourceTypeRead

PolicyRouter = APIRouter(prefix="/policy", tags=["Permissions: Policy"])


@PolicyRouter.get("/resource-types", response_model=List[ResourceTypeRead])
async def list_resource_types(
    _: dict = Depends(require_permission(RT_ROLE, "read")),
) -> List[ResourceTypeRead]:
    """Return all resource types and their allowed actions. Requires role:read."""
    return [
        ResourceTypeRead(resource_type=rt, actions=data["actions"])
        for rt, data in ResourceTypeManifest.items()
    ]
