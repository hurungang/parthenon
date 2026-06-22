"""Pytest configuration and shared fixtures."""
import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
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
    services_running = all(
        _is_service_available(p) for p in (8000, 8001, 8002)
    )
    for item in items:
        rel_path = item.nodeid.split("::")[0]
        norm = os.path.normpath(rel_path).replace(os.sep, "/")
        if norm in _SERVICE_DEPENDENT_FILES and not services_running:
            item.add_marker(skip_services)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


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
