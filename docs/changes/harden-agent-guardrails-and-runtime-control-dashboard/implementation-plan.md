## Overview
This change hardens policy guardrails and runtime control across direct execution and delegated execution trees while preserving strict service segregation. The implementation introduces observe-only alert visibility, a running-agents topology dashboard, permission-gated node termination with cascade behavior, and recursion risk validation at create, update, and run entry points. The model-usage guardrail surface is being restructured from a flat per-model row with all four period columns baked in to a vendor → model → guardrail hierarchy with per-period guardrail rows, per-vendor and per-model disable toggles, and a pre-execution availability check performed by the Agent Runtime before dispatch. Delivery is phased to keep Control Center as the only database authority and Agent Runtime as the only execution boundary.

## Task Checklist
### Phase 1 — Architecture Baseline and Contracts
- [x] 1.1 — Lock service-boundary contracts for guardrails, topology, and termination
- [x] 1.2 — Define policy-event taxonomy for observe-only alerts, denials, and cascade outcomes
- [x] 1.3 — Define runtime topology projection contract for parent-child delegation trees
- [x] 1.4 — Define model-level usage limit schema and period-rollup projection contract

### Phase 2 — Recursion Risk Validation Hardening
- [x] 2.1 — Implement reusable recursion and dead-loop validation service for agent graph checks
- [x] 2.2 — Enforce recursion validation during agent create and update flows
- [x] 2.3 — Enforce recursion validation during run initiation flow before dispatch
- [x] 2.4 — Persist validation checks and findings for auditability

### Phase 3 — Guardrail and Termination Runtime Enforcement
- [x] 3.1 — Unify guardrail enforcement across parent and delegated execution paths
- [x] 3.2 — Emit observe-only threshold events as structured execution log entries
- [x] 3.3 — Implement node terminate orchestration with subtree cascade handling
- [x] 3.4 — Enforce permission-gated termination outcomes with explicit denial reasons
- [x] 3.5 — Change default guardrail enforcement mode from observe to terminate for new guardrails
- [x] 3.6 — Implement model-level usage guardrails with configurable hour/day/week/month limits  ⚠️ NEEDS REWORK — superseded by 3.7 (per-guardrail CRUD with one row per `(model, period)` and `(model_id, model_name, period)` uniqueness)
- [ ] 3.7 — Restructure model-usage guardrails to one `ModelGuardrailConfiguration` row per `(model, period)`, with `period`, `limit_value`, `unit`, `enforcement_posture`, and `is_active` per row; enforce a unique constraint on `(model_id, model_name, period)`; preserve `enforcement_posture` default of terminate; preserve `unit` default of `k`
- [ ] 3.8 — Add vendor-level `ModelConfig.is_disabled` toggle and cascade semantics: when set, every `ModelAvailability` row for the vendor is materialised with `is_disabled = true` and `disabled_reason = vendor_cascaded`; when the vendor is re-enabled, each row is restored to its prior manual state
- [ ] 3.9 — Add `ModelAvailability` entity (per-model enabled state with `disabled_reason` of `manual` or `vendor_cascaded`) and Control Center endpoint to toggle a single `(vendor, model_name)` row; the row is unique on `(vendor_model_config_id, model_name)`
- [ ] 3.10 — Add the Agent Runtime pre-execution availability check: before dispatching any run, Agent Runtime calls Control Center `POST /api/v1/agents/preflight/availability` for the resolved model; on denial, dispatch is blocked and a policy-block outcome (with `model_disabled` or `vendor_disabled` `AgentJob.termination_category`) is produced and surfaced in execution logs

### Phase 4 — Runtime Control Dashboard and Operator UX
- [x] 4.1 — Build running-agents dashboard view for active parent and delegated runs
- [x] 4.2 — Add live topology diagram view for execution tree relationships
- [x] 4.3 — Add per-node terminate interaction with permission-aware UI states
- [x] 4.4 — Surface observe-only limit alerts in execution logs using existing log viewer patterns
- [x] 4.5 — Surface model-usage posture and consumption visibility in the runtime dashboard  ⚠️ NEEDS REWORK — superseded by 4.6 (hierarchy-aware vendor → model → guardrail view) and 4.7 (inline add-guardrail form)
- [ ] 4.6 — Build `VendorModelGuardrailPanel` rendering the vendor → model → guardrail hierarchy on the runtime dashboard: vendor rows with enable/disable toggle and enabled-model count, expandable model rows with per-model enable/disable toggle and a "Vendor disabled" cascade source badge, and expandable per-guardrail rows with posture state, period, limit, unit, and per-guardrail edit/remove/enable controls
- [ ] 4.7 — Build inline `AddGuardrailForm` (no modal): a small form rendered inside the expanded model row that filters the period select to only periods not yet configured on that model, then dispatches one per-period create call; reuse the standard dialog error-handling pattern for API/permission failures

### Phase 5 — API, Data Model, and Integration Completion
- [x] 5.1 — Add or extend API routes for active topology, node termination, and policy outcomes
- [x] 5.2 — Extend schemas and models for guardrail events, run relationships, and termination outcomes
- [x] 5.3 — Ensure Control Center-only persistence and secure service-to-service data exchange
- [x] 5.4 — Add API routes and data models for model-level usage limits and period-rollup posture  ⚠️ NEEDS REWORK — superseded by 5.5 (schema migration to per-period rows + new `ModelAvailability` and `ModelConfig.is_disabled`) and 5.6 (new API surface for hierarchy, disable toggles, and preflight)
- [ ] 5.5 — Add a single Alembic migration that (a) restructures `model_guardrail_configurations` to per-period rows (drop `usage_limit_hour`/`usage_limit_day`/`usage_limit_week`/`usage_limit_month`, add `period` enum and `limit_value` int, add a unique constraint on `(model_id, model_name, period)`), (b) adds `is_disabled` boolean (default false) to `model_configs`, and (c) creates `model_availability` with `(vendor_model_config_id, model_name)` unique and the `disabled_reason` enum (`manual`, `vendor_cascaded`)
- [ ] 5.6 — Update the API surface: replace `POST /api/v1/agents/guardrails/model-usage-limits` and `PUT /api/v1/agents/guardrails/model-usage-limits/{id}` with the new per-guardrail shape (`model_id`, `model_name`, `period`, `limit_value`, `unit`, `enforcement_posture`, `is_active`); add `PUT /api/v1/agents/model-configs/{config_id}/disabled`, `PUT /api/v1/agents/model-configs/{config_id}/models/{model_name}/disabled`, `GET /api/v1/agents/model-availability`, and `POST /api/v1/agents/preflight/availability`

### Phase 6 — Verification, Observability, and Rollout Readiness
- [x] 6.1 — Add backend unit and integration tests for recursion validation and cascade termination
- [x] 6.2 — Add frontend tests for dashboard topology, permission gating, and alert rendering
- [x] 6.3 — Add end-to-end scenarios for dead-loop prevention and terminate cascade behavior
- [x] 6.4 — Finalize deployment and operations updates for monitoring and incident response
- [ ] 6.5 — Add real-database regression coverage for the rework: lifecycle test that exercises the new schema (per-period rows, `(model_id, model_name, period)` uniqueness, `ModelConfig.is_disabled`, `ModelAvailability` cascade), the new API surface, and the pre-execution availability contract (allow on enabled, deny on per-model disabled with reason `manual`, deny on cascaded vendor disable with reason `vendor_cascaded`); runs against the migrated real database to catch migration drift

## Phase 1
### Task 1.1 — Lock service-boundary contracts for guardrails, topology, and termination
Define authoritative ownership boundaries so runtime execution stays inside Agent Runtime, policy and persistence stay inside Control Center, and Communication Hub remains transport/orchestration only.
Done when:
- Service-level ownership is documented for each workflow: run validation, guardrail event handling, topology updates, and termination requests.
- No planned workflow requires Agent Runtime direct database access.
- No planned workflow requires agent identities to hold sensitive tokens or database credentials.

### Task 1.2 — Define policy-event taxonomy for observe-only alerts, denials, and cascade outcomes
Create a common event taxonomy so frontend logs and backend audit trails distinguish guardrail observation, policy denial, and functional failure.
Done when:
- Event categories and outcome types are defined for observe-only threshold reached, recursion blocked, terminate denied, and cascade completed/partial/failed.
- Event payload requirements include correlation identifiers and actor context.
- Taxonomy maps cleanly to frontend execution log rendering requirements.

### Task 1.3 — Define runtime topology projection contract for parent-child delegation trees
Define the shape and freshness requirements for active run topology projection consumed by the dashboard.
Done when:
- Parent-child edge semantics, root identification, depth, and node status fields are defined.
- Refresh/stream behavior for active topology updates is specified.
- Contract includes compatibility requirements for topology rendering in frontend.

### Task 1.4 — Define model-level usage limit schema and period-rollup projection contract
Define the data contract for model-specific usage limits and the period-rollup projection consumed by the runtime dashboard.
Done when:
- Period types (hour, day, week, month) and limit semantics are defined.
- Usage posture states (within_limit, approaching_limit, breached) are defined and mapped to operator-visible dashboard indicators.
- Projection contract specifies rollup source, staleness tolerance, and dashboard query access pattern.

## Phase 2
### Task 2.1 — Implement reusable recursion and dead-loop validation service for agent graph checks
Implement a centralized validation component that can evaluate SOP delegation graphs for cycles and dead-loop risk.
Done when:
- Validation service can return pass/fail plus structured findings with path signatures.
- Validation supports create, update, and run contexts.
- Validation output supports both strict-block and warn-only policy modes.

### Task 2.2 — Enforce recursion validation during agent create and update flows
Integrate validation into create and update endpoints before agent type persistence completes.
Done when:
- Invalid create/update submissions are blocked in strict mode with clear error responses.
- Validation findings are returned in user-consumable form.
- Successful writes include recorded validation check metadata.

### Task 2.3 — Enforce recursion validation during run initiation flow before dispatch
Integrate validation into the run entry path so recursion risk is blocked before a session is queued or executed. Recursion preflight was integrated in `launch_agent_session` (POST /api/v1/agents/sessions in backend/app/api/v1/agents.py) rather than the gateway init path.
Done when:
- Run initiation performs preflight recursion validation.
- Blocked runs return deterministic policy failure outcomes.
- No execution starts when recursion validation fails in strict mode.

### Task 2.4 — Persist validation checks and findings for auditability
Add model and persistence support for checks and findings to support compliance and operations review.
Done when:
- Validation check records store context, outcome, actor, and timestamp.
- Validation finding records store type, severity, involved SOP elements, and recommendation.
- Stored records are queryable for incident and compliance workflows.

## Phase 3
### Task 3.1 — Unify guardrail enforcement across parent and delegated execution paths
Apply the same guardrail contract to root and delegated runs so no bypass exists across delegation boundaries.
Done when:
- Guardrail enforcement logic is applied consistently regardless of delegation depth.
- Delegated steps inherit or resolve compatible guardrail policy snapshots.
- Regression checks confirm no parent/delegate enforcement divergence.

### Task 3.2 — Emit observe-only threshold events as structured execution log entries
When thresholds are reached under observe-only mode, emit explicit events for frontend visibility and audit differentiation.
Done when:
- Observe-only threshold events are emitted with structured payload data.
- Events are visible in execution logs without being misclassified as runtime errors.
- Event details include threshold and observed values.

### Task 3.3 — Implement node terminate orchestration with subtree cascade handling
Implement terminate orchestration so a selected node can be stopped, with optional/required cascade across descendants.
Done when:
- Parent-node termination stops all active delegated descendants in its subtree.
- Cascade outcomes are tracked per affected node.
- Partial completion and failure outcomes are captured and returned.

### Task 3.4 — Enforce permission-gated termination outcomes with explicit denial reasons
Apply authorization checks before termination and produce clear deny responses for unauthorized actors.
Done when:
- Terminate requests fail closed when permission is missing.
- Denials are returned to frontend with clear, user-visible reason text.
- Denials are logged as policy outcomes, not generic runtime failures.

### Task 3.5 — Change default guardrail enforcement mode from observe to terminate for new guardrails
Update the platform default so newly configured guardrails use terminate mode unless an authorized operator explicitly selects a different posture.
Done when:
- Default enforcement mode is terminate for all new guardrail configurations across create flows.
- Existing guardrail configurations retain their stored enforcement mode without forced migration.
- Admin UI reflects the new default clearly; observe-only posture remains selectable.

### Task 3.6 — Implement model-level usage guardrails with configurable hour/day/week/month limits  ⚠️ NEEDS REWORK
The original task built a flat per-model row with `usage_limit_hour`/`usage_limit_day`/`usage_limit_week`/`usage_limit_month` columns. That model is being replaced by a one-row-per-`(model, period)` shape (see 3.7), so the original work needs to be refactored: drop the four limit columns, replace them with a single `period` + `limit_value` pair, and rebuild the surrounding CRUD, posture evaluation, and dashboard reads against the new shape.
Done when (original scope, retained for traceability):
- Operators can configure upper limits per model for each period type independently.
- Usage is measured, rolled up to each configured period, and persisted in Control Center.
- Enforcement action (terminate or observe) aligns with the active enforcement mode for the guardrail.
- Period rollup values are available for dashboard posture display within acceptable staleness tolerance.

### Task 3.7 — Restructure model-usage guardrails to one row per `(model, period)`
Replace the flat per-model row with per-guardrail rows so a model can carry one to four guardrails, one per period, with its own enforcement posture and enable/disable toggle.
Done when:
- `ModelGuardrailConfiguration` has columns `model_id`, `model_name`, `period` (enum: `hour`/`day`/`week`/`month`), `limit_value` (int), `unit` (enum: `k`/`tokens`, default `k`), `enforcement_posture` (enum: `terminate`/`observe_only`, default `terminate`), `is_active` (boolean), `details` (json), and standard timestamps.
- A unique constraint on `(model_id, model_name, period)` prevents two guardrails on the same `(model, period)` pair.
- `ModelUsageGuardrailService` exposes per-guardrail CRUD: list, get, create, update, delete, plus posture refresh and posture read.
- All dashboard reads (model-usage-limits list, model-usage-posture rollup) project from the per-guardrail row shape.
- No API or service method accepts or returns the removed four-column shape.

### Task 3.8 — Add vendor-level `ModelConfig.is_disabled` toggle and cascade semantics
Extend the vendor (ModelConfig) with a single enable/disable toggle and materialise the cascade onto per-model availability rows.
Done when:
- `ModelConfig` gains `is_disabled` (boolean, default false).
- When `is_disabled` is set to true on a vendor, every `ModelAvailability` row for that vendor is updated to `is_disabled = true` and `disabled_reason = vendor_cascaded`.
- When `is_disabled` is set back to false on the vendor, each `ModelAvailability` row is restored to its prior manual state: rows previously disabled manually keep `is_disabled = true` and `disabled_reason = manual`; rows previously enabled are restored to `is_disabled = false`.
- The cascade is applied inside a single Control Center transaction so partial cascade is impossible.
- The vendor-level toggle is exposed by `PUT /api/v1/agents/model-configs/{config_id}/disabled` and is permission-gated.

### Task 3.9 — Add `ModelAvailability` entity and per-model disable endpoint
Introduce the per-model enabled state as a first-class entity so operators can disable a single model without disabling the vendor.
Done when:
- `ModelAvailability` model exists with `model_name`, `vendor_model_config_id` (FK to ModelConfig), `is_disabled` (boolean), `disabled_reason` (enum: `manual`/`vendor_cascaded`), and standard timestamps.
- A unique constraint on `(vendor_model_config_id, model_name)` prevents duplicate availability rows.
- `PUT /api/v1/agents/model-configs/{config_id}/models/{model_name}/disabled` toggles the per-model row and sets `disabled_reason = manual` whenever the operator drives the toggle.
- `GET /api/v1/agents/model-availability` returns the full vendor → model → enabled state for the dashboard hierarchy, including the cascade source indicator on each model row.
- A model name enabled by multiple vendors is considered available if at least one vendor offers it as enabled.

### Task 3.10 — Add the Agent Runtime pre-execution availability check
Make the Agent Runtime consult Control Center for vendor + model availability before dispatching any run.
Done when:
- Agent Runtime calls `POST /api/v1/agents/preflight/availability` for the resolved model (model_id + model_name) before dispatch.
- On allow, dispatch proceeds unchanged.
- On deny, dispatch is blocked, the run is marked with `AgentJob.termination_category` of `model_disabled` (when `disabled_reason = manual`) or `vendor_disabled` (when `disabled_reason = vendor_cascaded`), and an execution-log entry with `event_category = model_disabled` or `vendor_disabled` is emitted.
- The preflight contract is enforced at the Agent Runtime side; Control Center never initiates dispatch itself.
- The denial reason is returned in the API response and surfaced in operator-facing execution log views.

## Phase 4
### Task 4.1 — Build running-agents dashboard view for active parent and delegated runs
Implement a consolidated dashboard listing active sessions and delegated executions with policy posture indicators.
Done when:
- Dashboard shows active root and delegated runs in one view.
- Node-level status includes guardrail-related state indicators.
- View supports filtering and refresh behavior needed for operations.

### Task 4.2 — Add live topology diagram view for execution tree relationships
Implement an operator-facing topology view for active runtime relationships.
Done when:
- Topology diagram renders parent-child execution tree accurately.
- Node selection surfaces details required for operational decisions.
- Topology updates remain consistent with backend runtime projection.

### Task 4.3 — Add per-node terminate interaction with permission-aware UI states
Implement node terminate actions in the UI with proper permission gating and error handling patterns.
Done when:
- Authorized operators can request terminate on selected nodes.
- Unauthorized operators see disabled controls or explicit denial feedback.
- Dialog flows show API failure and permission failure states inline.

### Task 4.4 — Surface observe-only limit alerts in execution logs using existing log viewer patterns
Integrate observe-only events into the existing execution log presentation stack rather than introducing a separate log renderer.
Done when:
- Observe-only alerts are rendered in execution logs and distinguishable from failures.
- Existing span-based log viewer remains the canonical execution log surface.
- Alert metadata is visible in structured and raw log modes.

### Task 4.5 — Surface model-usage posture and consumption visibility in the runtime dashboard  ⚠️ NEEDS REWORK
The original task landed on a flat `ModelUsageGuardrailPanel` paired with a `ModelUsageGuardrailDialog` that took all four period limits at once. That pair is being replaced by a hierarchy-aware `VendorModelGuardrailPanel` and an inline `AddGuardrailForm` (no modal). See 4.6 and 4.7.
Done when (original scope, retained for traceability):
- Dashboard shows each configured model guardrail limit with its period type and current usage rollup.
- Posture state (within_limit, approaching_limit, breached) is visually represented without ambiguity.
- Model-usage guardrail panel is co-located with execution guardrail information for a single-view operator workflow.
- Display refresh cadence is consistent with topology polling configuration.

### Task 4.6 — Build `VendorModelGuardrailPanel` for the vendor → model → guardrail hierarchy
Replace the flat panel with a hierarchy-aware panel rendered in the dedicated "Model Guardrails" view on the runtime dashboard.
Done when:
- `VendorModelGuardrailPanel` renders vendor rows (one per `ModelConfig`), with each vendor row expandable into model rows (one per enabled model on that vendor) and each model row expandable into guardrail rows (one per configured period).
- Each vendor row exposes a vendor enable/disable toggle bound to `PUT /api/v1/agents/model-configs/{config_id}/disabled`; when the vendor is disabled, every model row beneath it shows a "Vendor disabled" cascade source badge.
- Each model row exposes a per-model enable/disable toggle bound to `PUT /api/v1/agents/model-configs/{config_id}/models/{model_name}/disabled`; the toggle is visible even when the vendor is disabled, and the model row displays a "Cascaded from vendor" indicator.
- Each guardrail row shows period, limit, unit, posture state, and per-guardrail enable, edit, and remove controls.
- All UI text is localized through i18next; permission errors and API failures follow the standard dialog error-handling pattern (clear on open/close, render first in content).

### Task 4.7 — Build inline `AddGuardrailForm` (no modal)
Replace the modal-based create flow with a small inline form rendered inside the expanded model row.
Done when:
- `AddGuardrailForm` is rendered inside the model row, not as a dialog or modal.
- The period select is filtered to only periods not yet configured on the model (i.e. it does not allow picking a period already covered by a guardrail on that model).
- Submitting the form dispatches a single per-period create call and closes the inline form on success.
- The form reuses the standard dialog error-handling pattern for inline API/permission failures (clear on open/close, render inline first).
- The form respects the `enforcement_posture` default of terminate and the `unit` default of `k`.

## Phase 5
### Task 5.1 — Add or extend API routes for active topology, node termination, and policy outcomes
Define and implement API contract changes required by dashboard and runtime control interactions.
Done when:
- API routes support active topology retrieval/streaming.
- API routes support node terminate requests and structured outcomes.
- API responses expose policy outcomes for recursion and guardrail events.

### Task 5.2 — Extend schemas and models for guardrail events, run relationships, and termination outcomes
Implement schema and model updates required for new runtime governance data. All planned models were implemented, with some using different names than originally planned: `ModelGuardrailEvaluation` (planned as `GuardrailPolicyEvaluation`), `ModelGuardrailConfiguration` (planned as `ModelUsageGuardrail`), and `ModelUsagePosture` (planned as `ModelUsagePeriodRollup`).
Done when:
- New entities and extensions align with data-model change documentation.
- Read/write schemas expose required fields with strong typing.
- Model registration and migrations are complete and consistent.

### Task 5.3 — Ensure Control Center-only persistence and secure service-to-service data exchange
Verify that persistence writes are centralized in Control Center and inter-service calls remain certificate-secured.
Done when:
- Agent Runtime writes governance records through Control Center pathways only.
- Communication Hub and Agent Runtime interactions use existing secure service channels.
- Sensitive identity and database credentials remain inaccessible to agents.

### Task 5.4 — Add API routes and data models for model-level usage limits and period-rollup posture  ⚠️ NEEDS REWORK
The original task landed endpoints and a flat `ModelGuardrailConfiguration` row. Both are being reshaped for the per-period hierarchy. See 5.5 (schema migration) and 5.6 (new API surface).
Done when (original scope, retained for traceability):
- CRUD endpoints allow operator configuration of per-model usage limits by period type.
- A posture query endpoint returns current rollup values and posture state (within_limit, approaching_limit, breached) for each period.
- Persistence models for usage limits and period-rollup snapshots are schema-migrated and registered.
- Agent Runtime reports usage through Control Center channels; Control Center aggregates and persists rollups.

### Task 5.5 — Add the rework migration: per-period guardrail rows, vendor disable, and ModelAvailability
Land a single Alembic migration that restructures the guardrail table, adds the vendor toggle, and creates the availability table.
Done when:
- `model_guardrail_configurations` is restructured: the four `usage_limit_*` columns are dropped, `period` (enum: `hour`/`day`/`week`/`month`) and `limit_value` (int) are added, and a unique constraint on `(model_id, model_name, period)` is in place.
- `model_configs` gains `is_disabled` (boolean, default false, not null).
- `model_availability` is created with `model_name` (string), `vendor_model_config_id` (FK to `model_configs.id`, ondelete cascade), `is_disabled` (boolean, default false, not null), `disabled_reason` (enum: `manual`/`vendor_cascaded`, default `manual`, not null), timestamps, and a unique constraint on `(vendor_model_config_id, model_name)`.
- A backfill step (in the same migration, in a transaction) seeds a `ModelAvailability` row for every `(vendor, model_name)` pair currently listed in any `ModelConfig.enabled_models` so the cascade and per-model toggles have a row to materialise on.
- The migration is reversible (downgrade restores the four limit columns as nullable and drops the new structures).

### Task 5.6 — Update the API surface for the hierarchy, disable toggles, and preflight
Replace the existing flat CRUD endpoints with the per-guardrail shape and add the four new endpoints required for the new contract.
Done when:
- `POST /api/v1/agents/guardrails/model-usage-limits` accepts `model_id`, `model_name`, `period`, `limit_value`, `unit`, `enforcement_posture`, `is_active` and creates exactly one guardrail row.
- `PUT /api/v1/agents/guardrails/model-usage-limits/{id}` uses the same per-guardrail shape.
- `PUT /api/v1/agents/model-configs/{config_id}/disabled` accepts `{ is_disabled: boolean }` and triggers the cascade in 3.8.
- `PUT /api/v1/agents/model-configs/{config_id}/models/{model_name}/disabled` accepts `{ is_disabled: boolean }` and sets `disabled_reason` to `manual` on operator-driven changes.
- `GET /api/v1/agents/model-availability` returns the full vendor → model → enabled state for the dashboard hierarchy, including the cascade source indicator.
- `POST /api/v1/agents/preflight/availability` accepts `model_id` + `model_name`, returns `{ allowed: boolean, reason?: string, disabled_reason?: "manual" | "vendor_cascaded" }`, and is the contract Agent Runtime uses in 3.10.
- All new endpoints are permission-gated, return explicit denial reasons, and follow existing API error conventions.

## Phase 6
### Task 6.1 — Add backend unit and integration tests for recursion validation and cascade termination
Implement backend test coverage for validation, authorization, and termination behavior. Implemented coverage includes recursion detection unit tests, API tests for create/update/run recursion-validation 422 contracts, model-usage guardrail API tests, and integration persistence tests for cascade outcomes and model posture records.
Done when:
- Unit tests cover recursion detection and policy decision edge cases.
- Integration tests validate terminate cascade outcomes across parent-child trees.
- Tests assert clear differentiation between policy denials and runtime failures.

### Task 6.2 — Add frontend tests for dashboard topology, permission gating, and alert rendering
Implement frontend tests for runtime dashboard behavior and operator UX. Implemented tests cover dashboard loading and permission error states, topology rendering and selection behavior, permission-gated terminate affordance, and termination dialog submit/error flows.
Done when:
- Tests cover topology rendering and selected-node detail behavior.
- Tests verify permission-gated terminate controls and denial visibility.
- Tests validate observe-only alert rendering in execution log views.

### Task 6.3 — Add end-to-end scenarios for dead-loop prevention and terminate cascade behavior
Implement E2E coverage validating integrated behavior across backend and frontend, including a real-backend integration variant in `runtime-control-dashboard.spec.ts` that avoids `page.route` mocks when credentials and backend availability are present.
Done when:
- E2E scenarios confirm create/update/run recursion blocking behavior.
- E2E scenarios confirm parent termination cascades to active child delegations.
- E2E scenarios confirm observe-only alerts are visible to operators in logs.

### Task 6.4 — Finalize deployment and operations updates for monitoring and incident response
Prepare deployment and operational readiness deliverables for controlled rollout.
Done when:
- Deployment notes cover new config, migration, and rollback considerations, including model-level usage limit variables and the default enforcement mode behavioral change.
- Operations notes define metrics, logs, and alerting for policy, terminate, and model-usage limit outcomes.
- Runbook guidance includes incident triage for recursion, cascade-stop, and model-usage limit breach events.

### Task 6.5 — Real-database regression coverage for the rework
Add a real-DB lifecycle test that exercises the new schema, the cascade semantics, and the pre-execution availability contract end-to-end so migration drift and contract drift are caught in CI rather than at deploy time.
Done when:
- A backend integration test runs against the migrated real database (no mocks) and verifies (a) per-period guardrail rows and `(model_id, model_name, period)` uniqueness, (b) `ModelConfig.is_disabled` cascade to `ModelAvailability` with `disabled_reason = vendor_cascaded`, (c) restoration on re-enable, (d) per-model toggle setting `disabled_reason = manual`, and (e) `POST /api/v1/agents/preflight/availability` returns allow/deny with the correct `disabled_reason`.
- The test fails when the migration is not applied (`alembic current` does not include the new migration id).
- The test is registered alongside the existing real-DB integration suite and runs as part of the standard test pass.

## Completion Checklist
- [x] All phase tasks are complete and validated against acceptance criteria
- [x] Architecture constraints are verified: runtime execution boundary, control-center database ownership, and sensitive data isolation
- [x] API, schema, and frontend contracts are aligned and version-consistent
- [x] Test coverage includes backend, frontend, and end-to-end scenarios for all critical flows
- [x] Deployment and operations documents are ready for release review
- [ ] Model-usage guardrails are restructured to the vendor → model → guardrail hierarchy (tasks 3.7–3.10, 4.6–4.7, 5.5–5.6, 6.5) and the previous flat per-model row (3.6, 4.5, 5.4) is retired
- [ ] `ModelConfig.is_disabled` vendor toggle and `ModelAvailability` per-model availability (with `manual` / `vendor_cascaded` cascade source) are wired end-to-end and audited
- [ ] Agent Runtime pre-execution availability check (`POST /api/v1/agents/preflight/availability`) blocks dispatch on vendor-disabled and model-disabled states and records the policy outcome
- [ ] `VendorModelGuardrailPanel` and inline `AddGuardrailForm` replace the previous `ModelUsageGuardrailPanel` and `ModelUsageGuardrailDialog` in the runtime dashboard
- [ ] Real-database regression coverage (6.5) is in place and passing against the migrated schema
