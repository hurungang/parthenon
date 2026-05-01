"""Result Store — persists structured agent/SOP outputs; registers save_result MCP tool."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.results import ResultRecord

logger = logging.getLogger(__name__)

# MCP tool definition for save_result
SAVE_RESULT_TOOL_DEFINITION = {
    "name": "save_result",
    "description": "Save a structured result from the current agent or SOP execution.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Optional title for the result",
            },
            "payload": {
                "type": "object",
                "description": "Structured result data to persist",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for filtering",
            },
        },
        "required": ["payload"],
    },
}


class ResultStore:
    """
    Persists structured result records and exposes the save_result MCP tool.
    """

    async def save(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        title: str | None = None,
        tags: list[str] | None = None,
        agent_type_id: Any | None = None,
        agent_instance_id: Any | None = None,
        conversation_session_id: Any | None = None,
        content_type: str = "application/json",
    ) -> ResultRecord:
        """Persist a structured result record."""
        record = ResultRecord(
            agent_type_id=agent_type_id,
            agent_instance_id=agent_instance_id,
            conversation_session_id=conversation_session_id,
            title=title,
            content_type=content_type,
            payload=payload,
            tags=tags,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        logger.info("Saved result record %s (title=%s)", record.id, title)
        return record

    async def get(self, result_id: Any, db: AsyncSession) -> ResultRecord | None:
        """Retrieve a result record by ID."""
        return await db.get(ResultRecord, result_id)

    async def list_records(
        self,
        db: AsyncSession,
        agent_type_id: Any | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ResultRecord]:
        """List result records with optional filtering."""
        query = select(ResultRecord).order_by(ResultRecord.created_at.desc())
        if agent_type_id:
            query = query.where(ResultRecord.agent_type_id == agent_type_id)
        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return list(result.scalars().all())

    def get_mcp_tool_definition(self) -> dict[str, Any]:
        """Return the MCP tool definition for save_result."""
        return SAVE_RESULT_TOOL_DEFINITION

    async def handle_mcp_call(
        self, arguments: dict[str, Any], db: AsyncSession, **context: Any
    ) -> dict[str, Any]:
        """Handle a save_result MCP tool call."""
        record = await self.save(
            payload=arguments["payload"],
            db=db,
            title=arguments.get("title"),
            tags=arguments.get("tags"),
            agent_type_id=context.get("agent_type_id"),
            agent_instance_id=context.get("agent_instance_id"),
            conversation_session_id=context.get("conversation_session_id"),
        )
        return {"result_id": str(record.id), "saved": True}
