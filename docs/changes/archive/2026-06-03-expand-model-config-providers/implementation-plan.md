# Implementation Plan: expand-model-config-providers

## Overview

This change extends the Model Configuration Service to support eight new API-key-based LLM providers (Gemini, Mistral, Cohere, Groq, Together, Fireworks, Perplexity, DeepSeek) alongside the four incumbent ones, refactors the runtime dispatcher into a small provider-registry facade, and updates the frontend dropdown, chip-colour map, and i18n catalogue. The work is split across a database enum extension, a dispatcher refactor, a model-lister extension, a frontend update, a comprehensive test pass, and a documentation pass — each phase is dependency-ordered and independently verifiable.

## Task Checklist

### Phase 1 — Enum and database migration

- [x] 1.1: Add 8 new members to the `ModelProvider` Python enum in `backend/app/db/models/agents.py`: `gemini`, `mistral`, `cohere`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`.
- [x] 1.2: Generate a new Alembic migration that additively extends the Postgres `model_provider_enum` with the 8 new values (no type recreation, no row rewrites, no parameterised DDL).
- [x] 1.3: Apply the migration locally with `alembic upgrade head` and verify the new revision is current; confirm the Postgres enum metadata now lists all 12 values.
- [x] 1.4: Verify backward compatibility by snapshotting the `provider_type` values of every pre-existing `ModelConfig` row before and after the migration and asserting byte-for-byte equality.

### Phase 2 — Provider-registry and dispatcher refactor

- [x] 2.1: Introduce a `PROVIDER_REGISTRY` module-level constant in `backend/app/services/agents/model_binding.py` that maps each of the 12 provider keys to a dispatch-family tag and a default API base URL.
- [x] 2.2: Add `_call_gemini` and `_call_cohere` private methods on `ModelBindingLayer` that POST to each vendor's native REST endpoint using the vendor's credential header convention.
- [x] 2.3: Refactor `ModelBindingLayer.complete_from_context` so the 12 providers are dispatched by registry family; OpenAI-compatible family reuses `_call_openai_compat`; native family uses `_call_gemini` / `_call_cohere` / `_call_anthropic`.
- [x] 2.4: Refactor `ModelBindingLayer.complete` to use the same registry-driven dispatch as `complete_from_context`; the existing call sites in `backend/app/services/agents/runtime_executor.py` must continue to work without modification.
- [x] 2.5: Widen the static extractors `extract_text`, `extract_tool_calls`, and `extract_usage` to cover the new providers, keeping the `null`-on-unavailable semantics for both text and usage.
- [x] 2.6: Add a single regression test asserting the error log includes the provider key when a vendor returns 4xx / 5xx for any of the 12 providers.

### Phase 3 — Model-lister extension

- [x] 3.1: Add `_list_openai_compat_models` shared helper on `ModelConfigService` that calls the OpenAI-style `/models` endpoint with the standard bearer header and a 10-second timeout.
- [x] 3.2: Add `_list_gemini_models` returning a curated static list of well-known Gemini model identifiers; no network call.
- [x] 3.3: Add `_list_cohere_models` returning a curated static list of well-known Cohere model identifiers; no network call.
- [x] 3.4: Refactor `list_models_for_config` to route each of the 12 providers through the appropriate helper and degrade gracefully on network failure (return `[]` and log an error).

### Phase 4 — Frontend types and dropdown

- [x] 4.1: Extend the `ModelProviderType` union in `frontend/src/types/index.ts` to include the 8 new string-literal members.
- [x] 4.2: Extend the `PROVIDERS` array in `frontend/src/pages/agents/ModelConfigDialog.tsx` with one entry per new provider; preserve incumbent entries in their current order.
- [x] 4.3: Extend the `providerColor` chip-colour map in `frontend/src/pages/agents/ModelConfigListPage.tsx` so every supported provider has a unique MUI 7 chip colour (no two providers share a colour).
- [x] 4.4: Add i18n labels for the 8 new providers under `frontend/src/i18n/locales/en.json` at `agents.modelConfigs.providerLabels` (or the equivalent nested key) so the dropdown and list chip both read from a single translatable map.

### Phase 5 — Tests

- [x] 5.1: Extend `backend/tests/unit/test_model_config_service.py` with a CRUD lifecycle test for each of the 8 new providers (create / read / update / delete with vault encryption) and a list-models test per native-API provider.
- [x] 5.2: Extend `backend/tests/unit/test_model_binding.py` with a resolve + dispatch test for each of the 8 new providers and the 4xx error-log assertion from task 2.6.
- [x] 5.3: Extend `backend/tests/api/test_model_configs_api.py` with round-trip tests for the full 12-provider catalogue (list, create, get, update, delete) and a 422 for the API-key-field validation.
- [x] 5.4: Extend `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx` so all 12 providers appear in the dropdown, the create flow inserts a row without manual reload, the edit flow pre-populates, the delete flow removes the row, and the chip colour is unique per provider.
- [x] 5.5: Extend `e2e/tests/agent-runtime.spec.ts` with a model-configurations block: list page renders chips for all 12 providers; create dialog accepts a new provider and the row appears; edit dialog saves; delete dialog removes; one variant uses a real backend (no mocks) per the change-lifecycle skill's database-change rules.

### Phase 6 — Documentation update

- [x] 6.1: Create the new dedicated Model Configurations feature spec at `docs/master/product/features/model-configurations.md` (or expand `agent-management.md` in place if the team prefers a single file) — describe the 12-provider catalogue, the CRUD lifecycle, the credential-encryption model, the "Fetch Models" behaviour, and the runtime resolution contract.
- [x] 6.2: Update `docs/master/product/features/agent-management.md` to reference the Model Configurations feature spec instead of enumerating providers inline.
- [x] 6.3: Update `docs/master/product/features/agent-types.md` and `docs/master/product/features/agent-runtime-gateway.md` to point to the Model Configurations feature spec for the model picker and runtime resolution.
- [x] 6.4: Update `docs/master/architecture/modules/model-config.md` with the dispatch-family table, the 12-value `provider_type` annotation, and a brief "Adding a new provider" section.
- [x] 6.5: Update `docs/master/architecture/system-overview.md` only if a diagram names the four providers explicitly — replace with a generic "LLM provider (catalog)" label and a paragraph pointing to the Model Configurations feature spec.
- [x] 6.6: Update `docs/master/data-model/modules/agents/entities.md` to annotate `ModelConfig.provider_type` with the 12 supported values, and add a paragraph noting the additive-migration extension path.
- [x] 6.7: Update `docs/master/data-model/overview.md` (Agent Management section) with the same `provider_type` annotation, replacing any per-provider enumeration with a reference to the module spec.
- [x] 6.8: Update `docs/master/technology/modules/agents/tech-spec.md` with the 12-provider catalogue, the dispatch-family note, and the new Code Reference Map rows for the registry, the new `_call_*` helpers, the new `_list_*` helpers, the new `PROVIDER_REGISTRY` constant, and the new Alembic migration file.
- [x] 6.9: Update `docs/master/qa/test-plans/agent-runtime-test-plan.md` with per-provider WHEN/THEN scenarios pointing to the new unit and API tests.
- [x] 6.10: Update `docs/master/qa/test-plans/agent-engine-test-plan.md` with per-provider WHEN/THEN scenarios for the engine-level dispatch path.
- [x] 6.11: Update `docs/master/qa/test-plans/agents-ui-test-plan.md` with per-provider WHEN/THEN scenarios for the dropdown, chip colour, and create/edit/delete flows.

## Phase 1: Enum and database migration

### Task 1.1: Add 8 new members to the `ModelProvider` enum

Description: Extend the `ModelProvider` Python enum in `backend/app/db/models/agents.py` with the 8 new string-literal members listed in the task. Each member's value must equal its key. The enum file is the canonical source of truth for the allowlist — no other code in this change is allowed to hard-code a provider key.

Done when: The enum lists all 12 members; the import statement in `model_binding.py` and `model_config_service.py` resolves without changes; the existing `pytest` suite continues to pass; type-check tools (e.g. mypy / pyright if run locally) report no errors on `backend/app/db/models/agents.py`.

### Task 1.2: Generate the Alembic migration

Description: From `backend/`, run the autogenerate workflow to produce a new revision under `backend/alembic/versions/` whose `down_revision` chains from `f4a5b6c7d8e9` (the most recent revision). Manually edit the generated file so it uses the project's `postgresql.ENUM(..., create_type=False)` pattern and a non-parameterised `ALTER TYPE ... ADD VALUE` statement (no `.bindparams()` per `AGENTS.md`). The migration must be additive only — no `DROP TYPE`, no `CREATE TYPE`, no row rewrites.

Done when: A new file exists under `backend/alembic/versions/` with a deterministic `revision` and `down_revision = "f4a5b6c7d8e9"`; the `upgrade()` function adds all 8 new values to the existing `model_provider_enum`; the `downgrade()` function leaves the values in place (matching the project's additive-only migration convention) and the file is reversible on its own when the database is empty.

### Task 1.3: Apply the migration locally

Description: From `backend/`, run `python -m alembic current` to capture the pre-state, then `python -m alembic upgrade head`, then `python -m alembic current` again to capture the post-state. Connect to Postgres and inspect the enum metadata to confirm all 12 values are present.

Done when: `alembic current` shows the new revision id; the Postgres enum metadata returns the 12 names in the expected order; the migration is idempotent on a second `alembic upgrade head`; the SQLite test path (used by the in-memory test suite) is a no-op for the `ALTER TYPE` statement.

### Task 1.4: Verify backward compatibility for existing `ModelConfig` rows

Description: Snapshot the `id` and `provider_type` of every existing `ModelConfig` row before the migration; apply the migration; snapshot again; assert byte-for-byte equality of the two snapshots. The migration must not rewrite, reinterpret, or alter any existing `provider_type` value.

Done when: A documented script or test fixture records the before/after snapshots; the comparison is automated; on a populated test database the assertion passes; on an empty database the assertion is trivially true.

## Phase 2: Provider-registry and dispatcher refactor

### Task 2.1: Introduce `PROVIDER_REGISTRY`

Description: Add a `PROVIDER_REGISTRY` constant in `backend/app/services/agents/model_binding.py` that maps each of the 12 provider keys to a `DispatchSpec`-like object carrying (a) the dispatch-family tag (`openai_compat` or `native`), (b) the default `api_base_url` where applicable, and (c) the static curated model list for providers with no public listing endpoint. The constant must be import-safe (no I/O) and free of side effects.

Done when: The constant exists at module scope; every one of the 12 provider keys is present; the structure is documented in a docstring; an `import` from another module loads it without side effects.

### Task 2.2: Add `_call_gemini` and `_call_cohere` private methods

Description: Add two new private methods on `ModelBindingLayer` whose job is to send a chat-completions-style request to the Gemini and Cohere native REST endpoints. The methods must accept the same parameter shape as the existing `_call_openai_compat` and `_call_anthropic` (api_key, model, messages, optional tools, max_tokens), use `httpx.AsyncClient` with `get_ssl_context()`, attach the vendor-native credential header, and raise `ModelBindingError` (after logging the status and body) on a non-2xx response.

Done when: Both methods exist; their public surface mirrors the existing private callers; a unit test asserts that a 4xx response is logged with the provider key and surfaces as `ModelBindingError`; a unit test asserts that a 200 response returns the parsed JSON body.

### Task 2.3: Refactor `complete_from_context` to use the registry

Description: Replace the four-branch `if/elif` ladder in `ModelBindingLayer.complete_from_context` with a single lookup against `PROVIDER_REGISTRY`. The OpenAI-compatible family must go through `_call_openai_compat`; the native family must go through `_call_gemini`, `_call_cohere`, or `_call_anthropic`; an unknown provider key must raise `ModelBindingError` and log the provider key.

Done when: All 12 provider keys are accepted; the dispatch is data-driven (no per-provider `if` branch); the Azure OpenAI quirk (which composes the URL from `api_base_url` and the deployment name) is preserved; the OpenAI-compat default URL fallback is preserved; an unknown key is rejected with a logged provider name.

### Task 2.4: Refactor `complete` to use the same registry-driven dispatch

Description: Mirror the refactor in task 2.3 on `ModelBindingLayer.complete`, which takes an `AgentType` and a `ModelConfig` (ORM-typed) instead of a context dict. The two functions should call the same internal helper so the dispatch logic is defined in exactly one place.

Done when: `complete` accepts every one of the 12 `ModelProvider` enum values; the existing call sites in `backend/app/services/agents/runtime_executor.py` (around lines 1511, 2032, 2259, 2913) work without modification; the behaviour is identical to `complete_from_context` for the equivalent inputs.

### Task 2.5: Widen the static extractors

Description: Update `extract_text`, `extract_tool_calls`, and `extract_usage` so the response shapes of Gemini and Cohere are recognised alongside the existing OpenAI-compatible and Anthropic shapes. Preserve the `null`-on-unavailable semantics: if a provider does not return usage, `extract_usage` must return `None`, not raise.

Done when: `extract_text` returns the assistant's text from each of the 12 providers' canonical response shapes; `extract_tool_calls` returns the normalised tool-call list (or `[]`); `extract_usage` returns a normalised usage dict with `prompt_tokens`, `completion_tokens`, and `total_tokens`, or `None` if the provider did not return one; an unknown provider returns `""`, `[]`, and `None` respectively.

### Task 2.6: Add a 4xx / 5xx provider-key log assertion

Description: Add a single regression test that exercises `_call_openai_compat` (as a stand-in for the OpenAI-compatible family) plus `_call_anthropic`, `_call_gemini`, and `_call_cohere` against a mocked httpx client that returns 401 / 500. Assert that the error log line contains the provider key for every one of the 12 providers (the OpenAI-compatible providers can share the same logged message format, but the key must be present).

Done when: The test runs in under one second; it iterates over all 12 provider keys; the assertion is specific (it looks for the provider key string in the captured log output, not just "error").

## Phase 3: Model-lister extension

### Task 3.1: Add `_list_openai_compat_models` shared helper

Description: Add a `_list_openai_compat_models(api_key, base_url)` method on `ModelConfigService` that calls the OpenAI-style `/models` endpoint with the standard bearer header and a 10-second timeout. The existing `_list_openai_models` and `_list_litellm_models` should be refactored to delegate to this shared helper, or be replaced by it.

Done when: The helper exists; the existing `_list_openai_models` and `_list_litellm_models` continue to work; the 6 new OpenAI-compatible providers (Mistral, Groq, Together, Fireworks, Perplexity, DeepSeek) can be listed by calling this helper with their respective `base_url`.

### Task 3.2: Add `_list_gemini_models` curated list

Description: Add `_list_gemini_models` returning a curated static list of well-known Gemini model identifiers (one entry per flagship / generally-available model at the time of release). The list must be sorted, must be non-empty, and must contain no network calls. The list is documented in a module-level constant so it can be reviewed and updated in a single place.

Done when: The method returns the static list sorted ascending; the constant is documented in a docstring with the source (Google's official "generally available" model list); an empty-credential configuration still returns the curated list.

### Task 3.3: Add `_list_cohere_models` curated list

Description: Add `_list_cohere_models` returning a curated static list of well-known Cohere model identifiers, mirroring task 3.2's contract.

Done when: The method returns the static list sorted ascending; the constant is documented in a docstring with the source; an empty-credential configuration still returns the curated list.

### Task 3.4: Wire per-provider branches in `list_models_for_config`

Description: Extend the dispatch in `ModelConfigService.list_models_for_config` to cover the 8 new providers. OpenAI-compatible family (Mistral, Groq, Together, Fireworks, Perplexity, DeepSeek) routes to `_list_openai_compat_models`; native family (Gemini, Cohere) routes to the respective curated helpers. Network failures must degrade to `[]` and log an error, matching the existing behaviour for the 4 incumbent providers.

Done when: All 12 providers return a non-empty list in the happy path; a simulated network failure returns `[]` and logs an error; the return value is sorted ascending, matching the existing contract.

## Phase 4: Frontend types and dropdown

### Task 4.1: Extend `ModelProviderType` union

Description: Add 8 new string-literal members to the `ModelProviderType` union in `frontend/src/types/index.ts`. The order of the existing 4 must be preserved (so existing usage sites are unaffected); the 8 new members are appended.

Done when: TypeScript compiles without errors; every existing reference to `ModelProviderType` (in `ModelConfig`, `WorkflowGenerationModelOption`, `ModelConfigDialog`, etc.) resolves; the type acts as a compile-time guardrail against typos in new code.

### Task 4.2: Extend `PROVIDERS` dropdown array

Description: Extend the `PROVIDERS` array in `frontend/src/pages/agents/ModelConfigDialog.tsx` with one entry per new provider. Each entry must reference a label that resolves through `t('agents.modelConfigs.providerLabels.<key>')` so the labels are translatable. Preserve the order of the 4 incumbent entries.

Done when: The array has 12 entries; the dropdown renders all 12 in the correct order; the i18n key for each new entry is present in `frontend/src/i18n/locales/en.json`; saving a config with a new provider persists the string-literal key.

### Task 4.3: Extend `providerColor` chip-colour map

Description: Extend the `providerColor` function in `frontend/src/pages/agents/ModelConfigListPage.tsx` so every one of the 12 supported providers has a unique MUI 7 chip colour. No two providers may share a colour; the existing 4 colour mappings must be preserved (so the visual identity of the incumbent providers is unchanged).

Done when: The function maps each of the 12 keys to a colour; the same colour is not used twice; an unknown provider falls back to the existing `default` colour; the visual layout of the list page does not change.

### Task 4.4: Add i18n labels for the 8 new providers

Description: Add a `providerLabels` (or equivalent nested) map to `frontend/src/i18n/locales/en.json` under `agents.modelConfigs` with one English display label per new provider. The 4 incumbent providers may remain as they are; the 8 new keys are added in stable, release-defined order. No label may be hard-coded inside a component.

Done when: The JSON file is valid; every new provider has a label; the dropdown and the list chip both read from the same map; the `t()` function returns the expected string for every key.

## Phase 5: Tests

### Task 5.1: Extend backend unit tests for the service

Description: Add tests in `backend/tests/unit/test_model_config_service.py` covering: (a) create / read / update / delete for each of the 8 new providers, asserting that the AES-256 vault encrypts the API key and that the API-key field is never round-tripped to the response; (b) list-models tests for Gemini and Cohere, asserting that the curated list is returned; (c) list-models tests for the 6 OpenAI-compatible providers, asserting that the shared helper is invoked.

Done when: At least 8 new tests pass; the vault is exercised on every create / update path; the list-models tests cover both the static and live-listing paths.

### Task 5.2: Extend backend unit tests for the binding layer

Description: Add tests in `backend/tests/unit/test_model_binding.py` covering: (a) `resolve_model_config` for each of the 8 new providers (when a `ModelConfig` whose `provider_type` is one of the new keys has the model in its `enabled_models` list, the resolver returns it); (b) `complete_from_context` dispatches to the right internal caller for each of the 12 providers; (c) `extract_text`, `extract_tool_calls`, and `extract_usage` return the right shape for Gemini and Cohere response envelopes.

Done when: All 8 new provider cases are covered; the existing test cases for the 4 incumbent providers still pass; the 4xx error-log assertion from task 2.6 is included in this file (or imported from it).

### Task 5.3: Extend backend API tests

Description: Add tests in `backend/tests/api/test_model_configs_api.py` covering: (a) `GET /api/v1/agents/model-configs` returns all 12 provider keys across multiple configs; (b) `POST /api/v1/agents/model-configs` accepts each of the 8 new keys and round-trips the `provider_type` value; (c) `PUT /api/v1/agents/model-configs/{id}` updates a `provider_type` from one new key to another; (d) `DELETE /api/v1/agents/model-configs/{id}` returns 409 when an AgentType still references a model from the config; (e) `GET /api/v1/agents/model-configs/{id}/models` returns a non-empty list for each of the 12 providers.

Done when: The tests run against a real (or in-memory) database; the round-trip is verified byte-for-byte; permission tests still pass (the new provider keys do not weaken the existing permission rules).

### Task 5.4: Extend frontend tests

Description: Add tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx` covering: (a) the dropdown lists all 12 providers; (b) selecting a new provider in the create dialog and submitting inserts a row in the list without manual reload; (c) opening the edit dialog for a config with a new provider pre-populates correctly; (d) clicking the delete icon and confirming removes the row; (e) the chip colour is unique per provider (asserted by computing the colour for every one of the 12 keys and asserting no two values are equal); (f) the standard dialog-error pattern is in place (a permission-denied or other API error appears inline, not as a silent failure).

Done when: All new tests pass under Vitest; the existing 4-provider tests still pass; the chip-colour uniqueness assertion is explicit and machine-checked.

### Task 5.5: Extend E2E tests

Description: Add a `model-configurations` block in `e2e/tests/agent-runtime.spec.ts` that exercises: (a) the list page renders chips for all 12 providers; (b) the create dialog accepts a new provider (e.g. Gemini), saves, and the row appears; (c) the edit dialog saves a `provider_type` change from one new provider to another; (d) the delete dialog removes the row; (e) the page is reload-free across the create / edit / delete flow. One variant must use a real backend (no `page.route()` mocks) per the change-lifecycle skill's database-change rules.

Done when: The E2E tests pass against a running backend; the real-backend variant is labelled `Real Backend Integration - Model Configurations`; the test report shows at least 12 provider keys exercised in the UI flow.

## Phase 6: Documentation update

### Task 6.1: Create the new dedicated Model Configurations feature spec

Description: Create `docs/master/product/features/model-configurations.md` (preferred over inlining into `agent-management.md` per `spec-change.md` NC-4). Document the 12-provider catalogue, the CRUD lifecycle, the credential-encryption model, the "Fetch Models" behaviour, and the runtime resolution contract. The spec must be business-language and free of implementation details.

Done when: The file exists; every section listed above is present; the 12-provider catalogue is enumerated with a one-line note per provider describing the dispatch family; the file is linked from `docs/master/product/features/agent-management.md`.

### Task 6.2: Update `agent-management.md`

Description: Update `docs/master/product/features/agent-management.md` so any reference to a fixed four-provider set is replaced with a reference to the new Model Configurations feature spec.

Done when: No hard-coded four-provider enumeration remains; the model-selection criterion names "Model Configurations" as the source of truth; the document is consistent with the new spec.

### Task 6.3: Update `agent-types.md` and `agent-runtime-gateway.md`

Description: Update `docs/master/product/features/agent-types.md` and `docs/master/product/features/agent-runtime-gateway.md` to point to the Model Configurations feature spec for the model picker and runtime resolution. Add a one-line statement that the model picker in the Agent Type form is sourced from the centrally managed catalogue and grows as new providers are configured.

Done when: Both files reference the new spec; no per-provider enumeration remains in either file; the runtime gateway spec notes the 12-provider dispatch surface.

### Task 6.4: Update `model-config.md` (architecture module spec)

Description: Update `docs/master/architecture/modules/model-config.md`. Replace the existing "Supported Backend Types" table with a provider-family table that lists the two dispatch families (OpenAI-compatible and native-API) and the specific provider keys in each. Update the `ModelConfig` entity table so the `provider_type` description enumerates the 12 supported values. Add a brief "Adding a new provider" section that points future maintainers to `PROVIDER_REGISTRY`, the model-lister helpers, and the i18n key map.

Done when: The dispatch-family table is present; the `provider_type` description enumerates all 12 keys; the "Adding a new provider" section references the right source files; the Mermaid `flowchart` either stays as-is or is updated to reflect the registry grouping (per the architecture document's instructions).

### Task 6.5: Update `system-overview.md` (conditional)

Description: Update `docs/master/architecture/system-overview.md` only if a diagram names the four providers explicitly. Replace such labels with a generic "LLM provider (catalog)" label, and add a one-paragraph note pointing to the Model Configurations feature spec.

Done when: Any provider-specific label in the system-overview diagrams is replaced; the paragraph note is present; if no diagram was provider-specific, the change is a no-op and the file is left unchanged.

### Task 6.6: Update `data-model/modules/agents/entities.md`

Description: Update `docs/master/data-model/modules/agents/entities.md` to annotate `ModelConfig.provider_type` with the 12 supported values, and add a one-paragraph note that the enum is extended through additive migrations and that adding a new value is a release-led activity.

Done when: The Mermaid `erDiagram` annotation lists all 12 keys; the prose paragraph is present; no other attribute on `ModelConfig` is changed; no other entity in the file is changed.

### Task 6.7: Update `data-model/overview.md`

Description: Update `docs/master/data-model/overview.md` (Agent Management section only) with the same `provider_type` annotation as in task 6.6, and replace any per-provider enumeration in the surrounding prose with a generic reference to the module spec.

Done when: The overview's `erDiagram` block carries the 12-value annotation; the surrounding prose does not enumerate individual providers; no other `erDiagram` block in the file is changed.

### Task 6.8: Update master technology spec (Code Reference Map)

Description: Update `docs/master/technology/modules/agents/tech-spec.md` so the Code Reference Map includes every new symbol added by this change: the 8 new enum members of `ModelProvider`, the new `PROVIDER_REGISTRY` constant, the new `_call_gemini` and `_call_cohere` private methods, the new `_list_openai_compat_models`, `_list_gemini_models`, and `_list_cohere_models` helpers, and the new Alembic migration file. Update the `ModelConfig` / `ModelConfigRead` / `ModelConfigCreate` / `ModelConfigUpdate` schema descriptions to note that the provider-type field accepts the 12 keys. Add a brief paragraph describing the two dispatch families and where in the codebase a new provider would be registered.

Done when: The Code Reference Map is comprehensive; the dispatch-family paragraph is present; the model-schema descriptions reference the 12-provider catalogue; the file is otherwise consistent with the existing format.

### Task 6.9: Update `agent-runtime-test-plan.md`

Description: Update `docs/master/qa/test-plans/agent-runtime-test-plan.md`. Add a per-provider scenario block pointing to the new unit tests in `backend/tests/unit/test_model_config_service.py` and `backend/tests/unit/test_model_binding.py`, and to the API tests in `backend/tests/api/test_model_configs_api.py`. Add a WHEN/THEN scenario for each of the 8 new providers asserting that a model id bound to a config of that provider is dispatched to the correct vendor endpoint, with a clear provider-key error on failure.

Done when: Each of the 8 new providers has a scenario block referencing the right test files; the existing scenarios for the 4 incumbent providers are preserved.

### Task 6.10: Update `agent-engine-test-plan.md`

Description: Update `docs/master/qa/test-plans/agent-engine-test-plan.md` with per-provider WHEN/THEN scenarios for the engine-level dispatch path. The engine-level scenarios are distinct from the runtime-level scenarios in task 6.9: they cover the tool-calling, plan-mode, and error-handling paths that are exercised by the agent loop.

Done when: Each of the 8 new providers has an engine-level scenario block; the existing scenarios for the 4 incumbent providers are preserved.

### Task 6.11: Update `agents-ui-test-plan.md`

Description: Update `docs/master/qa/test-plans/agents-ui-test-plan.md` with per-provider WHEN/THEN scenarios for the dropdown, chip colour, and create/edit/delete flows. Add a "real backend" variant per the change-lifecycle skill's database-change rules. Reference the frontend tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx`, and the model-configuration block of `e2e/tests/agent-runtime.spec.ts`.

Done when: At least one real-backend E2E variant exists; each provider has a UI scenario block; the scenarios reference the actual test files; the page is asserted to be reload-free.

## Completion Checklist

- [x] All 34 tasks across 6 phases are complete and individually verified.
- [x] All 12 provider keys are accepted by the backend (`ModelProvider` enum, Alembic migration, dispatcher registry, model-lister) and the frontend (`ModelProviderType` union, `PROVIDERS` array, `providerColor` map, i18n labels).
- [x] Existing `ModelConfig` rows with the 4 incumbent provider types are unchanged and continue to be returned and editable.
- [x] AES-256 credential encryption is exercised for every new provider's create / update path; the `has_credentials` flag is the only credential-derived field in the response.
- [x] The "Fetch Models" capability returns a non-empty list for every one of the 12 providers; failure degrades to `[]` with a logged error.
- [x] The 4xx / 5xx error path includes the provider key in the log line.
- [x] Backend unit tests, backend API tests, frontend Vitest tests, and E2E tests all pass for the new behaviour; the E2E suite includes at least one real-backend variant for the model-configurations block.
- [x] Master product, architecture, data-model, technology, and QA documents are updated per `spec-change.md`; the master technology spec's Code Reference Map includes every new symbol added by this change.
- [x] No new top-priority architecture rule from `docs/config.yaml` is violated (Control Center still owns the database; Agent Runtime still uses the data-client; agents never hold raw API keys).
- [x] Dialog error handling in the Model Configurations create / edit / delete dialogs follows the project's standard pattern (inline alert, not silent failure).
