"""SkillSeeder — idempotent initializer for default platform skills.

Seeds every system tool that has ``skill_name`` defined in ``SystemToolRegistry``.
System skills are marked ``is_system`` and cannot be edited or deleted through
the API.  To add or rename a skill, update ``system_tool_registry.py``.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding

logger = logging.getLogger(__name__)




class SkillSeeder:
    """Idempotent service that creates default platform skills if they are absent."""

    async def run(self, session: AsyncSession) -> dict[str, str]:
        """Seed default skills.

        Returns a summary dict mapping skill name → action taken
        ('created' | 'exists' | 'skipped').
        """
        from app.services.agents.system_tool_registry import SystemToolRegistry

        summary: dict[str, str] = {}
        try:
            for skill_def in SystemToolRegistry.get_skill_definitions():
                action = await self._seed_one(session, skill_def)
                summary[skill_def["name"]] = action
            await session.flush()
        except Exception:
            logger.exception("SkillSeeder encountered an unexpected error; rolling back.")
            await session.rollback()
            raise
        return summary

    async def _seed_one(self, session: AsyncSession, skill_def: dict) -> str:
        name: str = skill_def["name"]

        result = await session.execute(select(Skill).where(Skill.name == name))
        existing = result.scalar_one_or_none()
        if existing is not None:
            updated = False
            if not existing.is_system:
                existing.is_system = True
                updated = True
            if skill_def.get("description") and existing.description != skill_def["description"]:
                existing.description = skill_def["description"]
                updated = True
            if skill_def.get("instructions") and existing.instructions != skill_def["instructions"]:
                existing.instructions = skill_def["instructions"]
                updated = True
            if updated:
                logger.info("SkillSeeder: updated existing skill '%s'.", name)
            else:
                logger.info("SkillSeeder: skill '%s' already exists — checking bindings.", name)
            return await self._ensure_bindings(session, existing, skill_def)

        skill = Skill(
            name=name,
            description=skill_def.get("description"),
            instructions=skill_def.get("instructions"),
            is_active=True,
            is_system=True,
        )
        session.add(skill)
        await session.flush()

        logger.info("SkillSeeder: created default skill '%s'.", name)
        return await self._ensure_bindings(session, skill, skill_def)

    async def _ensure_bindings(
        self, session: AsyncSession, skill: Skill, skill_def: dict
    ) -> str:
        """Ensure ``SkillToolBinding`` records exist for the given skill.

        Creates missing bindings for tool names listed in *skill_def*.
        Returns ``'created'`` when bindings were added, ``'exists'`` otherwise.
        """
        tool_names: list[str] = skill_def.get("tool_names", [])
        binding_added = False
        for order, tool_name in enumerate(tool_names):
            existing_binding_result = await session.execute(
                select(SkillToolBinding)
                .join(McpTool, SkillToolBinding.tool_id == McpTool.id)
                .where(
                    SkillToolBinding.skill_id == skill.id,
                    (McpTool.original_name == tool_name) | (McpTool.name == tool_name),
                )
            )
            if existing_binding_result.scalars().first() is not None:
                continue

            tool_result = await session.execute(
                select(McpTool).where(
                    (McpTool.original_name == tool_name) | (McpTool.name == tool_name)
                )
            )
            tool = tool_result.scalars().first()
            if tool is None:
                logger.warning(
                    "SkillSeeder: platform tool '%s' not found for skill '%s' — "
                    "binding skipped. Run a server sync to register the tool.",
                    tool_name,
                    skill.name,
                )
                continue
            binding = SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=order)
            session.add(binding)
            binding_added = True
            logger.info(
                "SkillSeeder: added binding skill='%s' → tool='%s' (id=%s).",
                skill.name, tool_name, tool.id,
            )

        if binding_added:
            return "created"
        return "exists"
