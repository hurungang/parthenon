"""Round-2 integration tests: AgentDataType references in decision tools.

Covers:
- tool CRUD accepting + persisting input/output_data_type_id references
  (platform NULL-tenant types referenceable by any tenant; tenant types
  referenceable only within their tenant),
- AgentDataTypeSummary (id/name/slug/fields) present in Read responses,
- auto-generated description derived from the referenced types' fields,
- referenced data type deletion blocked with 409 via the data-types API,
- state preset ``input`` mappings validated against the input type's fields.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import (
    RT_AGENT_DATA_TYPES,
    RT_SYSTEM_DECISION_TOOLS,
    RT_SYSTEM_SYSTEM_ONE,
)
from app.db.models.agent_data_type import AgentDataType
from app.db.models.decision_tools import DecisionTool
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware

TOOLS_URL = "/api/v1/decision-tools"
PROVIDERS_URL = "/api/v1/system-one/providers"
DATA_TYPES_URL = "/api/v1/data-types"

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _bypass_jwt_middleware():
    from unittest.mock import patch as _patch

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


def _tool_body(name: str, input_id=None, output_id=None, state_preset=None):
    return {
        "name": name,
        "purpose": "Decide loan applications (data-type reference tests)",
        "input_data_type_id": input_id,
        "output_data_type_id": output_id,
        "state_preset": state_preset,
        "questions": [
            {
                "question_key": "approve",
                "question_type": "choice",
                "instructions": "Approve this application?",
                "criteria_options": {"yes": "approve", "no": "reject"},
                "ordering": 0,
            },
        ],
    }


async def _clean(session: AsyncSession) -> None:
    from app.db.models.results import DecisionExecutionResult
    from app.db.models.system_one_provider_config import SystemOneProviderConfig

    await session.execute(DecisionExecutionResult.__table__.delete())
    await session.execute(DecisionTool.__table__.delete())
    from app.db.models.system_one_provider_config import SystemOneProviderConfig as P

    await session.execute(P.__table__.delete())
    await session.execute(AgentDataType.__table__.delete())
    await session.commit()


@pytest_asyncio.fixture
async def client(test_engine):
    """App client with decision-tools + data-types + system-one permissions.

    Supports the test-only ``X-Test-Tenant`` tenant context (patched into the
    decision-tools and data-types router modules) for per-tenant scenarios.
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        await _clean(session)

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    for action in ("read", "create", "update", "delete"):
        app.dependency_overrides[
            require_permission(RT_SYSTEM_DECISION_TOOLS, action)
        ] = _allow_all()
        app.dependency_overrides[
            require_permission(RT_AGENT_DATA_TYPES, action)
        ] = _allow_all()
    app.dependency_overrides[
        require_permission(RT_SYSTEM_SYSTEM_ONE, "read")
    ] = _allow_all()
    app.dependency_overrides[
        require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")
    ] = _allow_all()

    import app.api.v1.decision_tools as dt_api
    import app.api.v1.system_one as so_api
    from app.core.tenant_context import TenantContext

    # NOTE: the data-types API is not tenant-context-scoped; only the
    # decision-tools/system-one routers resolve the caller's tenant here.
    modules = [dt_api, so_api]
    originals = [m.get_tenant_context for m in modules]

    def fake_get_tenant_context(request):
        raw = request.headers.get("x-test-tenant")
        if not raw:
            return originals[0](request)
        return TenantContext(
            tenant_id=uuid.UUID(raw), slug=f"t-{raw[:8]}", name=f"tenant-{raw[:8]}"
        )

    for m in modules:
        m.get_tenant_context = fake_get_tenant_context

    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    for m, orig in zip(modules, originals):
        m.get_tenant_context = orig


@pytest_asyncio.fixture
async def provider_configured(client):
    """Enabled provider configs for the root scope + TENANT_A + TENANT_B."""
    for label, tenant in (("root", None), ("a", TENANT_A), ("b", TENANT_B)):
        headers = {"x-test-tenant": str(tenant)} if tenant else {}
        resp = await client.post(
            PROVIDERS_URL,
            json={
                "provider_type": "typesafe",
                "display_name": f"TypeSafe Jev (dt-ref tests, {label})",
                "default_model": "jev-latest",
                "api_key": "sk-dt-ref-test-key-1234567890",
                "enabled": True,
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text


@pytest_asyncio.fixture
async def make_data_type(test_engine):
    """Factory creating AgentDataType rows directly in the test DB."""

    async def _make(name, slug, tenant_id, fields):
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            row = AgentDataType(
                name=name, slug=slug, tenant_id=tenant_id, fields=fields
            )
            session.add(row)
            await session.commit()
            return {"id": str(row.id), "name": name, "slug": slug}

    return _make


LOAN_FIELDS = [
    {"name": "amount", "type": "number", "description": "Requested amount"},
    {"name": "tier", "type": "string", "description": "Customer tier"},
]

RESULT_FIELDS = [
    {"name": "decision", "type": "string", "description": "Final decision"},
]


# ── CRUD with data type references ────────────────────────────────────────


@pytest.mark.asyncio
class TestDataTypeReferences:
    async def test_create_with_platform_and_tenant_types_persists_and_reads_summary(
        self, client, provider_configured, make_data_type
    ):
        # strict-tenant-isolation: the NULL-tenant shared slot is retired —
        # input references must resolve within the creating tenant.
        platform_type = await make_data_type(
            f"loan-{uuid.uuid4().hex[:8]}", f"loan-{uuid.uuid4().hex[:8]}", TENANT_A,
            LOAN_FIELDS,
        )
        tenant_type = await make_data_type(
            f"result-{uuid.uuid4().hex[:8]}",
            f"result-{uuid.uuid4().hex[:8]}",
            TENANT_A,
            RESULT_FIELDS,
        )
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body(
                "typed_tool_a",
                input_id=platform_type["id"],
                output_id=tenant_type["id"],
                state_preset={"tier": {"source": "input", "key": "tier"}},
            ),
            headers={"x-test-tenant": str(TENANT_A)},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["input_data_type_id"] == platform_type["id"]
        assert body["output_data_type_id"] == tenant_type["id"]
        # AgentDataTypeSummary present in reads
        assert body["input_data_type"]["id"] == platform_type["id"]
        assert body["input_data_type"]["slug"] == platform_type["slug"]
        assert {f["name"] for f in body["input_data_type"]["fields"]} == {
            "amount",
            "tier",
        }
        assert body["output_data_type"]["name"] == tenant_type["name"]

        # Read endpoint carries the summaries too
        got = await client.get(
            f"{TOOLS_URL}/{body['id']}", headers={"x-test-tenant": str(TENANT_A)}
        )
        assert got.status_code == 200
        assert got.json()["input_data_type"]["slug"] == platform_type["slug"]

    async def test_platform_null_tenant_type_referenceable_from_any_tenant(
        self, client, provider_configured, make_data_type
    ):
        """strict-tenant-isolation: the NULL-tenant shared slot is retired.
        A legacy NULL-tenant (root-adopted) data type is NOT referenceable
        from a member tenant — references resolve within the calling
        tenant only (fail closed 422)."""
        platform_type = await make_data_type(
            f"shared-{uuid.uuid4().hex[:8]}",
            f"shared-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        for tenant in (TENANT_A, TENANT_B):
            resp = await client.post(
                TOOLS_URL,
                json=_tool_body(f"uses_platform_{tenant.hex[:6]}", input_id=platform_type["id"]),
                headers={"x-test-tenant": str(tenant)},
            )
            assert resp.status_code == 422, resp.text
            assert "not found or not visible to this tenant" in resp.text

    async def test_tenant_type_not_referenceable_from_other_tenant(
        self, client, provider_configured, make_data_type
    ):
        tenant_a_type = await make_data_type(
            f"private-{uuid.uuid4().hex[:8]}",
            f"private-{uuid.uuid4().hex[:8]}",
            TENANT_A,
            LOAN_FIELDS,
        )
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body("cross_tenant_ref", input_id=tenant_a_type["id"]),
            headers={"x-test-tenant": str(TENANT_B)},
        )
        assert resp.status_code == 422
        assert "input_data_type_id" in resp.text

    async def test_unknown_data_type_id_rejected(
        self, client, provider_configured
    ):
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body("unknown_type_ref", input_id=str(uuid.uuid4())),
        )
        assert resp.status_code == 422

    async def test_description_derived_from_referenced_types(
        self, client, provider_configured, make_data_type
    ):
        input_type = await make_data_type(
            f"desc-in-{uuid.uuid4().hex[:8]}",
            f"desc-in-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        output_type = await make_data_type(
            f"desc-out-{uuid.uuid4().hex[:8]}",
            f"desc-out-{uuid.uuid4().hex[:8]}",
            None,
            RESULT_FIELDS,
        )
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body(
                "described_tool",
                input_id=input_type["id"],
                output_id=output_type["id"],
            ),
        )
        assert resp.status_code == 201
        description = resp.json()["description"]
        # Derived from the referenced types' names/slugs/fields:
        assert f"Input data type: {input_type['name']}" in description
        assert input_type["slug"] in description
        assert "amount, tier" in description
        assert f"Output data type: {output_type['name']}" in description

        # Regenerated when the definition (referenced type) changes:
        other_input = await make_data_type(
            f"desc-in2-{uuid.uuid4().hex[:8]}",
            f"desc-in2-{uuid.uuid4().hex[:8]}",
            None,
            [{"name": "region", "type": "string"}],
        )
        upd = await client.put(
            f"{TOOLS_URL}/{resp.json()['id']}",
            json={"input_data_type_id": other_input["id"]},
        )
        assert upd.status_code == 200
        assert f"Input data type: {other_input['name']}" in upd.json()["description"]

    async def test_referenced_data_type_deletion_blocked_409(
        self, client, provider_configured, make_data_type
    ):
        input_type = await make_data_type(
            f"protected-{uuid.uuid4().hex[:8]}",
            f"protected-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        created = await client.post(
            TOOLS_URL,
            json=_tool_body("blocking_tool", input_id=input_type["id"]),
        )
        assert created.status_code == 201

        resp = await client.delete(f"{DATA_TYPES_URL}/{input_type['id']}")
        assert resp.status_code == 409
        # the blocking decision tool is named in the conflict payload
        assert "blocking_tool" in resp.text

        # Type still present and tool still readable.
        got = await client.get(f"{DATA_TYPES_URL}/{input_type['id']}")
        assert got.status_code == 200
        assert (await client.get(TOOLS_URL)).status_code == 200

    async def test_unreferenced_data_type_deletable(
        self, client, provider_configured, make_data_type
    ):
        loose = await make_data_type(
            f"loose-{uuid.uuid4().hex[:8]}",
            f"loose-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        resp = await client.delete(f"{DATA_TYPES_URL}/{loose['id']}")
        assert resp.status_code == 204


# ── State preset validated against the input type fields ──────────────────


@pytest.mark.asyncio
class TestStatePresetAgainstInputFields:
    async def test_input_mapping_to_unknown_field_rejected(
        self, client, provider_configured, make_data_type
    ):
        input_type = await make_data_type(
            f"preset-{uuid.uuid4().hex[:8]}",
            f"preset-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body(
                "bad_preset",
                input_id=input_type["id"],
                state_preset={"amt": {"source": "input", "key": "not_a_field"}},
            ),
        )
        assert resp.status_code == 422
        assert "not a field of the input data type" in resp.text

    async def test_input_mapping_to_known_field_accepted(
        self, client, provider_configured, make_data_type
    ):
        input_type = await make_data_type(
            f"preset-ok-{uuid.uuid4().hex[:8]}",
            f"preset-ok-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body(
                "good_preset",
                input_id=input_type["id"],
                state_preset={"amt": {"source": "input", "key": "amount"}},
            ),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["state_preset"] == {
            "amt": {"source": "input", "key": "amount"}
        }

    async def test_agent_data_mapping_free_form(
        self, client, provider_configured, make_data_type
    ):
        input_type = await make_data_type(
            f"preset-ad-{uuid.uuid4().hex[:8]}",
            f"preset-ad-{uuid.uuid4().hex[:8]}",
            None,
            LOAN_FIELDS,
        )
        resp = await client.post(
            TOOLS_URL,
            json=_tool_body(
                "agent_data_preset",
                input_id=input_type["id"],
                state_preset={
                    "history": {"source": "agent_data", "key": "anything_goes"}
                },
            ),
        )
        assert resp.status_code == 201, resp.text
