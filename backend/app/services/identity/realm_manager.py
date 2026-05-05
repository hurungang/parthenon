"""RealmManager — initializes and configures the agent realm in the OIDC provider.

On first run (keycloak_bundled mode), this service creates the agent realm,
applies token lifetime and session policies to match the user realm, and
registers the platform's OAuth client for the authorization code flow.

When provider_type is 'external', initialization is skipped with a warning
because the operator is responsible for pre-configuring the agent realm.
"""
from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.yaml_config import load_identity_yaml
from app.services.identity.keycloak_admin_client import KeycloakAdminClient, KeycloakAdminError

logger = logging.getLogger(__name__)

# Token lifetime / session policies applied to the agent realm (matches typical user realm defaults)
_REALM_TOKEN_POLICIES: dict[str, object] = {
    "accessTokenLifespan": 300,           # 5 minutes
    "ssoSessionIdleTimeout": 1800,        # 30 minutes
    "ssoSessionMaxLifespan": 36000,       # 10 hours
    "offlineSessionIdleTimeout": 2592000, # 30 days (refresh token lifetime)
    "enabled": True,
}


class RealmManagerError(Exception):
    """Raised when agent realm initialization fails."""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


class RealmManager:
    """Manages the lifecycle of the agent realm in the configured OIDC provider.

    Usage:
        manager = RealmManager()
        await manager.initialize_agent_realm(realm_name="ai_agents")
    """

    def _get_keycloak_base_url(self) -> str | None:
        """Derive the Keycloak base URL from oidc_provider_url.

        Returns None if the URL pattern is unexpected.
        """
        settings = get_settings()
        url = settings.oidc_provider_url.rstrip("/")
        if "/realms/" in url:
            return url.split("/realms/")[0]
        return url or None

    async def initialize_agent_realm(self, realm_name: str | None = None) -> None:
        """Initialize the agent realm in the OIDC provider.

        For ``keycloak_bundled`` providers:
          1. Creates the realm if it does not exist.
          2. Applies token lifetime and session policies.
          3. Registers the platform OAuth client for the authorization code flow.

        For ``external`` providers: logs a warning and returns without error.

        Args:
            realm_name: Agent realm name to initialize.  Defaults to the value
                of ``agent_realm_name`` in ``config/identity.yaml``, or
                ``"ai_agents"`` if not set.
        """
        yaml_cfg = load_identity_yaml()
        provider_type = yaml_cfg.provider_type or "unconfigured"

        if provider_type not in ("keycloak_bundled",):
            logger.warning(
                "Agent realm initialization skipped: provider_type=%r. "
                "For external providers the agent realm must be pre-configured manually.",
                provider_type,
            )
            return

        effective_realm_name: str = (
            realm_name
            or getattr(yaml_cfg, "agent_realm_name", None)
            or "ai_agents"
        )

        keycloak_base = self._get_keycloak_base_url()
        if not keycloak_base:
            raise RealmManagerError(
                "missing_keycloak_url",
                "Cannot derive Keycloak base URL from oidc_provider_url — "
                "agent realm initialization aborted",
            )

        settings = get_settings()

        # Derive admin credentials from environment / settings
        # (same credentials used by IdentityBootstrapService)
        admin_user: str = getattr(settings, "keycloak_admin_user", "admin")
        admin_password: str = getattr(settings, "keycloak_admin_password", "admin")

        kc = KeycloakAdminClient(keycloak_base)
        try:
            token = await kc.authenticate(admin_user, admin_password)
        except KeycloakAdminError as exc:
            raise RealmManagerError("keycloak_auth_failed", str(exc)) from exc

        try:
            await kc.create_realm(
                token,
                realm_name=effective_realm_name,
                display_name=f"Parthenon Agent Realm ({effective_realm_name})",
            )
        except KeycloakAdminError as exc:
            raise RealmManagerError("realm_creation_failed", str(exc)) from exc

        # Apply token lifetime policies to the realm
        await self._apply_token_policies(kc, token, keycloak_base, effective_realm_name)

        # Register the platform OAuth client in the agent realm for the auth code flow
        callback_redirect_uri = (
            f"{settings.oidc_provider_url.rsplit('/realms/', 1)[0]}"
            "/api/v1/agents/oauth/callback"
            if "/realms/" in settings.oidc_provider_url
            else "/api/v1/agents/oauth/callback"
        )
        # Build frontend callback redirect URIs (same origins as user realm)
        redirect_uris = [
            f"{callback_redirect_uri}",
            "http://localhost:5173/agents/identities/oauth/callback",
            "http://localhost:5174/agents/identities/oauth/callback",
            "http://localhost:4173/agents/identities/oauth/callback",
            "http://localhost:3000/agents/identities/oauth/callback",
            "*",  # Permissive for dev; tighten in production
        ]
        client_id = yaml_cfg.client_id or "parthenon-api"
        try:
            await kc.create_oidc_client(
                token,
                realm_name=effective_realm_name,
                client_id=client_id,
                redirect_uris=redirect_uris,
                public_client=True,  # Public client for auth code flow (PKCE)
            )
        except KeycloakAdminError as exc:
            raise RealmManagerError("client_registration_failed", str(exc)) from exc

        logger.info(
            "Agent realm %r initialized in Keycloak at %s",
            effective_realm_name,
            keycloak_base,
        )

    async def _apply_token_policies(
        self,
        kc: KeycloakAdminClient,
        token: object,
        keycloak_base: str,
        realm_name: str,
    ) -> None:
        """Apply token lifetime and session policies to the agent realm."""
        import httpx
        from app.services.identity.keycloak_admin_client import AdminToken, _request_with_retry

        if not isinstance(token, AdminToken):
            return

        url = f"{keycloak_base}/admin/realms/{realm_name}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "PUT",
                url,
                json=_REALM_TOKEN_POLICIES,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
        if response.status_code not in (200, 204):
            logger.warning(
                "Failed to apply token policies to realm %r (HTTP %s): %s",
                realm_name,
                response.status_code,
                response.text[:200],
            )
        else:
            logger.debug("Token policies applied to agent realm %r", realm_name)

    async def realm_exists(self, realm_name: str | None = None) -> bool:
        """Return True if the agent realm already exists in Keycloak."""
        yaml_cfg = load_identity_yaml()
        effective_realm_name: str = (
            realm_name
            or getattr(yaml_cfg, "agent_realm_name", None)
            or "ai_agents"
        )
        keycloak_base = self._get_keycloak_base_url()
        if not keycloak_base:
            return False

        settings = get_settings()
        admin_user: str = getattr(settings, "keycloak_admin_user", "admin")
        admin_password: str = getattr(settings, "keycloak_admin_password", "admin")

        kc = KeycloakAdminClient(keycloak_base)
        try:
            token = await kc.authenticate(admin_user, admin_password)
            return await kc.realm_exists(token, effective_realm_name)
        except KeycloakAdminError:
            return False
