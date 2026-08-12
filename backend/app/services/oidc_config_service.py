"""OIDC Config Service — CRUD, encryption, discovery validation, and audit logging.

Provides the authoritative API for managing ``IdentityProviderConfig`` entities.
All writes go through this service so that client secrets are encrypted at rest
and audit entries are created consistently.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.identity_provider_config import IdentityProviderConfig
from app.db.models.identity_provider_config_audit import IdentityProviderConfigAudit
from app.db.models.identity_provider_setup_state import IdentityProviderSetupState

logger = logging.getLogger(__name__)

_VALID_SCOPES = {"user", "agent"}
_VALID_PROVIDER_TYPES = {"oidc_generic", "keycloak", "azure_entraid"}


class OIDCConfigError(Exception):
    """Raised when an OIDC config operation fails business validation."""


class OIDCConfigService:
    """Full CRUD for ``IdentityProviderConfig``, with encryption and auditing."""

    # ── Read ──────────────────────────────────────────────────────────────

    async def list_providers(
        self, db: AsyncSession
    ) -> list[IdentityProviderConfig]:
        """Return all configured identity providers, newest first."""
        result = await db.execute(
            select(IdentityProviderConfig).order_by(
                IdentityProviderConfig.created_at.desc()
            )
        )
        return list(result.scalars().all())

    async def get_by_scope(
        self, db: AsyncSession, scope: str
    ) -> Optional[IdentityProviderConfig]:
        """Return the config for *scope* (``user`` or ``agent``), or ``None``."""
        _validate_scope(scope)
        result = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.provider_scope == scope
            )
        )
        return result.scalar_one_or_none()

    async def get_enabled(
        self, db: AsyncSession
    ) -> list[IdentityProviderConfig]:
        """Return only enabled provider configs."""
        result = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.is_enabled.is_(True)
            )
        )
        return list(result.scalars().all())

    # ── Create ────────────────────────────────────────────────────────────

    async def create_provider(
        self,
        db: AsyncSession,
        *,
        provider_scope: str,
        provider_type: str,
        display_name: str,
        issuer_url: str,
        client_id: str,
        client_secret: Optional[str] = None,
        public_client_id: Optional[str] = None,
        scopes: str = "openid profile email",
        claim_mappings: Optional[dict] = None,
        is_enabled: bool = True,
        changed_by: str = "system",
    ) -> IdentityProviderConfig:
        """Create a new identity provider config.

        Validates OIDC Discovery at the issuer URL before persisting.
        Rejects duplicate *provider_scope* entries.
        """
        _validate_scope(provider_scope)
        _validate_provider_type(provider_type)

        # Reject duplicate scope
        existing = await self.get_by_scope(db, provider_scope)
        if existing is not None:
            raise OIDCConfigError(
                f"A provider config already exists for scope '{provider_scope}'."
            )

        issuer_url = issuer_url.rstrip("/")

        # Validate OIDC discovery before persisting
        await _validate_oidc_discovery(issuer_url)

        # Encrypt client secret
        encrypted_secret: Optional[str] = None
        if client_secret:
            encrypted_secret = get_vault().encrypt(client_secret)

        config = IdentityProviderConfig(
            id=uuid.uuid4(),
            provider_scope=provider_scope,
            provider_type=provider_type,
            display_name=display_name,
            issuer_url=issuer_url,
            client_id=client_id,
            encrypted_client_secret=encrypted_secret,
            ui_client_id=public_client_id,
            scopes=scopes,
            claim_mappings=claim_mappings,
            is_enabled=is_enabled,
        )
        db.add(config)

        # Write audit entry
        _write_audit(
            db,
            config_id=config.id,
            changed_by=changed_by,
            change_type="created",
            changed_fields=list(
                _config_diff_fields(None, config)
            ),
            previous_values=None,
        )

        # Update setup state sentinel
        await _update_setup_state(db, provider_scope, configured=True)

        await db.flush()
        await db.refresh(config)
        logger.info(
            "OIDCConfigService: created provider scope=%s type=%s",
            provider_scope, provider_type,
        )
        return config

    # ── Update ────────────────────────────────────────────────────────────

    async def update_provider(
        self,
        db: AsyncSession,
        scope: str,
        *,
        provider_type: Optional[str] = None,
        display_name: Optional[str] = None,
        issuer_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        public_client_id: Optional[str] = None,
        scopes: Optional[str] = None,
        claim_mappings: Optional[dict] = None,
        is_enabled: Optional[bool] = None,
        changed_by: str = "system",
    ) -> IdentityProviderConfig:
        """Update an existing provider config by scope.

        Only non-``None`` fields are updated.  If *issuer_url* changes the
        new URL is validated via OIDC Discovery before persisting.
        """
        _validate_scope(scope)
        if provider_type is not None:
            _validate_provider_type(provider_type)

        config = await self.get_by_scope(db, scope)
        if config is None:
            raise OIDCConfigError(
                f"No provider config exists for scope '{scope}'."
            )

        # Snapshot before change for audit
        previous_snapshot = _config_diff_fields(None, config)

        # Apply changes
        changed: list[str] = []
        if provider_type is not None and provider_type != config.provider_type:
            changed.append("provider_type")
            config.provider_type = provider_type
        if display_name is not None and display_name != config.display_name:
            changed.append("display_name")
            config.display_name = display_name
        if issuer_url is not None:
            issuer_url = issuer_url.rstrip("/")
            if issuer_url != config.issuer_url:
                changed.append("issuer_url")
                config.issuer_url = issuer_url
                await _validate_oidc_discovery(issuer_url)
        if client_id is not None and client_id != config.client_id:
            changed.append("client_id")
            config.client_id = client_id
        if client_secret is not None:
            changed.append("encrypted_client_secret")
            config.encrypted_client_secret = get_vault().encrypt(client_secret)
        if public_client_id is not None:
            changed.append("ui_client_id")
            config.ui_client_id = public_client_id
        if scopes is not None and scopes != config.scopes:
            changed.append("scopes")
            config.scopes = scopes
        if claim_mappings is not None and claim_mappings != config.claim_mappings:
            changed.append("claim_mappings")
            config.claim_mappings = claim_mappings
        if is_enabled is not None and is_enabled != config.is_enabled:
            changed.append("is_enabled")
            config.is_enabled = is_enabled

        if changed:
            config.updated_at = datetime.now(timezone.utc)
            _write_audit(
                db,
                config_id=config.id,
                changed_by=changed_by,
                change_type="updated",
                changed_fields=changed,
                previous_values=previous_snapshot,
            )

        await db.flush()
        await db.refresh(config)
        logger.info(
            "OIDCConfigService: updated provider scope=%s fields=%s",
            scope, changed,
        )
        return config

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_provider(
        self,
        db: AsyncSession,
        scope: str,
        changed_by: str = "system",
    ) -> None:
        """Delete a provider config by scope."""
        _validate_scope(scope)
        config = await self.get_by_scope(db, scope)
        if config is None:
            raise OIDCConfigError(
                f"No provider config exists for scope '{scope}'."
            )

        # Snapshot before deletion
        previous_snapshot = _config_diff_fields(None, config)

        # Write audit entry referencing the config before deletion
        _write_audit(
            db,
            config_id=config.id,
            changed_by=changed_by,
            change_type="deleted",
            changed_fields=list(_config_diff_fields(None, config)),
            previous_values=previous_snapshot,
        )

        await db.delete(config)

        # Update setup state sentinel
        await _update_setup_state(db, scope, configured=False)

        await db.flush()
        logger.info(
            "OIDCConfigService: deleted provider scope=%s", scope,
        )

    # ── Toggle ────────────────────────────────────────────────────────────

    async def toggle_provider(
        self,
        db: AsyncSession,
        scope: str,
        is_enabled: bool,
        changed_by: str = "system",
    ) -> IdentityProviderConfig:
        """Enable or disable a provider without deleting its config."""
        _validate_scope(scope)
        config = await self.get_by_scope(db, scope)
        if config is None:
            raise OIDCConfigError(
                f"No provider config exists for scope '{scope}'."
            )

        previous_snapshot = _config_diff_fields(None, config)
        config.is_enabled = is_enabled
        config.updated_at = datetime.now(timezone.utc)

        _write_audit(
            db,
            config_id=config.id,
            changed_by=changed_by,
            change_type="updated",
            changed_fields=["is_enabled"],
            previous_values=previous_snapshot,
        )

        await db.flush()
        await db.refresh(config)
        logger.info(
            "OIDCConfigService: toggled provider scope=%s to is_enabled=%s",
            scope, is_enabled,
        )
        return config

    # ── Test connection ───────────────────────────────────────────────────

    async def test_connection(
        self,
        *,
        issuer_url: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> dict:
        """Test OIDC connectivity for a given issuer.

        Returns per-step diagnostics without persisting anything.

        Returns
        -------
        dict
            With keys ``success`` (bool), ``steps`` (list of step dicts),
            ``discovery_doc`` (dict or None).
        """
        issuer_url = issuer_url.rstrip("/")
        steps: list[dict] = []

        # Step 1: Fetch discovery document
        try:
            discovery = await _fetch_discovery(issuer_url)
            steps.append({
                "step": "discovery_fetch",
                "status": "passed",
                "detail": f"Successfully fetched from {issuer_url}/.well-known/openid-configuration",
            })
        except Exception as exc:
            steps.append({
                "step": "discovery_fetch",
                "status": "failed",
                "detail": str(exc),
            })
            return {"success": False, "steps": steps, "discovery_doc": None}

        # Step 2: Validate issuer match
        discovered_issuer = discovery.get("issuer", "")
        if discovered_issuer.rstrip("/") != issuer_url:
            steps.append({
                "step": "issuer_validation",
                "status": "failed",
                "detail": f"Issuer mismatch: expected={issuer_url}, got={discovered_issuer}",
            })
            return {"success": False, "steps": steps, "discovery_doc": discovery}
        steps.append({
            "step": "issuer_validation",
            "status": "passed",
            "detail": f"Issuer matches: {discovered_issuer}",
        })

        # Step 3: Verify JWKS endpoint
        jwks_uri = discovery.get("jwks_uri", "")
        if jwks_uri:
            try:
                async with httpx.AsyncClient(
                    timeout=10.0, verify=get_ssl_context()
                ) as http_client:
                    resp = await http_client.get(jwks_uri)
                    resp.raise_for_status()
                    jwks_data = resp.json()
                    keys = jwks_data.get("keys", [])
                    steps.append({
                        "step": "jwks_verification",
                        "status": "passed",
                        "detail": f"JWKS endpoint reachable, {len(keys)} key(s) found",
                    })
            except Exception as exc:
                steps.append({
                    "step": "jwks_verification",
                    "status": "failed",
                    "detail": f"JWKS endpoint unreachable: {exc}",
                })
        else:
            steps.append({
                "step": "jwks_verification",
                "status": "skipped",
                "detail": "No jwks_uri in discovery document",
            })

        # Step 4: Check token endpoint
        token_endpoint = discovery.get("token_endpoint", "")
        if token_endpoint:
            try:
                async with httpx.AsyncClient(
                    timeout=10.0, verify=get_ssl_context()
                ) as http_client:
                    resp = await http_client.get(token_endpoint)
                    # Token endpoint usually requires POST, so a 4xx is expected
                    steps.append({
                        "step": "token_endpoint_check",
                        "status": "passed",
                        "detail": f"Token endpoint reachable (HTTP {resp.status_code})",
                    })
            except Exception as exc:
                steps.append({
                    "step": "token_endpoint_check",
                    "status": "failed",
                    "detail": f"Token endpoint unreachable: {exc}",
                })
        else:
            steps.append({
                "step": "token_endpoint_check",
                "status": "skipped",
                "detail": "No token_endpoint in discovery document",
            })

        all_passed = all(s["status"] != "failed" for s in steps)
        return {
            "success": all_passed,
            "steps": steps,
            "discovery_doc": discovery,
        }

    # ── Encryption helpers ────────────────────────────────────────────────

    @staticmethod
    def mask_secret(value: Optional[str]) -> Optional[str]:
        """Return a masked version of an encrypted secret for listing.

        For display: shows the last 4 characters of the base64 encoding.
        """
        if not value:
            return None
        return f"****{value[-4:]}" if len(value) > 4 else "****"

    @staticmethod
    def decrypt_secret(encrypted: Optional[str]) -> Optional[str]:
        """Decrypt an encrypted client secret. Returns ``None`` if input is ``None``."""
        if not encrypted:
            return None
        return get_vault().decrypt(encrypted)


# ── Module-level helpers ───────────────────────────────────────────────────


def _validate_scope(scope: str) -> None:
    if scope not in _VALID_SCOPES:
        raise OIDCConfigError(
            f"Invalid provider_scope '{scope}'. Must be one of: {_VALID_SCOPES}"
        )


def _validate_provider_type(provider_type: str) -> None:
    if provider_type not in _VALID_PROVIDER_TYPES:
        raise OIDCConfigError(
            f"Invalid provider_type '{provider_type}'. "
            f"Must be one of: {_VALID_PROVIDER_TYPES}"
        )


async def _validate_oidc_discovery(issuer_url: str) -> dict:
    """Fetch OIDC Discovery and return it. Raises on any error."""
    return await _fetch_discovery(issuer_url)


async def _fetch_discovery(issuer_url: str) -> dict:
    """Fetch .well-known/openid-configuration from *issuer_url*."""
    discovery_url = f"{issuer_url}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(
            timeout=15.0, verify=get_ssl_context()
        ) as http_client:
            resp = await http_client.get(discovery_url)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError as exc:
        raise OIDCConfigError(
            f"Cannot reach issuer at {issuer_url}: connection refused"
        ) from exc
    except httpx.TimeoutException as exc:
        raise OIDCConfigError(
            f"Timeout connecting to issuer at {issuer_url}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise OIDCConfigError(
            f"Discovery endpoint returned HTTP {exc.response.status_code} "
            f"for {issuer_url}"
        ) from exc
    except Exception as exc:
        raise OIDCConfigError(
            f"Failed to fetch discovery document from {issuer_url}: {exc}"
        ) from exc


def _config_diff_fields(
    _old: Optional[IdentityProviderConfig],
    new: IdentityProviderConfig,
) -> dict:
    """Build a snapshot of the config fields (masking sensitive values)."""
    return {
        "provider_scope": new.provider_scope,
        "provider_type": new.provider_type,
        "display_name": new.display_name,
        "issuer_url": new.issuer_url,
        "client_id": new.client_id,
        "encrypted_client_secret": OIDCConfigService.mask_secret(
            new.encrypted_client_secret
        ),
        "scopes": new.scopes,
        "claim_mappings": new.claim_mappings,
        "is_enabled": new.is_enabled,
    }


def _write_audit(
    db: AsyncSession,
    *,
    config_id: uuid.UUID,
    changed_by: str,
    change_type: str,
    changed_fields: list[str],
    previous_values: Optional[dict] = None,
) -> None:
    """Write an immutable audit entry (not flushed — caller flushes)."""
    audit = IdentityProviderConfigAudit(
        id=uuid.uuid4(),
        config_id=config_id,
        changed_by=changed_by,
        change_type=change_type,
        changed_fields=changed_fields,
        previous_values=previous_values,
    )
    db.add(audit)


async def _update_setup_state(
    db: AsyncSession, scope: str, *, configured: bool
) -> None:
    """Update the single-row ``IdentityProviderSetupState`` sentinel."""
    result = await db.execute(select(IdentityProviderSetupState))
    state = result.scalar_one_or_none()
    if state is None:
        state = IdentityProviderSetupState(id=uuid.uuid4())
        db.add(state)

    if scope == "user":
        state.user_provider_configured = configured
    elif scope == "agent":
        state.agent_provider_configured = configured
    await db.flush()
