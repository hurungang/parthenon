"""Scenario 3 — fail-closed internal endpoints.

Every ``/api/v1/internal/*`` data-plane router must enforce the signed
``X-Internal-Tenant-*`` context via ``require_internal_tenant_context``:

- present-but-invalid / tampered / stale headers → 401
- headerless with multi-tenancy ON → 401 (before any DB access)
- headerless with multi-tenancy OFF → root tenant bound (single-tenant
  regression safety)
- valid signed headers → request proceeds bound to the signed tenant

Structural checks verify the dependency is attached to every data-plane
internal router, so a future router cannot silently ship fail-open.
"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.tenant_signature import (
    TENANT_ID_HEADER,
    TENANT_SIGNATURE_HEADER,
    TENANT_SLUG_HEADER,
    TENANT_TIMESTAMP_HEADER,
    build_tenant_signature_headers,
)
from app.core.tenant_context import TenantContext

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()

# Every internal DATA-PLANE router module (fail-closed requirement).
_DATA_PLANE_ROUTER_MODULES = [
    "app.api.v1.internal.system_tools",
    "app.api.v1.internal.session_data",
    "app.api.v1.internal.outputs",
    "app.api.v1.internal.agent_data",
    "app.api.v1.internal.mcp_proxy",
    "app.api.v1.internal.authorization",
]


def _tenant_ctx(tenant_id, slug: str) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, slug=slug, name=slug)


@pytest.fixture
def app_with_dependency(db):
    """Minimal app exposing the real fail-closed dependency."""
    from app.api.deps import require_internal_tenant_context
    from app.db.session import get_db

    app = FastAPI()

    @app.get("/probe")
    async def probe(tenant_ctx=Depends(require_internal_tenant_context)):
        return {"tenant_id": str(tenant_ctx.tenant_id), "slug": tenant_ctx.slug}

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
async def client(app_with_dependency):
    transport = ASGITransport(app=app_with_dependency)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mt_on(monkeypatch):
    """Force the multi-tenancy switch ON for the dependency's DB check."""

    class _FakeSettings:
        async def is_multi_tenancy_enabled(self, db):  # noqa: ANN001
            return True

    import app.services.tenancy.platform_settings_service as pss

    monkeypatch.setattr(pss, "get_platform_settings_service", lambda: _FakeSettings())


@pytest.fixture
def mt_off(monkeypatch):
    """Force the multi-tenancy switch OFF and a provisioned root tenant."""

    class _FakeSettings:
        async def is_multi_tenancy_enabled(self, db):  # noqa: ANN001
            return False

    import app.services.tenancy.platform_settings_service as pss

    monkeypatch.setattr(pss, "get_platform_settings_service", lambda: _FakeSettings())


class TestFailClosedHeaders:
    async def test_headerless_with_tenancy_on_is_401(self, client, mt_on, db):
        response = await client.get("/probe")
        assert response.status_code == 401

    async def test_tampered_signature_is_401(self, client, mt_on, db):
        tenant_a, _ = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_tenant_ctx(tenant_a.id, tenant_a.slug))
        headers[TENANT_SIGNATURE_HEADER] = "0" * 64
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 401

    async def test_stale_timestamp_is_401(self, client, mt_on, db):
        tenant_a, _ = await create_two_tenants(db)
        headers = build_tenant_signature_headers(
            _tenant_ctx(tenant_a.id, tenant_a.slug),
            timestamp=time.time() - 3600,  # far outside the replay window
        )
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 401

    async def test_partial_header_set_is_401(self, client, mt_on, db):
        tenant_a, _ = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_tenant_ctx(tenant_a.id, tenant_a.slug))
        headers.pop(TENANT_TIMESTAMP_HEADER)
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 401

    async def test_id_slug_mismatch_is_401(self, client, mt_on, db):
        tenant_a, tenant_b = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_tenant_ctx(tenant_a.id, tenant_a.slug))
        # Swap in tenant B's slug without re-signing.
        headers[TENANT_SLUG_HEADER] = tenant_b.slug
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 401

    async def test_malformed_tenant_id_is_401(self, client, mt_on, db):
        headers = {
            TENANT_ID_HEADER: "not-a-uuid",
            TENANT_SLUG_HEADER: "x",
            TENANT_TIMESTAMP_HEADER: str(int(time.time())),
            TENANT_SIGNATURE_HEADER: "ab" * 32,
        }
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 401

    async def test_valid_signed_headers_pass_and_bind_tenant(self, client, mt_on, db):
        tenant_a, _ = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_tenant_ctx(tenant_a.id, tenant_a.slug))
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(tenant_a.id)
        assert response.json()["slug"] == tenant_a.slug


class TestSingleTenantRegression:
    async def test_headerless_with_tenancy_off_binds_root(self, client, mt_off, monkeypatch, db):
        from app.db.models.tenant import Tenant
        from app.services.tenancy import root_tenant

        suffix = uuid.uuid4().hex[:6]
        root = Tenant(
            name=f"root-{suffix}", slug="root", is_system_tenant=True
        )
        db.add(root)
        await db.commit()
        # Short-TTL cache may hold a stale value from other tests — reset it.
        monkeypatch.setattr(root_tenant, "_root_context_cache", None)

        response = await client.get("/probe")
        assert response.status_code == 200
        assert response.json()["slug"] == "root"


class TestDependencyAttachedToAllDataPlaneRouters:
    @pytest.mark.parametrize("module_name", _DATA_PLANE_ROUTER_MODULES)
    async def test_router_enforces_internal_tenant_context(self, module_name):
        """Structural fail-closed guarantee: the signed-tenant dependency is
        attached to every route of every internal data-plane router."""
        import importlib

        from app.api.deps import require_internal_tenant_context

        module = importlib.import_module(module_name)
        routers = [
            obj
            for obj in vars(module).values()
            if hasattr(obj, "routes") and hasattr(obj, "dependencies")
        ]
        assert routers, f"no APIRouter found in {module_name}"
        for router in routers:
            for route in router.routes:
                attached = any(
                    getattr(dep, "dependency", None) is require_internal_tenant_context
                    for dep in getattr(route, "dependencies", [])
                ) or any(
                    dep.call is require_internal_tenant_context
                    for dep in getattr(getattr(route, "dependant", None), "dependencies", [])
                )
                assert attached, (
                    f"{module_name} route {getattr(route, 'path', route)} is not "
                    f"protected by require_internal_tenant_context (fail-open!)"
                )
