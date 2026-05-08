"""AgentIdentity CRUD service — manages first-class OIDC agent identities.

OAuth flow:
  1. get_oauth_authorize_url(identity_id, redirect_uri) → authorization URL pointing at the
     configured agent realm.  The identity_id is encoded in the `state` parameter so the
     callback can locate the record.
  2. complete_oauth_flow(identity_id, code, redirect_uri) → exchanges the authorization code
     for an access + refresh token pair, AES-256 encrypts both, and persists them on the
     AgentIdentity record.  Sets status to `active`.
"""
import json
import logging
import urllib.parse
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.core.yaml_config import load_identity_yaml
from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentIdentityType, AgentRole, AgentRoleIdentity, AgentType

logger = logging.getLogger(__name__)


class AgentIdentityNotFoundError(Exception):
    """Raised when an AgentIdentity is not found."""


class AgentIdentityConflictError(Exception):
    """Raised when deletion is blocked by a referencing AgentType."""


class AgentOAuthError(Exception):
    """Raised when the OAuth authorization code exchange fails."""


def _keycloak_base_url() -> str:
    """Derive the Keycloak base URL from the configured OIDC provider URL.

    e.g. "http://localhost:8082/realms/parthenon" → "http://localhost:8082"
    Falls back to the raw oidc_provider_url if it doesn't look like a realm URL.
    """
    settings = get_settings()
    url = settings.oidc_provider_url.rstrip("/")
    # Strip "/realms/<realm>" suffix if present
    if "/realms/" in url:
        return url.split("/realms/")[0]
    return url


def _agent_realm_name() -> str:
    """Return the configured agent realm name (default: ai_agents)."""
    yaml_cfg = load_identity_yaml()
    return getattr(yaml_cfg, "agent_realm_name", None) or "ai_agents"


def _agent_realm_client_id() -> str:
    """Return the OAuth client ID registered in the agent realm."""
    settings = get_settings()
    # Use the platform client_id but suffixed so it's distinct in the agent realm
    base_client_id = settings.jwt_audience or "parthenon-api"
    return f"{base_client_id}"


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

    async def list_identities(self, db: AsyncSession) -> list[AgentIdentity]:
        """Return all AgentIdentity records ordered by name."""
        result = await db.execute(
            select(AgentIdentity).order_by(AgentIdentity.name)
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

        # Referential integrity guard
        ref_check = await db.execute(
            select(AgentType.id).where(AgentType.identity_id == identity_id).limit(1)
        )
        if ref_check.scalar_one_or_none() is not None:
            raise AgentIdentityConflictError(
                f"AgentIdentity {identity_id} is referenced by one or more AgentTypes and cannot be deleted"
            )

        await db.delete(identity)
        await db.flush()
        logger.info("Deleted AgentIdentity %s", identity_id)

    # ── OAuth Flow ────────────────────────────────────────────────────────────

    def get_oauth_authorize_url(self, state: str, redirect_uri: str) -> str:
        """Generate the OAuth authorization URL for signing in as the agent user.

        The state parameter is passed through the OAuth flow and returned to the
        callback. It can be a UUID (for token refresh) or "new" (for creation).

        Args:
            state: State value to pass to callback (UUID or "new").
            redirect_uri: Callback URL registered with the OIDC client.

        Returns:
            Full authorization URL to redirect the administrator's browser to.
        """
        keycloak_base = _keycloak_base_url()
        realm = _agent_realm_name()
        client_id = _agent_realm_client_id()

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid profile email offline_access",
            "state": state,
            "prompt": "login",  # Force re-authentication even if SSO session exists
            # login_hint omitted to prevent pre-filling username from previous session
        }
        auth_url = (
            f"{keycloak_base}/realms/{realm}/protocol/openid-connect/auth"
            f"?{urllib.parse.urlencode(params)}"
        )
        logger.info("Generated OAuth authorize URL with state=%s in realm %s (prompt=login)", state, realm)
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

        keycloak_base = _keycloak_base_url()
        realm = _agent_realm_name()
        client_id = _agent_realm_client_id()
        token_url = f"{keycloak_base}/realms/{realm}/protocol/openid-connect/token"

        token_data: dict
        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as http_client:
            response = await http_client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
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
        keycloak_base = _keycloak_base_url()
        realm = _agent_realm_name()
        client_id = _agent_realm_client_id()
        token_url = f"{keycloak_base}/realms/{realm}/protocol/openid-connect/token"

        # Exchange code for tokens
        token_data: dict
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
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
        keycloak_base = _keycloak_base_url()
        realm = identity.realm_name or _agent_realm_name()
        client_id = _agent_realm_client_id()
        token_url = f"{keycloak_base}/realms/{realm}/protocol/openid-connect/token"

        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as http_client:
            response = await http_client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
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
            raise AgentOAuthError(
                f"Token refresh failed (HTTP {response.status_code}): {response.text[:200]}"
            )

        token_data = response.json()
        access_token_plain: str = token_data["access_token"]
        new_refresh_token_plain: str | None = token_data.get("refresh_token")
        expires_in: int = int(token_data.get("expires_in", 300))

        identity.access_token = vault.encrypt(access_token_plain)
        if new_refresh_token_plain:
            identity.refresh_token = vault.encrypt(new_refresh_token_plain)
        identity.token_expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )
        identity.status = AgentIdentityStatus.active

        await db.flush()
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

        # Build redirect URI from the incoming request
        base_url = str(request.base_url).rstrip("/")
        redirect_uri = f"{base_url}/api/v1/agents/oauth/callback"

        state = str(identity_id)
        return self.get_oauth_authorize_url(state=state, redirect_uri=redirect_uri)

