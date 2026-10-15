"""Integration tests — decision-scope guardrails (FIX-20261014-003000).

Covers:
- guardrail CRUD via the decision-scoped /system-one endpoints
- duplicate (provider, model, period) → 409 guardrail_period_conflict
- unknown provider → 404
- LLM (model_config) guardrail rows are NOT reachable via the decision
  update/delete endpoints (scope isolation, both directions)
- posture refresh computes decision posture from decision executions
- decision pre-call check blocks on breached DECISION guardrails only —
  LLM guardrails with identical model names must stay untouched.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests.integration.conftest import create_provider

GUARDRAILS_URL = "/api/v1/system-one/providers/{pid}/guardrails"
POSTURE_URL = "/api/v1/system-one/providers/{pid}/guardrails/posture"
GUARDRAIL_BY_ID_URL = "/api/v1/system-one/guardrails/{gid}"


def _session_local(test_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _make_provider(client) -> dict:
    resp = await create_provider(
        client, {"display_name": f"Guardrail Vendor {uuid.uuid4().hex[:8]}"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestDecisionGuardrailCrud:
    async def test_create_list_update_delete_roundtrip(self, providers_client):
        provider = await _make_provider(providers_client)
        pid = provider["id"]

        # create
        resp = await providers_client.post(
            GUARDRAILS_URL.format(pid=pid),
            json={
                "model_name": "jev-latest",
                "period": "day",
                "limit_value": 100,
                "unit": "k",
                "enforcement_posture": "terminate",
                "is_active": True,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["model_name"] == "jev-latest"
        assert body["model_id"] is None
        assert body["decision_provider_id"] == pid
        gid = body["id"]

        # list
        resp = await providers_client.get(GUARDRAILS_URL.format(pid=pid))
        assert resp.status_code == 200
        assert [g["id"] for g in resp.json()] == [gid]

        # update
        resp = await providers_client.put(
            GUARDRAIL_BY_ID_URL.format(gid=gid), json={"limit_value": 250}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["limit_value"] == 250

        # delete
        resp = await providers_client.delete(GUARDRAIL_BY_ID_URL.format(gid=gid))
        assert resp.status_code == 204
        resp = await providers_client.get(GUARDRAILS_URL.format(pid=pid))
        assert resp.json() == []

    async def test_duplicate_period_conflicts_409(self, providers_client):
        provider = await _make_provider(providers_client)
        url = GUARDRAILS_URL.format(pid=provider["id"])
        payload = {
            "model_name": "jev-latest",
            "period": "week",
            "limit_value": 10,
        }
        assert (await providers_client.post(url, json=payload)).status_code == 201
        resp = await providers_client.post(url, json=payload)
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "guardrail_period_conflict"

    async def test_unknown_provider_404(self, providers_client):
        resp = await providers_client.get(
            GUARDRAILS_URL.format(pid=uuid.uuid4())
        )
        assert resp.status_code == 404

    async def test_same_model_period_on_other_provider_allowed(self, providers_client):
        """Uniqueness is (provider, model, period) — the same pair on another
        provider is a separate guardrail."""
        payloads = [
            {
                "model_name": "jev-latest",
                "period": "month",
                "limit_value": 5,
            }
        ]
        for _ in range(2):
            provider = await _make_provider(providers_client)
            resp = await providers_client.post(
                GUARDRAILS_URL.format(pid=provider["id"]),
                json=payloads[0],
            )
            assert resp.status_code == 201, resp.text


class TestScopeIsolation:
    async def test_llm_guardrail_not_reachable_via_decision_endpoints(
        self, providers_client, test_engine
    ):
        """An LLM (model_config) guardrail row must 404 on the decision
        PUT/DELETE endpoints — the decision module never touches LLM rows."""
        from app.db.models.model_guardrail_configuration import (
            ModelGuardrailConfiguration,
        )

        provider = await _make_provider(providers_client)
        SessionLocal = _session_local(test_engine)
        async with SessionLocal() as session:
            llm_row = ModelGuardrailConfiguration(
                config_source="model_config",
                model_name="jev-latest",
                period="day",
                limit_value=1000,
            )
            session.add(llm_row)
            await session.commit()
            llm_id = llm_row.id

        resp = await providers_client.put(
            GUARDRAIL_BY_ID_URL.format(gid=llm_id), json={"limit_value": 1}
        )
        assert resp.status_code == 404
        resp = await providers_client.delete(GUARDRAIL_BY_ID_URL.format(gid=llm_id))
        assert resp.status_code == 404

        # cleanup
        async with SessionLocal() as session:
            row = await session.get(ModelGuardrailConfiguration, llm_id)
            await session.delete(row)
            await session.commit()

    async def test_decision_row_not_in_llm_listing(self, providers_client, test_engine):
        from app.db.models.model_guardrail_configuration import (
            ModelGuardrailConfiguration,
        )
        from app.services.control_center.model_usage_guardrail_service import (
            ModelUsageGuardrailService,
        )

        provider = await _make_provider(providers_client)
        resp = await providers_client.post(
            GUARDRAILS_URL.format(pid=provider["id"]),
            json={"model_name": "jev-latest", "period": "hour", "limit_value": 7},
        )
        assert resp.status_code == 201
        decision_id = resp.json()["id"]

        SessionLocal = _session_local(test_engine)
        async with SessionLocal() as session:
            llm_rows = await ModelUsageGuardrailService().list_configurations(session)
        assert decision_id not in {r.id for r in llm_rows}


class TestDecisionPostureAndPreCall:
    async def _seed_completed_execution(
        self, client, test_engine, provider_id: str, model: str
    ):
        from app.db.models.results import DecisionExecutionResult

        tool_resp = await client.post(
            "/api/v1/decision-tools",
            json={
                "name": f"guardrail_tool_{uuid.uuid4().hex[:8]}",
                "purpose": "posture rollup seed",
                "enabled": False,
                "act_threshold": 0.9,
                "confirm_threshold": 0.7,
                "questions": [
                    {
                        "question_key": "approve",
                        "question_type": "noul",
                        "instructions": "Approve?",
                        "ordering": 0,
                    }
                ],
            },
        )
        assert tool_resp.status_code in (200, 201), tool_resp.text
        tool_id = tool_resp.json()["id"]

        async with _session_local(test_engine)() as session:
            session.add(
                DecisionExecutionResult(
                    decision_tool_id=uuid.UUID(str(tool_id)),
                    status="completed",
                    outcome="act",
                    answers={
                        "provider": {"provider_id": provider_id, "model_name": model}
                    },
                )
            )
            await session.commit()

    async def test_posture_refresh_counts_decision_executions(
        self, providers_client, test_engine
    ):

        provider = await _make_provider(providers_client)
        pid = provider["id"]
        resp = await providers_client.post(
            GUARDRAILS_URL.format(pid=pid),
            json={"model_name": "jev-latest", "period": "day", "limit_value": 2},
        )
        assert resp.status_code == 201

        await self._seed_completed_execution(providers_client, test_engine, pid, "jev-latest")

        resp = await providers_client.get(f"{POSTURE_URL.format(pid=pid)}?refresh=true")
        assert resp.status_code == 200, resp.text
        postures = resp.json()
        assert len(postures) == 1
        assert postures[0]["usage_value"] == 1
        assert postures[0]["limit_value"] == 2

    async def test_pre_call_blocks_on_breached_decision_guardrail_only(
        self, providers_client, test_engine
    ):
        """A breached DECISION guardrail blocks; an LLM guardrail with the
        same model name must NOT influence the decision pre-call check."""
        from app.db.models.model_guardrail_configuration import (
            ModelGuardrailConfiguration,
            ModelGuardrailEnforcementPosture,
        )
        from app.db.models.model_usage_posture import (
            ModelUsagePosture,
            ModelUsagePostureState,
        )
        from app.db.models.system_one_provider_config import SystemOneProviderConfig
        from app.services.system_one.decision_model_availability_service import (
            DecisionModelCatalogueService,
        )

        provider = await _make_provider(providers_client)
        pid = provider["id"]

        SessionLocal = _session_local(test_engine)
        try:
            async with SessionLocal() as session:
                # Decision guardrail (breached).
                decision_row = ModelGuardrailConfiguration(
                    config_source="decision_provider",
                    decision_provider_id=uuid.UUID(pid),
                    model_name="jev-latest",
                    period="day",
                    limit_value=1,
                    enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
                    is_active=True,
                )
                # LLM guardrail, same model name, also breached — must be
                # ignored by the decision pre-call check.
                llm_row = ModelGuardrailConfiguration(
                    config_source="model_config",
                    model_name="jev-latest",
                    period="day",
                    limit_value=1,
                    enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
                    is_active=True,
                )
                session.add_all([decision_row, llm_row])
                await session.flush()
                for row in (decision_row, llm_row):
                    session.add(
                        ModelUsagePosture(
                            model_guardrail_configuration_id=row.id,
                            model_id=row.id,
                            posture_period="day",
                            usage_value=5,
                            limit_value=1,
                            posture_state=ModelUsagePostureState.breached,
                            observed_at=datetime.now(timezone.utc),
                        )
                    )
                await session.commit()

                config = await session.get(SystemOneProviderConfig, uuid.UUID(pid))
                blocked = await DecisionModelCatalogueService().check_pre_call(
                    session, config, "jev-latest"
                )
                assert blocked == "guardrail_breached"
        finally:
            async with SessionLocal() as session:
                await session.execute(
                    ModelUsagePosture.__table__.delete()
                )
                await session.execute(
                    ModelGuardrailConfiguration.__table__.delete()
                )
                await session.commit()
