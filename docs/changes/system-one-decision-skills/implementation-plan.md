# Implementation Plan: system-one-decision-skills

## Overview

This plan implements the System One decision skill capability: a new `decision` skill type that executes a predefined typed question set (Choice / Score / Noul) against the TypeSafe Jev API instead of running LLM tool calls. Work spans new DB entities + migration, an encrypted System One provider configuration, a decision execution engine in Control Center, integration into the existing skill execution and Communication Hub routing paths, frontend authoring/config/results UI, and full test coverage including migration verification and one real-backend e2e variant.

## Task Checklist

### Phase 1 — DB Models + Alembic Migration
- [ ] 1.1 — Add `skill_type` discriminator to the Skill model
- [ ] 1.2 — Add SystemOneProviderConfig model
- [ ] 1.3 — Add DecisionSkillDefinition and DecisionQuestion models
- [ ] 1.4 — Add DecisionExecutionResult model
- [ ] 1.5 — Generate and apply Alembic autogenerate migration
- [ ] 1.6 — Add Pydantic schemas for decision skill payloads

### Phase 2 — System One Provider Config (Backend)
- [ ] 2.1 — Provider config service with AES-256 encrypted API key
- [ ] 2.2 — Provider config REST API (write-only key, status endpoint)
- [ ] 2.3 — Register `system::system_one` resource type in backend manifest

### Phase 3 — Decision Skill Definitions (Backend)
- [ ] 3.1 — Decision skill definition CRUD service
- [ ] 3.2 — Question/state-preset validation logic
- [ ] 3.3 — Wire decision skill type into skills API with configured-model gate

### Phase 4 — TypeSafe Client + Decision Execution Engine (Control Center)
- [ ] 4.1 — Provider-agnostic System One client interface + TypeSafe/Jev implementation
- [ ] 4.2 — Decision execution engine (state build, dispatch, response parse)
- [ ] 4.3 — Confidence gating (act / confirm / escalate)
- [ ] 4.4 — Decision result persistence and query endpoints

### Phase 5 — Skill Execution Integration
- [ ] 5.1 — Route `decision` skill type in the Control Center skill executor
- [ ] 5.2 — Communication Hub routing for decision skill invocations
- [ ] 5.3 — Register decision skill resource type and verify permission resolution

### Phase 6 — Frontend
- [ ] 6.1 — System One provider config UI in System Config
- [ ] 6.2 — Skill editor decision-skill authoring form
- [ ] 6.3 — Decision results view in skill execution results
- [ ] 6.4 — i18n entries for all new UI text
- [ ] 6.5 — Mirror resource types in frontend resourceTypes.ts

### Phase 7 — Tests
- [ ] 7.1 — Backend integration tests incl. migration verification
- [ ] 7.2 — Frontend component tests
- [ ] 7.3 — E2E tests with one real-backend variant

## Phase 1 — DB Models + Alembic Migration

- [ ] 1.1 — Add `skill_type` discriminator to the Skill model — Add a `skill_type` enum column (`tool_based` | `decision`, default `tool_based`) to the Skill model in `backend/app/db/models/skills.py`. _Done when: model imports cleanly and existing skills default to `tool_based`._
- [ ] 1.2 — Add SystemOneProviderConfig model — New file `backend/app/db/models/system_one_provider_config.py` with provider_type enum, display_name, base_url, default_model, encrypted_api_key, enabled flag, enabled_models JSON, tenant scoping; register in `backend/app/db/models/__init__.py`. _Done when: model is importable and appears in Alembic autogenerate diff._
- [ ] 1.3 — Add DecisionSkillDefinition and DecisionQuestion models — New file `backend/app/db/models/decision_skills.py` with the one-to-one Skill specialization (state_preset JSON, act/confirm thresholds, is_active) and ordered child questions (question_key, question_type enum choice/score/noul, instructions, criteria_options JSON, is_required); unique constraint on skill_id; register in `__init__.py`. _Done when: models importable and relationships resolve._
- [ ] 1.4 — Add DecisionExecutionResult model — Add to `backend/app/db/models/results.py` (or new `decision_results.py`): tenant/skill/definition/session FKs, input_state_snapshot JSON, answers JSON, outcome enum act/confirm/escalate, status enum, provider_model, created_at. _Done when: model importable with all FKs._
- [ ] 1.5 — Generate and apply Alembic autogenerate migration — Run `python -m alembic revision --autogenerate -m "system one decision skills"` in `backend/`, review the generated file in `backend/alembic/versions/` (correct down_revision chain, `postgresql.ENUM(..., create_type=False)` for enums, reversible downgrade), then `python -m alembic upgrade head` and verify with `alembic current`. _Done when: migration applied; `alembic current` shows the new revision; backend restarts without errors._
- [ ] 1.6 — Add Pydantic schemas for decision skill payloads — New `backend/app/schemas/system_one.py` covering provider config DTOs (key write-only) and `backend/app/schemas/decision_skills.py` covering definition/question/result DTOs with per-type question validation models. _Done when: schemas importable and used by later-phase endpoints._

## Phase 2 — System One Provider Config (Backend)

- [ ] 2.1 — Provider config service with AES-256 encrypted API key — New `backend/app/services/system_one/provider_config_service.py` following the existing credential-vault pattern (`backend/app/core/credential_vault.py`): encrypt on write via `get_vault()`, decrypt only at call time, never return plaintext. Support listing enabled providers and resolving the active typesafe/jev-latest config. _Done when: service round-trips a key with only ciphertext stored; no method returns the plaintext key to callers outside execution._
- [ ] 2.2 — Provider config REST API (write-only key, status endpoint) — Extend `backend/app/api/v1/system_config.py` (or new `backend/app/api/v1/system_one.py` router) with CRUD endpoints plus a `GET .../status` used by the skill editor gating. API key accepted on create/update only; responses exclude it. JWT-protected with `system::system_one` permission checks. _Done when: CRUD works via API; any GET response contains no API key material; 403 without permission._
- [ ] 2.3 — Register `system::system_one` resource type in backend manifest — Add to `ResourceTypeManifest` with allowed actions and to the appropriate `MODULE_GROUPS` in `backend/app/core/resource_types.py`. _Done when: a user granted `system::system_one:*` passes `PermissionEngine.authorize()`; wildcard `system::*` covers it._

## Phase 3 — Decision Skill Definitions (Backend)

- [ ] 3.1 — Decision skill definition CRUD service — New `backend/app/services/system_one/decision_skill_service.py`: create/update/get/list/delete definitions joined to `decision`-type Skills, managing the ordered question children transactionally. _Done when: full CRUD round-trips definitions with questions; deleting a skill removes (or blocks per existing skill policy) its definition consistently._
- [ ] 3.2 — Question/state-preset validation logic — Validate each question by type: Choice requires a non-empty options list; Score requires an ordered rubric legend; Noul requires neither but rejects extraneous criteria. Validate state preset mappings reference known state fields. At least one question required. _Done when: invalid definitions are rejected with clear field-level errors; valid definitions of all three types pass._
- [ ] 3.3 — Wire decision skill type into skills API with configured-model gate — Extend `backend/app/api/v1/skills.py` and `backend/app/schemas/skills.py`: creating/updating a skill with `skill_type=decision` first checks provider config status and returns a structured "no System One model configured" error when absent; decision definitions exposed via skill detail payload. _Done when: decision skill creation blocked without config (clear error) and succeeds with config; existing tool-based skill flows unchanged._

## Phase 4 — TypeSafe Client + Decision Execution Engine (Control Center)

- [ ] 4.1 — Provider-agnostic System One client interface + TypeSafe/Jev implementation — New `backend/app/services/system_one/client.py`: abstract client interface; `TypeSafeJevClient` performing the authenticated POST to the provider base_url with state, model, and typed questions payload; key resolved via the provider config service at call time. _Done when: client builds the correct request for a sample definition and unit-testable without network (transport injected)._
- [ ] 4.2 — Decision execution engine (state build, dispatch, response parse) — New `backend/app/services/system_one/decision_engine.py`: resolve skill definition, apply the state preset to input/agent data, dispatch all questions in a single evaluation, normalize per-question typed answers (choice/score/noul, probabilities, confidence, legend), handle provider errors and timeouts. OTEL spans on the outbound call. _Done when: engine produces normalized answers for a mocked provider response and fails gracefully (failed result) on provider errors._
- [ ] 4.3 — Confidence gating (act / confirm / escalate) — Compute the gate from the definition's act/confirm thresholds against the response confidences: confidence >= act → `act`; >= confirm → `confirm`; else `escalate`. Gate outcome attached to the result. _Done when: unit tests cover all three gate outcomes and threshold boundaries._
- [ ] 4.4 — Decision result persistence and query endpoints — Persist each execution via the DecisionExecutionResult model (state snapshot, answers, gate, status, provider model); expose query endpoints filtered by skill, session, date range for the frontend results view. _Done when: executions are persisted and retrievable; results are browsable like existing skill executions._

## Phase 5 — Skill Execution Integration

- [ ] 5.1 — Route `decision` skill type in the Control Center skill executor — Extend `backend/app/services/skills/executor.py`: when the invoked skill has `skill_type=decision`, delegate to the decision execution engine instead of running MCP tool calls; structured result returned in the existing execution result shape. _Done when: invoking a decision skill through the existing skill execution path executes the engine and returns structured answers._
- [ ] 5.2 — Communication Hub routing for decision skill invocations — Extend the Communication Hub skill invocation broker (`backend/app/communication_hub/`) to recognize decision skills and forward to Control Center's decision execution path; CH holds no credentials and makes no external calls. _Done when: an invocation arriving at CH for a decision skill reaches CC and the structured result returns to the caller._
- [ ] 5.3 — Register decision skill resource type and verify permission resolution — Confirm decision skills are grantable via existing agent roles: permission resolution flows through the existing skill resource type unchanged; add decision skills to role-assignment selectors wherever skills are listed. _Done when: an agent role granting a decision skill allows invocation; ungranted invocation is denied 403; no parallel permission path added._

## Phase 6 — Frontend

- [ ] 6.1 — System One provider config UI in System Config — New section/component under `frontend/src/pages/system/` for managing the TypeSafe provider: display name, base URL, default model, enabled toggle, enabled models, and a write-only API key field (never populated on edit). API layer in `frontend/src/api/systemOneApi.ts`. Uses the standard dialog error handling pattern (`useDialogErrorHandler`). _Done when: admin can save/update/remove the key; no GET ever renders key material; permission-denied shows in-dialog._
- [ ] 6.2 — Skill editor decision-skill authoring form — Extend the skill editor under `frontend/src/pages/skills/` (and components under `frontend/src/components/` as needed): skill-type selector including `decision`; on selection, call the status endpoint and block with a clear message if no System One model is configured; otherwise render the question builder (Choice / Score / Noul typed fields with instructions and criteria/options) and the state preset mapper, plus act/confirm threshold inputs. _Done when: all three question types authorable; authoring blocked with clear message when unconfigured; form validates per type before submit._
- [ ] 6.3 — Decision results view in skill execution results — Extend results display (`frontend/src/pages/results/` area) to show per-question typed answers, probability distributions, confidence, and the gate outcome (act/confirm/escalate) for decision executions. _Done when: a decision execution's full structured result is visible and auditable in the UI._
- [ ] 6.4 — i18n entries for all new UI text — Add all new strings to the i18next resource files under `frontend/src/i18n/` for supported locales; no hardcoded strings in new components. _Done when: grep for new UI literals finds none outside i18n resources; UI renders translated text._
- [ ] 6.5 — Mirror resource types in frontend resourceTypes.ts — Add the `system::system_one` entry to `RESOURCE_TYPE_MANIFEST` and the matching `MODULE_GROUPS` submodule list in `frontend/src/constants/resourceTypes.ts`. _Done when: permission UI can grant `system::system_one` actions; no unknown-resource-type 403s for admins._

## Phase 7 — Tests

- [ ] 7.1 — Backend integration tests incl. migration verification — New tests under `backend/tests/` (e.g. `integration/test_system_one_decision_skills.py`): verify migration applied (`alembic current` shows the new revision in setup / apply `alembic upgrade head`), schema constraints (unique skill_id on definition, enum values, nullable rules via information_schema checks), provider config encryption-at-rest, question validation negatives, execution engine gating, and CH→CC routing with permission denial. _Done when: all backend tests pass against a migrated database; negative constraint tests fail as expected._
- [ ] 7.2 — Frontend component tests — Tests under `frontend/src/__tests__/` for the provider config form (write-only key, dialog error handling), decision authoring form (per-type validation, unconfigured gating), and results view rendering. Run via the JSON-reporter Vitest workflow. _Done when: all new frontend tests pass._
- [ ] 7.3 — E2E tests with one real-backend variant — Add E2E specs under `e2e/tests/`: mocked-route variants for authoring and executing a decision skill, plus one `Real Backend Integration - System One Decision Skills` variant that hits the real backend (provider config save → decision skill create → execute with a stubbed/mocked outbound TypeSafe call) and verifies real DB persistence of the result. _Done when: mocked variants and the real-backend variant both pass._

## Completion Checklist

- [ ] All phases 1–7 tasks checked off
- [ ] Alembic migration applied and verified (`alembic current` matches latest revision in `backend/alembic/versions/`)
- [ ] Resource types registered in both `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts`
- [ ] API key never returned in plaintext by any endpoint or UI state
- [ ] Only Control Center connects to the DB and calls the TypeSafe API; agents never receive the API key
- [ ] All UI text routed through i18next `t()`
- [ ] All dialogs use the standard dialog error handling pattern
- [ ] Backend integration, frontend, and e2e (incl. real-backend variant) tests all pass
- [ ] Backend services restarted after migration and code changes; no 500s in `backend/logs/`
- [ ] docs/config.yaml top-priority rules re-validated (service segregation unchanged)
