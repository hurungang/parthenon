"""Permission Resolution Service — maps agent certificates to permissions and identity tokens.

This service is called by the Communication Hub Authorization Middleware on every tool call.
It:
1. Validates the certificate against the CA
2. Looks up the agent type from the certificate serial number
3. Resolves the agent type's role to a complete set of allowed tools
4. Checks the requested tool is in the allowed set
5. Checks/refreshes the agent identity token
6. Returns the authorization decision with identity token (if authorized)

All identity tokens returned here are used ONLY by the Communication Hub to execute tool
calls — they are never transmitted to the Agent Runtime.
"""
from __future__ import annotations

import logging
import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.agent_security import AgentInstanceCertificate
from app.db.models.agents import AgentIdentity, AgentType
from app.services.agents.permission_manager import get_shared_permission_manager
from app.services.certificate_authority import (
    CertificateValidationResult,
    validate_certificate,
)
from app.services.token_refresh import TokenRefreshError, refresh_oauth_token, check_token_expiration

logger = logging.getLogger(__name__)

_permission_manager = get_shared_permission_manager()


# ── Result types ──────────────────────────────────────────────────────────────


class AuthorizationResult(NamedTuple):
    """Result of a full permission resolution for a tool call."""

    authorized: bool
    identity_token: str | None        # Decrypted access token (only when authorized=True)
    identity_id: uuid.UUID | None
    agent_type_id: uuid.UUID | None
    reason: str | None                # Human-readable denial reason when authorized=False
    required_permission: str | None   # Tool name when denied due to permissions
    agent_type_name: str | None


# ── Core functions ────────────────────────────────────────────────────────────


async def resolve_permissions(
    certificate_serial_number: str,
    tool_name: str,
    db: AsyncSession,
) -> AuthorizationResult:
    """Main entry point for certificate-based permission resolution.

    Called by Communication Hub on every tool call.

    Args:
        certificate_serial_number: Serial number of the agent's certificate.
        tool_name: Fully-qualified tool identifier being requested.
        db: Active async database session.

    Returns:
        AuthorizationResult with authorization decision and, if authorized,
        the identity token to use for the tool call.
    """
    # 1. Lookup certificate record
    cert_record = await _get_certificate_by_serial(certificate_serial_number, db)
    if cert_record is None:
        return AuthorizationResult(
            authorized=False,
            identity_token=None,
            identity_id=None,
            agent_type_id=None,
            reason="certificate_not_found",
            required_permission=None,
            agent_type_name=None,
        )

    agent_type_id = cert_record.agent_type_id

    # 2. Lookup agent type
    agent_type = await _get_agent_type(agent_type_id, db)
    if agent_type is None:
        return AuthorizationResult(
            authorized=False,
            identity_token=None,
            identity_id=None,
            agent_type_id=agent_type_id,
            reason="agent_type_not_found",
            required_permission=None,
            agent_type_name=None,
        )

    # 3. Check role and permissions
    if agent_type.role_id is None:
        return AuthorizationResult(
            authorized=False,
            identity_token=None,
            identity_id=None,
            agent_type_id=agent_type_id,
            reason="no_role_assigned",
            required_permission=tool_name,
            agent_type_name=agent_type.name,
        )

    allowed_tools = await get_allowed_tools(agent_type.role_id, db)
    if not check_tool_permission(tool_name, allowed_tools):
        logger.warning(
            "Permission denied: tool '%s' not allowed for agent_type='%s' role=%s",
            tool_name,
            agent_type.name,
            agent_type.role_id,
        )
        return AuthorizationResult(
            authorized=False,
            identity_token=None,
            identity_id=None,
            agent_type_id=agent_type_id,
            reason="insufficient_permissions",
            required_permission=tool_name,
            agent_type_name=agent_type.name,
        )

    # 4. Get agent identity and check/refresh token
    if agent_type.identity_id is None:
        return AuthorizationResult(
            authorized=False,
            identity_token=None,
            identity_id=None,
            agent_type_id=agent_type_id,
            reason="no_identity_assigned",
            required_permission=None,
            agent_type_name=agent_type.name,
        )

    identity = await get_agent_identity(agent_type.identity_id, db)
    if identity is None:
        return AuthorizationResult(
            authorized=False,
            identity_token=None,
            identity_id=agent_type.identity_id,
            agent_type_id=agent_type_id,
            reason="identity_not_found",
            required_permission=None,
            agent_type_name=agent_type.name,
        )

    # 5. Check/refresh token
    needs_refresh = await check_token_expiration(identity.id, db)
    if needs_refresh:
        logger.info(
            "Token expired for identity %s (agent_type=%s); triggering refresh",
            identity.id,
            agent_type.name,
        )
        try:
            refresh_result = await refresh_oauth_token(identity.id, db)
            access_token_plain = refresh_result.access_token
            # Re-fetch identity to get encrypted version for vault consistency
            await db.refresh(identity)
        except TokenRefreshError as exc:
            logger.error(
                "Token refresh failed for identity %s: %s",
                identity.id,
                exc,
            )
            return AuthorizationResult(
                authorized=False,
                identity_token=None,
                identity_id=identity.id,
                agent_type_id=agent_type_id,
                reason=f"token_refresh_failed: {exc}",
                required_permission=None,
                agent_type_name=agent_type.name,
            )
    else:
        # Decrypt current access token
        if not identity.access_token:
            return AuthorizationResult(
                authorized=False,
                identity_token=None,
                identity_id=identity.id,
                agent_type_id=agent_type_id,
                reason="no_access_token",
                required_permission=None,
                agent_type_name=agent_type.name,
            )
        vault = get_vault()
        try:
            access_token_plain = vault.decrypt(identity.access_token)
        except Exception as exc:
            logger.error("Failed to decrypt access token for identity %s: %s", identity.id, exc)
            return AuthorizationResult(
                authorized=False,
                identity_token=None,
                identity_id=identity.id,
                agent_type_id=agent_type_id,
                reason="token_decryption_failed",
                required_permission=None,
                agent_type_name=agent_type.name,
            )

    return AuthorizationResult(
        authorized=True,
        identity_token=access_token_plain,
        identity_id=identity.id,
        agent_type_id=agent_type_id,
        reason=None,
        required_permission=None,
        agent_type_name=agent_type.name,
    )


# ── Lookup helpers ────────────────────────────────────────────────────────────


async def _get_certificate_by_serial(
    serial_number: str, db: AsyncSession
) -> AgentInstanceCertificate | None:
    """Look up a certificate record by serial number."""
    result = await db.execute(
        select(AgentInstanceCertificate).where(
            AgentInstanceCertificate.serial_number == serial_number
        )
    )
    return result.scalar_one_or_none()


async def get_agent_type_from_certificate(
    serial_number: str, db: AsyncSession
) -> AgentType | None:
    """Look up the agent type for a certificate serial number."""
    cert = await _get_certificate_by_serial(serial_number, db)
    if cert is None:
        return None
    return await _get_agent_type(cert.agent_type_id, db)


async def _get_agent_type(
    agent_type_id: uuid.UUID, db: AsyncSession
) -> AgentType | None:
    """Look up an agent type by ID."""
    return await db.get(AgentType, agent_type_id)


async def get_agent_identity(
    identity_id: uuid.UUID, db: AsyncSession
) -> AgentIdentity | None:
    """Retrieve the assigned identity for an agent type."""
    return await db.get(AgentIdentity, identity_id)


async def get_allowed_tools(role_id: uuid.UUID, db: AsyncSession) -> set[str]:
    """Resolve a role to its complete set of allowed MCP tool identifiers."""
    return await _permission_manager.calculate_allowed_tools(role_id, db)


def check_tool_permission(tool_name: str, allowed_tools: set[str]) -> bool:
    """Return True if tool_name is in the allowed tools set."""
    return tool_name in allowed_tools


# ── Main Service Class ────────────────────────────────────────────────────────


class PermissionResolutionService:
    """Stateless service facade for certificate-based permission resolution."""

    async def resolve_permissions(
        self,
        certificate_serial_number: str,
        tool_name: str,
        db: AsyncSession,
    ) -> AuthorizationResult:
        return await resolve_permissions(certificate_serial_number, tool_name, db)

    async def get_agent_type_from_certificate(
        self, serial_number: str, db: AsyncSession
    ) -> AgentType | None:
        return await get_agent_type_from_certificate(serial_number, db)

    async def get_agent_identity(
        self, identity_id: uuid.UUID, db: AsyncSession
    ) -> AgentIdentity | None:
        return await get_agent_identity(identity_id, db)

    async def get_allowed_tools(
        self, role_id: uuid.UUID, db: AsyncSession
    ) -> set[str]:
        return await get_allowed_tools(role_id, db)

    def check_tool_permission(
        self, tool_name: str, allowed_tools: set[str]
    ) -> bool:
        return check_tool_permission(tool_name, allowed_tools)
