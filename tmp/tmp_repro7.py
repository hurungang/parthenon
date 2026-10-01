import asyncio, os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import uuid as uuid_mod
import app.db.models  # noqa
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession, with_loader_criteria
from sqlalchemy.sql.selectable import Select
from app.db.session import Base
from app.db.models.tenant import Tenant
from app.db.models.access_request_batch import AccessRequestBatch
from app.db.models.platform_user import PlatformUser

_SCOPE_KEY = "probe_scope"

def fixed_scope_options(stmt: Select, tenant_id):
    """Candidate fix shape: closure variable (tracked by SQLAlchemy's lambda
    cache) instead of a default-arg binding."""
    entities = []
    for desc in stmt.column_descriptions or []:
        ent = desc.get("entity") if isinstance(desc, dict) else None
        if ent is not None and ent not in entities and "tenant_id" in ent.__table__.columns.keys():
            entities.append(ent)
    options = []
    for ent in entities:
        def _crit(cls, _tid):
            return cls.tenant_id == _tid
        options.append(with_loader_criteria(ent, lambda cls, tid=tenant_id: cls.tenant_id == tid, include_aliases=True))
    return options

@event.listens_for(SyncSession, "do_orm_execute")
def fixed_do_orm_execute(state):
    tid = state.session.info.get(_SCOPE_KEY)
    if tid is None:
        return
    stmt = state.statement
    if isinstance(stmt, Select):
        options = fixed_scope_options(stmt, tid)
        if options:
            state.statement = stmt.options(*options)

def apply_fixed(session, tid):
    session.sync_session.info[_SCOPE_KEY] = uuid_mod.UUID(str(tid))

async def main():
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

    for label, tid, expect in (("A", ta_id, ["a"]), ("B", tb_id, ["b"]), ("A", ta_id, ["a"])):
        async with S() as s:
            apply_fixed(s, tid)
            rows = (await s.execute(select(AccessRequestBatch))).scalars().all()
            got = [r.justification for r in rows]
            print(f"closure-lambda scope {label} -> {got} (expect {expect}) {'OK' if got == expect else 'STILL BROKEN'}")
    await engine.dispose()

asyncio.run(main())
