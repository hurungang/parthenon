"""Unit tests for SkillExecutor."""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.services.skills.executor import SkillExecutor, SkillExecutionError
from app.services.mcp.proxy import McpProxyEngine


class TestSkillExecutor:
    """Tests for the SkillExecutor."""

    def _make_mock_tool(self, name: str = "test/tool", is_active: bool = True) -> MagicMock:
        tool = MagicMock()
        tool.id = uuid.uuid4()
        tool.name = name
        tool.is_active = is_active
        tool.server = MagicMock()
        return tool

    def _make_mock_binding(self, tool_id: uuid.UUID, order: int = 0) -> MagicMock:
        binding = MagicMock()
        binding.tool_id = tool_id
        binding.order = order
        return binding

    @pytest.mark.asyncio
    async def test_execute_raises_when_skill_not_found(self) -> None:
        mock_proxy = AsyncMock(spec=McpProxyEngine)
        executor = SkillExecutor(proxy_engine=mock_proxy)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(SkillExecutionError, match="not found"):
            await executor.execute(uuid.uuid4(), {}, mock_db)

    @pytest.mark.asyncio
    async def test_execute_raises_when_no_tool_bindings(self) -> None:
        mock_proxy = AsyncMock(spec=McpProxyEngine)
        executor = SkillExecutor(proxy_engine=mock_proxy)

        mock_skill = MagicMock()
        mock_skill.id = uuid.uuid4()
        mock_skill.name = "test-skill"
        mock_skill.tool_bindings = []  # No bindings

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(SkillExecutionError, match="no MCP tool bindings"):
            await executor.execute(mock_skill.id, {}, mock_db)

    @pytest.mark.asyncio
    async def test_execute_returns_tool_results(self) -> None:
        """Successful execution should return a list of tool results."""
        mock_proxy = AsyncMock(spec=McpProxyEngine)
        mock_proxy.call_tool = AsyncMock(return_value={"output": "done"})

        executor = SkillExecutor(proxy_engine=mock_proxy)

        tool = self._make_mock_tool()
        binding = self._make_mock_binding(tool.id, order=0)
        binding.tool_id = tool.id

        mock_skill = MagicMock()
        mock_skill.id = uuid.uuid4()
        mock_skill.name = "test-skill"
        mock_skill.tool_bindings = [binding]

        mock_db = AsyncMock()
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = mock_skill
        mock_db.execute = AsyncMock(return_value=mock_execute_result)
        mock_db.get = AsyncMock(return_value=tool)
        mock_db.refresh = AsyncMock()

        results = await executor.execute(mock_skill.id, {"input": "test"}, mock_db)
        assert len(results) == 1
        assert results[0]["result"] == {"output": "done"}
        assert results[0]["tool"] == tool.name

    @pytest.mark.asyncio
    async def test_execute_handles_proxy_error_gracefully(self) -> None:
        """Proxy errors should be captured in the result, not raised."""
        from app.services.mcp.proxy import McpProxyError

        mock_proxy = AsyncMock(spec=McpProxyEngine)
        mock_proxy.call_tool = AsyncMock(side_effect=McpProxyError("Connection refused"))

        executor = SkillExecutor(proxy_engine=mock_proxy)

        tool = self._make_mock_tool()
        binding = self._make_mock_binding(tool.id)

        mock_skill = MagicMock()
        mock_skill.id = uuid.uuid4()
        mock_skill.name = "failing-skill"
        mock_skill.tool_bindings = [binding]

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.get = AsyncMock(return_value=tool)
        mock_db.refresh = AsyncMock()

        results = await executor.execute(mock_skill.id, {}, mock_db)
        assert results[0]["error"] == "Connection refused"
        assert results[0]["result"] is None
