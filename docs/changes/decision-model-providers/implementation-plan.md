# Implementation Plan: decision-model-providers

## Overview

Generalise the single "System One Provider" into a multi-vendor **Decision Model Providers** catalogue with per-model enablement, per-decision-tool model selection, and full guardrail/budget coverage — mirroring the existing LLM Model Configurations pattern. Work spans a backward-compatible Alembic migration, Control Center service/API changes only (service segregation and CC-only DB access are preserved), a renamed frontend settings page with CRUD + model toggles, an enabled-model selector in decision tool authoring, and backend/frontend tests.

## Task Checklist

### Phase 1 — Database Schema & Migration

- [x] 1.1 — Generalise the provider schema model for multi-vendor support
- [x] 1.2 — Create the decision model availability schema model
- [x] 1.3 — Add decision-model reference to DecisionTool and retire free-text provider_model
- [x] 1.4 — Export new models and generate the Alembic migration
- [x] 1.5 — Write the idempotent data migration (single provider → multi-provider, tools → model reference)
- [x] 1.6 — Apply and verify the migration locally

### Phase 2 — Backend Services (Control Center)

- [x] 2.1 — Extend provider config service to multi-provider CRUD with duplicate/referential-integrity rules
- [x] 2.2 — Add decision model catalogue service (enable/disable, cascade, enabled-models listing)
- [x] 2.3 — Generalise the vendor client registry to instantiate per-provider clients
- [x] 2.4 — Update Decision Execution Engine to resolve the tool's selected enabled model
- [x] 2.5 — Update decision tool service/authoring service for model selection validation

### Phase 3 — Guardrail & Budget Pipeline Hookup

- [x] 3.1 — Pre-call guardrail and budget/spend checks in the decision execution path
- [x] 3.2 — Record decision usage into the shared usage/spend store
- [x] 3.3 — Emit provider/model identity in execution responses and audit records

### Phase 4 — API Changes (Control Center)

- [x] 4.1 — Extend provider management endpoints (CRUD, connection test, duplicate handling)
- [x] 4.2 — Add model availability endpoints (list hierarchy, enable/disable)
- [x] 4.3 — Extend decision tool endpoints for model selection and enabled-models listing
- [x] 4.4 — Verify internal decision endpoints expose model identity and enforce blocked outcomes

### Phase 5 — Frontend: Settings Page

- [x] 5.1 — Rename "System One Providers" to "Decision Model Providers" (routing, page, i18n)
- [x] 5.2 — Convert settings page to multi-provider table with full CRUD dialogs
- [x] 5.3 — Add per-model enable/disable toggles with vendor-level cascade

### Phase 6 — Frontend: Decision Tool Authoring

- [x] 6.1 — Add enabled-decision-model selector to DecisionToolForm
- [x] 6.2 — Show selected model on decision tool list/detail views and result views

### Phase 7 — Tests & Verification

- [x] 7.1 — Backend unit tests (services, engine, availability, migration compatibility)
- [x] 7.2 — Backend API/integration tests (CRUD, delete-blocking, guardrail/budget blocking, internal endpoints)
- [x] 7.3 — Frontend tests (settings page, model toggles, authoring selector)
- [x] 7.4 — Full regression run and migration verification against real database (migration `8144e472dce9` at head, idempotency + legacy-row dedup verified; regression exercised via the real-backend E2E suite `decision-model-providers-real-backend.spec.ts` against the live app + PostgreSQL)

---

## Phase 1 — Database Schema & Migration

**1.1 — Generalise the provider schema model.** Update `SystemOneProviderConfig` in `backend/app/db/models/system_one_provider_config.py` to support multiple rows per tenant: per-vendor display-name uniqueness (tenant-scoped), vendor-level `enabled` flag, and a `default_model` column (per the data model doc). Keep the internal table identity unchanged to limit migration risk; rename only the concept in the docstring and extend the vendor type enum. — _Done when: the model supports multiple providers per tenant with unique (tenant, vendor type, display name) and the enum is extensible._

**1.2 — Create the decision model availability schema model.** New file `backend/app/db/models/decision_model_availability.py` mirroring `backend/app/db/models/model_availability.py`: FK to provider, `model_name` unique per provider, `is_disabled`, `disabled_reason` enum (`manual` / `vendor_cascaded`), timestamps, optional tenant. — _Done when: the model exists, is exported from `backend/app/db/models/__init__.py`, and matches the availability pattern with cascade-aware disable reasons._

**1.3 — DecisionTool model reference.** In `backend/app/db/models/decision_tools.py`, add a nullable FK from `DecisionTool` to the availability row; keep `provider_model` readable during migration (backfilled, then retired per data-model doc). — _Done when: the reference exists, `provider_model` is marked legacy, and existing rows remain loadable._

**1.4 — Export & autogenerate migration.** Update models `__init__.py`; run `python -m alembic revision --autogenerate` in `backend/`. Review: correct `down_revision` chain, reversible `downgrade()`, no parameterized DDL, no enum `create_type` issues. — _Done when: the migration file reviews clean and is chained after the current head._

**1.5 — Idempotent data migration.** In the migration: promote the existing single provider row into the new multi-provider shape; seed its `default_model` as the initial enabled availability row; backfill each `DecisionTool`'s model reference from its legacy `provider_model` (fallback to migrated default). Handle `NULL`s explicitly; make re-runs no-ops. — _Done when: re-running the upgrade on an upgraded DB changes nothing, existing credentials survive, and existing tools resolve to the migrated provider/model._

**1.6 — Apply & verify.** `python -m alembic current` → `python -m alembic upgrade head` → `python -m alembic current`. Restart backend via `parthenon.ps1` so cached ORM models refresh. — _Done when: `alembic current` shows the new revision and the backend starts without 500s._

## Phase 2 — Backend Services (Control Center)

**2.1 — Multi-provider CRUD.** Extend `SystemOneProviderConfigService` in `backend/app/services/system_one/provider_config_service.py`: create/update/delete/list per tenant; duplicate display-name-per-vendor rejection; delete blocked with named blocking references while any decision tool references one of its models; credentials write-only (never in `to_read`); keep `test_connection` per provider; replace `get_active_provider` semantics with tenant-scoped multi-provider lookup (retain a thin wrapper for backward compat). — _Done when: full CRUD works per tenant, duplicates rejected, in-use deletion blocked with clear errors, no credential ever returned._

**2.2 — Decision model catalogue service.** New service in `backend/app/services/system_one/` (or `control_center/`) mirroring `ModelAvailabilityService` (`backend/app/services/control_center/model_availability_service.py`): vendor-level `set_vendor_disabled` cascading to models (preserving manual disables as `vendor_cascaded`), `set_model_disabled`, `list_hierarchy`, and `list_enabled_models` used by tool authoring. — _Done when: toggles take effect immediately, cascade preserves manual state, and only enabled (provider enabled + model enabled) models are listed._

**2.3 — Per-provider client registry.** Extend `get_system_one_client` in `backend/app/services/system_one/client.py` so each registered vendor type instantiates its client from its own provider config (endpoint + credential decrypted at call time only, CC-only). — _Done when: evaluations can target any enabled provider's client, credentials decrypted only during the vendor call._

**2.4 — Engine resolves selected model.** In `backend/app/services/system_one/decision_engine.py`, `DecisionExecutionEngine.execute` resolves the tool's model reference → provider + model; disabled/unavailable selections raise `DecisionExecutionError` with an actionable message; execution records capture provider/model identity. — _Done when: a tool evaluates against its selected model, changes take effect on next evaluation without restart, and disabled selections fail with a clear error._

**2.5 — Tool service validation.** Update `DecisionToolService` create/update (`backend/app/services/system_one/decision_tool_service.py`) to validate the selected availability row exists and is enabled; update `backend/app/services/system_one/decision_authoring_service.py` draft generation if it references provider/model defaults. — _Done when: create/update reject unknown/disabled models and legacy payloads without a selection still resolve via the migrated default._

## Phase 3 — Guardrail & Budget Pipeline Hookup

**3.1 — Pre-call checks.** In the decision execution path (CC), invoke the same pre-call guardrail/budget checks used for regular agent model calls (see `backend/app/services/agents/guardrails.py` stop reasons and the posture checks in `backend/app/services/control_center/model_availability_service.py` / `model_usage_guardrail_service.py`). Breach or exhausted budget blocks the evaluation with the same stop reasons and audit trail (guardrail threshold events persist via `backend/app/db/models/guardrail_threshold_event.py`). — _Done when: a configured breach or exhausted budget blocks the vendor call with regular-model-equivalent outcomes._

**3.2 — Usage metering.** Record decision usage plus provider/model identity on the persisted `DecisionExecutionResult` (`answers.provider`, plus the `provider_model` column) so every evaluation is auditable. _Deviation:_ decision usage is **not** wired into the AgentJob-derived `ModelUsagePosture` rollups — aggregated usage/spend reporting does not yet include decision calls (known limitation, follow-up change). — _Done when: decision usage and provider/model identity are persisted on the execution result and verified by integration tests._

**3.3 — Identity in responses/audit.** Internal execution responses and logs include provider display name/vendor type and model name. — _Done when: any evaluation can be attributed to its provider/model from the response or logs._

## Phase 4 — API Changes (Control Center)

**4.1 — Provider endpoints.** Extend `backend/app/api/v1/system_one.py`: list/create/update/delete stay at `/providers`, now multi-row; duplicate errors and delete-blocking return structured, user-friendly errors; connection test per provider. — _Done when: all CRUD flows behave per acceptance criteria with JWT auth and tenant scoping._

**4.2 — Model availability endpoints.** Add endpoints for listing the provider/model hierarchy and setting vendor/model disabled state. — _Done when: toggles persist and are reflected immediately in authoring listings._

**4.3 — Decision tool endpoints.** Extend `backend/app/api/v1/decision_tools.py`: create/update accept the model reference; add enabled-models listing for the authoring selector; detail/list include the selected model. — _Done when: authoring UI can list enabled models and persist selections._

**4.4 — Internal endpoints.** Verify the CH-called internal decision endpoints (`/decision/list`, `/decision/execute`) expose per-tool model identity and blocked outcomes; they must keep using `internal_httpx_client` signed headers and never leak credentials. — _Done when: CH bridges multi-provider tools unchanged and blocked evaluations return regular-model-equivalent error outcomes._

## Phase 5 — Frontend: Settings Page

**5.1 — Rename.** Update route, page component name/labels, nav entry in `frontend/src/app/AppShell.tsx` / `AppRouter.tsx`, and all `systemOne.*` strings in `frontend/src/i18n/locales/en.json` to "Decision Model Providers". All text via `t()`. — _Done when: no "System One" appears user-facing; internal identifiers unchanged._

**5.2 — Multi-provider CRUD UI.** Rework `frontend/src/pages/system/SystemOneProviderConfigPage.tsx` and `frontend/src/api/systemOneApi.ts` into a providers table (vendor chip, credentials-set indicator) with create/edit/delete dialogs following the Dialog Error Handling Standard (`useDialogErrorHandler`), confirm-on-delete, and inline visible validation. — _Done when: all PRD CRUD acceptance criteria pass without page reloads and errors surface in-dialog._

**5.3 — Model toggles.** Add per-provider model catalogue view with per-model switches and a vendor-level enable/disable that cascades, implemented as inline React Query mutations in the page component (invalidating the hierarchy query on success), following the semantics of `frontend/src/hooks/useModelAvailability.ts` without extracting a shared hook. — _Done when: toggles take effect immediately for authoring._

## Phase 6 — Frontend: Decision Tool Authoring

**6.1 — Model selector.** In `frontend/src/components/decisionTools/DecisionToolForm.tsx`, add a selector fed by the enabled-models listing only; validation on submit; error state handled in-dialog. — _Done when: only enabled models are selectable and selection persists._

**6.2 — Display selection.** Show the selected provider/model on `frontend/src/pages/agents/DecisionToolsPage.tsx` list/detail and on `frontend/src/components/results/DecisionResultView.tsx`. — _Done when: users can see which model each tool uses without opening the editor._

## Phase 7 — Tests & Verification

**7.1 — Backend unit tests.** Extend `backend/tests/unit/test_decision_engine.py`, `test_system_one_client.py`, and add tests for the catalogue service (cascade semantics), duplicate rejection, delete-blocking, and credential non-exposure. — _Done when: all new unit tests pass._

**7.2 — Backend API/integration tests.** Add tests under `backend/tests/api/` / `backend/tests/integration/` covering CRUD endpoints, model toggles, guardrail/budget blocking of evaluations, internal endpoint identity fields, and migration effect verification against a real database (constraint + backfill assertions). — _Done when: integration tests pass with `alembic upgrade head` applied._

**7.3 — Frontend tests.** Update `frontend/src/__tests__/SystemOneProviderConfigPage.test.tsx` (rename + multi-provider CRUD), `DecisionToolForm.test.tsx` (selector), `DecisionToolsPage.test.tsx`. Run Vitest with the JSON reporter per AGENTS.md. — _Done when: frontend suites pass._

**7.4 — Regression & migration check.** `alembic current` confirms head; restart backend via `parthenon.ps1`; run full backend and frontend suites; manually verify an existing decision tool still evaluates after upgrade. — _Done when: no regressions and post-migration evaluation succeeds._

## Completion Checklist

- [x] All Phase 1–7 tasks checked off
- [x] Migration applied and idempotency verified (`alembic upgrade head` run twice cleanly)
- [x] No credential ever returned by any read endpoint (verified by test)
- [x] Delete-blocking, duplicate rejection, and disabled-model errors covered by tests
- [x] Guardrail/budget blocking and usage metering verified for decision evaluations (usage + provider/model identity persisted on `DecisionExecutionResult`; posture-rollup reporting is a known limitation)
- [x] No user-facing "System One" strings remain; all UI text via `t()`
- [x] Backend and frontend test suites fully green
- [x] Top-priority rules respected: three services segregated, DB touched by CC only, agents hold no credentials
