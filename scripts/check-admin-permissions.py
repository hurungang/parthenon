"""
⚠ DEPRECATED — use ``python -m setup.main verify`` instead.

This script will be removed in a future release.
See: setup/README.md
"""
import sys as _sys
print("⚠ DEPRECATED: Use 'python -m setup.main verify' instead.", file=_sys.stderr)
"""Diagnostic script to check admin user permissions."""
import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models.platform_user import PlatformUser
from app.db.models.identity import Role
from app.db.models.user_role import UserRole
from app.db.models.policy_statement import PolicyStatement, PolicyEffect
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource
from app.core.config import get_settings


async def check_admin_permissions():
    """Check admin user permissions setup."""
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        print("=" * 80)
        print("ADMIN PERMISSIONS DIAGNOSTIC")
        print("=" * 80)
        
        # 1. Check BOOTSTRAP_ADMIN_EMAIL environment variable
        admin_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
        print(f"\n1. BOOTSTRAP_ADMIN_EMAIL env var: {admin_email or '(not set)'}")
        
        # 2. Find admin user in platform_users
        if admin_email:
            result = await db.execute(
                select(PlatformUser).where(PlatformUser.email == admin_email)
            )
            admin_user = result.scalar_one_or_none()
            if admin_user:
                print(f"   ✓ Found admin user: id={admin_user.id}, email={admin_user.email}, sub={admin_user.sub}")
                await check_single_admin_user(db, admin_user)
            else:
                print(f"   ✗ Admin user with email '{admin_email}' NOT FOUND in platform_users table")
                print("   → User needs to log in first to be created in platform_users")
        else:
            print("   ⚠ No admin email configured. Checking for any admin users...")
            # List all users
            result = await db.execute(select(PlatformUser))
            all_users = result.scalars().all()
            print(f"   Found {len(all_users)} total users:")
            for u in all_users:
                print(f"      - {u.email} (id={u.id})")
            
            # Find all admin@parthenon.local users
            admin_users = [u for u in all_users if u.email == "admin@parthenon.local"]
            if admin_users:
                print(f"\n   Found {len(admin_users)} admin@parthenon.local user(s)")
                # Check permissions for ALL admin users
                for admin_user in admin_users:
                    print(f"\n   === Checking admin user id={admin_user.id} ===")
                    await check_single_admin_user(db, admin_user)
            elif all_users and len(all_users) == 1:
                admin_user = all_users[0]
                print(f"   Using single user as admin: {admin_user.email}")
                await check_single_admin_user(db, admin_user)
            else:
                print("   Cannot determine which user to check.")
    
    await engine.dispose()


async def check_single_admin_user(db: AsyncSession, admin_user: PlatformUser):
    """Check permissions for a single admin user."""
    
    # 3. Check system_admin role exists
    result = await db.execute(
        select(Role).where(Role.name == "system_admin", Role.is_system.is_(True))
    )
    system_admin_role = result.scalar_one_or_none()
    print(f"   2. System Admin Role:")
    if system_admin_role:
        print(f"      ✓ Found system_admin role: id={system_admin_role.id}, is_active={system_admin_role.is_active}")
    else:
        print(f"      ✗ system_admin role NOT FOUND")
        print("      → Bootstrap service did not run or failed")
        return
    
    # 4. Check if admin user has system_admin role
    result = await db.execute(
        select(UserRole).where(
            UserRole.user_id == admin_user.id,
            UserRole.role_id == system_admin_role.id
        )
    )
    user_role = result.scalar_one_or_none()
    print(f"   3. Admin User Role Assignment:")
    if user_role:
        print(f"      ✓ Admin user HAS system_admin role (assigned at {user_role.assigned_at})")
    else:
        print(f"      ✗ Admin user DOES NOT have system_admin role")
        print(f"      → UserRole record missing for user_id={admin_user.id}, role_id={system_admin_role.id}")
        
        # Check what roles the user DOES have
        result = await db.execute(
            select(Role, UserRole)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == admin_user.id)
        )
        user_roles = result.all()
        if user_roles:
            print(f"      User has {len(user_roles)} role(s):")
            for role, ur in user_roles:
                print(f"         - {role.name} (id={role.id})")
        else:
            print("      User has NO roles assigned")
        return
    
    # 5. Check policy statements for system_admin role
    result = await db.execute(
        select(PolicyStatement).where(
            PolicyStatement.role_id == system_admin_role.id,
            PolicyStatement.effect == PolicyEffect.allow
        )
    )
    policy_statements = result.scalars().all()
    print(f"   4. System Admin Policy Statements:")
    if policy_statements:
        print(f"      Found {len(policy_statements)} allow statement(s):")
        for stmt in policy_statements:
            print(f"      - Statement id={stmt.id}, module={stmt.module}")
            
            # Check actions
            result = await db.execute(
                select(PolicyAction).where(PolicyAction.policy_statement_id == stmt.id)
            )
            actions = result.scalars().all()
            print(f"        Actions: {[a.action for a in actions]}")
            
            # Check resources
            result = await db.execute(
                select(PolicyResource).where(PolicyResource.policy_statement_id == stmt.id)
            )
            resources = result.scalars().all()
            print(f"        Resources: {[(r.resource_type, r.resource_id) for r in resources]}")
            
            # Check if it's the wildcard policy
            has_wildcard_action = any(a.action == "*" for a in actions)
            has_wildcard_resource = any(r.resource_id == "*" for r in resources)
            if stmt.module == "*" and has_wildcard_action and has_wildcard_resource:
                print(f"        ✓ This is the FULL WILDCARD policy (allows everything)")
    else:
        print(f"      ✗ NO policy statements found for system_admin role")
        print("      → Bootstrap service did not create policies or they were deleted")
    
    # 6. Summary
    print("\n   " + "=" * 76)
    print("   SUMMARY for user", admin_user.id)
    if user_role and policy_statements:
        has_wildcard = any(
            stmt.module == "*" for stmt in policy_statements
        )
        if has_wildcard:
            print(f"   ✓ Admin user {admin_user.id} has correct permissions!")
        else:
            print(f"   ⚠ Admin user {admin_user.id} has role but no wildcard policy - limited permissions")
    else:
        print(f"   ✗ Admin user {admin_user.id} permissions are NOT correctly configured")
        print("     Recommended fix: Run bootstrap service or manually assign roles")
    print("   " + "=" * 76)


if __name__ == "__main__":
    asyncio.run(check_admin_permissions())
