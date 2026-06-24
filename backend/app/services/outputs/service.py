"""OutputService — typed agent output persistence and querying.

Provides save_typed, list_outputs, get_output, and export_csv operations
for AgentOutput records. All database access is through SQLAlchemy async
sessions (CC-owned database).
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent_output import AgentOutput, AgentOutputValidationStatus
from app.db.models.agents import AgentJob, AgentType

logger = logging.getLogger(__name__)


class OutputService:
    """Business logic for typed agent output persistence and querying."""

    async def save_typed(
        self,
        db: AsyncSession,
        data_type_id: uuid.UUID,
        agent_type_id: uuid.UUID,
        session_id: uuid.UUID,
        field_values: dict[str, Any] | None,
        validation_status: str,
        raw_output: str | None = None,
    ) -> AgentOutput:
        """Persist a typed AgentOutput record and link to the session.

        Creates an AgentOutput row and updates AgentJob.output_id to link
        the session to the output record.

        Args:
            db: Database session.
            data_type_id: FK to AgentDataType.
            agent_type_id: FK to AgentType.
            session_id: FK to AgentJob (execution session).
            field_values: Validated field values (or None on validation error).
            validation_status: "valid" or "validation_error".
            raw_output: Unstructured fallback text.

        Returns:
            The created AgentOutput record.
        """
        status_enum = (
            AgentOutputValidationStatus.valid
            if validation_status == "valid"
            else AgentOutputValidationStatus.validation_error
        )

        output = AgentOutput(
            data_type_id=data_type_id,
            agent_type_id=agent_type_id,
            execution_session_id=session_id,
            field_values=field_values,
            validation_status=status_enum,
            raw_output=raw_output,
        )
        db.add(output)
        await db.flush()
        await db.refresh(output)

        # Wire the output_id back to the AgentJob for convenience linking
        job = await db.get(AgentJob, session_id)
        if job:
            job.output_id = output.id
            await db.flush()
            logger.info(
                "Linked output %s to session %s (job.output_id=%s)",
                output.id, session_id, job.output_id,
            )
        else:
            logger.warning("Could not find AgentJob for session %s", session_id)

        logger.info(
            "Saved typed output %s for session %s (status=%s, fields=%s)",
            output.id, session_id, validation_status, list(output.field_values.keys()) if output.field_values else None,
        )
        return output

    async def list_outputs(
        self,
        db: AsyncSession,
        filters: dict[str, Any] | None = None,
    ) -> tuple[list[AgentOutput], int]:
        """List agent outputs with optional filters and pagination.

        Supports filters: data_type_id, agent_type_id, date_from, date_to,
        page, page_size.

        Args:
            db: Database session.
            filters: Dict of filter parameters.

        Returns:
            Tuple of (items, total_count).
        """
        filters = filters or {}
        query = select(AgentOutput).options(
            selectinload(AgentOutput.data_type),
            selectinload(AgentOutput.agent_type),
            selectinload(AgentOutput.execution_session),
        )

        # Apply filters
        if filters.get("data_type_id"):
            query = query.where(
                AgentOutput.data_type_id == filters["data_type_id"]
            )
        if filters.get("agent_type_id"):
            query = query.where(
                AgentOutput.agent_type_id == filters["agent_type_id"]
            )
        if filters.get("date_from"):
            date_from = filters["date_from"]
            if isinstance(date_from, str):
                date_from = datetime.fromisoformat(date_from)
            query = query.where(AgentOutput.created_at >= date_from)
        if filters.get("date_to"):
            date_to = filters["date_to"]
            if isinstance(date_to, str):
                date_to = datetime.fromisoformat(date_to)
            query = query.where(AgentOutput.created_at <= date_to)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar_one()

        # Apply pagination
        page = filters.get("page", 1)
        page_size = filters.get("page_size", 20)
        query = (
            query.order_by(AgentOutput.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        result = await db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def get_output(
        self,
        db: AsyncSession,
        output_id: uuid.UUID,
    ) -> AgentOutput | None:
        """Get a single output by ID with relationships loaded."""
        result = await db.execute(
            select(AgentOutput)
            .where(AgentOutput.id == output_id)
            .options(
                selectinload(AgentOutput.data_type),
                selectinload(AgentOutput.agent_type),
                selectinload(AgentOutput.execution_session),
            )
        )
        return result.scalar_one_or_none()

    async def export_csv(
        self,
        db: AsyncSession,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Export filtered outputs as a CSV string.

        Column headers are derived from the data type's field definitions
        when a single data_type_id filter is applied, falling back to
        base columns otherwise.

        Args:
            db: Database session.
            filters: Same filter params as list_outputs (without pagination).

        Returns:
            CSV-formatted string.
        """
        filters = filters or {}
        query = select(AgentOutput).options(
            selectinload(AgentOutput.data_type),
            selectinload(AgentOutput.agent_type),
        )

        # Apply filters (same as list_outputs but no pagination)
        if filters.get("data_type_id"):
            query = query.where(
                AgentOutput.data_type_id == filters["data_type_id"]
            )
        if filters.get("agent_type_id"):
            query = query.where(
                AgentOutput.agent_type_id == filters["agent_type_id"]
            )
        if filters.get("date_from"):
            date_from = filters["date_from"]
            if isinstance(date_from, str):
                date_from = datetime.fromisoformat(date_from)
            query = query.where(AgentOutput.created_at >= date_from)
        if filters.get("date_to"):
            date_to = filters["date_to"]
            if isinstance(date_to, str):
                date_to = datetime.fromisoformat(date_to)
            query = query.where(AgentOutput.created_at <= date_to)

        query = query.order_by(AgentOutput.created_at.desc())

        result = await db.execute(query)
        items = list(result.scalars().all())

        # Determine columns
        base_columns = ["id", "data_type", "agent_type", "validation_status", "created_at"]
        field_columns: list[str] = []

        # Derive field columns from the data type schema
        if items and items[0].data_type and items[0].data_type.fields:
            for field in items[0].data_type.fields:
                if isinstance(field, dict) and field.get("name"):
                    field_columns.append(field["name"])

        columns = base_columns + field_columns

        # Write CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)

        for item in items:
            row = []
            for col in columns:
                if col == "id":
                    row.append(str(item.id))
                elif col == "data_type":
                    row.append(item.data_type.name if item.data_type else "")
                elif col == "agent_type":
                    row.append(item.agent_type.name if item.agent_type else "")
                elif col == "validation_status":
                    row.append(item.validation_status.value)
                elif col == "created_at":
                    row.append(item.created_at.isoformat() if item.created_at else "")
                elif col in field_columns and item.field_values:
                    row.append(str(item.field_values.get(col, "")))
                else:
                    row.append("")
            writer.writerow(row)

        csv_str = output.getvalue()
        output.close()
        return csv_str
