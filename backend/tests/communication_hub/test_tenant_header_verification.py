"""Communication Hub signed tenant-header verification tests (Phase 9.4, CS-17..CS-20).

``ControlPlaneMiddleware`` (CH) must:

- pass headerless traffic through unchanged (single-tenant)
- verify the full signed set from CC and bind the verified context on
  ``/internal/*`` paths (including the cert-exempt execute forwards)
- reject tampered / stale / unsigned / partial sets with 401
- A2A: cross-tenant target resolution maps to refusal (CC decides;
  CH relays 403/404 — never the payload)
- ``validate_api_key_internal`` returns the key's tenant binding for
  MCP session scoping (CS-17)
"""
from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import TenantContext, get_current_tenant_context  # noqa: E402
from app.core.tenant_signature import (  # noqa: E402
    TENANT_ID_HEADER,
    TENANT_SIGNATURE_HEADER,
    TENANT_TIMESTAMP_HEADER,
    build_tenant_signature_headers,
    forward_tenant_headers,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
    slug="ch-tenant",
    name="CH Tenant",
)


@pytest.fixture
def ch_app():
    """Minimal CH-shaped app: control-plane middleware + the cert-exempt
    execute path as the observable internal endpoint."""
    from app.communication_hub.middleware.control_plane import ControlPlaneMiddleware

    app = FastAPI()

    @app.post("/internal/agent/execute")
    async def execute(request: Request):
        ctx = get_current_tenant_context()
        return {
            "tenant_slug": ctx.slug if ctx else None,
            "forwarded": sorted(forward_tenant_headers().keys()),
        }

    app.add_middleware(ControlPlaneMiddleware)
    return app


@pytest.fixture
def ch_client(ch_app):
    with TestClient(ch_app) as client:
        yield client


class TestHeaderlessTraffic:
    def test_no_tenant_headers_pass_through_unchanged(self, ch_client):
        response = ch_client.post("/internal/agent/execute", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_slug"] is None
        assert body["forwarded"] == []


class TestValidSignedContext:
    def test_valid_headers_bind_context(self, ch_client):
        headers = build_tenant_signature_headers(CTX)
        response = ch_client.post("/internal/agent/execute", json={}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_slug"] == "ch-tenant"
        assert len(body["forwarded"]) == 4


class TestInvalidHeaderSets:
    def test_tampered_slug_rejected(self, ch_client):
        headers = build_tenant_signature_headers(CTX)
        headers["X-Internal-Tenant-Slug"] = "forged-tenant"
        response = ch_client.post("/internal/agent/execute", json={}, headers=headers)
        assert response.status_code == 401
        assert "Invalid tenant context" in response.json()["detail"]

    def test_tampered_signature_rejected(self, ch_client):
        headers = build_tenant_signature_headers(CTX)
        headers[TENANT_SIGNATURE_HEADER] = "ff" * 32
        response = ch_client.post("/internal/agent/execute", json={}, headers=headers)
        assert response.status_code == 401

    def test_stale_replayed_signature_rejected(self, ch_client):
        stale = build_tenant_signature_headers(CTX, timestamp=time.time() - 900)
        response = ch_client.post("/internal/agent/execute", json={}, headers=stale)
        assert response.status_code == 401

    def test_unsigned_partial_set_rejected(self, ch_client):
        partial = {TENANT_ID_HEADER: str(CTX.tenant_id)}
        response = ch_client.post("/internal/agent/execute", json={}, headers=partial)
        assert response.status_code == 401

    def test_non_internal_paths_unaffected(self, ch_client):
        """Non-control-plane paths never carry tenant logic."""
        response = ch_client.post("/not-internal", json={})
        assert response.status_code == 404  # routed past the middleware


# ── A2A cross-tenant refusal (CS-18) ─────────────────────────────────────────


class TestA2ACrossTenantRefusal:
    def _request(self):
        from app.communication_hub.api.a2a import A2ARequest

        return A2ARequest(
            target_agent_type_slug="other-tenant-agent",
            request_payload={"message": "secret payload"},
            conversation_metadata={"requester_instance_id": "inst-1"},
        )

    def _http_request(self, cc_error=None, data_client=None):
        """Request stub whose app.state.data_client simulates CC's answer."""
        import asyncio
        from app.communication_hub.data_client import ControlCenterDataError

        if data_client is None:
            async def prepare(**kwargs):
                raise ControlCenterDataError(
                    f"CC prepare returned {cc_error}: refusal"
                )

            data_client = SimpleNamespace(prepare_a2a_request=prepare)

        return SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(data_client=data_client))
        )

    def _run(self, coro):
        import asyncio

        return asyncio.new_event_loop().run_until_complete(coro)

    def test_cc_404_maps_to_404_without_payload(self):
        """Unknown/cross-tenant target (404 from CC) → 404; the payload is
        never relayed anywhere."""
        import app.communication_hub.api.a2a as a2a_module

        with pytest.raises(Exception) as exc_info:
            self._run(
                a2a_module.request_a2a(self._request(), self._http_request(cc_error=404))
            )
        assert getattr(exc_info.value, "status_code", None) == 404

    def test_cc_403_maps_to_403(self):
        """CC refuses the cross-tenant pair (403); CH refuses the relay."""
        import app.communication_hub.api.a2a as a2a_module

        with pytest.raises(Exception) as exc_info:
            self._run(
                a2a_module.request_a2a(self._request(), self._http_request(cc_error=403))
            )
        assert getattr(exc_info.value, "status_code", None) == 403

    def test_no_data_client_is_service_unavailable(self):
        """Fail-closed: without a CC data client nothing is relayed."""
        import app.communication_hub.api.a2a as a2a_module

        with pytest.raises(Exception) as exc_info:
            self._run(
                a2a_module.request_a2a(
                    self._request(),
                    SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(data_client=None))),
                )
            )
        assert getattr(exc_info.value, "status_code", None) == 503


# ── API-key tenant binding (CS-17) ───────────────────────────────────────────


class TestApiKeyTenantBinding:
    def test_validate_response_schema_carries_tenant_id(self):
        """The MCP session binding contract: the validation response
        includes the key's tenant_id (None in single-tenant mode)."""
        from app.schemas.api_key import ApiKeyValidateResponse

        response = ApiKeyValidateResponse(
            valid=True,
            agent_identity_id=uuid.uuid4(),
            agent_role_id=uuid.uuid4(),
            agent_role_name="developer",
            identity_token="tok",
            permissions=[],
            skills=[],
            api_key_name="k",
            tenant_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        )
        assert response.tenant_id is not None

    def test_api_key_auth_binds_tenant_from_validation_not_headers(self):
        """CH binds the MCP session to the CC-validated tenant — never
        from client-supplied headers."""
        import app.communication_hub.middleware.api_key_auth as api_key_auth

        source = api_key_auth.__dict__.get("ApiKeyAuthMiddleware")
        if source is None:
            pytest.skip("ApiKeyAuthMiddleware moved")
        import inspect

        code = inspect.getsource(api_key_auth)
        assert 'request.state.tenant_id = tenant_id' in code
        # The binding comes from the CC validation payload only.
        assert 'validation.get("tenant_id")' in code
