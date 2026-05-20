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
