# Test Plan: Harden Agent Guardrails and Runtime Control Dashboard

## 1) Test Strategy

Validate this change across backend, frontend, and end-to-end layers with emphasis on:
- guardrail consistency across direct and delegated execution,
- default terminate posture and observe-only visibility,
- model-usage governance by period,
- runtime topology visibility,
- permission-gated termination with cascade outcomes,
- recursion/dead-loop prevention at create/update/run,
- operational log auditability.

This plan follows `docs/config.yaml` constraints:
- Service segregation is preserved (Agent Runtime executes, Control Center governs/persists, Communication Hub orchestrates).
- Frontend uses backend APIs only.
- Policy and termination outcomes must be visible and auditable.

Quality gates for sign-off:
- Every PRD acceptance criterion is covered by at least one E2E scenario.
- Large feature areas include 3+ distinct E2E scenarios.
- Backend coverage includes endpoint + service behavior, including denial/error paths.
- Frontend coverage includes component/hook behavior, permission UX, and error rendering.
- Real DB validation is mandatory for schema/state changes.
- At least one real-backend E2E variant runs without API request mocking.

## 2) Acceptance Criteria Coverage Map

Feature areas mapped to PRD acceptance criteria:
- A. Guardrail enforcement posture and policy visibility: AC1, AC2, AC3, AC15
- B. Model-usage limits and posture (vendor → model → guardrail hierarchy, per-period guardrails, per-guardrail enable/disable, no forced 4-period entry): AC4, AC5, AC6, AC9
- C. Runtime visibility and topology monitoring: AC7, AC8, AC9
- D. Runtime termination governance and cascade: AC10, AC11, AC12, AC15
- E. Recursion/dead-loop prevention (create/update/run): AC13, AC14
- F. Model guardrail configuration management UI (frontend hierarchy: vendor rows expand to model rows expand to per-period guardrail rows, with cascade-source badge): AC4, AC5
- G. Dedicated runtime control dashboard page + live SVG topology + configured model dropdown: AC5, AC7, AC8
- H. Vendor and model availability (vendor disable with cascade, per-model disable, pre-execution availability check, execution-log visibility of model_disabled and vendor_disabled blocks): AC4 (partial — disable + availability), new ACs covering vendor disable, per-model disable, and pre-execution availability block

## 3) Detailed Coverage by Feature Area

### A) Guardrail Enforcement Posture and Policy Visibility

#### User Journey (step-by-step)
1. Admin opens Agent Type configuration and configures execution guardrail values.
2. Admin saves without changing enforcement posture and confirms default posture resolves to terminate.
3. Admin optionally changes posture to observe-only for a controlled scenario.
4. Operator launches a run that includes delegation to child nodes.
5. System enforces guardrails on root and child execution paths.
6. If observe-only threshold is reached, operator views policy alert in execution logs.
7. Operator reviews logs and distinguishes guardrail/policy events from functional failures.

#### E2E Scenarios (3+)
- E2E-A1 Happy path: create/update agent type, keep default posture, run delegated workflow, verify run stops on hard guardrail threshold and both root/child sessions show guardrail-stop policy event.
- E2E-A2 Happy path: set observe-only posture explicitly, run threshold-reaching workflow, verify execution continues and execution log shows clear observe-only threshold alert.
- E2E-A3 Happy path: run mixed delegated workflow, verify no guardrail bypass in child path (child hits same policy constraints and produces policy events consistent with root policy snapshot).
- E2E-A4 Error/edge: submit invalid guardrail contract values (out-of-range limits), verify API validation errors and UI surfaces field-level or dialog-level error feedback.

#### Backend Test Cases
- Endpoint tests:
	- `POST /api/v1/agents/types` default posture behavior when posture omitted.
	- `PUT /api/v1/agents/types/{type_id}` explicit observe-only override persistence/readback.
	- `GET /api/v1/agents/sessions/{session_id}/logs` policy event fields present and typed.
	- `GET /api/v1/agents/runtime/policy-events` returns guardrail/validation/termination/posture events.
- Service tests:
	- `AgentRuntimeExecutor._check_runtime_limits_or_raise`: enforce mode blocks at threshold.
	- `AgentRuntimeExecutor` observe-only threshold event emission (`guardrail.token_budget.threshold_reached`).
	- Parent/child policy consistency checks in delegated execution paths.
	- Log classification correctness (policy vs functional failure metadata).

#### Frontend Component Test Cases
- `AgentType` create/update forms: posture default display and explicit override behavior.
- `AgentExecutionDetailsDialog` + log surfaces: policy event visibility and labeling.
- `LogViewer`/`WorkingStepsPanel`/`LogPresenter`: guardrail events rendered as policy outcomes and distinguishable from runtime failures.
- Error handling pattern compliance for dialogs that save guardrail settings.

### B) Model-Usage Limits and Posture (Vendor → Model → Guardrail Hierarchy)

#### User Journey (step-by-step)
1. Admin opens the Runtime Control dashboard and selects the model-usage guardrail section.
2. Admin sees the vendor → model → guardrail hierarchy: vendor rows expandable to model rows, model rows expandable to per-period guardrail rows.
3. Admin chooses "Add guardrail" on a model and creates only a single period guardrail (for example, hourly); the dashboard updates to show one row for that period with no forced 4-period entry.
4. Admin adds additional periods to the same model; the inline "Add guardrail" form filters the period select to non-configured periods.
5. Admin configures each per-period guardrail with the default terminate posture (or explicitly selects observe-only), the unit, the limit value, and the per-guardrail `is_active` toggle.
6. Admin disables a single guardrail and verifies the per-guardrail toggle and remove button work independently of the per-model toggle; the model remains enabled.
7. Admin removes a single guardrail and verifies only that row disappears; sibling guardrails on the same model are unchanged.
8. System refreshes posture snapshots from current usage, and the dashboard shows per-period posture state (within_limit, approaching_limit, breached) keyed by the per-period `ModelGuardrailConfiguration` row.
9. Operator confirms posture transitions without leaving the monitoring workflow.

#### E2E Scenarios (3+)
- E2E-B1 Happy path: create per-period guardrails (one to four) on a model, open runtime dashboard, verify the hierarchy shows the correct vendor, model, and per-period rows with configured threshold and current usage; the posture row count matches the configured period count.
- E2E-B2 Happy path: drive usage into approaching-limit range for a configured period, refresh dashboard, verify the posture indicator changes to approaching_limit on the matching period row only.
- E2E-B3 Happy path: drive usage beyond threshold for a configured period, verify posture becomes breached and the per-guardrail enforcement posture is displayed alongside the period's usage state.
- E2E-B4 Error/edge: unauthorized user attempts create/update/delete on a per-period guardrail, verify action blocked and clear denial feedback is shown.
- E2E-B5 Error/edge: delete non-existent per-period guardrail id, verify backend returns not-found and UI shows non-silent error state.
- E2E-B6 (new) Vendor cascade disable: WHEN an authorized operator disables a vendor, THEN every model under it shows a "Disabled (cascade from vendor)" badge, the per-model disable affordance remains visible, the pre-execution availability check returns `vendor_disabled` for each cascaded model, and any agent execution that would use one of the cascaded models is blocked with a clear `vendor_disabled` reason in execution logs.
- E2E-B7 (new) Re-enable individual model under disabled vendor: WHEN a vendor is disabled and an operator then enables an individual model under it, THEN only the per-model toggle changes; the vendor stays disabled, the model badge indicates the model is enabled but the cascade source is still the vendor, and the pre-execution availability check continues to block dispatch with `vendor_disabled` reason until the vendor itself is re-enabled.
- E2E-B8 (new) Manual model disable: WHEN an authorized operator manually disables a single model, THEN the pre-execution availability check blocks dispatch with a clear `model_disabled` reason, execution logs show the model_disabled block event, and re-enabling the model restores dispatch without affecting sibling models or the vendor.
- E2E-B9 (new) Single-period guardrail (no forced 4-period entry): WHEN an operator adds only an hourly guardrail to a model, THEN the dashboard shows exactly one guardrail row for that model, the period select filters out hour on subsequent adds, and the posture view reports state for hour only; the model is saved successfully without prompting for day/week/month.
- E2E-B10 (new) Remove one of four guardrails: WHEN an operator adds all four period guardrails on a model and then removes the daily guardrail, THEN the daily row disappears from the model, the model still shows three guardrails (hour, week, month), and the corresponding `ModelUsagePosture` row is no longer present in posture rollups.
- E2E-B11 (new) Disable a single guardrail, not the model: WHEN an operator toggles a single per-period guardrail to disabled, THEN the model remains enabled, the pre-execution availability check still allows dispatch (the model is enabled), and the disabled guardrail does not block dispatch but is recorded in evaluation history with `is_active = false`.

#### Backend Test Cases
- Endpoint tests (per-period guardrail CRUD):
	- `GET /api/v1/agents/guardrails/model-usage-limits` returns all per-period guardrail rows aggregated by model in the new hierarchy shape, not a single per-model row.
	- `POST /api/v1/agents/guardrails/model-usage-limits` creates a single per-period guardrail, defaults posture to terminate, defaults unit to `k`, enforces the `(model_id, model_name, period)` uniqueness rule, returns 409 on conflict with a clear error code, and rejects requests missing `period` or `limit_value`.
	- `GET /api/v1/agents/guardrails/model-usage-limits/{limit_id}` retrieval and 404 behavior.
	- `PUT /api/v1/agents/guardrails/model-usage-limits/{limit_id}` updates `limit_value`, `enforcement_posture`, `unit`, and `is_active` of a single per-period guardrail; does not allow changing the `period` of an existing row.
	- `DELETE /api/v1/agents/guardrails/model-usage-limits/{limit_id}` removes only the specified period's guardrail and 404 behavior on missing id.
	- `GET /api/v1/agents/guardrails/model-usage-posture` returns posture rows keyed by per-guardrail `ModelGuardrailConfiguration` and grouped by model for the dashboard hierarchy.
- Endpoint tests (vendor and model availability — new):
	- `PUT /api/v1/agents/model-configs/{id}/disabled` toggles vendor disabled state; WHEN set to true, every `ModelAvailability` row for that vendor flips to `is_disabled = true` and `disabled_reason = vendor_cascaded`; WHEN set to false, the per-model `is_disabled` and `disabled_reason` are restored from each row's prior state.
	- `PUT /api/v1/agents/model-configs/{id}/models/{model_name}/disabled` toggles a single model's availability; WHEN set to true, sets `is_disabled = true` and `disabled_reason = manual`; WHEN set to false, clears `is_disabled` and resets `disabled_reason` to `manual` only if the row was previously manually disabled (cascade state is restored from the vendor).
	- `GET /api/v1/agents/model-availability` returns the full vendor → model → guardrail hierarchy with effective availability state, per-model `is_disabled`, per-model `disabled_reason`, and a cascade-source indicator on each model.
	- `POST /api/v1/agents/preflight/availability` returns `allowed` with empty reason when both vendor and model are enabled, `vendor_disabled` when the vendor is disabled (cascade reason), `model_disabled` when the model is manually disabled, and `allowed` when the same model name is enabled by a different vendor.
- Service tests:
	- `ModelUsageGuardrailService` per-period CRUD operations.
	- `ModelUsageGuardrailService.refresh_posture_snapshots` period rollup correctness for hour/day/week/month boundaries.
	- Posture-state transition logic (within_limit, approaching_limit, breached).
	- `ModelAvailabilityAuthority.cascade_vendor_disabled` materialises the cascade on every child `ModelAvailability` row with `disabled_reason = vendor_cascaded`, idempotent on repeated calls.
	- `ModelAvailabilityAuthority.restore_vendor_enabled` returns each per-model `is_disabled` to its prior value and `disabled_reason` to `manual` where the row was previously manually disabled; otherwise clears `is_disabled` to false and `disabled_reason` to a non-cascaded state.
	- `PreExecutionAvailabilityCheck.evaluate` returns the correct reason for each state combination (vendor only, model only, both, multi-vendor same model name, unknown model).
	- `PreExecutionAvailabilityCheck` is invoked from the Agent Runtime session-orchestrator path before dispatch and the block path is observable in execution logs as a `model_disabled` or `vendor_disabled` event with the correct reason.

#### Frontend Component Test Cases
- `ModelUsageGuardrailPanel` renders the vendor → model → guardrail hierarchy with expandable vendor rows, expandable model rows, and per-period guardrail rows; counts and visibility match the configured state.
- `ModelUsageGuardrailDialog` create mode exposes a period select that filters out already-configured periods and accepts a single period per submission; edit mode pre-populates the existing period; posture defaults to terminate and unit defaults to `k`; validation rejects submission with no period or no limit.
- Per-guardrail enable/disable toggle and remove button work independently from the per-model toggle; the model stays enabled when only a guardrail is disabled.
- Per-model enable/disable toggle updates the panel state and the cascade-source badge; per-vendor toggle cascades the disabled state visibly to all child models.
- The cascade-source badge ("Disabled (cascade from vendor)") appears on each model under a disabled vendor, and the per-model disable affordance remains visible.
- `useModelUsageLimits` and `useModelUsagePosture` queries: success, empty state, refresh, and the dashboard view that aggregates posture by model in the new hierarchy.
- `useCreateModelUsageLimit`, `useUpdateModelUsageLimit`, `useDeleteModelUsageLimit`: mutation success, 409 conflict path on duplicate `(model_id, model_name, period)`, and error rendering per the dialog error handling convention.
- `useModelAvailability` and `usePreflightAvailability` hooks: success, error, and refresh behavior; cache invalidation on availability state changes.
- Runtime dashboard posture chips/labels: correct visual mapping for within/approaching/breached per period.
- Permission-denied error rendering for guardrail, vendor-disable, and model-disable actions.
- `ModelUsageGuardrailManagement.test.tsx`: end-to-end panel rendering on the dedicated `RuntimeControlDashboardPage`, add/edit dialog opening, create dialog display on button click, assertion that the panel renders the unit suffix (e.g. `45 / 100 k`) next to each usage value, and assertion of the new vendor → model → guardrail hierarchy rendering.
- **Unit selector (added in FIX-20260601-153000):** Operator can choose the unit (`k` default or raw `tokens`) for each period limit, and the panel renders the unit suffix consistently. The unit Select is disabled in edit mode because the unit is a property of the configuration's billing semantics.
	- `ModelUsageGuardrailDialog.unit.test.tsx`: dialog renders a unit Select with default `k`; save dispatches `unit: 'k'`; operator can change to `tokens` and the payload reflects the choice; edit mode freezes the unit selector.
	- `ModelUsageGuardrailDialog.modelDropdown.test.tsx`: existing model-dropdown test extended to also assert `unit: 'k'` in the save payload.
	- `ModelUsageGuardrailManagement.test.tsx`: mocked `model-usage-limits` response extended to include `unit: 'k'` per limit; new test asserts the unit suffix is rendered next to the usage value.

### C) Runtime Visibility and Topology Monitoring

#### User Journey (step-by-step)
1. Operator navigates to runtime executions dashboard.
2. Operator sees consolidated list of active sessions.
3. Operator opens runtime topology panel and inspects parent-child edges.
4. Operator selects a node and reviews depth/status metadata.
5. Operator observes model usage posture panel in same dashboard view.
6. Polling/refresh updates list and topology as active state changes.
7. Operator opens execution details/logs from selected session.

#### E2E Scenarios (3+)
- E2E-C1 Happy path: start parent run that delegates to children, open dashboard, verify consolidated active list includes root + delegated sessions.
- E2E-C2 Happy path: verify topology graph nodes/edges match active relationships and selected-node details (status/depth/parent) update on click.
- E2E-C3 Happy path: while topology visible, verify model usage posture panel is simultaneously visible with current state, satisfying one-workflow risk assessment.
- E2E-C4 Error/edge: empty runtime state (no active sessions), verify clear empty states in list/topology/panels without rendering errors.
- E2E-C5 Error/edge: transient API failure during polling, verify non-blocking error display and successful recovery on next refresh.

#### Backend Test Cases
- Endpoint tests:
	- `GET /api/v1/agents/sessions` active filtering behavior for dashboard list.
	- `GET /api/v1/agents/runtime/topology` returns nodes/edges/root ids with status filtering and `max_nodes` handling.
	- `GET /api/v1/agents/sessions/{session_id}/execution-logs` retrieval for selected session detail flow.
- Service tests:
	- `RuntimeTopologyController.get_active_topology` projection correctness for mixed depth/fan-out trees.
	- Terminal vs non-terminal inclusion behavior (`include_terminal` query branch).
	- Relationship integrity for parent-child edge generation.

#### Frontend Component Test Cases
- `AgentInstanceDashboardPage`: consolidated list rendering and refresh behavior.
- `RuntimeTopologyPanel`: node/edge rendering, selection state, empty state, and status display.
- `AgentExecutionDetailsDialog` launch from dashboard rows and selected node context.
- Query state handling (loading/error/success) with `PermissionDeniedAlert` when required.

### D) Runtime Termination Governance and Cascade

#### User Journey (step-by-step)
1. Authorized operator selects running node in runtime topology.
2. Operator opens terminate dialog and chooses scope (`node_only` or `cascade_subtree`) with reason.
3. System performs permission evaluation and accepts/rejects request.
4. Operator receives request id/correlation context.
5. Operator monitors termination outcomes for affected nodes.
6. If parent terminated with cascade scope, active descendants terminate and outcomes are recorded.
7. Unauthorized user cannot execute termination and receives clear message.

#### E2E Scenarios (3+)
- E2E-D1 Happy path: authorized user terminates selected child with node-only scope; verify only target node transitions to terminated outcome.
- E2E-D2 Happy path: authorized user terminates parent with cascade_subtree scope; verify parent + active descendants terminate and outcomes are visible per node.
- E2E-D3 Happy path: submit termination and poll request outcome endpoint; verify request id and complete cascade result set are visible in UI.
- E2E-D4 Error/edge: unauthorized user attempts terminate action; verify control hidden/disabled where applicable and backend denial is shown if attempted.
- E2E-D5 Error/edge: terminate already-completed or missing session id; verify not-found/already-completed outcomes are surfaced clearly.

#### Backend Test Cases
- Endpoint tests:
	- `POST /api/v1/agents/runtime/terminate` allowed and denied flows.
	- `GET /api/v1/agents/runtime/terminate/{request_id}` outcome retrieval and 404 behavior.
	- `GET /api/v1/agents/runtime/policy-events` includes termination category entries.
	- Existing `DELETE /api/v1/agents/instances/{instance_id}` behavior remains compatible for legacy instance stop path.
- Service tests:
	- `TerminationOrchestrator.request_termination` permission-gated request creation.
	- `TerminationOrchestrator.get_cascade_outcomes` per-node outcome completeness.
	- Cascade processing idempotency for overlapping terminate requests.
	- Explicit denial reason propagation.

#### Frontend Component Test Cases
- `RuntimeTopologyPanel`: terminate entrypoint availability by permission.
- `NodeTerminationDialog`: scope selection, reason input, confirm flow, and dialog error handling.
- `useNodeTermination` + `useTerminationOutcomes`: mutation success/error + polling behavior.
- Runtime status alert area in dashboard: request status and outcome count display.

### E) Recursion and Dead-Loop Prevention (Create/Update/Run)

#### User Journey (step-by-step)
1. Admin creates or edits Agent Type with SOP/delegation configuration.
2. System validates recursion/dead-loop risk in create/update context.
3. Invalid recursive configuration is blocked with actionable details.
4. Admin saves valid configuration.
5. Operator initiates run.
6. System performs run preflight recursion validation before execution queueing.
7. Risky run is blocked before execution starts; valid run proceeds.

#### E2E Scenarios (3+)
- E2E-E1 Happy path: create valid non-recursive agent type and launch run successfully.
- E2E-E2 Error/edge: create agent type with direct/indirect recursive delegation path, verify create blocked with recursion_validation_failed response and user-visible message.
- E2E-E3 Error/edge: update existing agent type to introduce recursion risk, verify update blocked with validation details.
- E2E-E4 Error/edge: run initiation for currently risky agent type, verify run rejected pre-execution and no active session is created.

#### Backend Test Cases
- Endpoint tests:
	- `POST /api/v1/agents/types` recursion validation in `create` context.
	- `PUT /api/v1/agents/types/{type_id}` recursion validation in `update` context.
	- `POST /api/v1/agents/sessions` recursion validation in `run` context.
	- Validation error payload contract (`error=recursion_validation_failed`, findings summary).
- Service tests:
	- `RecursionValidationService.validate_agent_type` behavior for create/update/run contexts.
	- `detect_cycle_path` scenarios: self-loop, indirect cycle, acyclic path, traversal depth constraints.
	- Runtime precheck path alignment between control-center validation and runtime delegation precheck.

#### Frontend Component Test Cases
- Agent Type create/edit pages/dialogs: blocked-save error rendering and actionable messaging.
- Session launch UI path: blocked-run feedback when recursion/dead-loop risk is detected.
- Validation message persistence across retries after user correction.

### F) Model Guardrail Configuration Management UI (Vendor → Model → Guardrail Hierarchy)

This feature area covers the operator-facing presentation of the new vendor → model → guardrail hierarchy. The dashboard panel and its inline forms replace the previous flat "one row per model" affordance; the hierarchy is navigable without losing context, and per-vendor and per-model disable affordances remain visible to show the cascade source.

#### User Journey (step-by-step)
1. Admin opens the Runtime Control dashboard and locates the model-usage guardrail section.
2. Admin sees a list of vendors; each vendor row shows the vendor name, an enable/disable toggle, a count of models, and an expand affordance.
3. Admin expands a vendor row to see all models under it; each model row shows the model name, a per-model enable/disable toggle, a count of guardrails, a posture chip, and an expand affordance.
4. Admin expands a model row to see its existing per-period guardrails; each guardrail row shows the period, limit, unit, posture state, a per-guardrail enable/disable toggle, and a remove affordance.
5. Admin chooses "Add guardrail" on a model; the inline form filters the period select to non-configured periods only, so the operator cannot duplicate a period on the same model.
6. Admin adds only an hourly guardrail and verifies the model is saved with exactly one guardrail row, no forced 4-period entry.
7. Admin disables a single guardrail via the per-guardrail toggle; the model remains enabled, the disable is independent of the per-model toggle, and the disabled state is reflected in the guardrail row.
8. Admin removes a single guardrail via the remove button; only that row disappears; sibling guardrails on the same model are unchanged.
9. Admin disables a vendor; the cascade-source badge appears on every child model, the per-model disable affordance remains visible, and the operator can see the cascade source in the UI.
10. Admin enables a model under a still-disabled vendor; the per-model toggle changes, the cascade source remains visible, and the model badge reflects the per-model enabled state while the vendor stays disabled.

#### Frontend Component Test Cases
- `VendorModelGuardrailPanel` renders vendor rows, expandable to model rows, expandable to guardrail rows; the three-level hierarchy is navigable without losing context; the panel renders on the dedicated `RuntimeControlDashboardPage` (not on the session-list page).
- The cascade-source badge ("Disabled (cascade from vendor)") appears on each model under a disabled vendor, and the per-model disable affordance remains visible.
- The "Add guardrail" inline form filters the period select to non-configured periods only; the operator cannot pick a period that already has a guardrail on the model.
- Per-guardrail enable/disable toggle and remove button work independently of the per-model toggle; the model stays enabled when only a guardrail is disabled.
- Per-model enable/disable toggle works and updates the panel state; per-vendor enable/disable toggle works and cascades the visible disabled state to all child models.
- Empty, loading, and error states render correctly per level of the hierarchy (no vendors, no models, no guardrails, partial failure).
- Permission-denied error rendering for vendor-disable, model-disable, and per-guardrail actions; affordances hidden/disabled where the user lacks permission.
- Localized UI text coverage for all new affordances, badges, and labels (i18next keys, no hardcoded strings).
- `useVendorModelGuardrailTree` and related hooks: success, empty state, and refresh behavior; cache invalidation on vendor/model/guardrail mutations.
- `VendorModelGuardrailPanel.test.tsx` (new): covers the three-level hierarchy rendering, cascade-source badge, per-guardrail CRUD, and per-vendor/per-model disable flows described above.

### G) Dedicated Runtime Control Dashboard + Live SVG Topology + Configured Model Dropdown

This feature area was added in FIX-20260601-145208 to ensure the runtime control surface is a standalone page (not a panel embedded in the execution list), the live delegation topology uses the SVG-based renderer that matches the agent topology preview prototype, and the model-usage guardrail dialog exposes a dropdown of configured models so guardrails are linked by `model_id` rather than free-text.

#### User Journey (step-by-step)
1. Operator opens the AI Agent section in the sidebar and selects "Runtime Control" (new nav item) which navigates to `/agents/runtime-control`.
2. The dedicated page renders the live SVG topology, selected-node details panel, and the model-usage guardrail panel.
3. Operator clicks a topology node to inspect details and open the terminate dialog.
4. Operator opens "Add Model Limit" in the model-usage panel.
5. The dialog shows a model dropdown populated from the union of `enabled_models` across all `ModelConfig` providers; selecting an option sends both `model_id` and `model_name` to the backend.
6. Operator opens the execution list at `/agents/executions` to confirm the runtime-control panels (topology, model guardrails) are no longer embedded there.

#### Frontend Component Test Cases
- `RuntimeControlDashboardPage.test.tsx`:
  - Route registration — `/agents/runtime-control` resolves to the dedicated page element.
  - Topology rendering — the page mounts `RuntimeTopologyDiagram`, which renders an `svg` element with `data-testid="runtime-topology-svg"` and at least one `rect` per node plus at least one `line`/`path` per edge from the topology payload.
- `ModelUsageGuardrailDialog.modelDropdown.test.tsx`:
  - Dialog renders a model `Select` (combobox role), not a free-text textbox.
  - On save, the dialog dispatches both `model_id` and `model_name` from the chosen option (no random UUID).
  - When no model is selected, the save button does not submit and an inline required-error alert is shown.
- `ModelUsageGuardrailManagement.test.tsx`:
  - The model-usage guardrail panel and CRUD affordances render on the dedicated `RuntimeControlDashboardPage` (not on the session-list page).
  - Add and Edit affordances open the create/edit dialogs with the configured-model dropdown.
- `AgentInstanceDashboard.runtime-control.test.tsx`:
  - The execution list page no longer renders runtime-control panels (topology, model-usage guardrail); it only renders the session list and execution details dialog.
- `AppShell.test.tsx`:
  - The sidebar shows a "Runtime Control" nav item under the AI Agent group that navigates to `/agents/runtime-control`.

### H) Vendor and Model Availability

This feature area covers the new vendor and model disable controls, the per-model availability state, the cascade rule (vendor disable cascades to all its models), and the pre-execution availability check that the Agent Runtime performs before dispatching any agent execution. Disabled states and the cascade source are visible in the UI and in execution logs.

#### User Journey (step-by-step)
1. Authorized operator opens the Runtime Control dashboard and locates the vendor and model availability sections.
2. Operator sees the vendor list with an enable/disable toggle on each vendor; the per-model disable affordances are also visible.
3. Operator disables a vendor; the system cascades the disabled state to every model under it, the cascade source is visible in the UI on each model, and the pre-execution availability check returns `vendor_disabled` for each cascaded model.
4. Operator confirms that any in-flight or new agent execution that uses one of the cascaded models is blocked with a clear `vendor_disabled` reason in execution logs; the block event is distinct from functional failures.
5. Operator re-enables a model under the still-disabled vendor; the per-model toggle changes, the model badge indicates the per-model enabled state, but the vendor remains disabled and dispatch continues to be blocked with `vendor_disabled`.
6. Operator re-enables the vendor; the cascade is reversed, each model's prior manual disable state is restored, and dispatch is allowed for models that are not manually disabled.
7. Operator manually disables a single model; the pre-execution availability check returns `model_disabled`, dispatch is blocked, and execution logs show the reason. Re-enabling the model restores dispatch without affecting siblings or the vendor.
8. Operator checks a model name offered by two vendors; if one vendor is disabled, the model remains available through the other vendor and dispatch is allowed.

#### E2E Scenarios (3+)
- E2E-H1 (new) Vendor disable blocks dispatch: WHEN an authorized operator disables a vendor, THEN every model under it shows a cascade-source badge, the pre-execution availability check returns `vendor_disabled` for each cascaded model, and any agent execution that would use one of the cascaded models is blocked with a clear `vendor_disabled` reason in execution logs.
- E2E-H2 (new) Manual model disable blocks dispatch: WHEN an authorized operator manually disables a single model, THEN the pre-execution availability check returns `model_disabled`, the agent execution is blocked, execution logs show the model_disabled block event, and re-enabling the model restores dispatch without affecting siblings or the vendor.
- E2E-H3 (new) Multi-vendor same model: WHEN a model name is offered by two vendors and one vendor is disabled, THEN the pre-execution availability check returns `allowed` for the model (resolved through the still-enabled vendor) and dispatch proceeds.
- E2E-H4 Error/edge: unauthorized user attempts to disable a vendor or a model, verify the action is blocked, the UI surfaces a clear denial message, and the vendor/model state remains unchanged.
- E2E-H5 Error/edge: pre-execution availability check is called for a model name that does not exist in any vendor, verify the check returns a clear `model_not_found` reason and the UI surfaces the reason in the execution log.

#### Backend Test Cases
- Endpoint tests:
	- `PUT /api/v1/agents/model-configs/{id}/disabled` toggles vendor disabled state; cascading of `disabled_reason` to all child `ModelAvailability` rows; restoration on re-enable; idempotent on repeated calls.
	- `PUT /api/v1/agents/model-configs/{id}/models/{model_name}/disabled` per-model toggle; setting `disabled_reason = manual` on disable; clearing on enable; preserves vendor cascade state when the vendor is disabled.
	- `GET /api/v1/agents/model-availability` returns the full vendor → model → guardrail hierarchy with effective availability state, per-model `is_disabled`, per-model `disabled_reason`, and a cascade-source indicator on each model.
	- `POST /api/v1/agents/preflight/availability` returns `allowed` with empty reason when both vendor and model are enabled, `vendor_disabled` when the vendor is disabled (cascade reason), `model_disabled` when the model is manually disabled, `allowed` when the same model name is enabled by a different vendor, and `model_not_found` for unknown model names.
	- Authorization: `PUT` endpoints and `POST /agents/preflight/availability` enforce the runtime terminate / guardrail-management permission; unauthorized callers receive explicit denial.
- Service tests:
	- `ModelAvailabilityAuthority.cascade_vendor_disabled` materialises the cascade on every child `ModelAvailability` row with `disabled_reason = vendor_cascaded`; idempotent.
	- `ModelAvailabilityAuthority.restore_vendor_enabled` returns per-model `is_disabled` to its prior value and `disabled_reason` to `manual` where the row was previously manually disabled; otherwise clears `is_disabled` and sets `disabled_reason` to a non-cascaded state.
	- `PreExecutionAvailabilityCheck.evaluate` returns the correct reason for each state combination (vendor only, model only, both, multi-vendor same model name, unknown model).
	- `PreExecutionAvailabilityCheck` is invoked from the Agent Runtime session-orchestrator path before dispatch; the block path is observable in execution logs as a `model_disabled` or `vendor_disabled` event with the correct reason and a stable event_category.

#### Frontend Component Test Cases
- `VendorModelGuardrailPanel` vendor enable/disable toggle works and cascades visible state to all child models; the cascade-source badge appears on each affected model and the per-model disable affordance remains visible.
- `VendorModelGuardrailPanel` per-model enable/disable toggle works and updates the panel state; re-enabling a model under a disabled vendor shows the per-model enabled state while the vendor stays disabled.
- `RuntimeControlDashboardPage` shows the new vendor → model → guardrail hierarchy with availability state per level; the dashboard reflects the cascade-source indicator on each model.
- `useModelAvailability` and `usePreflightAvailability` query/mutation hooks: success, error, and refresh behavior; cache invalidation on availability state changes.
- Permission-denied error rendering for vendor-disable and model-disable actions; affordances hidden/disabled where the user lacks permission.
- Execution log surfaces: `model_disabled` and `vendor_disabled` events are rendered distinctly from functional failures and clearly attribute the root cause (vendor or model).

## 4) Cross-Cutting Error and Reliability Scenarios

- Concurrent termination requests on overlapping subtrees: verify deterministic outcome states and no stuck pending requests.
- Topology/read consistency during rapid session state changes: ensure no stale parent-child artifacts after polling refresh.
- Permission drift mid-session: UI affordance recalculates and backend remains source-of-truth.
- High fan-out/depth delegations: topology and outcome endpoints remain performant and bounded by `max_nodes`/query limits.
- Mixed policy + runtime failures in same session: logs preserve category distinction and chronological coherence.
- **Race between vendor-disable and a running agent**: WHEN a vendor is disabled while one or more agent executions are in-flight (or queued for dispatch) using models under that vendor, THEN the pre-execution availability check returns a deterministic outcome for each in-flight/queued run (already-dispatched runs continue; not-yet-dispatched runs are blocked with `vendor_disabled`); no partial-dispatch state is observable; the cascade is applied atomically to all child `ModelAvailability` rows before the preflight call returns. Cover this with a concurrency integration test that fires the vendor-disable call and a session launch simultaneously and asserts the post-state is one of the allowed outcomes (allow or block) — never a torn state.
- **Concurrent per-model toggles on the same model name offered by multiple vendors**: WHEN two operators concurrently disable/enable the same model name under different vendors (or the same vendor), THEN the system serialises the toggles per `(vendor_model_config_id, model_name)` and the final per-model `is_disabled` and `disabled_reason` are consistent with the last applied write; `ModelAvailability` rows for both vendors reflect the final state; the pre-execution availability check returns a deterministic reason.
- **Availability check during a vendor toggle transition**: WHEN a pre-execution availability check is called for a model whose vendor is being toggled concurrently, THEN the check returns a deterministic reason (`allowed`, `vendor_disabled`, or `model_disabled`) consistent with the persisted state at the time the transaction committed; the result is never an inconsistent mixed-state. Cover with a test that interleaves vendor-disable calls with preflight calls and asserts the response reason matches the persisted DB state at the moment of decision.
- **Vendor disable → model toggle → vendor re-enable sequence**: WHEN an operator disables a vendor, then disables a model under it, then re-enables the vendor, THEN the model is correctly restored to its prior manual-disable state (still disabled) and the cascade-source badge indicates the manual reason; no model is left in a stale cascade-disabled state.
- **Permission drift on vendor/model disable actions**: WHEN a user's permission is revoked between page load and toggle action, THEN the action is rejected, the UI surfaces the denial, and the vendor/model state is unchanged.

## 5) Real DB and Real-Backend Validation (Mandatory)

This change includes governance persistence and state-lifecycle entities. The following are mandatory for sign-off:
- Real DB integration checks (no mocks):
	- Apply migrations (`alembic upgrade head`) before integration execution.
	- Verify migration version (`alembic current`) captured in test run notes.
	- Verify schema objects for new/extended runtime-governance entities exist and constraints/enums are applied.
	- Verify persistence lifecycle transitions for:
		- termination requests and cascade outcomes,
		- recursion validation checks/findings,
		- model usage limits and posture snapshots,
		- guardrail threshold events.
		- **vendor and model availability**: `ModelConfig.is_disabled`, `ModelAvailability.is_disabled`, `ModelAvailability.disabled_reason` (enum values `manual` and `vendor_cascaded`), and the `(vendor_model_config_id, model_name)` referential integrity.
	- Verify referential integrity between request/outcome, evaluation/event, and parent/child relationship records.
	- **New mandatory real-DB check — vendor cascade materialises on child `ModelAvailability` rows**: WHEN a real vendor is disabled via `PUT /api/v1/agents/model-configs/{id}/disabled` against the real database, THEN every `ModelAvailability` row for that vendor is observed to have `is_disabled = true` and `disabled_reason = vendor_cascaded` in the database (no stale rows, no missing rows). Conversely, WHEN the vendor is re-enabled, THEN each `ModelAvailability` row is restored: rows that were originally manually disabled are returned to `is_disabled = true` and `disabled_reason = manual`; rows that were not manually disabled return to `is_disabled = false` and `disabled_reason` is set to a non-cascaded value. Per-model toggles via `PUT /agents/model-configs/{id}/models/{model_name}/disabled` are observed to set `disabled_reason = manual` on disable and clear it on enable, while a concurrent vendor-disabled state remains the cascade source. This check must run against the real database, not against mocks, and must query the `model_availability` table directly to confirm the persisted state.
	- **New mandatory real-DB check — per-guardrail `(model_id, model_name, period)` uniqueness**: WHEN a second per-period guardrail is created for the same `(model_id, model_name, period)` pair, the database enforces the uniqueness rule and the API returns 409. Verify the underlying index/constraint exists in the schema (e.g. via `information_schema`) and the second insert is rejected at the database level (or via SQLAlchemy's unique-constraint violation, mapped to a 409).
	- **New mandatory real-DB check — pre-execution availability persistence of block events**: WHEN the pre-execution availability check returns `vendor_disabled` or `model_disabled` against a real session launch, THEN a corresponding `ExecutionLogEntry` row exists with the correct `event_category` (`vendor_disabled` or `model_disabled`), a stable reason string, and a correlation id linking the block to the originating availability check. This is observed in the real database, not via mocks.

- Real-backend E2E variant (no `page.route` request mocking):
	- At least one E2E suite must hit real backend and real DB for this change.
	- Minimum required real-backend scenario: runtime topology + terminate cascade + policy/log visibility in one run.
	- Recommended additional real-backend scenarios: model-usage posture transitions, recursion run-block preflight, vendor cascade disable + per-model disable + preflight availability block, and per-guardrail CRUD including 409 on duplicate `(model_id, model_name, period)`.

## 6) Execution Checklist (Coverage Completion)

- [ ] AC1 covered by E2E-A1/A3 + backend/runtime guardrail service tests.
- [ ] AC2 covered by E2E-A1 + model/agent guardrail default-posture tests.
- [ ] AC3 covered by E2E-A2 + log/policy-event backend/frontend tests.
- [x] AC4 covered by E2E-B1/B9/B10/B11 + per-period model-usage CRUD endpoint/service tests + frontend hierarchy (F) + ModelUsageGuardrailDialog; vendor disable cascade covered by E2E-B6 + H area.
- [x] AC5 covered by E2E-B1/B9/C3 + dashboard component/hook tests + ModelUsageGuardrailDialog + VendorModelGuardrailPanel (F) + RuntimeControlDashboardPage.
- [ ] AC6 covered by E2E-B2/B3 + posture transition service tests.
- [ ] AC7 covered by E2E-C1 + sessions/topology backend tests.
- [ ] AC8 covered by E2E-C2 + runtime topology panel tests.
- [ ] AC9 covered by E2E-C3 + integrated dashboard rendering tests.
- [ ] AC10 covered by E2E-D1/D3 + terminate endpoint tests.
- [ ] AC11 covered by E2E-D2 + cascade outcome service tests.
- [ ] AC12 covered by E2E-D4 + explicit denial handling tests.
- [ ] AC13 covered by E2E-E2 + create-context recursion validation tests.
- [ ] AC14 covered by E2E-E3/E4 + update/run-context recursion validation tests.
- [ ] AC15 covered by E2E-A2/D2 + H area (model_disabled and vendor_disabled log events) + policy/termination log category tests.
- [ ] **AC-vendor-disable (new)** covered by E2E-B6/H1 + vendor/model availability endpoint tests + cascade service tests + real-DB cascade check + VendorModelGuardrailPanel cascade-source badge.
- [ ] **AC-model-disable (new)** covered by E2E-B8/H2 + per-model availability endpoint tests + execution log event tests + pre-execution availability check tests.
- [ ] **AC-cascade-source-visibility (new)** covered by E2E-B6/B7 + F area cascade-source badge tests + cascade service tests.
- [ ] **AC-pre-execution-availability (new)** covered by E2E-H1/H2/H3/H5 + `POST /api/v1/agents/preflight/availability` endpoint tests + `PreExecutionAvailabilityCheck` service tests + Agent Runtime session-orchestrator integration test + real-DB block-event persistence check.
- [ ] **AC-multi-vendor-same-model (new)** covered by E2E-H3 + `POST /api/v1/agents/preflight/availability` multi-vendor reason test + `GET /agents/model-availability` hierarchy test.
- [ ] **AC-no-forced-4-period (new)** covered by E2E-B9 + per-period CRUD endpoint test (single period create) + frontend period-select filter test.
- [ ] **AC-per-guardrail-CRUD (new)** covered by E2E-B9/B10/B11 + per-period CRUD endpoint tests including 409 on duplicate `(model_id, model_name, period)` + VendorModelGuardrailPanel per-guardrail toggle/remove tests.
- [ ] **AC-log-disabled-model-and-vendor (new)** covered by H area execution log tests + real-DB block-event persistence check + E2E-H1/H2.
- [x] Backend changed-area tests pass (22/22 passing; +4 new unit-roundtrip tests in `test_model_usage_guardrails_api.py` per FIX-20260601-153000).
- [ ] **New backend test groups (vendor/model availability)**: `backend/tests/api/v1/test_model_availability_api.py` and `backend/tests/integration/test_model_availability_cascade.py` and `backend/tests/integration/test_preflight_availability.py` added and all passing.
- [x] Frontend changed-area tests pass (17/17 passing; +1 new `ModelUsageGuardrailDialog.unit.test.tsx` and +1 new unit-suffix assertion in `ModelUsageGuardrailManagement.test.tsx` per FIX-20260601-153000).
- [ ] **New frontend test group (hierarchy)**: `frontend/src/__tests__/VendorModelGuardrailPanel.test.tsx` added and passing; existing `ModelUsageGuardrailManagement.test.tsx` extended to cover the new vendor → model → guardrail hierarchy.
- [ ] E2E changed-area tests pass including real-backend variant; new E2E scenarios E2E-B6, E2E-B7, E2E-B8, E2E-B9, E2E-B10, E2E-B11, E2E-H1, E2E-H2, E2E-H3, E2E-H4, E2E-H5 added to `e2e/tests/runtime-control-dashboard.spec.ts` (or new spec file) and passing.
- [ ] Real DB integration validation completed and recorded, including the new mandatory real-DB checks: vendor cascade materialises on child `ModelAvailability` rows; per-guardrail `(model_id, model_name, period)` uniqueness; pre-execution availability block event persistence.

## 7) Test File Planning Targets

Testing paths (from `docs/config.yaml`):
- `backend/tests/`
- `frontend/src/__tests__/`
- `e2e/tests/`
- `mcp-demo-app/tests/`

Existing relevant test files:
- `backend/tests/api/v1/test_agent_runtime_controls_api.py`
- `backend/tests/api/v1/test_model_usage_guardrails_api.py`
- `backend/tests/unit/test_agent_guardrails.py`
- `backend/tests/integration/test_runtime_control_persistence.py`
- `backend/tests/integration/test_model_guardrail_persistence.py`
- `frontend/src/__tests__/AgentInstanceDashboard.runtime-control.test.tsx`
- `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx`
- `frontend/src/__tests__/RuntimeTopologyPanel.test.tsx`
- `frontend/src/__tests__/NodeTerminationDialog.test.tsx`
- `frontend/src/__tests__/ModelUsageGuardrailDialog.modelDropdown.test.tsx`
- `frontend/src/__tests__/ModelUsageGuardrailDialog.unit.test.tsx`
- `frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx`
- `e2e/tests/runtime-control-dashboard.spec.ts`

New test files (added for the vendor → model → guardrail hierarchy refinement):
- `backend/tests/api/v1/test_model_availability_api.py` (new): endpoint coverage for `PUT /api/v1/agents/model-configs/{id}/disabled`, `PUT /api/v1/agents/model-configs/{id}/models/{model_name}/disabled`, `GET /api/v1/agents/model-availability`, and `POST /api/v1/agents/preflight/availability`.
- `backend/tests/integration/test_model_availability_cascade.py` (new): real-DB and service-level coverage of the vendor cascade rule — disable vendor → all child `ModelAvailability` rows flip to `is_disabled = true` and `disabled_reason = vendor_cascaded`; re-enable vendor → prior manual state is restored; per-model toggles set `disabled_reason = manual`.
- `backend/tests/integration/test_preflight_availability.py` (new): service + integration coverage of `PreExecutionAvailabilityCheck.evaluate` across vendor-only, model-only, both, multi-vendor same model name, and unknown model; covers the Agent Runtime session-orchestrator invocation path and the resulting execution-log block event.
- `frontend/src/__tests__/VendorModelGuardrailPanel.test.tsx` (new): three-level hierarchy rendering, cascade-source badge, per-guardrail CRUD affordances (toggle, remove), per-model enable/disable toggle, per-vendor enable/disable toggle with cascade, period-select filter for the inline "Add guardrail" form, and permission/error state rendering.
- `e2e/tests/runtime-control-dashboard.spec.ts` (extended): add E2E-B6, E2E-B7, E2E-B8, E2E-B9, E2E-B10, E2E-B11, E2E-H1, E2E-H2, E2E-H3, E2E-H4, E2E-H5; add a real-backend scenario covering vendor cascade + per-model disable + preflight block + execution-log visibility in one run.

Expanded planning targets for this change:
- Backend API/integration
	- Runtime topology projection coverage (`/agents/runtime/topology`) including edge cardinality and status filters.
	- Termination request/outcome coverage (`/agents/runtime/terminate`, `/agents/runtime/terminate/{id}`) including denial and partial completion.
	- Policy event endpoint coverage (`/agents/runtime/policy-events`) category and payload shape, including new `model_disabled` and `vendor_disabled` event categories.
	- Recursion validation contexts on create/update/run with detailed finding assertions.
	- **Per-period model-usage guardrail CRUD** (`/agents/guardrails/model-usage-limits`) including 409 on duplicate `(model_id, model_name, period)`, posture refresh, and the `unit` round-trip.
	- **Vendor and model availability endpoints** (`PUT /agents/model-configs/{id}/disabled`, `PUT /agents/model-configs/{id}/models/{model_name}/disabled`, `GET /agents/model-availability`, `POST /agents/preflight/availability`) including authorization, cascade behaviour, and multi-vendor same model name resolution.
	- Real-DB lifecycle persistence validation for governance entities, including the new mandatory real-DB checks (cascade materialisation, `(model_id, model_name, period)` uniqueness, availability block event persistence).
- Frontend component/hook
	- `RuntimeTopologyPanel` selection, empty/error states, and terminate affordance gating.
	- `NodeTerminationDialog` scope/reason UX and API error rendering.
	- `ModelUsageGuardrailPanel` posture state rendering and refresh synchronization; extended to the new vendor → model → guardrail hierarchy.
	- `VendorModelGuardrailPanel` (new): three-level hierarchy, cascade-source badge, per-guardrail CRUD, per-vendor/per-model disable toggles with cascade, period-select filter.
	- `LogViewer`/`WorkingStepsPanel` policy-vs-functional event distinction, including the new `model_disabled` and `vendor_disabled` event categories.
	- `useRuntimeTopology`, `useNodeTermination`, `useModelUsagePosture`, `useModelUsageLimits`, `useModelAvailability`, `usePreflightAvailability` query/mutation reliability; cache invalidation across vendor/model/guardrail mutations.
- E2E
	- Coverage of all scenario families E2E-A through E2E-E, E2E-B6–E2E-B11, and E2E-H1–E2E-H5.
	- One mandatory real-backend suite validating topology + cascade termination + log/policy visibility end-to-end.
	- Recommended additional real-backend suites: vendor cascade disable + per-model disable + preflight availability block + execution-log visibility; per-guardrail CRUD including 409 on duplicate `(model_id, model_name, period)`.
