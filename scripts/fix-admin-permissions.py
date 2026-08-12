"""
⚠ DEPRECATED — use ``python -m setup.main database`` instead.

This script will be removed in a future release.
See: setup/README.md
"""
import sys as _sys
print("⚠ DEPRECATED: Use 'python -m setup.main database' instead.", file=_sys.stderr)
"""Fix admin permissions by assigning system_admin role to duplicate admin user."""
import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.models.platform_user import PlatformUser
from app.db.models.identity import Role
from app.db.models.user_role import UserRole
from app.core.config import get_settings


async def fix_admin_permissions():
    """Assign system_admin role to the duplicate admin user."""
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        print("=" * 80)
        print("FIX ADMIN PERMISSIONS")
        print("=" * 80)
        
        # 1. Find the duplicate admin user (the newer one without roles)
        duplicate_admin_id = "224e6c26-bd0e-4b27-b1b1-5f20b561725b"
        
        result = await db.execute(
            select(PlatformUser).where(PlatformUser.id == duplicate_admin_id)
        )
        duplicate_admin = result.scalar_one_or_none()
        
        if not duplicate_admin:
            print(f"✗ Duplicate admin user {duplicate_admin_id} not found!")
            return
        
        print(f"\n1. Found duplicate admin user:")
        print(f"   ID:    {duplicate_admin.id}")
        print(f"   Email: {duplicate_admin.email}")
        print(f"   Sub:   {duplicate_admin.sub}")
        
        # 2. Find the system_admin role
        result = await db.execute(
            select(Role).where(Role.name == "system_admin", Role.is_system.is_(True))
        )
        system_admin_role = result.scalar_one_or_none()
        
        if not system_admin_role:
            print(f"\n✗ system_admin role not found!")
            return
        
        print(f"\n2. Found system_admin role: {system_admin_role.id}")
        
        # 3. Check if already assigned
        result = await db.execute(
            select(UserRole).where(
                UserRole.user_id == duplicate_admin.id,
                UserRole.role_id == system_admin_role.id
            )
        )
        existing_assignment = result.scalar_one_or_none()
        
        if existing_assignment:
            print(f"\n✓ system_admin role already assigned to this user!")
            return
        
        # 4. Assign the role
        print(f"\n3. Assigning system_admin role to duplicate admin user...")
        db.add(UserRole(user_id=duplicate_admin.id, role_id=system_admin_role.id))
        await db.commit()
        
        print(f"\n✓ Successfully assigned system_admin role!")
        print("\n" + "=" * 80)
        print("FIX COMPLETE")
        print("=" * 80)
        print("\nThe admin user should now have full permissions.")
        print("Please refresh the UI to see the changes.")
        print("\nNote: You still have TWO admin@parthenon.local users.")
        print("Consider investigating why a duplicate was created and optionally")
        print("delete the old admin user if no longer needed.")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(fix_admin_permissions())
