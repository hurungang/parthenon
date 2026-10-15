# Module: decision-tools — Tech Spec

## Overview

Decision tools are interactive, tenant-scoped tools derived from Agent Data Types: when an agent needs structured human input mid-run, the decision toolset renders the data type's typed fields as questions, gates on answer confidence, and persists the resulting structured output. Decision tools are exposed to agents as virtual tool ids (`resolve_virtual_tool_id`) alongside system tools and MCP tools, and follow the same `server____tool`-style routing through the Communication Hub to Control Center (internal wire format `decision____<tool>` unchanged).

The subsystem is vendor-abstracted through the **Decision Model Providers** catalogue (multi-vendor generalisation of the former single System One Provider): administrators register any number of decision vendors with encrypted, write-only credentials, manage a per-vendor model catalogue with individual enable/disable and vendor-level cascade (mirroring the LLM Model Configurations availability pattern), and each decision tool explicitly references one enabled decision model instead of the legacy free-text `provider_model`. `SystemOneClient` remains the client protocol, with `TypeSafeJevClient` as the built-in implementation and `get_system_one_client` generalised to instantiate a client per provider from its own config (credential decrypted at call time only, inside Control Center).

The decision execution path resolves the tool's selected model to a provider + model pair, applies the same pre-call guardrail and budget/spend checks used for regular agent model usage before any vendor call, and records usage plus provider/model identity on the persisted execution result for audit (not yet rolled up into the AgentJob-derived `ModelUsagePosture` reporting — known limitation). Internal identifiers (table names, `system_one` module paths, MCP wire format) remain unchanged; the rename to "Decision Model Providers" is user-facing only. Agent Runtime and Communication Hub are untouched structurally — CH keeps forwarding decision calls to Control Center internal endpoints via `internal_httpx_client` with signed tenant headers; agents never receive credentials or provider configuration.

Decision guardrails reuse the SAME `model_guardrail_configurations` + `model_usage_postures` tables as LLM guardrails, discriminated by `config_source` (`model_config` vs `decision_provider`) with a nullable `decision_provider_id` FK; decision rows keep `model_id` NULL. The LLM listing filters to `model_config` and the decision pre-call check (`check_pre_call`) filters to `decision_provider` — the two scopes never mix in either direction.

Strict tenant isolation (strict-tenant-isolation change): decision tools resolve **strictly within the caller's tenant** — a tool named `tool_a` in tenant A is never resolvable from tenant B; input/output data-type resolution is exact tenant match (no `IS NULL OR own` fallback); readiness gating and question derivation operate on the bound tenant's data types only.

## Key Components

| Component | Description |
|-----------|-------------|
| `SystemOneProviderConfigService` | Control Center service: multi-provider CRUD per tenant, duplicate display-name-per-vendor rejection, delete blocked with named blocking references, write-only credentials (`to_read` never exposes them), per-provider `test_connection`, vendor model discovery/import, availability seeding; `get_active_provider` retained as backward-compat wrapper |
| `DecisionModelCatalogueService` | Per-model enable/disable per provider mirroring `ModelAvailabilityService`: `set_vendor_disabled` (cascade preserving manual disables), `set_model_disabled`, `list_hierarchy`, `list_enabled_models`, `resolve_selection`, decision-scoped `check_pre_call` guardrail check, `usage_identity` |
| `DecisionToolService` | Decision tool CRUD, tenant-contained data-type resolution (`_resolve_data_types`), question derivation from output types, virtual tool id resolution, readiness validation, selected-model reference validation |
| `DecisionExecutionEngine` | Executes a decision flow: resolve the tool within the caller's tenant → resolve the selected enabled model → guardrail/budget pre-call checks → build state → normalize answers → confidence gate (`compute_confidence_gate`, `derive_effective_confidence`) → vendor call → persist structured output with provider/model identity |
| `ModelUsageGuardrailService` | Budget/spend posture service reused for decision pre-call checks and metering; decision-scoped guardrail CRUD + posture on the shared tables |
| `SystemOneClient` (protocol) | Vendor client contract; `SystemOneClientError` on vendor failure; `list_vendor_models` discovery with `derive_models_url` |
| Provider management API (`backend/app/api/v1/system_one.py`) | Multi-row `/system-one/providers` CRUD (409 duplicate/in-use), connection test, vendor-type/vendor-models/import endpoints, model availability toggles, decision-scoped guardrail CRUD + posture |
| `list_decision_tools_internal` / `execute_decision_tool_internal` | Internal endpoints in `backend/app/api/v1/internal/system_tools.py`; tenant-scoped, behind `require_internal_tenant_context`; expose per-tool provider/model identity and blocked (guardrail/budget) outcomes |
| Decision Model Providers settings page (`SystemOneProviderConfigPage`) | Multi-provider table with create/edit/delete dialogs (Dialog Error Handling Standard), enabled-models chip selection + vendor sync + default model in the editor dialog, embedded collapsible decision guardrail section reusing `VendorModelGuardrailPanel` |
| `route_tool_call` / `_route_to_decision_tool` (CH) | Communication Hub routing of decision tool calls to Control Center with the session's tenant binding |
| `ToolRegistryBridge._list_decision_tools` / `_call_decision_tool` (CH) | Per-tenant decision tool catalogue and tenant-contained dispatch for MCP-protocol clients |
| `get_agent_context` (CC internal) | Registers the caller's tenant decision toolset in the agent context handed to Agent Runtime |

## Code Reference Map

### Data models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemOneProviderType` | enum | Vendor type enum | `backend/app/db/models/system_one_provider_config.py` |
| `SystemOneProviderConfig` | model | Provider row; multi-row per tenant, vendor-level `enabled`, `default_model` | `backend/app/db/models/system_one_provider_config.py` |
| `DecisionModelAvailability` | model | Per-model enable/disable record mirroring `ModelAvailability` | `backend/app/db/models/decision_model_availability.py` |
| `ModelAvailability` | model | LLM availability entity (pattern source) | `backend/app/db/models/model_availability.py` |
| `ModelAvailabilityDisabledReason` | enum | `manual` / `vendor_cascaded` disable reasons (pattern source) | `backend/app/db/models/model_availability.py` |
| `DecisionTool` | model | Decision tool; FK to selected availability row; legacy `provider_model` retired | `backend/app/db/models/decision_tools.py` |
| `DecisionToolStatus` | enum | Tool status (draft/active/disabled) | `backend/app/db/models/decision_tools.py` |
| models `__init__` exports | module | Exports the availability model | `backend/app/db/models/__init__.py` |
| `GuardrailThresholdEvent` | model | Guardrail breach persistence reused for decision evaluations | `backend/app/db/models/guardrail_threshold_event.py` |
| `ModelGuardrailConfiguration.config_source` / `.decision_provider_id` | columns | Scope discriminator: `model_config` (LLM) vs `decision_provider`; decision rows key via provider FK with `model_id` NULL | `backend/app/db/models/model_guardrail_configuration.py` |
| `DecisionExecutionResult` | model | Persists each decision execution; `answers.provider` carries per-question provider/model identity for audit | `backend/app/db/models/results.py` |

### Services (Control Center)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemOneProviderError` | exception | Provider service error base | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderDuplicateError` / `SystemOneProviderInUseError` | exceptions | Duplicate rejection / delete-blocking errors (mapped to HTTP 409) | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderValidationError` | exception | `default_model` must belong to the catalogued/enabled models (write-only validation) | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService` | class | Multi-provider CRUD, duplicate rejection, delete-blocking, credential masking | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService.create` / `.update` / `.delete` / `.list_all` | methods | Tenant-scoped provider lifecycle; credential placeholder semantics on update; referential-integrity delete blocking | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService.get_active_provider` | method | Backward-compat wrapper over multi-provider lookup | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService.to_read` | method | Read serialization; never exposes credentials | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService.test_connection` | method | Per-provider connection test (CC-only) | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService._seed_availability_rows` | method | Seeds availability rows at create/sync/import (rows are the authoritative catalogue) | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService.list_vendor_models` | method | Discovers vendor models via the vendor model-listing endpoint (derived to `<origin>/v1/models`); decrypted key at call time only | `backend/app/services/system_one/provider_config_service.py` |
| `SystemOneProviderConfigService.import_vendor_models` | method | Imports vendor model ids as enabled availability rows; keeps `default_model` valid | `backend/app/services/system_one/provider_config_service.py` |
| `_tenant_filter` | function | Tenant scoping helper for provider queries | `backend/app/services/system_one/provider_config_service.py` |
| `DecisionModelCatalogueService` | class | `set_vendor_disabled` cascade, `set_model_disabled`, `list_hierarchy`, `list_enabled_models`, `resolve_selection`, `check_pre_call`, `usage_identity`; mirrors availability service pattern | `backend/app/services/system_one/decision_model_availability_service.py` |
| `DecisionModelCatalogueService.check_pre_call` | method | Decision pre-call guardrail check — reads ONLY `config_source='decision_provider'` rows; LLM guardrails untouched | `backend/app/services/system_one/decision_model_availability_service.py` |
| `ModelAvailabilityService` (+ `.set_vendor_disabled` / `.set_model_disabled` / `.list_hierarchy`) | class/methods | LLM availability service; reference implementation for cascade/toggle semantics | `backend/app/services/control_center/model_availability_service.py` |
| `ModelUsageGuardrailService` | class | Budget/spend posture service reused for decision pre-call checks and metering | `backend/app/services/control_center/model_usage_guardrail_service.py` |
| `ModelUsageGuardrailService.get_current_posture` | method | Spend posture check applied before decision vendor calls | `backend/app/services/control_center/model_usage_guardrail_service.py` |
| `ModelUsageGuardrailService.list_decision_configurations` / `.create_decision_configuration` | methods | Decision-scope guardrail listing/creation on the SAME table (`config_source='decision_provider'`); (provider, model, period) uniqueness | `backend/app/services/control_center/model_usage_guardrail_service.py` |
| `ModelUsageGuardrailService.get_decision_configuration_scoped` | method | Tenant-contained decision-guardrail lookup; LLM rows and cross-tenant rows return None (→ 404) | `backend/app/services/control_center/model_usage_guardrail_service.py` |
| `ModelUsageGuardrailService.get_current_decision_posture` / `.refresh_decision_posture_snapshots` | methods | Decision posture snapshots rolled up from persisted `DecisionExecutionResult` provider identity | `backend/app/services/control_center/model_usage_guardrail_service.py` |
| `GuardrailStop` / `GuardrailStopReason` | exception/class | Guardrail breach semantics shared with regular model usage | `backend/app/services/agents/guardrails.py` |
| `SystemOneClient` | protocol | Vendor client contract | `backend/app/services/system_one/client.py` |
| `TypeSafeJevClient` | class | Built-in vendor implementation | `backend/app/services/system_one/client.py` |
| `get_system_one_client` | function | Client registry (`_SYSTEM_ONE_CLIENTS`); generalised to instantiate per-provider from its own config | `backend/app/services/system_one/client.py` |
| `build_questions_payload` | function | Questions payload for vendor evaluate call | `backend/app/services/system_one/client.py` |
| `list_vendor_models` (client) | function | Vendor model discovery with bearer auth; URL derived to `<origin>/v1/models` via `derive_models_url` (full endpoint / `/v1` root / `/models` / bare host); parses TypeSafe `models[].name` (primary) + OpenAI `data[].id` (fallback); actionable errors, no key logging | `backend/app/services/system_one/client.py` |
| `derive_models_url` | function | Derives the vendor model-listing URL so it always ends with `/v1/models` (strips endpoint segments like `/v1/systemone`) | `backend/app/services/system_one/client.py` |
| `SystemOneClientError` | exception | Vendor client errors (timeouts, HTTP failures) | `backend/app/services/system_one/client.py` |
| `DecisionToolService` | class | Decision tool CRUD; tenant-contained data-type resolution; validates selected availability row exists and is enabled | `backend/app/services/system_one/decision_tool_service.py` |
| `DecisionToolService.create` / `.update` | methods | Tool create/update with model reference validation | `backend/app/services/system_one/decision_tool_service.py` |
| `_resolve_data_types` | method | Input/output data-type resolution; exact tenant match (NULL fallback removed) | `backend/app/services/system_one/decision_tool_service.py` |
| `resolve_virtual_tool_id` | function | Virtual decision-tool id resolution; tenant-scoped | `backend/app/services/system_one/decision_tool_service.py` |
| `decision_tool_virtual_tool_id` | function | Virtual tool ID mapping (wire format unchanged) | `backend/app/services/system_one/decision_tool_service.py` |
| `derive_questions_from_output_type` | function | Derives typed questions from a data type's fields | `backend/app/services/system_one/decision_tool_service.py` |
| `_derive_question_specs` / `_coerce_question_payloads` | functions | Question spec derivation and payload coercion | `backend/app/services/system_one/decision_tool_service.py` |
| `_validate_readiness` | function | Readiness gate for a decision tool's data types | `backend/app/services/system_one/decision_tool_service.py` |
| `is_decision_tool_ready` | function | Readiness check | `backend/app/services/system_one/decision_tool_service.py` |
| `DecisionToolValidationError` | exception | Validation errors incl. unknown/disabled model selection | `backend/app/services/system_one/decision_tool_service.py` |
| `generate_decision_draft` | function | Authoring draft generation | `backend/app/services/system_one/decision_authoring_service.py` |
| `DecisionExecutionEngine` | class | Decision evaluation orchestration; resolves selected enabled model, applies guardrail/budget pre-call checks, records provider/model identity | `backend/app/services/system_one/decision_engine.py` |
| `DecisionExecutionEngine.execute` | method | Evaluation entry point (model resolution + vendor call + metering) | `backend/app/services/system_one/decision_engine.py` |
| `DecisionExecutionEngine.resolve_tool` | method | Resolves a decision tool by name WITHIN the caller's tenant; cross-tenant names never resolve | `backend/app/services/system_one/decision_engine.py` |
| `DecisionExecutionEngine.resolve_model_selection` | method | Resolves the tool's selected availability row → provider + model (legacy fallback: enabled provider + `provider_model`) | `backend/app/services/system_one/decision_engine.py` |
| `DecisionExecutionEngine.build_state` | method | Execution state capture | `backend/app/services/system_one/decision_engine.py` |
| `compute_confidence_gate` / `derive_effective_confidence` | functions | Answer confidence gating | `backend/app/services/system_one/decision_engine.py` |
| `DecisionExecutionError` | exception | Actionable errors for disabled/unavailable model selections and flow failure | `backend/app/services/system_one/decision_engine.py` |

### API endpoints (Control Center)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `list_providers` / `create_provider` / `update_provider` / `delete_provider` | endpoints | Multi-provider CRUD; PATCH partial update; structured duplicate (409) and delete-blocking errors with named references | `backend/app/api/v1/system_one.py` |
| `test_provider_connection` | endpoint | Per-provider connection test | `backend/app/api/v1/system_one.py` |
| `get_status` | endpoint | Multi-provider status | `backend/app/api/v1/system_one.py` |
| `list_provider_types` | endpoint | GET /system-one/provider-types — serves the backend enum for the create dialog | `backend/app/api/v1/system_one.py` |
| Model availability endpoints | endpoints | Hierarchy listing (`/system-one/models`), model/vendor disable toggles, enabled-models listing (`/system-one/enabled-models`) | `backend/app/api/v1/system_one.py` |
| `list_vendor_models` | endpoint | GET /system-one/providers/{id}/vendor-models — discovered ids (502 on vendor failure) | `backend/app/api/v1/system_one.py` |
| `import_vendor_models` | endpoint | POST /system-one/providers/{id}/import-models — import ids as availability rows | `backend/app/api/v1/system_one.py` |
| `list_decision_guardrails` / `create_decision_guardrail` / `update_decision_guardrail` / `delete_decision_guardrail` / `get_decision_guardrail_posture` | endpoints | Decision-scoped guardrail CRUD + posture under `/system-one`, gated by `system::system_one` read/manage (existing resource type) | `backend/app/api/v1/system_one.py` |
| `list_decision_tools` / `create_decision_tool` / `update_decision_tool` / `get_decision_tool` | endpoints | Decision tool CRUD; accepts/returns the model reference; enabled-models listing for the authoring selector | `backend/app/api/v1/decision_tools.py` |
| `generate_decision_tool_draft` | endpoint | Draft generation endpoint | `backend/app/api/v1/decision_tools.py` |
| `_require_system_one_configured` | function | Precondition check for multi-provider configuration | `backend/app/api/v1/decision_tools.py` |
| `_resolve_type` (decision draft data-type resolution) | closure | Exact tenant match for decision draft data types | `backend/app/api/v1/decision_tools.py` |
| `list_decision_tools_internal` / `execute_decision_tool_internal` | endpoints | Internal decision tool catalogue/execution; tenant-scoped via signed tenant context; catalogue includes per-tool provider/model identity; execute returns provider/model identity and structured blocked (guardrail/budget) outcomes | `backend/app/api/v1/internal/system_tools.py` |
| `DecisionToolInfo` / `DecisionToolListResponse` / `DecisionToolListRequest` / `DecisionToolExecuteRequest` | schemas | Internal catalogue/execute schemas; catalogue entries carry model identity fields | `backend/app/api/v1/internal/system_tools.py` |
| `DecisionModelHierarchyEntry` / `DecisionEnabledModelRead` / `DecisionModelAvailabilityUpdate` | schemas | Catalogue API payloads | `backend/app/schemas/system_one.py` |
| `VendorModelSyncResult` / `VendorModelImportRequest` / `SystemOneProviderTypeRead` | schemas | Vendor-sync payloads + selectable vendor type DTO | `backend/app/schemas/system_one.py` |
| `DecisionGuardrailCreate` / `DecisionGuardrailUpdate` / `DecisionGuardrailRead` | schemas | Decision guardrail payloads (mirror the LLM shapes; `decision_provider_id` keyed, `model_id` nullable) | `backend/app/schemas/system_one.py` |
| `require_internal_tenant_context` | function | Shared dependency enforcing the signed tenant context on internal data-plane routers | `backend/app/api/deps.py` |
| `get_agent_context` | endpoint | Internal agent-context fetch; registers the tenant decision toolset for the run | `backend/app/api/v1/internal/agent_data.py` |
| `route_tool_call` / `_route_to_decision_tool` | endpoint + function | CH routing of decision tool calls to CC with the session's tenant binding | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `ToolRegistryBridge._list_decision_tools` / `._call_decision_tool` | methods | Per-tenant decision tool catalogue + tenant-contained invocation for MCP clients | `backend/app/communication_hub/mcp/tool_registry_bridge.py` |

### Migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| Multi-vendor migration | migration | Idempotent schema + data migration (multi-provider shape, availability seeding, tool backfill, legacy-row dedup) | `backend/alembic/versions/8144e472dce9_decision_model_providers_multi_vendor.py` |
| Guardrail scoping migration | migration | `model_guardrail_configurations`: `config_source` discriminator + nullable `decision_provider_id` FK; partial unique index (provider, model, period); idempotent | `backend/alembic/versions/b7d2e9f4a1c8_decision_guardrail_scoping.py` |

### Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemOneProviderConfigPage` | component | "Decision Model Providers" settings page: multi-provider table CRUD (vendor chip, endpoint, credentials indicator, enabled flag), create/edit dialog with enabled-models chip select (MUI Autocomplete `multiple` + `freeSolo`) + vendor sync + default model gated on selection; vendor-type select locked on edit; NO inline model catalogue drawer; embedded collapsible decision guardrail section (provider select + reused panel); all text via `t()` | `frontend/src/pages/system/SystemOneProviderConfigPage.tsx` |
| `systemOneApi` | api client | Multi-provider endpoints, model availability calls, provider-types/vendor-models/import clients (`listSystemOneProviderTypes` / `listVendorModels` / `importVendorModels`), decision guardrail clients (`listDecisionGuardrails` / `createDecisionGuardrail` / `updateDecisionGuardrail` / `deleteDecisionGuardrails` / `getDecisionGuardrailPosture`) | `frontend/src/api/systemOneApi.ts` |
| `VendorModelGuardrailPanel` | component | Guardrail panel parameterized by optional `decisionProviderId`: decision scope feeds from decision hierarchy + guardrail endpoints, hides availability switches, routes mutations to `/system-one/guardrails`; LLM scope unchanged | `frontend/src/components/agents/VendorModelGuardrailPanel.tsx` |
| `AddGuardrailForm` | component | Optional `decisionProviderId` routes create/update to the decision guardrail endpoints; LLM behaviour unchanged | `frontend/src/components/agents/AddGuardrailForm.tsx` |
| `useDecisionGuardrails` (incl. `useDecisionGuardrailPosture` / `useCreateDecisionGuardrail` / `useUpdateDecisionGuardrail` / `useDeleteDecisionGuardrail`) | hooks | Decision-scoped guardrail queries/mutations with `system-one` React Query invalidation | `frontend/src/hooks/useDecisionGuardrails.ts` |
| `useModelAvailability` | hook | Toggle/mutation pattern reference (toggles implemented as inline React Query mutations in the page); `enabled` flag keeps decision surfaces off LLM endpoints | `frontend/src/hooks/useModelAvailability.ts` |
| `useDialogErrorHandler` | hook | Dialog error handling standard for provider CRUD dialogs | `frontend/src/hooks/useDialogErrorHandler.ts` |
| `AppShell` | component | Nav entry renamed to Decision Model Providers | `frontend/src/app/AppShell.tsx` |
| `AppRouter` | component | Route path/labels updated (internal path may remain) | `frontend/src/app/AppRouter.tsx` |
| i18n `systemOne.*` strings | resource | All user-facing strings renamed to "Decision Model Providers", via `t()` | `frontend/src/i18n/locales/en.json` |
| `DecisionToolForm` | component | Enabled-decision-model selector (fed by GET /decision-tools/enabled-models, enabled models only), validated on submit; never silently empty — placeholder option when unselected, stored-but-disabled selection rendered as a disabled "unavailable — re-select" option | `frontend/src/components/decisionTools/DecisionToolForm.tsx` |
| `DecisionToolsPage` | component | Responsive table (fixed layout, constrained columns, ellipsis tooltips, sticky actions); list/detail shows selected provider/model chip (without the internal `decision:` prefix) | `frontend/src/pages/agents/DecisionToolsPage.tsx` |
| `DecisionResultView` | component | Result view shows which provider/model produced the decision | `frontend/src/components/results/DecisionResultView.tsx` |
| `decisionToolsApi` | api client | Extended for model reference + enabled-models listing | `frontend/src/api/decisionToolsApi.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| Backend unit tests | tests | Engine model resolution, cascade semantics, credential non-exposure, duplicate/delete-blocking, client URL derivation/parsing | `backend/tests/unit/test_decision_engine.py`, `backend/tests/unit/test_system_one_client.py` |
| Backend API tests | tests | Provider-types enum endpoint, vendor-models 200/502, import-models key-free, default_model 422, vendor-model URL derivation | `backend/tests/api/v1/test_system_one_api.py`, `backend/tests/api/v1/test_system_one_vendor_models.py` |
| Backend integration tests | tests | Provider CRUD, availability toggles, schema verification, guardrail/budget blocking, migration compat, full journey | `backend/tests/integration/test_system_one_decision_tools.py`, `backend/tests/integration/test_decision_tool_full_journey.py`, `backend/tests/integration/test_decision_providers_crud.py`, `backend/tests/integration/test_decision_model_availability.py`, `backend/tests/integration/test_decision_providers_schema.py` |
| Decision guardrail integration tests | tests | Decision guardrail CRUD round-trip, 409 conflict, 404 unknown provider, LLM-row scope isolation (both directions), posture rollup, breached-decision-only pre-call blocking | `backend/tests/integration/test_decision_guardrails.py` |
| Frontend tests | tests | Settings page CRUD + terminology, form selector, page display | `frontend/src/__tests__/SystemOneProviderConfigPage.test.tsx`, `frontend/src/__tests__/DecisionToolForm.test.tsx`, `frontend/src/__tests__/DecisionToolsPage.test.tsx`, `frontend/src/__tests__/DecisionModelProvidersPage.test.tsx` |
| E2E tests | tests | Full lifecycle + real-backend provider creation | `e2e/tests/system-one-decision-tools.spec.ts`, `e2e/tests/decision-model-providers-real-backend.spec.ts` |

## Related Modules

- [multi-tenancy](../multi-tenancy/tech-spec.md) — strict tenant isolation model and signed header contract
- [data-types](../data-types/tech-spec.md) — the Agent Data Type Registry decision tools derive from
- [agents](../agents/tech-spec.md) — LLM Model Configurations availability/guardrail patterns mirrored by Decision Model Providers
- [comm-hub](../comm-hub/tech-spec.md) — tool routing and MCP protocol server
- [agent-runtime](../agent-runtime/tech-spec.md) — tenant-bound execution and downstream call forwarding
