import asyncio, os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event
from sqlalchemy.orm import Session as SyncSession
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
    S2 = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with S2() as chk:
        rows = (await chk.execute(select(model_cls))).scalars().all()
        print(f"  seed check {model_cls.__name__}: {len(rows)} rows, tenant_ids={[str(r.tenant_id) for r in rows]}")
    return ids

async def test_body(engine, model_cls):
    id_a, id_b = await seed(engine, model_cls)
    S = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as unscoped:
        got = await unscoped.get(model_cls, id_b)
        print(f"  {model_cls.__name__}: unscoped get -> {'OK' if got else 'NONE!!'}")
        ta_id = ((await unscoped.execute(select(Tenant).where(Tenant.slug == "a"))).scalar_one()).id
    print(f"  {model_cls.__name__}: ta_id={ta_id}")
    async with S() as scoped:
        ts.apply_tenant_scope(scoped, ta_id)
        rows = (await scoped.execute(select(model_cls))).scalars().all()
        print(f"  {model_cls.__name__}: scoped rows -> {len(rows)}")

async def main():
    ts.register_tenant_scope_listener()
    for cls in (AccessRequest, AccessRequestBatch):
        print(f"test {cls.__name__}:")
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.exec_driver_sql("DROP INDEX IF EXISTS uq_roles_global_name")
        await test_body(engine, cls)
        await engine.dispose()

asyncio.run(main())
