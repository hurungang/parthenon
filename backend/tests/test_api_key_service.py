"""Unit tests for ApiKeyService — key generation, hashing, and validation."""
import hashlib
import uuid

import pytest

from app.services.api_key_service import (
    _hash_key,
    check_duplicate_active_key,
    generate_api_key,
    hash_api_key,
)


class TestKeyGeneration:
    """Test API key generation format and security properties."""

    def test_key_has_correct_prefix(self):
        raw_key, _, prefix = generate_api_key()
        assert raw_key.startswith("phn_sk_")
        assert prefix == "phn_sk_"

    def test_key_has_correct_length(self):
        raw_key, _, _ = generate_api_key()
        # "phn_sk_" (7 chars) + 32 random chars = 39 total
        assert len(raw_key) == 39

    def test_key_is_random(self):
        """Generate two keys and verify they are different."""
        key1, _, _ = generate_api_key()
        key2, _, _ = generate_api_key()
        assert key1 != key2

    def test_key_contains_only_valid_chars(self):
        import string
        raw_key, _, _ = generate_api_key()
        prefix = "phn_sk_"
        random_part = raw_key[len(prefix):]
        allowed = set(string.ascii_letters + string.digits)
        assert all(c in allowed for c in random_part)

    def test_key_hash_is_sha256_hex(self):
        raw_key, key_hash, _ = generate_api_key()
        # SHA-256 hex digest is 64 hex chars
        assert len(key_hash) == 64
        assert all(c in "0123456789abcdef" for c in key_hash)
        # Verify the hash is correct
        expected = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        assert key_hash == expected

    def test_hash_api_key_public_wrapper(self):
        raw_key, _, _ = generate_api_key()
        h = hash_api_key(raw_key)
        assert h == _hash_key(raw_key)

    def test_different_keys_have_different_hashes(self):
        _, h1, _ = generate_api_key()
        _, h2, _ = generate_api_key()
        assert h1 != h2

    def test_same_key_has_same_hash(self):
        """Generating the same key (theoretically possible but extremely unlikely)
        would produce the same hash."""
        # Verification of deterministic hashing
        test_key = "phn_sk_abc123def456ghi789jkl012mno345pq"
        h1 = _hash_key(test_key)
        h2 = _hash_key(test_key)
        assert h1 == h2
