"""Cross-tenant isolation — negative tests at the DB gateway per domain
group (Phase 3.6 / 9.2, CS-12/CS-13).

For EVERY scoped domain group the suite proves, from a tenant-A-scoped
session (what ``get_db`` produces in multi-tenancy mode):

- list/select returns exclusively tenant A rows (CS-13)
- direct-addressed tenant B ids yield None (404-equivalent) — never data
- writes cannot create/update/delete rows outside tenant A
- each cross-tenant probe becomes a security-relevant
  ``cross_tenant_access_denied`` TenantAuditEvent attributed to tenant A

Join/child tables (UserRole, ApiKeyUsageLog) inherit scope through their
scoped parents (E-01).  The mechanism under test is the single choke
point (``apply_tenant_scope``) — the same object every endpoint's
``get_db`` session carries, so these guarantees hold for all routes.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.session import Base  # noqa: E402
from app.db.tenant_scoping import (  # noqa: E402
    apply_tenant_scope,
    flush_scope_miss_audits,
    register_tenant_scope_listener,
)

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("DROP INDEX IF EXISTS uq_roles_global_name")
    register_tenant_scope_listener()
    yield engine
    await engine.dispose()


def _sessions(engine):
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return SessionLocal


# ── Domain group definitions ─────────────────────────────────────────────────
#
# Each entry: (label, factory(db) -> model instance with tenant_id=TENANT_B
# and one with TENANT_A).  Factories insert rows for BOTH tenants so the
# isolation assertions run per domain group.


async def _mk_identity(db):
    from app.db.models.identity import Role

    return [
        Role(name=f"role-a-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_A),
        Role(name=f"role-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B),
    ]


async def _mk_agent_domain(db):
    from app.db.models.agents import AgentType, AgentRole, AgentIdentity

    role_a = AgentRole(name=f"arole-a-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_A)
    role_b = AgentRole(name=f"arole-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B)
    at_a = AgentType(name=f"atype-a-{uuid.uuid4().hex[:6]}", role=role_a, tenant_id=TENANT_A)
    at_b = AgentType(name=f"atype-b-{uuid.uuid4().hex[:6]}", role=role_b, tenant_id=TENANT_B)
    ident_b = AgentIdentity(
        name=f"ident-b-{uuid.uuid4().hex[:6]}",
        identity_type="service_account",
        tenant_id=TENANT_B,
    )
    db.add_all([role_a, role_b, at_a, at_b, ident_b])
    return [at_b, ident_b]


async def _mk_mcp_skills(db):
    from app.db.models.mcp_hub import McpServer
    from app.db.models.skills import Skill, Sop

    suffix = uuid.uuid4().hex[:6]
    server_b = McpServer(
        name=f"srv-b-{suffix}",
        slug=f"srv-b-{suffix}",
        base_url="http://b.example.com",
        tenant_id=TENANT_B,
    )
    skill_b = Skill(name=f"skill-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B)
    sop_b = Sop(name=f"sop-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B)
    return [server_b, skill_b, sop_b]


async def _mk_conversations_results(db):
    from app.db.models.conversations import ConversationSession
    from app.db.models.results import ResultRecord
    from app.db.models.agent_data import AgentData
    from app.db.models.agent_data_type import AgentDataType

    suffix = uuid.uuid4().hex[:6]
    dtype_b = AgentDataType(
        name=f"dt-b-{suffix}", slug=f"dt-b-{suffix}", fields=[{"name": "v", "type": "string"}],
        tenant_id=TENANT_B,
    )
    conv_b = ConversationSession(title="b-session", tenant_id=TENANT_B)
    result_b = ResultRecord(
        title="b-result", payload={"k": "b"}, tenant_id=TENANT_B
    )
    data_b = AgentData(
        data_name=f"data-b-{suffix}", data_value={"v": "b"}, tenant_id=TENANT_B
    )
    db.add_all([dtype_b, conv_b, result_b, data_b])
    return [dtype_b, conv_b, result_b, data_b]


async def _mk_model_governance(db):
    from app.db.models.agents import ModelConfig

    b = ModelConfig(
        display_name=f"model-b-{uuid.uuid4().hex[:6]}",
        provider_type="openai",
        tenant_id=TENANT_B,
    )
    db.add(b)
    return [b]


async def _mk_api_keys(db):
    from app.db.models.agent_api_key import AgentApiKey
    from app.db.models.agents import AgentIdentity, AgentRole

    role_b = AgentRole(name=f"keyrole-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B)
    ident_b = AgentIdentity(
        name=f"keyident-b-{uuid.uuid4().hex[:6]}",
        identity_type="service_account",
        tenant_id=TENANT_B,
    )
    db.add_all([role_b, ident_b])
    await db.flush()
    suffix = uuid.uuid4().hex[:6]
    key_b = AgentApiKey(
        name=f"key-b-{suffix}",
        key_hash="b" * 64,
        key_prefix="bbbb",
        agent_identity_id=ident_b.id,
        agent_role_id=role_b.id,
        tenant_id=TENANT_B,
    )
    db.add(key_b)
    return [key_b]


async def _mk_notifications(db):
    from app.db.models.notifications import NotificationChannel

    b = NotificationChannel(
        name=f"chan-b-{uuid.uuid4().hex[:6]}",
        channel_type="webhook",
        tenant_id=TENANT_B,
    )
    db.add(b)
    return [b]


async def _mk_scheduling(db):
    from app.db.models.scheduling import ScheduledJob

    b = ScheduledJob(
        name=f"job-b-{uuid.uuid4().hex[:6]}",
        cron_expression="*/5 * * * *",
        target_type="prompt",
        target_id=uuid.uuid4(),
        tenant_id=TENANT_B,
    )
    db.add(b)
    return [b]


DOMAIN_GROUPS = [
    ("identity_roles", _mk_identity),
    ("agent_domain", _mk_agent_domain),
    ("mcp_skills_sops", _mk_mcp_skills),
    ("conversations_results_data", _mk_conversations_results),
    ("model_governance", _mk_model_governance),
    ("api_keys", _mk_api_keys),
    ("notifications", _mk_notifications),
    ("scheduling", _mk_scheduling),
]


# ── Per-group isolation matrix ───────────────────────────────────────────────


@pytest.mark.parametrize("label,factory", DOMAIN_GROUPS, ids=[g[0] for g in DOMAIN_GROUPS])
class TestCrossTenantIsolationPerDomain:
    async def _scoped_pair(self, engine, factory):
        """Seed B rows (via factory), then open a tenant-A scoped session."""
        SessionLocal = _sessions(engine)
        async with SessionLocal() as seeder:
            rows_b = await factory(seeder)
            await seeder.commit()
            foreign_ids = {
                type(r).__name__: str(r.id) for r in rows_b if getattr(r, "id", None)
            }
        scoped = SessionLocal()
        apply_tenant_scope(scoped, TENANT_A)
        return scoped, rows_b, foreign_ids

    async def test_list_excludes_tenant_b(self, engine, label, factory):
        scoped, rows_b, _ = await self._scoped_pair(engine, factory)
        model = type(rows_b[0])
        visible = (await scoped.execute(select(model))).scalars().all()
        visible_ids = {str(r.id) for r in visible}
        for row in rows_b:
            assert str(row.id) not in visible_ids, f"{label}: tenant B row leaked in list"
        await scoped.rollback()
        await scoped.close()

    async def test_direct_address_yields_none_and_audits(self, engine, label, factory):
        """CS-12: direct-addressed foreign ids yield 404-equivalent + audit."""
        scoped, rows_b, _ = await self._scoped_pair(engine, factory)
        target = rows_b[0]
        fetched = await scoped.get(type(target), target.id)
        assert fetched is None, f"{label}: foreign row reachable via get()"

        await flush_scope_miss_audits(scoped)
        await scoped.commit()

        SessionLocal = _sessions(engine)
        async with SessionLocal() as checker:
            from app.db.models.tenant_audit_event import (
                TenantAuditEvent,
                TenantAuditEventType,
            )

            events = (
                await checker.execute(
                    select(TenantAuditEvent).where(
                        TenantAuditEvent.tenant_id == TENANT_A,
                        TenantAuditEvent.event_type
                        == TenantAuditEventType.cross_tenant_access_denied,
                        TenantAuditEvent.is_security_relevant.is_(True),
                    )
                )
            ).scalars().all()
            assert len(events) >= 1, f"{label}: cross-tenant probe not audited"
        await scoped.close()

    async def test_update_cannot_modify_tenant_b(self, engine, label, factory):
        scoped, rows_b, _ = await self._scoped_pair(engine, factory)
        target = rows_b[0]
        model = type(target)
        result = await scoped.execute(
            update(model).where(model.id == target.id).values(tenant_id=TENANT_A)
        )
        await scoped.commit()
        assert result.rowcount == 0, f"{label}: tenant B row was modified"
        await scoped.close()

    async def test_delete_cannot_remove_tenant_b(self, engine, label, factory):
        scoped, rows_b, _ = await self._scoped_pair(engine, factory)
        target = rows_b[0]
        model = type(target)
        result = await scoped.execute(delete(model).where(model.id == target.id))
        await scoped.commit()
        assert result.rowcount == 0, f"{label}: tenant B row was deleted"
        await scoped.close()

    async def test_insert_is_stamped_with_tenant_a(self, engine, label, factory):
        """Writes cannot CREATE rows outside the tenant — INSERTs are
        stamped with the session's tenant at the choke point."""
        from app.db.models.identity import Role

        scoped, _, _ = await self._scoped_pair(engine, factory)
        row = Role(name=f"scoped-create-{uuid.uuid4().hex[:6]}")
        scoped.add(row)
        await scoped.flush()
        assert row.tenant_id == TENANT_A, f"{label}: INSERT not stamped with tenant"
        await scoped.rollback()
        await scoped.close()


# ── Join/child-table inheritance through parents (E-01) ──────────────────────


class TestChildTableInheritance:
    async def test_api_key_usage_log_reached_through_scoped_key(self, engine):
        """ApiKeyUsageLog carries NO tenant column; rows for tenant B keys
        are unreachable from a tenant A scoped session via the parent join."""
        from app.db.models.agent_api_key import AgentApiKey, ApiKeyUsageAction, ApiKeyUsageLog
        from app.db.models.agents import AgentIdentity, AgentRole

        SessionLocal = _sessions(engine)
        async with SessionLocal() as seeder:
            role_a = AgentRole(name=f"u-role-a-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_A)
            role_b = AgentRole(name=f"u-role-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B)
            ident_a = AgentIdentity(
                name=f"u-ident-a-{uuid.uuid4().hex[:6]}",
                identity_type="service_account",
                tenant_id=TENANT_A,
            )
            ident_b = AgentIdentity(
                name=f"u-ident-b-{uuid.uuid4().hex[:6]}",
                identity_type="service_account",
                tenant_id=TENANT_B,
            )
            seeder.add_all([role_a, role_b, ident_a, ident_b])
            await seeder.flush()
            key_a = AgentApiKey(
                name=f"ukey-a-{uuid.uuid4().hex[:6]}", key_hash="a" * 64,
                key_prefix="aaaa",
                agent_role_id=role_a.id, agent_identity_id=ident_a.id,
                tenant_id=TENANT_A,
            )
            key_b = AgentApiKey(
                name=f"ukey-b-{uuid.uuid4().hex[:6]}", key_hash="b" * 64,
                key_prefix="bbbb",
                agent_role_id=role_b.id, agent_identity_id=ident_b.id,
                tenant_id=TENANT_B,
            )
            seeder.add_all([key_a, key_b])
            await seeder.flush()
            log_a = ApiKeyUsageLog(api_key_id=key_a.id, action=ApiKeyUsageAction.validate)
            log_b = ApiKeyUsageLog(api_key_id=key_b.id, action=ApiKeyUsageAction.validate)
            seeder.add_all([log_a, log_b])
            await seeder.commit()
            foreign_log_id = log_b.id

        scoped = SessionLocal()
        apply_tenant_scope(scoped, TENANT_A)
        visible = (
            await scoped.execute(
                select(ApiKeyUsageLog).join(
                    AgentApiKey, AgentApiKey.id == ApiKeyUsageLog.api_key_id
                )
            )
        ).scalars().all()
        visible_ids = {str(r.id) for r in visible}
        assert str(foreign_log_id) not in visible_ids, (
            "ApiKeyUsageLog of tenant B key leaked through the parent join"
        )
        await scoped.rollback()
        await scoped.close()

    async def test_user_role_rows_follow_parent_role_tenant(self, engine):
        from app.db.models.identity import Role
        from app.db.models.user_role import UserRole

        SessionLocal = _sessions(engine)
        user_a, user_b = uuid.uuid4(), uuid.uuid4()
        async with SessionLocal() as seeder:
            role_a = Role(name=f"ur-a-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_A)
            role_b = Role(name=f"ur-b-{uuid.uuid4().hex[:6]}", tenant_id=TENANT_B)
            seeder.add_all([role_a, role_b])
            await seeder.flush()
            seeder.add_all(
                [
                    UserRole(user_id=user_a, role_id=role_a.id),
                    UserRole(user_id=user_b, role_id=role_b.id),
                ]
            )
            await seeder.commit()
            foreign_pair = (user_b, role_b.id)

        scoped = SessionLocal()
        apply_tenant_scope(scoped, TENANT_A)
        visible = set(
            (
                await scoped.execute(
                    select(UserRole.user_id, UserRole.role_id).join(
                        Role, Role.id == UserRole.role_id
                    )
                )
            ).all()
        )
        assert foreign_pair not in visible, "tenant B UserRole leaked via parent join"
        await scoped.rollback()
        await scoped.close()
