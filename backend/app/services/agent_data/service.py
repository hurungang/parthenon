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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

        Args:
            db: Database session.
            data_name: Optional filter by data name.
            agent_type_id: Optional filter by agent type ID.
            session_id: Optional filter by session ID.
            limit: Maximum number of records to return (default 50).
            offset: Number of records to skip (default 0).

        Returns:
            List of matching AgentData records ordered by created_at desc.

        Raises:
            ValueError: If all filter arguments are None.
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
