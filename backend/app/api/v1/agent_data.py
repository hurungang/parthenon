"""Public API router for agent data querying.

Provides read-only access to intermediate AgentData records saved by agents
via the save_data system tool during execution.

Routes:
  GET /api/v1/agent-data          — paginated, filterable agent data list
  GET /api/v1/agent-data/{id}     — single agent data record with full JSON value
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_DATA
from app.db.session import DbSession
from app.schemas.agent_data import AgentDataListResponse, AgentDataResponse
from app.services.agent_data.service import AgentDataService

logger = logging.getLogger(__name__)

AgentDataRouter = APIRouter(
    prefix="/agent-data",
    tags=["Agent Data"],
)

_data_service = AgentDataService()


@AgentDataRouter.get("", response_model=AgentDataListResponse)
async def list_agent_data(
    db: DbSession,
    data_name: str | None = Query(None, description="Exact match filter on data name"),
    agent_type_id: uuid.UUID | None = Query(None, description="Filter by agent type ID"),
    session_id: uuid.UUID | None = Query(None, description="Filter by session ID"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _: dict = Depends(require_permission(RT_AGENT_DATA, "read")),
) -> AgentDataListResponse:
    """Query agent data records with optional filters and pagination.

    Returns a paginated list of intermediate AgentData records saved by agents
    during execution, with resolved agent type names for display.
    """
    logger.info("Listing agent data: data_name=%s agent_type=%s page=%d", data_name, agent_type_id, page)

    items, total = await _data_service.list_all(
        db=db,
        data_name=data_name,
        agent_type_id=agent_type_id,
        session_id=session_id,
        page=page,
        page_size=page_size,
    )

    responses = []
    for record in items:
        agent_type_name = record.agent_type.name if record.agent_type else None
        responses.append(
            AgentDataResponse(
                id=record.id,
                agent_type_id=record.agent_type_id,
                session_id=record.session_id,
                data_name=record.data_name,
                data_value=record.data_value,
                data_type=record.data_type,
                is_active=record.is_active,
                created_at=record.created_at,
                agent_type_name=agent_type_name,
            )
        )

    return AgentDataListResponse(
        items=responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@AgentDataRouter.get("/{record_id}", response_model=AgentDataResponse)
async def get_agent_data(
    record_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_DATA, "read")),
) -> AgentDataResponse:
    """Get a single agent data record by ID with its full data value."""
    logger.info("Getting agent data: record_id=%s", record_id)

    record = await _data_service.get_by_id(db=db, record_id=record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"AgentData {record_id} not found")

    agent_type_name = record.agent_type.name if record.agent_type else None

    return AgentDataResponse(
        id=record.id,
        agent_type_id=record.agent_type_id,
        session_id=record.session_id,
        data_name=record.data_name,
        data_value=record.data_value,
        data_type=record.data_type,
        is_active=record.is_active,
        created_at=record.created_at,
        agent_type_name=agent_type_name,
    )
