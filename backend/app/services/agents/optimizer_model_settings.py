"""Per-tenant optimizer model selection (DB-backed) with authoring fallback.

The conversational optimizer runs on a workspace-chosen model that is kept
**separate from the agent type's runtime model**. The selection lives in the
``tenant_settings`` table under the key ``optimizer_model_id`` and is resolved
for the SESSION tenant (the root tenant when multi-tenancy is off).

Resolution order (read time only — nothing is ever normalised or written back):

1. an explicit ``optimizer_model_id`` that resolves in the tenant's enabled
   model catalogue and is not disabled → ``source="optimizer"``;
2. unset → the existing plan-AUTHORING model (``workflow_generation_model_id``)
   → ``source="authoring"``;
3. explicit but unusable (removed from the catalogue, or the provider config
   was disabled) → ``optimizer_model_not_enabled`` (no fallback);
4. unset and the authoring model is unusable → ``optimizer_model_not_configured``
   (echoing the authoring reason).

There is deliberately **no fallback to ``AgentType.model_id``** (the subject's
runtime model) and no first-available config: an unusable state is reported so
the operator can fix it in System Config.

Control-Center-only: this module reads PostgreSQL, so Agent Runtime and
Communication Hub must never import it (they receive model identifiers through
the internal agent-context endpoint instead).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tenancy.tenant_settings_service import get_value, set_value

if TYPE_CHECKING:
    from app.db.models.agents import ModelConfig

#: Tenant-setting key holding the optimizer model id.
OPTIMIZER_MODEL_KEY = "optimizer_model_id"

#: ``reason_code`` — no usable model (nothing configured and no authoring model).
REASON_OPTIMIZER_MODEL_NOT_CONFIGURED = "optimizer_model_not_configured"
#: ``reason_code`` — the chosen optimizer model is no longer usable here.
REASON_OPTIMIZER_MODEL_NOT_ENABLED = "optimizer_model_not_enabled"

#: ``source`` values describing where the effective model came from.
SOURCE_OPTIMIZER = "optimizer"
SOURCE_AUTHORING = "authoring"


def _not_configured_reason(authoring_reason: str | None) -> str:
    base = (
        "No optimizer model is configured for this workspace and there is no "
        "usable plan-authoring model to inherit. Select an optimizer model "
        "in System Config (Optimizer Model)."
    )
    if authoring_reason:
        return f"{base} {authoring_reason}"
    return base


def _not_enabled_reason(model_id: str) -> str:
    return (
        f"The configured optimizer model '{model_id}' is no longer available in "
        "this workspace's model catalogue. Re-select an enabled model in System "
        "Config (Optimizer Model)."
    )


@dataclass(frozen=True)
class OptimizerModelState:
    """Derived (read-time) state of the workspace optimizer model.

    - ``model_id`` — the RAW stored optimizer selection (echoed even when
      unusable so the UI can say "``<id>`` is no longer available — re-select").
    - ``effective_model_id`` — the model the optimizer would run on (the
      explicit selection, or the inherited authoring model). ``None`` when no
      usable model exists.
    - ``source`` — ``"optimizer"`` when the explicit selection is used,
      ``"authoring"`` when the authoring model is inherited, ``None`` when
      nothing usable resolves.
    - ``configured`` / ``enabled`` — whether a selection exists and whether it
      resolves in the tenant's enabled catalogue.
    - ``model_config`` — the resolved tenant ``ModelConfig`` when usable.
    - ``reason_code`` / ``reason`` — set only when no usable model exists.
    """

    model_id: str | None
    effective_model_id: str | None
    source: str | None
    configured: bool
    enabled: bool
    model_config: ModelConfig | None = field(default=None)
    reason_code: str | None = None
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return (
            self.enabled
            and self.model_config is not None
            and bool(self.effective_model_id)
        )


@dataclass(frozen=True)
class OptimizerModel:
    """A usable optimizer model: the effective model id plus its config."""

    model_id: str
    model_config: ModelConfig


class OptimizerModelNotConfigured(Exception):
    """No usable optimizer model for the session tenant.

    Carries the structured ``reason_code`` (``optimizer_model_not_configured``
    or ``optimizer_model_not_enabled``) so HTTP callers can emit the documented
    ``412 optimizer_model_unavailable`` payload. Never handled by selecting
    another model.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


async def _session_tenant_id(db: AsyncSession) -> uuid.UUID | None:
    """The current tenant id (root tenant when multi-tenancy is off)."""
    from app.core.tenant_context import get_current_tenant_context
    from app.services.tenancy.root_tenant import get_root_tenant_id

    context = get_current_tenant_context()
    if context is not None:
        return context.tenant_id
    # No request context (startup, background jobs) — the root tenant
    # is the default tenant context when the tenancy switch is OFF.
    return await get_root_tenant_id(db)


async def get_optimizer_model_id(db: AsyncSession) -> str | None:
    """Return the session tenant's RAW optimizer model id, or None (unset)."""
    tenant_id = await _session_tenant_id(db)
    if tenant_id is None:
        return None
    value = await get_value(db, tenant_id, OPTIMIZER_MODEL_KEY)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


async def get_optimizer_model_state(db: AsyncSession) -> OptimizerModelState:
    """Return the session tenant's optimizer-model state (never raises).

    Explicit selection → authoring fallback → structured reason. The stored
    setting row is never rewritten, and an unusable selection is reported
    rather than replaced.
    """
    from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer
    from app.services.agents.workflow_generation_settings import (
        get_authoring_model_state,
    )

    explicit_model_id = await get_optimizer_model_id(db)

    if explicit_model_id:
        try:
            model_config = await ModelBindingLayer().resolve_model_config(
                explicit_model_id, db
            )
        except ModelBindingError:
            return OptimizerModelState(
                model_id=explicit_model_id,
                effective_model_id=None,
                source=SOURCE_OPTIMIZER,
                configured=True,
                enabled=False,
                model_config=None,
                reason_code=REASON_OPTIMIZER_MODEL_NOT_ENABLED,
                reason=_not_enabled_reason(explicit_model_id),
            )

        # A provider configuration can be disabled (e.g. cascaded from vendor
        # availability) while still listing the model in ``enabled_models``.
        # Such a selection is NOT usable — report it instead of calling a
        # guaranteed-to-fail model.
        if getattr(model_config, "is_disabled", False):
            return OptimizerModelState(
                model_id=explicit_model_id,
                effective_model_id=None,
                source=SOURCE_OPTIMIZER,
                configured=True,
                enabled=False,
                model_config=None,
                reason_code=REASON_OPTIMIZER_MODEL_NOT_ENABLED,
                reason=_not_enabled_reason(explicit_model_id),
            )

        return OptimizerModelState(
            model_id=explicit_model_id,
            effective_model_id=explicit_model_id,
            source=SOURCE_OPTIMIZER,
            configured=True,
            enabled=True,
            model_config=model_config,
        )

    # Unset → inherit the workspace plan-authoring model (read-time fallback).
    authoring = await get_authoring_model_state(db)
    if authoring.usable and authoring.model_id:
        return OptimizerModelState(
            model_id=None,
            effective_model_id=authoring.model_id,
            source=SOURCE_AUTHORING,
            configured=False,
            enabled=True,
            model_config=authoring.model_config,
        )

    return OptimizerModelState(
        model_id=None,
        effective_model_id=None,
        source=None,
        configured=False,
        enabled=False,
        model_config=None,
        reason_code=REASON_OPTIMIZER_MODEL_NOT_CONFIGURED,
        reason=_not_configured_reason(authoring.reason),
    )


async def require_optimizer_model(db: AsyncSession) -> OptimizerModel:
    """Return the usable optimizer model for the session tenant.

    Raises ``OptimizerModelNotConfigured`` with the documented ``reason_code``
    when nothing usable resolves. Callers must NOT substitute another model
    (no agent-runtime-model and no first-available fallback).
    """
    state = await get_optimizer_model_state(db)
    if not state.usable or state.model_config is None or not state.effective_model_id:
        raise OptimizerModelNotConfigured(
            state.reason_code or REASON_OPTIMIZER_MODEL_NOT_CONFIGURED,
            state.reason or _not_configured_reason(None),
        )
    return OptimizerModel(
        model_id=state.effective_model_id,
        model_config=state.model_config,
    )


async def set_optimizer_model_id(
    db: AsyncSession, model_id: str | None
) -> None:
    """Persist the session tenant's optimizer model selection (None clears)."""
    tenant_id = await _session_tenant_id(db)
    if tenant_id is None:
        raise RuntimeError("No tenant context available to store the optimizer model")
    cleaned = (model_id or "").strip() or None
    await set_value(db, tenant_id, OPTIMIZER_MODEL_KEY, cleaned)
