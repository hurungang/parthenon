"""Public API router for agent output querying and CSV export.

All endpoints require JWT authentication via require_permission.
These are consumed by the frontend Agent Outputs admin page.

Routes:
  GET /api/v1/agent-outputs          — paginated, filterable agent output list
  GET /api/v1/agent-outputs/export   — CSV export with same filters
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import require_permission
from app.core.resource_types import RT_RESULT
from app.db.session import DbSession
from app.schemas.agent_outputs import AgentOutputListResponse, AgentOutputResponse
from app.services.outputs.service import OutputService

logger = logging.getLogger(__name__)

OutputRouter = APIRouter(
    prefix="/agent-outputs",
    tags=["Agent Outputs"],
)

_output_service = OutputService()


@OutputRouter.get("", response_model=AgentOutputListResponse)
async def list_agent_outputs(
    db: DbSession,
    data_type_id: uuid.UUID | None = Query(None, description="Filter by data type ID"),
    agent_type_id: uuid.UUID | None = Query(None, description="Filter by agent type ID"),
    date_from: str | None = Query(None, description="Filter outputs created on or after this date (ISO format)"),
    date_to: str | None = Query(None, description="Filter outputs created on or before this date (ISO format)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _: dict = Depends(require_permission(RT_RESULT, "read")),
) -> AgentOutputListResponse:
    """Query typed agent outputs with optional filters and pagination.

    Returns a paginated list of agent output records with resolved
    data type and agent type names for display.
    """
    logger.info(
        "Listing agent outputs: data_type=%s agent_type=%s page=%d",
        data_type_id, agent_type_id, page,
    )

    filters = {
        "data_type_id": data_type_id,
        "agent_type_id": agent_type_id,
        "date_from": date_from,
        "date_to": date_to,
        "page": page,
        "page_size": page_size,
    }

    items, total = await _output_service.list_outputs(db=db, filters=filters)

    # Resolve names for each output
    output_responses = []
    for output in items:
        data_type_name = None
        agent_type_name = None
        if output.data_type:
            data_type_name = output.data_type.name
        if output.agent_type:
            agent_type_name = output.agent_type.name

        output_responses.append(
            AgentOutputResponse(
                id=output.id,
                data_type_id=output.data_type_id,
                agent_type_id=output.agent_type_id,
                execution_session_id=output.execution_session_id,
                field_values=output.field_values,
                validation_status=output.validation_status.value,
                raw_output=output.raw_output,
                created_at=output.created_at,
                data_type_name=data_type_name,
                agent_type_name=agent_type_name,
            )
        )

    return AgentOutputListResponse(
        items=output_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@OutputRouter.get("/export")
async def export_agent_outputs_csv(
    db: DbSession,
    data_type_id: uuid.UUID | None = Query(None, description="Filter by data type ID"),
    agent_type_id: uuid.UUID | None = Query(None, description="Filter by agent type ID"),
    date_from: str | None = Query(None, description="Filter outputs created on or after this date (ISO format)"),
    date_to: str | None = Query(None, description="Filter outputs created on or before this date (ISO format)"),
    _: dict = Depends(require_permission(RT_RESULT, "read")),
) -> StreamingResponse:
    """Export filtered agent outputs as a CSV file.

    Accepts the same filter parameters as the list endpoint (without
    pagination). Returns a streaming CSV response with Content-Disposition
    attachment header.
    """
    logger.info(
        "Exporting agent outputs CSV: data_type=%s agent_type=%s",
        data_type_id, agent_type_id,
    )

    filters = {
        "data_type_id": data_type_id,
        "agent_type_id": agent_type_id,
        "date_from": date_from,
        "date_to": date_to,
    }

    csv_str = await _output_service.export_csv(db=db, filters=filters)

    # Generate filename with current date
    filename = f"agent-outputs-{datetime.now().strftime('%Y-%m-%d')}.csv"

    return StreamingResponse(
        iter([csv_str]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(csv_str)),
        },
    )
