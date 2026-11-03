"""Database migration tests for ``AgentType.is_system``.

Verifies the ``is_system`` schema change took effect against the real
PostgreSQL (``information_schema`` probe + backfill/default sanity), and that
system agent types are protected from user edit/delete via the REST API
(negative protection test exercising the actual ``agents.py`` handlers).

The information-schema probes require a running PostgreSQL (this file is
registered in ``_DB_DEPENDENT_FILES``); the negative-protection test runs
against the SQLite test engine + the real app with auth/permission overridden.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT
from app.db.models.agents import AgentType
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


@pytest.fixture(scope="module")
def real_db_url():
    """Real PostgreSQL URL (the ``parthenon`` dev DB running in Docker)."""
    url = os.environ.get("DATABASE_URL", "")
    if "parthenon_test" in url or not url:
        url = "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon"
    if "postgresql://" in url and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif "postgresql+psycopg2://" in url:
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


# ── Schema verification (real PostgreSQL) ───────────────────────────────────


@pytest.mark.asyncio
async def test_agent_types_is_system_column_schema(real_db_url):
    """``agent_types.is_system`` exists, is boolean, NOT NULL, default false."""
    engine = create_async_engine(real_db_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(
            text(
                """
                SELECT data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'agent_types' AND column_name = 'is_system'
                """
            )
        )
        row = result.fetchone()
        assert row is not None, "agent_types.is_system column must exist"
        data_type, is_nullable, column_default = row
        assert data_type == "boolean"
        assert is_nullable == "NO"
        assert column_default is not None
        assert "false" in column_default.lower()

    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_types_is_system_no_null_values(real_db_url):
    """No existing ``is_system`` value may be NULL (NOT NULL + default backfill)."""
    engine = create_async_engine(real_db_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM agent_types WHERE is_system IS NULL")
        )
        count = result.scalar()
        assert count == 0

    await engine.dispose()


# ── Negative protection: system agent types are read-only ───────────────────


@pytest_asyncio.fixture
async def client(test_engine):
    app = create_app()

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_permission(RT_AGENT, "update")] = _allow_all()
    app.dependency_overrides[require_permission(RT_AGENT, "delete")] = _allow_all()

    with _bypass_auth():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def _seed_agent_type(test_engine, *, is_system: bool, name: str) -> str:
    from app.db.models.agents import AgentInputType, AgentOutputType
    from app.services.tenancy.root_tenant import get_root_tenant_id

    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as session:
        root_id = await get_root_tenant_id(session)
        at = AgentType(
            tenant_id=root_id,
            name=name,
            is_system=is_system,
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
            is_active=True,
        )
        session.add(at)
        await session.commit()
        return str(at.id)


@pytest.mark.asyncio
async def test_system_agent_type_update_is_rejected(client, test_engine) -> None:
    name = f"e2e-system-type-{uuid.uuid4().hex[:8]}"
    type_id = await _seed_agent_type(test_engine, is_system=True, name=name)

    response = await client.put(
        f"/api/v1/agents/types/{type_id}",
        json={"name": name + "-edited"},
    )
    assert response.status_code == 403, response.text
    assert "System agent types cannot be modified" in response.json()["detail"]


@pytest.mark.asyncio
async def test_system_agent_type_delete_is_rejected(client, test_engine) -> None:
    name = f"e2e-system-type-{uuid.uuid4().hex[:8]}"
    type_id = await _seed_agent_type(test_engine, is_system=True, name=name)

    response = await client.delete(f"/api/v1/agents/types/{type_id}")
    assert response.status_code == 403, response.text
    assert "System agent types cannot be deleted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_non_system_agent_type_delete_is_allowed(client, test_engine) -> None:
    """Regression: non-system agent types remain deletable."""
    name = f"e2e-normal-type-{uuid.uuid4().hex[:8]}"
    type_id = await _seed_agent_type(test_engine, is_system=False, name=name)

    response = await client.delete(f"/api/v1/agents/types/{type_id}")
    assert response.status_code == 204, response.text

    # Confirm it was actually deleted.
    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as session:
        row = (
            await session.execute(select(AgentType).where(AgentType.id == uuid.UUID(type_id)))
        ).scalar_one_or_none()
        assert row is None


@pytest.mark.asyncio
async def test_non_system_agent_type_update_not_system_protected(
    client, test_engine
) -> None:
    """Regression: non-system agent types do not hit the system-protection 403."""
    name = f"e2e-normal-type-{uuid.uuid4().hex[:8]}"
    type_id = await _seed_agent_type(test_engine, is_system=False, name=name)

    response = await client.put(
        f"/api/v1/agents/types/{type_id}",
        json={"name": name + "-edited"},
    )
    # Not 403 (the system-protection branch).  The request may still fail on
    # binding validation (400/422), but it must NOT be a system-protection 403.
    assert response.status_code != 403
