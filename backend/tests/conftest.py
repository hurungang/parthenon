"""Pytest configuration and shared fixtures."""
import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncGenerator

# Make the repo-root ``setup`` package importable regardless of the pytest
# working directory (CI runs pytest from ``backend/``, developers often run it
# from the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── SQLite type-affinity shim ────────────────────────────────────────────────
# Models declare UUID columns with ``postgresql.UUID``. SQLite has no UUID type,
# so the bare ``UUID`` DDL gets NUMERIC affinity and reserved values such as
# ``00000000-…-000000000003`` are silently stored as the integer 3, which then
# blows up UUID result processing. Compile those columns as CHAR(32) (the
# layout SQLAlchemy itself uses for ``Uuid`` on SQLite).
from sqlalchemy.dialects.postgresql import UUID as _PgUUID
from sqlalchemy.ext.compiler import compiles as _compiles


@_compiles(_PgUUID, "sqlite")
def _compile_pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ARG001
    return "CHAR(32)"

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment variables before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("OIDC_PROVIDER_URL", "http://localhost:8080/realms/parthenon")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.session import Base, get_db
from app.main import create_app

# Use SQLite for unit tests to avoid needing Postgres
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# ── Dynamic test skipping ─────────────────────────────────────────────────

_SERVICE_DEPENDENT_FILES = {
    "tests/integration/test_nonconv_agent_mcp_tools.py",
    "tests/integration/test_service_triggers.py",
    "tests/integration/test_runtime_control_persistence.py",
    "tests/integration/test_internal_auth_security.py",
    "tests/integration/test_mcp_hub.py",
    "tests/integration/test_mcp_session_identity_lookup.py",
    "tests/integration/test_skill_system_tools.py",
    "tests/integration/test_enhance_mcp_hub_skills_sops_db.py",
    "tests/integration/test_startup_session_cleanup.py",
    "tests/integration/test_agent_execution_with_logs.py",
    "tests/integration/test_system_tool_schemas.py",
    "tests/api/v1/test_model_availability_api.py",
    "tests/api/v1/test_model_usage_guardrails_api.py",
    "tests/api/v1/test_agent_runtime_controls_api.py",
    "tests/api/v1/test_intervene.py",
    "tests/integration/test_websocket_communication_hub.py",
}

# Files whose tests require a live PostgreSQL database (localhost:5432)
_DB_DEPENDENT_FILES = {
    "tests/db/test_namespace_migration.py",
    "tests/db/test_agent_type_is_system_migration.py",
}

# Individual tests (within otherwise-runnable files) that require PostgreSQL
_DB_DEPENDENT_TESTS = {
    "tests/integration/test_namespace_permission_evaluation.py": {
        "test_db_can_connect_and_query_schema",
        "test_policy_statements_module_is_varchar_100_not_null",
    },
}


def _is_service_available(port: int) -> bool:
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    skip_services = pytest.mark.skip(reason="Requires running services (CC, AR, or CH)")
    skip_db = pytest.mark.skip(reason="Requires a running PostgreSQL database (localhost:5432)")
    services_running = all(
        _is_service_available(p) for p in (8000, 8001, 8002)
    )
    postgres_running = _is_service_available(5432)
    for item in items:
        rel_path = item.nodeid.split("::")[0]
        norm = os.path.normpath(rel_path).replace(os.sep, "/")
        if norm in _SERVICE_DEPENDENT_FILES and not services_running:
            item.add_marker(skip_services)
        if norm in _DB_DEPENDENT_FILES and not postgres_running:
            item.add_marker(skip_db)
        elif item.name in _DB_DEPENDENT_TESTS.get(norm, set()) and not postgres_running:
            item.add_marker(skip_db)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def _migrate_postgres_test_db():
    """Apply Alembic migrations to the PostgreSQL test database once per session.

    Request middleware (tenant resolution, root-tenant lookup) uses the real
    ``AsyncSessionLocal`` engine — it is not covered by FastAPI dependency
    overrides — so the Postgres test DB must have the schema. The QA strategy
    already requires this ("test database fixture applies migrations").
    """
    if not _is_service_available(5432):
        yield
        return

    import subprocess

    backend_root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "DATABASE_URL": (
            "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test"
        ),
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(backend_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            print(
                "WARNING: could not migrate parthenon_test — middleware-backed "
                f"tests may fail:\n{result.stderr[-2000:]}"
            )
    except Exception as exc:  # noqa: BLE001 — never block the unit suite
        print(f"WARNING: alembic upgrade skipped: {exc}")
    yield


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # strict-tenant-isolation: internal data-plane endpoints resolve the
    # ROOT tenant when multi-tenancy is off; tests driving the app
    # headerless need the root tenant provisioned in the test database.
    from app.db.models.tenant import Tenant

    async with async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )() as session:
        existing = (
            await session.execute(
                select(Tenant).where(Tenant.is_system_tenant.is_(True))
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Tenant(
                    name="Root",
                    slug="root",
                    is_system_tenant=True,
                )
            )
            await session.commit()
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True, scope="module")
async def _isolate_module_database(test_engine):
    """Reset committed state between test modules.

    The test engine is session-scoped and some suites must ``commit()`` (seeder,
    migration and API-path tests). Those commits survive the per-test rollback
    and would otherwise leak into every later module, making population-wide
    assertions order-dependent. Truncate everything except the root tenant at
    module teardown so each module starts from the same baseline.
    """
    yield
    from app.db.models.tenant import Tenant
    from app.db.session import Base

    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name == "tenants":
                continue
            await conn.execute(table.delete())
        await conn.execute(
            Tenant.__table__.delete().where(Tenant.is_system_tenant.is_(False))
        )

    # Re-provision the baseline root tenant: some suites legitimately delete it
    # (platform-tenancy toggles), but every later module must start from the
    # same session baseline that ``test_engine`` seeds.
    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as session:
        existing = (
            await session.execute(
                select(Tenant).where(Tenant.is_system_tenant.is_(True))
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(Tenant(name="Root", slug="root", is_system_tenant=True))
            await session.commit()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session for tests."""
    TestSessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client with DB override."""
    TestSessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with TestSessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def _fresh_root_tenant_cache():
    """Phase 11: isolate the process-wide root-tenant TTL cache per test.

    Tests seed different root tenants (fixtures use their own sqlite
    engines); the production 30s cache would otherwise leak an id across
    tests.  Cheap (a global reset) and production behaviour is untouched.
    """
    from app.services.tenancy.root_tenant import invalidate_root_tenant_cache

    invalidate_root_tenant_cache()
    yield
    invalidate_root_tenant_cache()
