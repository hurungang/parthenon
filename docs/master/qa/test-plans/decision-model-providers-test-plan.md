# Decision Model Providers Test Plan

> Added by change `decision-model-providers`. Complements `decision-tools-test-plan.md` (tenant-isolation coverage of decision tools lives there).

## What to Test

- **Multi-vendor provider CRUD** — create/edit/delete Decision Model Providers (vendor type, display name, endpoint, credentials); table refreshes without reload; duplicate display name per vendor rejected; providers referenced by decision tools cannot be deleted; unreferenced providers delete cleanly (same-name recreate proves true deletion); credentials never returned by any read endpoint.
- **Per-model enable/disable + vendor cascade** — per-model toggles effective immediately; vendor-level enable/disable cascades while previously manually-disabled models retain their `manual` disable reason; disabled models blocked at evaluation with an actionable error (no silent vendor fallback).
- **Per-decision-tool model selection** — authoring selector lists only enabled models across all enabled providers; selection shown on detail/list views; evaluation resolves and records provider/model identity on the persisted `DecisionExecutionResult`; model change takes effect on the next evaluation without restart.
- **Guardrail & budget enforcement on decision executions** — content guardrails and exhausted budgets block decision evaluations pre-vendor-call with the same outcomes/audit trail as regular model usage; successful evaluations are metered (usage + provider/model identity recorded on the execution result). Known limitation: ModelUsagePosture rollup of decision usage is a manual check, not automated.
- **Migration & backward compat** — legacy single System One provider row migrated 1:1 (display name, endpoint, encrypted credential, default model preserved); migration idempotent; pre-upgrade decision tools keep working; existing tests confirm legacy `provider_model` handling.
- **Schema verification** — migration `8144e472dce9` applied; uniqueness constraints; FK deletion blocking verified against real PostgreSQL with negative tests.
- **Permissions & credential security** — provider CRUD restricted to settings-permission admins (403 otherwise); agent-instance certificates get execution scope only, never provider configuration/credentials.
- **Terminology rename** — "System One Providers" absent from all user-visible UI (nav, titles, dialogs, help, notifications, i18n resources); internal identifiers unchanged.

## Test File References (verified present)

Backend:
- `backend/tests/api/v1/test_system_one_vendor_models.py` — vendor model catalogue endpoints
- `backend/tests/api/v1/test_system_one_api.py` — provider API endpoints
- `backend/tests/integration/test_decision_providers_crud.py` — provider CRUD, uniqueness, FK delete blocking, credential masking, permissions
- `backend/tests/integration/test_decision_model_availability.py` — per-model toggles, vendor cascade, disable-reason preservation
- `backend/tests/integration/test_decision_providers_schema.py` — schema verification vs real DB, constraints, backward compat
- `backend/tests/integration/test_decision_guardrails.py` — guardrail/budget interception of decision executions
- `backend/tests/integration/test_system_one_decision_tools.py` — migration/backward-compat, per-tool model selection
- `backend/tests/integration/test_decision_tool_full_journey.py` — full decision journey incl. guardrail/budget metering
- `backend/tests/unit/test_decision_engine.py` — multi-provider model resolution, disabled-model blocking, credential masking
- `backend/tests/unit/test_system_one_client.py` — per-provider client factory

Frontend (`frontend/src/__tests__/`):
- `DecisionModelProvidersPage.test.tsx` — settings page CRUD, dialog errors, terminology sweep (incl. en.json)
- `DecisionToolForm.test.tsx` — enabled-model selector filtering
- `DecisionToolsPage.test.tsx`, `DecisionResultView.test.tsx`, `DecisionToolQuestionEditor.test.tsx`, `decisionStatePaths.test.ts` — supporting coverage

E2E (`e2e/tests/`):
- `system-one-decision-tools.spec.ts` — mocked journeys: terminology (nav/header sweep), provider CRUD (create without reload, edit pre-population + credential-placeholder semantics, referenced-delete blocked, duplicate rejection, delete + same-name recreate), model selector filtering, delete-blocked errors; `Decision Model Providers (mocked)` describe block plus legacy mocked journeys
- `decision-model-providers-real-backend.spec.ts` — `Real Backend Integration - Decision Model Providers > multi-provider CRUD, availability cascade, delete blocking, DB persistence` (no mocks; requires running app + PostgreSQL; catches unapplied migrations)

E2E not automated by design: full settings-route terminology crawl (manual), real evaluation guardrail/budget flows (covered by backend integration suites), posture-rollup reporting (manual check).

## Pre-Test Gate

- Alembic migration applied (`alembic current` shows `8144e472dce9`); backend fixtures run `alembic upgrade head` in setup.
- Real-backend E2E requires the live stack running (`parthenon.ps1 start`) with PostgreSQL healthy.
- Pre-existing, unrelated failure: `AppShell.tenantAdmin.test.tsx` fails on a clean tree.
