"""Policy utility endpoints."""
from typing import List

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.core.resource_types import MODULE_GROUPS, RT_SYSTEM_PERMISSIONS, ResourceTypeManifest, get_module_from_resource_type
from app.schemas.perm_roles import ResourceTypeRead

PolicyRouter = APIRouter(prefix="/policy", tags=["Permissions: Policy"])


@PolicyRouter.get("/resource-types", response_model=List[ResourceTypeRead])
async def list_resource_types(
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "read")),
) -> List[ResourceTypeRead]:
    """Return all resource types and their allowed actions with module grouping metadata."""
    return [
        ResourceTypeRead(
            resource_type=rt,
            actions=data["actions"],
            module_group=get_module_from_resource_type(rt) or "",
        )
        for rt, data in ResourceTypeManifest.items()
    ]
