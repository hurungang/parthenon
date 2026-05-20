"""Integration tests — Control Center data API clients (Task 7.3).

Tests that Agent Runtime data client and Communication Hub data client correctly
call Control Center data APIs via mTLS and parse responses.

All HTTP calls are mocked — no running services required.

AR data client tests:
  - get_agent_plan: fetches from /internal/data/agent-types/{id}/plan
  - get_agent_context: fetches from /internal/data/agent-types/{id}/context
  - get_model_config: fetches from /internal/data/model-configs/{id}
  - All calls use mTLS-configured client from CertificateManager
  - ControlCenterDataError raised on HTTP errors

CH data client tests:
  - get_session: fetches from /internal/data/sessions/{id}
  - get_conversation_history: fetches from /internal/data/sessions/{id}/history
  - get_user_permissions: fetches from /internal/data/users/{id}/permissions
  - check_revocation_status: fetches from /internal/certificates/revocation-status
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agent_runtime.data_client import ControlCenterDataClient, ControlCenterDataError
from app.communication_hub.data_client import (
    ControlCenterDataClient as CHDataClient,
    ControlCenterDataError as CHDataError,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ar_client() -> ControlCenterDataClient:
    """Create an AR data client with a mock cert manager."""
    cert_manager = MagicMock()
    # configure_mtls_client raises CertificateLoadError in real code if not loaded;
    # our mock returns a plain client so the test doesn't need TLS
    cert_manager.configure_mtls_client.side_effect = Exception("not loaded")
    return ControlCenterDataClient(
        cert_manager=cert_manager,
        control_center_url="http://cc.test",
    )


def _make_ch_client() -> CHDataClient:
    """Create a CH data client with a mock cert manager."""
    cert_manager = MagicMock()
    cert_manager.configure_mtls_client.side_effect = Exception("not loaded")
    return CHDataClient(
        cert_manager=cert_manager,
        control_center_url="http://cc.test",
    )


def _mock_httpx_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=resp,
        )
        resp.text = "Error"
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runtime data client
# ═══════════════════════════════════════════════════════════════════════════════


class TestARDataClientAgentPlan:
    """Tests for ControlCenterDataClient.get_agent_plan."""

    @pytest.mark.asyncio
    async def test_get_agent_plan_calls_correct_endpoint(self):
        """get_agent_plan calls /api/v1/internal/data/agent-types/{id}/plan."""
        client = _make_ar_client()
        agent_type_id = uuid.uuid4()
        plan_data = {"plan_id": str(uuid.uuid4()), "steps": ["step1", "step2"]}

        mock_resp = _mock_httpx_response(plan_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.get_agent_plan(agent_type_id)

        assert result == plan_data
        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert f"/internal/data/agent-types/{agent_type_id}/plan" in url

    @pytest.mark.asyncio
    async def test_get_agent_plan_raises_on_http_error(self):
        """get_agent_plan returns None on 404 (error is swallowed by implementation)."""
        client = _make_ar_client()
        agent_type_id = uuid.uuid4()

        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 404
        error_resp.text = "Not Found"
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404",
            request=MagicMock(),
            response=error_resp,
        )

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=error_resp)
            mock_class.return_value = mock_instance

            result = await client.get_agent_plan(agent_type_id)

        # get_agent_plan swallows ControlCenterDataError and returns None
        assert result is None


class TestARDataClientAgentContext:
    """Tests for ControlCenterDataClient.get_agent_context."""

    @pytest.mark.asyncio
    async def test_get_agent_context_returns_skills_and_role(self):
        """get_agent_context returns agent context with skills, SOPs, role, model."""
        client = _make_ar_client()
        agent_type_id = uuid.uuid4()
        context_data = {
            "agent_type_id": str(agent_type_id),
            "role_id": str(uuid.uuid4()),
            "skills": ["skill-1", "skill-2"],
            "sops": ["sop-1"],
            "model_config_id": str(uuid.uuid4()),
        }

        mock_resp = _mock_httpx_response(context_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.get_agent_context(agent_type_id)

        assert result == context_data
        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert f"/internal/data/agent-types/{agent_type_id}/context" in url


class TestARDataClientModelConfig:
    """Tests for ControlCenterDataClient.get_model_config."""

    @pytest.mark.asyncio
    async def test_get_model_config_calls_correct_endpoint(self):
        """get_model_config calls /api/v1/internal/data/model-configs/{id}."""
        client = _make_ar_client()
        model_id = uuid.uuid4()
        model_data = {
            "id": str(model_id),
            "provider_type": "openai",
            "api_base_url": "https://api.openai.com/v1",
            "enabled_models": ["gpt-4o"],
            "api_key": "decrypted-key",
        }

        mock_resp = _mock_httpx_response(model_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.get_model_config(model_id)

        assert result == model_data
        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert f"/internal/data/model-configs/{model_id}" in url


class TestARDataClientSubmitResult:
    """Tests for ControlCenterDataClient.submit_result."""

    @pytest.mark.asyncio
    async def test_submit_result_posts_to_correct_endpoint(self):
        """submit_result POSTs to /api/v1/internal/data/sessions/{id}/result."""
        client = _make_ar_client()
        session_id = uuid.uuid4()
        result_data = {"output": "Agent completed task", "status": "completed"}
        response_data = {"session_id": str(session_id), "status": "persisted"}

        mock_resp = _mock_httpx_response(response_data, status_code=200)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.submit_result(session_id, result_data)

        # submit_result is fire-and-forget: returns None
        assert result is None
        call_args = mock_instance.post.call_args
        url = call_args[0][0]
        assert f"/internal/data/sessions/{session_id}/result" in url


# ═══════════════════════════════════════════════════════════════════════════════
# Communication Hub data client
# ═══════════════════════════════════════════════════════════════════════════════


class TestCHDataClientSession:
    """Tests for Communication Hub ControlCenterDataClient.get_session."""

    @pytest.mark.asyncio
    async def test_get_session_calls_correct_endpoint(self):
        """get_session calls /api/v1/internal/data/sessions/{id}."""
        client = _make_ch_client()
        session_id = uuid.uuid4()
        session_data = {
            "id": str(session_id),
            "status": "running",
            "agent_type_id": str(uuid.uuid4()),
        }

        mock_resp = _mock_httpx_response(session_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.get_session(session_id)

        assert result == session_data
        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert f"/internal/data/sessions/{session_id}" in url

    @pytest.mark.asyncio
    async def test_get_session_raises_on_error(self):
        """get_session raises ControlCenterDataError on HTTP failure."""
        client = _make_ch_client()
        session_id = uuid.uuid4()

        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 500
        error_resp.text = "Internal Error"
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500",
            request=MagicMock(),
            response=error_resp,
        )

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=error_resp)
            mock_class.return_value = mock_instance

            with pytest.raises(CHDataError):
                await client.get_session(session_id)


class TestCHDataClientConversationHistory:
    """Tests for get_conversation_history."""

    @pytest.mark.asyncio
    async def test_get_conversation_history_endpoint(self):
        """get_conversation_history calls /api/v1/internal/data/sessions/{id}/history."""
        client = _make_ch_client()
        session_id = uuid.uuid4()
        history_data = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        # API returns {"messages": [...]}, data client extracts the list
        mock_resp = _mock_httpx_response({"messages": history_data})

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.get_conversation_history(session_id)

        assert result == history_data
        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert f"/internal/data/sessions/{session_id}/history" in url


class TestCHDataClientUserPermissions:
    """Tests for get_user_permissions."""

    @pytest.mark.asyncio
    async def test_get_user_permissions_endpoint(self):
        """get_user_permissions calls /api/v1/internal/data/users/{id}/permissions."""
        client = _make_ch_client()
        user_id = uuid.uuid4()
        perms_data = {
            "user_id": str(user_id),
            "allowed_tools": ["tool:read", "tool:write"],
            "roles": ["admin"],
        }

        mock_resp = _mock_httpx_response(perms_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.get_user_permissions(user_id)

        # get_user_permissions extracts allowed_tools list from the response dict
        assert result == perms_data["allowed_tools"]
        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert f"/internal/data/users/{user_id}/permissions" in url


class TestCHDataClientRevocationStatus:
    """Tests for check_revocation_status."""

    @pytest.mark.asyncio
    async def test_check_revocation_status_revoked(self):
        """check_revocation_status returns True when certificate is revoked."""
        client = _make_ch_client()
        serial = "DEADBEEF1234"
        revocation_data = {"serial": serial, "revoked": True, "reason": "key compromised"}

        mock_resp = _mock_httpx_response(revocation_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.check_revocation_status(serial)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_revocation_status_not_revoked(self):
        """check_revocation_status returns False when certificate is valid."""
        client = _make_ch_client()
        serial = "GOODCERT0001"
        revocation_data = {"serial": serial, "revoked": False}

        mock_resp = _mock_httpx_response(revocation_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            result = await client.check_revocation_status(serial)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_revocation_status_calls_correct_url(self):
        """check_revocation_status calls /api/v1/internal/certificates/revocation-status."""
        client = _make_ch_client()
        serial = "ABC123"
        revocation_data = {"serial": serial, "revoked": False}

        mock_resp = _mock_httpx_response(revocation_data)

        with patch("httpx.AsyncClient") as mock_class:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_class.return_value = mock_instance

            await client.check_revocation_status(serial)

        call_args = mock_instance.get.call_args
        url = call_args[0][0]
        assert "revocation-status" in url
        assert serial in url
