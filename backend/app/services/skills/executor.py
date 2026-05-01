"""Skill Executor — resolves MCP tool bindings and executes skill via McpProxyEngine."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill
from app.services.mcp.proxy import McpProxyEngine, McpProxyError

logger = logging.getLogger(__name__)


class SkillExecutionError(Exception):
    """Raised when a skill execution fails."""


class SkillExecutor:
    """
    Resolves skill-to-MCP-tool bindings and executes them via McpProxyEngine.
    """

    def __init__(self, proxy_engine: McpProxyEngine | None = None) -> None:
        self._proxy = proxy_engine or McpProxyEngine()

    async def execute(
        self,
        skill_id: Any,
        tool_input: dict[str, Any],
        db: AsyncSession,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute all MCP tools bound to a skill in order.

        Args:
            skill_id: UUID of the Skill to execute.
            tool_input: Input parameters passed to each tool call.
            db: Database session.
            session_id: Optional specific MCP session to use.

        Returns:
            List of tool results in invocation order.
        """
        # Load skill with bindings
        result = await db.execute(
            select(Skill).where(Skill.id == skill_id).options(selectinload(Skill.tool_bindings))
        )
        skill = result.scalar_one_or_none()
        if not skill:
            raise SkillExecutionError(f"Skill {skill_id} not found")

        if not skill.tool_bindings:
            raise SkillExecutionError(f"Skill '{skill.name}' has no MCP tool bindings")

        # Sort by order
        bindings = sorted(skill.tool_bindings, key=lambda b: b.order)

        results: list[dict[str, Any]] = []
        for binding in bindings:
            tool = await db.get(McpTool, binding.tool_id)
            if not tool:
                raise SkillExecutionError(
                    f"MCP tool {binding.tool_id} bound to skill '{skill.name}' not found"
                )
            if not tool.is_active:
                raise SkillExecutionError(
                    f"MCP tool '{tool.name}' is inactive — sync the server to refresh"
                )

            # Load the server relationship
            await db.refresh(tool, ["server"])

            try:
                tool_result = await self._proxy.call_tool(
                    tool=tool,
                    tool_input=tool_input,
                    db=db,
                    session_id=session_id,
                )
                results.append({"tool": tool.name, "result": tool_result, "error": None})
            except McpProxyError as exc:
                logger.error("Tool '%s' failed during skill '%s': %s", tool.name, skill.name, exc)
                results.append({"tool": tool.name, "result": None, "error": str(exc)})

        return results
