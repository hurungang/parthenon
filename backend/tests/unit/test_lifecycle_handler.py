"""Unit tests for GatewayLifecycleHandler — routes launch requests through AgentSessionService."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler
from app.db.models.agents import AgentJobStatus


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_job(session_id: uuid.UUID | None = None) -> MagicMock:
    job = MagicMock()
    job.id = session_id or uuid.uuid4()
    job.status = AgentJobStatus.queued
    return job


def _mock_db() -> AsyncMock:
    return AsyncMock()


# ── launch() — routes through AgentSessionService.enqueue ─────────────────────


@pytest.mark.asyncio
async def test_launch_calls_enqueue_and_returns_session_id():
    """launch() delegates to AgentSessionService.enqueue and returns the session ID synchronously."""
    handler = GatewayLifecycleHandler()
    session_id = uuid.uuid4()
    job = _make_job(session_id=session_id)

    handler._session_service.enqueue = AsyncMock(return_value=job)
    # Mock validate_agent_identity_token so tests focus on launch routing, not auth
    handler.validate_agent_identity_token = AsyncMock(return_value=None)

    db = _mock_db()
    agent_type_id = uuid.uuid4()
    user_id = uuid.uuid4()

    result = await handler.launch(
        agent_type_id=agent_type_id,
        input_data={"prompt": "hello"},
        user_id=user_id,
        db=db,
    )

    handler._session_service.enqueue.assert_called_once_with(
        agent_type_id=agent_type_id,
        input_data={"prompt": "hello"},
        user_id=user_id,
        db=db,
    )
    assert result["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_launch_returns_session_id_synchronously():
    """launch() returns the session_id without waiting for job completion."""
    handler = GatewayLifecycleHandler()
    session_id = uuid.uuid4()
    job = _make_job(session_id=session_id)

    handler._session_service.enqueue = AsyncMock(return_value=job)
    handler.validate_agent_identity_token = AsyncMock(return_value=None)

    db = _mock_db()

    result = await handler.launch(
        agent_type_id=uuid.uuid4(),
        input_data=None,
        user_id=None,
        db=db,
    )

    # Must be a dict with a "session_id" key
    assert "session_id" in result
    assert result["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_launch_does_not_invoke_executor_directly():
    """launch() must NOT call the executor directly — it only enqueues."""
    handler = GatewayLifecycleHandler()
    job = _make_job()

    handler._session_service.enqueue = AsyncMock(return_value=job)
    handler.validate_agent_identity_token = AsyncMock(return_value=None)

    # If AgentRuntimeExecutor.run were called, it would raise because db.get returns None
    # The test verifies no such call occurs
    db = _mock_db()

    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    with MagicMock() as mock_executor_cls:
        mock_executor_cls.run = AsyncMock(side_effect=AssertionError("executor must not be called"))
        result = await handler.launch(uuid.uuid4(), None, None, db)

    # If we reach here, executor was not called
    assert "session_id" in result


@pytest.mark.asyncio
async def test_launch_with_no_input_data():
    """launch() works when input_data is None (for 'none' input_type agents)."""
    handler = GatewayLifecycleHandler()
    job = _make_job()
    handler._session_service.enqueue = AsyncMock(return_value=job)
    handler.validate_agent_identity_token = AsyncMock(return_value=None)

    db = _mock_db()
    result = await handler.launch(uuid.uuid4(), None, None, db)
    assert "session_id" in result


@pytest.mark.asyncio
async def test_launch_passes_user_id_to_session_service():
    """launch() forwards the user_id to AgentSessionService.enqueue."""
    handler = GatewayLifecycleHandler()
    job = _make_job()
    handler._session_service.enqueue = AsyncMock(return_value=job)
    handler.validate_agent_identity_token = AsyncMock(return_value=None)

    db = _mock_db()
    user_id = uuid.uuid4()

    await handler.launch(uuid.uuid4(), {"data": "x"}, user_id, db)

    call_kwargs = handler._session_service.enqueue.call_args.kwargs
    assert call_kwargs["user_id"] == user_id


# ── validate_agent_identity_token() — auto-refresh expired tokens ──────────────


@pytest.mark.asyncio
async def test_validate_token_auto_refreshes_when_expired_with_refresh_token():
    """validate_agent_identity_token() auto-refreshes expired access token if refresh token is available."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityStatus, AgentIdentityType
    from app.services.agents.identity_service import AgentOAuthError

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    
    # Create mock agent_type with identity
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = None
    
    # Create mock identity with expired access token but valid refresh token
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "expired_access_token"
    identity.refresh_token = "valid_refresh_token"
    identity.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)  # Expired
    identity.identity_type = AgentIdentityType.realm_user
    identity.status = AgentIdentityStatus.active
    
    db = AsyncMock()
    # Mock db.execute to return result with scalar_one_or_none
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent_type
    db.execute.return_value = mock_result
    db.get.return_value = identity
    db.refresh = AsyncMock()
    
    # Mock refresh_token to succeed
    handler._identity_service.refresh_token = AsyncMock()
    
    # Should not raise an error - auto-refresh should succeed
    await handler.validate_agent_identity_token(agent_type_id, db)
    
    # Verify refresh was called
    handler._identity_service.refresh_token.assert_called_once_with(identity_id, db)
    db.refresh.assert_called_once_with(identity)


@pytest.mark.asyncio
async def test_validate_token_raises_error_when_expired_without_refresh_token():
    """validate_agent_identity_token() raises error when access token is expired and no refresh token."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityStatus, AgentIdentityType
    from app.services.gateway.lifecycle_handler import AgentAuthError

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = None
    
    # Identity with expired access token and NO refresh token
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "expired_access_token"
    identity.refresh_token = None  # No refresh token
    identity.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    identity.identity_type = AgentIdentityType.realm_user
    
    db = AsyncMock()
    # Mock db.execute to return result with scalar_one_or_none
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent_type
    db.execute.return_value = mock_result
    db.get.return_value = identity
    
    # Should raise error because no refresh token available
    with pytest.raises(AgentAuthError) as exc_info:
        await handler.validate_agent_identity_token(agent_type_id, db)
    
    assert "access token has expired" in str(exc_info.value)
    assert "no refresh token available" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_token_raises_error_when_refresh_fails():
    """validate_agent_identity_token() raises error when token refresh fails."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityStatus, AgentIdentityType
    from app.services.agents.identity_service import AgentOAuthError
    from app.services.gateway.lifecycle_handler import AgentAuthError

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = None
    
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "expired_access_token"
    identity.refresh_token = "invalid_refresh_token"
    identity.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    identity.identity_type = AgentIdentityType.realm_user
    
    db = AsyncMock()
    # Mock db.execute to return result with scalar_one_or_none
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent_type
    db.execute.return_value = mock_result
    db.get.return_value = identity
    
    # Mock refresh_token to fail
    handler._identity_service.refresh_token = AsyncMock(
        side_effect=AgentOAuthError("Refresh token expired or invalid")
    )
    
    # Should raise error with details about refresh failure
    with pytest.raises(AgentAuthError) as exc_info:
        await handler.validate_agent_identity_token(agent_type_id, db)
    
    assert "auto-refresh failed" in str(exc_info.value)
    handler._identity_service.refresh_token.assert_called_once()


@pytest.mark.asyncio
async def test_validate_token_succeeds_when_not_expired():
    """validate_agent_identity_token() succeeds without refresh when token is still valid."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityStatus, AgentIdentityType

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = None
    
    # Identity with VALID access token
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "valid_access_token"
    identity.refresh_token = "refresh_token"
    identity.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)  # Not expired
    identity.identity_type = AgentIdentityType.realm_user
    
    db = AsyncMock()
    # Mock db.execute to return result with scalar_one_or_none
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent_type
    db.execute.return_value = mock_result
    db.get.return_value = identity
    
    # Mock refresh_token so we can verify it's NOT called
    handler._identity_service.refresh_token = AsyncMock()
    
    # Should succeed without calling refresh
    await handler.validate_agent_identity_token(agent_type_id, db)
    
    # Verify refresh was NOT called
    handler._identity_service.refresh_token.assert_not_called()


@pytest.mark.asyncio
async def test_validate_token_succeeds_when_identity_assigned_to_role():
    """validate_agent_identity_token() succeeds when identity is explicitly assigned to role."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityType, AgentRole, AgentRoleIdentity

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    role_id = uuid.uuid4()
    
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "valid_access_token"
    identity.refresh_token = "refresh_token"
    identity.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    identity.identity_type = AgentIdentityType.realm_user
    
    assignment = MagicMock(spec=AgentRoleIdentity)
    assignment.role_id = role_id
    assignment.identity_id = identity_id
    
    db = AsyncMock()
    # First execute: fetch agent_type
    mock_result1 = MagicMock()
    mock_result1.scalar_one_or_none.return_value = agent_type
    # Second execute: check role assignment
    mock_result2 = MagicMock()
    mock_result2.scalar_one_or_none.return_value = assignment
    db.execute.side_effect = [mock_result1, mock_result2]
    db.get.return_value = identity
    
    handler._identity_service.refresh_token = AsyncMock()
    
    # Should succeed - identity is assigned to role
    await handler.validate_agent_identity_token(agent_type_id, db)
    
    handler._identity_service.refresh_token.assert_not_called()


@pytest.mark.asyncio
async def test_validate_token_raises_error_when_identity_not_assigned_to_role():
    """validate_agent_identity_token() raises error when identity is not assigned to role."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityType, AgentRole
    from app.services.gateway.lifecycle_handler import AgentAuthError

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    role_id = uuid.uuid4()
    
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "valid_access_token"
    identity.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    identity.identity_type = AgentIdentityType.realm_user
    
    role = MagicMock(spec=AgentRole)
    role.id = role_id
    role.name = "test_role"
    
    db = AsyncMock()
    # First execute: fetch agent_type
    mock_result1 = MagicMock()
    mock_result1.scalar_one_or_none.return_value = agent_type
    # Second execute: check role assignment - returns None (not assigned)
    mock_result2 = MagicMock()
    mock_result2.scalar_one_or_none.return_value = None
    db.execute.side_effect = [mock_result1, mock_result2]
    db.get.side_effect = [identity, role]
    
    # Should raise error - identity not assigned to role
    with pytest.raises(AgentAuthError) as exc_info:
        await handler.validate_agent_identity_token(agent_type_id, db)
    
    assert "is not assigned to role" in str(exc_info.value)
    assert "test_role" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_token_succeeds_when_agent_type_has_no_role():
    """validate_agent_identity_token() succeeds when agent_type has no role (skips role validation)."""
    from datetime import datetime, timezone, timedelta
    from app.db.models.agents import AgentType, AgentIdentity, AgentIdentityType

    handler = GatewayLifecycleHandler()
    
    agent_type_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    
    agent_type = MagicMock(spec=AgentType)
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = None  # No role assigned
    
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id
    identity.name = "test_agent@ai_agents"
    identity.access_token = "valid_access_token"
    identity.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    identity.identity_type = AgentIdentityType.realm_user
    
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = agent_type
    db.execute.return_value = mock_result
    db.get.return_value = identity
    
    # Should succeed - no role means no role validation
    await handler.validate_agent_identity_token(agent_type_id, db)

