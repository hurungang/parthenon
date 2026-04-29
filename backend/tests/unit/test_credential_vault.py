"""Unit tests for credential vault (AES-256 encrypt/decrypt)."""
import os

import pytest

# Set env before importing settings-dependent modules
os.environ["CREDENTIAL_VAULT_KEY"] = "test-32-byte-key-for-aes-256-enc!"
os.environ["SECRET_KEY"] = "test-secret-key"

from app.core.credential_vault import CredentialVault


class TestCredentialVault:
    """Tests for AES-256 encrypt/decrypt operations."""

    def test_encrypt_returns_different_string_than_input(self) -> None:
        vault = CredentialVault()
        plaintext = "my-super-secret-api-key"
        ciphertext = vault.encrypt(plaintext)
        assert ciphertext != plaintext

    def test_decrypt_returns_original_plaintext(self) -> None:
        vault = CredentialVault()
        plaintext = "my-super-secret-api-key"
        ciphertext = vault.encrypt(plaintext)
        decrypted = vault.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_produces_unique_ciphertext_each_call(self) -> None:
        """Each encryption call should produce a unique ciphertext (random nonce)."""
        vault = CredentialVault()
        plaintext = "same-plaintext"
        c1 = vault.encrypt(plaintext)
        c2 = vault.encrypt(plaintext)
        assert c1 != c2

    def test_encrypt_empty_string(self) -> None:
        vault = CredentialVault()
        ciphertext = vault.encrypt("")
        assert vault.decrypt(ciphertext) == ""

    def test_encrypt_unicode_string(self) -> None:
        vault = CredentialVault()
        plaintext = "日本語テスト 🔐"
        ciphertext = vault.encrypt(plaintext)
        assert vault.decrypt(ciphertext) == plaintext

    def test_decrypt_invalid_ciphertext_raises(self) -> None:
        vault = CredentialVault()
        with pytest.raises(Exception):
            vault.decrypt("not-valid-base64-or-ciphertext!!!")

    def test_json_credentials_roundtrip(self) -> None:
        """JSON credential dict should survive encrypt → decrypt."""
        import json

        vault = CredentialVault()
        creds = {"api_key": "sk-abc123", "region": "us-east-1"}
        ciphertext = vault.encrypt(json.dumps(creds))
        recovered = json.loads(vault.decrypt(ciphertext))
        assert recovered == creds
