"""Identity provider setup — Keycloak realm and client provisioning.

Ports the Keycloak provisioning logic from ``scripts/init-local-dev.py``
and ``IdentityBootstrapService.provision_bundled_keycloak()`` into an
idempotent setup sub-command.  Also persists ``IdentityProviderConfig``
rows so the app can discover the provider without running the setup wizard.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from app.core.config import get_settings
from app.services.identity.keycloak_admin_client import KeycloakAdminClient, KeycloakAdminError

logger = logging.getLogger("setup.identity")

# Default values for local dev
_DEFAULT_KEYCLOAK_URL = "http://localhost:8082"
_DEFAULT_REALM = "parthenon"
_DEFAULT_CLIENT_ID = "parthenon-api"
_DEFAULT_ADMIN_USER = "admin"
_DEFAULT_ADMIN_PASSWORD = "admin"
_DEFAULT_INITIAL_ADMIN_PASSWORD = "admin"


async def run_identity_setup(args: Any) -> int:
    """Provision Keycloak realms and clients.

    Idempotent — checks existence before creating any resource.
    After Keycloak provisioning, persists IdentityProviderConfig rows
    to the database so the app discovers the provider automatically.
    """
    keycloak_url = args.keycloak_url or os.environ.get("KEYCLOAK_URL", _DEFAULT_KEYCLOAK_URL)
    realm = args.realm or os.environ.get("KEYCLOAK_REALM", _DEFAULT_REALM)
    client_id = args.client_id or os.environ.get("KEYCLOAK_CLIENT_ID", _DEFAULT_CLIENT_ID)
    admin_user = args.admin_user or os.environ.get("KEYCLOAK_ADMIN_USER", _DEFAULT_ADMIN_USER)
    admin_password = (
        args.admin_password
        or os.environ.get("KEYCLOAK_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)
    )
    initial_admin_password = (
        args.initial_admin_password
        or os.environ.get("INITIAL_ADMIN_PASSWORD", _DEFAULT_INITIAL_ADMIN_PASSWORD)
    )
    is_external = getattr(args, "external", False)

    results: list[dict[str, str]] = []

    if is_external:
        results.append(_r("external_oidc", "skipped", "External OIDC registration — use setup-identity --external"))
    else:
        report = await _setup_bundled_keycloak(
            keycloak_url, realm, client_id, admin_user, admin_password, initial_admin_password
        )
        results.extend(report)

        # Persist IdentityProviderConfig to DB if Keycloak provisioning succeeded
        has_errors = any(r["status"] == "error" for r in report)
        if not has_errors:
            oidc_report = await _persist_oidc_config(keycloak_url, realm, client_id)
            results.extend(oidc_report)

    if args.output == "json":
        print(json.dumps({"status": "ok", "steps": results}, indent=2))
    else:
        for r in results:
            icon = "✓" if r["status"] == "created" else ("●" if r["status"] == "exists" else "✗")
            print(f"  {icon} {r['step']}: {r['status']} {r.get('detail', '')}")

    failed = [r for r in results if r["status"] == "error"]
    return 1 if failed else 0


async def _setup_bundled_keycloak(
    keycloak_url: str,
    realm_name: str,
    client_id: str,
    admin_user: str,
    admin_password: str,
    initial_admin_password: str,
) -> list[dict[str, str]]:
    """Provision bundled Keycloak — realm, clients, admin user, agent realm."""
    report: list[dict[str, str]] = []
    keycloak_url = keycloak_url.rstrip("/")

    # ── Authenticate ──────────────────────────────────────────────────
    kc = KeycloakAdminClient(keycloak_url)
    try:
        token = await kc.authenticate(admin_user, admin_password)
        report.append(_r("authenticate", "created", f"Connected to {keycloak_url}"))
    except KeycloakAdminError as exc:
        report.append(_r("authenticate", "error", str(exc)))
        return report

    # ── User (human) realm ─────────────────────────────────────────────
    realm_exists = await kc.realm_exists(token, realm_name)
    if realm_exists:
        report.append(_r("user_realm", "exists", f"Realm '{realm_name}' already exists"))
    else:
        await kc.create_realm(token, realm_name, display_name="Parthenon")
        report.append(_r("user_realm", "created", f"Created realm '{realm_name}'"))

    # ── User realm OIDC clients ────────────────────────────────────────
    # API client (confidential) — capture the returned secret for DB config
    api_exists = await kc.client_exists(token, realm_name, client_id)
    api_secret = None
    if api_exists:
        report.append(_r("api_client", "exists", f"Client '{client_id}' already exists in '{realm_name}'"))
    else:
        api_secret = await kc.create_oidc_client(token, realm_name, client_id, public_client=False)
        secret_detail = ""
        if api_secret and api_secret.value:
            secret_detail = " (secret captured)"
        report.append(_r("api_client", "created", f"Created confidential client '{client_id}' in '{realm_name}'{secret_detail}"))

    # UI client (public)
    ui_client_id = f"{client_id}-ui"
    ui_exists = await kc.client_exists(token, realm_name, ui_client_id)
    if ui_exists:
        report.append(_r("ui_client", "exists", f"Client '{ui_client_id}' already exists in '{realm_name}'"))
    else:
        await kc.create_oidc_client(
            token,
            realm_name,
            ui_client_id,
            redirect_uris=[
                "http://localhost:5173/*",
                "http://localhost:5174/*",
                "http://localhost:4173/*",
                "http://localhost:3000/*",
            ],
            public_client=True,
        )
        report.append(_r("ui_client", "created", f"Created public client '{ui_client_id}' in '{realm_name}'"))

    # ── Admin user ──────────────────────────────────────────────────────
    user_exists = await kc.get_user_by_username(token, realm_name, "admin")
    if user_exists:
        report.append(_r("admin_user", "exists", "Admin user 'admin' already exists"))
    else:
        await kc.create_user(token, realm_name, "admin", initial_admin_password, roles=["admin"])
        report.append(_r("admin_user", "created", "Created admin user 'admin'"))

    # ── Agent realm ─────────────────────────────────────────────────────
    _agent_realm = "ai_agents"
    agent_realm_exists = await kc.realm_exists(token, _agent_realm)
    if agent_realm_exists:
        report.append(_r("agent_realm", "exists", f"Agent realm '{_agent_realm}' already exists"))
    else:
        await kc.create_realm(token, _agent_realm, display_name="Parthenon Agent Realm")
        report.append(_r("agent_realm", "created", f"Created agent realm '{_agent_realm}'"))

    # ── Agent realm OIDC client ────────────────────────────────────────
    agent_client_id = client_id  # Match init-local-dev.py behavior
    agent_client_exists = await kc.client_exists(token, _agent_realm, agent_client_id)
    if agent_client_exists:
        report.append(_r("agent_client", "exists", f"Client '{agent_client_id}' already exists in '{_agent_realm}'"))
    else:
        await kc.create_oidc_client(
            token,
            _agent_realm,
            agent_client_id,
            redirect_uris=[
                "http://localhost:8000/api/v1/agents/oauth/callback",
                "http://localhost:5173/agents/identities/oauth/callback",
                "http://localhost:4173/agents/identities/oauth/callback",
                "http://localhost:3000/agents/identities/oauth/callback",
            ],
            public_client=True,
        )
        report.append(_r("agent_client", "created", f"Created public client '{agent_client_id}' in '{_agent_realm}'"))

    return report


async def _persist_oidc_config(
    keycloak_url: str, realm_name: str, client_id: str
) -> list[dict[str, str]]:
    """Create IdentityProviderConfig records in the database for user and agent scopes."""
    report: list[dict[str, str]] = []
    issuer_url = f"{keycloak_url.rstrip('/')}/realms/{realm_name}"
    ui_client_id = f"{client_id}-ui"

    try:
        from app.db.models.identity_provider_config import IdentityProviderConfig
        from app.db.models.identity_provider_setup_state import IdentityProviderSetupState
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from datetime import datetime, timezone

        settings = get_settings()
        engine = create_async_engine(str(settings.database_url))
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as db:
            # Check if user provider already exists
            existing = await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.provider_scope == "user"
                )
            )
            user_config = existing.scalar_one_or_none()

            if user_config is None:
                user_config = IdentityProviderConfig(
                    id=uuid.uuid4(),
                    provider_scope="user",
                    provider_type="keycloak",
                    display_name=f"Keycloak - {realm_name}",
                    issuer_url=issuer_url,
                    client_id=client_id,
                    ui_client_id=ui_client_id,
                    encrypted_client_secret=None,
                    scopes="openid profile email",
                    is_enabled=True,
                )
                db.add(user_config)
                report.append(_r("db_user_provider", "created", f"User IDP config → {issuer_url}"))
            else:
                # Update existing to ensure URLs are correct
                user_config.issuer_url = issuer_url
                user_config.client_id = client_id
                user_config.ui_client_id = ui_client_id
                user_config.provider_type = "keycloak"
                user_config.is_enabled = True
                report.append(_r("db_user_provider", "exists", f"User IDP config updated → {issuer_url}"))

            # Check if agent provider already exists
            agent_issuer_url = f"{keycloak_url.rstrip('/')}/realms/ai_agents"
            existing_agent = await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.provider_scope == "agent"
                )
            )
            agent_config = existing_agent.scalar_one_or_none()

            if agent_config is None:
                agent_config = IdentityProviderConfig(
                    id=uuid.uuid4(),
                    provider_scope="agent",
                    provider_type="keycloak",
                    display_name=f"Keycloak - ai_agents",
                    issuer_url=agent_issuer_url,
                    client_id=client_id,
                    ui_client_id=None,
                    encrypted_client_secret=None,
                    scopes="openid profile email",
                    is_enabled=True,
                )
                db.add(agent_config)
                report.append(_r("db_agent_provider", "created", f"Agent IDP config → {agent_issuer_url}"))
            else:
                agent_config.issuer_url = agent_issuer_url
                agent_config.client_id = client_id
                agent_config.provider_type = "keycloak"
                agent_config.is_enabled = True
                report.append(_r("db_agent_provider", "exists", f"Agent IDP config updated → {agent_issuer_url}"))

            # Mark setup as complete
            state_result = await db.execute(select(IdentityProviderSetupState))
            state_row = state_result.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if state_row is None:
                state_row = IdentityProviderSetupState(
                    id=uuid.uuid4(),
                    is_setup_complete=True,
                    user_provider_configured=True,
                    completed_at=now,
                )
                db.add(state_row)
            else:
                state_row.is_setup_complete = True
                state_row.user_provider_configured = True
                state_row.completed_at = now

            await db.commit()

        await engine.dispose()
        report.append(_r("db_setup_state", "created", "Setup marked as complete"))

    except Exception as exc:
        logger.exception("Failed to persist OIDC config to database")
        report.append(_r("db_oidc_config", "error", str(exc)))

    return report


def _r(step: str, status: str, detail: str = "") -> dict[str, str]:
    return {"step": step, "status": status, "detail": detail}
