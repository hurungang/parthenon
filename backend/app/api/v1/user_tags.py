"""Tag Definition API router."""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import require_permission
from app.core.resource_types import RT_PERMISSIONS
from app.db.session import DbSession
from app.schemas.tags import TagDefinitionCreate, TagDefinitionRead, TagDefinitionUpdate
from app.services.permissions.tag_registry import TagRegistry

TagsRouter = APIRouter(prefix="/user-tags", tags=["Permissions: Tags"])


@TagsRouter.get("/definitions", response_model=List[TagDefinitionRead])
async def list_tag_definitions(
    db: DbSession,
    scope: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
) -> list:
    """List tag definitions; filterable by scope and resource_type. Any authenticated user."""
    return await TagRegistry().list_definitions(db, scope=scope, resource_type=resource_type)


@TagsRouter.post(
    "/definitions",
    response_model=TagDefinitionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tag_definition(
    body: TagDefinitionCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> object:
    """Create a tag definition. Admin only. Returns 409 if key+scope already exists."""
    return await TagRegistry().create_definition(
        db,
        key=body.key,
        scope=body.scope,
        resource_type=body.resource_type,
        description=body.description,
        allowed_values=body.allowed_values,
    )


@TagsRouter.patch("/definitions/{tag_id}", response_model=TagDefinitionRead)
async def update_tag_definition(
    tag_id: uuid.UUID,
    body: TagDefinitionUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> object:
    """Update a tag definition's description or allowed values. Admin only."""
    return await TagRegistry().update_definition(
        db,
        tag_id=tag_id,
        description=body.description,
        add_values=body.add_values,
        remove_values=body.remove_values,
    )


@TagsRouter.delete("/definitions/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag_definition(
    tag_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> None:
    """Delete a tag definition. Admin only. Returns 409 if referenced by policy conditions."""
    await TagRegistry().delete_definition(db, tag_id=tag_id)
