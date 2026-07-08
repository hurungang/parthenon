"""Identity YAML Migration — one-time migration from config/identity.yaml to database.

Reads the legacy ``config/identity.yaml`` file on upgrade and creates
``IdentityProviderConfig`` database records with the appropriate fields.
Runs once; skips on subsequent starts when DB configs already exist.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity_provider_config import IdentityProviderConfig
from app.db.models.identity_provider_setup_state import IdentityProviderSetupState
from app.services.oidc_config_service import OIDCConfigService

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_YAML_PATH = _REPO_ROOT / "config" / "identity.yaml"


class IdentityYamlMigration:
    """Reads config/identity.yaml and creates IdentityProviderConfig DB records.

    Safe to run on every startup — it checks for existing DB configs first.
    """

    def __init__(self, yaml_path: Optional[Path] = None) -> None:
        self._yaml_path = yaml_path or Path(
            os.environ.get("IDENTITY_YAML_PATH", str(_DEFAULT_YAML_PATH))
        )

    async def run(self, db: AsyncSession) -> bool:
        """Run the migration if needed.

        Returns:
            ``True`` if migration ran and wrote data; ``False`` if skipped.
        """
        # Skip if the YAML file doesn't exist
        if not self._yaml_path.exists():
            logger.info("IdentityYamlMigration: %s not found — nothing to migrate", self._yaml_path)
            return False

        # Skip if DB already has both user and agent provider configs
        user_exists = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.provider_scope == "user"
            )
        )
        agent_exists = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.provider_scope == "agent"
            )
        )
        if user_exists.scalar_one_or_none() is not None and agent_exists.scalar_one_or_none() is not None:
            logger.info(
                "IdentityYamlMigration: DB already has both user and agent provider configs — skipping"
            )
            return False

        # Read the YAML file
        try:
            data = self._read_yaml()
        except Exception as exc:
            logger.warning("IdentityYamlMigration: failed to parse %s: %s", self._yaml_path, exc)
            return False

        if not data:
            logger.info("IdentityYamlMigration: YAML file is empty or missing key fields")
            return False

        # Determine old provider type and map to new enum
        old_provider_type = data.get("provider_type", "")
        new_provider_type = self._map_provider_type(old_provider_type)

        # Extract fields
        issuer_url = data.get("oidc_provider_url", data.get("issuer_url", ""))
        client_id = data.get("client_id", "")
        client_secret = data.get("client_secret", "")
        realm_name = data.get("realm_name", "")
        scopes = data.get("scopes", "openid profile email")
        is_setup_complete = data.get("setup_complete", data.get("is_setup_complete", False))

        if not issuer_url:
            logger.warning("IdentityYamlMigration: no oidc_provider_url/issuer_url in YAML")
            return False

        display_name = self._build_display_name(new_provider_type, realm_name)
        config_service = OIDCConfigService()
        any_created = False
        agent_created = False

        # Create user provider if it doesn't exist
        if user_exists.scalar_one_or_none() is None:
            try:
                await config_service.create_provider(
                    db,
                    provider_scope="user",
                    provider_type=new_provider_type,
                    display_name=display_name,
                    issuer_url=issuer_url.rstrip("/"),
                    client_id=client_id or "migrated",
                    client_secret=client_secret or None,
                    scopes=scopes,
                    is_enabled=True,
                    changed_by="identity_yaml_migration",
                )
                any_created = True
            except Exception as exc:
                logger.warning("IdentityYamlMigration: failed to create user provider: %s", exc)

        # Create agent provider for bundled Keycloak (agent realm 'ai_agents')
        if agent_exists.scalar_one_or_none() is None and old_provider_type == "keycloak_bundled":
            agent_realm = data.get("agent_realm_name", "ai_agents")
            agent_issuer = issuer_url.rstrip("/").rstrip("/" + realm_name) + "/" + agent_realm
            try:
                await config_service.create_provider(
                    db,
                    provider_scope="agent",
                    provider_type="keycloak",
                    display_name=f"Migrated keycloak - {agent_realm}",
                    issuer_url=agent_issuer,
                    client_id=client_id or "parthenon-api",
                    client_secret=client_secret or None,
                    scopes=scopes,
                    is_enabled=True,
                    changed_by="identity_yaml_migration",
                )
                any_created = True
                agent_created = True
            except Exception as exc:
                logger.warning(
                    "IdentityYamlMigration: failed to create agent provider: %s", exc
                )

        if not any_created:
            return False

        # Update setup state
        try:
            from app.db.models.identity_provider_setup_state import IdentityProviderSetupState
            state_result = await db.execute(select(IdentityProviderSetupState))
            state_row = state_result.scalar_one_or_none()
            if state_row is None:
                state_row = IdentityProviderSetupState(
                    is_setup_complete=bool(is_setup_complete),
                    user_provider_configured=user_exists.scalar_one_or_none() is not None,
                    agent_provider_configured=agent_created,
                    completed_at=datetime.now(timezone.utc) if is_setup_complete else None,
                )
                db.add(state_row)
            else:
                if is_setup_complete and not state_row.is_setup_complete:
                    state_row.is_setup_complete = True
                    state_row.completed_at = datetime.now(timezone.utc)
                if user_exists.scalar_one_or_none() is not None:
                    state_row.user_provider_configured = True
                if agent_created:
                    state_row.agent_provider_configured = True

            logger.info(
                "IdentityYamlMigration: migrated config from %s — user_provider=%s agent_provider=%s issuer=%s",
                self._yaml_path, new_provider_type, agent_created, issuer_url,
            )
            return True
        except Exception as exc:
            logger.error("IdentityYamlMigration: failed to write to DB: %s", exc)
            return False

    # ── Internal helpers ──────────────────────────────────────────────────

    def _read_yaml(self) -> dict:
        """Read and parse the identity.yaml file."""
        with open(self._yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning("IdentityYamlMigration: YAML root is not a dict")
            return {}
        return data

    @staticmethod
    def _map_provider_type(old: str) -> str:
        """Map old provider_type values to new enum values."""
        mapping = {
            "keycloak_bundled": "keycloak",
            "keycloak_external": "keycloak",
            "keycloak": "keycloak",
            "azure_entraid": "azure_entraid",
        }
        return mapping.get(old, "oidc_generic")

    @staticmethod
    def _build_display_name(provider_type: str, realm_name: str) -> str:
        """Build a human-readable display name from provider info."""
        if realm_name:
            return f"Migrated {provider_type} - {realm_name}"
        return f"Migrated {provider_type}"
