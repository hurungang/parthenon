# Multi-Tenancy — Tenant Settings

> Part of the [multi-tenancy hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

Two settings stores exist and the distinction is structural:

| Store | Scope | Purpose |
|-------|-------|---------|
| `PlatformSetting` | Tenant-agnostic, globally unique per key | Describes the deployment (e.g. `multi_tenancy_enabled`) |
| `TenantSetting` | One row per `(tenant_id, key)` | Describes one workspace; must never leak across tenants |

`TenantSetting` values are JSON and are scoped by the standard `apply_tenant_scope` gateway — no bespoke tenant filter. Callers resolve the session tenant (root tenant when multi-tenancy is off) and pass an explicit `tenant_id`. No consumer rewrites a setting row to normalise a stale value; unusable states are derived at read time so the operator can see and correct them.

## Tenant-scoped keys

| Key | Owner module | Meaning |
|-----|--------------|---------|
| `workflow_generation_model_id` | agents (authoring) | The workspace **authoring model** used for Skill/SOP workflow generation, base-plan generation and optimization-plan generation |
| `optimizer_model_id` | agents (optimizer) | Optional dedicated model for the optimization conversation; unset inherits the authoring model |
| `conversation_turn_resume_ttl_seconds` | conversations | The answerable window for a paused conversational turn (default 900 s, clamped ≥ 30); exposed in the tenant settings API |

The Control Center Assistant model is **not** a tenant setting row: it is stored per tenant on the assistant `AgentType.model_id` and configured via `/agents/model-configs/assistant-model` (see [agents — assistant](../agents/assistant.md)).

## Behaviour

- **Authoring model** — resolution wraps `get_workflow_generation_model_id` + `ModelBindingLayer.resolve_model_config`; "not configured" (blank) and "not enabled" (absent from every enabled-model list) are derived at read time. No fallback to the agent model or an arbitrary config.
- **Optimizer model** — explicit and usable → optimizer; unset → authoring; explicit but unusable → `optimizer_model_not_enabled`; both unusable → `optimizer_model_not_configured`. Never falls back to the agent's runtime model and never persists a resolved value.
- **Resume TTL** — Control Center owns the window end-to-end: `PUT …/resume` ignores a client-supplied expiry and recomputes it from tenant policy, and the checkpoint payload uses the same live window so it cannot expire before the answer window.
- **Legacy adoption** — a one-time, idempotent startup adoption copies the legacy `config/app.yaml` workflow-generation value into the root tenant's row only when that row is empty.

## Read/write pattern

| Step | What happens |
|------|--------------|
| Resolve tenant | Callers use the session tenant (`_session_tenant_id`), falling back to the root tenant when tenancy is off |
| Read | `get_value(db, tenant_id, key)` returns the JSON value; absence is a valid state, not an error |
| Derive usability | The consumer resolves the value against the tenant's enabled catalogue at read time (`configured` / `enabled` / `reason_code`) — the row is never rewritten |
| Write | `set_value(db, tenant_id, key, value)` upserts one row; `null`/empty clears the selection where the contract allows it |
| Scope | `apply_tenant_scope` enforces the tenant on every statement; a cross-tenant read is impossible in application code |
| Expose | Only the fields a surface needs (for example the resume TTL in the tenant settings API) are projected |

## Consumer summary

| Consumer | Reads | Failure behaviour |
|----------|-------|-------------------|
| Skill/SOP workflow generation | Authoring model | Structured not-configured error; nothing generated |
| Base plan generation | Authoring model | `412 plan_generation_unavailable`; no plan write, serving versions not retired |
| Optimization plan generation (command or conversation) | Authoring model, then the optimizer model when explicitly set | Structured error; executes on no substitute model |
| Optimization conversation context | Optimizer model → authoring fallback | `412 optimizer_model_unavailable`; fail closed |
| Paused conversational turns | Resume TTL | Platform default (900 s) when the tenant has no override |
| Checkpoint payload expiry | Resume TTL (live record window) | Payload cannot outlive or predecease the answer window |

## Rollout notes

The store is additive: `tenant_settings` was created by one migration and every later key is a new row, not a schema change. A tenant with no rows behaves exactly like a deployment whose settings are unset — the consuming surface shows its "configure me" state. Existing deployments pick up the legacy workflow-generation value through the one-time root adoption; no other key has a legacy source.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TenantSetting` | model | Tenant-scoped key/value store (`tenant_settings`): unique `(tenant_id, key)`, FK → tenants CASCADE, JSON value | `backend/app/db/models/tenant_setting.py` |
| `get_value` / `set_value` | functions | Typed async read/upsert helpers requiring an explicit `tenant_id` | `backend/app/services/tenancy/tenant_settings_service.py` |
| `WORKFLOW_GENERATION_MODEL_KEY` | constant | `workflow_generation_model_id` | `backend/app/services/agents/workflow_generation_settings.py` |
| `get_workflow_generation_model_id` / `set_workflow_generation_model_id` | functions | Session-tenant read/persist of the authoring selection | `backend/app/services/agents/workflow_generation_settings.py` |
| `AuthoringModelState` / `AuthoringModel` / `AuthoringModelNotConfigured` | types / exception | Authoring-model derivation and reason codes | `backend/app/services/agents/workflow_generation_settings.py` |
| `get_authoring_model_state` / `require_authoring_model` / `REASON_AUTHORING_MODEL_NOT_CONFIGURED` / `REASON_AUTHORING_MODEL_NOT_ENABLED` | functions / constants | Non-raising and raising resolvers (no fallback) | `backend/app/services/agents/workflow_generation_settings.py` |
| `adopt_legacy_app_yaml_value` | function | One-time root-tenant adoption of the legacy YAML value | `backend/app/services/agents/workflow_generation_settings.py`, `backend/app/main.py` |
| `OPTIMIZER_MODEL_KEY` / `OptimizerModelState` / `OptimizerModelNotConfigured` | constants / types / exception | Optimizer model setting and state | `backend/app/services/agents/optimizer_model_settings.py` |
| `get_optimizer_model_state` / `require_optimizer_model` / `get_optimizer_model_id` / `set_optimizer_model_id` / `REASON_OPTIMIZER_MODEL_NOT_CONFIGURED` / `REASON_OPTIMIZER_MODEL_NOT_ENABLED` | functions / constants | Explicit → authoring resolution; no agent-model fallback; CC-only module | `backend/app/services/agents/optimizer_model_settings.py` |
| `resolve_resume_ttl_seconds` / `resolve_resume_expiry` / `set_resume_ttl_seconds` | functions | Tenant policy read (coerce/clamp), expiry computation, persistence | `backend/app/services/conversations/turn_resume_settings.py` |
| `conversation_turn_resume_ttl_seconds` | settings field | Platform default (900 s) used when the tenant has no override | `backend/app/core/config.py` |
| `TenantSettingsRead` / `TenantSettingsUpdate` | schemas | Tenant settings API; exposes/accepts the resume TTL (`ge=30`, 422 below) | `backend/app/api/v1/tenant.py` |
| `SystemConfigPage` model selectors | component | Workspace-scoped authoring and optimizer model selection through the existing REST contracts | `frontend/src/pages/system/SystemConfigPage.tsx` |
| tenant API typing | module | `conversation_turn_resume_ttl_seconds` field (API-only; no UI control) | `frontend/src/api/tenantApi.ts` |
| migration `6fba31147599` | migration | Creates `tenant_settings` with the per-tenant unique index and tenant FK CASCADE | `backend/alembic/versions/6fba31147599_add_tenant_settings_table.py` |
| `test_tenant_settings_workflow_generation` | test | Per-tenant isolation, upsert semantics, legacy adoption idempotency | `backend/tests/test_tenant_settings_workflow_generation.py` |
| `test_tenant_resume_ttl_setting` | test | Default/override/clamp/malformed values, two-tenant isolation, expiry authority | `backend/tests/unit/test_tenant_resume_ttl_setting.py` |
| `test_optimizer_model_settings` | test | Explicit/unset/stale derivation, tenant scoping, no-substitution, CC-only boundary | `backend/tests/unit/services/test_optimizer_model_settings.py` |
