"""AgentIdentity CRUD service — manages first-class OIDC agent identities.

OAuth flow:
  1. get_oauth_authorize_url(identity_id, redirect_uri) → authorization URL pointing at the
     configured agent realm.  The identity_id is encoded in the `state` parameter so the
     callback can locate the record.
  2. complete_oauth_flow(identity_id, code, redirect_uri) → exchanges the authorization code
     for an access + refresh token pair, AES-256 encrypts both, and persists them on the
     AgentIdentity record.  Sets status to `active`.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentIdentityType, AgentRole, AgentRoleIdentity, AgentType

logger = logging.getLogger(__name__)


@dataclass
class AgentOAuthConfig:
    """Resolved OAuth configuration for the agent identity provider."""

    issuer_url: str
    client_id: str
    # Derived fields for building auth/token URLs
    auth_endpoint: str
    token_endpoint: str


async def _resolve_agent_oauth_config(db: AsyncSession) -> Optional[AgentOAuthConfig]:
    """Resolve the agent identity provider config from the database.

    Reads the ``IdentityProviderConfig`` with ``provider_scope == "agent"``
    from the database and resolves OIDC Discovery endpoints.  Falls back
    to the legacy env-var / YAML config if no DB config exists.
    """
    from app.db.models.identity_provider_config import IdentityProviderConfig
    from app.services.oidc_config_service import OIDCConfigService

    result = await db.execute(
        select(IdentityProviderConfig).where(
            IdentityProviderConfig.provider_scope == "agent",
            IdentityProviderConfig.is_enabled == True,
        )
    )
    agent_config = result.scalar_one_or_none()

    if agent_config is not None:
        # Resolve OIDC Discovery to get endpoints
        service = OIDCConfigService()
        try:
            discovery_result = await service.test_connection(
                issuer_url=agent_config.issuer_url,
            )
            discovery = discovery_result.get("discovery_doc", {})
            auth_ep = discovery.get("authorization_endpoint", "")
            token_ep = discovery.get("token_endpoint", "")
            if auth_ep and token_ep:
                return AgentOAuthConfig(
                    issuer_url=agent_config.issuer_url.rstrip("/"),
                    client_id=agent_config.client_id,
                    auth_endpoint=auth_ep,
                    token_endpoint=token_ep,
                )
        except Exception:
            logger.warning("Failed OIDC discovery for agent provider; falling back to legacy config")

    # Fallback to legacy config (env / YAML) for backward compatibility
    return _legacy_agent_oauth_config()


def _legacy_agent_oauth_config() -> Optional[AgentOAuthConfig]:
    """Legacy fallback using env vars (pre-DB-config era)."""

    settings = get_settings()
    url = settings.oidc_provider_url.rstrip("/")
    if "/realms/" in url:
        keycloak_base = url.split("/realms/")[0]
    else:
        keycloak_base = url

    realm = settings.agent_realm_name or "ai_agents"
    client_id = settings.jwt_audience or "parthenon-api"

    return AgentOAuthConfig(
        issuer_url=f"{keycloak_base}/realms/{realm}",
        client_id=client_id,
        auth_endpoint=f"{keycloak_base}/realms/{realm}/protocol/openid-connect/auth",
        token_endpoint=f"{keycloak_base}/realms/{realm}/protocol/openid-connect/token",
    )


class AgentIdentityNotFoundError(Exception):
    """Raised when an AgentIdentity is not found."""


class AgentIdentityConflictError(Exception):
    """Raised when deletion is blocked by a referencing AgentType."""


class AgentOAuthError(Exception):
    """Raised when the OAuth authorization code exchange fails."""


class AgentIdentityService:
    """
    Provides async CRUD operations for AgentIdentity.

    delete_identity enforces referential integrity: it rejects the delete
    if any AgentType still references the identity.

    OAuth methods:
        get_oauth_authorize_url — generate IdP redirect URL for agent sign-in.
        complete_oauth_flow — exchange authorization code for encrypted token pair.
    """

    async def create_identity(
        self,
        name: str,
        realm_name: str,
        realm_username: str,
        status: AgentIdentityStatus,
        db: AsyncSession,
        identity_type: AgentIdentityType = AgentIdentityType.realm_user,
    ) -> AgentIdentity:
        """Create a new AgentIdentity placeholder record.

        Tokens are not set at creation time — they are obtained via the
        OAuth authorize → callback flow.
        """
        identity = AgentIdentity(
            name=name,
            identity_type=identity_type,
            realm_name=realm_name,
            realm_username=realm_username,
            status=status,
        )
        db.add(identity)
        await db.flush()
        await db.refresh(identity)
        logger.info("Created AgentIdentity %s (%s)", identity.id, name)
        return identity

    async def list_identities(
        self, db: AsyncSession, limit: int = 1000, offset: int = 0
    ) -> list[AgentIdentity]:
        """Return all AgentIdentity records ordered by name."""
        result = await db.execute(
            select(AgentIdentity)
            .order_by(AgentIdentity.name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_identity(
        self, identity_id: uuid.UUID, db: AsyncSession
    ) -> AgentIdentity:
        """Fetch a single AgentIdentity by ID."""
        identity = await db.get(AgentIdentity, identity_id)
        if not identity:
            raise AgentIdentityNotFoundError(f"AgentIdentity {identity_id} not found")
        return identity

    async def update_identity(
        self,
        identity_id: uuid.UUID,
        name: str | None,
        realm_name: str | None,
        realm_username: str | None,
        status: AgentIdentityStatus | None,
        db: AsyncSession,
    ) -> AgentIdentity:
        """Update fields on an AgentIdentity. None values are left unchanged."""
        identity = await self.get_identity(identity_id, db)

        if name is not None:
            identity.name = name
        if realm_name is not None:
            identity.realm_name = realm_name
        if realm_username is not None:
            identity.realm_username = realm_username
        if status is not None:
            identity.status = status

        await db.flush()
        await db.refresh(identity)
        logger.info("Updated AgentIdentity %s", identity_id)
        return identity

    async def delete_identity(
        self, identity_id: uuid.UUID, db: AsyncSession
    ) -> None:
        """Delete an AgentIdentity. Fails if any AgentType references it."""
        identity = await self.get_identity(identity_id, db)

        # Referential integrity guard — fetch the referencing AgentType with its name
        ref_check = await db.execute(
            select(AgentType).where(AgentType.identity_id == identity_id).limit(1)
        )
        referencing_type = ref_check.scalar_one_or_none()
        if referencing_type is not None:
            error_msg = (
                f"AgentIdentity {identity_id} (name: {identity.name}) is referenced by "
                f"AgentType '{referencing_type.name}' (ID: {referencing_type.id}). "
                f"Please unassign this identity from the agent type before deleting."
            )
            logger.error(
                "Delete blocked: %s",
                error_msg,
            )
            # Return structured error with agent_type_id and agent_type_name for frontend linking
            raise AgentIdentityConflictError(
                f"agent_type_id:{referencing_type.id}|agent_type_name:{referencing_type.name}|{error_msg}"
            )

        await db.delete(identity)
        await db.flush()
        logger.info("Deleted AgentIdentity %s (name: %s)", identity_id, identity.name)

    # ── OAuth Flow ────────────────────────────────────────────────────────────

    async def get_oauth_authorize_url(self, state: str, redirect_uri: str) -> str:
        """Generate the OAuth authorization URL using the DB-stored agent provider config.

        Reads the agent ``IdentityProviderConfig`` from the database (with
        fallback to legacy env/YAML config for backward compatibility).

        Args:
            state: State value to pass to callback (UUID or "new").
            redirect_uri: Callback URL registered with the OIDC client.

        Returns:
            Full authorization URL to redirect the administrator's browser to.
        """
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            oauth_config = await _resolve_agent_oauth_config(db)

        if oauth_config is None:
            raise AgentOAuthError("No agent identity provider configured. Configure one in System Config.")

        params = {
            "client_id": oauth_config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email offline_access",
            "state": state,
            "prompt": "login",
        }
        auth_url = (
            f"{oauth_config.auth_endpoint}"
            f"?{urllib.parse.urlencode(params)}"
        )
        logger.info(
            "Generated OAuth authorize URL with state=%s issuer=%s (prompt=login)",
            state, oauth_config.issuer_url,
        )
        return auth_url

    async def complete_oauth_flow(
        self,
        identity_id: uuid.UUID,
        code: str,
        redirect_uri: str,
        db: AsyncSession,
    ) -> AgentIdentity:
        """Exchange an authorization code for tokens and persist them encrypted.

        Calls the agent realm token endpoint, stores AES-256 encrypted access
        and refresh tokens on the AgentIdentity record, and sets status to `active`.

        Args:
            identity_id: UUID of the AgentIdentity being authorized.
            code: Authorization code from the IdP redirect.
            redirect_uri: Must exactly match the redirect_uri used in the authorize step.
            db: Active async database session.

        Returns:
            Updated AgentIdentity with token_expires_at populated.

        Raises:
            AgentIdentityNotFoundError: If identity_id does not exist.
            AgentOAuthError: If the token exchange request fails.
        """
        identity = await self.get_identity(identity_id, db)

        oauth_config = await _resolve_agent_oauth_config(db)
        if oauth_config is None:
            raise AgentOAuthError("No agent identity provider configured")

        token_data: dict
        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as http_client:
            response = await http_client.post(
                oauth_config.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": oauth_config.client_id,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )

        if response.status_code != 200:
            logger.error(
                "Token exchange failed for identity %s: HTTP %s — %s",
                identity_id,
                response.status_code,
                response.text[:200],
            )
            raise AgentOAuthError(
                f"Token exchange failed (HTTP {response.status_code}): {response.text[:200]}"
            )

        token_data = response.json()
        vault = get_vault()
        access_token_plain: str = token_data["access_token"]
        refresh_token_plain: str | None = token_data.get("refresh_token")
        expires_in: int = int(token_data.get("expires_in", 300))

        identity.access_token = vault.encrypt(access_token_plain)
        if refresh_token_plain:
            identity.refresh_token = vault.encrypt(refresh_token_plain)
        identity.token_expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )
        identity.status = AgentIdentityStatus.active

        await db.flush()
        await db.refresh(identity)
        logger.info(
            "OAuth flow completed for identity %s; token_expires_at=%s",
            identity_id,
            identity.token_expires_at,
        )
        return identity

    async def create_identity_from_oauth(
        self,
        code: str,
        redirect_uri: str,
        db: AsyncSession,
    ) -> AgentIdentity:
        """Auto-create AgentIdentity after successful OAuth sign-in.

        Exchanges the authorization code for tokens, decodes the access token
        to extract the username and realm, then creates or updates an AgentIdentity
        record for that realm_username.

        Args:
            code: Authorization code from the IdP redirect.
            redirect_uri: Must exactly match the redirect_uri used in the authorize step.
            db: Active async database session.

        Returns:
            Created or updated AgentIdentity with encrypted tokens.

        Raises:
            AgentOAuthError: If the token exchange or userinfo request fails.
        """
        oauth_config = await _resolve_agent_oauth_config(db)
        if oauth_config is None:
            raise AgentOAuthError("No agent identity provider configured")

        # Exchange code for tokens
        token_data: dict
        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as http_client:
            response = await http_client.post(
                oauth_config.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": oauth_config.client_id,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )

        if response.status_code != 200:
            logger.error(
                "Token exchange failed for new identity: HTTP %s — %s",
                response.status_code,
                response.text[:200],
            )
            raise AgentOAuthError(
                f"Token exchange failed (HTTP {response.status_code}): {response.text[:200]}"
            )

        token_data = response.json()
        access_token_plain: str = token_data["access_token"]
        refresh_token_plain: str | None = token_data.get("refresh_token")
        expires_in: int = int(token_data.get("expires_in", 300))

        # Extract realm from issuer URL (format: http://host:port/realms/{realm_name})
        realm_parts = oauth_config.issuer_url.split("/realms/")
        realm = realm_parts[-1] if len(realm_parts) > 1 else "ai_agents"

        # Decode access token to extract username (JWT claims: preferred_username)
        # Keycloak JWTs have 3 parts: header.payload.signature
        try:
            payload_b64 = access_token_plain.split(".")[1]
            # Add padding if needed
            padding = 4 - (len(payload_b64) % 4)
            if padding != 4:
                payload_b64 += "=" * padding
            import base64
            payload_json = base64.urlsafe_b64decode(payload_b64)
            claims = json.loads(payload_json)
            realm_username = claims.get("preferred_username") or claims.get("sub")
            if not realm_username:
                raise AgentOAuthError("Access token missing preferred_username and sub claims")
        except (IndexError, ValueError, KeyError) as exc:
            logger.error("Failed to decode access token: %s", exc)
            raise AgentOAuthError(f"Failed to decode access token: {exc}")

        # Check if identity already exists for this realm_username
        stmt = select(AgentIdentity).where(
            AgentIdentity.realm_name == realm,
            AgentIdentity.realm_username == realm_username,
        )
        result = await db.execute(stmt)
        identity = result.scalar_one_or_none()

        vault = get_vault()
        token_expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )

        if identity:
            # Update existing identity's tokens
            identity.access_token = vault.encrypt(access_token_plain)
            if refresh_token_plain:
                identity.refresh_token = vault.encrypt(refresh_token_plain)
            identity.token_expires_at = token_expires_at
            identity.status = AgentIdentityStatus.active
            await db.flush()
            await db.refresh(identity)
            logger.info(
                "Updated existing AgentIdentity %s for %s@%s",
                identity.id,
                realm_username,
                realm,
            )
        else:
            # Create new identity
            identity = AgentIdentity(
                name=f"{realm_username}@{realm}",
                identity_type=AgentIdentityType.realm_user,
                realm_name=realm,
                realm_username=realm_username,
                status=AgentIdentityStatus.active,
                access_token=vault.encrypt(access_token_plain),
                refresh_token=vault.encrypt(refresh_token_plain) if refresh_token_plain else None,
                token_expires_at=token_expires_at,
            )
            db.add(identity)
            await db.flush()
            await db.refresh(identity)
            logger.info(
                "Created new AgentIdentity %s for %s@%s",
                identity.id,
                realm_username,
                realm,
            )

        return identity

    # ── Role Assignment Methods ────────────────────────────────────────────────

    async def assign_roles(
        self,
        identity_id: uuid.UUID,
        role_ids: list[uuid.UUID],
        db: AsyncSession,
    ) -> None:
        """Bulk-assign roles to an identity. Skips duplicates."""
        identity = await self.get_identity(identity_id, db)

        for role_id in role_ids:
            existing = await db.execute(
                select(AgentRoleIdentity).where(
                    AgentRoleIdentity.role_id == role_id,
                    AgentRoleIdentity.identity_id == identity_id,
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(AgentRoleIdentity(role_id=role_id, identity_id=identity_id))

        await db.flush()
        logger.info("Assigned %d role(s) to identity %s", len(role_ids), identity_id)

    async def remove_role(
        self,
        identity_id: uuid.UUID,
        role_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Remove a specific role assignment from an identity."""
        await self.get_identity(identity_id, db)  # Validates identity exists

        result = await db.execute(
            select(AgentRoleIdentity).where(
                AgentRoleIdentity.role_id == role_id,
                AgentRoleIdentity.identity_id == identity_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.flush()
        logger.info("Removed role %s from identity %s", role_id, identity_id)

    async def list_roles(
        self,
        identity_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[AgentRole]:
        """List all AgentRole records assigned to an identity."""
        await self.get_identity(identity_id, db)  # Validates identity exists

        result = await db.execute(
            select(AgentRole)
            .options(
                selectinload(AgentRole.sop_assignments),
                selectinload(AgentRole.skill_assignments),
            )
            .join(AgentRoleIdentity, AgentRoleIdentity.role_id == AgentRole.id)
            .where(AgentRoleIdentity.identity_id == identity_id)
            .order_by(AgentRole.name)
        )
        return list(result.scalars().all())

    # ── Token Refresh Methods ──────────────────────────────────────────────────

    async def refresh_token(
        self,
        identity_id: uuid.UUID,
        db: AsyncSession,
    ) -> AgentIdentity:
        """Refresh the access token using the stored refresh token.

        Decrypts the stored refresh token, calls the IdP token endpoint with
        grant_type=refresh_token, re-encrypts the new token pair, and persists.

        Raises:
            AgentIdentityNotFoundError: If identity not found.
            AgentOAuthError: If refresh token is missing or the request fails.
        """
        identity = await self.get_identity(identity_id, db)

        vault = get_vault()
        if not identity.refresh_token:
            raise AgentOAuthError(
                f"Identity {identity_id} has no refresh token stored — re-authentication required"
            )

        refresh_token_plain = vault.decrypt(identity.refresh_token)
        oauth_config = await _resolve_agent_oauth_config(db)
        if oauth_config is None:
            raise AgentOAuthError("No agent identity provider configured")

        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as http_client:
            response = await http_client.post(
                oauth_config.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "client_id": oauth_config.client_id,
                    "refresh_token": refresh_token_plain,
                },
            )

        if response.status_code != 200:
            logger.error(
                "Token refresh failed for identity %s: HTTP %s — %s",
                identity_id,
                response.status_code,
                response.text[:200],
            )
            # Clear the refresh token so the UI will switch to re-auth button
            identity.refresh_token = None
            identity.status = AgentIdentityStatus.suspended
            await db.flush()
            await db.commit()
            await db.refresh(identity)
            raise AgentOAuthError(
                f"Token refresh failed (HTTP {response.status_code}): {response.text[:200]}"
            )

        token_data = response.json()
        access_token_plain: str = token_data["access_token"]
        new_refresh_token_plain: str | None = token_data.get("refresh_token")
        expires_in: int = int(token_data.get("expires_in", 300))

        logger.info(
            "Token refresh response for identity %s: has_new_refresh_token=%s",
            identity_id,
            new_refresh_token_plain is not None,
        )

        identity.access_token = vault.encrypt(access_token_plain)
        if new_refresh_token_plain:
            encrypted_new_refresh = vault.encrypt(new_refresh_token_plain)
            identity.refresh_token = encrypted_new_refresh
            # Also update encrypted_refresh_token to keep both fields in sync
            # (auto-refresh in runtime_executor checks this field first)
            identity.encrypted_refresh_token = encrypted_new_refresh
            logger.debug(
                "Updated both refresh_token and encrypted_refresh_token for identity %s",
                identity_id,
            )
        else:
            logger.warning(
                "Keycloak did not return a new refresh_token for identity %s - "
                "old refresh_token will remain (may be invalid for next auto-refresh)",
                identity_id,
            )
        identity.token_expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )
        identity.status = AgentIdentityStatus.active

        await db.flush()
        await db.commit()
        await db.refresh(identity)
        logger.info(
            "Token refreshed for identity %s; new token_expires_at=%s",
            identity_id,
            identity.token_expires_at,
        )
        return identity

    async def get_reauth_url(
        self,
        identity_id: uuid.UUID,
        request: Request,
        db: AsyncSession,
    ) -> str:
        """Generate an OAuth re-authentication URL for an identity.

        Uses the same authorize URL flow as initial authentication, embedding
        the identity_id in the state parameter so the callback can locate the record.

        Returns:
            Full authorization URL for the admin's browser redirect.
        """
        identity = await self.get_identity(identity_id, db)

        # Build redirect_uri pointing at the frontend callback page
        # Extract origin from request headers (for dev/prod flexibility)
        origin = request.headers.get("origin")
        if not origin:
            # Fallback: extract from referer if origin not present
            referer = request.headers.get("referer", "")
            if referer:
                from urllib.parse import urlparse
                parsed = urlparse(referer)
                origin = f"{parsed.scheme}://{parsed.netloc}"
        if not origin or not origin.startswith("http"):
            origin = "http://localhost:5173"  # Default to Vite dev server

        # Redirect URI must point to the frontend OAuth callback page, not the API endpoint
        redirect_uri = f"{origin}/agents/identities/oauth/callback"

        state = str(identity_id)
        return await self.get_oauth_authorize_url(state=state, redirect_uri=redirect_uri)

