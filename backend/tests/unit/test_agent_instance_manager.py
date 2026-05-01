"""Unit tests for AgentInstanceManager."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.db.models.agents import AgentInstanceStatus, AgentMode
from app.services.agents.instance_manager import AgentInstanceManager, InstanceLimitError


class TestAgentInstanceManager:
    """Tests for spawn, activate, and close lifecycle transitions."""

    def _make_mock_agent_type(
        self, max_instances: int = 3, mode: AgentMode = AgentMode.skillful_agent
    ) -> MagicMock:
        at = MagicMock()
        at.id = uuid.uuid4()
        at.name = "test-agent"
        at.mode = mode
        at.max_instances = max_instances
        at.is_active = True
        at.sop_id = None
        return at

    @pytest.mark.asyncio
    async def test_spawn_raises_when_max_instances_exceeded(self) -> None:
        """Spawning beyond max_instances should raise InstanceLimitError."""
        manager = AgentInstanceManager()
        agent_type_id = uuid.uuid4()
        agent_type = self._make_mock_agent_type(max_instances=2)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=agent_type)

        # Mock count query returning max_instances
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 2  # Already at limit
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(InstanceLimitError, match="max_instances"):
            await manager.spawn(agent_type_id, "test-user", mock_db)

    @pytest.mark.asyncio
    async def test_spawn_creates_instance_when_under_limit(self) -> None:
        """Spawning should succeed when current count < max_instances."""
        manager = AgentInstanceManager()
        agent_type_id = uuid.uuid4()
        agent_type = self._make_mock_agent_type(max_instances=5)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=agent_type)

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0  # No active instances
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock flush and refresh
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        instance = await manager.spawn(agent_type_id, "test-user", mock_db)  # noqa: F841
        assert mock_db.add.called
        assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_spawn_raises_when_agent_type_not_found(self) -> None:
        """Spawning with unknown agent_type_id should raise ValueError."""
        manager = AgentInstanceManager()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await manager.spawn(uuid.uuid4(), None, mock_db)

    @pytest.mark.asyncio
    async def test_close_sets_closed_status(self) -> None:
        """Close should set status to closed."""
        manager = AgentInstanceManager()
        instance_id = uuid.uuid4()

        mock_instance = MagicMock()
        mock_instance.id = instance_id
        mock_instance.status = AgentInstanceStatus.active

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_instance)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await manager.close(instance_id, mock_db)
        assert mock_instance.status == AgentInstanceStatus.closed
        assert mock_instance.closed_at is not None

    @pytest.mark.asyncio
    async def test_close_raises_when_instance_not_found(self) -> None:
        """Closing a non-existent instance should raise ValueError."""
        manager = AgentInstanceManager()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await manager.close(uuid.uuid4(), mock_db)
