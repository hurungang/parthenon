"""Results API router — query endpoints for the result repository."""
import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_TRAILS
from app.db.session import DbSession
from app.db.models.results import DecisionExecutionResult
from app.schemas.decision_tools import DecisionExecutionResultRead
from app.schemas.notifications import ResultRecordRead
from app.services.results.store import ResultStore

logger = logging.getLogger(__name__)

ResultRouter = APIRouter(prefix="/results", tags=["Results"])

_store = ResultStore()


@ResultRouter.get("/decision", response_model=list[DecisionExecutionResultRead])
async def list_decision_results(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
    decision_tool_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DecisionExecutionResultRead]:
    """Query persisted decision execution results (tool/session/date filters)."""
    query = select(DecisionExecutionResult).order_by(
        DecisionExecutionResult.created_at.desc()
    )
    if decision_tool_id is not None:
        query = query.where(
            DecisionExecutionResult.decision_tool_id == decision_tool_id
        )
    if session_id is not None:
        query = query.where(
            DecisionExecutionResult.conversation_session_id == session_id
        )
    if date_from is not None:
        query = query.where(DecisionExecutionResult.created_at >= date_from)
    if date_to is not None:
        query = query.where(DecisionExecutionResult.created_at <= date_to)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@ResultRouter.get("", response_model=list[ResultRecordRead])
async def list_results(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
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
    _: dict = Depends(require_permission(RT_AGENT_TRAILS, "read")),
):
    record = await _store.get(result_id, db)
    if not record:
        raise HTTPException(status_code=404, detail="Result record not found")
    return record
