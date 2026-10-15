"""Integration test fixtures and skip conditions.

Skip conditions are evaluated at test collection time (not import time) to
avoid side effects from external-service availability checks.
"""
import pytest
import os
import pytest_asyncio


def _is_service_available(port: int) -> bool:
    """Return True if a TCP service is listening on localhost:port."""
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


def _requires_running_services() -> bool:
    """Return True if all required backend services are available."""
    return all(
        _is_service_available(port) for port in (8000, 8001, 8002)
    )


# -- Dynamic skip: service-dependent files --------------------------------------

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


def pytest_collection_modifyitems(config, items):
    skip_services = pytest.mark.skip(reason="Requires running services (CC, AR, or CH)")
    skip_bug = pytest.mark.skip(reason="Pre-existing bug — not from this change")

    for item in items:
        nodeid = item.nodeid
        rel_path = nodeid.split("::")[0]

        # Skip service-dependent files when services are not running
        if rel_path in _SERVICE_DEPENDENT_FILES and not _requires_running_services():
            item.add_marker(skip_services)


# ── Decision Model Providers (decision-model-providers change) ────────────────

import uuid as _uuid

from httpx import ASGITransport, AsyncClient as _AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker as _asm

from app.api.deps import require_permission as _require_permission
from app.db.session import get_db as _get_db
from app.main import create_app as _create_app

PROVIDERS_URL = "/api/v1/system-one/providers"
MODELS_URL = "/api/v1/system-one/models"
ENABLED_MODELS_URL = "/api/v1/system-one/enabled-models"
DT_ENABLED_MODELS_URL = "/api/v1/decision-tools/enabled-models"


def _bypass_jwt():
    """Patch JWTAuthMiddleware to inject identity claims without a real JWT."""
    from unittest.mock import patch as _patch

    from app.middleware.auth import JWTAuthMiddleware

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


async def _clean_decision_tables(session):
    from app.db.models.decision_model_availability import DecisionModelAvailability
    from app.db.models.decision_tools import DecisionTool
    from app.db.models.results import DecisionExecutionResult
    from app.db.models.system_one_provider_config import SystemOneProviderConfig

    await session.execute(DecisionExecutionResult.__table__.delete())
    await session.execute(DecisionTool.__table__.delete())
    await session.execute(DecisionModelAvailability.__table__.delete())
    await session.execute(SystemOneProviderConfig.__table__.delete())
    await session.commit()


def _fake_tenant_context(module, original):
    """Header-driven tenant context for ``x-test-tenant``."""
    from app.core.tenant_context import TenantContext

    def fake_get_tenant_context(request):
        raw = request.headers.get("x-test-tenant")
        if not raw:
            return original(request)
        return TenantContext(
            tenant_id=_uuid.UUID(raw), slug=f"t-{raw[:8]}", name=f"tenant-{raw[:8]}"
        )

    return fake_get_tenant_context


@pytest_asyncio.fixture
async def providers_client(test_engine):
    """ASGI client with system-one + decision-tools permissions allowed and
    header-driven tenant context (Decision Model Providers CRUD tests)."""
    from app.core.resource_types import (
        RT_AGENT_TRAILS,
        RT_SYSTEM_DECISION_TOOLS,
        RT_SYSTEM_SYSTEM_ONE,
    )

    SessionLocal = _asm(bind=test_engine, class_=_AsyncSession, expire_on_commit=False)

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        await _clean_decision_tables(session)

    app = _create_app()
    app.dependency_overrides[_get_db] = override_db
    for action in ("read", "create", "update", "delete", "manage"):
        app.dependency_overrides[
            _require_permission(RT_SYSTEM_DECISION_TOOLS, action)
        ] = _allow_all()
        app.dependency_overrides[
            _require_permission(RT_SYSTEM_SYSTEM_ONE, action)
        ] = _allow_all()
    app.dependency_overrides[_require_permission(RT_AGENT_TRAILS, "read")] = _allow_all()

    import app.api.v1.decision_tools as dt_api
    import app.api.v1.system_one as so_api

    orig_dt, orig_so = dt_api.get_tenant_context, so_api.get_tenant_context
    dt_api.get_tenant_context = _fake_tenant_context(dt_api, orig_dt)
    so_api.get_tenant_context = _fake_tenant_context(so_api, orig_so)

    with _bypass_jwt():
        async with _AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    dt_api.get_tenant_context = orig_dt
    so_api.get_tenant_context = orig_so


PROVIDER_PAYLOAD = {
    "provider_type": "typesafe",
    "display_name": "E2E Decision Provider",
    "base_url": "http://localhost:9999/v1",
    "default_model": "jev-latest",
    "api_key": "sk-crud-test-key-1234567890",
    "enabled": True,
    "enabled_models": ["jev-latest", "jev-mini"],
}


async def create_provider(client, overrides: dict | None = None, headers: dict | None = None):
    import copy

    payload = {**copy.deepcopy(PROVIDER_PAYLOAD), **(overrides or {})}
    return await client.post(PROVIDERS_URL, json=payload, headers=headers or {})

