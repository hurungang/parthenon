"""Identity provider setup — Keycloak realm and client provisioning.

Ports the Keycloak provisioning logic from ``scripts/init-local-dev.py``
and ``IdentityBootstrapService.provision_bundled_keycloak()`` into an
idempotent setup sub-command.
"""
from __future__ import annotations

import json
import logging
import os
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
        results.append(_result("external_oidc", "skipped", "External OIDC registration — use setup-identity --external"))
    else:
        report = await _setup_bundled_keycloak(
            keycloak_url, realm, client_id, admin_user, admin_password, initial_admin_password
        )
        results.extend(report)

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
        report.append(_result("authenticate", "created", f"Connected to {keycloak_url}"))
    except KeycloakAdminError as exc:
        report.append(_result("authenticate", "error", str(exc)))
        return report

    # ── User (human) realm ─────────────────────────────────────────────
    realm_exists = await kc.realm_exists(token, realm_name)
    if realm_exists:
        report.append(_result("user_realm", "exists", f"Realm '{realm_name}' already exists"))
    else:
        await kc.create_realm(token, realm_name, display_name="Parthenon")
        report.append(_result("user_realm", "created", f"Created realm '{realm_name}'"))

    # ── User realm OIDC clients ────────────────────────────────────────
    # API client (confidential)
    api_exists = await kc.client_exists(token, realm_name, client_id)
    if api_exists:
        report.append(_result("api_client", "exists", f"Client '{client_id}' already exists in '{realm_name}'"))
    else:
        await kc.create_oidc_client(token, realm_name, client_id, public_client=False)
        report.append(_result("api_client", "created", f"Created confidential client '{client_id}' in '{realm_name}'"))

    # UI client (public)
    ui_client_id = f"{client_id}-ui"
    ui_exists = await kc.client_exists(token, realm_name, ui_client_id)
    if ui_exists:
        report.append(_result("ui_client", "exists", f"Client '{ui_client_id}' already exists in '{realm_name}'"))
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
        report.append(_result("ui_client", "created", f"Created public client '{ui_client_id}' in '{realm_name}'"))

    # ── Admin user ──────────────────────────────────────────────────────
    user_exists = await kc.get_user_by_username(token, realm_name, "admin")
    if user_exists:
        report.append(_result("admin_user", "exists", "Admin user 'admin' already exists"))
    else:
        await kc.create_user(token, realm_name, "admin", initial_admin_password, roles=["admin"])
        report.append(_result("admin_user", "created", "Created admin user 'admin'"))

    # ── Agent realm ─────────────────────────────────────────────────────
    _agent_realm = "ai_agents"
    agent_realm_exists = await kc.realm_exists(token, _agent_realm)
    if agent_realm_exists:
        report.append(_result("agent_realm", "exists", f"Agent realm '{_agent_realm}' already exists"))
    else:
        await kc.create_realm(token, _agent_realm, display_name="Parthenon Agent Realm")
        report.append(_result("agent_realm", "created", f"Created agent realm '{_agent_realm}'"))

    # ── Agent realm OIDC client ────────────────────────────────────────
    agent_client_id = client_id  # Match init-local-dev.py behavior
    agent_client_exists = await kc.client_exists(token, _agent_realm, agent_client_id)
    if agent_client_exists:
        report.append(_result("agent_client", "exists", f"Client '{agent_client_id}' already exists in '{_agent_realm}'"))
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
        report.append(_result("agent_client", "created", f"Created public client '{agent_client_id}' in '{_agent_realm}'"))

    return report


def _result(step: str, status: str, detail: str = "") -> dict[str, str]:
    return {"step": step, "status": status, "detail": detail}
