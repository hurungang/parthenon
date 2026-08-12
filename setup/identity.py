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

    # ── mcp_role user profile attribute (both realms) ─────────────────
    report.extend(await _register_mcp_role_attribute(kc, token, keycloak_url, realm_name))
    report.extend(await _register_mcp_role_attribute(kc, token, keycloak_url, _agent_realm))

    # ── mcp_role claim mappers ───────────────────────────────────────
    report.extend(await _add_mcp_role_claim_mapper(kc, token, keycloak_url, _agent_realm, agent_client_id))
    report.extend(await _add_mcp_role_claim_mapper(kc, token, keycloak_url, realm_name, client_id))
    report.extend(await _add_mcp_role_claim_mapper(kc, token, keycloak_url, realm_name, ui_client_id))

    # ── offline_access scope for agent client ────────────────────────
    report.extend(await _enable_offline_access_scope(kc, token, keycloak_url, _agent_realm, agent_client_id))

    # ── Realm roles for MCP demo app ─────────────────────────────────
    report.extend(await _ensure_realm_role(kc, token, keycloak_url, _agent_realm, "demo_agent", "Required mcp_role for helloAgent MCP tool"))
    report.extend(await _ensure_realm_role(kc, token, keycloak_url, realm_name, "demo_user", "Required mcp_role for helloUser MCP tool"))

    # ── Test agent identities (ai_agents realm) ──────────────────────
    _TEST_AGENTS = [
        {"username": "test_agent", "password": "test_agent", "roles": ["demo_agent"], "mcp_role": "demo_agent"},
        {"username": "test_agent_2", "password": "test_agent_2", "roles": [], "mcp_role": None},
    ]
    for agent_info in _TEST_AGENTS:
        report.extend(await _create_agent_identity(kc, token, keycloak_url, _agent_realm, agent_info))

    # ── Test user (parthenon realm) ──────────────────────────────────
    report.extend(await _create_test_user(kc, token, keycloak_url, realm_name, {"username": "testuser", "password": "testuser", "roles": [], "mcp_role": None}))

    # ── Admin mcp_role assignment ────────────────────────────────────
    report.extend(await _sync_user_roles(kc, token, keycloak_url, realm_name, "admin", ["admin", "demo_user", "offline_access"]))
    report.extend(await _set_user_attribute(kc, token, keycloak_url, realm_name, "admin", "mcp_role", "demo_user"))

    # ── mcp-demo-app confidential client (ai_agents realm) ───────────
    report.extend(await _ensure_mcp_demo_app_client(kc, token, keycloak_url, _agent_realm))

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


async def _register_mcp_role_attribute(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
) -> list[dict[str, str]]:
    """Register mcp_role in user profile attributes (idempotent)."""
    import httpx

    base = f"{keycloak_url}/admin/realms/{realm_name}"
    h = {"Authorization": f"Bearer {token.access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base}/users/profile", headers=h)
        profile = resp.json() if resp.status_code == 200 else {"attributes": []}
        existing_attrs = {a.get("name") for a in profile.get("attributes", [])}
        if "mcp_role" in existing_attrs:
            return [_r("mcp_role_attr", "exists", f"mcp_role attribute already in profile for '{realm_name}'")]

        profile.setdefault("attributes", []).append({
            "name": "mcp_role",
            "displayName": "MCP Role",
            "permissions": {"view": ["admin", "user"], "edit": ["admin"]},
            "multivalued": False,
            "validations": {},
            "annotations": {},
            "group": None,
        })
        resp = await client.put(f"{base}/users/profile", headers={**h, "Content-Type": "application/json"}, json=profile)
        if resp.status_code in (200, 204):
            return [_r("mcp_role_attr", "created", f"Registered mcp_role attribute in '{realm_name}'")]
        return [_r("mcp_role_attr", "error", f"HTTP {resp.status_code} registering mcp_role in '{realm_name}'")]


async def _add_mcp_role_claim_mapper(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    client_id: str,
) -> list[dict[str, str]]:
    """Add mcp_role claim mapper to an OIDC client (idempotent)."""
    import httpx

    base = f"{keycloak_url}/admin/realms/{realm_name}"
    h = {"Authorization": f"Bearer {token.access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base}/clients", params={"clientId": client_id}, headers=h)
        clients = resp.json() if resp.status_code == 200 else []
        if not clients:
            return [_r("mcp_role_mapper", "error", f"Client '{client_id}' not found in '{realm_name}'")]
        client_uuid = clients[0]["id"]

        resp = await client.get(f"{base}/clients/{client_uuid}/protocol-mappers/models", headers=h)
        mappers = resp.json() if resp.status_code == 200 else []
        if any(m.get("name") == "mcp_role" for m in mappers):
            return [_r("mcp_role_mapper", "exists", f"mcp_role mapper already on '{client_id}' in '{realm_name}'")]

        mapper = {
            "name": "mcp_role",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {
                "claim.name": "mcp_role",
                "user.attribute": "mcp_role",
                "access.token.claim": "true",
                "id.token.claim": "true",
                "userinfo.token.claim": "true",
                "jsonType.label": "String",
            },
        }
        resp = await client.post(
            f"{base}/clients/{client_uuid}/protocol-mappers/models",
            headers=h, json=mapper,
        )
        if resp.status_code in (201, 204):
            return [_r("mcp_role_mapper", "created", f"Added mcp_role mapper to '{client_id}' in '{realm_name}'")]
        return [_r("mcp_role_mapper", "error", f"HTTP {resp.status_code} adding mcp_role mapper")]


async def _enable_offline_access_scope(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    client_id: str,
) -> list[dict[str, str]]:
    """Enable offline_access scope for a client (idempotent)."""
    import httpx

    base = f"{keycloak_url}/admin/realms/{realm_name}"
    h = {"Authorization": f"Bearer {token.access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base}/clients", params={"clientId": client_id}, headers=h)
        clients = resp.json() if resp.status_code == 200 else []
        if not clients:
            return [_r("offline_access", "error", f"Client '{client_id}' not found in '{realm_name}'")]
        client_uuid = clients[0]["id"]

        resp = await client.get(f"{base}/client-scopes", headers=h)
        scopes = resp.json() if resp.status_code == 200 else []
        offline_scope = next((s for s in scopes if s.get("name") == "offline_access"), None)
        if not offline_scope:
            return [_r("offline_access", "error", f"'offline_access' scope not found in '{realm_name}'")]

        resp = await client.get(
            f"{base}/clients/{client_uuid}/optional-client-scopes",
            headers=h,
        )
        assigned = resp.json() if resp.status_code == 200 else []
        if any(s.get("id") == offline_scope["id"] for s in assigned):
            return [_r("offline_access", "exists", f"offline_access already assigned to '{client_id}'")]

        resp = await client.put(
            f"{base}/clients/{client_uuid}/optional-client-scopes/{offline_scope['id']}",
            headers=h,
        )
        if resp.status_code in (204, 200):
            return [_r("offline_access", "created", f"Enabled offline_access for '{client_id}' in '{realm_name}'")]
        return [_r("offline_access", "error", f"HTTP {resp.status_code} enabling offline_access")]


async def _ensure_realm_role(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    role_name: str,
    description: str,
) -> list[dict[str, str]]:
    """Ensure a realm-level role exists (idempotent)."""
    import httpx

    base_url = f"{keycloak_url}/admin/realms/{realm_name}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        h = {"Authorization": f"Bearer {token.access_token}"}
        resp = await client.get(f"{base_url}/roles/{role_name}", headers=h)
    if resp.status_code == 200:
        return [_r("realm_role", "exists", f"Role '{role_name}' already in '{realm_name}'")]

    create_url = f"{keycloak_url}/admin/realms/{realm_name}/roles"
    async with httpx.AsyncClient(timeout=10.0) as client:
        h = {"Authorization": f"Bearer {token.access_token}"}
        resp = await client.post(
            create_url,
            json={"name": role_name, "description": description},
            headers=h,
        )
    if resp.status_code == 201:
        return [_r("realm_role", "created", f"Created role '{role_name}' in '{realm_name}'")]
    elif resp.status_code == 409:
        return [_r("realm_role", "exists", f"Role '{role_name}' already in '{realm_name}' (409)")]
    return [_r("realm_role", "error", f"HTTP {resp.status_code} creating role '{role_name}'")]


async def _create_agent_identity(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    agent_info: dict,
) -> list[dict[str, str]]:
    """Create a test agent identity in Keycloak and the AgentIdentity DB record."""
    username = agent_info["username"]
    report: list[dict[str, str]] = []

    try:
        await kc.create_user(token, realm_name, username, agent_info["password"], roles=agent_info["roles"])
    except KeycloakAdminError as exc:
        report.append(_r("agent_identity", "error", f"Failed to create Keycloak user '{username}': {exc.detail}"))
        return report

    import httpx
    user_id = await kc.get_user_by_username(token, realm_name, username)
    if user_id:
        reset_url = f"{keycloak_url}/admin/realms/{realm_name}/users/{user_id}/reset-password"
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.put(
                reset_url,
                json={"type": "password", "value": agent_info["password"], "temporary": False},
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

    if agent_info.get("mcp_role"):
        report.extend(await _set_user_attribute(kc, token, keycloak_url, realm_name, username, "mcp_role", agent_info["mcp_role"]))
    else:
        report.extend(await _remove_user_attribute(kc, token, keycloak_url, realm_name, username, "mcp_role"))

    desired_roles = agent_info["roles"] + ["offline_access"]
    report.extend(await _sync_user_roles(kc, token, keycloak_url, realm_name, username, desired_roles))

    try:
        from app.core.config import get_settings as _get_settings
        _settings = _get_settings()
        from app.db.models.agents import AgentIdentity as AgentIdentityModel, AgentIdentityType, AgentIdentityStatus
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

        engine = create_async_engine(str(_settings.database_url))
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            result = await db.execute(
                select(AgentIdentityModel).where(AgentIdentityModel.name == f"{username}@{realm_name}")
            )
            existing = result.scalar_one_or_none()
            if existing:
                report.append(
                    _r("agent_identity_db", "exists",
                       f"AgentIdentity '{username}@{realm_name}' (mcp_role={agent_info.get('mcp_role')})")
                )
            else:
                identity = AgentIdentityModel(
                    name=f"{username}@{realm_name}",
                    identity_type=AgentIdentityType.realm_user,
                    realm_name=realm_name,
                    realm_username=username,
                    status=AgentIdentityStatus.active,
                )
                db.add(identity)
                await db.commit()
                report.append(_r("agent_identity_db", "created", f"AgentIdentity '{username}@{realm_name}'"))
        await engine.dispose()
    except Exception as exc:
        logger.exception("Failed to create AgentIdentity DB record for %r", username)
        report.append(_r("agent_identity_db", "error", str(exc)))

    return report


async def _create_test_user(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    user_info: dict,
) -> list[dict[str, str]]:
    """Create a test user in Keycloak (idempotent)."""
    username = user_info["username"]
    report: list[dict[str, str]] = []

    try:
        await kc.create_user(token, realm_name, username, user_info["password"], roles=user_info["roles"])
    except KeycloakAdminError as exc:
        report.append(_r("test_user", "error", f"Failed to create user '{username}': {exc.detail}"))
        return report

    import httpx
    user_id = await kc.get_user_by_username(token, realm_name, username)
    if user_id:
        reset_url = f"{keycloak_url}/admin/realms/{realm_name}/users/{user_id}/reset-password"
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.put(
                reset_url,
                json={"type": "password", "value": user_info["password"], "temporary": False},
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

    if user_info.get("mcp_role"):
        report.extend(await _set_user_attribute(kc, token, keycloak_url, realm_name, username, "mcp_role", user_info["mcp_role"]))
    else:
        report.extend(await _remove_user_attribute(kc, token, keycloak_url, realm_name, username, "mcp_role"))

    report.extend(await _sync_user_roles(kc, token, keycloak_url, realm_name, username, user_info["roles"]))
    report.append(_r("test_user", "created", f"Test user '{username}' in '{realm_name}' (mcp_role={user_info.get('mcp_role')})"))
    return report


async def _sync_user_roles(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    username: str,
    desired_roles: list[str],
) -> list[dict[str, str]]:
    """Ensure a user has the desired realm roles (additive — never removes)."""
    import httpx

    user_id = await kc.get_user_by_username(token, realm_name, username)
    if not user_id:
        return [_r("user_roles", "error", f"User '{username}' not found in '{realm_name}'")]

    base = f"{keycloak_url}/admin/realms/{realm_name}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        h = {"Authorization": f"Bearer {token.access_token}"}

        resp = await client.get(f"{base}/users/{user_id}/role-mappings/realm", headers=h)
        current_roles = resp.json() if resp.status_code == 200 else []
        current_names = {r.get("name") for r in current_roles if isinstance(r, dict)}

        to_add = set(desired_roles) - current_names
        if not to_add:
            return [_r("user_roles", "exists", f"Roles for '{username}' already correct in '{realm_name}'")]

        resp = await client.get(f"{base}/roles", headers=h)
        all_roles = resp.json() if resp.status_code == 200 else []
        role_reprs = [r for r in all_roles if r.get("name") in to_add]
        if role_reprs:
            resp = await client.post(f"{base}/users/{user_id}/role-mappings/realm", headers=h, json=role_reprs)
            if resp.status_code == 204:
                return [_r("user_roles", "created", f"Assigned roles {list(to_add)} to '{username}' in '{realm_name}'")]
    return [_r("user_roles", "error", f"Failed to sync roles for '{username}'")]


async def _set_user_attribute(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    username: str,
    attr_name: str,
    attr_value: str,
) -> list[dict[str, str]]:
    """Set a single-valued user attribute via Keycloak admin API (idempotent)."""
    import httpx

    user_id = await kc.get_user_by_username(token, realm_name, username)
    if not user_id:
        return [_r("user_attr", "error", f"User '{username}' not found in '{realm_name}'")]

    url = f"{keycloak_url}/admin/realms/{realm_name}/users/{user_id}"
    h = {"Authorization": f"Bearer {token.access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=h)
        if resp.status_code != 200:
            return [_r("user_attr", "error", f"Failed to get user '{username}'")]
        user_data = resp.json()

        current = user_data.get("attributes", {}).get(attr_name)
        if current == [attr_value]:
            return [_r("user_attr", "exists", f"Attribute {attr_name}={attr_value} already set on '{username}'")]

        if not user_data.get("email"):
            user_data["email"] = f"{username}@test.local"
        if not user_data.get("firstName"):
            user_data["firstName"] = "Test"
        if not user_data.get("lastName"):
            user_data["lastName"] = "User"

        attrs = dict(user_data.get("attributes", {}))
        attrs[attr_name] = [attr_value]
        user_data["attributes"] = attrs

        resp = await client.put(url, headers={**h, "Content-Type": "application/json"}, json=user_data)
        if resp.status_code == 204:
            return [_r("user_attr", "created", f"Set {attr_name}={attr_value} on '{username}' in '{realm_name}'")]
    return [_r("user_attr", "error", f"HTTP {resp.status_code} setting attribute for '{username}'")]


async def _remove_user_attribute(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
    username: str,
    attr_name: str,
) -> list[dict[str, str]]:
    """Remove a user attribute via Keycloak admin API (idempotent)."""
    import httpx

    user_id = await kc.get_user_by_username(token, realm_name, username)
    if not user_id:
        return [_r("user_attr", "error", f"User '{username}' not found in '{realm_name}'")]

    url = f"{keycloak_url}/admin/realms/{realm_name}/users/{user_id}"
    h = {"Authorization": f"Bearer {token.access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=h)
        if resp.status_code != 200:
            return [_r("user_attr", "error", f"Failed to get user '{username}'")]
        user_data = resp.json()

        if attr_name not in user_data.get("attributes", {}):
            return [_r("user_attr", "exists", f"Attribute {attr_name} already absent on '{username}'")]

        if not user_data.get("email"):
            user_data["email"] = f"{username}@test.local"
        if not user_data.get("firstName"):
            user_data["firstName"] = "Test"
        if not user_data.get("lastName"):
            user_data["lastName"] = "User"

        attrs = dict(user_data.get("attributes", {}))
        attrs.pop(attr_name, None)
        user_data["attributes"] = attrs

        resp = await client.put(url, headers={**h, "Content-Type": "application/json"}, json=user_data)
        if resp.status_code == 204:
            return [_r("user_attr", "created", f"Removed {attr_name} from '{username}' in '{realm_name}'")]
    return [_r("user_attr", "error", f"HTTP {resp.status_code} removing attribute from '{username}'")]


async def _ensure_mcp_demo_app_client(
    kc: KeycloakAdminClient,
    token: Any,
    keycloak_url: str,
    realm_name: str,
) -> list[dict[str, str]]:
    """Create the mcp-demo-app confidential client in the agent realm (idempotent)."""
    import httpx

    client_id = "mcp-demo-app"
    base = f"{keycloak_url}/admin/realms/{realm_name}"
    h = {"Authorization": f"Bearer {token.access_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base}/clients", params={"clientId": client_id}, headers=h)
        existing = resp.json() if resp.status_code == 200 else []
        if existing:
            return [_r("mcp_demo_app_client", "exists", f"Client '{client_id}' already in '{realm_name}'")]

        client_config = {
            "clientId": client_id,
            "name": "MCP Demo App",
            "description": "Demo MCP server for agent identity propagation",
            "enabled": True,
            "serviceAccountsEnabled": True,
            "clientAuthenticatorType": "client-secret",
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "publicClient": False,
            "protocol": "openid-connect",
        }
        resp = await client.post(f"{base}/clients", headers=h, json=client_config)
        if resp.status_code in (201, 200):
            return [_r("mcp_demo_app_client", "created", f"Created client '{client_id}' in '{realm_name}'")]
        return [_r("mcp_demo_app_client", "error", f"HTTP {resp.status_code} creating '{client_id}' in '{realm_name}'")]


def _r(step: str, status: str, detail: str = "") -> dict[str, str]:
    return {"step": step, "status": status, "detail": detail}
