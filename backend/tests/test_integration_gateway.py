"""Tests for the CH integration gateway rate limiter and origin matcher (pure logic)."""
from app.communication_hub.integration.client_auth import _origin_allowed
from app.communication_hub.integration.rate_limit import is_rate_limited, reset


def test_rate_limit_allows_under_limit():
    reset()
    for _ in range(5):
        assert is_rate_limited("c1", 5, "per_minute") is False


def test_rate_limit_blocks_over_limit():
    reset()
    for _ in range(3):
        assert is_rate_limited("c2", 3, "per_minute") is False
    assert is_rate_limited("c2", 3, "per_minute") is True


def test_rate_limit_no_limit_passes():
    reset()
    for _ in range(100):
        assert is_rate_limited("c3", None, None) is False


def test_rate_limit_is_per_key():
    reset()
    for _ in range(2):
        assert is_rate_limited("key-a", 2, "per_minute") is False
    assert is_rate_limited("key-a", 2, "per_minute") is True
    # A different key has its own budget.
    assert is_rate_limited("key-b", 2, "per_minute") is False


def test_origin_exact_match():
    assert _origin_allowed("https://acme.com", ["https://acme.com"]) is True
    assert _origin_allowed("https://other.com", ["https://acme.com"]) is False


def test_origin_wildcard_subdomain():
    assert _origin_allowed("https://app.acme.com", ["https://*.acme.com"]) is True
    assert _origin_allowed("https://a.b.acme.com", ["https://*.acme.com"]) is True


def test_origin_wildcard_rejects_path_smuggling():
    # `*` must not cross `/` — a path cannot be smuggled into an origin match.
    assert _origin_allowed("https://evil.com/x.acme.com", ["https://*.acme.com"]) is False


def test_origin_bare_star_allows_all():
    assert _origin_allowed("https://anything.example", ["*"]) is True


def test_origin_no_match():
    assert _origin_allowed("https://acme.com", []) is False
