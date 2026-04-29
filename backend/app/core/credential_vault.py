"""AES-256 credential vault for secure storage and retrieval of secrets."""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CredentialVault:
    """
    AES-256-GCM encrypt/decrypt for stored credentials.

    Credentials are never logged or returned in API responses.
    Decryption only happens at call time.
    """

    def __init__(self) -> None:
        settings = get_settings()
        # Use exactly 32 bytes for AES-256
        key_bytes = settings.credential_vault_key.encode()[:32]
        # Pad if shorter
        key_bytes = key_bytes.ljust(32, b"\x00")
        self._key = key_bytes

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string with AES-256-GCM.

        Returns a base64-encoded string: nonce(12) + ciphertext + tag(16).
        """
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Concatenate nonce + ciphertext and base64-encode
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, ciphertext_b64: str) -> str:
        """
        Decrypt a base64-encoded AES-256-GCM ciphertext.

        Returns the original plaintext string.
        """
        raw = base64.b64decode(ciphertext_b64)
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(self._key)
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode("utf-8")


# Singleton
_vault: CredentialVault | None = None


def get_vault() -> CredentialVault:
    """Return the singleton CredentialVault instance."""
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
