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
import logging
import os
import sys
from pathlib import Path

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
                old_admin = result.scalar_one_or_none()
                
                if old_admin:
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
