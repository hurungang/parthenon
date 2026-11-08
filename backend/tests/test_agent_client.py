"""Tests for third-party agent-integration clients (model + service layer).

Covers: schema presence, credential generation/hashing, lookup, expiry,
duplicate checks, usage logging, and revocation behaviour. A client is an
access grant bound to one agent type (input-interface only) — never an identity.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload

from app.db.models.agent_client import (
    AgentClient,
    AgentClientAction,
    AgentClientKeyType,
    AgentClientRateLimitWindow,
    AgentClientStatus,
    AgentClientUsageLog,
)
from app.db.models.agents import AgentInputType, AgentType
from app.db.models.tenant import Tenant
from app.services.agent_client_service import (
    check_duplicate_name,
    check_duplicate_slug,
    create_client_usage_log,
    generate_client_key,
    hash_client_key,
    is_client_expired,
    slugify,
    update_last_used_at,
    validate_client_from_hash,
)


@pytest.mark.asyncio
async def test_agent_client_tables_exist(test_engine):
    """The schema change produced the expected tables and columns."""

    async with test_engine.connect() as conn:

        def _inspect(sync_conn):
            insp = inspect(sync_conn)
            tables = set(insp.get_table_names())
            cols = {c["name"] for c in insp.get_columns("agent_clients")}
            log_cols = {c["name"] for c in insp.get_columns("agent_client_usage_logs")}
            return tables, cols, log_cols

        tables, cols, log_cols = await conn.run_sync(_inspect)

    assert "agent_clients" in tables
    assert "agent_client_usage_logs" in tables

    for c in (
        "id",
        "tenant_id",
        "name",
        "slug",
        "agent_type_id",
        "key_type",
        "key_hash",
        "key_prefix",
        "status",
        "white_label_theme",
        "allowed_origins",
        "rate_limit",
        "rate_limit_window",
        "expires_at",
        "last_used_at",
        "created_by",
        "created_at",
    ):
        assert c in cols, f"missing agent_clients column {c}"

    for c in ("id", "client_id", "action", "ip_address", "timestamp", "success"):
        assert c in log_cols, f"missing agent_client_usage_logs column {c}"


def test_generate_client_key_prefixes():
    raw_s, h_s, p_s = generate_client_key(AgentClientKeyType.secret)
    raw_p, h_p, p_p = generate_client_key(AgentClientKeyType.publishable)

    assert raw_s.startswith("phn_cl_sk_")
    assert raw_p.startswith("phn_cl_pk_")
    assert p_s == "phn_cl_sk_"
    assert p_p == "phn_cl_pk_"
    assert hash_client_key(raw_s) == h_s
    assert len(h_s) == 64
    assert raw_s != raw_p  # distinct random material


def test_slugify():
    assert slugify("Acme Support Bot") == "acme-support-bot"
    assert slugify("  --weird--  ") == "weird"
    assert slugify("") == "client"


@pytest.mark.asyncio
async def test_client_lifecycle(db_session):
    tenant = (
        await db_session.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))
    ).scalar_one()

    agent_type = AgentType(
        name="Support Bot",
        tenant_id=tenant.id,
        input_type=AgentInputType.conversation,
    )
    db_session.add(agent_type)
    await db_session.flush()

    raw, key_hash, prefix = generate_client_key(AgentClientKeyType.publishable)
    client = AgentClient(
        tenant_id=tenant.id,
        name="Acme",
        slug="acme",
        agent_type_id=agent_type.id,
        key_type=AgentClientKeyType.publishable,
        key_hash=key_hash,
        key_prefix=prefix,
        status=AgentClientStatus.active,
        white_label_theme={"name": "Acme Bot", "color": "#6D28D9"},
        allowed_origins=["https://acme.com"],
        rate_limit=100,
        rate_limit_window=AgentClientRateLimitWindow.per_minute,
    )
    db_session.add(client)
    await db_session.flush()

    # Lookup by hash succeeds and is not expired.
    found = await validate_client_from_hash(key_hash, db_session)
    assert found is not None and found.id == client.id
    assert not is_client_expired(client)
    assert found.key_type == AgentClientKeyType.publishable

    # Expiry: a past timestamp is expired.
    client.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()
    assert is_client_expired(client)

    # Usage log + last_used_at.
    await create_client_usage_log(
        client.id,
        AgentClientAction.conversation_turn,
        db_session,
        success=True,
        ip_address="127.0.0.1",
    )
    await update_last_used_at(client.id, db_session)
    logs = (
        await db_session.execute(
            select(AgentClientUsageLog).where(AgentClientUsageLog.client_id == client.id)
        )
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].action == AgentClientAction.conversation_turn
    assert logs[0].ip_address == "127.0.0.1"

    # Duplicate checks are tenant-scoped.
    assert await check_duplicate_name("Acme", db_session, tenant_id=tenant.id)
    assert not await check_duplicate_name("Other", db_session, tenant_id=tenant.id)
    assert await check_duplicate_slug("acme", db_session, tenant_id=tenant.id)

    # Revocation makes the credential unresolvable.
    client.status = AgentClientStatus.revoked
    await db_session.flush()
    assert await validate_client_from_hash(key_hash, db_session) is None


@pytest.mark.asyncio
async def test_inactive_client_is_not_resolvable_and_can_reactivate(db_session):
    """Deactivating a client rejects its credential; reactivating restores it."""
    tenant = (
        await db_session.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))
    ).scalar_one()
    agent_type = AgentType(name="Toggle Bot", tenant_id=tenant.id, input_type=AgentInputType.typed)
    db_session.add(agent_type)
    await db_session.flush()

    raw, key_hash, prefix = generate_client_key(AgentClientKeyType.secret)
    client = AgentClient(
        tenant_id=tenant.id,
        name="Toggle",
        slug="toggle",
        agent_type_id=agent_type.id,
        key_type=AgentClientKeyType.secret,
        key_hash=key_hash,
        key_prefix=prefix,
        status=AgentClientStatus.active,
    )
    db_session.add(client)
    await db_session.flush()

    assert await validate_client_from_hash(key_hash, db_session) is not None

    client.status = AgentClientStatus.inactive
    await db_session.flush()
    assert await validate_client_from_hash(key_hash, db_session) is None

    client.status = AgentClientStatus.active
    await db_session.flush()
    assert await validate_client_from_hash(key_hash, db_session) is not None


@pytest.mark.asyncio
async def test_client_bound_to_single_agent_type(db_session):
    """A client is bound to exactly one agent type; the relationship resolves."""
    tenant = (
        await db_session.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))
    ).scalar_one()
    agent_type = AgentType(name="Triage", tenant_id=tenant.id, input_type=AgentInputType.typed)
    db_session.add(agent_type)
    await db_session.flush()

    raw, key_hash, prefix = generate_client_key(AgentClientKeyType.secret)
    client = AgentClient(
        tenant_id=tenant.id,
        name="Nimbus",
        slug="nimbus",
        agent_type_id=agent_type.id,
        key_type=AgentClientKeyType.secret,
        key_hash=key_hash,
        key_prefix=prefix,
        status=AgentClientStatus.active,
    )
    db_session.add(client)
    await db_session.flush()

    # The AgentType 1:N relationship resolves both directions (eager-loaded).
    refreshed = (
        await db_session.execute(
            select(AgentType)
            .where(AgentType.id == agent_type.id)
            .options(selectinload(AgentType.clients))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert any(c.id == client.id for c in refreshed.clients)
    assert client.agent_type_id == agent_type.id
