"""Unit tests for register_with_hub (app/registration.py).

All outbound httpx calls are mocked — no real Hub or network access required.
Covers: success path, 409 idempotency, 409-but-slug-missing error,
and unexpected HTTP error propagation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.registration import register_with_hub

_HUB_URL = "http://hub:8000"
_TOKEN = "test-hub-token"
_SLUG = "demo"
_APP_URL = "http://demo:7001"


def _mock_response(status_code: int, json_data=None, raise_on_status: Exception | None = None):
    """Build a MagicMock that mimics an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if raise_on_status:
        resp.raise_for_status = MagicMock(side_effect=raise_on_status)
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _patch_httpx(inner_client: AsyncMock):
    """Return a patch context that wires AsyncClient to inner_client."""
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=inner_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    patcher = patch("app.registration.httpx.AsyncClient", return_value=mock_ctx)
    return patcher


# ── Success path ──────────────────────────────────────────────────────────────


async def test_register_success_creates_server_and_syncs():
    """Scenario 3.10: first registration → POST /servers 201, POST /sync 200."""
    create_resp = _mock_response(201, {"id": "server-uuid-1"})
    sync_resp = _mock_response(200)

    inner = AsyncMock()
    inner.post = AsyncMock(side_effect=[create_resp, sync_resp])

    with _patch_httpx(inner):
        await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)

    assert inner.post.call_count == 2
    first_call_url = inner.post.call_args_list[0][0][0]
    assert "/api/v1/mcp/servers" in first_call_url
    second_call_url = inner.post.call_args_list[1][0][0]
    assert "server-uuid-1" in second_call_url and "sync" in second_call_url


async def test_register_success_sync_is_called_with_correct_headers():
    """POST /sync must include the Bearer token header."""
    create_resp = _mock_response(201, {"id": "srv-99"})
    sync_resp = _mock_response(200)

    inner = AsyncMock()
    inner.post = AsyncMock(side_effect=[create_resp, sync_resp])

    with _patch_httpx(inner):
        await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)

    sync_kwargs = inner.post.call_args_list[1][1]
    assert sync_kwargs["headers"]["Authorization"] == f"Bearer {_TOKEN}"


# ── 409 idempotency ───────────────────────────────────────────────────────────


async def test_register_409_looks_up_existing_record():
    """Scenario 3.10: 409 on create → GET /servers to find existing id."""
    create_resp = _mock_response(409)
    list_resp = _mock_response(200, [{"id": "existing-id", "slug": _SLUG}])
    sync_resp = _mock_response(200)

    inner = AsyncMock()
    inner.post = AsyncMock(side_effect=[create_resp, sync_resp])
    inner.get = AsyncMock(return_value=list_resp)

    with _patch_httpx(inner):
        await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)

    inner.get.assert_called_once()
    second_post_url = inner.post.call_args_list[1][0][0]
    assert "existing-id" in second_post_url


async def test_register_409_handles_paginated_list_response():
    """409 idempotency: Hub may return {'items': [...]} pagination format."""
    create_resp = _mock_response(409)
    list_resp = _mock_response(200, {"items": [{"id": "paged-id", "slug": _SLUG}]})
    sync_resp = _mock_response(200)

    inner = AsyncMock()
    inner.post = AsyncMock(side_effect=[create_resp, sync_resp])
    inner.get = AsyncMock(return_value=list_resp)

    with _patch_httpx(inner):
        await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)

    sync_url = inner.post.call_args_list[1][0][0]
    assert "paged-id" in sync_url


async def test_register_409_slug_not_in_list_raises_runtime_error():
    """Edge case: 409 returned but slug is missing from server list → RuntimeError."""
    create_resp = _mock_response(409)
    # List contains a different slug
    list_resp = _mock_response(200, [{"id": "other-id", "slug": "other-app"}])

    inner = AsyncMock()
    inner.post = AsyncMock(return_value=create_resp)
    inner.get = AsyncMock(return_value=list_resp)

    with _patch_httpx(inner):
        with pytest.raises(RuntimeError, match="not found in server list"):
            await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)


# ── Unexpected errors ─────────────────────────────────────────────────────────


async def test_register_500_raises():
    """Scenario 3.10: unexpected status (500) → exception propagated to caller."""
    import httpx

    error = httpx.HTTPStatusError(
        "Internal Server Error",
        request=MagicMock(),
        response=MagicMock(status_code=500),
    )
    create_resp = _mock_response(500, raise_on_status=error)

    inner = AsyncMock()
    inner.post = AsyncMock(return_value=create_resp)

    with _patch_httpx(inner):
        with pytest.raises(Exception):
            await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)


async def test_register_sync_failure_raises():
    """Sync endpoint failure → exception propagated."""
    import httpx

    sync_error = httpx.HTTPStatusError(
        "Sync failed",
        request=MagicMock(),
        response=MagicMock(status_code=500),
    )
    create_resp = _mock_response(201, {"id": "server-id"})
    sync_resp = _mock_response(500, raise_on_status=sync_error)

    inner = AsyncMock()
    inner.post = AsyncMock(side_effect=[create_resp, sync_resp])

    with _patch_httpx(inner):
        with pytest.raises(Exception):
            await register_with_hub(_HUB_URL, _TOKEN, _SLUG, _APP_URL)
