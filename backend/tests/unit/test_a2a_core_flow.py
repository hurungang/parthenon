"""Unit tests for A2A core flow in Communication Hub.

These tests validate the DB-free boundary where Communication Hub delegates
all A2A preparation/disconnect persistence to Control Center data APIs.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.communication_hub.data_client import ControlCenterDataError
from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.schemas.agents import A2ARequest, A2AResponse
from app.services.skills.sop_orchestrator import SopOrchestrator, SopOrchestratorError


def _make_request_with_data_client(data_client: object) -> object:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(data_client=data_client)))


# ── A2A Request Handler Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a2a_request_handler_validates_target_agent_type() -> None:
    """A2A request handler maps Control Center 404 to HTTP 404."""
    from app.communication_hub.api.a2a import request_a2a

    body = A2ARequest(
        target_agent_type_slug="nonexistent-agent",
        conversation_metadata={"requester_instance_id": "req_123"},
        request_payload={"input": "test"},
    )
    data_client = MagicMock()
    data_client.prepare_a2a_request = AsyncMock(
        side_effect=ControlCenterDataError(
            "CC POST /internal/data/a2a/request returned 404: not found"
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await request_a2a(body, _make_request_with_data_client(data_client))

    assert exc_info.value.status_code == 404
    assert "returned 404" in exc_info.value.detail


@pytest.mark.asyncio
async def test_a2a_request_handler_returns_prepared_session_link() -> None:
    """A2A request returns Control Center prepared receiver/session identifiers."""
    from app.communication_hub.api.a2a import request_a2a

    body = A2ARequest(
        target_agent_type_slug="test-receiver-agent",
        conversation_metadata={"requester_instance_id": "req_123"},
        request_payload={"input": "test"},
    )
    data_client = MagicMock()
    data_client.prepare_a2a_request = AsyncMock(
        return_value={
            "receiver_instance_id": "receiver-001",
            "session_link_id": "link-001",
            "status": "accepted",
            "receiver_session_id": str(uuid.uuid4()),
        }
    )

    response = await request_a2a(body, _make_request_with_data_client(data_client))

    assert isinstance(response, A2AResponse)
    assert response.receiver_instance_id == "receiver-001"
    assert response.session_link_id == "link-001"
    assert response.status == "accepted"


@pytest.mark.asyncio
async def test_a2a_request_handler_maps_400_from_control_center() -> None:
    """A2A request maps Control Center validation errors to HTTP 400."""
    from app.communication_hub.api.a2a import request_a2a

    body = A2ARequest(
        target_agent_type_slug="inactive-agent",
        conversation_metadata={},
        request_payload={},
    )
    data_client = MagicMock()
    data_client.prepare_a2a_request = AsyncMock(
        side_effect=ControlCenterDataError(
            "CC POST /internal/data/a2a/request returned 400: inactive"
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await request_a2a(body, _make_request_with_data_client(data_client))

    assert exc_info.value.status_code == 400
    assert "returned 400" in exc_info.value.detail


@pytest.mark.asyncio
async def test_a2a_disconnect_uses_control_center_data_api() -> None:
    """A2A disconnect delegates completion persistence to Control Center."""
    from app.communication_hub.api.a2a import disconnect_a2a

    data_client = MagicMock()
    data_client.disconnect_a2a_session = AsyncMock(
        return_value={"status": "disconnected", "session_link_id": "session_789"}
    )

    result = await disconnect_a2a("session_789", _make_request_with_data_client(data_client))

    assert result["status"] == "disconnected"
    assert result["session_link_id"] == "session_789"


# ── SopOrchestrator A2A Execution Tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_sop_orchestrator_handles_agent_delegation_step(db_session):
    """SopOrchestrator executes agent_delegation step and calls A2A endpoint."""
    from app.db.models.skills import Sop, SopStep, SopStepType
    
    # Create test data
    target_agent_type = AgentType(
        id=uuid.uuid4(),
        name="delegation-target",
        is_active=True,
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(target_agent_type)
    await db_session.flush()
    
    sop = Sop(
        id=uuid.uuid4(),
        name="test-sop-delegation",
        description="Test SOP with delegation",
    )
    db_session.add(sop)
    await db_session.flush()
    
    step = SopStep(
        id=uuid.uuid4(),
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.agent_delegation,
        target_agent_type_id=target_agent_type.id,
        name="Delegate to receiver",
        step_config={"payload": "test"},
    )
    db_session.add(step)
    await db_session.flush()
    
    orchestrator = SopOrchestrator()
    
    # Mock httpx.AsyncClient to simulate A2A response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "receiver_instance_id": "recv_123",
        "session_link_id": "session_456",
        "status": "accepted",
    }
    mock_response.raise_for_status = MagicMock()
    
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__.return_value = mock_client
    
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await orchestrator._execute_step(step, {"test": "context"}, db_session)
    
    # Verify result structure
    assert result["type"] == "agent_delegation"
    assert result["target_agent_type_slug"] == "delegation-target"
    assert result["receiver_instance_id"] == "recv_123"
    assert result["session_link_id"] == "session_456"
    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_sop_orchestrator_raises_error_for_missing_agent_delegation_target(db_session):
    """SopOrchestrator raises error when agent_delegation step references non-existent target."""
    from app.db.models.skills import Sop, SopStep, SopStepType
    
    sop = Sop(
        id=uuid.uuid4(),
        name="test-sop-missing-target",
        description="Test SOP with missing delegation target",
    )
    db_session.add(sop)
    await db_session.flush()
    
    step = SopStep(
        id=uuid.uuid4(),
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.agent_delegation,
        target_agent_type_id=uuid.uuid4(),  # Non-existent
        name="Delegate to missing agent",
    )
    db_session.add(step)
    await db_session.flush()
    
    orchestrator = SopOrchestrator()
    
    with pytest.raises(SopOrchestratorError) as exc_info:
        await orchestrator._execute_step(step, {}, db_session)
    
    assert "not found" in str(exc_info.value)


# ── Slug Validation Tests ──────────────────────────────────────────────────────


def test_agent_identity_create_validates_slug():
    """AgentIdentityCreate schema enforces slug pattern."""
    from app.schemas.agents import AgentIdentityCreate
    from pydantic import ValidationError
    
    # Valid slug
    valid = AgentIdentityCreate(
        name="valid-agent-identity",
        realm_name="test-realm",
        realm_username="agent-user",
    )
    assert valid.name == "valid-agent-identity"
    
    # Invalid slug — uppercase not allowed
    with pytest.raises(ValidationError) as exc_info:
        AgentIdentityCreate(
            name="Invalid-Agent",
            realm_name="test-realm",
            realm_username="agent-user",
        )
    assert "should match pattern" in str(exc_info.value)
    
    # Invalid slug — spaces not allowed
    with pytest.raises(ValidationError) as exc_info:
        AgentIdentityCreate(
            name="invalid agent",
            realm_name="test-realm",
            realm_username="agent-user",
        )
    assert "should match pattern" in str(exc_info.value)
    
    # Invalid slug — special characters not allowed
    with pytest.raises(ValidationError) as exc_info:
        AgentIdentityCreate(
            name="invalid@agent",
            realm_name="test-realm",
            realm_username="agent-user",
        )
    assert "should match pattern" in str(exc_info.value)


def test_agent_identity_update_validates_slug_when_provided():
    """AgentIdentityUpdate schema enforces slug pattern on name update."""
    from app.schemas.agents import AgentIdentityUpdate
    from pydantic import ValidationError
    
    # Valid update
    valid = AgentIdentityUpdate(name="updated-agent-name")
    assert valid.name == "updated-agent-name"
    
    # Invalid update — uppercase not allowed
    with pytest.raises(ValidationError) as exc_info:
        AgentIdentityUpdate(name="Invalid-Update")
    assert "should match pattern" in str(exc_info.value)
    
    # None is allowed (optional update)
    none_update = AgentIdentityUpdate(name=None)
    assert none_update.name is None
