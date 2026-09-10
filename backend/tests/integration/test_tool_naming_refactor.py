"""Integration tests for Phase 10 tool naming refactor.

Covers:
  1. System tools are NOT auto-injected into allowed_tools (task 10.3).
  2. agent_data context API returns system____* canonical names when system tools
     are explicitly bound to a skill assigned to the agent's role.

Database:
  Uses the shared SQLite StaticPool engine from integration/conftest.py.
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.mcp_hub import (
    SYSTEM_SERVER_ID,
    seed_system_tools,
)
from app.services.agents.system_tool_registry import SystemToolRegistry

SYSTEM_TOOL_SAVE_DATA_ID = SystemToolRegistry.get("save_data").mcp_hub_id
SYSTEM_TOOL_SEND_NOTIFICATION_ID = SystemToolRegistry.get("send_notification").mcp_hub_id
SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID = SystemToolRegistry.get("get_recipient_group").mcp_hub_id
from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType, AgentOutputType
from app.db.models.mcp_hub import McpTool
from app.services.agents.tool_naming import (
    TOOL_SEPARATOR,
    build_tool_name,
    is_system_tool,
)


# ── helpers ───────────────────────────────────────────────────────────────────


async def _get_all_tool_names(db: AsyncSession) -> list[str]:
    """Return all active McpTool names from DB."""
    rows = await db.execute(select(McpTool.name).where(McpTool.is_active.is_(True)))
    return [r[0] for r in rows.fetchall()]


# ── Task 10.2: system tool DB names use system____ separator ─────────────────


class TestSystemToolDbNames:
    """System tools stored in DB should use system____ naming after seed."""

    @pytest.mark.asyncio
    async def test_seeded_system_tools_use_canonical_names(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_tools(db_session)

        tool_names = await _get_all_tool_names(db_session)
        system_names = [n for n in tool_names if is_system_tool(n)]

        assert "system____save_data" in system_names, (
            "save_data must be stored as system____save_data"
        )
        assert "system____send_notification" in system_names
        assert "system____get_recipient_group" in system_names

    @pytest.mark.asyncio
    async def test_seeded_system_tools_have_original_name(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_tools(db_session)

        save_tool = await db_session.get(McpTool, SYSTEM_TOOL_SAVE_DATA_ID)
        assert save_tool is not None
        assert save_tool.name == "system____save_data"
        assert save_tool.original_name == "save_data"


# ── Task 10.3: system tools are NOT auto-injected ────────────────────────────


class TestNoAutoInjection:
    """Verify that the context API builds allowed_tools from DB bindings only."""

    @pytest.mark.asyncio
    async def test_empty_role_has_no_system_tools(
        self, db_session: AsyncSession
    ) -> None:
        """An agent with a role that has no skill bindings should get zero allowed tools."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.models.agents import AgentType, AgentRole, AgentInputType, AgentOutputType

        # Create a role with no skills
        role = AgentRole(name="empty-role-test", description="No tools")
        db_session.add(role)
        await db_session.flush()

        agent_type = AgentType(
            name="TestAgent-NoTools",
            role_id=role.id,
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.auto,
        )
        db_session.add(agent_type)
        await db_session.flush()

        # Call the context endpoint directly
        context = await get_agent_context(agent_type_id=agent_type.id, db=db_session)

        # No system tools should be auto-injected
        auto_injected = [
            t for t in context.allowed_tools
            if is_system_tool(t)
        ]
        assert auto_injected == [], (
            f"System tools were auto-injected into allowed_tools: {auto_injected}"
        )

    @pytest.mark.asyncio
    async def test_system_tools_appear_when_explicitly_bound(
        self, db_session: AsyncSession
    ) -> None:
        """System tools appear in allowed_tools when explicitly bound via a skill."""
        from app.api.v1.internal.agent_data import get_agent_context
        from app.db.models.agents import (
            AgentType,
            AgentRole,
            AgentRoleSkill,
            AgentInputType,
            AgentOutputType,
        )
        from app.db.models.skills import Skill, SkillToolBinding

        await seed_system_tools(db_session)

        # Create skill bound to system____save_data
        skill = Skill(name="result-skill", description="Save result skill")
        db_session.add(skill)
        await db_session.flush()

        binding = SkillToolBinding(
            skill_id=skill.id,
            tool_id=SYSTEM_TOOL_SAVE_DATA_ID,
        )
        db_session.add(binding)
        await db_session.flush()

        # Create role with this skill
        role = AgentRole(name="result-role", description="Has save_data")
        db_session.add(role)
        await db_session.flush()

        role_skill = AgentRoleSkill(role_id=role.id, skill_id=skill.id)
        db_session.add(role_skill)
        await db_session.flush()

        agent_type = AgentType(
            name="TestAgent-WithSaveResult",
            role_id=role.id,
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.auto,
        )
        db_session.add(agent_type)
        await db_session.flush()

        context = await get_agent_context(agent_type_id=agent_type.id, db=db_session)

        assert "system____save_data" in context.allowed_tools, (
            "system____save_data must appear in allowed_tools when explicitly bound"
        )
        # send_notification and get_recipient_group were NOT bound — should be absent
        assert "system____send_notification" not in context.allowed_tools
        assert "system____get_recipient_group" not in context.allowed_tools


class TestSendNotificationSystemTool:
    """Verify send_notification endpoint uses the session-bound NotificationService API."""

    @pytest.mark.asyncio
    async def test_send_notification_calls_service_with_session(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api.v1.internal.system_tools import send_notification_tool, SystemToolRequest
        import app.services.notifications.notification_service as notification_module

        send_mock = AsyncMock(return_value=None)

        class FakeNotificationService:
            def __init__(self, session: AsyncSession) -> None:
                assert session is db_session

            async def send_to_group(
                self,
                group_slug: str,
                body: str,
                source_type: Any = None,
                subject: str | None = None,
                source_id: uuid.UUID | None = None,
                channel: str | None = None,
            ) -> Any:
                return await send_mock(
                    group_slug=group_slug,
                    body=body,
                    subject=subject,
                    source_type=source_type,
                    source_id=source_id,
                    channel=channel,
                )

        monkeypatch.setattr(notification_module, "NotificationService", FakeNotificationService)

        req = SystemToolRequest(
            session_id=str(uuid.uuid4()),
            tool_args={
                "group_slug": "ops-team",
                "channel": "teams",
                "subject": "Alert",
                "body": "Service health degraded",
            },
        )

        resp = await send_notification_tool(body=req, db=db_session)

        assert resp.result["status"] == "sent"
        assert resp.result["group_slug"] == "ops-team"
        assert resp.result["channel"] == "teams"
        send_mock.assert_awaited_once()
