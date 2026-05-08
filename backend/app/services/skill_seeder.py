"""SkillSeeder — idempotent initializer for default platform skills.

Creates the `save_result` and `send_notification` skills on application startup
or via the `seed-skills` CLI command if they do not already exist.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding

logger = logging.getLogger(__name__)

# Default skill definitions — name is the idempotency key
_DEFAULT_SKILLS: list[dict] = [
    {
        "name": "save_result",
        "description": "Persists structured agent outputs to the Result Repository.",
        "instructions": (
            "Use this skill to store the final structured output of an agent run "
            "into the Result Repository. Provide the result payload as the first argument. "
            "Results are immutable after saving."
        ),
        # Tool names that should be bound (matched by McpTool.name or McpTool.original_name)
        "tool_names": ["save_result"],
    },
    {
        "name": "send_notification",
        "description": "Dispatches notifications through configured channel integrations.",
        "instructions": (
            "Use this skill to dispatch a notification through one of the configured "
            "channel integrations (email, Slack, webhook, etc.). Specify the channel "
            "and message payload. Ensure the channel is active before invoking."
        ),
        "tool_names": ["send_notification"],
    },
]


class SkillSeeder:
    """Idempotent service that creates default platform skills if they are absent."""

    async def run(self, session: AsyncSession) -> dict[str, str]:
        """Seed default skills.

        Returns a summary dict mapping skill name → action taken
        ('created' | 'exists' | 'skipped').
        """
        summary: dict[str, str] = {}
        try:
            for skill_def in _DEFAULT_SKILLS:
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

        # Check existence — name is the idempotency key
        result = await session.execute(select(Skill).where(Skill.name == name))
        existing = result.scalar_one_or_none()
        if existing is not None:
            logger.info("SkillSeeder: skill '%s' already exists — skipping.", name)
            return "exists"

        # Create the skill
        skill = Skill(
            name=name,
            description=skill_def.get("description"),
            instructions=skill_def.get("instructions"),
            is_active=True,
        )
        session.add(skill)
        await session.flush()  # populate skill.id

        # Bind platform tools by name (look up by original_name or namespaced name)
        tool_names: list[str] = skill_def.get("tool_names", [])
        for order, tool_name in enumerate(tool_names):
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
                    name,
                )
                continue
            binding = SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=order)
            session.add(binding)

        logger.info("SkillSeeder: created default skill '%s'.", name)
        return "created"
