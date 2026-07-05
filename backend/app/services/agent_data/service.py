"""AgentDataService — persistence and querying of named intermediate agent data.

All database access is through SQLAlchemy async sessions (CC-owned database).
At least one filter must be provided to query_by_filters to prevent
unbounded full-table scans.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agent_data import AgentData

logger = logging.getLogger(__name__)


class AgentDataService:
    """Business logic for AgentData persistence and querying."""

    async def save(
        self,
        db: AsyncSession,
        session_id: uuid.UUID | str,
        data_name: str,
        data_value: Any,
        agent_type_id: uuid.UUID | str | None = None,
        data_type: str = "json",
    ) -> AgentData:
        """Persist a named AgentData record.

        Args:
            db: Database session.
            session_id: FK to AgentJob (execution session).
            data_name: Name key for this data item.
            data_value: JSON-serialisable value to store.
            agent_type_id: Optional FK to AgentType.
            data_type: Value type hint (default "json").

        Returns:
            The created AgentData record.
        """
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)
        if isinstance(agent_type_id, str):
            agent_type_id = uuid.UUID(agent_type_id)

        record = AgentData(
            agent_type_id=agent_type_id,
            session_id=session_id,
            data_name=data_name,
            data_value=data_value,
            data_type=data_type,
            is_active=True,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)

        logger.info(
            "Saved AgentData %s (session=%s, data_name=%s, data_type=%s)",
            record.id,
            session_id,
            data_name,
            data_type,
        )
        return record

    async def list_all(
        self,
        db: AsyncSession,
        data_name: str | None = None,
        agent_type_id: uuid.UUID | str | None = None,
        session_id: uuid.UUID | str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AgentData], int]:
        """Public paginated listing of active AgentData records.

        All filters are optional — when none are provided, returns all active
        records ordered by created_at DESC.

        Args:
            db: Database session.
            data_name: Optional exact match filter on data_name.
            agent_type_id: Optional filter by agent type ID.
            session_id: Optional filter by session ID.
            page: Page number (1-indexed, default 1).
            page_size: Items per page (default 20).

        Returns:
            Tuple of (list of AgentData records, total count).
        """
        if isinstance(agent_type_id, str):
            agent_type_id = uuid.UUID(agent_type_id)
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)

        base = select(AgentData).where(AgentData.is_active.is_(True))

        # Eager-load agent_type to avoid MissingGreenlet errors when
        # accessing record.agent_type.name in the response layer.
        base = base.options(selectinload(AgentData.agent_type))

        if data_name is not None:
            base = base.where(AgentData.data_name == data_name)
        if agent_type_id is not None:
            base = base.where(AgentData.agent_type_id == agent_type_id)
        if session_id is not None:
            base = base.where(AgentData.session_id == session_id)

        count_q = select(func.count()).select_from(AgentData).where(
            AgentData.is_active.is_(True)
        )
        if data_name is not None:
            count_q = count_q.where(AgentData.data_name == data_name)
        if agent_type_id is not None:
            count_q = count_q.where(AgentData.agent_type_id == agent_type_id)
        if session_id is not None:
            count_q = count_q.where(AgentData.session_id == session_id)

        total_result = await db.execute(count_q)
        total = total_result.scalar() or 0

        offset = (page - 1) * page_size
        query = base.order_by(AgentData.created_at.desc()).offset(offset).limit(page_size)

        result = await db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def get_by_id(
        self,
        db: AsyncSession,
        record_id: uuid.UUID,
    ) -> AgentData | None:
        """Get a single AgentData record by ID.

        Args:
            db: Database session.
            record_id: UUID of the record to retrieve.

        Returns:
            The AgentData record or None if not found or inactive.
        """
        result = await db.execute(
            select(AgentData)
            .options(selectinload(AgentData.agent_type))
            .where(
                AgentData.id == record_id,
                AgentData.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def query_by_filters(
        self,
        db: AsyncSession,
        data_name: str | None = None,
        agent_type_id: uuid.UUID | str | None = None,
        session_id: uuid.UUID | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentData]:
        """Query AgentData records by one or more filters.

        At least one of data_name, agent_type_id, or session_id must be
        provided to prevent unbounded full-table scans.
        """
        if data_name is None and agent_type_id is None and session_id is None:
            raise ValueError(
                "At least one filter (data_name, agent_type_id, or session_id) "
                "must be provided to query AgentData records."
            )

        if isinstance(agent_type_id, str):
            agent_type_id = uuid.UUID(agent_type_id)
        if isinstance(session_id, str):
            session_id = uuid.UUID(session_id)

        query = select(AgentData).where(AgentData.is_active.is_(True))

        if data_name is not None:
            query = query.where(AgentData.data_name == data_name)
        if agent_type_id is not None:
            query = query.where(AgentData.agent_type_id == agent_type_id)
        if session_id is not None:
            query = query.where(AgentData.session_id == session_id)

        query = (
            query.order_by(AgentData.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await db.execute(query)
        return list(result.scalars().all())
