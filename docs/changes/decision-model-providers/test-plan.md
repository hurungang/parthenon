# Test Plan — Decision Model Providers

Change: `decision-model-providers` · Owner: tester
Inputs: `prd.md`, `spec-change.md`, `architecture.md`, `data-model.md`, `tech-spec.md`

---

## 1. Test Strategy

- **Backend unit tests** — decision-engine model resolution, availability cascade logic, credential masking, migration helper idempotency.
- **Backend integration tests (real PostgreSQL)** — provider/model CRUD against the database, schema-change verification (constraints, uniqueness, FK blocking), guardrail/budget interception of decision executions, permission enforcement, migration backward-compat.
- **Frontend component tests** — settings page CRUD UX, dialog pre-population and error handling, enabled-model selector filtering, terminology sweep.
- **E2E tests** — full lifecycle flows; at least ONE real-backend variant (no route mocks) exercising provider creation against the live API + database.
- **Manual checks** — terminology sweep across exported reports/docs, connection-test against a real vendor.
- Pre-test gate for all layers: verify Alembic migration applied (`alembic current` shows the new revision); backend test fixtures must run `alembic upgrade head` in setup.

## 2. Coverage Areas

| Area | Why critical |
|---|---|
| Terminology rename sweep | "System One Providers" must not survive anywhere user-visible (nav, titles, dialogs, help, notifications, i18n resources); internal identifiers must remain unchanged to limit breakage |
| Multi-vendor provider CRUD | Core epic value; encryption, uniqueness, referential-integrity deletion blocking |
| Per-model enable/disable + vendor cascade | Controls exactly which models are usable; mirrors Model Configurations semantics (manual vs vendor_cascaded disable reasons) |
| Decision tool model selection | Tools must only select enabled models; execution must resolve and record provider/model identity |
| Guardrail & budget enforcement on decision executions | Zero ungoverned spend; decision calls must hit the same pre-call checks and metering as regular model calls |
| Migration / backward compat | Existing single System One provider row and existing tools must survive upgrade with no data loss or credential re-entry; migration must be idempotent |
| Permission checks | Provider management restricted to administrators with the settings permission; agent-instance certs blocked from admin endpoints |
| Credential security | Credentials encrypted at rest, never returned on read, decrypted only at call time in Control Center |
| Schema changes | Migration applied; new availability entity, tool→model reference, retired `provider_model` field verified against real DB |

## 3. Critical Scenarios

### Migration & Backward Compat
- WHEN the migration runs against a database containing the legacy single System One provider config, THEN the row is transformed 1:1 into a Decision Model Provider with display name, endpoint, encrypted credential, and `default_model` preserved — no data loss, no credential re-entry required.
- WHEN the migration runs twice (re-run / crash-recovery), THEN the outcome is identical and no duplicate providers or availability rows are created (idempotency).
- WHEN an existing decision tool authored pre-upgrade evaluates after upgrade, THEN it resolves successfully to the migrated provider/model and returns a correct result.
- WHEN the migration runs on an empty/legacy-schema database, THEN it completes without error (handles missing/NULL legacy fields).

### Provider CRUD (multi-vendor)
- WHEN an admin creates a provider (vendor type, display name, endpoint, credentials), THEN it appears immediately in the providers table without page reload, with vendor chip and credentials-set indicator correct.
- WHEN the admin edits a provider, THEN the dialog is pre-populated with current values and the table refreshes automatically on save.
- WHEN the credential field is left as placeholder on edit, THEN the stored credential is unchanged; WHEN a new value is entered it replaces the old; WHEN explicitly cleared it is removed.
- WHEN a provider still referenced by decision tools is deleted, THEN deletion is blocked with an error naming the blocking references.
- WHEN a provider with no references is deleted, THEN it disappears immediately and a new provider with the same display name/vendor can be created (proves true deletion).
- WHEN a duplicate display name within the same vendor type (or duplicate vendor registration) is submitted, THEN it is rejected with a clear user-friendly error.
- WHEN required fields are missing or the API returns an error (e.g., 403), THEN a visible error appears inside the dialog — no silent failure.
- WHEN any provider read endpoint is called, THEN the response never contains the credential (plaintext or ciphertext).

### Model Management
- WHEN an individual model toggle is flipped, THEN the change takes effect immediately for decision-tool authoring with no reload.
- WHEN a provider-level enable/disable is applied, THEN all its models cascade accordingly while previously manually-disabled models retain `manual` disable reason after re-enable.
- WHEN a model referenced by an existing decision tool becomes disabled, THEN that tool's next evaluation is blocked with a clear, actionable error (no silent vendor fallback).

### Decision Tool Model Selection
- WHEN authoring or re-configuring a decision tool, THEN the model selector lists only enabled models across all enabled providers.
- WHEN a tool is saved with a selected model, THEN the detail/list view displays it and the next evaluation uses it — no restart or re-deploy.
- WHEN a decision evaluation completes, THEN the execution record/log identifies the provider and model used.

### Guardrails & Budget
- WHEN a decision evaluation would violate a configured content/safety guardrail, THEN it is blocked pre-vendor-call with the same user-visible outcome and audit trail as regular model usage.
- WHEN the budget/spend limit is exhausted, THEN the decision evaluation is blocked pre-vendor-call and no vendor call is made.
- WHEN a decision evaluation succeeds, THEN usage is metered into the same spend store and appears in usage/spend reporting alongside regular agent model usage.

### Permissions
- WHEN a user without the provider-management permission attempts any provider CRUD API call, THEN it is rejected 403.
- WHEN a user lacking permission opens the settings page, THEN management actions are unavailable/denied without crashing the page.
- WHEN an agent-instance certificate calls internal decision endpoints, THEN it gets only execution-scope access and can never retrieve provider configuration or credentials.

### Terminology
- WHEN the UI is loaded (navigation, settings page, create/edit dialogs, help text, notifications), THEN no occurrence of "System One Provider(s)" remains user-visible; all strings route through i18n `t()`.
- WHEN internal APIs/tables are inspected, THEN internal identifiers remain unchanged (rename is presentation-layer only).

## 4. E2E User Journeys (planning)

Step-by-step user journeys through the UI. Each feature gets a happy-path, an error/edge-case, and a journey-level scenario with exact titles suitable for Playwright test names.

> **Implementation deviation (from developer report):** decision usage plus provider/model identity is metered into the persisted `DecisionExecutionResult` (`answers.provider`, plus the `provider_model` column), **not** into the AgentJob-derived ModelUsagePosture store. Budget/usage E2E assertions verify that usage and provider/model identity are recorded on the execution result. The posture-store rollup gap is a **known limitation** — verify manually whether decision usage appears in aggregated posture/spend reporting views; do not automate that assertion.

### 4.1 Feature 1 — Terminology Rename

**User journey:** Admin signs in → opens navigation → navigates to the settings area → expects to find "Decision Model Providers" (not "System One Providers") in nav, page title, create/edit dialogs, help text, and toast notifications. After any CRUD action, notification copy must use the new term.

**E2E scenarios:**

1. **"Settings > navigation and page header show 'Decision Model Providers' with no trace of 'System One Providers'"**
   - Sign in as admin → open settings navigation → click the decision providers entry.
   - Assert nav label, page title, and any breadcrumb read "Decision Model Providers"; assert `page.getByText(/System One/i)` count is 0 across nav, header, and dialogs.
2. **"Settings > create dialog, help text, and error notification all use 'Decision Model Providers' terminology"**
   - Open the create provider dialog → check dialog title and inline help text.
   - Submit an invalid/duplicate provider to trigger an error toast/notification → assert the notification text uses "Decision Model Provider" and never "System One".
3. **"Settings > legacy 'System One Providers' string does not appear anywhere in the rendered settings app (sweep)"**
   - Crawl all reachable settings routes as admin; assert the legacy string never appears in rendered DOM (internal API paths/ids are exempt).

### 4.2 Feature 2 — Multi-Vendor Provider CRUD

**User journey:** Admin opens Decision Model Providers page → clicks create → selects vendor type, enters display name, endpoint, API key → saves → row appears in table without reload (vendor chip + credentials-set indicator). Admin edits the row (dialog pre-populated, credential shows placeholder) → saves → table updates. Admin deletes an unreferenced provider → confirm dialog → row disappears; recreates with same name to prove true deletion.

**E2E scenarios:**

1. **"Settings > admin creates a decision model provider and sees it appear without reload"**
   - Note initial row count → click Create → fill vendor type, display name `e2e-provider-<ts>`, endpoint, credential → save.
   - Assert dialog closes, table gains a row without page reload, vendor chip and credentials-set indicator correct, endpoint/name match what was typed.
2. **"Settings > editing a provider keeps stored credential when placeholder is left untouched"**
   - Edit the provider created above → assert dialog is pre-populated, credential field shows masked placeholder → change only the display name → save.
   - Assert table shows the new name without reload; then trigger a connection test / subsequent read and assert the credential still works (credentials-set indicator remains, no corruption). Edge: submitting the masked placeholder literally must not replace the stored secret.
3. **"Settings > admin cannot delete a provider referenced by a decision tool and duplicate names are rejected"**
   - Create provider → attach a decision tool selecting one of its models → attempt delete → assert confirmation followed by a visible error naming the blocking tool; row remains.
   - Then attempt to create a second provider with the same display name + vendor → assert clear user-friendly duplicate error inside the dialog.
4. **"Settings > admin deletes an unreferenced provider and can recreate the same name afterwards"**
   - Delete an unreferenced provider → confirm → assert row removed from table immediately → create a new provider with the identical display name and vendor → assert it succeeds (proves true deletion, not soft-hide).

### 4.3 Feature 3 — Per-Model Enable/Disable + Vendor Cascade

**User journey:** Admin opens a provider's model catalogue → toggles one model off → toggle reflects immediately. Toggles the provider-level enable control off → all model toggles show disabled (cascaded). Re-enables the vendor → previously manually-disabled model stays disabled (manual reason preserved), others re-enabled.

**E2E scenarios:**

1. **"Settings > disabling a model removes it from the decision tool model selector without reload"**
   - Open decision tool authoring form → note the target model present in selector → in another tab/context disable the model → reopen/refresh the selector.
   - Assert the disabled model no longer appears as an option; enabled models across all providers still listed.
2. **"Settings > vendor-level disable cascades to all models and re-enable preserves manual disables"**
   - Manually disable model A; leave model B enabled → flip vendor-level toggle off → assert both A and B show disabled with cascaded indication.
   - Flip vendor toggle back on → assert B is enabled again but A remains disabled (manual disable reason preserved).
3. **"Settings > decision tool referencing a since-disabled model is blocked with an actionable error on next evaluation"**
   - Save a decision tool referencing model M → disable M → run the tool's evaluation (agent run / test-evaluation UI).
   - Assert evaluation fails with a clear error naming the disabled model/provider — no silent vendor fallback, no crash.

### 4.4 Feature 4 — Per-Decision-Tool Model Selection

**User journey:** Author opens decision tool creation → model selector lists only enabled models across all providers → selects one → saves → detail/list view shows the chosen model. Edits the tool, switches to a different enabled model → saves → next evaluation uses the new model without restart/re-deploy; execution record shows the new provider/model.

**E2E scenarios:**

1. **"Decision tools > author selects an enabled model and sees it on the tool detail and list views"**
   - Create/edit a decision tool → assert selector contains only enabled models → pick model M (provider P) → save.
   - Assert detail view and list row display "P / M" (or equivalent) immediately.
2. **"Decision tools > changing the selected model takes effect on the next evaluation without restart"**
   - With tool evaluating against model M1 and a working backend, change selection to M2 → save → trigger an evaluation.
   - Assert the execution result records provider/model identity for M2 (e.g., `answers.provider` on `DecisionExecutionResult`) — no restart or redeploy step performed.
3. **"Decision tools > selector never offers disabled models from any provider"**
   - Disable at least one model in each of two providers → open the tool's model selector → assert disabled models absent from all providers' entries; assert a tool saved earlier with a now-disabled model still displays it (or a clear 'unavailable' state) rather than silently switching.

### 4.5 Feature 5 — Guardrail/Budget Enforcement on Decision Evaluations

**User journey:** Compliance owner configures a content guardrail and a low spend budget. A decision tool evaluation that would violate the guardrail is blocked pre-vendor-call with the same user-visible outcome as regular model usage. An evaluation attempted after budget exhaustion is blocked; successful evaluations record usage + provider/model on the persisted execution result.

**E2E scenarios:**

1. **"Decision tools > evaluation violating a content guardrail is blocked with the same outcome as regular model usage"**
   - Configure a guardrail that trips on known content → run a decision evaluation with that content → assert the evaluation is blocked with the standard guardrail-blocked UI outcome and an audit trail entry; assert no vendor result is returned.
2. **"Decision tools > exhausted budget blocks decision evaluation before the vendor call"**
   - Reduce budget/spend limit below what a decision evaluation would consume (or exhaust it via prior runs) → trigger a decision evaluation → assert blocked with the budget-exhausted outcome; assert no new usage recorded for the blocked attempt.
3. **"Decision tools > successful evaluation records usage and provider/model identity on the execution result"**
   - Run a successful decision evaluation → open the execution/decision result view (or read persisted `DecisionExecutionResult` via the UI's execution details).
   - Assert usage is recorded on the execution result and `answers.provider` identifies the correct provider and model used.
   - **Known limitation (manual check):** the AgentJob-derived ModelUsagePosture rollup may not include decision usage — verify manually whether aggregated usage/spend reporting shows decision calls; do not automate this assertion until the rollup gap is resolved.

## 5. Edge Cases & Risks

- **Migration not applied** — mocked tests pass while the real DB lacks the new schema; mitigated by the mandatory real-backend E2E test and schema-verification integration tests.
- **Cascade wiping manual disables** — vendor re-enable could incorrectly reset `manual` disable reasons.
- **Stale model selector data** — authoring UI may cache an enabled-model list that has since changed; a saved tool referencing a since-disabled model must fail safely at evaluation time.
- **Uniqueness scope confusion** — duplicate display names must be rejected per vendor type, not globally (or per current spec decision); test both same-vendor duplicate (rejected) and different-vendor same name (allowed if spec allows).
- **Credential round-trip** — masked placeholder accidentally submitted as a new value would corrupt the stored secret.
- **Concurrent edits** — two admins toggling availability simultaneously; last-write wins must not corrupt cascade state.
- **Vendor-outage during connection test / evaluation** — timeouts must surface actionable errors, not hang or partially meter usage.
- **Legacy `provider_model` free-text values** — tools with non-default legacy values must map correctly during migration (or surface a clear migration warning).
- **Multi-tenancy** — provider rows are tenant-scoped; one tenant must never see or select another tenant's providers/models.
- **Budget race** — concurrent decision evaluations must not exceed the spend limit via a check-then-spend gap.

## 6. Acceptance Criteria Checklist (maps to PRD)

| PRD criterion | Covered by |
|---|---|
| Provider create dialog → appears in table immediately, fields correct | Provider CRUD scenarios; frontend + E2E tests |
| Edit dialog pre-populated; table auto-refreshes on save | Provider CRUD scenarios; frontend tests |
| Credential placeholder/new/clear semantics on edit | Provider CRUD scenarios; backend integration test |
| Delete confirmation; referenced provider blocked with named references; same-name recreate after delete | Provider CRUD scenarios; backend negative constraint tests |
| Duplicate name / duplicate vendor rejected; required-field & dialog error surfacing | Provider CRUD scenarios; frontend tests |
| Per-model toggles effective immediately; vendor-level cascade | Model management scenarios; backend integration tests |
| Disabled models hidden from authoring selector; existing tools blocked with actionable error | Model selection scenarios; backend + E2E |
| Selector shows only enabled models; selection shown on detail/list; evaluation records provider/model | Model selection scenarios |
| Model change effective next evaluation, no restart | Model selection scenarios; E2E |
| Guardrails applied to every decision evaluation | Guardrail scenarios; backend integration tests |
| Decision usage metered against shared budget; exhausted budget blocks; usage + provider/model identity persisted on the execution result (posture-reporting rollup pending — known limitation, manual check) | Budget scenarios; backend integration tests |
| "System One Providers" renamed everywhere; internal identifiers unchanged | Terminology scenarios; frontend tests + manual sweep |
| Legacy config migrated 1:1, editable, credentials preserved; existing tools keep working | Migration scenarios; backend integration + real-backend E2E |
| Schema changes verified against real DB (migration applied, constraints, FK blocking) | Schema verification tests (see Coverage Areas / Section 4) |
| Permission checks on settings page and APIs | Permission scenarios |

## 7. Test File References

Backend (backend/tests/):
- `backend/tests/unit/test_decision_engine.py` — multi-provider model resolution, disabled-model blocking, credential masking (41 tests, passing)
- `backend/tests/unit/test_system_one_client.py` — per-provider client factory generalisation incl. unknown-provider-type rejection (passing)
- `backend/tests/integration/test_decision_providers_crud.py` — provider CRUD, uniqueness, FK deletion blocking, credential masking, permissions (passing)
- `backend/tests/integration/test_decision_model_availability.py` — per-model toggles, vendor cascade, disable-reason preservation (passing)
- `backend/tests/integration/test_decision_providers_schema.py` — schema verification: migration `8144e472dce9` applied, uniqueness constraints, negative constraint tests, legacy backward compat (passing)
- `backend/tests/integration/test_system_one_decision_tools.py` — migration/backward-compat, per-tool model selection (passing)
- `backend/tests/integration/test_decision_tool_full_journey.py` — guardrail/budget enforcement on decision executions, usage metering (passing)

Frontend (frontend/src/__tests__/):
- `frontend/src/__tests__/DecisionToolForm.test.tsx` — enabled-model selector filtering (passing)
- `frontend/src/__tests__/DecisionModelProvidersPage.test.tsx` — settings page CRUD, dialog errors, terminology sweep incl. en.json (passing)
- `frontend/src/__tests__/DecisionToolsPage.test.tsx` — tool list/authoring gate (passing)
- Note: `AppShell.tenantAdmin.test.tsx` has one PRE-EXISTING failure (fails on a clean tree; unrelated to this change).

E2E (e2e/tests/):
- `e2e/tests/system-one-decision-tools.spec.ts` — 15 tests, all passing (`Decision Model Providers (mocked)` + legacy mocked journeys). Mocked E2E coverage of Section 4: 4.1.1 (nav/header terminology + DOM sweep on settings page), 4.1.2 (duplicate-name error terminology inside dialog), 4.2.1 (create appears without reload), 4.2.2 (edit pre-population, credential-unchanged placeholder semantics — asserts PATCH payload excludes api_key), 4.2.3 (referenced-provider delete blocked, error inside dialog), 4.2.4 (delete unreferenced + same-name recreate), 4.3.1 (disabled model removed from tool selector), 4.3.2 (vendor cascade + per-model toggle API calls), 4.4.1/4.4.3 (selector lists only enabled models, submits availability id)
- `e2e/tests/decision-model-providers-real-backend.spec.ts` — `test.describe('Real Backend Integration - Decision Model Providers')`: multi-provider CRUD, availability cascade, delete blocking, DB persistence against the live API + database (passing with app + PostgreSQL running)
- Not automated (by design): 4.1.3 full settings-route crawl sweep (manual), 4.3.3 / 4.4.2 real evaluation flows (covered by backend integration tests), 4.5.x guardrail/budget E2E (covered by `test_decision_tool_full_journey.py`; posture-rollup reporting remains a manual check per the Section 4 implementation note).
