"""
⚠ DEPRECATED — use ``python -m setup.main dev`` instead.

This script will be removed in a future release.
The new setup CLI provides the same functionality with idempotency
guarantees, structured output, and JSON output for scripting.

See: setup/README.md
"""

"""Local development environment initialization script.

Idempotent setup script that ensures:
1. Keycloak human user realm is created (`parthenon`)
2. OIDC clients are configured in human user realm
3. Keycloak agent realm is created (`ai_agents`)
4. OIDC client is configured in agent realm
5. Default admin user exists with consistent UUID
6. Platform database is seeded with system roles
7. Admin user has system_admin role assigned

Safe to run multiple times - will skip steps that are already complete.
"""
import asyncio
import io
import logging
import os
import sys
from pathlib import Path

# Fix Unicode print on Windows terminals
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.yaml_config import load_identity_yaml
from app.db.models.platform_user import PlatformUser
from app.db.models.identity import Role
from app.db.models.user_role import UserRole
from app.db.models.policy_statement import PolicyStatement, PolicyEffect
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource
from app.services.identity.keycloak_admin_client import KeycloakAdminClient, KeycloakAdminError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class InitializationError(Exception):
    """Raised when initialization fails."""
    pass


class LocalDevInitializer:
    """Handles local development environment initialization."""
    
    # Default configuration for local dev
    KEYCLOAK_BASE_URL = "http://localhost:8082"
    KEYCLOAK_ADMIN_USER = "admin"
    KEYCLOAK_ADMIN_PASSWORD = "admin"  # Default Keycloak admin password
    
    # Human user realm
    REALM_NAME = "parthenon"
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "admin"
    ADMIN_EMAIL = "admin@parthenon.local"
    
    # Agent realm
    AGENT_REALM_NAME = "ai_agents"
    
    def __init__(self):
        self.settings = get_settings()
        self.kc_client = KeycloakAdminClient(self.KEYCLOAK_BASE_URL)
        self.admin_token = None
        
    async def initialize(self):
        """Run full initialization sequence."""
        print("=" * 80)
        print("PARTHENON LOCAL DEVELOPMENT INITIALIZATION")
        print("=" * 80)
        print()
        
        try:
            # Step 1: Authenticate with Keycloak
            await self._authenticate_keycloak()
            
            # Step 2: Ensure realm exists
            await self._ensure_realm()
            
            # Step 3: Ensure OIDC clients exist
            await self._ensure_clients()
            
            # Step 4: Ensure agent realm exists
            await self._ensure_agent_realm()
            
            # Step 5: Ensure agent realm clients exist
            await self._ensure_agent_clients()

            # Step 5b: Ensure test agent identities exist
            await self._ensure_test_agent_identities()

            # Step 6: Ensure admin user exists in Keycloak
            admin_user_id = await self._ensure_admin_user_in_keycloak()
            
            # Step 7: Initialize database (roles, policies)
            await self._initialize_database()
            
            # Step 8: Ensure admin user in platform_users with correct sub
            await self._ensure_admin_in_platform_users(admin_user_id)
            
            # Step 9: Assign system_admin role to admin user
            await self._assign_admin_role(admin_user_id)
            
            print()
            print("=" * 80)
            print("✓ INITIALIZATION COMPLETE")
            print("=" * 80)
            print()
            print("You can now start the backend with:")
            print("  ./parthenon.ps1 start-backend")
            print()
            print("Admin credentials:")
            print(f"  Email:    {self.ADMIN_EMAIL}")
            print(f"  Password: {self.ADMIN_PASSWORD}")
            print()
            
        except KeycloakAdminError as e:
            logger.error(f"Keycloak error: {e.error_code} - {e.detail}")
            raise InitializationError(f"Keycloak setup failed: {e.detail}")
        except Exception as e:
            logger.exception("Initialization failed")
            raise InitializationError(f"Initialization failed: {e}")
    
    async def _authenticate_keycloak(self):
        """Authenticate with Keycloak admin API."""
        logger.info("Step 1: Authenticating with Keycloak...")
        
        try:
            self.admin_token = await self.kc_client.authenticate(
                self.KEYCLOAK_ADMIN_USER,
                self.KEYCLOAK_ADMIN_PASSWORD
            )
            print(f"  ✓ Authenticated with Keycloak at {self.KEYCLOAK_BASE_URL}")
        except KeycloakAdminError as e:
            if e.error_code == "keycloak_unreachable":
                print(f"  ✗ Keycloak is not running at {self.KEYCLOAK_BASE_URL}")
                print(f"    Start Keycloak with: ./parthenon.ps1 start -Services keycloak")
                raise
            else:
                print(f"  ✗ Authentication failed: {e.detail}")
                raise
    
    async def _ensure_realm(self):
        """Ensure Parthenon human user realm exists."""
        logger.info("Step 2: Ensuring human user realm exists...")
        
        exists = await self.kc_client.realm_exists(self.admin_token, self.REALM_NAME)
        if exists:
            print(f"  ✓ Human user realm '{self.REALM_NAME}' already exists")
        else:
            await self.kc_client.create_realm(
                self.admin_token,
                self.REALM_NAME,
                display_name="Parthenon"
            )
            print(f"  ✓ Created human user realm '{self.REALM_NAME}'")
    
    async def _ensure_clients(self):
        """Ensure OIDC clients are configured in human user realm."""
        logger.info("Step 3: Ensuring human user realm OIDC clients exist...")
        
        # Check if API client exists
        api_client_exists = await self.kc_client.client_exists(
            self.admin_token,
            self.REALM_NAME,
            "parthenon-api"
        )
        if api_client_exists:
            print("  ✓ API client 'parthenon-api' already exists in human realm")
        else:
            await self.kc_client.create_confidential_client(
                self.admin_token,
                self.REALM_NAME,
                "parthenon-api",
                "Parthenon API",
                ["http://localhost:8000/*"]
            )
            print("  ✓ Created API client 'parthenon-api' in human realm")
        
        # Check if UI client exists
        ui_client_exists = await self.kc_client.client_exists(
            self.admin_token,
            self.REALM_NAME,
            "parthenon-api-ui"
        )
        if ui_client_exists:
            print("  ✓ UI client 'parthenon-api-ui' already exists in human realm")
        else:
            await self.kc_client.create_public_client(
                self.admin_token,
                self.REALM_NAME,
                "parthenon-api-ui",
                "Parthenon UI",
                [
                    "http://localhost:5173/*",
                    "http://localhost:4173/*",
                    "http://localhost:3000/*"
                ]
            )
            print("  ✓ Created UI client 'parthenon-api-ui' in human realm")
    
    async def _ensure_agent_realm(self):
        """Ensure Parthenon agent realm exists."""
        logger.info("Step 4: Ensuring agent realm exists...")
        
        exists = await self.kc_client.realm_exists(self.admin_token, self.AGENT_REALM_NAME)
        if exists:
            print(f"  ✓ Agent realm '{self.AGENT_REALM_NAME}' already exists")
        else:
            await self.kc_client.create_realm(
                self.admin_token,
                self.AGENT_REALM_NAME,
                display_name="Parthenon Agent Realm"
            )
            print(f"  ✓ Created agent realm '{self.AGENT_REALM_NAME}'")
    
    async def _ensure_agent_clients(self):
        """Ensure OIDC clients are configured in agent realm."""
        logger.info("Step 5: Ensuring agent realm OIDC clients exist...")
        
        # Agent realm client must match what identity_service._agent_realm_client_id() returns
        # which reads audience from config/identity.yaml
        yaml_cfg = load_identity_yaml()
        agent_client_id = yaml_cfg.audience or "parthenon"
        print(f"  Using agent client ID '{agent_client_id}' from identity.yaml")
        
        agent_client_exists = await self.kc_client.client_exists(
            self.admin_token,
            self.AGENT_REALM_NAME,
            agent_client_id
        )
        if agent_client_exists:
            print(f"  ✓ Agent client '{agent_client_id}' already exists in agent realm")
        else:
            # Create public client for agent OAuth flow
            await self.kc_client.create_public_client(
                self.admin_token,
                self.AGENT_REALM_NAME,
                agent_client_id,
                "Parthenon Agent OAuth Client",
                [
                    "http://localhost:8000/api/v1/agents/oauth/callback",
                    "http://localhost:5173/agents/identities/oauth/callback",
                    "http://localhost:4173/agents/identities/oauth/callback",
                    "http://localhost:3000/agents/identities/oauth/callback",
                ]
            )
            print(f"  ✓ Created agent client '{agent_client_id}' in agent realm")

        # Always ensure offline_access scope is enabled for agent OAuth
        await self._enable_offline_access_scope(self.AGENT_REALM_NAME, agent_client_id)

        # Add mcp_role claim mapper to agent client
        await self._add_mcp_role_claim_mapper(self.AGENT_REALM_NAME, agent_client_id)

        # Also add mcp_role claim mapper to user realm client
        await self._add_mcp_role_claim_mapper(self.REALM_NAME, "parthenon-api")
        await self._add_mcp_role_claim_mapper(self.REALM_NAME, "parthenon-api-ui")

    async def _add_mcp_role_claim_mapper(self, realm_name: str, client_id: str):
        """Register mcp_role attribute in user profile and add claim mapper."""
        import httpx

        base = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}"
        h = {"Authorization": f"Bearer {self.admin_token.access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            # ── Step 1: Register mcp_role in user profile ──
            resp = await client.get(f"{base}/users/profile", headers=h)
            profile = resp.json() if resp.status_code == 200 else {"attributes": []}
            existing_attrs = {a.get("name") for a in profile.get("attributes", [])}
            if "mcp_role" not in existing_attrs:
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
                    print(f"  ✓ Registered mcp_role attribute in user profile for '{realm_name}'")

            # ── Step 2: Get client UUID ──
            resp = await client.get(f"{base}/clients", params={"clientId": client_id}, headers=h)
            clients = resp.json() if resp.status_code == 200 else []
            if not clients:
                return
            client_uuid = clients[0]["id"]

            # ── Step 3: Add claim mapper ──
            resp = await client.get(f"{base}/clients/{client_uuid}/protocol-mappers/models", headers=h)
            mappers = resp.json() if resp.status_code == 200 else []
            if any(m.get("name") == "mcp_role" for m in mappers):
                print(f"  ✓ mcp_role claim mapper already exists on '{client_id}' in '{realm_name}'")
                return

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
                print(f"  ✓ Added mcp_role claim mapper to '{client_id}' in '{realm_name}'")

    async def _enable_offline_access_scope(self, realm_name: str, client_id: str):
        """Enable offline_access for a client so OAuth flow can get refresh tokens."""
        import httpx

        base = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}"
        h = {"Authorization": f"Bearer {self.admin_token.access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get client UUID
            resp = await client.get(f"{base}/clients", params={"clientId": client_id}, headers=h)
            clients = resp.json() if resp.status_code == 200 else []
            if not clients:
                print(f"  ⚠ Could not find client '{client_id}' in realm '{realm_name}'")
                return
            client_uuid = clients[0]["id"]

            # Find offline_access scope ID
            resp = await client.get(f"{base}/client-scopes", headers=h)
            scopes = resp.json() if resp.status_code == 200 else []
            offline_scope = next((s for s in scopes if s.get("name") == "offline_access"), None)
            if not offline_scope:
                print(f"  ⚠ 'offline_access' scope not found in realm '{realm_name}'")
                return

            # Assign as optional client scope
            resp = await client.put(
                f"{base}/clients/{client_uuid}/optional-client-scopes/{offline_scope['id']}",
                headers=h,
            )
            if resp.status_code in (204, 200):
                print(f"  ✓ Enabled offline_access for client '{client_id}' in realm '{realm_name}'")
            else:
                print(f"  ⚠ Could not enable offline_access: HTTP {resp.status_code}")

    async def _ensure_test_agent_identities(self):
        """Create test agent identities in the ai_agents realm with demo_agent role."""
        logger.info("Step 5b: Ensuring test agent identities...")

        from app.db.models.agents import AgentIdentity, AgentIdentityType, AgentIdentityStatus

        # Ensure realm roles exist
        await self._ensure_realm_role(self.AGENT_REALM_NAME, "demo_agent", "Required mcp_role for helloAgent MCP tool")
        await self._ensure_realm_role(self.REALM_NAME, "demo_user", "Required mcp_role for helloUser MCP tool")

        # test_agent: has demo_agent role → helloAgent succeeds
        # test_agent_2: NO demo_agent role → helloAgent access-denied
        # admin: has demo_user role → helloUser succeeds
        # testuser: NO demo_user role → helloUser access-denied
        TEST_AGENTS = [
            {"username": "test_agent", "password": "test_agent", "roles": ["demo_agent"], "mcp_role": "demo_agent"},
            {"username": "test_agent_2", "password": "test_agent_2", "roles": [], "mcp_role": None},
        ]
        USER_REALM_USERS = [
            {"username": "testuser", "password": "testuser", "roles": [], "mcp_role": None},
        ]

        # ── Agent identities (ai_agents realm) ──
        for agent in TEST_AGENTS:
            username = agent["username"]
            try:
                await self.kc_client.create_user(
                    self.admin_token,
                    self.AGENT_REALM_NAME,
                    username,
                    agent["password"],
                    roles=agent["roles"],
                )
                await self._reset_user_password(self.AGENT_REALM_NAME, username, agent["password"])

                # Set mcp_role user attribute
                if agent.get("mcp_role"):
                    await self._set_user_attribute(self.AGENT_REALM_NAME, username, "mcp_role", agent["mcp_role"])
                else:
                    await self._remove_user_attribute(self.AGENT_REALM_NAME, username, "mcp_role")
            except KeycloakAdminError as e:
                print(f"  ⚠ Failed to create Keycloak user '{username}': {e.detail}")
                continue

            # Ensure correct role assignments (remove unwanted roles)
            await self._sync_user_roles(self.AGENT_REALM_NAME, username, agent["roles"] + ["offline_access"])

            # Create AgentIdentity record in DB
            engine = create_async_engine(str(self.settings.database_url))
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as db:
                result = await db.execute(
                    select(AgentIdentity).where(AgentIdentity.name == f"{username}@ai_agents")
                )
                existing = result.scalar_one_or_none()
                if existing:
                    print(f"  ✓ Agent identity '{username}@ai_agents' exists (demo_agent={'demo_agent' in agent['roles']})")
                    # Clear tokens if they were issued by a previous Keycloak instance
                    if existing.access_token and existing.token_expires_at:
                        from datetime import datetime as dt, timezone as tz
                        if existing.token_expires_at < dt.now(tz.utc):
                            existing.access_token = None
                            existing.refresh_token = None
                            existing.encrypted_refresh_token = None
                            existing.token_status = None
                            existing.token_expires_at = None
                else:
                    identity = AgentIdentity(
                        name=f"{username}@ai_agents",
                        identity_type=AgentIdentityType.realm_user,
                        realm_name=self.AGENT_REALM_NAME,
                        realm_username=username,
                        status=AgentIdentityStatus.active,
                    )
                    db.add(identity)
                    await db.commit()
                    print(f"  ✓ Created agent identity '{username}@ai_agents'")
            await engine.dispose()

        # ── User realm identities (parthenon realm) ──
        for user_info in USER_REALM_USERS:
            username = user_info["username"]
            try:
                await self.kc_client.create_user(
                    self.admin_token,
                    self.REALM_NAME,
                    username,
                    user_info["password"],
                    roles=user_info["roles"],
                )
                await self._reset_user_password(self.REALM_NAME, username, user_info["password"])

                if user_info.get("mcp_role"):
                    await self._set_user_attribute(self.REALM_NAME, username, "mcp_role", user_info["mcp_role"])
                else:
                    await self._remove_user_attribute(self.REALM_NAME, username, "mcp_role")
            except KeycloakAdminError as e:
                print(f"  ⚠ Failed to create user '{username}' in {self.REALM_NAME}: {e.detail}")
                continue

            await self._sync_user_roles(self.REALM_NAME, username, user_info["roles"])
            print(f"  ✓ Test user '{username}' in realm '{self.REALM_NAME}' (demo_user=False)")

        # ── Admin gets demo_user role (additive, preserves admin/user roles) ──
        await self._sync_user_roles(self.REALM_NAME, "admin", ["admin", "demo_user", "offline_access"])
        await self._set_user_attribute(self.REALM_NAME, "admin", "mcp_role", "demo_user")
        print(f"  ✓ Admin user has admin + demo_user roles + mcp_role=demo_user in realm '{self.REALM_NAME}'")

    async def _ensure_realm_role(self, realm_name: str, role_name: str, description: str):
        """Ensure a realm-level role exists (idempotent)."""
        import httpx

        url = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}/roles/{role_name}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {self.admin_token.access_token}"},
            )
        if resp.status_code == 200:
            return  # Already exists

        create_url = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}/roles"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                create_url,
                json={"name": role_name, "description": description},
                headers={"Authorization": f"Bearer {self.admin_token.access_token}"},
            )
        if resp.status_code == 201:
            print(f"  ✓ Created realm role '{role_name}' in realm '{realm_name}'")
        elif resp.status_code == 409:
            print(f"  ✓ Realm role '{role_name}' already exists in '{realm_name}'")
        else:
            print(f"  ⚠ Could not create role '{role_name}': HTTP {resp.status_code}")

    async def _reset_user_password(self, realm_name: str, username: str, password: str):
        """Reset a user's password via Keycloak admin API."""
        import httpx

        user_id = await self.kc_client.get_user_by_username(self.admin_token, realm_name, username)
        if not user_id:
            return

        url = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}/users/{user_id}/reset-password"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.put(
                url,
                json={"type": "password", "value": password, "temporary": False},
                headers={"Authorization": f"Bearer {self.admin_token.access_token}"},
            )
        if resp.status_code == 204:
            logger.info("Password reset for user %r in realm %r", username, realm_name)

    async def _sync_user_roles(self, realm_name: str, username: str, desired_roles: list[str]):
        """Ensure a user has desired realm roles (additive only — never removes existing roles)."""
        import httpx

        user_id = await self.kc_client.get_user_by_username(self.admin_token, realm_name, username)
        if not user_id:
            return

        base = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            h = {"Authorization": f"Bearer {self.admin_token.access_token}"}

            # Get currently assigned realm roles
            resp = await client.get(f"{base}/users/{user_id}/role-mappings/realm", headers=h)
            current_roles = resp.json() if resp.status_code == 200 else []
            current_names = {r.get("name") for r in current_roles if isinstance(r, dict)}

            # Add missing roles (never remove)
            to_add = set(desired_roles) - current_names
            if to_add:
                resp = await client.get(f"{base}/roles", headers=h)
                all_roles = resp.json() if resp.status_code == 200 else []
                role_reprs = [r for r in all_roles if r.get("name") in to_add]
                if role_reprs:
                    resp = await client.post(f"{base}/users/{user_id}/role-mappings/realm",
                        headers=h, json=role_reprs)
                    if resp.status_code == 204:
                        logger.info("Assigned roles %s to %r in %r", list(to_add), username, realm_name)

    async def _set_user_attribute(self, realm_name: str, username: str, attr_name: str, attr_value: str):
        """Set a single-valued user attribute via Keycloak admin API.
        
        Uses GET-then-PUT to preserve existing user fields."""
        import httpx

        user_id = await self.kc_client.get_user_by_username(self.admin_token, realm_name, username)
        if not user_id:
            return

        url = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}/users/{user_id}"
        h = {"Authorization": f"Bearer {self.admin_token.access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            # GET current user to preserve all fields
            resp = await client.get(url, headers=h)
            if resp.status_code != 200:
                return
            user_data = resp.json()

            # Skip if attribute already has the correct value
            current = user_data.get("attributes", {}).get(attr_name)
            if current == [attr_value]:
                return  # Already set — skip to avoid invalidating Keycloak sessions

            # Restore fields that may have been wiped by a prior faulty update
            if not user_data.get("email"):
                user_data["email"] = f"{username}@test.local"
            if not user_data.get("firstName"):
                user_data["firstName"] = "Test"
            if not user_data.get("lastName"):
                user_data["lastName"] = "User"

            # Merge attributes
            attrs = dict(user_data.get("attributes", {}))
            attrs[attr_name] = [attr_value]
            user_data["attributes"] = attrs

            # PUT back with merged attributes
            resp = await client.put(url, headers={**h, "Content-Type": "application/json"}, json=user_data)
            if resp.status_code == 204:
                logger.debug("Set attribute %s=%s on user %r in %r", attr_name, attr_value, username, realm_name)

    async def _remove_user_attribute(self, realm_name: str, username: str, attr_name: str):
        """Remove a user attribute via Keycloak admin API.
        
        Uses GET-then-PUT to preserve existing user fields."""
        import httpx

        user_id = await self.kc_client.get_user_by_username(self.admin_token, realm_name, username)
        if not user_id:
            return

        url = f"{self.KEYCLOAK_BASE_URL}/admin/realms/{realm_name}/users/{user_id}"
        h = {"Authorization": f"Bearer {self.admin_token.access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=h)
            if resp.status_code != 200:
                return
            user_data = resp.json()

            # Skip if attribute is already absent
            if attr_name not in user_data.get("attributes", {}):
                return  # Already absent — skip to avoid invalidating Keycloak sessions

            # Restore fields that may have been wiped
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
                logger.debug("Removed attribute %s from user %r in %r", attr_name, username, realm_name)

    async def _ensure_admin_user_in_keycloak(self) -> str:
        """Ensure admin user exists in Keycloak and return their UUID.
        
        Returns:
            User UUID (sub claim) from Keycloak
        """
        logger.info("Step 4: Ensuring admin user exists in Keycloak...")
        
        # Check if user already exists
        user_id = await self.kc_client.get_user_by_username(
            self.admin_token,
            self.REALM_NAME,
            self.ADMIN_USERNAME
        )
        
        if user_id:
            print(f"  ✓ Admin user '{self.ADMIN_USERNAME}' already exists (UUID: {user_id})")
            return user_id
        
        # Create the user
        await self.kc_client.create_user(
            self.admin_token,
            self.REALM_NAME,
            self.ADMIN_USERNAME,
            self.ADMIN_PASSWORD,
            roles=["admin"]  # Assign realm admin role
        )
        
        # Get the newly created user's UUID
        user_id = await self.kc_client.get_user_by_username(
            self.admin_token,
            self.REALM_NAME,
            self.ADMIN_USERNAME
        )
        
        if not user_id:
            raise InitializationError("Failed to retrieve admin user ID after creation")
        
        print(f"  ✓ Created admin user '{self.ADMIN_USERNAME}' (UUID: {user_id})")
        return user_id
    
    async def _initialize_database(self):
        """Initialize database with system roles and policies."""
        logger.info("Step 5: Initializing database...")
        
        engine = create_async_engine(str(self.settings.database_url))
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        8
        async with async_session() as db:
            # Check if system_admin role exists
            result = await db.execute(
                select(Role).where(Role.name == "system_admin", Role.is_system.is_(True))
            )
            role = result.scalar_one_or_none()
            
            if role:
                print("  ✓ System admin role already exists")
            else:
                # Create system_admin role
                role = Role(
                    name="system_admin",
                    description="System administrator — full platform access. Immutable.",
                    is_system=True,
                    is_active=True,
                )
                db.add(role)
                await db.flush()
                print(f"  ✓ Created system_admin role (ID: {role.id})")
                
                # Create wildcard policy for system_admin
                stmt = PolicyStatement(
                    role_id=role.id,
                    effect=PolicyEffect.allow,
                    module="*",
                )
                db.add(stmt)
                await db.flush()
                
                db.add(PolicyAction(policy_statement_id=stmt.id, action="*"))
                db.add(PolicyResource(policy_statement_id=stmt.id, resource_type="*", resource_id="*"))
                await db.flush()
                
                print(f"  ✓ Created wildcard policy for system_admin role")
            
            await db.commit()
        
        await engine.dispose()
    
    async def _ensure_admin_in_platform_users(self, keycloak_user_id: str):
        """Ensure admin user exists in platform_users table with correct sub."""
        logger.info("Step 6: Ensuring admin user in platform_users...")
        
        engine = create_async_engine(str(self.settings.database_url))
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as db:
            # Check if user exists with this sub
            result = await db.execute(
                select(PlatformUser).where(PlatformUser.sub == keycloak_user_id)
            )
            user = result.scalar_one_or_none()
            
            if user:
                print(f"  ✓ Admin user already in platform_users (ID: {user.id})")
                
                # Check for duplicate admin users with same email but different sub
                result = await db.execute(
                    select(PlatformUser).where(
                        PlatformUser.email == self.ADMIN_EMAIL,
                        PlatformUser.sub != keycloak_user_id
                    )
                )
                duplicates = result.scalars().all()
                
                if duplicates:
                    print(f"  ⚠ WARNING: Found {len(duplicates)} duplicate admin user(s) with same email but different sub:")
                    for dup in duplicates:
                        print(f"    - ID: {dup.id}, Sub: {dup.sub}")
                    print("    These should be manually cleaned up to avoid confusion.")
            else:
                # Check if there's an old admin user with different sub
                result = await db.execute(
                    select(PlatformUser).where(PlatformUser.email == self.ADMIN_EMAIL)
                )
                old_admins = result.scalars().all()

                if old_admins:
                    # Keep the first, remove duplicates, update sub
                    old_admin = old_admins[0]
                    if len(old_admins) > 1:
                        print(f"  ⚠ Found {len(old_admins)} admin users with same email, consolidating...")
                        for dup in old_admins[1:]:
                            await db.delete(dup)
                    print(f"  ⚠ Found existing admin user with different sub (old: {old_admin.sub}, new: {keycloak_user_id})")
                    print(f"    Updating sub to match current Keycloak user...")
                    old_admin.sub = keycloak_user_id
                    await db.commit()
                    print(f"  ✓ Updated admin user sub to {keycloak_user_id}")
                else:
                    # Create new platform user entry (will be auto-created on first login anyway)
                    print(f"  ℹ Admin user will be created in platform_users on first login")
        
        await engine.dispose()
    
    async def _assign_admin_role(self, keycloak_user_id: str):
        """Assign system_admin role to the admin user."""
        logger.info("Step 7: Assigning system_admin role to admin user...")
        
        engine = create_async_engine(str(self.settings.database_url))
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as db:
            # Get system_admin role
            result = await db.execute(
                select(Role).where(Role.name == "system_admin", Role.is_system.is_(True))
            )
            role = result.scalar_one_or_none()
            
            if not role:
                raise InitializationError("system_admin role not found")
            
            # Get or create platform user
            result = await db.execute(
                select(PlatformUser).where(PlatformUser.sub == keycloak_user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                # User hasn't logged in yet, create placeholder entry
                from datetime import datetime
                user = PlatformUser(
                    sub=keycloak_user_id,
                    email=self.ADMIN_EMAIL,
                    display_name="Admin User",
                    first_seen_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow()
                )
                db.add(user)
                await db.flush()
                print(f"  ✓ Created platform_user entry for admin (ID: {user.id})")
            
            # Check if role is already assigned
            result = await db.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id
                )
            )
            existing_assignment = result.scalar_one_or_none()
            
            if existing_assignment:
                print(f"  ✓ Admin user already has system_admin role")
            else:
                db.add(UserRole(user_id=user.id, role_id=role.id))
                await db.commit()
                print(f"  ✓ Assigned system_admin role to admin user")
        
        await engine.dispose()


async def main():
    """Main entry point."""
    initializer = LocalDevInitializer()
    try:
        await initializer.initialize()
        return 0
    except InitializationError as e:
        print()
        print("=" * 80)
        print("✗ INITIALIZATION FAILED")
        print("=" * 80)
        print(f"Error: {e}")
        print()
        return 1
    except KeyboardInterrupt:
        print("\n\nInitialization cancelled by user.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
