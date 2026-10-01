import asyncio, os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.session import Base
from app.db.models.tenant import Tenant
from app.db.models.access_request_batch import AccessRequestBatch
from app.db.models.platform_user import PlatformUser
import app.db.tenant_scoping as ts

async def main():
    ts.register_tenant_scope_listener()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as db:
        ta = Tenant(name="A", slug="a"); tb = Tenant(name="B", slug="b")
        db.add_all([ta, tb]); await db.flush()
        ua = PlatformUser(sub="s-a", email="a@x.test", display_name="UA")
        ub = PlatformUser(sub="s-b", email="b@x.test", display_name="UB")
        db.add_all([ua, ub]); await db.flush()
        db.add_all([
            AccessRequestBatch(user_id=ua.id, justification="a", tenant_id=ta.id),
            AccessRequestBatch(user_id=ub.id, justification="b", tenant_id=tb.id),
        ])
        await db.commit()
        ta_id, tb_id = ta.id, tb.id

    async with S() as s1:
        ts.apply_tenant_scope(s1, ta_id)
        rows = (await s1.execute(select(AccessRequestBatch))).scalars().all()
        print(f"scope A -> rows justification={[r.justification for r in rows]} (expect ['a'])")
    async with S() as s2:
        ts.apply_tenant_scope(s2, tb_id)
        rows = (await s2.execute(select(AccessRequestBatch))).scalars().all()
        print(f"scope B -> rows justification={[r.justification for r in rows]} (expect ['b'])")
    async with S() as s3:
        ts.apply_tenant_scope(s3, ta_id)
        rows = (await s3.execute(select(AccessRequestBatch))).scalars().all()
        print(f"scope A again -> rows justification={[r.justification for r in rows]} (expect ['a'])")
    await engine.dispose()

asyncio.run(main())
