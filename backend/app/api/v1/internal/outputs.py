"""Internal API endpoints for agent output validation and persistence.

All endpoints require service certificate authentication (mTLS).
These are called by Agent Runtime during and after execution.

Routes:
  POST /api/v1/internal/validate-output    — validate payload against data type schema
  POST /api/v1/internal/agent-outputs       — persist typed output record
  GET  /api/v1/internal/agent-outputs       — query typed outputs with filters
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import require_service_certificate
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agent_output import AgentOutput
from app.db.models.agents import AgentType
from app.db.session import DbSession
from app.schemas.agent_outputs import (
    AgentOutputCreate,
    AgentOutputListResponse,
    AgentOutputResponse,
    ValidateOutputRequest,
    ValidationResult,
)
from app.services.outputs.service import OutputService
from app.services.validation.schema_validation_service import SchemaValidationService

logger = logging.getLogger(__name__)

InternalOutputsRouter = APIRouter(
    prefix="/internal",
    tags=["internal"],
)

_output_service = OutputService()
_validation_service = SchemaValidationService()


# ── Validation Endpoint ─────────────────────────────────────────────────────────


@InternalOutputsRouter.post(
    "/validate-output",
    response_model=ValidationResult,
    dependencies=[Depends(require_service_certificate)],
    summary="Validate payload against data type schema",
)
async def validate_output(
    body: ValidateOutputRequest,
    db: DbSession,
) -> ValidationResult:
    """Validate a payload against a data type's field schema.

    Fetches the data type by ID, then validates the payload fields
    against the schema definition. Returns field-level errors for
    invalid values.
    """
    logger.info(
        "Validating output against data type %s", body.data_type_id
    )

    data_type = await db.get(AgentDataType, body.data_type_id)
    if not data_type:
        raise HTTPException(
            status_code=404,
            detail=f"Data type {body.data_type_id} not found",
        )

    fields = data_type.fields or []
    result = _validation_service.validate(body.payload or {}, fields)

    logger.info(
        "Validation result for data type %s: valid=%s errors=%d",
        body.data_type_id,
        result.valid,
        len(result.errors),
    )
    return result


# ── Persistence Endpoint ────────────────────────────────────────────────────────


@InternalOutputsRouter.post(
    "/agent-outputs",
    response_model=AgentOutputResponse,
    status_code=201,
    dependencies=[Depends(require_service_certificate)],
    summary="Persist a typed agent output record",
)
async def create_internal_output(
    body: AgentOutputCreate,
    db: DbSession,
) -> AgentOutputResponse:
    """Persist a typed output record.

    Called by Agent Runtime after validation to store the agent's
    typed output with the assigned data type reference and validation
    status.
    """
    logger.info(
        "Persisting agent output for session %s, data type %s",
        body.execution_session_id,
        body.data_type_id,
    )

    # Verify the data type exists
    data_type = await db.get(AgentDataType, body.data_type_id)
    if not data_type:
        raise HTTPException(
            status_code=404,
            detail=f"Data type {body.data_type_id} not found",
        )

    # Verify the agent type exists
    agent_type = await db.get(AgentType, body.agent_type_id)
    if not agent_type:
        raise HTTPException(
            status_code=404,
            detail=f"Agent type {body.agent_type_id} not found",
        )

    output = await _output_service.save_typed(
        db=db,
        data_type_id=body.data_type_id,
        agent_type_id=body.agent_type_id,
        session_id=body.execution_session_id,
        field_values=body.field_values,
        validation_status=body.validation_status,
        raw_output=body.raw_output,
    )

    return AgentOutputResponse(
        id=output.id,
        data_type_id=output.data_type_id,
        agent_type_id=output.agent_type_id,
        execution_session_id=output.execution_session_id,
        field_values=output.field_values,
        validation_status=output.validation_status.value,
        raw_output=output.raw_output,
        created_at=output.created_at,
        data_type_name=data_type.name,
        agent_type_name=agent_type.name,
    )


# ── Query Endpoint ──────────────────────────────────────────────────────────────


@InternalOutputsRouter.get(
    "/agent-outputs",
    response_model=AgentOutputListResponse,
    dependencies=[Depends(require_service_certificate)],
    summary="Query typed agent outputs with filters",
)
async def query_internal_outputs(
    db: DbSession,
    data_type_id: uuid.UUID | None = Query(None, description="Filter by data type"),
    agent_type_id: uuid.UUID | None = Query(None, description="Filter by agent type"),
    date_from: str | None = Query(None, description="Filter outputs created on or after this date (ISO format)"),
    date_to: str | None = Query(None, description="Filter outputs created on or before this date (ISO format)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> AgentOutputListResponse:
    """Query typed agent outputs with optional filters and pagination.

    Used by the query_result system tool and internal services.
    """
    logger.info(
        "Querying agent outputs: data_type=%s agent_type=%s page=%d",
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
