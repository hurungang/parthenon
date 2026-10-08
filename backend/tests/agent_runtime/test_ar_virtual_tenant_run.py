"""Scenario 7 — Agent Runtime virtual tenant awareness.

- The AR middleware binds the verified signed header set to the current
  async task; concurrent runs never bleed context between each other.
- AR outbound internal calls stamp the forwarded ``X-Internal-Tenant-*``
  headers exactly as Control Center signed them.
- The scheduler hard-skips a job with no owning tenant (no unscoped
  dispatch path) and dispatches tenant-bound jobs under the owning
  tenant's context.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.tenant_signature import (
    TENANT_ID_HEADER,
    TENANT_SLUG_HEADER,
    bind_forwarded_tenant_headers,
    build_tenant_signature_headers,
    forward_tenant_headers,
    reset_forwarded_tenant_headers,
)
from app.core.tenant_context import TenantContext

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_agent_type,
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()


def _ctx(tenant_id, slug) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, slug=slug, name=slug)


class TestForwardedHeaderBinding:
    async def test_forward_returns_bound_headers(self):
        headers = build_tenant_signature_headers(
            _ctx(uuid.uuid4(), "tenant-x")
        )
        token = bind_forwarded_tenant_headers(headers)
        try:
            assert forward_tenant_headers() == headers
        finally:
            reset_forwarded_tenant_headers(token)
        # Reset clears the binding entirely.
        assert forward_tenant_headers() == {}

    async def test_no_context_bleed_between_concurrent_runs(self):
        """``bind_forwarded_tenant_headers`` is per-async-task: two
        concurrent runs each see only their own signed header set."""
        headers_a = build_tenant_signature_headers(_ctx(uuid.uuid4(), "tenant-a"))
        headers_b = build_tenant_signature_headers(_ctx(uuid.uuid4(), "tenant-b"))

        async def _run(bound_headers: dict, iterations: int = 50) -> bool:
            token = bind_forwarded_tenant_headers(bound_headers)
            try:
                for _ in range(iterations):
                    await asyncio.sleep(0)  # yield to the other task
                    if forward_tenant_headers() != bound_headers:
                        return False
                return True
            finally:
                reset_forwarded_tenant_headers(token)

        ok_a, ok_b = await asyncio.gather(
            _run(headers_a), _run(headers_b)
        )
        assert ok_a and ok_b

    async def test_outbound_internal_call_stamps_forwarded_headers(self, monkeypatch):
        """AR's CommHubToolClient.call_tool forwards EXACTLY the verified
        header set (no re-signing, no widening) on its downstream internal
        call to Communication Hub."""
        import httpx

        from app.agent_runtime import comm_hub_client as chc

        headers_a = build_tenant_signature_headers(_ctx(uuid.uuid4(), "tenant-a"))
        captured: dict = {}

        class _FakeResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {"result": {"output": "ok"}}

            def raise_for_status(self):
                return None

        async def _fake_post(self, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return _FakeResponse()

        monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

        token = bind_forwarded_tenant_headers(headers_a)
        try:
            client = chc.CommHubToolClient()
            result = await client.call_tool(
                "supabase____query",
                {"q": "x"},
                session_id=str(uuid.uuid4()),
                agent_type_id=str(uuid.uuid4()),
            )
            assert result.get("error") is None or "error" not in result
        finally:
            reset_forwarded_tenant_headers(token)

        for header, value in headers_a.items():
            assert captured["headers"].get(header) == value, (
                f"downstream internal call missing forwarded header {header}"
            )


class TestSchedulerNullTenantHardSkip:
    def _job(self, tenant_id, target_id):
        from app.db.models.scheduling import JobTargetType, JobStatus, ScheduledJob

        return ScheduledJob(
            tenant_id=tenant_id,
            name=f"job-{uuid.uuid4().hex[:6]}",
            cron_expression="* * * * *",
            target_type=JobTargetType.agent,
            target_id=target_id,
            payload={"prompt": "hi"},
            status=JobStatus.active,
        )

    async def test_null_tenant_job_is_hard_skipped(self, db):
        """A NULL-tenant job at dispatch is a HARD ERROR path: skipped, never
        dispatched unscoped."""
        from app.services.scheduling.scheduler import SchedulingEngine

        tenant_a, _ = await create_two_tenants(db)
        agent_type = await create_agent_type(db, tenant_a.id, "sched-at")

        job = self._job(None, agent_type.id)  # legacy NULL-tenant job
        db.add(job)
        await db.commit()

        result = await SchedulingEngine()._dispatch(job, db)
        assert result == {
            "status": "skipped",
            "reason": "missing_tenant",
            "session_id": None,
        }

    async def test_tenant_bound_job_dispatches_under_owning_tenant(self, db, monkeypatch):
        from app.db.models.tenant import Tenant

        from app.services.scheduling.scheduler import SchedulingEngine

        suffix = uuid.uuid4().hex[:6]
        tenant = Tenant(name=f"sched-{suffix}", slug=f"sched-{suffix}")
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        agent_type = await create_agent_type(db, tenant.id, "sched-at2")

        job = self._job(tenant.id, agent_type.id)
        db.add(job)
        await db.commit()

        captured: dict = {}

        class _FakeHandler:
            async def launch(self, **kwargs):
                captured.update(kwargs)
                return {"session_id": str(uuid.uuid4())}

        import app.services.gateway.lifecycle_handler as lh

        monkeypatch.setattr(lh, "GatewayLifecycleHandler", _FakeHandler)

        result = await SchedulingEngine()._dispatch(job, db)
        assert "session_id" in result
        assert captured["tenant_context"] is not None
        assert captured["tenant_context"].tenant_id == tenant.id
        assert captured["agent_type_id"] == agent_type.id

    async def test_missing_tenant_row_is_skipped(self, db):
        """When the owning tenant row has vanished, dispatch is skipped —
        never executed tenant-less (transient job object, no DB write)."""
        from app.services.scheduling.scheduler import SchedulingEngine

        agent_type = await create_agent_type(db, None, "orphan-at")
        job = self._job(uuid.uuid4(), agent_type.id)  # tenant row missing

        result = await SchedulingEngine()._dispatch(job, db)
        assert result["status"] == "skipped"
        assert result["reason"] == "missing_tenant"
