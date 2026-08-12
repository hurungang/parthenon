"""Integration tests for Phase 10 tool naming refactor.

Covers:
  1. System tools are NOT auto-injected into allowed_tools (task 10.3).
  2. agent_data context API returns system____* canonical names when system tools
     are explicitly bound to a skill assigned to the agent's role.
  3. save_result tool call (via system_tools.py endpoint) persists a ResultRecord
     so it appears in the Result Repository (task 10.6).

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
    SYSTEM_TOOL_SAVE_RESULT_ID,
    SYSTEM_TOOL_SEND_NOTIFICATION_ID,
    SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID,
    seed_system_tools,
)
from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType, AgentOutputType
from app.db.models.mcp_hub import McpTool
from app.db.models.results import ResultRecord
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

        assert "system____save_result" in system_names, (
            "save_result must be stored as system____save_result"
        )
        assert "system____send_notification" in system_names
        assert "system____get_recipient_group" in system_names

    @pytest.mark.asyncio
    async def test_seeded_system_tools_have_original_name(
        self, db_session: AsyncSession
    ) -> None:
        await seed_system_tools(db_session)

        save_tool = await db_session.get(McpTool, SYSTEM_TOOL_SAVE_RESULT_ID)
        assert save_tool is not None
        assert save_tool.name == "system____save_result"
        assert save_tool.original_name == "save_result"


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

        # Create skill bound to system____save_result
        skill = Skill(name="result-skill", description="Save result skill")
        db_session.add(skill)
        await db_session.flush()

        binding = SkillToolBinding(
            skill_id=skill.id,
            tool_id=SYSTEM_TOOL_SAVE_RESULT_ID,
        )
        db_session.add(binding)
        await db_session.flush()

        # Create role with this skill
        role = AgentRole(name="result-role", description="Has save_result")
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

        assert "system____save_result" in context.allowed_tools, (
            "system____save_result must appear in allowed_tools when explicitly bound"
        )
        # send_notification and get_recipient_group were NOT bound — should be absent
        assert "system____send_notification" not in context.allowed_tools
        assert "system____get_recipient_group" not in context.allowed_tools


# ── Task 10.6: save_result creates ResultRecord ───────────────────────────────


class TestSaveResultCreatesResultRecord:
    """Verify that calling save_result_tool() persists a ResultRecord."""

    @pytest.mark.asyncio
    async def test_save_result_creates_result_record(
        self, db_session: AsyncSession
    ) -> None:
        from app.api.v1.internal.system_tools import save_result_tool, SystemToolRequest

        # Create a minimal AgentJob via AgentRole + AgentType (required FK)
        from app.db.models.agents import AgentJob, AgentJobStatus, AgentRole, AgentType
        import uuid

        role = AgentRole(name="sr-test-role", description="")
        db_session.add(role)
        await db_session.flush()

        agent_type = AgentType(name="sr-test-agent", role_id=role.id)
        db_session.add(agent_type)
        await db_session.flush()

        job = AgentJob(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            status=AgentJobStatus.running,
            input_data={"message": "test"},
        )
        db_session.add(job)
        await db_session.flush()

        request = SystemToolRequest(
            session_id=str(job.id),
            tool_args={"content": "The answer is 42", "title": "Test Result"},
        )

        # Count ResultRecord rows before
        before = await db_session.execute(select(ResultRecord))
        count_before = len(list(before.scalars().all()))

        response = await save_result_tool(body=request, db=db_session)

        assert response.result["status"] == "saved"

        # Count ResultRecord rows after
        after = await db_session.execute(select(ResultRecord))
        records = list(after.scalars().all())
        assert len(records) == count_before + 1, "save_result must create exactly one ResultRecord"

        new_record = records[-1]
        assert new_record.payload == {"content": "The answer is 42"}
        assert new_record.title == "Test Result"
        assert new_record.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_save_result_updates_job_output_data(
        self, db_session: AsyncSession
    ) -> None:
        """save_result must also update job.output_data for backward compat."""
        from app.api.v1.internal.system_tools import save_result_tool, SystemToolRequest
        from app.db.models.agents import AgentJob, AgentJobStatus, AgentRole, AgentType
        import uuid

        role = AgentRole(name="sr-compat-role", description="")
        db_session.add(role)
        await db_session.flush()

        agent_type = AgentType(name="sr-compat-agent", role_id=role.id)
        db_session.add(agent_type)
        await db_session.flush()

        job = AgentJob(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            status=AgentJobStatus.running,
            input_data={"message": "compat test"},
        )
        db_session.add(job)
        await db_session.flush()

        request = SystemToolRequest(
            session_id=str(job.id),
            tool_args={"content": "compat result"},
        )
        await save_result_tool(body=request, db=db_session)

        refreshed = await db_session.get(AgentJob, job.id)
        assert refreshed is not None
        assert refreshed.output_data is not None
        assert refreshed.output_data.get("result") == "compat result"

    @pytest.mark.asyncio
    async def test_save_result_honors_markdown_output_type(
        self, db_session: AsyncSession
    ) -> None:
        """save_result must persist markdown content type when agent output_type=markdown."""
        from app.api.v1.internal.system_tools import save_result_tool, SystemToolRequest
        from app.db.models.agents import AgentJob, AgentJobStatus, AgentRole, AgentType

        role = AgentRole(name="sr-markdown-role", description="")
        db_session.add(role)
        await db_session.flush()

        agent_type = AgentType(
            name="sr-markdown-agent",
            role_id=role.id,
            output_type=AgentOutputType.markdown,
        )
        db_session.add(agent_type)
        await db_session.flush()

        job = AgentJob(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            status=AgentJobStatus.running,
            input_data={"message": "markdown test"},
        )
        db_session.add(job)
        await db_session.flush()

        request = SystemToolRequest(
            session_id=str(job.id),
            tool_args={"content": "# Markdown Result"},
        )
        await save_result_tool(body=request, db=db_session)

        rows = await db_session.execute(
            select(ResultRecord)
            .where(ResultRecord.agent_type_id == agent_type.id)
            .order_by(ResultRecord.created_at.desc())
        )
        record = rows.scalars().first()
        assert record is not None
        assert record.content_type == "text/markdown"
        assert record.payload == {"content": "# Markdown Result"}


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
