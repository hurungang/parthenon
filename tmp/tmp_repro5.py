import asyncio, os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.db.session import Base
from app.db.models.access_request import AccessRequest
from app.db.models.access_request_batch import AccessRequestBatch
from app.db.models.tenant import Tenant
from app.db.models.platform_user import PlatformUser
import app.db.tenant_scoping as ts

async def seed(engine, model_cls):
    S = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as db:
        ta = Tenant(name="A", slug="a"); tb = Tenant(name="B", slug="b")
        db.add_all([ta, tb]); await db.flush()
        ua = PlatformUser(sub="sub-a", email="a@x.test", display_name="UA")
        ub = PlatformUser(sub="sub-b", email="b@x.test", display_name="UB")
        db.add_all([ua, ub]); await db.flush()
        if model_cls is AccessRequest:
            ba = AccessRequestBatch(user_id=ua.id, justification="s", tenant_id=ta.id)
            bb = AccessRequestBatch(user_id=ub.id, justification="s", tenant_id=tb.id)
            db.add_all([ba, bb]); await db.flush()
            ra = AccessRequest(batch_id=ba.id, user_id=ua.id, status="pending", tenant_id=ta.id)
            rb = AccessRequest(batch_id=bb.id, user_id=ub.id, status="pending", tenant_id=tb.id)
        else:
            ra = AccessRequestBatch(user_id=ua.id, justification="s", tenant_id=ta.id)
            rb = AccessRequestBatch(user_id=ub.id, justification="s", tenant_id=tb.id)
        db.add_all([ra, rb]); await db.flush()
        ids = (ra.id, rb.id)
        await db.commit()
    return ids

async def main():
    ts.register_tenant_scope_listener()
    for cls in (AccessRequest, AccessRequestBatch):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.exec_driver_sql("DROP INDEX IF EXISTS uq_roles_global_name")
        id_a, id_b = await seed(engine, cls)
        S = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        async with S() as unscoped:
            ta_id = ((await unscoped.execute(select(Tenant).where(Tenant.slug == "a"))).scalar_one()).id
        async with S() as raw:
            stored = (await raw.execute(text(f"SELECT tenant_id FROM {cls.__tablename__}"))).all()
            stored_tenants = (await raw.execute(text("SELECT id FROM tenants"))).all()
        print(f"### {cls.__name__}: raw stored tenant_id={[r[0] for r in stored]}")
        print(f"### {cls.__name__}: raw tenants id={[r[0] for r in stored_tenants]}")
        async with S() as scoped:
            ts.apply_tenant_scope(scoped, ta_id)
            rows = (await scoped.execute(select(cls))).scalars().all()
            print(f"### {cls.__name__}: scoped rows -> {len(rows)} (expect 1)")
        await engine.dispose()

asyncio.run(main())
