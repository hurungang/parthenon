"""Unit tests for the Communication Hub Agent Gateway token preflight gate.

Covers: block path, warn path, proceed path, unreachable endpoint
(fail closed), and message content — no token material ever propagates.
"""
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.gateway.preflight_gate import (
    PREFLIGHT_ENDPOINT,
    AgentPreflightBlocked,
    AgentPreflightUnavailable,
    enforce_execution_preflight,
    run_execution_preflight,
)

AGENT_TYPE_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


_POSTED: dict = {}


def _mock_client(response_json: dict):
    """Patch internal_httpx_client with a client whose post returns response_json."""
    response = type(
        "Response",
        (),
        {
            "raise_for_status": lambda self: None,
            "json": lambda self: response_json,
            "status_code": 200,
            "text": "",
        },
    )()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, endpoint, json=None):
            _POSTED["endpoint"] = endpoint
            _POSTED["payload"] = json
            return response

    return patch(
        "app.services.gateway.preflight_gate.internal_httpx_client",
        return_value=FakeClient(),
    )


class TestProceed:
    async def test_proceed_returns_no_warnings(self):
        with _mock_client({"verdict": "proceed", "warnings": [], "blocked": []}):
            warnings = await enforce_execution_preflight(AGENT_TYPE_ID, SESSION_ID)
        assert warnings == []

    async def test_calls_cc_preflight_endpoint_with_ids_only(self):
        with _mock_client({"verdict": "proceed", "warnings": [], "blocked": []}):
            await run_execution_preflight(AGENT_TYPE_ID, SESSION_ID)
        assert _POSTED["endpoint"].endswith(PREFLIGHT_ENDPOINT)
        # No token material in the payload — only identifiers.
        assert _POSTED["payload"] == {
            "agent_type_id": str(AGENT_TYPE_ID),
            "session_id": str(SESSION_ID),
        }


class TestWarn:
    async def test_warn_proceeds_with_notices(self):
        result = {
            "verdict": "proceed_with_warnings",
            "warnings": ["agent_identity 'researcher' token expires within 7 days — refresh soon"],
            "blocked": [],
        }
        with _mock_client(result):
            warnings = await enforce_execution_preflight(AGENT_TYPE_ID, SESSION_ID)
        assert len(warnings) == 1
        assert "researcher" in warnings[0]
        assert "7 days" in warnings[0]


class TestBlock:
    async def test_blocked_raises_with_actionable_message(self):
        result = {
            "verdict": "blocked",
            "warnings": [],
            "blocked": [
                "agent_identity 'researcher' token has expired — refresh it "
                "(identity) or re-authenticate (MCP session) before executing this agent"
            ],
        }
        with _mock_client(result):
            with pytest.raises(AgentPreflightBlocked) as exc_info:
                await enforce_execution_preflight(AGENT_TYPE_ID, SESSION_ID)
        # The message names the identity/session to refresh.
        assert "researcher" in str(exc_info.value)
        assert "expired" in str(exc_info.value)
        assert exc_info.value.blocked == result["blocked"]

    async def test_blocked_without_details_still_names_problem(self):
        with _mock_client({"verdict": "blocked", "warnings": [], "blocked": []}):
            with pytest.raises(AgentPreflightBlocked) as exc_info:
                await enforce_execution_preflight(AGENT_TYPE_ID, None)
        assert "blocked" in str(exc_info.value).lower()


class TestUnreachableFailClosed:
    async def _assert_fails_closed(self, exc):
        def _raise(*args, **kwargs):
            class FailingClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                async def post(self, *a, **kw):
                    raise exc

            return FailingClient()

        with patch(
            "app.services.gateway.preflight_gate.internal_httpx_client",
            side_effect=_raise,
        ):
            with pytest.raises(AgentPreflightUnavailable):
                await enforce_execution_preflight(AGENT_TYPE_ID, SESSION_ID)

    async def test_connect_error_fails_closed(self):
        await self._assert_fails_closed(httpx.ConnectError("connection refused"))

    async def test_timeout_fails_closed(self):
        await self._assert_fails_closed(httpx.TimeoutException("timed out"))

    async def test_http_error_fails_closed(self):
        request = httpx.Request("POST", "http://cc")
        response = httpx.Response(500, request=request)
        await self._assert_fails_closed(httpx.HTTPStatusError("boom", request=request, response=response))
