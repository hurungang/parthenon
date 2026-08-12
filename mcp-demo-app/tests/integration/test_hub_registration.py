"""Integration tests for hub registration and tool sync.

Requires the Parthenon MCP Hub (backend) to be running. If the hub is not
reachable, all tests in this module are skipped automatically.

These tests make real HTTP calls to the hub and verify that the demo app can
register, handle 409 idempotency, and trigger a tool sync.
"""
from __future__ import annotations

import os

import httpx
import pytest

# ── Service availability check ────────────────────────────────────────────────

_HUB_BASE_URL = os.environ.get("HUB_BASE_URL", "http://localhost:8000")
_HUB_API_TOKEN = os.environ.get("HUB_API_TOKEN", "test-token")
_APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:7001")
_SLUG = os.environ.get("APP_SLUG", "demo")


def _hub_available_with_valid_token() -> bool:
    """Check hub is reachable AND the configured API token is accepted."""
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(
                f"{_HUB_BASE_URL}/api/v1/mcp/servers",
                headers={"Authorization": f"Bearer {_HUB_API_TOKEN}"},
            )
            # 401/403 means hub is up but token is invalid — skip
            return r.status_code not in (401, 403)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _hub_available_with_valid_token(),
    reason=(
        f"Hub not reachable or API token invalid at {_HUB_BASE_URL} "
        "— skipping hub integration tests"
    ),
)


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_register_with_hub_success_or_idempotent():
    """Scenario 3.10: registration succeeds or returns 409 (idempotent restart).

    Both outcomes are valid — the function must complete without raising.
    """
    from app.registration import register_with_hub

    # Should not raise regardless of whether the server is already registered
    await register_with_hub(
        hub_base_url=_HUB_BASE_URL,
        api_token=_HUB_API_TOKEN,
        slug=_SLUG,
        app_base_url=_APP_BASE_URL,
    )


async def test_registered_server_appears_in_hub_list():
    """Scenario 3.11: after registration, the slug 'demo' appears in /api/v1/mcp/servers."""
    from app.registration import register_with_hub

    await register_with_hub(
        hub_base_url=_HUB_BASE_URL,
        api_token=_HUB_API_TOKEN,
        slug=_SLUG,
        app_base_url=_APP_BASE_URL,
    )

    headers = {
        "Authorization": f"Bearer {_HUB_API_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=_HUB_BASE_URL, timeout=10.0) as client:
        response = await client.get("/api/v1/mcp/servers", headers=headers)

    response.raise_for_status()
    servers = response.json()
    items = servers if isinstance(servers, list) else servers.get("items", servers)
    slugs = [s.get("slug") for s in items]
    assert _SLUG in slugs, f"Expected slug '{_SLUG}' in hub server list, got: {slugs}"


async def test_idempotent_registration_does_not_raise():
    """Scenario 3.10: calling register_with_hub twice must not raise RuntimeError."""
    from app.registration import register_with_hub

    # First call
    await register_with_hub(
        hub_base_url=_HUB_BASE_URL,
        api_token=_HUB_API_TOKEN,
        slug=_SLUG,
        app_base_url=_APP_BASE_URL,
    )

    # Second call (should hit 409 and recover gracefully)
    await register_with_hub(
        hub_base_url=_HUB_BASE_URL,
        api_token=_HUB_API_TOKEN,
        slug=_SLUG,
        app_base_url=_APP_BASE_URL,
    )
