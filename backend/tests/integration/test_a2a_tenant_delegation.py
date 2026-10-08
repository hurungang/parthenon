"""Scenario 2 — A2A delegation resolves strictly by ``(tenant, name)``.

Two tenants each have an agent type named ``helper``: delegation from
tenant A must resolve tenant A's agent only, never tenant B's same-named
agent; a target name that exists only in tenant B is unresolvable from
tenant A (fail closed 404).
"""
from __future__ import annotations

import uuid

import pytest

from app.api.v1.internal.session_data import A2ADataRequest, prepare_a2a_request
from app.core.tenant_context import TenantContext

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_agent_type,
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()


def _ctx(tenant) -> TenantContext:
    return TenantContext(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name)


def _request(slug: str) -> A2ADataRequest:
    return A2ADataRequest(
        target_agent_type_slug=slug,
        requester_instance_id=str(uuid.uuid4()),
        request_payload={"task": "do something"},
    )


@pytest.fixture(autouse=True)
def _no_comm_hub(monkeypatch):
    """Never hit the real Communication Hub from these tests."""
    from app.services.control_center import comm_hub_client

    async def _fake_trigger(self, **kwargs):  # noqa: ANN001
        return {"ok": True}

    monkeypatch.setattr(
        comm_hub_client.CommunicationHubClient, "trigger_execution", _fake_trigger
    )


class TestA2ATenantResolution:
    async def test_delegation_resolves_own_tenant_agent_on_name_collision(self, db):
        tenant_a, tenant_b = await create_two_tenants(db)
        helper_a = await create_agent_type(db, tenant_a.id, "helper")
        helper_b = await create_agent_type(db, tenant_b.id, "helper")

        response = await prepare_a2a_request(_request("helper"), _ctx(tenant_a), db)

        assert response.status == "accepted"
        # receiver_instance_id embeds the RESOLVED agent type id — tenant A's.
        assert str(helper_a.id) in response.receiver_instance_id
        assert str(helper_b.id) not in response.receiver_instance_id

    async def test_delegated_job_is_tenant_stamped(self, db):
        from sqlalchemy import text as sqltext

        tenant_a, _tenant_b = await create_two_tenants(db)
        await create_agent_type(db, tenant_a.id, "helper")

        response = await prepare_a2a_request(_request("helper"), _ctx(tenant_a), db)
        assert response.receiver_session_id is not None
        row = (
            await db.execute(
                sqltext("SELECT tenant_id FROM agent_jobs WHERE id = :id"),
                {"id": response.receiver_session_id},
            )
        ).first()
        assert row is not None and str(row[0]) == str(tenant_a.id)

    async def test_name_existing_only_in_other_tenant_fails_closed(self, db):
        from fastapi import HTTPException

        tenant_a, tenant_b = await create_two_tenants(db)
        await create_agent_type(db, tenant_b.id, "b_only_helper")

        with pytest.raises(HTTPException) as exc_info:
            await prepare_a2a_request(
                _request("b_only_helper"), _ctx(tenant_a), db
            )
        assert exc_info.value.status_code == 404

    async def test_delegation_to_tenant_b_agent_from_tenant_a_context(self, db):
        """Even with a request crafted against B's agent, tenant A's context
        resolves within tenant A only — the target is a miss."""
        from fastapi import HTTPException

        tenant_a, tenant_b = await create_two_tenants(db)
        helper_b = await create_agent_type(db, tenant_b.id, "helper")
        await create_agent_type(db, tenant_a.id, "helper")

        with pytest.raises(HTTPException):
            # Tenant A has no agent type named "not_present" — miss.
            await prepare_a2a_request(
                _request("not_present"), _ctx(tenant_a), db
            )

        # Sanity: B's own context DOES resolve B's agent (same wire name).
        response = await prepare_a2a_request(_request("helper"), _ctx(tenant_b), db)
        assert str(helper_b.id) in response.receiver_instance_id
