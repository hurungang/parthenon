"""Data Type API router — CRUD endpoints for the Agent Data Type registry."""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_DATA_TYPES
from app.db.session import DbSession
from app.schemas.data_types import (
    DataTypeCreate,
    DataTypeFieldResponse,
    DataTypeListResponse,
    DataTypeResponse,
    DataTypeUpdate,
)
from app.services.data_types.service import (
    DataTypeConflictError,
    DataTypeDuplicateError,
    DataTypeNotFoundError,
    DataTypeService,
)

logger = logging.getLogger(__name__)

DataTypeRouter = APIRouter(prefix="/data-types", tags=["Data Types"])

_service = DataTypeService()


VALID_FIELD_TYPES = frozenset({"string", "number", "boolean", "date", "enum"})


def _to_field_response(fields: list) -> list[DataTypeFieldResponse]:
    """Convert raw field dicts from the DB to DataTypeFieldResponse objects.

    Legacy data may contain fields with unsupported types (e.g. ``array``,
    ``object`` from JSON Schema output_schema migration). These are coerced
    to ``string`` to prevent Pydantic validation failures.
    """
    result: list[DataTypeFieldResponse] = []
    for f in fields:
        if not isinstance(f, dict):
            result.append(f)
            continue
        field_type = f.get("type", "string")
        if field_type not in VALID_FIELD_TYPES:
            f = {**f, "type": "string"}
        result.append(DataTypeFieldResponse(**f))
    return result


@DataTypeRouter.get("", response_model=DataTypeListResponse)
async def list_data_types(
    db: DbSession,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, description="Search by name, slug, or description"),
    usage: bool = Query(False, description="Include referencing agent type info"),
    _: dict = Depends(require_permission(RT_AGENT_DATA_TYPES, "read")),
) -> DataTypeListResponse:
    """List data types with pagination, optional search, and usage info."""
    items, total = await _service.list(
        db=db,
        page=page,
        page_size=page_size,
        search=search,
        usage=usage,
    )

    dt_responses = []
    for dt in items:
        fields = _to_field_response(getattr(dt, "fields", []) or [])
        dt_responses.append(
            DataTypeResponse(
                id=dt.id,
                name=dt.name,
                slug=dt.slug,
                description=dt.description,
                fields=fields,
                created_at=dt.created_at,
                updated_at=dt.updated_at,
            )
        )

    return DataTypeListResponse(
        items=dt_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@DataTypeRouter.post(
    "", response_model=DataTypeResponse, status_code=status.HTTP_201_CREATED
)
async def create_data_type(
    body: DataTypeCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_DATA_TYPES, "create")),
) -> DataTypeResponse:
    """Create a new data type with typed fields."""
    try:
        fields_dicts = [f.model_dump() for f in body.fields]
        dt = await _service.create(
            db=db,
            name=body.name,
            slug=body.slug,
            description=body.description,
            fields=fields_dicts,
        )
    except DataTypeDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return DataTypeResponse(
        id=dt.id,
        name=dt.name,
        slug=dt.slug,
        description=dt.description,
        fields=_to_field_response(dt.fields),
        created_at=dt.created_at,
        updated_at=dt.updated_at,
    )


@DataTypeRouter.get("/{data_type_id}", response_model=DataTypeResponse)
async def get_data_type(
    data_type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_DATA_TYPES, "read")),
) -> DataTypeResponse:
    """Get a single data type by ID."""
    dt = await _service.get(db=db, id=data_type_id)
    if not dt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data type {data_type_id} not found",
        )

    return DataTypeResponse(
        id=dt.id,
        name=dt.name,
        slug=dt.slug,
        description=dt.description,
        fields=_to_field_response(dt.fields),
        created_at=dt.created_at,
        updated_at=dt.updated_at,
    )


@DataTypeRouter.put("/{data_type_id}", response_model=DataTypeResponse)
async def update_data_type(
    data_type_id: uuid.UUID,
    body: DataTypeUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_DATA_TYPES, "update")),
) -> DataTypeResponse:
    """Update an existing data type."""
    try:
        fields_dicts = (
            [f.model_dump() for f in body.fields] if body.fields is not None else None
        )
        dt = await _service.update(
            db=db,
            id=data_type_id,
            name=body.name,
            slug=body.slug,
            description=body.description,
            fields=fields_dicts,
        )
    except DataTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DataTypeDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return DataTypeResponse(
        id=dt.id,
        name=dt.name,
        slug=dt.slug,
        description=dt.description,
        fields=_to_field_response(dt.fields),
        created_at=dt.created_at,
        updated_at=dt.updated_at,
    )


@DataTypeRouter.delete(
    "/{data_type_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_data_type(
    data_type_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_DATA_TYPES, "delete")),
) -> None:
    """Delete a data type.

    Returns 204 on success.
    Returns 409 if the data type is referenced by any agent types.
    """
    try:
        await _service.delete(db=db, id=data_type_id)
    except DataTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DataTypeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"Cannot delete data type: referenced by agent types",
                "referencing_agent_types": exc.referencing_types,
            },
        )
