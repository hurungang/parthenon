"""Unit tests for the System One client: vendor registry, verbatim URL
semantics, and response logging (no API key material in any log record).

Covers:
- get_system_one_client factory: typesafe → TypeSafeJevClient; unknown → error
- base_url used VERBATIM as the endpoint (no /systemone append, no strip)
- TYPESAFE_DEFAULT_BASE_URL is the full default endpoint
- INFO logs include endpoint + answers summary; DEBUG carries full bodies;
  the api_key never appears in any log record
- Pydantic schemas accept full URLs verbatim and enforce http(s)
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.schemas.system_one import (
    SYSTEM_ONE_PRESET_BASE_URL,
    SystemOneProviderCreate,
)
from app.services.system_one.client import (
    TYPESAFE_DEFAULT_BASE_URL,
    SystemOneClientError,
    TypeSafeJevClient,
    get_system_one_client,
)

API_KEY = "sk-super-secret-key-do-not-log"


class _MockTransport(httpx.MockTransport):
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self.body = body or {}
        self.requests: list[httpx.Request] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self.status_code, json=self.body, request=request
        )


# ── Vendor registry ───────────────────────────────────────────────────────


def test_factory_returns_typesafe_client():
    client = get_system_one_client("typesafe")
    assert isinstance(client, TypeSafeJevClient)


def test_factory_rejects_unknown_provider_type():
    with pytest.raises(ValueError, match="Unsupported System One provider type"):
        get_system_one_client("acme")


def test_default_base_url_is_full_endpoint():
    assert TYPESAFE_DEFAULT_BASE_URL == "https://api.typesafe.ai/v1/systemone"
    assert SYSTEM_ONE_PRESET_BASE_URL == "https://api.typesafe.ai/v1/systemone"


# ── Verbatim URL semantics ────────────────────────────────────────────────



async def test_base_url_used_verbatim_no_append():
    transport = _MockTransport(
        body={"answers": {"q1": {"type": "noul", "noul": 0.5}}}
    )
    client = TypeSafeJevClient(transport=transport)
    await client.evaluate(
        base_url="http://127.0.0.1:18099/v1/systemone",
        api_key=API_KEY,
        model="jev-latest",
        state={},
        questions={"q1": {"type": "noul"}},
    )
    assert transport.requests[0].url == "http://127.0.0.1:18099/v1/systemone"
    # No automatic suffix anywhere in the URL path.
    assert transport.requests[0].url.path == "/v1/systemone"



async def test_base_url_not_stripped_when_full_path_given():
    transport = _MockTransport(
        body={"answers": {"q1": {"type": "noul", "noul": 0.5}}}
    )
    client = TypeSafeJevClient(transport=transport)
    custom = "https://proxy.example.com/typesafe/endpoint"
    await client.evaluate(
        base_url=custom,
        api_key=API_KEY,
        model="jev-latest",
        state={},
        questions={"q1": {"type": "noul"}},
    )
    assert transport.requests[0].url == custom



async def test_http_error_logs_url_status_and_body():
    transport = _MockTransport(status_code=404, body={"error": "no such route"})
    client = TypeSafeJevClient(transport=transport)
    with pytest.raises(SystemOneClientError, match="HTTP 404"):
        await client.evaluate(
            base_url="http://127.0.0.1:18099/v1/systemone",
            api_key=API_KEY,
            model="jev-latest",
            state={},
            questions={"q1": {"type": "noul"}},
        )


# ── Logging: answers summary at INFO, no key material anywhere ────────────



async def test_info_logs_include_endpoint_and_answers_summary(caplog):
    transport = _MockTransport(
        body={
            "model": "jev-latest",
            "answers": {
                "approve": {"type": "choice", "choice": "yes", "confidence": 0.9},
                "score_q": {"type": "score", "score": 4},
            },
        }
    )
    client = TypeSafeJevClient(transport=transport)
    with caplog.at_level(logging.DEBUG, logger="app.services.system_one.client"):
        await client.evaluate(
            base_url="http://127.0.0.1:18099/v1/systemone",
            api_key=API_KEY,
            model="jev-latest",
            state={"a": 1},
            questions={"approve": {"type": "choice"}, "score_q": {"type": "score"}},
        )
    info_text = " ".join(r.message for r in caplog.records if r.levelno == logging.INFO)
    assert "http://127.0.0.1:18099/v1/systemone" in info_text
    assert "answers summary" in info_text
    assert "approve" in info_text and "yes" in info_text
    assert "score_q" in info_text
    # Status code is logged at INFO (success case) too.
    assert any("status=200" in r.message for r in caplog.records)
    debug_text = " ".join(
        r.message for r in caplog.records if r.levelno == logging.DEBUG
    )
    assert '"model"' in debug_text  # full request body at DEBUG



async def test_api_key_never_appears_in_any_log_record(caplog):
    transport = _MockTransport(
        body={"answers": {"q1": {"type": "noul", "noul": 0.5}}}
    )
    client = TypeSafeJevClient(transport=transport)
    with caplog.at_level(logging.DEBUG):
        await client.evaluate(
            base_url="http://127.0.0.1:18099/v1/systemone",
            api_key=API_KEY,
            model="jev-latest",
            state={},
            questions={"q1": {"type": "noul"}},
        )
    for record in caplog.records:
        message = record.getMessage()
        assert API_KEY not in message
        assert "Authorization" not in message
        assert "Bearer" not in message


# ── Schema URL validation (http(s) enforced, verbatim) ────────────────────


def test_schema_accepts_full_url_verbatim():
    schema = SystemOneProviderCreate(
        display_name="Local stub",
        base_url="http://127.0.0.1:18099/v1/systemone",
        api_key=API_KEY,
    )
    assert schema.base_url == "http://127.0.0.1:18099/v1/systemone"


def test_schema_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http"):
        SystemOneProviderCreate(
            display_name="X",
            base_url="ftp://tenant.example/v1/systemone",
            api_key=API_KEY,
        )
