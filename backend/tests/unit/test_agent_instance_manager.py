"""Unit tests for AgentInstanceManager."""
import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.db.models.agents import AgentInstanceStatus
from app.services.agents.instance_manager import AgentInstanceManager, InstanceLimitError


class TestAgentInstanceManager:
    """Tests for spawn, activate, and close lifecycle transitions."""

    def _make_mock_agent_type(
        self, max_instances: int = 3
    ) -> MagicMock:
        at = MagicMock()
        at.id = uuid.uuid4()
        at.name = "test-agent"
        at.max_instances = max_instances
        at.is_active = True
        return at

    @pytest.mark.asyncio
    async def test_spawn_creates_instance(self) -> None:
        """Spawning should create an AgentInstance when the agent type is active."""
        manager = AgentInstanceManager()
        agent_type_id = uuid.uuid4()
        agent_type = self._make_mock_agent_type()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=agent_type)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        instance = await manager.spawn(agent_type_id, "test-user", mock_db)
        assert mock_db.add.called
        assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_spawn_creates_instance_when_under_limit(self) -> None:
        """Spawning should succeed for an active agent type."""
        manager = AgentInstanceManager()
        agent_type_id = uuid.uuid4()
        agent_type = self._make_mock_agent_type()

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=agent_type)

        # Mock flush and refresh
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        instance = await manager.spawn(agent_type_id, "test-user", mock_db)
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
