"""Per-tenant workflow generation model selection (DB-backed).

The selection lives in the ``tenant_settings`` table under the key
``workflow_generation_model_id`` and is resolved for the SESSION tenant
(the root tenant when multi-tenancy is off). Each tenant configures its
own model — there is no global fallback.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tenancy.tenant_settings_service import get_value, set_value

#: Tenant-setting key holding the workflow generation model id.
WORKFLOW_GENERATION_MODEL_KEY = "workflow_generation_model_id"


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
