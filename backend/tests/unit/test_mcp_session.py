"""
Test CredentialVault encrypt/decrypt and GatewayEndpointRegistry route registration.
(McpSession CRUD goes through the API layer which uses CredentialVault under the hood.)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


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
    """GatewayEndpointRegistry: register creates a route; resolve returns the same route."""
    from app.services.gateway.registry import GatewayEndpointRegistry, GatewayRoute

    agent_type_id = uuid.uuid4()
    registry = GatewayEndpointRegistry()

    # Mock DB: first resolve returns None (not registered yet), then returns the route
    route = MagicMock(spec=GatewayRoute)
    route.agent_type_id = agent_type_id
    route.http_base_path = f"/gateway/{agent_type_id}"

    mock_db = AsyncMock()
    # First execute (resolve inside register) → None; second execute (list/resolve) → route
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=route)),
        ]
    )
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()

    created = await registry.register(agent_type_id, mock_db)
    assert created is not None

    resolved = await registry.resolve(agent_type_id, mock_db)
    assert resolved is not None
