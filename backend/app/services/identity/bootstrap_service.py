"""Identity Bootstrap Service.

Orchestrates the full identity provider setup lifecycle:
- Detect current setup state.
- Provision bundled Keycloak.
- Register external OIDC provider.
- Persist resolved settings to DB + config/identity.yaml.
- Trigger OIDC client reload.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.credential_vault import get_vault
from app.core.yaml_config import IdentityYamlConfig
from app.core.yaml_writer import write_identity_yaml
from app.db.models.identity_provider_config import IdentityProviderConfig
from app.db.models.identity_provider_setup_state import IdentityProviderSetupState
from app.schemas.identity_bootstrap import (
    ProviderSetupRequest,
    ProviderSetupResult,
    ProviderType,
    SetupState,
)
from app.services.identity.keycloak_admin_client import KeycloakAdminClient, KeycloakAdminError

logger = logging.getLogger(__name__)


class IdentityBootstrapService:
    """Orchestrates first-run detection and identity provider provisioning."""

    # ------------------------------------------------------------------ #
    # State detection                                                       #
    # ------------------------------------------------------------------ #

    async def check_setup_state(self, db: AsyncSession) -> SetupState:
        """Determine the current setup state.

        Queries ``IdentityProviderSetupState`` first; falls back to the
        ``identity_setup_complete`` flag in ``Settings`` (which is sourced
        from identity.yaml) when the DB is empty.

        Returns:
            :attr:`SetupState.CONFIGURED` if setup is complete,
            :attr:`SetupState.NOT_CONFIGURED` otherwise.
            :attr:`SetupState.IN_PROGRESS` is reserved for future use.
        """
        result = await db.execute(select(IdentityProviderSetupState))
        row = result.scalar_one_or_none()

        if row is not None:
            return SetupState.CONFIGURED if row.is_setup_complete else SetupState.NOT_CONFIGURED

        # No DB row yet — check YAML / Settings fallback
        settings = get_settings()
        if settings.identity_setup_complete:
            return SetupState.CONFIGURED

        return SetupState.NOT_CONFIGURED

    async def get_current_config(self, db: AsyncSession) -> Optional[IdentityProviderConfig]:
        """Return the active ``IdentityProviderConfig`` DB row, or ``None``."""
        result = await db.execute(
            select(IdentityProviderConfig)
            .where(IdentityProviderConfig.is_setup_complete.is_(True))
            .order_by(IdentityProviderConfig.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------ #
    # Bundled Keycloak provisioning                                         #
    # ------------------------------------------------------------------ #

    async def provision_bundled_keycloak(
        self, db: AsyncSession, request: ProviderSetupRequest
    ) -> ProviderSetupResult:
        """Provision a bundled Keycloak instance.

        Steps:
        1. Validate Keycloak reachability.
        2. Authenticate with master-realm admin credentials.
        3. Create realm (idempotent).
        4. Create ``parthenon-api`` confidential client.
        5. Create ``parthenon-ui`` public client.
        6. Create initial admin user in the realm.
        7. Persist to DB (within a transaction).
        8. Write identity.yaml.
        9. Reload the OIDC client.

        Raises:
            :class:`KeycloakAdminError` if any Keycloak step fails.
        """
        if not request.keycloak_url:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="missing_keycloak_url",
                detail="keycloak_url is required for bundled Keycloak provisioning",
            )
        if not request.realm_name:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="missing_realm_name",
                detail="realm_name is required for bundled Keycloak provisioning",
            )
        if not request.client_id:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="missing_client_id",
                detail="client_id is required",
            )
        if not request.admin_user or not request.admin_password:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="missing_admin_credentials",
                detail="admin_user and admin_password are required for bundled Keycloak",
            )

        keycloak_url = request.keycloak_url.rstrip("/")
        realm_name = request.realm_name
        client_id = request.client_id

        # 1. Validate reachability
        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.get(f"{keycloak_url}/health/ready")
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Keycloak health check returned {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("Keycloak unreachable at %s: %s", keycloak_url, exc)
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="keycloak_unreachable",
                detail=f"Cannot reach Keycloak at {keycloak_url}: {exc}",
            )

        # 2–6. Keycloak provisioning
        try:
            kc = KeycloakAdminClient(keycloak_url)
            token = await kc.authenticate(request.admin_user, request.admin_password)
            await kc.create_realm(token, realm_name)
            api_secret_obj = await kc.create_oidc_client(
                token, realm_name, client_id, public_client=False
            )
            await kc.create_oidc_client(
                token,
                realm_name,
                f"{client_id}-ui",
                redirect_uris=[
                    "http://localhost:5173/*",
                    "http://localhost:5174/*",
                    "http://localhost:4173/*",
                    "http://localhost:3000/*",
                ],
                public_client=True,
            )
            if request.initial_admin_password:
                await kc.create_user(
                    token,
                    realm_name,
                    "admin",
                    request.initial_admin_password,
                )
        except KeycloakAdminError as exc:
            logger.error("Keycloak provisioning failed: %s", exc)
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code=exc.error_code,
                detail=exc.detail,
            )

        oidc_provider_url = f"{keycloak_url}/realms/{realm_name}"
        encrypted_secret: Optional[str] = None
        if api_secret_obj and api_secret_obj.value:
            encrypted_secret = get_vault().encrypt(api_secret_obj.value)

        # 7. Persist to DB within a transaction
        now = datetime.now(timezone.utc)
        try:
            config_row = IdentityProviderConfig(
                id=uuid.uuid4(),
                provider_type=request.provider_type.value,
                oidc_provider_url=oidc_provider_url,
                client_id=client_id,
                client_secret=encrypted_secret,
                realm_name=realm_name,
                audience=client_id,
                is_setup_complete=True,
                setup_completed_at=now,
            )
            db.add(config_row)

            # Upsert the single-row state sentinel
            state_result = await db.execute(select(IdentityProviderSetupState))
            state_row = state_result.scalar_one_or_none()
            if state_row is None:
                state_row = IdentityProviderSetupState(
                    id=uuid.uuid4(),
                    is_setup_complete=True,
                    completed_at=now,
                )
                db.add(state_row)
            else:
                state_row.is_setup_complete = True
                state_row.completed_at = now

            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("DB commit failed during bundled Keycloak provisioning: %s", exc)
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="db_error",
                detail=f"Database error during provisioning: {exc}",
            )

        # 8. Write identity.yaml
        yaml_cfg = IdentityYamlConfig(
            provider_type=request.provider_type.value,
            oidc_provider_url=oidc_provider_url,
            realm_name=realm_name,
            client_id=client_id,
            audience=client_id,
            jwt_algorithm="RS256",
            setup_complete=True,
            completed_at=now.isoformat(),
        )
        try:
            write_identity_yaml(yaml_cfg)
        except Exception as exc:
            logger.warning("Failed to write identity.yaml (non-fatal): %s", exc)

        # 9. Reload OIDC client and clear settings cache
        self._reload_oidc_client(oidc_provider_url, "RS256", client_id)

        return ProviderSetupResult(
            success=True,
            provider_type=request.provider_type.value,
            oidc_provider_url=oidc_provider_url,
            realm_name=realm_name,
            client_id=client_id,
        )

    # ------------------------------------------------------------------ #
    # External OIDC provisioning                                           #
    # ------------------------------------------------------------------ #

    async def provision_external_oidc(
        self, db: AsyncSession, request: ProviderSetupRequest
    ) -> ProviderSetupResult:
        """Register an external OIDC provider.

        Steps:
        1. Fetch /.well-known/openid-configuration to validate the URL.
        2. Store client ID + encrypted secret in ``IdentityProviderConfig``.
        3. Mark setup complete in ``IdentityProviderSetupState``.
        4. Write identity.yaml.
        5. Reload the OIDC client.
        """
        if not request.oidc_discovery_url and not request.keycloak_url:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="missing_oidc_url",
                detail="oidc_discovery_url (or keycloak_url for external Keycloak) is required",
            )
        if not request.client_id:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="missing_client_id",
                detail="client_id is required",
            )

        # Resolve the discovery URL and the provider base URL
        discovery_url = request.oidc_discovery_url
        if not discovery_url:
            # For keycloak_external without explicit discovery URL, build it
            base = (request.keycloak_url or "").rstrip("/")
            realm = request.realm_name or "master"
            discovery_url = f"{base}/realms/{realm}/.well-known/openid-configuration"

        # 1. Fetch discovery document
        try:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                resp = await http_client.get(discovery_url)
                resp.raise_for_status()
                discovery_doc: dict = resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="oidc_unreachable",
                detail=f"Cannot reach OIDC discovery URL {discovery_url}: {exc}",
            )
        except httpx.HTTPStatusError as exc:
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="oidc_discovery_failed",
                detail=f"OIDC discovery endpoint returned HTTP {exc.response.status_code}",
            )

        # Extract provider URL from the discovery document
        issuer: str = discovery_doc.get("issuer", discovery_url.split("/.well-known")[0])
        oidc_provider_url = issuer.rstrip("/")

        encrypted_secret: Optional[str] = None
        if request.client_secret:
            encrypted_secret = get_vault().encrypt(request.client_secret)

        now = datetime.now(timezone.utc)

        # 2–3. Persist to DB
        try:
            config_row = IdentityProviderConfig(
                id=uuid.uuid4(),
                provider_type=request.provider_type.value,
                oidc_provider_url=oidc_provider_url,
                client_id=request.client_id,
                client_secret=encrypted_secret,
                realm_name=request.realm_name,
                audience=request.client_id,
                is_setup_complete=True,
                setup_completed_at=now,
            )
            db.add(config_row)

            state_result = await db.execute(select(IdentityProviderSetupState))
            state_row = state_result.scalar_one_or_none()
            if state_row is None:
                state_row = IdentityProviderSetupState(
                    id=uuid.uuid4(),
                    is_setup_complete=True,
                    completed_at=now,
                )
                db.add(state_row)
            else:
                state_row.is_setup_complete = True
                state_row.completed_at = now

            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("DB commit failed during external OIDC provisioning: %s", exc)
            return ProviderSetupResult(
                success=False,
                provider_type=request.provider_type.value,
                error_code="db_error",
                detail=f"Database error during provisioning: {exc}",
            )

        # 4. Write identity.yaml
        yaml_cfg = IdentityYamlConfig(
            provider_type=request.provider_type.value,
            oidc_provider_url=oidc_provider_url,
            client_id=request.client_id,
            audience=request.client_id,
            jwt_algorithm="RS256",
            setup_complete=True,
            completed_at=now.isoformat(),
            realm_name=request.realm_name or "",
        )
        try:
            write_identity_yaml(yaml_cfg)
        except Exception as exc:
            logger.warning("Failed to write identity.yaml (non-fatal): %s", exc)

        # 5. Reload OIDC client
        self._reload_oidc_client(oidc_provider_url, "RS256", request.client_id)

        return ProviderSetupResult(
            success=True,
            provider_type=request.provider_type.value,
            oidc_provider_url=oidc_provider_url,
            realm_name=request.realm_name,
            client_id=request.client_id,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _reload_oidc_client(
        provider_url: str, algorithm: str, audience: str
    ) -> None:
        """Reload the OIDC client singleton and clear the settings cache."""
        try:
            from app.core.oidc_client import get_oidc_client, reset_singleton  # noqa: PLC0415

            reset_singleton()
            client = get_oidc_client()
            client.reload(provider_url, algorithm, audience)
            get_settings.cache_clear()
            logger.info("OIDC client reloaded for provider: %s", provider_url)
        except Exception as exc:
            logger.warning("Failed to reload OIDC client: %s", exc)
