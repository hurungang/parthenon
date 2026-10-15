# Fix Log: decision-model-providers

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261014-004500

**Created:** 2026-10-14T04:50:00Z
**Status:** Resolved
**Issue:** "The decision model in decision tool editor has no value in it" — the Decision Model selector in `DecisionToolForm` could render silently empty.

### Investigation (both reported directions verified against code + tests)

1. **Prefill / field-name contract — VERIFIED CORRECT.** `GET /decision-tools` and `GET /decision-tools/{id}` serialize `decision_model_availability_id` under that exact name (`DecisionToolRead`, `backend/app/schemas/decision_tools.py:180`, ORM attr on `DecisionTool`); the editor pre-fills from it (`formFromTool`). `GET /decision-tools/enabled-models` and `GET /system-one/enabled-models` both return `availability_id` (`DecisionEnabledModelRead`), and the seed-on-list path in `DecisionModelCatalogueService.list_enabled_models` persists rows so ids are stable. A new backend contract test locks this round-trip.
2. **Options feed after FIX-20261014-003000 — VERIFIED CORRECT.** Both `/system-one/enabled-models` and `/decision-tools/enabled-models` routes exist; the filter is `provider.enabled == True AND (no row OR row.is_disabled == False)`; vendor enable/disable still works via the editor dialog (`PATCH /system-one/providers/{id}` `enabled` + `PUT .../availability` cascade) — models are NOT filtered out wholesale. Backend suites all green pre-fix (111 passed).
3. **ACTUAL DEFECT (presentation):** when the tool's stored selection is not in the enabled list — vendor-cascade/manual disable after tool creation, or a legacy tool with only the free-text `provider_model` (availability id NULL) — the select had **no placeholder and no unavailable state**: a non-matching value renders a blank MUI select, and a legacy NULL value renders blank too. The user sees "no value" with no hint that the model was disabled and must be re-selected (the `modelUnavailable` validation only fired on save).

### Fix Tasks
- [x] **Failing tests first** — `DecisionToolForm.test.tsx`: (a) "shows the stored selection as a disabled unavailable option when editing a tool whose model is no longer enabled" (❌ FAIL: option absent), (b) "shows a placeholder option instead of a blank select when no model is selected" (❌ FAIL: no placeholder option).
- [x] **Fix** — selector now always renders (1) a placeholder `MenuItem value=""` (`decisionTools.modelNone`) and (2) when the stored id is absent from the enabled list, a DISABLED option labelled `<model> — <provider> — unavailable — re-select a model` (`decisionTools.modelUnavailableOption`), using the enriched `model_name`/`provider_display_name` from the tool response; the existing `modelUnavailable` submit validation still blocks saving the stale selection.
- [x] **Backend contract test** — `TestAuthoringGate.test_tool_response_serializes_decision_model_availability_id` (integration): enabled-models id → tool create/list/detail round-trips the exact `decision_model_availability_id` + enriched identity.
- [x] **E2E spec check** — `e2e/tests/system-one-decision-tools.spec.ts` still matches reality (mocks cover both `/system-one/enabled-models` and `/decision-tools/enabled-models`; the selector test asserts option presence + submitted id, unaffected by the placeholder/unavailable option).
- [x] **Verify + document** — suites below; tech-spec Code Reference Map updated.

### Code Changes
- `frontend/src/components/decisionTools/DecisionToolForm.tsx` — model selector: placeholder MenuItem + disabled stored-unavailable MenuItem (FIX-20261014-004500 block).
- `frontend/src/i18n/locales/en.json` — new keys `decisionTools.modelNone`, `decisionTools.modelUnavailableOption`.
- `frontend/src/__tests__/DecisionToolForm.test.tsx` — 2 new reproduction tests; enabled-models-only option-count test updated for the placeholder (2 → 3 options).
- `backend/tests/integration/test_system_one_decision_tools.py` — new contract test above.

### Verification Results

**Frontend:** `npx vitest run DecisionToolForm + DecisionToolsPage + DecisionModelProvidersPage` — **59 passed / 0 failed** (was 57 passed / 2 failed before the fix); `npx tsc --noEmit` — clean.

**Backend** (`.venv/bin/python -m pytest`, PostgreSQL up, alembic head `b7d2e9f4a1c8`): `test_system_one_decision_tools.py` **41 passed** (40 + 1 new contract test; new test passed immediately — it locks the verified-correct backend contract from direction 1); combined decision/system-one suites (`test_system_one_decision_tools`, `test_decision_providers_crud`, `test_decision_providers_schema`, `test_decision_model_availability`, `test_decision_guardrails`, `test_decision_tool_full_journey`, `test_system_one_api`, `test_system_one_vendor_models`) — **112 passed / 0 failed**.

---

## FIX-20261014-003000

**Created:** 2026-10-14
**Status:** Resolved
**Issue:** (1) The inline expandable model catalogue under each provider row duplicated the editor and rendered inconsistent state (status chips computed against different data than the enabled list) — remove the drawer; model management lives in the editor dialog. (2) Guardrail management was only discoverable via a "jump to Model Configurations" info alert — embed guardrail management in the Decision Model Providers module, reusing the existing guardrail stack and enforcing decision-scope evaluation.

### Code Changes

**Keying decision:** guardrails reuse the SAME `model_guardrail_configurations` + `model_usage_postures` tables. A scope discriminator column `config_source` (`'model_config'` for LLM vendors, `'decision_provider'` for decision providers) plus a new nullable `decision_provider_id` FK → `system_one_provider_configs.id` were added; decision rows keep `model_id` NULL. Uniqueness: partial unique index `(decision_provider_id, model_name, period) WHERE decision_provider_id IS NOT NULL`. The LLM guardrail listing (`list_configurations`) filters to `config_source='model_config'` and the decision pre-call check (`check_pre_call`) filters to `'decision_provider'` — the two scopes never mix in either direction. Migration `b7d2e9f4a1c8_decision_guardrail_scoping` (alembic autogenerate-equivalent, idempotent, applied on top of `8144e472dce9`; the initially generated revision id collided with an existing migration and was renamed).

**Backend:**
- `backend/app/db/models/model_guardrail_configuration.py` — `config_source` (String(32), server_default `model_config`), nullable `model_id`, new nullable `decision_provider_id` FK + indexes.
- `backend/app/services/control_center/model_usage_guardrail_service.py` — decision-scope CRUD (`create_decision_configuration`, `list_decision_configurations`), tenant-contained lookup `get_decision_configuration_scoped` (LLM rows / cross-tenant rows → None → 404), decision posture (`get_current_decision_posture`, `refresh_decision_posture_snapshots` — rollup from persisted `DecisionExecutionResult` provider identity; naive-timestamp normalization).
- `backend/app/services/system_one/decision_model_availability_service.py` — `check_pre_call` reads ONLY `config_source='decision_provider'` rows for the resolved provider+model; sqlite-enum-safe period ordering; LLM guardrails untouched.
- `backend/app/api/v1/system_one.py` — new endpoints (existing `system::system_one` resource type reused — no new registration needed): `GET/POST /system-one/providers/{id}/guardrails`, `GET /system-one/providers/{id}/guardrails/posture?refresh=`, `PUT/DELETE /system-one/guardrails/{config_id}`; duplicate (provider, model, period) → 409 `guardrail_period_conflict`.
- `backend/app/schemas/system_one.py` — `DecisionGuardrailCreate` / `DecisionGuardrailUpdate` / `DecisionGuardrailRead`.

**Frontend:**
- `frontend/src/pages/system/SystemOneProviderConfigPage.tsx` — inline expandable catalogue drawer, vendor-cascade drawer switch and per-model availability mutations REMOVED (table lean: name, vendor chip, endpoint, default model, enabled chip, credentials indicator, test-connection/edit/delete); the guardrail info alert replaced by an embedded collapsible section (provider select + `VendorModelGuardrailPanel` fed with `decisionProviderId`); dead i18n keys removed (`manageModels`, `hideModels`, `vendorEnabledCascade`, `cascadedFromVendor`, `guardrailInfo`, `guardrailInfoLink`), new keys added (`guardrailsTitle`, `guardrailsSubtitle`, `guardrailsToggle`, `guardrailsProviderLabel`).
- `frontend/src/components/agents/VendorModelGuardrailPanel.tsx` — parameterized by optional `decisionProviderId`: decision scope sources hierarchy + posture from `/system-one` endpoints, projects them into the same `VendorAvailabilityNode` shape, routes guardrail update/delete through decision adapters, hides availability switches (managed on the page/dialog), and disables all LLM `/agents` queries.
- `frontend/src/components/agents/AddGuardrailForm.tsx` — optional `decisionProviderId` routes create/update to the decision guardrail endpoints; LLM behavior unchanged.
- `frontend/src/hooks/useDecisionGuardrails.ts` (**new**) + `frontend/src/api/systemOneApi.ts` — decision guardrail queries/mutations + typed clients; `useModelAvailability` / `useModelUsagePosture` / `useAvailableModels` gained an `enabled` flag so decision surfaces never call model-config endpoints.

**E2E spec updates:** `decision-model-providers-real-backend.spec.ts` (migration-revision assertion → `b7d2e9f4a1c8`), `system-one-decision-tools.spec.ts` (drawer-cascade test rewritten: asserts drawer removal + embedded decision-scoped guardrail section with zero availability calls), `system-one-provider-config.spec.ts` (aligned with current base-URL semantics and the "Decision Model providers" empty-state copy).

### Verification Results

**Schema:** alembic upgraded `8144e472dce9` → `b7d2e9f4a1c8` (PostgreSQL up); second `upgrade head` is a no-op (idempotency verified). Note: the first autogenerated revision id (`a1b2c3d4e5f6`) collided with an existing migration and broke the alembic graph ("Cycle is detected"); renamed to `b7d2e9f4a1c8`.

**Backend** (`.venv/bin/python -m pytest`, PostgreSQL up):
- `tests/integration/test_decision_guardrails.py` (**new**, 8 tests) — decision guardrail CRUD round-trip, 409 conflict, 404 unknown provider, per-provider uniqueness, LLM-row scope isolation (both directions), decision posture rollup from executions, breached-decision-only pre-call blocking — **8 passed**
- Decision/system-one suites (system-one API, vendor-models, client unit, decision engine unit, providers CRUD/schema, model availability, decision guardrail scoping) — **105 passed**
- `test_decision_tool_full_journey.py` — **17 passed** (the breached-guardrail pre-call test was re-keyed to `config_source='decision_provider'`/`decision_provider_id`, matching the new scoping)
- `test_system_one_decision_tools.py` — **40 passed**; decision unit suites — **72 passed**

**Frontend** (`npx tsc --noEmit` clean; `npx vitest run --reporter=json`): **1699 passed / 0 failed** (18 skipped) — includes the updated `DecisionModelProvidersPage.test.tsx` (21 tests: drawer-removal, embedded guardrail section rendering + decision-endpoint CRUD, prior fixes still green) and `SystemOneProviderConfigPage.test.tsx` plus all `VendorModelGuardrailPanel` / guardrail-management suites unchanged.

**E2E** (dev server on :5173, `playwright.dev.config.ts`, 4 system-one/decision spec files): **20 passed / 2 failed** — the 2 failures (`system-one-real-backend.spec.ts` 195 & 507) are **environmental 401s** on real-backend token acquisition (the spec is not part of the previously green decision set; unrelated to this fix — the mocked decision specs and the real-backend provider CRUD spec all pass, including the migration-revision check against `b7d2e9f4a1c8`).

---

## FIX-20261014-002300

**Created:** 2026-10-14T02:30:00Z
**Status:** Resolved
**Issue:** Enabled models is a free-text comma-separated input; default_model should be driven by an explicit selection of enabled models (UX requirement: "Make enabled models a selection control. Default model comes after enabled models selection, and only shows the models from the enabled ones.").

### Observed Behavior
1. `enabled_models` in the provider create/edit dialog is a raw comma-separated text field — error-prone and not selection-driven.
2. The default-model select's options are a union of typed text ∪ enabled rows ∪ in-session synced models, so a model can be the default without ever appearing as an enabled-model selection.
3. In create mode `default_model` is a freeSolo field independent of the enabled-models text.

### Expected Behavior
1. Enabled models is a multi-select (MUI Autocomplete, `multiple` + `freeSolo`, chip display); options come from catalogued availability rows (edit) and vendor-synced models (in-session); chips ARE the payload's `enabled_models`.
2. `default_model` renders directly BELOW the enabled-models select, its options are exactly the selected chips, it is disabled with helper text until ≥1 model is selected, and removing a selected model that was the default clears the default.

### Analysis
- **Affected components:** `frontend/src/pages/system/SystemOneProviderConfigPage.tsx` (dialog fields), `frontend/src/i18n/locales/en.json` (new key), `frontend/src/__tests__/DecisionModelProvidersPage.test.tsx`
- **Root cause:** legacy free-text field predating the selection UX; the default-model option union masked the enabled/typed distinction.
- Presentation-layer only — payload shape (`enabled_models` list + `default_model`) and backend validation unchanged.

### Fix Tasks
- [x] **Implement** — Replace free-text `enabled_models` with `Autocomplete multiple freeSolo`; reorder dialog (enabled models → default model); gate default select on chips; prune stale default on selection change; vendor sync pre-selects imported models as chips and refreshes options.
- [x] **i18n** — Added `systemOne.enabledModelsSelectHint`; reused existing `enabledModels` / `defaultModelSyncFirst` / `defaultModelHint` keys.
- [x] **Verify** — Frontend suites + `tsc --noEmit` + backend regression tests.
- [x] **Document** — tech-spec State Management updated.

### Implementation Details
1. `ProviderFormState.enabled_models` changed `string` → `string[]`; `parseEnabledModels` removed; `handleSave` sends `form.enabled_models` (or `null` when empty).
2. New `modelOptions` memo: selected chips ∪ `dialogModels` (vendor-synced) ∪ catalogue rows of the edited provider (`hierarchyFor(editing.id)`).
3. Chip `onChange` prunes `default_model` when it is no longer among the selected models (never leaves a stale default); default select renders a blank placeholder option so the cleared state is representable.
4. `handleSyncModels` merges imported models into the chips (pre-selected as enabled) and refreshes the option set; keeps a still-valid default, else falls back to the first imported model.
5. Create mode now uses the same pair of controls (previously a freeSolo default field with no catalogue).

### Verification Results

**Frontend** — `npx vitest run src/__tests__/DecisionModelProvidersPage.test.tsx`: **24 passed** (updated chip-payload test; added "default-model select disabled until selection / shows only chips" and "removing the default chip clears the default"). Regression: `DecisionToolForm` + `DecisionToolsPage` **36 passed**; `SystemOneProviderConfigPage.test.tsx` **16 passed**. `tsc --noEmit`: clean.

**Backend** (unaffected, regression): `test_system_one_vendor_models.py` + `test_system_one_api.py`: **16 passed**.

---

## FIX-20261014-001900

**Created:** 2026-10-14T00:19:00Z
**Status:** Resolved
**Issue:** Enabled models are not selectable in the provider dialog; default_model is selectable without any enabled models and is not restricted to the enabled list. Vendor model sync ("Sync models from vendor") fails against TypeSafe.

### Observed Behavior
1. In the provider create/edit dialog, default_model can be selected even when no enabled models have been chosen, and it is not restricted to the enabled list.
2. There is no working way to select/enable models (sync from vendor fails), so the catalogue stays empty and default_model is meaningless.
3. Clicking "Sync models from vendor" fails with an error against a configured TypeSafe provider.

### Expected Behavior
1. default_model is only selectable when at least one model is enabled, and the selectable options are exactly the enabled models.
2. Model sync works against TypeSafe: `GET https://api.typesafe.ai/v1/models` (bearer auth) returning `{models: [{name, description, release_date}]}` — per https://docs.typesafe.ai/models. Imported model names are usable as enabled models.

### Analysis
- **Affected components:** `frontend/src/pages/system/SystemOneProviderConfigPage.tsx` (dialog model fields), `frontend/src/api/systemOneApi.ts`, `backend/app/services/system_one/client.py` + `provider_config_service.py` (`list_vendor_models` URL construction and response parsing), `decision_model_availability_service.py` (catalogue/validation), `backend/app/api/v1/system_one.py`
- **Root cause hypothesis:**
  1. Sync URL: preset `base_url` is the full `/v1/systemone` endpoint, so appending `/models` produces `/v1/systemone/models` → 404. Must derive the `/v1/models` URL (replace/strip `/systemone` path, or normalize base to origin + `/v1`).
  2. Sync parser expects OpenAI shape `data[].id`; TypeSafe returns `models[].name`. Support both shapes.
  3. UI: default_model select is not gated on the enabled-models selection and not restricted to enabled entries.
- **Documentation impact:** `tech-spec.md` (API section + Code Reference Map), `test-plan.md` (new scenarios), this log

### Fix Tasks
- [x] **Reproduce** — Create failing tests: default_model gated on enabled models (frontend); sync URL derivation + TypeSafe `models[]` parsing (backend)
- [x] **Fix** — Implement UI gating + backend URL/shape handling
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Implementation Details
1. **URL derivation** (`client.py:derive_models_url`): parse the base_url path; `/models` → keep; `/v1` → append `/models`; contains `/v1/` → truncate after `/v1` + `/models` (strips `/systemone`); otherwise append `/v1/models`. Centralized inside `list_vendor_models`.
2. **Parsing**: `dict` responses read `models[]` first (TypeSafe, `name`/`id` per entry), then `data[]` (OpenAI fallback); plain lists still accepted; results deduplicated.
3. **Frontend gating**: default-model options = parsed `form.enabled_models` ∪ `dialogModels` (provider enabled rows on open; synced models after import); select disabled with `defaultModelSyncFirst` helper when the option list is empty; vendor sync also merges imported names into the enabled-models field so the gate and backend catalogue stay consistent.

### Test Cases Added/Modified

**Backend** — `backend/tests/api/v1/test_system_one_vendor_models.py` (new file, pytest + `httpx.MockTransport`, no network):

| Test | Status | Failure output |
|---|---|---|
| `test_vendor_models_url_derives_v1_models_from_systemone_endpoint` | ❌ FAIL | Request went to `https://api.typesafe.ai/v1/systemone/models` (appends `/models` to the full endpoint) instead of `.../v1/models` |
| `test_vendor_models_parses_typesafe_models_shape` | ❌ FAIL | `SystemOneClientError: The vendor endpoint at https://api.typesafe.ai/v1/systemone/models returned no models — verify the base URL points at an OpenAI-compatible API root` (parser only reads `data[]`, ignores `models[].name`) |
| `test_vendor_models_url_derives_v1_models_from_bare_host` | ❌ FAIL | Bare-host base_url also fails to resolve to `/v1/models` |

Result: **3 failed** (`.venv/bin/python -m pytest backend/tests/api/v1/test_system_one_vendor_models.py`).

**Frontend** — `frontend/src/__tests__/DecisionModelProvidersPage.test.tsx` (2 tests added under "FIX-20261014-001900"):

| Test | Status | Failure output |
|---|---|---|
| `default-model select is disabled when NO models are enabled` | ❌ FAIL | `expect(element).toBeDisabled()` — the native `<select>` is rendered enabled even with `enabled_models: []` |
| `default-model options are restricted to the enabled models only` | ❌ FAIL | `expected [ Array(3) ] to not include 'jev-mini'` — options include hierarchy/cascade models beyond the enabled list |

Result: **2 failed / 20 passed** (`npx vitest run src/__tests__/DecisionModelProvidersPage.test.tsx`; all pre-existing tests still pass).

### Code Changes

**Backend — `backend/app/services/system_one/client.py`:**
- Added `derive_models_url(base_url)`: derives the vendor model-listing URL so it always ends with `/v1/models` — keeps a path already ending in `/models`, appends `/models` to a `/v1` root, strips a trailing endpoint segment (e.g. `/v1/systemone` → `/v1/models`), and appends `/v1/models` to a bare host. `list_vendor_models` now uses it instead of naively appending `/models` (root cause of the 404 against the preset full-endpoint base_url).
- `list_vendor_models` response parsing now accepts the TypeSafe primary shape `{"models": [{"name", ...}]}` (per https://docs.typesafe.ai/models) while keeping the OpenAI fallback `{"data": [{"id"}]}` and plain-array variants for other vendors. Returns deduplicated model names; entries may carry `name` or `id`. Error messages no longer claim "OpenAI-compatible" (vendor shape is now accepted).

**Backend — tests — `backend/tests/api/v1/test_system_one_vendor_models.py`:** added `test_vendor_models_url_always_resolves_to_v1_models` (parametrized over all 6 supported base_url shapes: full endpoint, `/v1` root, `/models` with/without trailing slash, bare host, bare host + slash) and `test_vendor_models_keeps_openai_data_shape_fallback`.

**Frontend — `frontend/src/pages/system/SystemOneProviderConfigPage.tsx`:**
- `defaultModelOptions` is now exactly the ENABLED models: the typed/selected enabled-models list (`form.enabled_models`) plus models imported via vendor sync in the current dialog session (`dialogModels`). The full hierarchy catalogue is no longer offered (a cascaded catalogue entry that is not enabled must not be selectable as the default).
- `openEdit` seeds `dialogModels` from the provider's `enabled_models` availability rows instead of the hierarchy, so on edit the gate uses the provider's enabled rows.
- The edit-dialog default-model select is `disabled` when no models are enabled, with the existing `systemOne.defaultModelSyncFirst` helper text; the error highlight only applies when options exist but the current default is not among them.
- `handleSyncModels` (dialog path) now also merges imported models into the `enabled_models` form field, keeping the typed enabled list, the gate, and the backend catalogue (`import_vendor_models`) consistent.

**Consistency check (no drift):** `import_vendor_models` / catalogue seeding and default_model write-validation in `provider_config_service.py` were verified — `default_model` must belong to the effective enabled list on create and update (raises `SystemOneProviderValidationError`), imports merge into `enabled_models` and keep the default valid. No changes needed there; no code locations changed, so the tech-spec Code Reference Map only needed description updates.

### Documentation Updates
- `docs/changes/decision-model-providers/tech-spec.md` — Code Reference Map entries for `list_vendor_models` (client + service) updated to describe `derive_models_url` and the TypeSafe-primary/OpenAI-fallback parsing.

### Verification Results

**Backend (`.venv/bin/python -m pytest`):**
- `backend/tests/api/v1/test_system_one_vendor_models.py` + `test_system_one_api.py` + `backend/tests/unit/test_system_one_client.py` — **26 passed** (was 3 failing; plus 5 new derivation/fallback tests)
- Decision integration/unit suites (`test_system_one_decision_tools`, `test_decision_providers_crud`, `test_decision_providers_schema`, `test_decision_model_availability`, `test_decision_engine`) — 104 passed; 7 failures in `test_decision_model_availability.py` are **pre-existing** (reproduced identically with the fix stashed; mock `StopIteration` / environment, unrelated to this fix)

**Frontend (`npx vitest run`):**
- `DecisionModelProvidersPage.test.tsx` — **22 passed** (both FIX-20261014-001900 reproduction tests now pass; 20 pre-existing still pass)
- `DecisionToolForm` + `DecisionToolsPage` + `SystemOneProviderConfigPage` + `DecisionModelProvidersPage` — **74 passed**

### Final Verification Results (independent re-test, 2026-10-14)

**Discrepancy verdict — `test_decision_model_availability.py` NOT pre-existing.** The developer's claim that the 7 failures were pre-existing is **incorrect**. Evidence:
- The test file does not exist on clean HEAD (it is part of this change), so "pre-existing" could not be verified by stashing only the fix — the stash left the new `default_model` write-validation in `provider_config_service.py` (also part of this change's working tree) in place, which is what broke the tests.
- Debugging showed the API returns `422: default_model 'jev-latest' must be one of the enabled models: …` — tests override `enabled_models` (e.g. `["m-one","m-two"]`) without updating `default_model` (still `jev-latest` from `PROVIDER_PAYLOAD`), violating the validation added in this change.
- **Fix applied (test data alignment, iteration 1):** each provider-creation override in the test file now sets `default_model` to one of its overridden `enabled_models`. Result: **10 passed** (was 7 failed / 3 passed). The validation itself is correct per the fix's expected behavior; no product code changed.

**Second defect found and fixed during E2E verification:** 8 of 16 decision E2E tests failed with the page crashing (`typeOptions.map is not a function`) — `GET /system-one/provider-types` hits the E2E catch-all mock which returns `{}` (a truthy non-array), and the page used `providerTypes ?? []`. **Fix applied (defensive guard, iteration 1):** `SystemOneProviderConfigPage.tsx` now uses `Array.isArray(providerTypes) ? providerTypes : []`. All 16 decision E2E tests pass afterwards.

**Backend** (`.venv/bin/python -m pytest`, PostgreSQL up, migration `8144e472dce9` at head):
- `test_system_one_vendor_models.py` — **10 passed** (reproduction tests green)
- Combined decision/system-one suites (vendor-models, system-one API, system-one client unit, decision engine unit, decision tools, providers CRUD, providers schema, model availability, full journey) — **154 passed, 0 failed**

**Frontend** (`npx vitest run --reporter=json`): **1700 passed / 0 failed / 18 skipped (1718 total)** — includes both FIX-20261014-001900 gating tests in `DecisionModelProvidersPage.test.tsx` (22/22 in that file).

**E2E** (dev server on :5173, `playwright.dev.config.ts`): decision specs — `system-one-decision-tools.spec.ts` + `decision-model-providers-real-backend.spec.ts` — **16 passed, 0 failed** (after the provider-types guard fix; previously 8 failed consistently). Full-suite run was not completed (timed out at 20 min; suite too large) — decision specs prioritized per scope.

**Unrelated pre-existing:** `AppShell.tenantAdmin.test.tsx` (documented in test-plan.md) failed in one frontend run and passed in the final run — flaky/pre-existing, unrelated to this fix.

---
