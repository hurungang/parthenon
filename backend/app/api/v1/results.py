"""Results API router — query endpoints for the result repository."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_permission
from app.core.resource_types import RT_RESULT
from app.db.session import DbSession
from app.schemas.notifications import ResultRecordRead
from app.services.results.store import ResultStore

logger = logging.getLogger(__name__)

ResultRouter = APIRouter(prefix="/results", tags=["Results"])

_store = ResultStore()


@ResultRouter.get("", response_model=list[ResultRecordRead])
async def list_results(
    db: DbSession,
    _: dict = Depends(require_permission(RT_RESULT, "read")),
    agent_type_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    return await _store.list_records(
        db=db,
        agent_type_id=agent_type_id,
        limit=limit,
        offset=offset,
    )


@ResultRouter.get("/{result_id}", response_model=ResultRecordRead)
async def get_result(
    result_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_RESULT, "read")),
):
    record = await _store.get(result_id, db)
    if not record:
        raise HTTPException(status_code=404, detail="Result record not found")
    return record
