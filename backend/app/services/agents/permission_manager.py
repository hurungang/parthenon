"""AgentPermissionManager — resolves AgentRole → SOPs → Skills → MCP tools with LRU caching."""
import logging
import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentRoleSkill, AgentRoleSOP, AgentType
from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType
from app.db.models.mcp_hub import McpTool
from app.services.agents.tool_naming import build_tool_name, parse_tool_name, is_system_tool



logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


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
    """

    # Internal LRU cache mapping role_id (str) → frozenset[str]
    _cache: dict[str, frozenset[str]] = {}
    _agent_type_cache: dict[str, frozenset[str]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    async def calculate_allowed_tools(
        self, role_id: uuid.UUID, db: "AsyncSession", override_skill_ids: set[uuid.UUID] | None = None, override_sop_ids: set[uuid.UUID] | None = None
    ) -> set[str]:
        """
        Return the complete set of allowed MCP tool identifiers for the role.

        Results are cached until invalidated (unless using overrides for preview).
        
        Args:
            role_id: The agent role to resolve tools for
            db: Database session
            override_skill_ids: If provided, use these skill IDs for preview (bypasses cache)
            override_sop_ids: If provided, use these SOP IDs for preview (bypasses cache)
        """
        # Skip cache when previewing with overrides
        using_overrides = override_skill_ids is not None or override_sop_ids is not None
        
        cache_key = str(role_id)
        if not using_overrides and cache_key in self._cache:
            logger.debug("Permission cache hit for role %s", role_id)
            return set(self._cache[cache_key])

        with tracer.start_as_current_span(
            "permission_manager.calculate_allowed_tools",
            attributes={"role_id": str(role_id), "is_preview": using_overrides},
        ) as span:
            allowed = await self._resolve_allowed_tools(role_id, db, override_skill_ids, override_sop_ids)

            # Only cache if not using overrides
            if not using_overrides:
                self._cache[cache_key] = frozenset(allowed)
            
            span.set_attribute("tool_count", len(allowed))
            logger.info(
                "Resolved %d allowed tools for role %s%s: %s",
                len(allowed),
                role_id,
                " (preview)" if using_overrides else "",
                sorted(allowed),
            )
            return set(allowed)

    async def calculate_allowed_agent_types(
        self,
        role_id: uuid.UUID,
        db: "AsyncSession",
        override_sop_ids: set[uuid.UUID] | None = None,
    ) -> set[str]:
        """Return delegated agent type names allowed by SOP agent_delegation steps.

        The result is derived from SOP steps assigned to the role and cached per role.
        When ``override_sop_ids`` is provided, the method bypasses cache for preview mode.
        """
        using_overrides = override_sop_ids is not None
        cache_key = str(role_id)

        if not using_overrides and cache_key in self._agent_type_cache:
            logger.debug("Agent-type permission cache hit for role %s", role_id)
            return set(self._agent_type_cache[cache_key])

        with tracer.start_as_current_span(
            "permission_manager.calculate_allowed_agent_types",
            attributes={"role_id": str(role_id), "is_preview": using_overrides},
        ) as span:
            delegated_agent_ids = await self._resolve_allowed_agent_type_ids(
                role_id, db, override_sop_ids
            )

            if not delegated_agent_ids:
                if not using_overrides:
                    self._agent_type_cache[cache_key] = frozenset()
                span.set_attribute("agent_type_count", 0)
                return set()

            rows = await db.execute(
                select(AgentType.name).where(AgentType.id.in_(list(delegated_agent_ids)))
            )
            allowed_agent_types = {row[0] for row in rows.fetchall() if row[0]}

            if not using_overrides:
                self._agent_type_cache[cache_key] = frozenset(allowed_agent_types)

            span.set_attribute("agent_type_count", len(allowed_agent_types))
            logger.info(
                "Resolved %d allowed agent types for role %s%s: %s",
                len(allowed_agent_types),
                role_id,
                " (preview)" if using_overrides else "",
                sorted(allowed_agent_types),
            )
            return allowed_agent_types

    def get_allowed_tools_from_context(
        self, allowed_tools: list[str]
    ) -> set[str]:
        """Return the allowed tool set from context data (Agent Runtime path).

        The CC data API pre-resolves permissions; this method simply converts
        the list to a set. No database access required.
        """
        return {self._canonicalize_tool_identifier(t) for t in allowed_tools}

    def check_tool_allowed(
        self, tool_identifier: str, allowed_tools: set[str], role_id: uuid.UUID
    ) -> None:
        """
        Raise PermissionDeniedError if tool_identifier is not in allowed_tools.
        Called by AgentRuntimeExecutor on every tool dispatch.
        """
        requested = self._canonicalize_tool_identifier(tool_identifier)
        normalized_allowed = {self._canonicalize_tool_identifier(t) for t in allowed_tools}

        if requested not in normalized_allowed:
            with tracer.start_as_current_span(
                "permission_manager.deny",
                attributes={"tool": requested, "role_id": str(role_id)},
            ):
                logger.warning(
                    "Permission denied: tool '%s' not in allowed set for role %s",
                    requested,
                    role_id,
                )
            raise PermissionDeniedError(requested, role_id)

    def invalidate(self, role_id: uuid.UUID) -> None:
        """Evict the cached permission set for a role."""
        key = str(role_id)
        if key in self._cache:
            del self._cache[key]
            logger.debug("Permission cache invalidated for role %s", role_id)
        if key in self._agent_type_cache:
            del self._agent_type_cache[key]
            logger.debug("Agent-type permission cache invalidated for role %s", role_id)

    # ── Internal resolution ────────────────────────────────────────────────────

    async def _resolve_allowed_tools(
        self, role_id: uuid.UUID, db: AsyncSession, override_skill_ids: set[uuid.UUID] | None = None, override_sop_ids: set[uuid.UUID] | None = None
    ) -> set[str]:
        """Walk the role → SOP → Skill → tool graph and collect all tool identifiers.
        
        Args:
            role_id: The agent role to resolve tools for
            db: Database session
            override_skill_ids: If provided, use these skill IDs instead of querying the database
            override_sop_ids: If provided, use these SOP IDs instead of querying the database
        """
        skill_ids: set[uuid.UUID] = set()

        # Allow caller to override with temporary selections (for preview)
        if override_skill_ids is not None or override_sop_ids is not None:
            skill_ids = (override_skill_ids or set()).copy()
            if override_sop_ids:
                step_rows = await db.execute(
                    select(SopStep.skill_id)
                    .where(
                        SopStep.sop_id.in_(list(override_sop_ids)),
                        SopStep.step_type == SopStepType.skill_invocation,
                        SopStep.skill_id.isnot(None),
                    )
                )
                for (skill_id,) in step_rows.fetchall():
                    skill_ids.add(skill_id)
        else:
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
                        SopStep.step_type == SopStepType.skill_invocation,
                        SopStep.skill_id.isnot(None),
                    )
                )
                for (skill_id,) in step_rows.fetchall():
                    skill_ids.add(skill_id)

        if not skill_ids:
            return set()

        # 3. Resolve tool identifiers from the collected skill IDs
        return await self._resolve_tools_from_skills(skill_ids, db)

    async def _resolve_allowed_agent_type_ids(
        self,
        role_id: uuid.UUID,
        db: AsyncSession,
        override_sop_ids: set[uuid.UUID] | None = None,
    ) -> set[uuid.UUID]:
        """Resolve delegated target agent type IDs from role SOPs."""
        sop_ids: list[uuid.UUID]

        if override_sop_ids is not None:
            sop_ids = list(override_sop_ids)
        else:
            sop_rows = await db.execute(
                select(AgentRoleSOP.sop_id).where(AgentRoleSOP.role_id == role_id)
            )
            sop_ids = [row[0] for row in sop_rows.fetchall()]

        if not sop_ids:
            return set()

        delegated_rows = await db.execute(
            select(SopStep.target_agent_type_id)
            .where(
                SopStep.sop_id.in_(sop_ids),
                SopStep.step_type == SopStepType.agent_delegation,
                SopStep.target_agent_type_id.isnot(None),
            )
        )
        return {row[0] for row in delegated_rows.fetchall() if row[0] is not None}

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
            # Use canonical server____tool identifiers for both system and MCP tools.
            if is_system_tool(tool.name):
                allowed.add(self._canonicalize_tool_identifier(tool.name))
            else:
                original_name = getattr(tool, "original_name", None)
                if tool.server is not None and isinstance(original_name, str) and original_name:
                    allowed.add(build_tool_name(tool.server.slug, original_name))
                else:
                    try:
                        server_slug, bare_tool = parse_tool_name(tool.name)
                        allowed.add(build_tool_name(server_slug, bare_tool))
                    except ValueError:
                        if "/" in tool.name:
                            server_slug, bare_tool = tool.name.split("/", 1)
                            allowed.add(build_tool_name(server_slug, bare_tool))
                        else:
                            allowed.add(tool.name)

        return allowed

    def _canonicalize_tool_identifier(self, tool_identifier: str) -> str:
        """Normalize legacy and display formats to canonical ``server____tool`` form."""
        if tool_identifier.startswith("system____"):
            return tool_identifier

        if tool_identifier.startswith("system__"):
            return build_tool_name("system", tool_identifier[len("system__"):])

        if tool_identifier.startswith("system/"):
            return build_tool_name("system", tool_identifier[len("system/"):])

        if is_system_tool(tool_identifier):
            try:
                server, tool = parse_tool_name(tool_identifier)
                return build_tool_name(server, tool)
            except ValueError:
                return build_tool_name("system", tool_identifier)

        try:
            server, tool = parse_tool_name(tool_identifier)
            return build_tool_name(server, tool)
        except ValueError:
            if "/" in tool_identifier:
                server, tool = tool_identifier.split("/", 1)
                return build_tool_name(server, tool)
            return tool_identifier


# ── Shared singleton for Control Center process ─────────────────────────────
# All CC-internal API modules (agents.py, session_data.py, permission_resolution.py)
# share this one instance so cache invalidation (via AgentRoleService) works
# correctly for all code paths.
_shared_permission_manager: AgentPermissionManager | None = None


def get_shared_permission_manager() -> AgentPermissionManager:
    global _shared_permission_manager
    if _shared_permission_manager is None:
        _shared_permission_manager = AgentPermissionManager()
    return _shared_permission_manager
