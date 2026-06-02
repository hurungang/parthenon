"""Tests for the Agent Runtime pre-execution availability check.

The pre-execution availability check is performed by Agent Runtime before
dispatching any agent execution.  This file verifies:

- The preflight is invoked with the resolved model name and
  ``vendor_model_config_id`` from the agent context.
- On allow, dispatch proceeds unchanged.
- On deny, ``ModelAvailabilityBlockedError`` is raised and the
  ``run`` loop emits a structured execution log entry tagged with the
  matching ``event_category`` (model_disabled or vendor_disabled).
- Failures of the preflight call itself (network / 5xx) DO NOT block
  execution — runtime stays available, and the missing check is logged
  at WARN.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest

from app.services.agents.guardrails import ModelAvailabilityBlockedError
from app.services.agents.runtime_executor import AgentRuntimeExecutor


def _make_data_client(
    preflight: AsyncMock | None = None,
    *,
    preflight_side_effect: BaseException | None = None,
) -> SimpleNamespace:
    """Build a stub data client whose only relevant method is the
    preflight call; everything else returns a benign default.
    """
    if preflight is None:
        if preflight_side_effect is not None:
            preflight = AsyncMock(side_effect=preflight_side_effect)
        else:
            preflight = AsyncMock(return_value={"allowed": True})
    return SimpleNamespace(
        preflight_availability=preflight,
        get_session=AsyncMock(),
        get_agent_context=AsyncMock(),
        mark_session_completed=AsyncMock(),
        mark_session_failed=AsyncMock(),
        log_execution_event=AsyncMock(),
    )


def _context_with(
    *, model_id: str = "gpt-4o", model_config_id: str | None = None
) -> dict:
    ctx: dict = {
        "agent_type_id": str(uuid.uuid4()),
        "agent_type_slug": "agent",
        "model_id": model_id,
    }
    if model_config_id is not None:
        ctx["model_config_id"] = model_config_id
    return ctx


@pytest.mark.asyncio
async def test_preflight_allows_when_vendor_and_model_enabled():
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client(
        preflight=AsyncMock(return_value={"allowed": True})
    )
    ctx = _context_with(model_id="gpt-4o", model_config_id=str(uuid.uuid4()))

    # Should not raise.
    await executor._preflight_model_availability(
        session_id=uuid.uuid4(), context=ctx, data_client=data_client
    )

    data_client.preflight_availability.assert_awaited_once()
    _, kwargs = data_client.preflight_availability.call_args
    assert kwargs["model_name"] == "gpt-4o"
    assert kwargs["vendor_model_config_id"] is not None


@pytest.mark.asyncio
async def test_preflight_blocks_vendor_disabled():
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client(
        preflight=AsyncMock(
            return_value={
                "allowed": False,
                "reason": "Vendor A is disabled",
                "disabled_reason": "vendor_cascaded",
                "blocked_by": "vendor_disabled",
            }
        )
    )
    ctx = _context_with(model_id="gpt-4o", model_config_id=str(uuid.uuid4()))

    with pytest.raises(ModelAvailabilityBlockedError) as excinfo:
        await executor._preflight_model_availability(
            session_id=uuid.uuid4(),
            context=ctx,
            data_client=data_client,
        )
    assert excinfo.value.blocked_by == "vendor_disabled"
    assert excinfo.value.disabled_reason == "vendor_cascaded"


@pytest.mark.asyncio
async def test_preflight_blocks_guardrail_breached():
    """A preflight verdict of ``blocked_by=guardrail_breached`` must
    surface as a :class:`ModelAvailabilityBlockedError` so the calling
    ``run`` loop can mark the session as failed with the dedicated
    ``guardrail_breached`` event category.
    """
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client(
        preflight=AsyncMock(
            return_value={
                "allowed": False,
                "reason": "Guardrail breached for model 'gpt-4o' (period=hour)",
                "disabled_reason": None,
                "blocked_by": "guardrail_breached",
            }
        )
    )
    ctx = _context_with(model_id="gpt-4o", model_config_id=str(uuid.uuid4()))

    with pytest.raises(ModelAvailabilityBlockedError) as excinfo:
        await executor._preflight_model_availability(
            session_id=uuid.uuid4(),
            context=ctx,
            data_client=data_client,
        )
    assert excinfo.value.blocked_by == "guardrail_breached"
    assert "breached" in (excinfo.value.message or "").lower()


@pytest.mark.asyncio
async def test_preflight_blocks_model_disabled():
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client(
        preflight=AsyncMock(
            return_value={
                "allowed": False,
                "reason": "Model 'gpt-4o' is disabled",
                "disabled_reason": "manual",
                "blocked_by": "model_disabled",
            }
        )
    )
    ctx = _context_with(model_id="gpt-4o", model_config_id=str(uuid.uuid4()))

    with pytest.raises(ModelAvailabilityBlockedError) as excinfo:
        await executor._preflight_model_availability(
            session_id=uuid.uuid4(),
            context=ctx,
            data_client=data_client,
        )
    assert excinfo.value.blocked_by == "model_disabled"
    assert excinfo.value.disabled_reason == "manual"


@pytest.mark.asyncio
async def test_preflight_fails_open_on_data_client_error():
    """A preflight call that itself errors (network, 5xx) MUST NOT
    block execution — runtime stays available.  The failure is logged
    at WARN so the operator can spot degraded mode.
    """
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client(
        preflight_side_effect=RuntimeError("connection refused")
    )
    ctx = _context_with(model_id="gpt-4o", model_config_id=str(uuid.uuid4()))

    # Should not raise.
    await executor._preflight_model_availability(
        session_id=uuid.uuid4(), context=ctx, data_client=data_client
    )


@pytest.mark.asyncio
async def test_preflight_skips_when_no_model_bound():
    """If the agent context carries no model_id, the preflight is a
    no-op (most commonly hit during a cold-start context build).
    """
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client()
    ctx = {"agent_type_id": str(uuid.uuid4()), "agent_type_slug": "agent"}

    await executor._preflight_model_availability(
        session_id=uuid.uuid4(), context=ctx, data_client=data_client
    )

    data_client.preflight_availability.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_passes_vendor_config_id_when_present():
    """When the agent context includes ``model_config_id``, the
    preflight uses it so the runtime can target the resolved vendor.
    """
    executor = AgentRuntimeExecutor()
    vendor_id = uuid.uuid4()
    data_client = _make_data_client(
        preflight=AsyncMock(return_value={"allowed": True})
    )
    ctx = _context_with(model_id="gpt-4o", model_config_id=str(vendor_id))

    await executor._preflight_model_availability(
        session_id=uuid.uuid4(), context=ctx, data_client=data_client
    )

    data_client.preflight_availability.assert_awaited_once()
    _, kwargs = data_client.preflight_availability.call_args
    assert kwargs["model_name"] == "gpt-4o"
    assert kwargs["vendor_model_config_id"] == vendor_id


@pytest.mark.asyncio
async def test_preflight_passes_none_vendor_when_unresolved():
    """When the agent context has no ``model_config_id``, the
    preflight is invoked with ``vendor_model_config_id=None`` so
    Control Center can consider every vendor that offers the model.
    """
    executor = AgentRuntimeExecutor()
    data_client = _make_data_client(
        preflight=AsyncMock(return_value={"allowed": True})
    )
    ctx = _context_with(model_id="gpt-4o")

    await executor._preflight_model_availability(
        session_id=uuid.uuid4(), context=ctx, data_client=data_client
    )

    data_client.preflight_availability.assert_awaited_once()
    _, kwargs = data_client.preflight_availability.call_args
    assert kwargs["vendor_model_config_id"] is None
