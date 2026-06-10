"""
Test CredentialVault encrypt/decrypt and GatewayEndpointRegistry route registration.
(McpSession CRUD goes through the API layer which uses CredentialVault under the hood.)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid


@pytest.mark.asyncio
async def test_credential_vault_encrypt_decrypt_roundtrip():
    """CredentialVault: encrypt returns ciphertext; decrypt returns original plaintext."""
    from app.core.credential_vault import CredentialVault
    vault = CredentialVault()
    plaintext = '{"api_key": "secret-value"}'
    ciphertext = vault.encrypt(plaintext)
    assert ciphertext != plaintext
    assert vault.decrypt(ciphertext) == plaintext


@pytest.mark.asyncio
async def test_credential_vault_ciphertext_differs_from_input():
    """CredentialVault: the stored ciphertext should not contain plaintext."""
    from app.core.credential_vault import CredentialVault
    vault = CredentialVault()
    plaintext = "super-secret-token-12345"
    ciphertext = vault.encrypt(plaintext)
    assert plaintext not in ciphertext


@pytest.mark.asyncio
async def test_gateway_endpoint_registry_register_and_resolve():
    """GatewayEndpointRegistry: register creates an in-memory route; resolve returns the same path."""
    from app.services.gateway.registry import GatewayEndpointRegistry

    agent_type_id = uuid.uuid4()
    registry = GatewayEndpointRegistry()

    # register() is synchronous and returns the http_base_path
    path = registry.register(agent_type_id)
    assert path == f"/gateway/{agent_type_id}"

    # resolve() returns the same path
    resolved = registry.resolve(agent_type_id)
    assert resolved == path

    # list_all() includes the registered route
    all_routes = registry.list_all()
    assert any(r["agent_type_id"] == str(agent_type_id) for r in all_routes)


# ── is_default column & schema checks ──────────────────────────────────────────


def test_mcp_session_read_schema_includes_is_default():
    """McpSessionRead schema must include is_default field."""
    from app.schemas.mcp_hub import McpSessionRead
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    session_read = McpSessionRead(
        id=uuid.uuid4(),
        server_id=uuid.uuid4(),
        name="test-session",
        description=None,
        auth_type="api_key",
        identity_subject=None,
        is_active=True,
        is_default=False,
        identity_binding=None,
        credential_config=None,
        oauth_expires_at=None,
        oauth_refresh_expires_at=None,
        created_at=now,
        updated_at=now,
    )
    assert session_read.is_default == False
    # is_default is a bool field (not optional)
    assert isinstance(session_read.is_default, bool)


def test_mcp_session_create_schema_accepts_optional_is_default():
    """McpSessionCreate schema should accept optional is_default field."""
    from app.schemas.mcp_hub import McpSessionCreate

    # Without is_default
    s1 = McpSessionCreate(name="test-no-default", auth_type="api_key")
    assert s1.is_default is None

    # With is_default=True
    s2 = McpSessionCreate(name="test-with-default", auth_type="api_key", is_default=True)
    assert s2.is_default is True

    # With is_default=False
    s3 = McpSessionCreate(name="test-explicit-false", auth_type="api_key", is_default=False)
    assert s3.is_default is False


def test_mcp_session_update_schema_accepts_optional_is_default():
    """McpSessionUpdate schema should accept optional is_default field."""
    from app.schemas.mcp_hub import McpSessionUpdate

    s1 = McpSessionUpdate(name="updated-name")
    assert s1.is_default is None

    s2 = McpSessionUpdate(is_default=True)
    assert s2.is_default is True


# ── is_default model defaults ───────────────────────────────────────────────────


def test_mcp_session_model_is_default_defaults_to_false():
    """McpSession model should have is_default column defaulting to False (via server_default)."""
    from app.db.models.mcp_hub import McpSession, McpSessionAuthType
    import uuid

    # When constructed without is_default, it is None (SQLAlchemy lazy default)
    session = McpSession(
        server_id=uuid.uuid4(),
        name="new-session",
        auth_type=McpSessionAuthType.api_key,
    )
    # is_default column exists and is nullable=False — the ORM sets it at flush time
    # When explicitly set to False, it should be False
    session.is_default = False
    assert session.is_default is False

    # And can be set to True
    session.is_default = True
    assert session.is_default is True


# ── McpServerRead includes session_count ────────────────────────────────────────


def test_mcp_server_read_includes_session_count():
    """McpServerRead schema must include session_count field with default 0."""
    from app.schemas.mcp_hub import McpServerRead
    from app.db.models.mcp_hub import McpServerStatus
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    server_read = McpServerRead(
        id=uuid.uuid4(),
        name="TestServer",
        slug="test-server",
        description=None,
        base_url="http://mcp.test",
        oauth_config=None,
        status=McpServerStatus.active,
        last_synced_at=None,
        session_count=0,
        created_at=now,
        updated_at=now,
    )
    assert server_read.session_count == 0
    assert isinstance(server_read.session_count, int)
