"""Unit tests for AgentIdentityService — CRUD and OAuth flow operations.

Adjustment: Agent identities are users in a dedicated agent realm (realm_user model).
OAuth sign-in stores encrypted access/refresh tokens. The authorize URL targets the
agent realm, not the user realm.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.identity_service import (
    AgentIdentityService,
    AgentIdentityNotFoundError,
    AgentIdentityConflictError,
    AgentOAuthError,
)
from app.db.models.agents import AgentIdentity, AgentIdentityType, AgentIdentityStatus


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_identity(
    identity_id: uuid.UUID | None = None,
    name: str = "Test Identity",
    identity_type: AgentIdentityType = AgentIdentityType.realm_user,
    status: AgentIdentityStatus = AgentIdentityStatus.active,
    realm_name: str = "ai_agents",
    realm_username: str = "agent-user-1",
) -> AgentIdentity:
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id or uuid.uuid4()
    identity.name = name
    identity.identity_type = identity_type
    identity.realm_name = realm_name
    identity.realm_username = realm_username
    identity.access_token = None
    identity.refresh_token = None
    identity.token_expires_at = None
    identity.status = status
    return identity


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


# ── Create ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_identity_realm_user():
    """create_identity (realm_user type) creates an identity in the configured agent realm."""
    service = AgentIdentityService()
    identity = _make_identity(identity_type=AgentIdentityType.realm_user)
    db = _mock_db()

    with patch("app.services.agents.identity_service.AgentIdentity", return_value=identity):
        result = await service.create_identity(
            name="Agent Bot",
            realm_name="ai_agents",
            realm_username="agent-user-1",
            status=AgentIdentityStatus.active,
            db=db,
        )

    assert result.identity_type == AgentIdentityType.realm_user
    assert result.realm_name == "ai_agents"
    assert result.realm_username == "agent-user-1"
    db.flush.assert_called_once()
    db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_create_identity_default_type_is_realm_user():
    """create_identity without explicit identity_type defaults to realm_user."""
    service = AgentIdentityService()
    identity = _make_identity(identity_type=AgentIdentityType.realm_user)
    db = _mock_db()

    with patch("app.services.agents.identity_service.AgentIdentity", return_value=identity):
        result = await service.create_identity(
            name="Default Bot",
            realm_name="ai_agents",
            realm_username="default-agent",
            status=AgentIdentityStatus.active,
            db=db,
        )

    # The identity_type should be realm_user (the only supported type for new identities)
    assert result.identity_type == AgentIdentityType.realm_user


@pytest.mark.asyncio
async def test_create_identity_tokens_null_at_creation():
    """Tokens are null at creation time — set only after OAuth flow completes."""
    service = AgentIdentityService()
    identity = _make_identity()
    db = _mock_db()

    with patch("app.services.agents.identity_service.AgentIdentity", return_value=identity):
        result = await service.create_identity(
            name="No-Token Bot",
            realm_name="ai_agents",
            realm_username="no-token-user",
            status=AgentIdentityStatus.active,
            db=db,
        )

    assert result.access_token is None
    assert result.refresh_token is None
    assert result.token_expires_at is None


# ── List ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_identities_returns_all():
    """list_identities returns all identity records ordered by name."""
    service = AgentIdentityService()
    id_a = _make_identity(name="Alice Bot")
    id_b = _make_identity(name="Beta Bot")

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [id_a, id_b]

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    result = await service.list_identities(db)

    assert len(result) == 2
    assert result[0].name == "Alice Bot"


# ── Get ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_identity_returns_when_found():
    """get_identity returns the identity when it exists in the DB."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id)

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    result = await service.get_identity(identity_id, db)
    assert result.id == identity_id


@pytest.mark.asyncio
async def test_get_identity_raises_not_found():
    """get_identity raises AgentIdentityNotFoundError when the row is missing."""
    service = AgentIdentityService()

    db = _mock_db()
    db.get = AsyncMock(return_value=None)

    with pytest.raises(AgentIdentityNotFoundError):
        await service.get_identity(uuid.uuid4(), db)


# ── Update ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_identity_status():
    """update_identity changes the status field correctly."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id, status=AgentIdentityStatus.active)

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    async def refresh_side_effect(obj):
        pass

    db.refresh.side_effect = refresh_side_effect

    result = await service.update_identity(
        identity_id=identity_id,
        name=None,
        realm_name=None,
        realm_username=None,
        status=AgentIdentityStatus.suspended,
        db=db,
    )

    assert result.status == AgentIdentityStatus.suspended


@pytest.mark.asyncio
async def test_update_identity_preserves_unchanged_fields():
    """update_identity leaves fields unchanged when None is passed for them."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id, name="Original Name")

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    async def refresh_side_effect(obj):
        pass

    db.refresh.side_effect = refresh_side_effect

    result = await service.update_identity(
        identity_id=identity_id,
        name=None,
        realm_name=None,
        realm_username=None,
        status=None,
        db=db,
    )

    assert result.name == "Original Name"


# ── Delete ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_identity_succeeds_when_not_referenced():
    """delete_identity succeeds when no AgentType references the identity."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id)

    ref_result = MagicMock()
    ref_result.scalar_one_or_none.return_value = None  # no referencing type

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)
    db.execute = AsyncMock(return_value=ref_result)
    db.delete = AsyncMock()

    await service.delete_identity(identity_id, db)

    db.delete.assert_called_once_with(identity)


@pytest.mark.asyncio
async def test_delete_identity_raises_conflict_when_referenced():
    """delete_identity raises AgentIdentityConflictError (409) when an AgentType references it."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id)

    ref_result = MagicMock()
    ref_result.scalar_one_or_none.return_value = uuid.uuid4()  # referencing agent type

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)
    db.execute = AsyncMock(return_value=ref_result)

    with pytest.raises(AgentIdentityConflictError):
        await service.delete_identity(identity_id, db)


# ── OAuth — Authorize URL ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_oauth_authorize_url_targets_agent_realm():
    """get_oauth_authorize_url points to the configured agent realm, not the user realm."""
    service = AgentIdentityService()
    state = str(uuid.uuid4())

    with (
        patch(
            "app.services.agents.identity_service._keycloak_base_url",
            return_value="http://localhost:8082",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_name",
            return_value="ai_agents",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_client_id",
            return_value="parthenon-api",
        ),
    ):
        url = service.get_oauth_authorize_url(
            state=state,
            redirect_uri="http://localhost:5173/agents/identities/oauth/callback",
        )

    # Must target the agent realm, not the user realm
    assert "/realms/ai_agents/" in url
    assert "response_type=code" in url
    assert "client_id=parthenon-api" in url


@pytest.mark.asyncio
async def test_get_oauth_authorize_url_encodes_state_parameter():
    """get_oauth_authorize_url encodes the state parameter in the URL."""
    service = AgentIdentityService()
    state = str(uuid.uuid4())

    with (
        patch(
            "app.services.agents.identity_service._keycloak_base_url",
            return_value="http://localhost:8082",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_name",
            return_value="ai_agents",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_client_id",
            return_value="parthenon-api",
        ),
    ):
        url = service.get_oauth_authorize_url(
            state=state,
            redirect_uri="http://localhost:5173/agents/identities/oauth/callback",
        )

    assert state in url


@pytest.mark.asyncio
async def test_get_oauth_authorize_url_requests_offline_access():
    """get_oauth_authorize_url requests offline_access scope for refresh token."""
    service = AgentIdentityService()
    state = "new"

    with (
        patch(
            "app.services.agents.identity_service._keycloak_base_url",
            return_value="http://localhost:8082",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_name",
            return_value="ai_agents",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_client_id",
            return_value="parthenon-api",
        ),
    ):
        url = service.get_oauth_authorize_url(
            state=state,
            redirect_uri="http://localhost:5173/callback",
        )

    assert "offline_access" in url


# ── OAuth — Complete Flow ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_oauth_flow_stores_encrypted_tokens():
    """complete_oauth_flow stores encrypted access and refresh tokens and marks identity active."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id, status=AgentIdentityStatus.active)
    identity.access_token = None
    identity.refresh_token = None
    identity.token_expires_at = None

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    fake_token_response = {
        "access_token": "raw-access-token",
        "refresh_token": "raw-refresh-token",
        "expires_in": 300,
    }

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = fake_token_response

    mock_vault = MagicMock()
    mock_vault.encrypt.side_effect = lambda s: f"enc:{s}"

    with (
        patch(
            "app.services.agents.identity_service._keycloak_base_url",
            return_value="http://localhost:8082",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_name",
            return_value="ai_agents",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_client_id",
            return_value="parthenon-api",
        ),
        patch(
            "app.services.agents.identity_service.get_vault",
            return_value=mock_vault,
        ),
        patch("httpx.AsyncClient") as mock_http_client_cls,
    ):
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await service.complete_oauth_flow(
            identity_id=identity_id,
            code="auth-code-123",
            redirect_uri="http://localhost:5173/callback",
            db=db,
        )

    assert identity.access_token == "enc:raw-access-token"
    assert identity.refresh_token == "enc:raw-refresh-token"
    assert identity.token_expires_at is not None
    assert identity.status == AgentIdentityStatus.active


@pytest.mark.asyncio
async def test_complete_oauth_flow_raises_on_token_exchange_failure():
    """complete_oauth_flow raises AgentOAuthError when the IdP returns an error response."""
    service = AgentIdentityService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id)

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    mock_http_response = MagicMock()
    mock_http_response.status_code = 400
    mock_http_response.text = "invalid_grant"

    with (
        patch(
            "app.services.agents.identity_service._keycloak_base_url",
            return_value="http://localhost:8082",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_name",
            return_value="ai_agents",
        ),
        patch(
            "app.services.agents.identity_service._agent_realm_client_id",
            return_value="parthenon-api",
        ),
        patch(
            "app.services.agents.identity_service.get_vault",
            return_value=MagicMock(),
        ),
        patch("httpx.AsyncClient") as mock_http_client_cls,
    ):
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(AgentOAuthError):
            await service.complete_oauth_flow(
                identity_id=identity_id,
                code="bad-code",
                redirect_uri="http://localhost:5173/callback",
                db=db,
            )


@pytest.mark.asyncio
async def test_complete_oauth_flow_raises_not_found_for_missing_identity():
    """complete_oauth_flow raises AgentIdentityNotFoundError when identity_id does not exist."""
    service = AgentIdentityService()

    db = _mock_db()
    db.get = AsyncMock(return_value=None)

    with pytest.raises(AgentIdentityNotFoundError):
        await service.complete_oauth_flow(
            identity_id=uuid.uuid4(),
            code="some-code",
            redirect_uri="http://localhost:5173/callback",
            db=db,
        )

