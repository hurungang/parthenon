"""Skill Executor — resolves MCP tool bindings and executes skill via McpProxyEngine.

Virtual bindings are handled like the MCP tool-registry bridge dispatches them:
- system tools are DB-seeded rows and flow through the proxy engine, and
- decision tools (virtual uuid5 ids, no ``mcp_tools`` row) execute through
  the internal decision execution path (:class:`DecisionExecutionEngine`) —
  the same engine backing ``/internal/system-tools/decision/execute``.
"""
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.services.agents.tool_naming import build_tool_name
from app.services.mcp.proxy import McpProxyEngine, McpProxyError

logger = logging.getLogger(__name__)


class SkillExecutionError(Exception):
    """Raised when a skill execution fails."""


class SkillExecutor:
    """
    Resolves skill-to-MCP-tool bindings and executes them via McpProxyEngine.
    """

    def __init__(
        self,
        proxy_engine: McpProxyEngine | None = None,
        decision_engine: Any | None = None,
    ) -> None:
        self._proxy = proxy_engine or McpProxyEngine()
        self._decision_engine = decision_engine

    def _get_decision_engine(self) -> Any:
        """Lazily construct the DecisionExecutionEngine (import-isolated)."""
        if self._decision_engine is None:
            from app.services.system_one.decision_engine import DecisionExecutionEngine

            self._decision_engine = DecisionExecutionEngine()
        return self._decision_engine

    async def _execute_decision_binding(
        self,
        db: AsyncSession,
        skill: Skill,
        tool_id: Any,
        tool_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a virtual decision-tool binding via the decision engine.

        Returns a result entry, or None when ``tool_id`` does not refer to a
        decision tool of the skill's tenant.
        """
        from app.services.system_one.decision_engine import DecisionExecutionError

        tool = await resolve_decision_tool(db, tool_id, getattr(skill, "tenant_id", None))
        if tool is None:
            return None
        canonical_name = build_tool_name("decision", tool.name)
        try:
            decision_result = await self._get_decision_engine().execute(
                db=db,
                tool=tool,
                input_state=tool_input,
                tenant_id=getattr(skill, "tenant_id", None),
            )
        except DecisionExecutionError as exc:
            logger.error(
                "Decision tool '%s' failed during skill '%s': %s", tool.name, skill.name, exc
            )
            return {"tool": canonical_name, "result": None, "error": str(exc)}
        return {
            "tool": canonical_name,
            "result": {
                "decision_tool_id": str(tool.id),
                "tool_name": tool.name,
                "outcome": decision_result.outcome.value,
                "status": decision_result.status.value,
                "answers": (decision_result.answers or {}).get("answers", {}),
                "input_state_snapshot": decision_result.input_state_snapshot,
                "provider_model": decision_result.provider_model,
                "error_message": decision_result.error_message,
            },
            "error": None,
        }

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
            select(Skill)
            .where(Skill.id == skill_id)
            .options(selectinload(Skill.tool_bindings))
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

            # Virtual decision-tool binding — execute via the decision path
            # (same engine the tool-registry bridge dispatches to).
            if tool is None:
                decision_entry = await self._execute_decision_binding(
                    db, skill, binding.tool_id, tool_input
                )
                if decision_entry is not None:
                    results.append(decision_entry)
                    continue
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


async def resolve_decision_tool(db: AsyncSession, tool_id: Any, tenant_id: Any):
    """Resolve a virtual decision tool id within a tenant (None if not one)."""
    from app.services.system_one.decision_tool_service import resolve_virtual_tool_id

    return await resolve_virtual_tool_id(db, tool_id, tenant_id)
