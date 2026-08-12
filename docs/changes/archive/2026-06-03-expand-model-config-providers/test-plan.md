# Test Plan: expand-model-config-providers

## 1) Test Strategy

This change is `has_db_changes: true` (additive Alembic migration extending the Postgres `model_provider_enum` from 4 to 12 values) and touches every layer of the Model Configurations feature. The test plan covers all five layers defined in `docs/config.yaml` `source.tests`, with extra weight on schema-level validation, real-backend integration, and per-provider round-trip behaviour. The plan follows the project's standard pyramid (backend unit → backend API → frontend unit → E2E) and adds the database-specific checks required by the change-lifecycle skill for any `has_db_changes: true` change.

### Pre-Test Checklist (Mandatory — Database Change)

The following steps MUST be completed before running the full test suite, and a CI run-book entry must be added to the test execution notes:

- **Confirm migration applied.** Run `alembic current` from `backend/` and confirm the new revision id (chained from `f4a5b6c7d8e9`) is reported. If not, run `alembic upgrade head` and re-check.
- **Idempotency check.** Run `alembic upgrade head` a second time; the migration must be a no-op the second time (no `ALTER TYPE ... ADD VALUE` error, no duplicate-value error). This protects against test re-runs on already-migrated databases.
- **Test-database parity.** The local Postgres database used by `backend/tests/` must apply the migration in the fixture setup (`alembic upgrade head` in the conftest or session fixture) so the test schema matches production.
- **Downgrade safety.** Document that the migration's `downgrade()` is a no-op (additive-only convention); a smoke-test should be run once on an empty test database to confirm the upgrade is reversible to the prior enum state by re-running the prior migration.
- **information_schema baseline capture.** Before the test run, snapshot the `model_provider_enum` row in `information_schema` (column count = 12). After the run, the test must re-query and assert the row count is unchanged. A test in `backend/tests/db/test_model_provider_enum_migration.py` (new) automates this check.
- **Pre-existing row preservation.** Before the migration is applied, snapshot the `(id, provider_type)` tuple of every row in the `model_configs` table. After the migration, assert byte-for-byte equality. The new `test_model_provider_enum_migration.py` test automates this on a fixture-loaded test database and on an empty database (trivially true).
- **No DDL parameterisation regression.** A static review of the generated migration must confirm it does not use SQLAlchemy `.bindparams()` on `ALTER TYPE ... ADD VALUE` (Postgres does not support parameterised DDL) and uses `postgresql.ENUM(..., create_type=False)` for the in-model reflection.

### Test Layers

- **Backend unit** (`backend/tests/unit/test_model_config_service.py` and `backend/tests/unit/test_model_binding.py`): per-provider CRUD lifecycle with AES-256 encryption, per-provider dispatch and resolve, extractors widened to the new response shapes, and a single regression test that asserts the error log line contains the provider key for all 12 providers when a vendor returns 4xx/5xx.
- **Backend API** (`backend/tests/api/test_model_configs_api.py` extended): round-trip over the full 12-provider catalogue for `GET` / `POST` / `PUT` / `DELETE`, the 409 safety guard on delete, the `/models` endpoint returning a non-empty list for every provider, the 422 for non-enabled model references, and permission rules remain intact.
- **Backend database integration** (`backend/tests/db/test_model_provider_enum_migration.py` new): real-database assertions about the migration outcome — enum row count, column type, no recreated type, pre-existing rows preserved, idempotency on a second `alembic upgrade head`.
- **Frontend unit** (`frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx` extended): dropdown lists all 12 providers, chip colour uniqueness is machine-checked, create / edit / delete flows render reload-free, dialog error pattern (the project's `dialogError` + `PermissionDeniedAlert` convention) is in place for each new provider.
- **E2E** (`e2e/tests/agent-runtime.spec.ts` extended — new `Model Configurations` block): mock-driven E2E for fast feedback, plus a `Real Backend Integration - Model Configurations` variant that hits the real backend (no `page.route()` mocks) per the change-lifecycle skill's database-change rule. The real-backend variant is the safety net that catches migration-not-applied bugs the mocked tests cannot.
- **Manual / exploratory**: only where the test pyramid cannot reach — e.g. visual confirmation that a new provider's chip is distinct and recognisable in a browser at typical viewport widths, and a brief cross-locale check of the i18n labels in the dropdown.

### Quality Gates for Sign-off

- Every PRD acceptance criterion (AC-1 through AC-30) has at least one test reference in section 5.
- Backend coverage includes both happy path and the 4xx / 5xx / 422 / 403 / 409 negative paths.
- Frontend coverage includes both the new-provider variants and a regression assertion that incumbent providers still work.
- E2E includes at least one real-backend scenario in the `Model Configurations` block.
- The `information_schema` and pre-existing-row checks run against a real database (not a SQLite in-memory stub).

## 2) Coverage Areas

### Backend unit — service and dispatcher

- **ModelConfigService lifecycle per provider.** The existing 4-provider coverage in `test_model_config_service.py` is mirrored for each of the 8 new providers (`gemini`, `mistral`, `cohere`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`). The create / read / update / delete paths must each call the AES-256 vault (`get_vault().encrypt` / `decrypt`) on the API-key payload and the response must never carry the raw key. Coverage area is critical because it directly maps to PRD AC-23 (encryption parity) and AC-24 (placeholder semantics).
- **PROVIDER_REGISTRY dispatch and resolve.** `test_model_binding.py` exercises the resolve-and-dispatch path for each of the 12 providers. The dispatcher must route the 9 OpenAI-compatible providers through a single shared call path, route `anthropic` through its dedicated caller, and route the 2 native-API providers (`gemini`, `cohere`) through their own dedicated callers. Coverage area is critical because it directly maps to PRD AC-16 (correct dispatch) and AC-19 (provider-key attribution in error logs).
- **Extractor widening.** `extract_text`, `extract_tool_calls`, and `extract_usage` are widened to recognise the Gemini and Cohere response envelopes. The `null`-on-unavailable semantics for usage must be preserved (PRD AC-18).
- **Provider-key log assertion (single regression test).** A single test iterates over all 12 provider keys against a mocked httpx client that returns 4xx / 5xx and asserts the captured log line contains the provider key string. Coverage area is critical because it is the only machine-checked way to enforce PRD AC-19 across the full catalogue.
- **List-models per provider family.** The shared `_list_openai_compat_models` helper is exercised for each of the 6 new OpenAI-compatible providers; the curated static lists for Gemini and Cohere are exercised for empty-credential, non-empty-credential, and call-failure paths. Coverage area is critical because it directly maps to PRD AC-20 / AC-21 / AC-22.

### Backend API — CRUD and list-models endpoints

- **Round-trip over 12 providers.** The list / create / get / update / delete endpoints in `test_model_configs_api.py` are exercised with each of the 12 `provider_type` string literals. The `provider_type` field must round-trip byte-for-byte in the JSON response. Coverage area is critical because the public API surface is the integration point for the frontend and the agent runtime; a single broken literal cascades into the UI.
- **Provider-type change on update.** `PUT /agents/model-configs/{id}` must accept a `provider_type` change across the 12 keys (e.g. from `gemini` to `mistral`) and persist the new value. Coverage area is critical because it directly maps to PRD AC-10.
- **Delete safety guard.** `DELETE /agents/model-configs/{id}` must return 409 when an `AgentType.model_id` is in the config's `enabled_models` for every provider, mirroring the incumbent behaviour. Coverage area is critical because it directly maps to PRD AC-12.
- **List-models endpoint returns non-empty for every provider.** `GET /agents/model-configs/{id}/models` returns a non-empty list for each of the 12 providers. Network and credential failures degrade to `[]` with a 200 response; the UI's "no models returned" state is therefore always reachable. Coverage area is critical because it directly maps to PRD AC-20 and AC-22.
- **Permission rules unchanged.** The 403 path is exercised for each new provider to confirm the addition of 8 keys does not weaken the existing permission model. Coverage area is critical for D-6 (backward compatibility).

### Backend database integration (new test file)

- **Enum row count.** Query `information_schema` (e.g. `pg_type` joined to `pg_enum`) and assert the `model_provider_enum` type has exactly 12 values in the expected order (the 4 incumbent values, then the 8 new values, append-only). Coverage area is critical because it is the only test that catches a silently dropped `ALTER TYPE ... ADD VALUE`.
- **Column type preservation.** Query `information_schema.columns` for `model_configs.provider_type` and assert the column type is still `USER-DEFINED` (the `model_provider_enum` type) and the column is still `NOT NULL`. Coverage area is critical because the column shape is unchanged by the migration; a test that allowed the column type to drift would pass all backend unit tests yet fail at runtime.
- **Type not recreated.** Confirm the `model_provider_enum` Postgres OID is identical before and after the migration (no `DROP TYPE` / `CREATE TYPE`). Coverage area is critical because re-creating the type would silently break rows that referenced the old OID and would also break downstream extensions.
- **Pre-existing row preservation.** On a fixture-loaded test database, snapshot `(id, provider_type)` for every row in `model_configs` before and after the migration; assert byte-for-byte equality. On an empty database, the test is trivially true. Coverage area is critical because it directly maps to PRD AC-4 and D-6.
- **Idempotency on re-run.** Apply the migration a second time and assert it is a no-op (no errors, no schema drift). Coverage area is critical for CI re-runs.
- **Negative test for removed constraint.** Confirm there is no `UNIQUE` constraint or `CHECK` constraint on the `provider_type` column that would prevent the new values from being inserted (it is an enum, so this is a sanity check). Coverage area is critical for completeness of the schema-constraint test set.

### Frontend unit — dialog, list page, chip, dropdown

- **Dropdown lists 12 providers.** The provider-type `<Select>` in `ModelConfigDialog` lists all 12 entries; each entry's label is read from the i18n key `agents.modelConfigs.providerLabels.<key>` (no hard-coded English in the component). Coverage area is critical because it directly maps to PRD AC-3.
- **Create / edit / delete reload-free.** Opening the dialog, saving, and closing must update the parent table without a manual page reload. The existing dialog error pattern (`dialogError` state + `PermissionDeniedAlert`) must be in place for each new provider. Coverage area is critical because it directly maps to PRD AC-9 and AC-15.
- **Edit pre-population.** Opening the edit dialog for a config with a new provider pre-populates the display name, the correct provider in the dropdown, the `api_base_url`, the `enabled_models` chips, and the API-key placeholder (never the raw value). Coverage area is critical because it directly maps to PRD AC-8 and AC-23.
- **Chip colour uniqueness.** Compute the chip colour for every one of the 12 provider keys and assert no two values are equal. An unknown provider must fall back to the existing `default` colour. Coverage area is critical because it directly maps to PRD AC-3.
- **Delete confirmation.** The delete confirmation dialog is in place for each new provider; on confirm, the row is removed; on cancel, it remains. Coverage area is critical because it directly maps to PRD AC-11.
- **Recreate after delete.** After a config is deleted, an admin can create a new config with the same display name, the same provider, and a fresh API key, confirming true deletion. Coverage area is critical because it directly maps to PRD AC-13.
- **Disable / enable toggle.** The existing `is_disabled` toggle works for each new provider with the same cascade semantics as for the incumbent providers. Coverage area is critical because it directly maps to PRD AC-14.
- **Dialog error pattern (CRITICAL).** For every error path (403, 409, 422, 500, network failure), the inline `PermissionDeniedAlert` renders the error within the dialog and not as a silent failure. This is the project's CRITICAL dialog-error-handling standard and must hold for each new provider. Coverage area is critical because the standard is mandatory and applies to all dialogs.

### E2E — full flow with real backend and with mocks

- **Mocked flow** (`page.route()` mocks, fast feedback): list page renders all 12 chips, create dialog accepts each new provider and the row appears without page reload, edit dialog saves a provider-type change from one new provider to another, delete dialog removes the row. Coverage area is critical for fast feedback during the development cycle.
- **Real Backend Integration - Model Configurations** (no `page.route()` mocks, per the change-lifecycle skill's database-change rule): the Playwright test navigates to the Model Configurations page against the running backend, verifies the API returns 200 for the list endpoint (which only succeeds if the migration is applied and the enum has the 12 values), and verifies a `POST` with a new provider type (`gemini`) round-trips. The test is gated on the backend health endpoint and is skipped gracefully if the backend is not running. Coverage area is critical because it is the only test that exercises the real database schema and therefore catches migration-not-applied bugs.
- **Reload-free page flow.** Across the create / edit / delete flow in the mocked variant, the test asserts the page does not navigate away and the React Query cache is invalidated (no full page reload). Coverage area is critical because it directly maps to PRD AC-9 and AC-15.

### Cross-layer

- **AES-256 round-trip.** A backend unit test encrypts and then decrypts a sample API key for each of the 8 new providers and asserts the plaintext matches the original. The encrypted blob is never returned in any GET response. Coverage area is critical because it directly maps to PRD AC-23.
- **Observability attributes.** A backend unit test asserts that the OpenTelemetry span emitted for an inference call to a new provider carries the provider key, the model id, the config display name, and the standard latency / status attributes. Coverage area is critical because it directly maps to PRD AC-25.

## 3) Critical Scenarios

### Per-provider CRUD and security

**Scenario 3.1 — Per-provider create with API key encryption.** WHEN a Platform Administrator creates a Model Configuration for any of the eight new providers (one scenario block per provider, covering `gemini`, `mistral`, `cohere`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`) through the existing create dialog or REST `POST` endpoint, supplying a display name, an optional `api_base_url`, an API key, and an `enabled_models` list, THEN the backend encrypts the API key with the existing AES-256 vault and persists the encrypted blob against a `model_configs` row whose `provider_type` column carries the new enum value; the response payload contains only a `has_credentials` boolean and never the raw key or the encrypted blob; the new row appears in the parent Model Configurations table without a manual page reload; and the dialog closes. The end-to-end behaviour is verified by the per-provider tests in `backend/tests/unit/test_model_config_service.py` and `backend/tests/api/test_model_configs_api.py`, the dialog flow in `frontend/src/__tests__/ModelConfigDialog.test.tsx`, and the E2E flow in `e2e/tests/agent-runtime.spec.ts` `Model Configurations` block.

**Scenario 3.2 — Per-provider read.** WHEN the Platform Administrator opens the Model Configurations list page after creating a config for a new provider, THEN the row is rendered with the correct display name, the provider chip in the correct colour and label (per the i18n catalogue), a credentials-set or not-set indicator, the enabled-model count, and the existing Edit and Delete actions; the encrypted blob is not present in any cell; and the page is reload-free. Verified by `frontend/src/__tests__/ModelConfigListPage.test.tsx` and the E2E flow.

**Scenario 3.3 — Per-provider update and provider-type change.** WHEN the administrator opens the edit dialog for a config with one of the new providers, all fields are pre-populated correctly (display name, the correct provider in the dropdown, `api_base_url`, the `enabled_models` chips, and the API-key placeholder — never the raw value); on save, the changes are persisted and the parent table refreshes without a manual reload; and when the administrator changes `provider_type` from one new provider to another (for example, from `gemini` to `mistral`), the change is allowed, persists, and the chip colour and label in the list page update accordingly. Verified by `frontend/src/__tests__/ModelConfigDialog.test.tsx` and the API tests in `backend/tests/api/test_model_configs_api.py`.

**Scenario 3.4 — Per-provider delete with safety guard.** WHEN the administrator attempts to delete a config whose `enabled_models` includes a model id referenced by an existing `AgentType`, the delete is blocked with a 409 conflict response and the dialog surfaces the error inline using the project's standard `dialogError` + `PermissionDeniedAlert` pattern; WHEN the administrator confirms deletion of a config that is not referenced, the row is removed from the table without a manual reload, and the dialog closes; and WHEN a config has been deleted, the administrator can create a new config with the same display name, the same provider, and a fresh API key (true deletion, not soft-delete). Verified by the delete tests in `backend/tests/unit/test_model_config_service.py`, the API tests in `backend/tests/api/test_model_configs_api.py`, the dialog tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx`, and the E2E flow.

### Per-provider runtime dispatch and observability

**Scenario 3.5 — Per-provider dispatch to the correct vendor endpoint.** WHEN an agent invokes a model whose id is bound to a configuration of one of the eight new providers (one scenario block per provider, with the OpenAI-compatible family sharing a single dispatch path and the native-API providers going through their dedicated callers), the call reaches the correct vendor endpoint with the correct credential header, the response is normalised into Parthenon's internal completion envelope, and the response text, tool calls, and usage are extracted correctly (or recorded as unavailable with `null` for usage when the vendor does not report it). Verified by `backend/tests/unit/test_model_binding.py` (resolve and dispatch for each of the 12 providers) and the extractor tests.

**Scenario 3.6 — Per-provider 4xx / 5xx error log contains the provider key.** WHEN any one of the 12 providers (the four incumbent plus the eight new) returns a 4xx or 5xx response, the dispatcher raises `ModelBindingError` and the captured error log line contains the provider key string (for example, `gemini`, `mistral`) and the underlying vendor error body, so operators can immediately identify which provider the failing call was made against. Verified by a single regression test in `backend/tests/unit/test_model_binding.py` that iterates over all 12 keys.

**Scenario 3.7 — Provider-registry unknown provider rejection.** WHEN the agent runtime call site passes a `provider_type` that is not in the new 12-value registry, the dispatcher raises `ModelBindingError`, the log line contains the unknown key, and the call is blocked. Verified by a single negative test in `backend/tests/unit/test_model_binding.py`.

**Scenario 3.8 — Observability attributes on the inference call.** WHEN a successful or failed call is made to a new provider, the OpenTelemetry span and structured log line include the provider key, the model id, the config display name, and the standard latency and status attributes — consistent with the four incumbent providers. Verified by an OpenTelemetry capture test in `backend/tests/unit/test_model_binding.py`.

### Per-provider model listing ("Fetch Models")

**Scenario 3.9 — Per-provider "Fetch Models" returns a non-empty list.** WHEN the administrator clicks "Fetch Models" on the edit dialog for a config of any of the 12 providers, the existing endpoint `GET /agents/model-configs/{id}/models` returns a non-empty list of well-known model identifiers — sourced from a live vendor listing endpoint (where the vendor exposes one, used by the 6 new OpenAI-compatible providers plus the 3 incumbent OpenAI-compatible providers) or from a curated static list (used by `gemini`, `cohere`, and the existing `anthropic` provider). The list is sorted ascending and contains at least one entry. Verified by `backend/tests/unit/test_model_config_service.py` and the API tests in `backend/tests/api/test_model_configs_api.py`.

**Scenario 3.10 — Per-provider "Fetch Models" graceful degradation.** WHEN the "Fetch Models" call fails (network error, invalid key, vendor outage) for any of the 12 providers, the endpoint returns 200 with an empty list and logs a structured error, the UI shows the existing "no models returned" state, and the administrator is never blocked from saving the configuration. Verified by the failure-path tests in `backend/tests/unit/test_model_config_service.py` and `backend/tests/api/test_model_configs_api.py`, and the dialog's "fetch-models" failure path in `frontend/src/__tests__/ModelConfigDialog.test.tsx`.

### Security, encryption, and audit

**Scenario 3.11 — AES-256 round-trip and never-returned credential.** WHEN an API key for any of the 8 new providers is stored against a `ModelConfig` row, the encrypted blob is the only representation of the key on disk, the `has_credentials` boolean is the only credential-derived field in the `ModelConfigRead` response, and a round-trip encryption-and-decryption test recovers the original plaintext byte-for-byte. Verified by `backend/tests/unit/test_model_config_service.py` (create / update paths) and a dedicated AES-256 round-trip test.

**Scenario 3.12 — API-key field placeholder semantics on edit.** WHEN the administrator opens the edit dialog for a config that already has an API key stored, the API-key field is left at the placeholder; on save with no change to the field, the stored credential is not overwritten; WHEN a new value is typed, the stored credential is replaced; and WHEN the field is explicitly cleared, the stored credential is removed. Verified by the edit-mode tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and the update tests in `backend/tests/unit/test_model_config_service.py`.

### Database and migration

**Scenario 3.13 — Migration applied, enum has 12 values, existing rows untouched.** WHEN `alembic current` is run from `backend/`, the new revision id is reported (chained from `f4a5b6c7d8e9`); WHEN the Postgres `model_provider_enum` metadata is queried, the type lists exactly 12 values in the expected order (4 incumbent + 8 new, append-only); WHEN the `model_configs.provider_type` column is queried in `information_schema.columns`, its type is still `USER-DEFINED` (the enum) and it is still `NOT NULL`; and WHEN the `(id, provider_type)` of every pre-existing row in `model_configs` is snapshotted before and after the migration, the two snapshots are byte-for-byte equal. Verified by `backend/tests/db/test_model_provider_enum_migration.py` (new), which runs against a real Postgres database.

### Frontend dropdown, chip colour, and reload-free flow

**Scenario 3.14 — Dropdown lists all 12 providers; chip colours are unique.** WHEN the administrator opens the create or edit dialog, the provider-type dropdown lists all 12 provider keys, each with a label resolved through the i18n key `agents.modelConfigs.providerLabels.<key>`; WHEN the administrator opens the list page, every row's chip colour is computed by the `providerColor` function and no two of the 12 keys share a colour; and WHEN a key not in the registry is rendered (negative test), the chip falls back to the existing default colour. Verified by `frontend/src/__tests__/ModelConfigDialog.test.tsx`, `frontend/src/__tests__/ModelConfigListPage.test.tsx`, and the chip-colour-uniqueness test (machine-checked by computing the colour for all 12 keys and asserting no two values are equal).

**Scenario 3.15 — Reload-free page flow.** WHEN the administrator creates, edits, and then deletes a config for a new provider, the parent Model Configurations table refreshes after each dialog closes without a manual page reload, the React Query cache is invalidated correctly, and the page URL does not change. Verified by the E2E flow in `e2e/tests/agent-runtime.spec.ts` `Model Configurations` block (mocked variant) and the dialog-close tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx`.

### Real-backend E2E variant

**Scenario 3.16 — Real-backend integration validates the migration.** WHEN the Playwright test in the `Real Backend Integration - Model Configurations` block is run against a running backend (no `page.route()` mocks), the test asserts that `GET /api/v1/agents/model-configs` returns a 2xx response (which only succeeds if the migration is applied and the enum has the 12 values), and that a `POST` with `provider_type = "gemini"` round-trips a 201 response with the new key in the response body. The test is skipped gracefully if the backend health endpoint does not respond. Verified by `e2e/tests/agent-runtime.spec.ts` in the `Real Backend Integration - Model Configurations` block.

### i18n

**Scenario 3.17 — i18n label for each new provider is present.** WHEN the dropdown and the list chip render a label for any of the 8 new providers, the label is read from `agents.modelConfigs.providerLabels.<key>` in `frontend/src/i18n/locales/en.json` through the i18next `t()` function, no English string is hard-coded in the component, and a missing i18n key falls back to the provider key (a graceful-degradation test). Verified by the dropdown tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and the list-page tests.

## 4) Edge Cases & Risks

- **Migration runs on a populated database with the `ALTER TYPE ... ADD VALUE` statement.** Older Postgres versions execute `ALTER TYPE ... ADD VALUE` outside transaction control, so a long-running concurrent transaction can block the migration. The test plan requires a manual run of the migration against a fixture-loaded database with concurrent writes (a low-volume connection pool) and a snapshot of the `model_configs` row count before and after; the `backend/tests/db/test_model_provider_enum_migration.py` test runs the same assertion in CI. The risk is the migration could appear to succeed but leave the enum in an inconsistent state.
- **Provider URL typo means the dispatcher hits a non-existent endpoint.** A custom `api_base_url` (or an internal future provider registered with a typo) can cause the dispatcher to send a chat-completions call to a non-existent host, which surfaces as a connection error. The dispatch path is exercised end-to-end against each new provider in `backend/tests/unit/test_model_binding.py`; the failure mode must be a `ModelBindingError` with the provider key in the log (Scenario 3.6) and not a silent 500.
- **Static curated list drifts out of date.** The Gemini and Cohere curated lists are static; vendors release new models on a continuous basis. The list-listing test asserts a non-empty list, but the list itself is reviewed against the vendor's "generally available" catalogue as part of the release checklist. A test in `backend/tests/unit/test_model_config_service.py` asserts the curated list is non-empty and sorted; a manual code review of the curated list at release time is the primary mitigation.
- **Concurrent creates of the same provider type by two admins.** Two admins can simultaneously create a config for the same new provider type. The database enum allows duplicate `display_name`+`provider_type` rows (no uniqueness constraint in the current schema), so both inserts succeed; the resolved config at runtime is the first match by creation order (mirroring the incumbent semantics). The deterministic-resolution test in `backend/tests/unit/test_model_binding.py` covers this case.
- **Agent Runtime call site passes an unknown `provider_type`.** A new provider type registered in code but not yet in the dispatcher's registry (or vice versa) results in the dispatcher receiving an unknown key. Scenario 3.7 covers this case in `backend/tests/unit/test_model_binding.py`: the dispatcher must raise `ModelBindingError`, log the unknown key, and not crash.
- **`enabled_models` contains a model id that the new provider does not recognise.** If a config's `enabled_models` list contains a stale id, the dispatch should fail with a clear error from the vendor (or, in the curated-list case, the admin can re-fetch the models and clean the list). The list-models endpoint returns the live or curated list, which the UI uses to refresh the selection; the live-call failure path is covered by the 4xx / 5xx log assertion (Scenario 3.6).
- **Deletion race: an Agent Type is added between the check and the delete.** The existing 409 safety guard runs in the same transaction; a race window between the check and the delete could allow a successful delete while an AgentType is being created. The current implementation holds the safety guard inside the service method; the test in `backend/tests/unit/test_model_config_service.py` exercises the safe path, and the migration verification (Scenario 3.13) covers schema-level integrity.
- **i18n key missing for a new provider — dropdown falls back to the provider key.** If a translator omits the i18n entry for a new provider, the dropdown and the chip render the raw provider key (e.g. `gemini`) instead of the friendly English label. A graceful-degradation test in `frontend/src/__tests__/ModelConfigDialog.test.tsx` exercises the missing-key path and asserts the raw key is rendered without a crash; the project's i18n catalogue is reviewed at release time as the primary mitigation.
- **Test database not migrated.** A CI environment that skips `alembic upgrade head` in the test fixture setup will pass all the mocked tests but fail the real-backend E2E variant. The Pre-Test Checklist in section 1 mitigates this by requiring the migration to be applied before the test run, and the `Real Backend Integration - Model Configurations` E2E block serves as the catch-all safety net.
- **SQLite in-memory stub used in CI.** Some pytest paths run against an in-memory SQLite database to avoid spinning up Postgres. The enum extension is a Postgres-specific DDL statement; the test plan requires the schema-related tests in `backend/tests/db/test_model_provider_enum_migration.py` to run against a real Postgres instance, gated on a `requires_postgres` marker, so the in-memory SQLite stub does not falsely pass.

## 5) Acceptance Criteria Checklist

The mapping below points to the test files (paths from `docs/config.yaml` `source.tests`) that verify each PRD acceptance criterion from `prd.md`. Each AC is covered by at least one test reference.

### A. Provider Catalogue (Registry)

- **AC-1** (12 provider keys, full catalogue documented) — covered by `backend/tests/db/test_model_provider_enum_migration.py` (enum row count = 12) and the per-provider CRUD tests in `backend/tests/unit/test_model_config_service.py`.
- **AC-2** (each new provider storable, listed, created, updated, deleted) — covered by `backend/tests/api/test_model_configs_api.py` (round-trip) and the per-provider tests in `backend/tests/unit/test_model_config_service.py`.
- **AC-3** (dropdown lists 12 providers, distinct chip colours) — covered by `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx` (chip-colour-uniqueness test).
- **AC-4** (existing rows continue to be returned and editable) — covered by `backend/tests/db/test_model_provider_enum_migration.py` (pre-existing row preservation) and the backward-compat test in `backend/tests/unit/test_model_config_service.py`.

### B. CRUD Lifecycle for the Extended Catalogue

- **AC-5** (create flow inserts a row without manual reload) — covered by `frontend/src/__tests__/ModelConfigDialog.test.tsx`, `frontend/src/__tests__/ModelConfigListPage.test.tsx`, and the E2E flow in `e2e/tests/agent-runtime.spec.ts` `Model Configurations` block.
- **AC-6** (validation error, permission denied, API failure shown inline) — covered by `frontend/src/__tests__/ModelConfigDialog.test.tsx` (the dialog error pattern tests).
- **AC-7** (list endpoint returns all 12 providers correctly) — covered by `backend/tests/api/test_model_configs_api.py` (round-trip over the catalogue) and the list-page tests in `frontend/src/__tests__/ModelConfigListPage.test.tsx`.
- **AC-8** (edit dialog pre-population) — covered by `frontend/src/__tests__/ModelConfigDialog.test.tsx`.
- **AC-9** (parent table refresh after save) — covered by `frontend/src/__tests__/ModelConfigListPage.test.tsx` and the E2E flow.
- **AC-10** (provider-type change on update) — covered by `backend/tests/api/test_model_configs_api.py` (PUT with `provider_type` change) and the dialog tests.
- **AC-11** (delete confirmation, row removed on confirm) — covered by `frontend/src/__tests__/ModelConfigListPage.test.tsx` and the E2E flow.
- **AC-12** (delete blocked by referencing AgentType) — covered by `backend/tests/api/test_model_configs_api.py` (409) and `backend/tests/unit/test_model_config_service.py`.
- **AC-13** (recreate after delete) — covered by the E2E flow and the recreate test in `frontend/src/__tests__/ModelConfigDialog.test.tsx`.
- **AC-14** (disable / enable toggle works for new providers) — covered by the disable / enable test in `backend/tests/api/test_model_configs_api.py` and the E2E flow.
- **AC-15** (parent table refresh after dialog close) — covered by `frontend/src/__tests__/ModelConfigListPage.test.tsx` and the E2E flow.

### C. Runtime Dispatch

- **AC-16** (correct vendor dispatch, credential attached) — covered by the per-provider dispatch tests in `backend/tests/unit/test_model_binding.py` and the integration test in `e2e/tests/agent-runtime.spec.ts` `Model Configurations` block (real-backend variant) for the round-trip.
- **AC-17** (text and tool-call outcomes consistent with vendor) — covered by the extractor tests in `backend/tests/unit/test_model_binding.py` for Gemini and Cohere response envelopes.
- **AC-18** (usage captured or null-on-unavailable) — covered by the `extract_usage` tests in `backend/tests/unit/test_model_binding.py`.
- **AC-19** (4xx / 5xx error log contains provider key) — covered by the single regression test in `backend/tests/unit/test_model_binding.py` that iterates over all 12 provider keys.

### D. Model Listing ("Fetch Models") Per Provider

- **AC-20** (non-empty list for every provider) — covered by the per-provider list-models tests in `backend/tests/unit/test_model_config_service.py` and `backend/tests/api/test_model_configs_api.py`.
- **AC-21** (curated list up to date) — covered by a manual review at release time and the curated-list test in `backend/tests/unit/test_model_config_service.py` (asserts non-empty, sorted).
- **AC-22** (graceful degradation on failure) — covered by the failure-path tests in `backend/tests/unit/test_model_config_service.py` and the dialog's fetch-models failure test in `frontend/src/__tests__/ModelConfigDialog.test.tsx`.

### E. Security, Encryption, and Audit

- **AC-23** (AES-256 encryption; `has_credentials` is the only credential-derived field) — covered by the create / update tests in `backend/tests/unit/test_model_config_service.py` and the AES-256 round-trip test.
- **AC-24** (placeholder semantics on edit) — covered by the edit-mode tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and the update tests in `backend/tests/unit/test_model_config_service.py`.
- **AC-25** (OpenTelemetry attributes for inference calls) — covered by the observability test in `backend/tests/unit/test_model_binding.py`.

### F. Internationalisation

- **AC-26** (i18n label for each new provider) — covered by the dropdown tests in `frontend/src/__tests__/ModelConfigDialog.test.tsx` and the list-page tests.

### G. Test Coverage

- **AC-27** (per-provider backend unit tests) — covered by `backend/tests/unit/test_model_config_service.py` and `backend/tests/unit/test_model_binding.py` (one dedicated test case per provider).
- **AC-28** (full 12-provider backend API tests) — covered by `backend/tests/api/test_model_configs_api.py`.
- **AC-29** (frontend unit tests for the 12 providers) — covered by `frontend/src/__tests__/ModelConfigDialog.test.tsx` and `frontend/src/__tests__/ModelConfigListPage.test.tsx`.
- **AC-30** (E2E for the new providers, with a real-backend variant) — covered by `e2e/tests/agent-runtime.spec.ts` in the `Model Configurations` block, which contains both the mocked variant and the `Real Backend Integration - Model Configurations` variant per the change-lifecycle skill's database-change rule.

## 6) Test File References

Test paths below are taken from `docs/config.yaml` `source.tests`.

| File | Type | Owner | Purpose |
|------|------|-------|---------|
| `backend/tests/unit/test_model_config_service.py` | unit | extend | Per-provider CRUD lifecycle with AES-256 encryption, list-models per provider, failure-path coverage. |
| `backend/tests/unit/test_model_binding.py` | unit | extend | Per-provider resolve and dispatch, extractor widening for Gemini / Cohere, 4xx / 5xx log assertion across all 12 providers, unknown-provider rejection, observability attributes. |
| `backend/tests/api/test_model_configs_api.py` | API | extend | Round-trip over the 12-provider catalogue, provider-type change on update, delete safety guard, list-models endpoint coverage, permission rules. |
| `backend/tests/db/test_model_provider_enum_migration.py` | DB integration | new | Real-database assertions: enum has 12 values, `information_schema` column properties, type not recreated, pre-existing rows preserved, migration idempotency, no `UNIQUE` / `CHECK` constraint regression. |
| `frontend/src/__tests__/ModelConfigDialog.test.tsx` | unit | extend | Dropdown lists 12 providers, create / edit / delete flows reload-free, edit pre-population, dialog error pattern for each new provider, placeholder semantics, recreate after delete. |
| `frontend/src/__tests__/ModelConfigListPage.test.tsx` | unit | extend | Chip rendering for all 12 providers, chip-colour-uniqueness machine-check, parent table refresh after dialog close, delete confirmation, reload-free behaviour. |
| `e2e/tests/agent-runtime.spec.ts` | E2E | extend | New `Model Configurations` block: list page renders chips for all 12 providers, create dialog accepts a new provider, edit dialog saves, delete dialog removes, reload-free. Includes the `Real Backend Integration - Model Configurations` variant per the change-lifecycle skill's database-change rule (no `page.route()` mocks, real backend hit, real DB exercised). |

### Cross-layer summary

- **Backend unit**: 2 extended files (`test_model_config_service.py`, `test_model_binding.py`).
- **Backend API**: 1 extended file (`test_model_configs_api.py`).
- **Backend DB integration**: 1 new file (`test_model_provider_enum_migration.py`).
- **Frontend unit**: 2 extended files (`ModelConfigDialog.test.tsx`, `ModelConfigListPage.test.tsx`).
- **E2E**: 1 extended file (`agent-runtime.spec.ts`) with a new `Model Configurations` block and a `Real Backend Integration - Model Configurations` variant.

No changes are required in `mcp-demo-app/tests/` for this change.
