import asyncio, os, sys, uuid
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.session import Base
from app.db.models.access_request_batch import AccessRequestBatch
from app.db.models.tenant import Tenant
from app.db.models.platform_user import PlatformUser
from app.db.tenant_scoping import register_tenant_scope_listener, apply_tenant_scope

async def one_round(n):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as db:
        ta = Tenant(name="A", slug="a"); tb = Tenant(name="B", slug="b")
        db.add_all([ta, tb]); await db.flush()
        ua = PlatformUser(sub=f"sub-a{n}", email=f"a{n}@x.test", display_name="UA")
        ub = PlatformUser(sub=f"sub-b{n}", email=f"b{n}@x.test", display_name="UB")
        db.add_all([ua, ub]); await db.flush()
        rb = AccessRequestBatch(user_id=ub.id, justification="s", tenant_id=tb.id)
        db.add(rb); await db.flush()
        id_b = rb.id
        await db.commit()
    async with S() as unscoped:
        got = await unscoped.get(AccessRequestBatch, id_b)
        print(f"round {n}: unscoped get -> {got}")
    await engine.dispose()

async def main():
    register_tenant_scope_listener()
    await one_round(1)
    await one_round(2)

asyncio.run(main())
