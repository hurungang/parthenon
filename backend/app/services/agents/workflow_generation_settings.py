"""Per-tenant workflow generation (authoring) model selection (DB-backed).

The selection lives in the ``tenant_settings`` table under the key
``workflow_generation_model_id`` and is resolved for the SESSION tenant
(the root tenant when multi-tenancy is off). Each tenant configures its
own model — there is no global fallback.

The same selection is the workspace's single **authoring model**: it authors
Skill/SOP workflows, base implementation plans, and optimized plans.  The
resolver below is the ONLY place that answers "which model authors plans?".
There is deliberately **no fallback**: an unset value, or a value no longer
present in the tenant's enabled model catalogue, yields a structured reason
instead of silently selecting another model (never the agent runtime model,
never a first-available config).

Control-Center-only: this module reads PostgreSQL, so Agent Runtime and
Communication Hub must never import it (they receive identifiers through the
internal agent-context endpoint instead).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tenancy.tenant_settings_service import get_value, set_value

if TYPE_CHECKING:
    from app.db.models.agents import ModelConfig

#: Tenant-setting key holding the workflow generation model id.
WORKFLOW_GENERATION_MODEL_KEY = "workflow_generation_model_id"

#: ``reason_code`` — the workspace has no authoring model selected.
REASON_AUTHORING_MODEL_NOT_CONFIGURED = "authoring_model_not_configured"
#: ``reason_code`` — the selected authoring model is no longer offered.
REASON_AUTHORING_MODEL_NOT_ENABLED = "authoring_model_not_enabled"


def _not_configured_reason() -> str:
    return (
        "No authoring model is configured for this workspace. Select one in "
        "System Config (Workflow Generation Model) — implementation plans and "
        "optimization plans cannot be generated without it."
    )


def _not_enabled_reason(model_id: str) -> str:
    return (
        f"The configured authoring model '{model_id}' is no longer available in "
        "this workspace's model catalogue. Re-select an enabled model in System "
        "Config (Workflow Generation Model)."
    )


@dataclass(frozen=True)
class AuthoringModelState:
    """Derived (read-time) state of the workspace authoring model.

    - ``configured`` — a non-blank selection exists in ``tenant_settings``.
    - ``enabled`` — that selection resolves against the tenant's enabled model
      catalogue (``ModelConfig.enabled_models``).
    - ``model_id`` — echoes the raw stored value (even when unusable) so the
      UI can say "``<id>`` is no longer available — re-select".
    - ``model_config`` — the resolved tenant ``ModelConfig`` when usable.
    - ``reason_code`` / ``reason`` — set only when the model is unusable.
    """

    model_id: str | None
    configured: bool
    enabled: bool
    model_config: ModelConfig | None
    reason_code: str | None = None
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.configured and self.enabled and self.model_config is not None


@dataclass(frozen=True)
class AuthoringModel:
    """A usable authoring model: the model id plus its tenant model config."""

    model_id: str
    model_config: ModelConfig


class AuthoringModelNotConfigured(Exception):
    """No usable authoring model for the session tenant.

    Carries the structured ``reason_code`` (``authoring_model_not_configured``
    or ``authoring_model_not_enabled``) so HTTP callers can emit the
    documented ``412`` payload.  Never handled by selecting another model.
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


async def get_workflow_generation_model_id(db: AsyncSession) -> str | None:
    """Return the session tenant's workflow generation model ID, or None."""
    tenant_id = await _session_tenant_id(db)
    if tenant_id is None:
        return None
    value = await get_value(db, tenant_id, WORKFLOW_GENERATION_MODEL_KEY)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


async def get_authoring_model_state(db: AsyncSession) -> AuthoringModelState:
    """Return the session tenant's authoring-model state (never raises).

    Resolution: ``TenantSetting(tenant_id, workflow_generation_model_id)`` for
    the session tenant → ``ModelBindingLayer.resolve_model_config`` on the
    tenant-scoped session (the ORM query path is auto-constrained to the
    tenant).  "Not configured" and "not enabled" are DERIVED AT READ TIME —
    the stored setting is never rewritten to normalise a stale value.

    There is no fallback: when the selection is unusable the returned state
    reports it (``reason_code``) and ``model_config`` is ``None``.
    """
    from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer

    model_id = await get_workflow_generation_model_id(db)
    if not model_id:
        return AuthoringModelState(
            model_id=None,
            configured=False,
            enabled=False,
            model_config=None,
            reason_code=REASON_AUTHORING_MODEL_NOT_CONFIGURED,
            reason=_not_configured_reason(),
        )

    try:
        model_config = await ModelBindingLayer().resolve_model_config(model_id, db)
    except ModelBindingError:
        return AuthoringModelState(
            model_id=model_id,
            configured=True,
            enabled=False,
            model_config=None,
            reason_code=REASON_AUTHORING_MODEL_NOT_ENABLED,
            reason=_not_enabled_reason(model_id),
        )

    # A provider configuration can be disabled (e.g. cascaded from vendor
    # availability) while still listing the model in ``enabled_models``. Such a
    # selection is NOT usable for authoring — report it as not enabled rather
    # than attempting a call that is guaranteed to fail.
    if getattr(model_config, "is_disabled", False):
        return AuthoringModelState(
            model_id=model_id,
            configured=True,
            enabled=False,
            model_config=None,
            reason_code=REASON_AUTHORING_MODEL_NOT_ENABLED,
            reason=_not_enabled_reason(model_id),
        )

    return AuthoringModelState(
        model_id=model_id,
        configured=True,
        enabled=True,
        model_config=model_config,
    )


async def require_authoring_model(db: AsyncSession) -> AuthoringModel:
    """Return the usable authoring model for the session tenant.

    Raises ``AuthoringModelNotConfigured`` with the documented ``reason_code``
    when the workspace has no authoring model or the stored one is no longer
    in the tenant's enabled model catalogue.  Callers must NOT substitute
    another model (no agent-model or first-available fallback).
    """
    state = await get_authoring_model_state(db)
    if not state.usable or state.model_config is None or not state.model_id:
        raise AuthoringModelNotConfigured(
            state.reason_code or REASON_AUTHORING_MODEL_NOT_CONFIGURED,
            state.reason or _not_configured_reason(),
        )
    return AuthoringModel(
        model_id=state.model_id,
        model_config=state.model_config,
    )


async def set_workflow_generation_model_id(
    db: AsyncSession, model_id: str | None
) -> None:
    """Persist the session tenant's workflow generation model selection."""
    tenant_id = await _session_tenant_id(db)
    if tenant_id is None:
        raise RuntimeError("No tenant context available to store the workflow generation model")
    cleaned = (model_id or "").strip() or None
    await set_value(db, tenant_id, WORKFLOW_GENERATION_MODEL_KEY, cleaned)


async def adopt_legacy_app_yaml_value(
    db: AsyncSession,
    *,
    yaml_path_resolver=None,
) -> str | None:
    """Adopt the legacy ``config/app.yaml`` selection into the root tenant.

    One-time, best-effort migration for existing deployments: reads the
    legacy global ``workflow_generation_model_id`` from app.yaml and writes
    it to the ROOT tenant's ``tenant_settings`` row.  Idempotent — never
    overwrites an existing root-tenant selection.  The yaml value is left
    in place.  Returns the adopted model id, or None when nothing was
    adopted (no legacy value, or a selection already exists).  Caller
    commits.
    """
    import yaml

    from app.core.config import _app_yaml_path
    from app.services.tenancy.root_tenant import ensure_root_tenant

    resolve = yaml_path_resolver or _app_yaml_path
    legacy_value: str | None = None
    yaml_path = Path(resolve())
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
        if isinstance(loaded, dict):
            raw = loaded.get("workflow_generation_model_id")
            if isinstance(raw, str) and raw.strip():
                legacy_value = raw.strip()
    if not legacy_value:
        return None

    root = await ensure_root_tenant(db)
    existing = await get_value(db, root.id, WORKFLOW_GENERATION_MODEL_KEY)
    if isinstance(existing, str) and existing.strip():
        return None
    await set_value(db, root.id, WORKFLOW_GENERATION_MODEL_KEY, legacy_value)
    return legacy_value
