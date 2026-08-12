"""
⚠ DEPRECATED — use ``python -m setup.main verify`` instead.

This script will be removed in a future release.
See: setup/README.md
"""
import sys as _sys
print("⚠ DEPRECATED: Use 'python -m setup.main verify' instead.", file=_sys.stderr)
"""Check which admin user is the correct one."""
import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.models.platform_user import PlatformUser
from app.core.config import get_settings


async def check_admin_users():
    """Check admin user details."""
    settings = get_settings()
    engine = create_async_engine(str(settings.database_url))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        result = await db.execute(
            select(PlatformUser)
            .where(PlatformUser.email == "admin@parthenon.local")
            .order_by(PlatformUser.first_seen_at)
        )
        admin_users = result.scalars().all()
        
        print("=" * 80)
        print("ADMIN USER DETAILS")
        print("=" * 80)
        for i, user in enumerate(admin_users, 1):
            print(f"\nAdmin User #{i}:")
            print(f"  ID:          {user.id}")
            print(f"  Email:       {user.email}")
            print(f"  Sub:         {user.sub}")
            print(f"  Display Name:{user.display_name}")
            print(f"  First Seen:  {user.first_seen_at}")
            print(f"  Last Seen:   {user.last_seen_at}")
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_admin_users())
