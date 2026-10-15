# Tech Spec — Decision Model Providers

Change: `decision-model-providers` · Owner: developer
Inputs: `prd.md`, `spec-change.md`, `architecture.md`, `data-model.md`, `implementation-plan.md`

---

## Technical Overview

Generalise the single "System One Provider" decision-skill vendor configuration into a multi-vendor **Decision Model Providers** catalogue inside Control Center (the only DB-connected service). Administrators register any number of decision vendors with encrypted, write-only credentials, manage a per-vendor model catalogue with individual enable/disable and vendor-level cascade (mirroring the LLM Model Configurations availability pattern), and each decision tool explicitly references one enabled decision model instead of the legacy free-text `provider_model`. The decision execution path in Control Center resolves the tool's selected model to a provider + model pair, applies the same pre-call guardrail and budget/spend checks used for regular agent model usage before any vendor call, and records usage and provider/model identity on the persisted execution result for audit (note: not yet rolled up into the AgentJob-derived ModelUsagePosture reporting — a known limitation). Internal identifiers (table names, `system_one` module paths, MCP `decision____<tool>` wire format) remain unchanged to limit migration risk; the rename is user-facing only (UI, i18n, docs). Agent Runtime and Communication Hub are untouched structurally — CH keeps forwarding decision calls to Control Center internal endpoints via `internal_httpx_client` with signed tenant headers, and agents never receive credentials or provider configuration. A single idempotent Alembic migration backfills the legacy singleton provider row into the multi-provider shape and maps existing decision tools to the migrated default model.

## Component Breakdown

| Component | Responsibility |
|---|---|
| `SystemOneProviderConfig` schema model (CC DB) | Generalised to multiple rows per tenant: tenant-scoped per-vendor display-name uniqueness, vendor-level `enabled` flag, `default_model`; conceptually renamed Decision Model Provider (internal table identity unchanged) |
| `DecisionModelAvailability` schema model (CC DB, **new**) | Per-model enable/disable record per provider, mirroring `ModelAvailability` (`is_disabled`, `disabled_reason` = `manual` / `vendor_cascaded`) |
| `DecisionTool` schema model (CC DB) | Gains a nullable FK to the selected availability row; legacy `provider_model` free text retired after migration backfill |
| Alembic migration (backend/alembic/versions) | Idempotent schema + data migration: multi-provider shape, availability seeding from `default_model`, tool backfill from legacy `provider_model` |
| `SystemOneProviderConfigService` (CC service) | Extended to multi-provider CRUD per tenant: duplicate display-name-per-vendor rejection, delete blocked with named blocking references while tools reference its models, credentials write-only (`to_read` never exposes them), per-provider `test_connection`; `get_active_provider` retained as thin backward-compat wrapper |
| Decision model catalogue service (CC service, **new**) | Mirrors `ModelAvailabilityService`: `set_vendor_disabled` (cascade preserving manual disables), `set_model_disabled`, `list_hierarchy`, `list_enabled_models` for authoring |
| `SystemOneClient` / `TypeSafeJevClient` registry (CC service) | `get_system_one_client` generalised so each vendor type instantiates a client from its own provider config; credential decrypted at call time only, inside CC |
| `DecisionExecutionEngine` (CC service) | `execute` resolves the tool's selected availability row → provider + model; disabled/unavailable selections raise `DecisionExecutionError` with actionable message; execution state/records capture provider and model identity |
| Guardrail & budget hookup (CC service) | Decision evaluation path invokes the same pre-call guardrail checks (`GuardrailStop` semantics, `guardrail_threshold_event` persistence) and budget/spend posture checks used for regular model calls before the vendor call; usage metered into the shared store on success |
| Internal decision API (CC, `api/v1/internal/system_tools.py`) | `/decision/list` and `/decision/execute` extended to expose per-tool provider/model identity and blocked (guardrail/budget) outcomes; signed-header tenant scoping unchanged |
| Provider management API (CC, `api/v1/system_one.py`) | `/providers` CRUD becomes multi-row; structured duplicate/delete-blocking errors; connection test endpoint per provider |
| Model availability API (CC, **new** endpoints in `system_one.py`) | Provider/model hierarchy listing and vendor/model disable toggles |
| Decision tool API (CC, `api/v1/decision_tools.py`) | Create/update accept the model reference; enabled-models listing for the authoring selector; list/detail include the selected model |
| Decision guardrail API (CC, **new** endpoints in `system_one.py`) | Decision-scoped guardrail CRUD + posture on the SAME `model_guardrail_configurations` / `model_usage_postures` tables (`config_source='decision_provider'`, keyed by `decision_provider_id`); LLM guardrail endpoints/lists never mix decision rows and vice versa |
| Decision Model Providers settings page (Frontend, renamed) | Multi-provider table (vendor chip, endpoint, credentials indicator, enabled flag) with create/edit/delete dialogs per the Dialog Error Handling Standard; model management (enabled-models chips, vendor sync, default model) lives in the editor dialog — no inline expandable catalogue; embedded collapsible guardrail section rendering the reused `VendorModelGuardrailPanel` with decision-scoped data; all text via `t()` |
| Decision tool authoring UI (Frontend) | `DecisionToolForm` gains an enabled-decision-model selector (enabled models only); list/detail/result views display the selected model |

## API Changes

Control Center external API (JWT-authenticated, tenant-scoped):

- `GET /api/v1/system-one/providers` — **modified**: returns all providers for the tenant (was effectively single); never includes credentials.
- `POST /api/v1/system-one/providers` — **modified**: creates a provider; duplicate display name per vendor type returns a structured user-friendly error.
- `PATCH /api/v1/system-one/providers/{id}` — **modified**: partial update; credential omitted/placeholder leaves stored secret unchanged, new value replaces it.
- `DELETE /api/v1/system-one/providers/{id}` — **modified**: delete blocked with a structured error naming blocking decision tools when referenced.
- Duplicate (`SystemOneProviderDuplicateError`) and in-use (`SystemOneProviderInUseError`) service errors are mapped to **HTTP 409** with user-friendly detail.
- `POST /api/v1/system-one/providers/{id}/test` — **modified**: connection test against the specific provider.
- `GET /api/v1/system-one/status` — **modified**: reports multi-provider status.
- `GET /api/v1/system-one/models` — **new**: provider→model hierarchy with enabled state.
- `PUT /api/v1/system-one/models/{id}/availability` (or equivalent) — **new**: set model disabled state (`manual`).
- `PUT /api/v1/system-one/providers/{id}/availability` — **new**: vendor-level enable/disable (cascades).
- `GET /api/v1/system-one/enabled-models` — **new**: flat enabled-models list feeding the authoring selector.
- Decision tool endpoints (`/api/v1/decision-tools`) — **modified**: create/update accept a decision-model availability reference; list/detail responses include the selected provider/model; enabled-models listing available for authoring.
- `GET /api/v1/system-one/providers/{id}/guardrails` — **new** (FIX-20261014-003000): decision-scope guardrails for one provider.
- `POST /api/v1/system-one/providers/{id}/guardrails` — **new**: create one per-period decision guardrail; duplicate (provider, model, period) → 409 `guardrail_period_conflict`; unknown provider → 404.
- `PUT /api/v1/system-one/guardrails/{config_id}` / `DELETE ...` — **new**: update/delete a decision guardrail (period immutable); LLM (`model_config`) rows are not reachable → 404.
- `GET /api/v1/system-one/providers/{id}/guardrails/posture?refresh=` — **new**: usage posture snapshots computed from persisted decision executions.

Internal (CH→CC, signed `X-Internal-Tenant-*` headers via `internal_httpx_client`):

- `POST /internal/system-tools/decision/list` — **modified**: catalogue entries include the tool's selected provider/model identity.
- `POST /internal/system-tools/decision/execute` — **modified**: response includes provider/model identity; guardrail/budget blocks return the same structured error outcomes as regular model usage; no credentials ever cross the wire.

## State Management

- Settings page uses React Query mutations (existing `systemOneApi` client, reworked to multi-provider) with automatic list invalidation so creates/updates/deletes/toggles reflect immediately without page reload.
- Provider create/edit dialogs follow the Dialog Error Handling Standard: `dialogError` state via `useDialogErrorHandler`, cleared on open/close, surfaced via `PermissionDeniedAlert` inside `DialogContent`.
- Enabled models are chosen through an explicit selection control (MUI `Autocomplete` `multiple` + `freeSolo`) in the provider create/edit dialog: chips are the enabled models sent in the payload; typed entries remain possible. Option set = already-selected chips ∪ vendor-synced models (in-session `dialogModels`) ∪ the provider's catalogued availability rows (edit mode). `default_model` renders directly below, its native select options are exactly the currently-selected chips, it is disabled (helper `defaultModelSyncFirst`) until ≥1 model is selected, and removing a chip that was the default clears `default_model` (blank placeholder option) — a stale default is never sent.
- Model toggles: per-provider model enable/disable no longer lives on the settings page — the inline expandable catalogue was removed (it duplicated the editor and rendered status chips against different data); enablement is managed through the editor dialog's enabled-models chips (and vendor sync), while the embedded guardrail panel renders model status read-only in decision scope.
- Embedded guardrail section (FIX-20261014-003000): a collapsible section on the settings page hosts a provider select plus the reused `VendorModelGuardrailPanel` with `decisionProviderId`; in decision scope the panel's data comes from `useDecisionGuardrails` / `useDecisionGuardrailPosture` (decision-scoped `/system-one` endpoints) and guardrail create/update/delete go through `useCreateDecisionGuardrail` / `useUpdateDecisionGuardrail` / `useDeleteDecisionGuardrail`; the LLM `/agents` queries are disabled so no model-config endpoint is ever called from this page.
- Decision tool authoring form holds the selected availability reference in local form state, validated on submit against the enabled-models listing; the listing is fetched (not cached long-term) to avoid stale selections — a since-disabled selection still fails safely at evaluation time server-side.
- No new global stores; all server state stays in React Query caches keyed per tenant session.

## Data Access Patterns

- All database access is server-side in Control Center only (top-priority rule: CC is the sole DB-connected service). Frontend accesses data exclusively through CC REST APIs; CH reaches decision data only through CC internal endpoints; AR never touches provider data.
- Provider reads go through `SystemOneProviderConfigService.list_all` / `get` with a tenant filter (`_tenant_filter`); `to_read` strips credentials — write-only secret pattern identical to LLM Model Configurations.
- Enabled-model resolution at evaluation time is a join across `DecisionTool` → `DecisionModelAvailability` → `SystemOneProviderConfig` within the signed tenant scope, performed inside `DecisionExecutionEngine` per call (no caching of enabled state across requests, so toggles take effect on the next evaluation without restart).
- Credential decryption happens only inside CC at vendor-call time (`get_system_one_client` path); decrypted values never appear in responses, logs, or audit records.
- Usage metering deviation: decision usage plus provider/model identity is persisted on `DecisionExecutionResult` (`answers.provider` per question entry, plus the `provider_model` column) so every evaluation is auditable. It is **not** wired into the AgentJob-derived `ModelUsagePosture` rollups — aggregated usage/spend reporting views do not yet include decision usage (known limitation, to be closed in a follow-up change).

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemOneProviderType` | enum | Vendor type enum; extended beyond the initial vendor | backend/app/db/models/system_one_provider_config.py |
| `SystemOneProviderConfig` | model | Provider row; generalised to multi-row per tenant, vendor-level `enabled`, `default_model` | backend/app/db/models/system_one_provider_config.py |
| `DecisionModelAvailability` | model (**new**) | Per-model enable/disable record mirroring `ModelAvailability` | backend/app/db/models/decision_model_availability.py |
| `ModelAvailability` | model | Pattern to mirror for the new availability entity | backend/app/db/models/model_availability.py |
| `ModelAvailabilityDisabledReason` | enum | `manual` / `vendor_cascaded` disable reasons (pattern source) | backend/app/db/models/model_availability.py |
| `DecisionTool` | model | Gains FK to selected availability row; `provider_model` retired | backend/app/db/models/decision_tools.py |
| `DecisionToolStatus` | enum | Tool status (draft/active/disabled) | backend/app/db/models/decision_tools.py |
| models `__init__` exports | module | Export the new availability model | backend/app/db/models/__init__.py |
| `GuardrailThresholdEvent` | model | Guardrail breach persistence reused for decision evaluations | backend/app/db/models/guardrail_threshold_event.py |
| `DecisionExecutionResult` | model | Persists each decision execution; `answers.provider` carries per-question provider/model identity for audit | backend/app/db/models/results.py |
| `SystemOneProviderError` | exception | Provider service error base | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService` | class | Multi-provider CRUD, duplicate rejection, delete-blocking, credential masking | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.create` | method | Create provider (tenant-scoped, uniqueness enforced) | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.update` | method | Update provider; credential placeholder semantics | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.delete` | method | Delete with referential-integrity blocking | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.list_all` | method | Tenant-scoped multi-provider listing | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.get_active_provider` | method | Backward-compat wrapper over multi-provider lookup | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.to_read` | method | Read serialization; never exposes credentials | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.test_connection` | method | Per-provider connection test (CC-only) | backend/app/services/system_one/provider_config_service.py |
| `_tenant_filter` | function | Tenant scoping helper for provider queries | backend/app/services/system_one/provider_config_service.py |
| Decision model catalogue service | class (**new**) | `DecisionModelCatalogueService`: `set_vendor_disabled` cascade, `set_model_disabled`, `list_hierarchy`, `list_enabled_models`, `resolve_selection`, `check_pre_call`, `usage_identity`; mirrors availability service pattern | backend/app/services/system_one/decision_model_availability_service.py |
| `ModelAvailabilityService` | class | Reference implementation for cascade/toggle semantics | backend/app/services/control_center/model_availability_service.py |
| `ModelAvailabilityService.set_vendor_disabled` | method | Vendor-level cascade pattern to mirror | backend/app/services/control_center/model_availability_service.py |
| `ModelAvailabilityService.set_model_disabled` | method | Per-model toggle pattern to mirror | backend/app/services/control_center/model_availability_service.py |
| `ModelAvailabilityService.list_hierarchy` | method | Hierarchy listing pattern to mirror | backend/app/services/control_center/model_availability_service.py |
| `ModelUsageGuardrailService` | class | Budget/spend posture service reused for decision pre-call checks and metering | backend/app/services/control_center/model_usage_guardrail_service.py |
| `ModelUsageGuardrailService.get_current_posture` | method | Spend posture check applied before decision vendor calls | backend/app/services/control_center/model_usage_guardrail_service.py |
| `GuardrailStop` | exception | Guardrail breach exception semantics reused in decision path | backend/app/services/agents/guardrails.py |
| `GuardrailStopReason` | class | Stop reason constants shared with regular model usage | backend/app/services/agents/guardrails.py |
| `SystemOneClient` | protocol | Vendor client interface | backend/app/services/system_one/client.py |
| `TypeSafeJevClient` | class | Concrete vendor client | backend/app/services/system_one/client.py |
| `get_system_one_client` | function | Client registry; generalised to instantiate per-provider from its own config | backend/app/services/system_one/client.py |
| `build_questions_payload` | function | Questions payload for vendor evaluate call | backend/app/services/system_one/client.py |
| `SystemOneClientError` | exception | Vendor client errors (timeouts, HTTP failures) | backend/app/services/system_one/client.py |
| `DecisionExecutionError` | exception | Actionable errors for disabled/unavailable model selections | backend/app/services/system_one/decision_engine.py |
| `DecisionExecutionEngine` | class | Decision evaluation orchestration; resolves selected enabled model, applies guardrail/budget pre-call checks, records provider/model identity | backend/app/services/system_one/decision_engine.py |
| `DecisionExecutionEngine.execute` | method | Evaluation entry point (model resolution + vendor call + metering) | backend/app/services/system_one/decision_engine.py |
| `DecisionExecutionEngine.resolve_tool` | method | Tool resolution within tenant scope | backend/app/services/system_one/decision_engine.py |
| `DecisionExecutionEngine.resolve_model_selection` | method | Resolves the tool's selected availability row → provider + model (legacy fallback: enabled provider + provider_model) | backend/app/services/system_one/decision_engine.py |
| `DecisionExecutionEngine.build_state` | method | Execution state capture (unchanged) | backend/app/services/system_one/decision_engine.py |
| `compute_confidence_gate` | function | Confidence gating (unchanged) | backend/app/services/system_one/decision_engine.py |
| `DecisionToolService` | class | Tool CRUD; validates selected availability row exists and is enabled | backend/app/services/system_one/decision_tool_service.py |
| `DecisionToolService.create` | method | Create tool with model reference validation | backend/app/services/system_one/decision_tool_service.py |
| `DecisionToolService.update` | method | Update tool with model reference validation | backend/app/services/system_one/decision_tool_service.py |
| `DecisionToolValidationError` | exception | Validation errors incl. unknown/disabled model selection | backend/app/services/system_one/decision_tool_service.py |
| `is_decision_tool_ready` | function | Readiness check (unchanged semantics) | backend/app/services/system_one/decision_tool_service.py |
| `decision_tool_virtual_tool_id` | function | Virtual tool ID mapping (wire format unchanged) | backend/app/services/system_one/decision_tool_service.py |
| `generate_decision_draft` | function | Authoring draft generation; updated if it references provider/model defaults | backend/app/services/system_one/decision_authoring_service.py |
| `list_providers` | endpoint | Modified: multi-provider listing | backend/app/api/v1/system_one.py |
| `create_provider` | endpoint | Modified: duplicate rejection with structured error | backend/app/api/v1/system_one.py |
| `update_provider` | endpoint | Modified: partial update via PATCH; credential placeholder semantics | backend/app/api/v1/system_one.py |
| `delete_provider` | endpoint | Modified: delete-blocking with named references | backend/app/api/v1/system_one.py |
| `test_provider_connection` | endpoint | Modified: per-provider connection test | backend/app/api/v1/system_one.py |
| `get_status` | endpoint | Modified: multi-provider status | backend/app/api/v1/system_one.py |
| New model availability endpoints | endpoints (**new**) | Hierarchy listing, model/vendor disable toggles, enabled-models listing | backend/app/api/v1/system_one.py |
| `DecisionModelHierarchyEntry` / `DecisionEnabledModelRead` / `DecisionModelAvailabilityUpdate` | schemas (**new**) | Catalogue API payloads | backend/app/schemas/system_one.py |
| `SystemOneProviderDuplicateError` / `SystemOneProviderInUseError` | exceptions (**new**) | Duplicate rejection / delete-blocking errors | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderValidationError` | exception (**new**, UAT) | `default_model` must belong to the catalogued/enabled models (write-only validation) | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService._seed_availability_rows` | method (**new**, UAT) | Seeds availability rows at create/sync/import (rows are the authoritative catalogue) | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.list_vendor_models` | method (**new**, UAT) | Discovers vendor models via the vendor model-listing endpoint (derived to `<origin>/v1/models`); decrypted key at call time only | backend/app/services/system_one/provider_config_service.py |
| `SystemOneProviderConfigService.import_vendor_models` | method (**new**, UAT) | Imports vendor model ids as enabled availability rows; keeps `default_model` valid | backend/app/services/system_one/provider_config_service.py |
| `list_vendor_models` (client) | function (**new**, UAT) | Vendor model discovery with bearer auth; URL derived to `<origin>/v1/models` via `derive_models_url` (full endpoint / `/v1` root / `/models` / bare host); parses TypeSafe `models[].name` (primary) + OpenAI `data[].id` (fallback); actionable errors, no key logging | backend/app/services/system_one/client.py |
| `list_provider_types` | endpoint (**new**, UAT) | GET /system-one/provider-types — serves the backend enum for the create dialog | backend/app/api/v1/system_one.py |
| `list_vendor_models` | endpoint (**new**, UAT) | GET /system-one/providers/{id}/vendor-models — discovered ids (502 on vendor failure) | backend/app/api/v1/system_one.py |
| `import_vendor_models` | endpoint (**new**, UAT) | POST /system-one/providers/{id}/import-models — import ids as availability rows | backend/app/api/v1/system_one.py |
| `VendorModelSyncResult` / `VendorModelImportRequest` / `SystemOneProviderTypeRead` | schemas (**new**, UAT) | Vendor-sync payloads + selectable vendor type DTO | backend/app/schemas/system_one.py |
| `SystemOneProviderConfigPage` (UAT updates) | component | Vendor-type select (locked on edit), default-model select over catalogue, "Sync models from vendor" (dialog); inline model catalogue drawer REMOVED; embedded guardrail section (collapsible, provider select + reused panel) | frontend/src/pages/system/SystemOneProviderConfigPage.tsx |
| `listSystemOneProviderTypes` / `listVendorModels` / `importVendorModels` | api client (**new**, UAT) | Typed clients for vendor-type + vendor-model sync/import endpoints | frontend/src/api/systemOneApi.ts |
| `DecisionToolsPage` (UAT update) | component | Responsive table: fixed layout, constrained columns, no-wrap + ellipsis tooltips, sticky actions column | frontend/src/pages/agents/DecisionToolsPage.tsx |
| Backend API tests (**new**, UAT) | tests | provider-types enum endpoint, vendor-models 200/502, import-models key-free, default_model 422 | backend/tests/api/v1/test_system_one_api.py |
| `list_decision_tools` | endpoint | Modified: list includes selected model | backend/app/api/v1/decision_tools.py |
| `create_decision_tool` | endpoint | Modified: accepts model reference | backend/app/api/v1/decision_tools.py |
| `update_decision_tool` | endpoint | Modified: accepts model reference | backend/app/api/v1/decision_tools.py |
| `get_decision_tool` | endpoint | Modified: detail includes selected model | backend/app/api/v1/decision_tools.py |
| `generate_decision_tool_draft` | endpoint | Draft generation endpoint (defaults updated) | backend/app/api/v1/decision_tools.py |
| `_require_system_one_configured` | function | Precondition check; updated for multi-provider | backend/app/api/v1/decision_tools.py |
| `list_decision_tools_internal` | endpoint | Modified: CH catalogue includes provider/model identity per tool | backend/app/api/v1/internal/system_tools.py |
| `execute_decision_tool_internal` | endpoint | Modified: blocked outcomes + provider/model identity in response; signed-header tenant scoping unchanged | backend/app/api/v1/internal/system_tools.py |
| `DecisionToolExecuteRequest` | schema | Internal execute request schema | backend/app/api/v1/internal/system_tools.py |
| `DecisionToolInfo` | schema | Internal catalogue entry schema; gains model identity fields | backend/app/api/v1/internal/system_tools.py |
| `DecisionToolListResponse` / `DecisionToolListRequest` | schema | Internal catalogue list schemas | backend/app/api/v1/internal/system_tools.py |
| Alembic migration | migration (**new**) | Idempotent schema + data migration (multi-provider shape, availability seeding, tool backfill, legacy-row dedup) | backend/alembic/versions/8144e472dce9_decision_model_providers_multi_vendor.py |
| Alembic migration (guardrail scoping) | migration (**new**, FIX-20261014-003000) | `model_guardrail_configurations`: `config_source` discriminator + nullable `decision_provider_id` FK → `system_one_provider_configs.id`; partial unique index (provider, model, period); idempotent, applied at head | backend/alembic/versions/b7d2e9f4a1c8_decision_guardrail_scoping.py |
| `ModelGuardrailConfiguration.config_source` / `.decision_provider_id` | columns (**new**, FIX-20261014-003000) | Scope discriminator: `model_config` (LLM) vs `decision_provider`; decision rows key via provider FK with `model_id` NULL | backend/app/db/models/model_guardrail_configuration.py |
| `ModelUsageGuardrailService.list_decision_configurations` | method (**new**, FIX-20261014-003000) | Decision-scope guardrail listing per provider | backend/app/services/control_center/model_usage_guardrail_service.py |
| `ModelUsageGuardrailService.create_decision_configuration` | method (**new**, FIX-20261014-003000) | Create decision guardrail on the SAME table (`config_source='decision_provider'`); (provider, model, period) uniqueness | backend/app/services/control_center/model_usage_guardrail_service.py |
| `ModelUsageGuardrailService.get_decision_configuration_scoped` | method (**new**, FIX-20261014-003000) | Tenant-contained decision-guardrail lookup; LLM rows and cross-tenant rows return None (→ 404) | backend/app/services/control_center/model_usage_guardrail_service.py |
| `ModelUsageGuardrailService.get_current_decision_posture` / `refresh_decision_posture_snapshots` | methods (**new**, FIX-20261014-003000) | Decision posture snapshots rolled up from persisted `DecisionExecutionResult` provider identity | backend/app/services/control_center/model_usage_guardrail_service.py |
| `DecisionModelCatalogueService.check_pre_call` | method | Decision pre-call guardrail check — reads ONLY `config_source='decision_provider'` rows; LLM guardrails untouched | backend/app/services/system_one/decision_model_availability_service.py |
| `list_decision_guardrails` / `create_decision_guardrail` / `update_decision_guardrail` / `delete_decision_guardrail` / `get_decision_guardrail_posture` | endpoints (**new**, FIX-20261014-003000) | Decision-scoped guardrail CRUD + posture under `/system-one`, gated by `system::system_one` read/manage (existing resource type — no new registration needed) | backend/app/api/v1/system_one.py |
| `DecisionGuardrailCreate` / `DecisionGuardrailUpdate` / `DecisionGuardrailRead` | schemas (**new**, FIX-20261014-003000) | Decision guardrail payloads (mirror the LLM shapes; `decision_provider_id` keyed, `model_id` nullable) | backend/app/schemas/system_one.py |
| `SystemOneProviderConfigPage` | component | Renamed/relabeled "Decision Model Providers"; reworked to multi-provider table CRUD; inline model catalogue drawer removed; embedded decision guardrail section added | frontend/src/pages/system/SystemOneProviderConfigPage.tsx |
| `VendorModelGuardrailPanel` | component (**extended**, FIX-20261014-003000) | Parameterized by optional `decisionProviderId`: in decision scope feeds from the decision hierarchy + guardrail endpoints, hides availability switches (managed on the providers page/dialog), routes guardrail mutations to `/system-one/guardrails`; LLM scope unchanged | frontend/src/components/agents/VendorModelGuardrailPanel.tsx |
| `AddGuardrailForm` | component (**extended**, FIX-20261014-003000) | Optional `decisionProviderId` routes create/update to the decision guardrail endpoints; LLM behaviour unchanged | frontend/src/components/agents/AddGuardrailForm.tsx |
| `useDecisionGuardrails` / `useDecisionGuardrailPosture` / `useCreateDecisionGuardrail` / `useUpdateDecisionGuardrail` / `useDeleteDecisionGuardrail` | hooks (**new**, FIX-20261014-003000) | Decision-scoped guardrail queries/mutations with `system-one` React Query invalidation | frontend/src/hooks/useDecisionGuardrails.ts |
| `listDecisionGuardrails` / `createDecisionGuardrail` / `updateDecisionGuardrail` / `deleteDecisionGuardrail` / `getDecisionGuardrailPosture` | api client (**new**, FIX-20261014-003000) | Typed clients for the decision guardrail endpoints | frontend/src/api/systemOneApi.ts |
| `systemOneApi` | api client | Reworked to multi-provider endpoints + model availability calls | frontend/src/api/systemOneApi.ts |
| `useModelAvailability` | hook | Toggle/mutation pattern reference for the decision model toggles (toggles implemented as inline React Query mutations in the page, no shared hook extracted) | frontend/src/hooks/useModelAvailability.ts |
| `useDialogErrorHandler` | hook | Dialog error handling standard for provider CRUD dialogs | frontend/src/hooks/useDialogErrorHandler.ts |
| `AppShell` | component | Nav entry renamed to Decision Model Providers | frontend/src/app/AppShell.tsx |
| `AppRouter` | component | Route path/labels updated (internal path may remain) | frontend/src/app/AppRouter.tsx |
| i18n `systemOne.*` strings | resource | All user-facing strings renamed to "Decision Model Providers", via `t()` | frontend/src/i18n/locales/en.json |
| `DecisionToolForm` | component | Gains enabled-decision-model selector (fed by GET /decision-tools/enabled-models, enabled models only), validated on submit; never silently empty — placeholder option when unselected, stored-but-disabled selection rendered as a disabled "unavailable — re-select" option (FIX-20261014-004500) | frontend/src/components/decisionTools/DecisionToolForm.tsx |
| `DecisionToolsPage` | component | List/detail shows selected provider/model chip (without the internal `decision:` prefix) | frontend/src/pages/agents/DecisionToolsPage.tsx |
| `DecisionResultView` | component | Result view shows which provider/model produced the decision | frontend/src/components/results/DecisionResultView.tsx |
| `decisionToolsApi` | api client | Extended for model reference + enabled-models listing | frontend/src/api/decisionToolsApi.ts |
| Backend unit tests | tests | Engine model resolution, cascade semantics, credential non-exposure, duplicate/delete-blocking | backend/tests/unit/test_decision_engine.py, backend/tests/unit/test_system_one_client.py |
| Backend integration tests | tests | Provider CRUD, availability toggles, schema verification, guardrail/budget blocking, migration compat | backend/tests/integration/test_system_one_decision_tools.py, backend/tests/integration/test_decision_tool_full_journey.py, backend/tests/integration/test_decision_providers_crud.py (new), backend/tests/integration/test_decision_model_availability.py (new), backend/tests/integration/test_decision_providers_schema.py (new) |
| Decision guardrail integration tests | tests (**new**, FIX-20261014-003000) | Decision guardrail CRUD round-trip, 409 conflict, 404 unknown provider, LLM-row scope isolation (both directions), posture rollup from decision executions, breached-decision-only pre-call blocking | backend/tests/integration/test_decision_guardrails.py (new) |
| Frontend tests | tests | Settings page CRUD + terminology, form selector, page display | frontend/src/__tests__/SystemOneProviderConfigPage.test.tsx, frontend/src/__tests__/DecisionToolForm.test.tsx, frontend/src/__tests__/DecisionToolsPage.test.tsx, frontend/src/__tests__/DecisionModelProvidersPage.test.tsx (new) |
| E2E tests | tests | Full lifecycle + real-backend provider creation | e2e/tests/system-one-decision-tools.spec.ts, e2e/tests/decision-model-providers-real-backend.spec.ts (new) |
