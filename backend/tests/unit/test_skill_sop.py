"""
Test SkillExecutor and SopOrchestrator: execution, invalid binding, step ordering.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_skill_executor_raises_on_missing_binding():
    """SkillExecutor.execute() raises SkillExecutionError when no tool bindings exist."""
    from app.db.models.skills import Skill
    from app.services.skills.executor import SkillExecutionError, SkillExecutor

    mock_skill = MagicMock(spec=Skill)
    mock_skill.id = uuid.uuid4()
    mock_skill.name = "my-skill"
    mock_skill.tool_bindings = []  # no bindings → should raise

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_skill))
    )

    executor = SkillExecutor()
    with pytest.raises(SkillExecutionError, match="has no MCP tool bindings"):
        await executor.execute(mock_skill.id, {}, mock_db)


@pytest.mark.asyncio
async def test_skill_executor_returns_results_for_each_tool():
    """SkillExecutor.execute() invokes the proxy for each bound tool and returns results."""
    from app.db.models.mcp_hub import McpTool
    from app.db.models.skills import Skill, SkillToolBinding
    from app.services.skills.executor import SkillExecutor

    skill_id = uuid.uuid4()
    tool_id = uuid.uuid4()

    mock_binding = MagicMock(spec=SkillToolBinding)
    mock_binding.tool_id = tool_id
    mock_binding.order = 1

    mock_tool = MagicMock(spec=McpTool)
    mock_tool.name = "my-server/toolA"
    mock_tool.is_active = True

    mock_skill = MagicMock(spec=Skill)
    mock_skill.id = skill_id
    mock_skill.name = "skill-a"
    mock_skill.tool_bindings = [mock_binding]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_skill))
    )
    mock_db.get = AsyncMock(return_value=mock_tool)
    mock_db.refresh = AsyncMock()

    mock_proxy = AsyncMock()
    mock_proxy.call_tool = AsyncMock(return_value={"output": "result-from-tool"})

    executor = SkillExecutor(proxy_engine=mock_proxy)
    results = await executor.execute(skill_id, {"key": "value"}, mock_db)

    assert len(results) == 1
    assert results[0]["result"] == {"output": "result-from-tool"}
    assert results[0]["error"] is None


@pytest.mark.asyncio
async def test_sop_orchestrator_executes_steps_in_order():
    """SopOrchestrator.execute() iterates SOP steps sorted by .order and returns combined output."""
    from app.db.models.skills import Sop, SopStep, SopStepType
    from app.services.skills.sop_orchestrator import SopOrchestrator

    sop_id = uuid.uuid4()

    step1 = MagicMock(spec=SopStep)
    step1.id = uuid.uuid4()
    step1.order = 1
    step1.step_type = SopStepType.skill
    step1.skill_id = uuid.uuid4()
    step1.name = "Step 1"
    step1.config = {}

    step2 = MagicMock(spec=SopStep)
    step2.id = uuid.uuid4()
    step2.order = 2
    step2.step_type = SopStepType.skill
    step2.skill_id = uuid.uuid4()
    step2.name = "Step 2"
    step2.config = {}

    mock_sop = MagicMock(spec=Sop)
    mock_sop.id = sop_id
    mock_sop.name = "My SOP"
    mock_sop.steps = [step2, step1]  # intentionally reversed — orchestrator must sort

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_sop))
    )

    executed_order = []

    async def fake_execute(skill_id, tool_input, db, session_id=None):
        executed_order.append(skill_id)
        return [{"tool": "t", "result": f"result-{skill_id}", "error": None}]

    mock_skill_executor = MagicMock()
    mock_skill_executor.execute = fake_execute

    orchestrator = SopOrchestrator(skill_executor=mock_skill_executor)
    result = await orchestrator.execute(sop_id, "test prompt", {}, mock_db)

    assert "results" in result
    assert len(result["results"]) == 2
    # step1 (order=1) must execute before step2 (order=2)
    assert executed_order[0] == step1.skill_id
    assert executed_order[1] == step2.skill_id
