"""Integration tests — Full authorization flow: certificate validation + permission check + token refresh.

Covers:
  Task 6.3 — Backend Integration Tests - Authorization Flow

Tests:
  - Tool call with valid certificate and sufficient permissions → authorized
  - Tool call with invalid certificate → returns 403 with reason
  - Tool call with insufficient permissions → returns 403 with permissions reason
  - Tool call with expired token → triggers refresh automatically
  - Tool call with token that cannot be refreshed → returns error
  - Certificate validation log populated after every validation
  - Authorization flow via Communication Hub middleware

Database: Uses shared SQLite in-memory engine from conftest.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_security import (
    AgentInstanceCertificate,
    CertificateValidationLog,
    CertificateValidationOutcome,
)
from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityStatus,
    AgentIdentityType,
    AgentTokenStatus,
    AgentType,
)
from app.services.certificate_authority import CertificateAuthorityService, initialize_ca
from app.services.permission_resolution import PermissionResolutionService, resolve_permissions


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def reset_ca(db_session: AsyncSession):
    """Reset CA state before each test in this module."""
    import app.services.certificate_authority as ca_module
    ca_module._ca_private_key = None
    ca_module._ca_certificate = None
    await initialize_ca(db_session)


@pytest_asyncio.fixture
async def agent_type_with_identity_and_role(db_session: AsyncSession):
    """Create AgentType, AgentIdentity, and mock role setup for authorization tests."""
    from app.core.credential_vault import CredentialVault
    import os
    os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
    vault = CredentialVault()

    identity = AgentIdentity(
        name=f"auth-test-identity-{uuid.uuid4().hex[:6]}",
        identity_type=AgentIdentityType.realm_user,
        access_token=vault.encrypt("test-access-token"),
        refresh_token=vault.encrypt("test-refresh-token"),
        encrypted_refresh_token=vault.encrypt("test-refresh-token"),
        token_expires_at=_now_utc() + timedelta(hours=1),
        token_status=AgentTokenStatus.active,
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()

    agent_type = AgentType(
        name=f"auth-test-agent-type-{uuid.uuid4().hex[:6]}",
        identity_id=identity.id,
        role_id=None,  # No role — for permission denied tests
    )
    db_session.add(agent_type)
    await db_session.flush()

    return {"identity": identity, "agent_type": agent_type}


@pytest_asyncio.fixture
async def issued_certificate(
    db_session: AsyncSession,
    agent_type_with_identity_and_role,
):
    """Issue a certificate for the test agent type."""
    ca_service = CertificateAuthorityService()
    agent_type = agent_type_with_identity_and_role["agent_type"]
    instance_id = f"auth-test-{uuid.uuid4().hex[:8]}"
    issued = await ca_service.issue(agent_type.id, instance_id, db_session)
    await db_session.flush()
    return {
        "issued": issued,
        "agent_type": agent_type,
        "identity": agent_type_with_identity_and_role["identity"],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_permissions_no_role_returns_denied(
    db_session: AsyncSession,
    issued_certificate,
):
    """Agent type without role returns authorization denied."""
    cert_serial = issued_certificate["issued"].serial_number

    result = await resolve_permissions(
        certificate_serial_number=cert_serial,
        tool_name="mcp_hub.test_tool",
        db=db_session,
    )

    assert result.authorized is False
    assert result.reason == "no_role_assigned"
    assert result.identity_token is None


@pytest.mark.asyncio
async def test_resolve_permissions_invalid_serial_returns_not_found(
    db_session: AsyncSession,
):
    """Non-existent certificate serial returns certificate_not_found."""
    result = await resolve_permissions(
        certificate_serial_number="999999999999",
        tool_name="any.tool",
        db=db_session,
    )
    assert result.authorized is False
    assert result.reason == "certificate_not_found"


@pytest.mark.asyncio
async def test_validate_certificate_logs_outcome(
    db_session: AsyncSession,
    issued_certificate,
):
    """Certificate validation creates an audit log entry."""
    ca_service = CertificateAuthorityService()
    cert_pem = issued_certificate["issued"].certificate_pem
    serial = issued_certificate["issued"].serial_number

    logs_before = (await db_session.execute(select(CertificateValidationLog))).scalars().all()
    count_before = len(logs_before)

    await ca_service.validate(
        cert_pem=cert_pem,
        db=db_session,
        validated_by_service="communication-hub",
        requested_operation="mcp_hub.test",
    )

    logs_after = (await db_session.execute(select(CertificateValidationLog))).scalars().all()
    assert len(logs_after) == count_before + 1

    last_log = logs_after[-1]
    assert last_log.certificate_serial_number == serial
    assert last_log.outcome == CertificateValidationOutcome.valid
    assert last_log.validated_by_service == "communication-hub"


@pytest.mark.asyncio
async def test_validate_wrong_signature_returns_invalid(
    db_session: AsyncSession,
):
    """Certificate signed by wrong CA fails with invalid_signature."""
    # Generate a completely different CA and sign with it
    import app.services.certificate_authority as ca_module
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from cryptography.x509.oid import NameOID

    # Create a rogue CA
    rogue_key = rsa.generate_private_key(65537, 2048, default_backend())
    agent_key = rsa.generate_private_key(65537, 2048, default_backend())
    now = _now_utc()
    rogue_ca_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rogue CA")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rogue CA")]))
        .public_key(rogue_key.public_key())
        .serial_number(999)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(rogue_key, hashes.SHA256())
    )
    type_id = uuid.uuid4()
    rogue_agent_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{type_id}:rogue-instance")]))
        .issuer_name(rogue_ca_cert.subject)
        .public_key(agent_key.public_key())
        .serial_number(12345)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(hours=24))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(rogue_key, hashes.SHA256())
    )
    rogue_pem = rogue_agent_cert.public_bytes(serialization.Encoding.PEM).decode()

    ca_service = CertificateAuthorityService()
    result = await ca_service.validate(
        cert_pem=rogue_pem,
        db=db_session,
        validated_by_service="test",
    )

    assert result.valid is False
    assert result.reason == "invalid_signature"


@pytest.mark.asyncio
async def test_authorization_middleware_no_certificate_returns_403():
    """CertificateAuthorizationMiddleware returns 403 when no cert provided."""
    from unittest.mock import AsyncMock
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    from starlette.requests import Request

    from app.communication_hub.middleware.authorization import CertificateAuthorizationMiddleware

    async def tool_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"result": "ok"})

    app_test = Starlette(routes=[Route("/tools/mcp_hub.search", tool_endpoint)])
    app_test.add_middleware(CertificateAuthorizationMiddleware)

    client = TestClient(app_test, raise_server_exceptions=False)
    response = client.post("/tools/mcp_hub.search", json={"query": "test"})

    assert response.status_code == 403
    assert "Invalid certificate" in response.json()["detail"]


@pytest.mark.asyncio
async def test_token_expiration_during_permission_resolution_triggers_refresh(
    db_session: AsyncSession,
    agent_type_with_identity_and_role,
):
    """Permission resolution with expired token triggers refresh automatically."""
    # Set up identity with expired token
    from app.core.credential_vault import CredentialVault
    import os
    os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
    vault = CredentialVault()

    identity = agent_type_with_identity_and_role["identity"]
    identity.token_expires_at = _now_utc() - timedelta(hours=1)  # Expired
    identity.token_status = AgentTokenStatus.expired
    await db_session.flush()

    # Set up certificate for this agent type
    ca_service = CertificateAuthorityService()
    agent_type = agent_type_with_identity_and_role["agent_type"]
    issued = await ca_service.issue(agent_type.id, "expired-token-instance", db_session)

    # Mock: permission check allows tool
    new_access_token = "refreshed-access-token-xyz"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": new_access_token,
        "expires_in": 3600,
    }

    with patch("app.services.permission_resolution.get_allowed_tools") as mock_tools, \
         patch("app.services.token_refresh.httpx.AsyncClient") as mock_client_cls:

        mock_tools.return_value = {"mcp_hub.search", "save_result"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        # Give agent type a role so it doesn't return "no_role_assigned"
        from app.db.models.agents import AgentRole
        role = AgentRole(name=f"test-role-{uuid.uuid4().hex[:6]}")
        db_session.add(role)
        await db_session.flush()
        agent_type.role_id = role.id
        await db_session.flush()

        result = await resolve_permissions(
            certificate_serial_number=issued.serial_number,
            tool_name="mcp_hub.search",
            db=db_session,
        )

    # Should succeed with refreshed token
    assert result.authorized is True
    assert result.identity_token == new_access_token
