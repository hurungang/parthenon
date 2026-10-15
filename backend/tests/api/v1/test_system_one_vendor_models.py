"""Failing tests for FIX-20261014-001900 — vendor model sync against TypeSafe.

Reproduces two defects in ``list_vendor_models``:

1. URL derivation: a configured provider ``base_url`` is the FULL endpoint
   (e.g. ``https://api.typesafe.ai/v1/systemone``). Appending ``/models``
   yields ``/v1/systemone/models`` → 404. The listing URL must resolve to
   ``/v1/models`` (https://docs.typesafe.ai/models).
2. Response parsing: TypeSafe returns ``{"models": [{"name", ...}]}`` —
   NOT the OpenAI shape ``{"data": [{"id"}]}``. The parser must accept the
   TypeSafe shape and return the model names.

These tests are EXPECTED TO FAIL against the current implementation.
"""
from __future__ import annotations

import os

import httpx
import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.system_one.client import list_vendor_models


@pytest.mark.asyncio
async def test_vendor_models_url_derives_v1_models_from_systemone_endpoint():
    """A base_url of .../v1/systemone must list models at .../v1/models."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(
            200, json={"models": [{"name": "jev-latest", "description": "", "release_date": ""}]}
        )

    transport = httpx.MockTransport(handler)
    await list_vendor_models(
        base_url="https://api.typesafe.ai/v1/systemone",
        api_key="sk-test",
        transport=transport,
    )

    assert captured_urls, "no HTTP request was made"
    assert captured_urls[0].rstrip("/").endswith(
        "/v1/models"
    ), f"expected the listing URL to end with /v1/models, got {captured_urls[0]}"


@pytest.mark.asyncio
async def test_vendor_models_parses_typesafe_models_shape():
    """The TypeSafe ``{"models": [{"name": ...}]}`` shape returns model names."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "jev-latest", "description": "flagship", "release_date": "2026-01-01"},
                    {"name": "jev-mini", "description": "fast", "release_date": "2026-02-01"},
                ]
            },
        )

    models = await list_vendor_models(
        base_url="https://api.typesafe.ai/v1/systemone",
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
    )

    assert models == ["jev-latest", "jev-mini"]


@pytest.mark.asyncio
async def test_vendor_models_url_derives_v1_models_from_bare_host():
    """A bare-host base_url (no /v1 path) also resolves to /v1/models."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "jev-latest"}]})

    await list_vendor_models(
        base_url="https://api.typesafe.ai",
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
    )

    assert captured_urls[0].rstrip("/").endswith(
        "/v1/models"
    ), f"expected the listing URL to end with /v1/models, got {captured_urls[0]}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.typesafe.ai/v1/systemone",  # full endpoint → strip segment
        "https://api.typesafe.ai/v1",  # API root → append /models
        "https://api.typesafe.ai/v1/models/",  # already a models URL → keep
        "https://api.typesafe.ai/v1/models",  # already a models URL → keep
        "https://api.typesafe.ai",  # bare host → append /v1/models
        "https://api.typesafe.ai/",  # bare host with trailing slash
    ],
)
async def test_vendor_models_url_always_resolves_to_v1_models(base_url: str):
    """Every supported base_url shape resolves the listing to /v1/models."""
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "jev-latest"}]})

    await list_vendor_models(
        base_url=base_url,
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
    )

    assert captured_urls[0].rstrip("/").endswith(
        "/v1/models"
    ), f"base_url {base_url} → expected /v1/models, got {captured_urls[0]}"


@pytest.mark.asyncio
async def test_vendor_models_keeps_openai_data_shape_fallback():
    """Non-TypeSafe vendors using the OpenAI ``{"data": [{"id"}]}`` shape
    keep working (fallback parsing)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"id": "gpt-x"}, {"id": "gpt-y"}]}
        )

    models = await list_vendor_models(
        base_url="https://api.other-vendor.ai/v1",
        api_key="sk-test",
        transport=httpx.MockTransport(handler),
    )

    assert models == ["gpt-x", "gpt-y"]
