"""
conftest.py for service-decomposition tests.

Provides an `async_client` fixture variant that bypasses JWT middleware by
adding /api/v1/mcp to the public paths for the duration of the test session.
Also provides a stub identity via `require_permission` override so that
endpoints with permission checks return 409/201 rather than 403.
"""
import asyncio
import os
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Patch PUBLIC_PATHS BEFORE the app is imported to avoid 401 from JWTAuthMiddleware
import app.middleware.auth as _auth_mod

_ADDED_PATHS: set[str] = {
    "/api/v1/mcp/servers",
    "/api/v1/mcp/servers/",
}
_auth_mod.PUBLIC_PATHS = _auth_mod.PUBLIC_PATHS | _ADDED_PATHS


def _permission_bypass():
    """Stub require_permission that grants access to all requests in tests."""
    async def _dep():  # no Request / db needed
        return {"sub": "test-service-decomposition", "roles": ["admin"]}
    return _dep


@pytest_asyncio.fixture
async def async_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """
    Override parent conftest's async_client for service-decomposition tests.

    Differences from the parent fixture:
    - Overrides require_permission for mcp_server create to return a stub admin
      identity, bypassing the real permission engine.
    """
    from app.db.session import get_db
    from app.main import create_app
    from app.api.deps import require_permission

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

    # Override all require_permission(mcp_server, *) calls so tests don't
    # need a real JWT or a PlatformUser row in the DB.
    from app.api.v1 import mcp_hub  # noqa: F401
    RT_MCP_SERVER = mcp_hub.RT_MCP_SERVER
    for action in ("read", "create", "update", "delete", "manage"):
        dep = require_permission(RT_MCP_SERVER, action)
        app.dependency_overrides[dep] = _permission_bypass()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
