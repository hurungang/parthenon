"""AgentPermissionManager — resolves AgentRole → SOPs → Skills → MCP tools with LRU caching."""
import logging
import uuid
from functools import lru_cache
from typing import Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentRoleSkill, AgentRoleSOP
from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType
from app.db.models.mcp_hub import McpTool

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# ── Save-result pseudo-tool injected for all agent roles ──────────────────────

_SAVE_RESULT_TOOL = "save_result"


class PermissionDeniedError(Exception):
    """Raised when an agent attempts to call a tool it is not permitted to use."""

    def __init__(self, tool_identifier: str, role_id: uuid.UUID) -> None:
        super().__init__(
            f"Tool '{tool_identifier}' is not permitted for role {role_id}"
        )
        self.tool_identifier = tool_identifier
        self.role_id = role_id


class AgentPermissionManager:
    """
    Calculates the full set of allowed MCP tool identifiers for an AgentRole by
    traversing the role → SOP → Skill → tool hierarchy.

    Results are cached in-process with an LRU cache keyed on role_id.
    The cache is invalidated by calling ``invalidate(role_id)`` — this is called
    automatically by AgentRoleService on role writes.

    The ``save_result`` pseudo-tool is injected for every role (it is always allowed).
    """

    # Internal LRU cache mapping role_id (str) → frozenset[str]
    _cache: dict[str, frozenset[str]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    async def calculate_allowed_tools(
        self, role_id: uuid.UUID, db: AsyncSession
    ) -> set[str]:
        """
        Return the complete set of allowed MCP tool identifiers for the role.

        Results are cached until invalidated.
        """
        cache_key = str(role_id)
        if cache_key in self._cache:
            logger.debug("Permission cache hit for role %s", role_id)
            return set(self._cache[cache_key])

        with tracer.start_as_current_span(
            "permission_manager.calculate_allowed_tools",
            attributes={"role_id": str(role_id)},
        ) as span:
            allowed = await self._resolve_allowed_tools(role_id, db)
            # Always inject save_result
            allowed.add(_SAVE_RESULT_TOOL)

            self._cache[cache_key] = frozenset(allowed)
            span.set_attribute("tool_count", len(allowed))
            logger.info(
                "Resolved %d allowed tools for role %s: %s",
                len(allowed),
                role_id,
                sorted(allowed),
            )
            return set(allowed)

    def check_tool_allowed(
        self, tool_identifier: str, allowed_tools: set[str], role_id: uuid.UUID
    ) -> None:
        """
        Raise PermissionDeniedError if tool_identifier is not in allowed_tools.
        Called by AgentRuntimeExecutor on every tool dispatch.
        """
        if tool_identifier not in allowed_tools:
            with tracer.start_as_current_span(
                "permission_manager.deny",
                attributes={"tool": tool_identifier, "role_id": str(role_id)},
            ):
                logger.warning(
                    "Permission denied: tool '%s' not in allowed set for role %s",
                    tool_identifier,
                    role_id,
                )
            raise PermissionDeniedError(tool_identifier, role_id)

    def invalidate(self, role_id: uuid.UUID) -> None:
        """Evict the cached permission set for a role."""
        key = str(role_id)
        if key in self._cache:
            del self._cache[key]
            logger.debug("Permission cache invalidated for role %s", role_id)

    # ── Internal resolution ────────────────────────────────────────────────────

    async def _resolve_allowed_tools(
        self, role_id: uuid.UUID, db: AsyncSession
    ) -> set[str]:
        """Walk the role → SOP → Skill → tool graph and collect all tool identifiers."""
        skill_ids: set[uuid.UUID] = set()

        # 1. Collect skill IDs from directly assigned skills
        direct_skills = await db.execute(
            select(AgentRoleSkill.skill_id).where(AgentRoleSkill.role_id == role_id)
        )
        for (skill_id,) in direct_skills.fetchall():
            skill_ids.add(skill_id)

        # 2. Collect skill IDs from SOP steps for each assigned SOP
        sop_rows = await db.execute(
            select(AgentRoleSOP.sop_id).where(AgentRoleSOP.role_id == role_id)
        )
        sop_ids = [row[0] for row in sop_rows.fetchall()]

        if sop_ids:
            step_rows = await db.execute(
                select(SopStep.skill_id)
                .where(
                    SopStep.sop_id.in_(sop_ids),
                    SopStep.step_type == SopStepType.skill,
                    SopStep.skill_id.isnot(None),
                )
            )
            for (skill_id,) in step_rows.fetchall():
                skill_ids.add(skill_id)

        if not skill_ids:
            return set()

        # 3. Resolve tool identifiers from the collected skill IDs
        return await self._resolve_tools_from_skills(skill_ids, db)

    async def _resolve_tools_from_skills(
        self, skill_ids: set[uuid.UUID], db: AsyncSession
    ) -> set[str]:
        """Given a set of Skill IDs, return the full set of MCP tool identifiers."""
        if not skill_ids:
            return set()

        # Load all SkillToolBindings for the given skills, joining to McpTool for identifier
        binding_rows = await db.execute(
            select(McpTool.name, McpTool.server_id)
            .join(SkillToolBinding, SkillToolBinding.tool_id == McpTool.id)
            .where(SkillToolBinding.skill_id.in_(list(skill_ids)))
        )
        # Build a composite identifier: server_slug:tool_name via a separate query
        tool_ids_in_bindings: list[uuid.UUID] = []
        binding_tool_rows = await db.execute(
            select(SkillToolBinding.tool_id)
            .where(SkillToolBinding.skill_id.in_(list(skill_ids)))
        )
        tool_ids_in_bindings = [row[0] for row in binding_tool_rows.fetchall()]

        if not tool_ids_in_bindings:
            return set()

        # Load McpTool records with server relationship to build qualified identifiers
        from app.db.models.mcp_hub import McpServer
        tool_rows = await db.execute(
            select(McpTool)
            .where(McpTool.id.in_(tool_ids_in_bindings))
            .options(selectinload(McpTool.server))
        )
        tools = tool_rows.scalars().all()

        allowed: set[str] = set()
        for tool in tools:
            # Use "server_slug:tool_name" as the qualified identifier
            if tool.server:
                identifier = f"{tool.server.slug}:{tool.name}"
            else:
                identifier = tool.name
            allowed.add(identifier)

        return allowed
