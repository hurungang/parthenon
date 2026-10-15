"""Integration tests — per-model availability + vendor cascade.

Covers (test-plan.md §3 "Model Management"):
- catalogue derivation (enabled_models list, default_model fallback)
- per-model manual toggle (disabled_reason=manual) effective immediately in
  the enabled-models list feeding the authoring selector
- vendor-level disable cascades to ALL models (vendor_cascaded)
- vendor re-enable clears cascaded rows but PRESERVES manual disables
- execution-path resolution: a tool referencing a since-disabled model is
  blocked with an actionable error (no silent vendor fallback)
- tenant containment on resolution
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import (
    DT_ENABLED_MODELS_URL,
    ENABLED_MODELS_URL,
    MODELS_URL,
    PROVIDERS_URL,
    create_provider,
)

TOOLS_URL = "/api/v1/decision-tools"

TOOL_PAYLOAD = {
    "name": "availability_tool",
    "purpose": "Resolves through the decision model catalogue",
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
}


class FakeTransport:
    def __init__(self):
        self.calls: list[dict] = []

    async def evaluate(self, *, base_url, api_key, model, state, questions, **kw):
        self.calls.append({"model": model, "api_key": api_key})
        return {
            "model": model,
            "answers": {"approve": {"type": "noul", "noul": 1.0}},
        }


async def _toggle_model(client, availability_id: str, is_disabled: bool):
    return await client.put(
        f"/api/v1/system-one/models/{availability_id}/availability",
        json={"is_disabled": is_disabled},
    )


async def _toggle_vendor(client, provider_id: str, is_disabled: bool):
    return await client.put(
        f"{PROVIDERS_URL}/{provider_id}/availability",
        json={"is_disabled": is_disabled},
    )


async def _hierarchy(client):
    resp = await client.get(MODELS_URL)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestCatalogueDerivation:
    async def test_hierarchy_lists_enabled_models(self, providers_client):
        created = (
            await create_provider(
                providers_client,
                {
                    "display_name": "Cat Provider",
                    "enabled_models": ["m-one", "m-two"],
                    "default_model": "m-one",
                },
            )
        ).json()
        hierarchy = await _hierarchy(providers_client)
        entry = next(h for h in hierarchy if h["provider_id"] == created["id"])
        assert entry["is_disabled"] is False
        assert [m["model_name"] for m in entry["models"]] == ["m-one", "m-two"]
        assert all(m["effective_is_disabled"] is False for m in entry["models"])

    async def test_catalogue_falls_back_to_default_model(self, providers_client):
        created = (
            await create_provider(
                providers_client,
                {"display_name": "DefaultOnly", "enabled_models": None},
            )
        ).json()
        hierarchy = await _hierarchy(providers_client)
        entry = next(h for h in hierarchy if h["provider_id"] == created["id"])
        assert [m["model_name"] for m in entry["models"]] == ["jev-latest"]


class TestPerModelToggle:
    async def test_manual_toggle_hides_model_from_selector(self, providers_client):
        created = (
            await create_provider(
                providers_client,
                {"display_name": "Toggle Provider", "enabled_models": ["keep", "drop"], "default_model": "keep"},
            )
        ).json()
        enabled = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        names = {m["model_name"] for m in enabled if m["provider_id"] == created["id"]}
        assert names == {"keep", "drop"}

        drop = next(
            m for m in enabled
            if m["provider_id"] == created["id"] and m["model_name"] == "drop"
        )
        resp = await _toggle_model(providers_client, drop["availability_id"], True)
        assert resp.status_code == 200, resp.text
        assert resp.json()["disabled_reason"] == "manual"

        # effective immediately — no reload
        after = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        names_after = {
            m["model_name"] for m in after if m["provider_id"] == created["id"]
        }
        assert names_after == {"keep"}

        # hierarchy shows the disabled state + reason
        entry = next(
            h for h in await _hierarchy(providers_client)
            if h["provider_id"] == created["id"]
        )
        drop_entry = next(m for m in entry["models"] if m["model_name"] == "drop")
        assert drop_entry["effective_is_disabled"] is True
        assert drop_entry["disabled_reason"] == "manual"

    async def test_re_enable_restores_model(self, providers_client):
        created = (
            await create_provider(
                providers_client,
                {"display_name": "ReEn", "enabled_models": ["solo"], "default_model": "solo"},
            )
        ).json()
        enabled = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        row = next(m for m in enabled if m["provider_id"] == created["id"])
        await _toggle_model(providers_client, row["availability_id"], True)
        await _toggle_model(providers_client, row["availability_id"], False)
        after = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        assert "solo" in {
            m["model_name"] for m in after if m["provider_id"] == created["id"]
        }

    async def test_unknown_availability_id_404(self, providers_client):
        resp = await _toggle_model(providers_client, str(uuid.uuid4()), True)
        assert resp.status_code == 404


class TestVendorCascade:
    async def test_vendor_disable_cascades_and_reenable_preserves_manual(
        self, providers_client
    ):
        """Vendor-level disable cascades to all models; re-enable restores
        cascade-disabled models but PRESERVES manual disables (disable
        reason manual survives the cascade round-trip)."""
        created = (
            await create_provider(
                providers_client,
                {"display_name": "Cascade Provider", "enabled_models": ["mA", "mB"], "default_model": "mA"},
            )
        ).json()
        pid = created["id"]
        enabled = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        a_row = next(
            m for m in enabled if m["provider_id"] == pid and m["model_name"] == "mA"
        )

        # manually disable mA
        await _toggle_model(providers_client, a_row["availability_id"], True)

        # vendor-level disable → ALL models effectively disabled
        resp = await _toggle_vendor(providers_client, pid, True)
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] is False

        after_disable = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        assert not [
            m for m in after_disable if m["provider_id"] == pid
        ], "cascade must remove every model of the disabled vendor from the selector"
        entry = next(
            h for h in await _hierarchy(providers_client) if h["provider_id"] == pid
        )
        assert entry["is_disabled"] is True
        assert all(m["effective_is_disabled"] for m in entry["models"])

        # vendor re-enable → mB returns, mA stays manually disabled
        resp = await _toggle_vendor(providers_client, pid, False)
        assert resp.status_code == 200, resp.text

        after_enable = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        names = {m["model_name"] for m in after_enable if m["provider_id"] == pid}
        assert "mB" in names
        assert "mA" not in names, (
            "manual disable must survive the vendor cascade round-trip "
            "(no silent re-enable of a manually disabled model)"
        )

    async def test_disabled_provider_delete_toggle_404_containment(
        self, providers_client
    ):
        resp = await _toggle_vendor(providers_client, str(uuid.uuid4()), True)
        assert resp.status_code == 404


class TestExecutionPathBlocking:
    async def test_tool_with_disabled_selected_model_blocked_on_execute(
        self, providers_client, test_engine, monkeypatch
    ):
        """A tool referencing a since-disabled model fails at evaluation
        time with an actionable error — no vendor dispatch, no fallback."""
        created = (
            await create_provider(
                providers_client,
                {"display_name": "Exec Provider", "enabled_models": ["exec-m"], "default_model": "exec-m"},
            )
        ).json()
        enabled = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        row = next(m for m in enabled if m["provider_id"] == created["id"])

        tool = await providers_client.post(
            TOOLS_URL,
            json={
                **TOOL_PAYLOAD,
                "name": "blocked_exec_tool",
                "decision_model_availability_id": row["availability_id"],
            },
        )
        assert tool.status_code == 201, tool.text

        # disable the selected model AFTER tool creation
        await _toggle_model(providers_client, row["availability_id"], True)

        fake = FakeTransport()
        import app.services.system_one.decision_engine as engine_module

        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake)

        from app.db.models.decision_tools import DecisionTool
        from app.services.system_one.decision_engine import DecisionExecutionEngine

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            t = (
                await session.execute(
                    select(DecisionTool)
                    .where(DecisionTool.id == uuid.UUID(tool.json()["id"]))
                    .options(selectinload(DecisionTool.questions))
                )
            ).scalar_one()
            result = await DecisionExecutionEngine().execute(
                db=session, tool=t, input_state={}, tenant_id=t.tenant_id
            )
            await session.commit()

        assert result.status.value == "failed"
        assert fake.calls == [], "no vendor call may be made for a disabled model"
        assert "disabled" in (result.error_message or "").lower()

    async def test_tool_with_enabled_model_executes_with_selected_identity(
        self, providers_client, test_engine, monkeypatch
    ):
        created = (
            await create_provider(
                providers_client,
                {"display_name": "Happy Exec", "enabled_models": ["happy-m"], "default_model": "happy-m"},
            )
        ).json()
        enabled = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        row = next(m for m in enabled if m["provider_id"] == created["id"])

        tool = await providers_client.post(
            TOOLS_URL,
            json={
                **TOOL_PAYLOAD,
                "name": "happy_exec_tool",
                "decision_model_availability_id": row["availability_id"],
            },
        )
        assert tool.status_code == 201, tool.text
        # Read identity enrichment
        assert tool.json()["model_name"] == "happy-m"
        assert tool.json()["provider_display_name"] == "Happy Exec"

        fake = FakeTransport()
        import app.services.system_one.decision_engine as engine_module

        monkeypatch.setattr(engine_module, "get_system_one_client", lambda pt: fake)

        from app.db.models.decision_tools import DecisionTool
        from app.services.system_one.decision_engine import DecisionExecutionEngine

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            t = (
                await session.execute(
                    select(DecisionTool)
                    .where(DecisionTool.id == uuid.UUID(tool.json()["id"]))
                    .options(selectinload(DecisionTool.questions))
                )
            ).scalar_one()
            result = await DecisionExecutionEngine().execute(
                db=session, tool=t, input_state={}, tenant_id=t.tenant_id
            )
            await session.commit()

        assert result.status.value == "completed"
        assert len(fake.calls) == 1
        assert fake.calls[0]["model"] == "happy-m"
        # execution record identifies the provider/model used
        provider_identity = result.answers["provider"]
        assert provider_identity["model_name"] == "happy-m"
        assert provider_identity["provider_display_name"] == "Happy Exec"
        assert provider_identity["provider_id"] == created["id"]

    async def test_cross_tenant_resolution_blocked(self, providers_client, test_engine):
        """The availability row of tenant A is invisible to tenant B — a
        tool cannot be pointed at another tenant's model."""
        tenant = uuid.uuid4()
        headers = {"x-test-tenant": str(tenant)}
        created = (
            await create_provider(
                providers_client,
                {"display_name": "TenantScoped", "enabled_models": ["tm"], "default_model": "tm"},
                headers=headers,
            )
        ).json()
        enabled = (
            await providers_client.get(DT_ENABLED_MODELS_URL, headers=headers)
        ).json()
        row = next(m for m in enabled if m["provider_id"] == created["id"])

        # a DIFFERENT tenant cannot toggle or resolve it
        other = uuid.uuid4()
        resp = await _toggle_model(
            providers_client, row["availability_id"], True
        )  # headerless = root scope
        assert resp.status_code == 404

        # and the row's tenant scoping keeps it out of the other tenant's selector
        other_models = (
            await providers_client.get(DT_ENABLED_MODELS_URL, headers={"x-test-tenant": str(other)})
        ).json()
        assert not [
            m for m in other_models if m["availability_id"] == row["availability_id"]
        ]
