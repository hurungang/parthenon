# Test Plan: System One Decision Skills

## 1. Test Strategy

- **Unit tests (backend)** — Pure-logic validation: per-question-type rules (Choice/Score/Noul), state preset mapping, confidence gate computation, provider resolution. Fast, no DB.
- **Backend integration tests** — Real PostgreSQL via test fixtures; migration application (`alembic upgrade head`) in setup; API route behavior with JWT/permission checks; encrypted key storage verified at the DB level; execution engine with mocked TypeSafe transport (injected client) plus persisted `DecisionExecutionResult`.
- **Frontend unit/component tests (Vitest)** — Provider config form (write-only key, dialog error handling), skill editor decision flow (configured-model gate, question builder per type, thresholds), decision results view rendering.
- **E2E tests (Playwright)** — Mocked variants for authoring/execution flows; **one real-backend variant** (no mocks) exercising the actual API, DB, migration, and permission enforcement.
- **Manual testing** — Against live TypeSafe Jev API (`jev-latest`): real key round-trip, actual structured answers, confidence values plausibility. Verify i18n coverage of all new UI strings.

## 2. Coverage Areas

- **Provider config CRUD + encrypted key storage** — Critical: credentials must never leak. Verify create/read/update/delete via API, key encrypted at rest (ciphertext in DB column, not plaintext), key never returned by any response (list/detail), decryption only at call time via `CredentialVault`, and `system::system_one` permission enforcement on every provider route.
- **Decision skill authoring validation per question type** — Critical: malformed questions would produce invalid model evaluations. Choice requires non-empty options; Score requires an ordered legend; Noul carries no criteria; at least one question required; state preset mapping validated.
- **Authoring gate (configured-model check)** — Critical UX and data integrity: creating/updating a `decision` skill with no enabled System One model must be blocked with a clear structured error; allowed when a provider is configured.
- **Execution path** — Critical: correctness of the whole orchestration — skill resolution, state preset application to input/agent data, single dispatch of all questions, response normalization into typed answers (values, probabilities, confidence, legend).
- **Confidence gating** — Critical: automated action depends on it. confidence ≥ act → `act`; ≥ confirm → `confirm`; else `escalate`; boundaries tested at exact threshold values.
- **Permission / resource-type enforcement** — Critical: decision skills must flow through the existing skill permission path (role → skill grants); `system::system_one` must be registered in both backend and frontend manifests or ALL users (including wildcard admins) get 403. Unauthenticated access must fail on all new routes.
- **Migration** — Critical: schema must exist or everything fails at runtime. Verify tables (`system_one_provider_configs`, decision definition/question/result tables) and `skill_type` discriminator column exist post-migration, defaults applied to existing rows (`tool_based`), constraints enforced, and downgrade is reversible.
- **Routing boundaries (top-priority rules)** — Communication Hub forwards decision invocations without credentials; Agent Runtime receives structured results only; no agent-visible payload contains key material.

## 3. Critical Scenarios

- WHEN a platform admin creates a provider config with an API key, THEN the stored DB value is ciphertext, and no list/detail/status response contains the key or any reversible form.
- WHEN a provider config is updated with a new key, THEN the old ciphertext is replaced and the previous key no longer decrypts to anything used at call time.
- WHEN a provider config is deleted, THEN `GET /system-one/status` reports unconfigured and decision-skill authoring becomes blocked.
- WHEN a skill author selects the decision type with no enabled System One model, THEN the authoring flow is blocked with a clear message and no decision skill can be persisted.
- WHEN a skill author selects the decision type with a configured model, THEN the form proceeds and the definition form is driven by the configured model's API definition.
- WHEN a decision skill is created with zero questions, THEN creation is rejected with a validation error.
- WHEN a Choice question is saved with an empty options list, THEN validation fails; WHEN a Score question lacks an ordered legend, THEN validation fails; WHEN a Noul question has criteria attached, THEN validation fails.
- WHEN a decision skill is created with an invalid state preset mapping, THEN creation is rejected.
- WHEN a decision skill is executed with valid input, THEN one evaluation dispatch carries the constructed state plus ALL predefined questions, and the response contains a structured typed answer per question with probabilities and confidence.
- WHEN execution completes, THEN a `DecisionExecutionResult` row is persisted with state snapshot, per-question answers, gate outcome, status, and provider model, and is queryable via the decision results endpoint.
- WHEN confidence equals the act threshold exactly, THEN the outcome is `act`; WHEN confidence is between confirm and act, THEN `confirm`; WHEN below confirm, THEN `escalate`.
- WHEN an agent without a role grant to the decision skill invokes it, THEN the invocation is denied through the normal permission path (identical to tool-based skills).
- WHEN any user calls provider config routes without `system::system_one` permission, THEN access is denied; WHEN a wildcard-permission admin calls them, THEN access is allowed (manifest registered correctly).
- WHEN Communication Hub receives a decision-skill invocation, THEN it forwards to Control Center and its logs/payloads contain no API key material.
- WHEN the TypeSafe API returns a malformed or partial answer set, THEN execution fails gracefully with a logged error and no partially persisted result presented as successful.

## 4. Edge Cases & Risks

- **Migration not applied** — Tests pass against mocked backends while production DB lacks new tables; mitigated by real-backend tests and alembic in test setup (see Pre-Test Checklist).
- **Legacy skills after migration** — Existing `tool_based` skills must keep executing unchanged; verify defaulting of `skill_type` on pre-existing rows and that the executor's non-decision path is untouched.
- **Key update edge cases** — Empty key on update (must keep existing), whitespace key, update of non-key fields only must not touch stored ciphertext.
- **Threshold misconfiguration** — act threshold lower than confirm threshold; define and test validation or documented behavior.
- **Multiple provider rows** — Only one enabled provider should resolve for execution; behavior when several exist or when the enabled provider is deleted mid-flight.
- **Provider unavailable / network failure** — No LLM fallback (per out-of-scope); execution must fail with clear status, and results must not be persisted as successful.
- **State preset edge cases** — Missing input keys referenced by the mapping; agent data absent at execution time; empty state.
- **Question ordering** — Answers must map back to questions positionally/stably regardless of provider response ordering.
- **Confidence semantics** — Provider returning confidence outside expected range or missing per-question confidence.
- **Multi-tenancy** — Provider configs and results scoped to the correct tenant; cross-tenant reads denied.
- **i18n** — All new UI strings via `t()`; missing translation keys fail tests.
- **Risk: encrypted-key regression** — Any logging/serialization change could leak plaintext; integration tests assert ciphertext at rest and absence in responses/logs.

## 5. Acceptance Criteria Checklist

- [ ] Save, update, remove TypeSafe AI API key via UI and API; key encrypted at rest; never in plaintext in any UI or API response — _backend integration + frontend tests_
- [ ] Decision-type skill creation with no configured model: user clearly informed, cannot proceed — _frontend + backend tests_
- [ ] With model configured: form driven by configured model's API definition is shown — _frontend + E2E_
- [ ] Form supports one or more questions with type (Choice, Score, Noul), instructions, type-appropriate criteria/options, plus state preset — _backend validation + frontend component tests_
- [ ] Decision skills appear alongside existing skills: invocable, associable to agents/SOPs, grantable via roles — _backend integration + E2E_
- [ ] Execution sends state + all questions in a single evaluation; returns structured typed answers with probabilities and confidence — _backend integration (mocked transport) + real-backend E2E variant_
- [ ] Confidence exposed on every result; act/confirm/escalate threshold behavior works — _backend unit + integration tests_
- [ ] Executions logged and auditable like existing skill executions — _backend integration + results endpoint tests_
- [ ] Provider config model supports multiple providers; Jev/TypeSafe the only one initially — _backend integration tests (provider resolution)_
- [ ] Migration verified applied: schema columns/tables/constraints confirmed via `information_schema`, negative constraint tests pass — _backend integration tests_
- [ ] No agent or Communication Hub surface ever holds the API key (top-priority rule) — _backend integration tests_

## 6. Test File References

**Backend** (`backend/tests/`):
- `backend/tests/integration/test_system_one_decision_skills.py` — migration verification (`information_schema` checks, negative constraint tests), provider CRUD + encryption-at-rest, per-type question validation, authoring gate, execution engine + result persistence, permission enforcement, routing boundaries.
- `backend/tests/integration/test_system_one_provider_config.py` — provider config API routes, status endpoint, key write-only semantics.
- `backend/tests/unit/test_decision_engine.py` — confidence gate boundaries, state preset mapping, answer normalization.

**Frontend** (`frontend/src/__tests__/`):
- `frontend/src/__tests__/SystemOneProviderConfigPage.test.tsx` — write-only key field, dialog error handling, CRUD flows.
- `frontend/src/__tests__/DecisionSkillForm.test.tsx` — configured-model gate, question builder per type, thresholds, state preset mapper.
- `frontend/src/__tests__/DecisionQuestionEditor.test.tsx` — per-type editing validation (Choice/Score/Noul).
- `frontend/src/__tests__/DecisionResultView.test.tsx` — answers, probabilities, confidence, gate outcome rendering.

**E2E** (`e2e/tests/`):
- `e2e/tests/system-one-provider-config.spec.ts` — admin config flow (mocked backend).
- `e2e/tests/system-one-decision-skills.spec.ts` — authoring + execution flows (mocked backend).
- `e2e/tests/system-one-real-backend.spec.ts` — `test.describe('Real Backend Integration - Decision Skills')` — no mocks: create provider config and decision skill via real API, execute against real backend with injected/mock TypeSafe transport, verify 2xx responses, real DB persistence of results, permission enforcement, and migration-applied schema.

## Pre-Test Checklist (Database Changes)

- [ ] Run `python -m alembic current` — confirm the new `system_one_provider_configs` migration ID is applied.
- [ ] If not applied: `python -m alembic upgrade head`, then re-check `alembic current`.
- [ ] Backend integration test fixture applies migrations (`alembic upgrade head`) during setup, not model `create_all` only.
- [ ] Confirm test database schema matches production (tables, `skill_type` column with default, constraints).
- [ ] After applying migrations, restart backend services (ORM models cached at startup) — use `.\parthenon.ps1 restart -Services backend -Force`.
