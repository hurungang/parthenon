## Technical Overview
This change introduces a policy-safe runtime control surface that unifies guardrail behavior across direct and delegated execution while adding operator visibility and control over active execution trees. The implementation keeps execution inside Agent Runtime, keeps persistence and policy authority inside Control Center, and uses Communication Hub as the orchestrating transport between UI and runtime services. The model-usage guardrail surface is being reshaped from a flat per-model row with all four period limits baked in into a vendor → model → guardrail hierarchy: vendors are listed and can be disabled (cascading to all of their models), each model has its own enable/disable row with a visible cascade source, and each model carries one to four per-period guardrail rows, each with its own enforcement posture and active toggle. A new pre-execution availability check is performed by Agent Runtime via Control Center before any dispatch, and a denial produces a policy-block outcome. The design also adds recursion-risk preflight checks at create, update, and run entry points, observe-only threshold alerts in execution logs, and permission-gated node termination with cascade behavior for delegated descendants.

Critical architecture constraints enforced by this design:
- Three backend services remain segregated by responsibility.
- Agent execution occurs only in Agent Runtime services.
- Only Control Center owns and writes runtime governance persistence.
- Agent contexts never receive sensitive identity tokens or database credentials.

## Component Breakdown
### Frontend Runtime Operations
- RuntimeControlDashboardPage (implemented as standalone page at `/agents/runtime-control`): consolidated live topology, selected-node details, model-usage guardrail panel, and operator controls for terminate actions. Hosts the new "Model Guardrails" view that replaces the previous flat per-model panel.
- Model Guardrails view (new section on RuntimeControlDashboardPage): renders the vendor → model → guardrail hierarchy. Vendors expand to their models, models expand to their guardrails. Per-vendor and per-model enable/disable toggles, the cascade source badge, and the inline add-guardrail form all live here.
- VendorModelGuardrailPanel (new): hierarchy-aware panel that supersedes the previous flat `ModelUsageGuardrailPanel`. Renders vendor rows (with vendor enable/disable toggle and enabled-model count) expandable to model rows (with per-model enable/disable toggle, cascade source indicator, and enabled-guardrail count) expandable to guardrail rows (with period, limit, unit, posture state, and per-guardrail enable, edit, and remove controls). Uses the standard dialog error-handling pattern for API/permission failures and localizes all copy through i18next.
- AddGuardrailForm (new): inline (non-modal) form rendered inside an expanded model row inside `VendorModelGuardrailPanel`. Filters the period select to only periods not yet configured on that model. On submit, dispatches a single per-period create call. Reuses the standard dialog error-handling pattern for inline API/permission failures.
- Obsolete: `ModelUsageGuardrailPanel` (flat per-model row with all four period limits) and `ModelUsageGuardrailDialog` (modal create/edit form) are superseded by `VendorModelGuardrailPanel` and `AddGuardrailForm` and will be removed in the rework.
- RuntimeTopologyDiagram (existing): SVG-based live delegation topology reused unchanged.
- RuntimeTopologyPanel (existing, retained for compatibility): legacy flat-card grouped-by-depth fallback.
- NodeTerminationDialog (existing): permission-aware terminate request flow with cascade scope and audit reason capture.
- Existing execution log stack reused for policy visibility:
  - LogViewer
  - WorkingStepsPanel
  - LogPresenter
  - useExecutionLogs

Responsibilities:
- Surface observe-only threshold alerts as first-class operator-visible log events.
- Enforce permission-aware UX states for terminate actions and disable toggles.
- Keep all UI text localized through i18next keys.
- Reflect the new hierarchy (vendor → model → guardrail) in operator views and keep the cascade source visible.

### Communication Hub Orchestration Layer
- Communication Hub receives dashboard topology, terminate, and availability-toggle requests, and brokers them to policy and runtime services.
- It does not become a database writer and does not perform execution itself.
- It returns policy outcomes and runtime action results back to frontend in operator-consumable form.
- It brokers the new pre-execution availability check between Agent Runtime and Control Center.

Responsibilities:
- Transport-level orchestration for active topology retrieval, terminate commands, vendor/model disable toggles, and preflight availability calls.
- Consistent propagation of correlation identifiers for audit and log stitching.

### Control Center Policy and Persistence Layer
- Owns recursion/dead-loop validation authority for create, update, and run initiation checks.
- Owns authorization decisions for node termination requests and for vendor/model disable toggles.
- Owns the ModelAvailability Authority: the vendor-level `is_disabled` state on `ModelConfig` and the per-model `ModelAvailability` rows with `disabled_reason` of `manual` or `vendor_cascaded`.
- Exposes the pre-execution availability contract consumed by Agent Runtime.
- Owns persistence for topology projection, validation findings, guardrail policy outcomes, termination cascade outcomes, per-guardrail usage limit configurations, and period-rollup snapshots.
- Manages default guardrail enforcement mode; new guardrails default to terminate unless an operator explicitly overrides the posture.

Responsibilities:
- Enforce policy decisions before runtime operations execute.
- Persist governance events and outcomes for audit/compliance.
- Expose read models needed by runtime dashboard and log surfaces, including model-usage posture projection and the full vendor → model → enabled state.
- Aggregate model usage data reported by Agent Runtime into period-rollup snapshots per model.

### Agent Runtime Execution Layer
- Continues to execute agents and delegated runs.
- Applies unified guardrail enforcement for root and delegated execution paths.
- Performs the pre-execution availability check before dispatch: calls the Control Center preflight endpoint for the resolved model. On allow, dispatch proceeds; on deny, dispatch is blocked and a policy-block outcome is recorded with the appropriate `AgentJob.termination_category` (`model_disabled` or `vendor_disabled`).
- Executes terminate commands and reports per-node outcomes for cascade operations.

Responsibilities:
- Never bypass policy decisions issued by Control Center.
- Emit structured observe-only guardrail events, availability-block events, and termination outcomes.
- Avoid direct persistence writes outside approved Control Center channels.

### Shared Domain and Schema Layer
- Schema and model extensions define governance entities and relationships for this change.
- `ModelConfig` gains the vendor-level `is_disabled` boolean.
- `ModelGuardrailConfiguration` is restructured to one row per `(model, period)` with `(model_id, model_name, period)` uniqueness, dropping the four period-limit columns and adding `period` (enum) plus `limit_value` (int).
- `ModelAvailability` is introduced as a first-class entity (per-model enabled state with `disabled_reason` of `manual` or `vendor_cascaded`).
- Existing agent/session schemas are extended for new policy, availability, and termination metadata.

Responsibilities:
- Preserve strong typing and explicit enums for policy outcomes.
- Ensure frontend/backend contract compatibility for topology, availability, and log rendering.

## API Changes
### Existing Endpoints to Extend
- GET /api/v1/agents/sessions
  - Extend response shape to support active-runtime dashboard needs, including delegation context, availability state, and policy posture hints.
- GET /api/v1/agents/sessions/{session_id}/logs
  - Include structured policy event fields that let frontend distinguish observe-only alerts, authorization denials, model-disabled blocks, vendor-disabled blocks, and functional failures.
- GET /api/v1/agents/sessions/{session_id}/execution-logs
  - Surface observe-only, availability-block, and termination-related context in log metadata where applicable.
- POST /api/v1/agents/sessions
  - Add run preflight recursion/dead-loop validation gate in `launch_agent_session` before session is queued. (Originally planned at gateway/{agent_type_id}/init; integration was placed at the management API session launch path instead.)
- PUT /api/v1/agents/types/{type_id}
  - Add recursion/dead-loop validation gate during update flow.
- POST /api/v1/agents/types
  - Add recursion/dead-loop validation gate during create flow.

### Model-Usage Guardrail Endpoints — Updated Semantics
- POST /api/v1/agents/guardrails/model-usage-limits
  - Now creates exactly ONE guardrail (one period) per call. Request body shape: `model_id` (FK UUID), `model_name`, `period` (enum: `hour`/`day`/`week`/`month`), `limit_value` (int), `unit` (enum: `k`/`tokens`, default `k`), `enforcement_posture` (enum: `terminate`/`observe_only`, default `terminate`), `is_active` (boolean, default `true`). The four separate period-limit fields from the previous shape are removed. The `(model_id, model_name, period)` uniqueness rule is enforced server-side and returns a deterministic conflict on duplicate.
- PUT /api/v1/agents/guardrails/model-usage-limits/{id}
  - Uses the same per-guardrail shape (`period`, `limit_value`, `unit`, `enforcement_posture`, `is_active`, `details`); partial updates are supported.
- GET /api/v1/agents/guardrails/model-usage-limits and GET /api/v1/agents/guardrails/model-usage-limits/{id}
  - Read shape updated to the per-guardrail row (one period per item) so the dashboard can render a model's guardrails as a list of up to four rows.
- DELETE /api/v1/agents/guardrails/model-usage-limits/{id}
  - Removes a single per-period guardrail row.

### New Endpoints to Add
- GET /api/v1/agents/runtime/topology
  - Returns active runtime topology projection with nodes, edges, depth, root mapping, and node statuses.
- POST /api/v1/agents/runtime/terminate
  - Accepts node-targeted terminate requests with scope and operator reason; returns accepted/denied outcome with correlation identifier.
- GET /api/v1/agents/runtime/terminate/{request_id}
  - Returns full cascade outcome details for root and child nodes.
- GET /api/v1/agents/runtime/policy-events
  - Returns filtered policy events for dashboard and execution-log correlation views.
- GET /api/v1/agents/guardrails/model-usage-posture
  - Returns current period rollup values and posture state (within_limit, approaching_limit, breached) for all configured per-period guardrails; consumed by the runtime dashboard.
- PUT /api/v1/agents/model-configs/{config_id}/disabled
  - Toggles vendor-level `is_disabled` on `ModelConfig`. Triggers the cascade onto every `ModelAvailability` row for the vendor (set `is_disabled = true`, `disabled_reason = vendor_cascaded`); re-enable restores each row to its prior manual state. Permission-gated.
- PUT /api/v1/agents/model-configs/{config_id}/models/{model_name}/disabled
  - Toggles per-model availability for a single `(vendor, model_name)` pair. Operator-driven changes set `disabled_reason = manual`. Permission-gated.
- GET /api/v1/agents/model-availability
  - Returns the full vendor → model → enabled state for the dashboard hierarchy, including the cascade source indicator on each model row (`disabled_reason` of `manual` or `vendor_cascaded`).
- POST /api/v1/agents/preflight/availability
  - Agent Runtime pre-execution check. Request: `model_id` (FK UUID) and `model_name`. Response: `{ allowed: boolean, reason?: string, disabled_reason?: "manual" | "vendor_cascaded" }`. Called by Agent Runtime before dispatch; on deny, the run is recorded with the appropriate `AgentJob.termination_category` (`model_disabled` or `vendor_disabled`).

### Inter-Service Transport: Communication Hub → Agent Runtime
- `POST /internal/agent/execute` (Communication Hub) forwards Control Center's trigger to Agent Runtime with a 30s read timeout and 3-attempt retry (delays 0s, 2s, 4s).
- Failure-mode → status mapping to the caller:
  - 4xx from Agent Runtime → **502** (non-retriable, fail fast on validation).
  - 5xx from Agent Runtime → **502** after retries are exhausted (retriable).
  - `httpx.TimeoutException` (Read/Connect/Write/Pool) → **503** after retries are exhausted (transient availability issue).
  - `httpx.ConnectError` (connection refused) → **503** after retries are exhausted.
  - Any other unexpected error → **502**.
- The retry contract is covered by `tests/communication_hub/api/internal/test_agent_execute.py`.

### Authorization and Policy Semantics
- Terminate operations require explicit runtime terminate permission checks.
- Vendor and per-model disable toggles require explicit policy-management permission checks.
- Pre-execution availability requests are authenticated but enforced as policy; the request body is trusted only after agent identity and certificate validation.
- Unauthorized terminate, disable, and preflight requests return explicit denial outcomes, not generic transport errors.
- Recursion validation failures return policy-block outcomes that prevent session start.

## State Management
### Frontend Data Fetch and Synchronization
- React Query manages server-state for active sessions, topology projection, termination status, policy events, model-usage posture, vendor disable toggles, per-model disable toggles, and per-guardrail CRUD.
- Existing `useExecutionLogs` and session log streams continue to drive execution-log surfaces.
- Local component state manages expanded vendors/models, selected topology node, terminate dialog state, disable toggle pending state, and action-specific UI feedback.

### UI State Requirements
- Runtime dashboard state includes:
  - Active node selection
  - Permission capability flags
  - Pending terminate request status
  - Last policy event cursor for incremental updates
  - Expanded vendor/model rows in the Model Guardrails view
  - Pending disable-toggle state per vendor and per model
- Terminate dialog state includes:
  - Target node and cascade scope
  - Operator reason
  - Inline permission/API error surface
- Model Guardrails view state includes:
  - Expanded vendors and models
  - Inline add-guardrail form open/closed
  - Form period select (filtered to periods not yet configured on the model)
  - Inline API/permission error surface for vendor, model, and guardrail actions

### Log Presentation State
- LogPresenter remains the canonical transform layer from raw entries to structured spans.
- Observe-only threshold alerts, terminate outcomes, model-disabled blocks, and vendor-disabled blocks appear as structured policy events in the same execution log surface.
- No flat-table replacement for execution log visualization is introduced.

## Data Access Patterns
### Service-Boundary Data Flow
- Frontend calls backend APIs only and never accesses database directly.
- Communication Hub orchestrates requests but does not own runtime governance persistence.
- Control Center is the only component writing policy, availability, topology, and termination governance records.
- Agent Runtime emits events, performs the pre-execution availability check via Control Center, and receives policy decisions through service clients; it does not own direct governance persistence writes.

### Read and Write Ownership
- Control Center write ownership:
  - Recursion validation checks and findings
  - Runtime topology projection records
  - Termination request records and cascade outcomes
  - Guardrail policy evaluation and threshold-event records
  - `ModelAvailability` row writes (both manual toggles and vendor cascade materialisation)
  - Vendor `is_disabled` toggle writes (and the resulting cascade transaction)
- Control Center read ownership (exposed to UI and Agent Runtime via APIs):
  - Full vendor → model → enabled state (GET /api/v1/agents/model-availability)
  - Active topology view models
  - Termination request and cascade status views
  - Pre-execution availability decisions (POST /api/v1/agents/preflight/availability)
- Agent Runtime execution ownership:
  - Session execution lifecycle and delegated execution behavior
  - Pre-execution availability check (calls Control Center preflight before dispatch)
  - Guardrail checks during execution loop
  - Terminate command execution with outcome emission
  - Availability-block policy outcomes when preflight denies
- Frontend read ownership:
  - Active topology view models
  - Vendor → model → guardrail hierarchy view
  - Execution log and policy event views
  - Termination request and cascade status views

### Sensitive Data Handling
- Agent contexts cannot access identity tokens or database credentials.
- Service-to-service calls continue certificate-based validation and least-privilege policy.
- Policy and authorization outcomes are exposed to UI without leaking sensitive secrets.
- The pre-execution availability check is performed via existing secure service channels (Communication Hub → Control Center) so agent contexts never see vendor credential material.

## Complete Code Reference Map
| Symbol | Type | Description | File | Status |
| --- | --- | --- | --- | --- |
| create_agent_type | endpoint | Agent type create flow to receive recursion precheck integration | backend/app/api/v1/agents.py | Existing |
| update_agent_type | endpoint | Agent type update flow to receive recursion precheck integration | backend/app/api/v1/agents.py | Existing |
| list_agent_sessions | endpoint | Session list route to support runtime dashboard projections | backend/app/api/v1/agents.py | Existing |
| get_session_execution_logs | endpoint | Structured execution log entries consumed by log UI | backend/app/api/v1/agents.py | Existing |
| get_session_prompt_logs | endpoint | Prompt/system log records used by execution detail views | backend/app/api/v1/agents.py | Existing |
| gateway_init | endpoint | Gateway-level run initiation path; recursion preflight was integrated in `launch_agent_session` instead | backend/app/api/gateway/lifecycle.py | Existing |
| launch_agent_session | endpoint | Session launch path where run preflight recursion/dead-loop validation gate was integrated | backend/app/api/v1/agents.py | Existing |
| AgentRuntimeExecutor._precheck_delegation_graph | method | Existing delegation cycle guardrail precheck logic to expand for recursion risk hardening | backend/app/services/agents/runtime_executor.py | Existing |
| AgentRuntimeExecutor._check_runtime_limits_or_raise | method | Runtime guardrail limit enforcement point across execution loop | backend/app/services/agents/runtime_executor.py | Existing |
| detect_cycle_path | function | Delegation-cycle detection helper used by runtime prechecks | backend/app/services/agents/guardrails.py | Existing |
| ExecutionLogEntry | model | Execution log persistence model to extend with policy-event classification fields | backend/app/db/models/session_logs.py | Existing |
| AgentJob | model | Session model to extend with parent/root/depth, per-guardrail context, availability-block attribution, and terminate attribution fields | backend/app/db/models/agents.py | Existing |
| AgentTypeRead | schema | Agent type response schema to include recursion validation posture metadata | backend/app/schemas/agents.py | Existing |
| AgentTypeCreate | schema | Agent type create schema with validation entrypoint integration | backend/app/schemas/agents.py | Existing |
| AgentTypeUpdate | schema | Agent type update schema with validation entrypoint integration | backend/app/schemas/agents.py | Existing |
| AgentInstanceDashboardPage | page | Execution dashboard session list with filter controls and execution details dialog; runtime-control panels (topology, model guardrails, termination) were moved to the dedicated `RuntimeControlDashboardPage` per FIX-20260601-145208 | frontend/src/pages/agents/AgentInstanceDashboardPage.tsx | Existing |
| AgentJobPage | page | Session detail page hosting status, logs, and stream behavior | frontend/src/pages/agents/AgentJobPage.tsx | Existing |
| useExecutionLogs | hook | Fetches execution prompt logs and supports refetch-on-completion behavior | frontend/src/hooks/useExecutionLogs.ts | Existing |
| LogViewer | component | Canonical execution log rendering container | frontend/src/components/executions/LogViewer.tsx | Existing |
| WorkingStepsPanel | component | Span-based structured execution visualization | frontend/src/components/executions/WorkingStepsPanel.tsx | Existing |
| LogPresenter.toStructuredLog | method | Transforms raw execution entries into structured summary and spans | frontend/src/services/LogPresenter.ts | Existing |
| TopologyDiagramRenderer | component | Existing topology renderer reused for runtime delegation topology views | frontend/src/components/agents/TopologyDiagramRenderer.tsx | Existing |
| ExecutionLogEntry | frontend type | Frontend log entry contract to extend with policy-event metadata fields | frontend/src/types/index.ts | Existing |
| AgentJob | frontend type | Frontend session type to extend with runtime topology, availability-block attribution, and termination attribution fields | frontend/src/types/index.ts | Existing |
| RuntimeTopologyController | service | Control Center service for active runtime topology projection queries | backend/app/services/control_center/runtime_topology_controller.py | Implemented |
| TerminationOrchestrator | service | Control Center service for permission-gated node terminate and cascade orchestration | backend/app/services/control_center/termination_orchestrator.py | Implemented |
| RecursionValidationService | service | Control Center service for create/update/run recursion and dead-loop checks | backend/app/services/control_center/recursion_validation_service.py | Implemented |
| RuntimeControlRouter | router | Agents runtime-control API router for topology, terminate, and policy event endpoints | backend/app/api/v1/agents.py | Implemented |
| get_runtime_topology | endpoint | Returns active runtime topology projection for the dashboard | backend/app/api/v1/agents.py | Implemented |
| request_runtime_termination | endpoint | Performs permission-gated terminate requests with explicit denial reasons | backend/app/api/v1/agents.py | Implemented |
| get_runtime_termination_outcomes | endpoint | Returns per-node cascade outcomes for a termination request | backend/app/api/v1/agents.py | Implemented |
| list_runtime_policy_events | endpoint | Returns structured policy/guardrail/termination log events for runtime correlation views | backend/app/api/v1/agents.py | Implemented |
| RuntimeTerminateRequest | schema | Request schema for node terminate API with scope and operator reason | backend/app/schemas/agents.py | Implemented |
| TerminationRequestRead | schema | Response schema for terminate request outcomes and permission evaluations | backend/app/schemas/agents.py | Implemented |
| RuntimeTopologyRead | schema | Response schema for active runtime topology nodes and edges | backend/app/schemas/agents.py | Implemented |
| RuntimeControlDashboardPage | page | Dedicated runtime control dashboard at `/agents/runtime-control` with live SVG topology, selected-node details, the new Model Guardrails view (vendor → model → guardrail hierarchy), and terminate entry point | frontend/src/pages/agents/RuntimeControlDashboardPage.tsx | Implemented |
| RuntimeTopologyDiagram | component | SVG-based live delegation topology with rounded-rect nodes, status fills, arrow-marked bezier connectors, click-to-select, and risk highlighting | frontend/src/components/agents/RuntimeTopologyDiagram.tsx | Implemented |
| RuntimeTopologyPanel | component | Legacy runtime execution-tree view with selected-node details and terminate entry point (flat card list, retained for compatibility) | frontend/src/components/agents/RuntimeTopologyPanel.tsx | Implemented |
| NodeTerminationDialog | component | Terminate modal with permission/API denial feedback and cascade scope selection | frontend/src/components/agents/NodeTerminationDialog.tsx | Implemented |
| useRuntimeTopology | hook | Frontend server-state hook for active runtime topology and polling refresh | frontend/src/hooks/useRuntimeTopology.ts | Implemented |
| useNodeTermination | hook | Frontend mutation/query hooks for terminate requests and cascade outcome polling | frontend/src/hooks/useNodeTermination.ts | Implemented |
| ModelGuardrailEvaluation | model | Persistence model for per-run model guardrail policy evaluation outcomes (implemented as ModelGuardrailEvaluation) | backend/app/db/models/model_guardrail_evaluation.py | Implemented |
| GuardrailThresholdEvent | model | Persistence model for observe-only threshold alerts | backend/app/db/models/guardrail_threshold_event.py | Implemented |
| AgentRunRelationship | model | Parent-child runtime relationship model for active topology mapping | backend/app/db/models/agent_run_relationship.py | Implemented |
| TerminationRequest | model | Termination request record with permission outcome and request lifecycle | backend/app/db/models/termination_request.py | Implemented |
| TerminationCascadeOutcome | model | Per-node cascade result model for terminate orchestration | backend/app/db/models/termination_cascade_outcome.py | Implemented |
| SopRecursionValidationCheck | model | Validation-check audit model for create/update/run contexts | backend/app/db/models/sop_recursion_validation_check.py | Implemented |
| SopRecursionValidationFinding | model | Detailed recursion-risk finding model linked to validation checks | backend/app/db/models/sop_recursion_validation_finding.py | Implemented |
| ModelGuardrailEnforcementPosture | enum | Enforcement posture enum used by per-period model-usage guardrail rows; default terminate for new configurations | backend/app/db/models/model_guardrail_configuration.py | Implemented |
| ModelUsageUnit | enum | Unit of measure for per-period model-usage numeric limits and rollups (`k` = thousand tokens, `tokens` = raw tokens); default `k` for new configurations | backend/app/db/models/model_guardrail_configuration.py | Implemented |
| ModelGuardrailConfiguration | model | Operator-configured per-period model usage limit (one row per `(model, period)`) with `period`, `limit_value`, `unit`, `enforcement_posture`, `is_active`; `(model_id, model_name, period)` uniqueness is enforced | backend/app/db/models/model_guardrail_configuration.py | Implemented (reworked) |
| ModelUsagePosture | model | Dashboard-facing model usage posture snapshot per configured period aggregated by Control Center (implemented as ModelUsagePosture) | backend/app/db/models/model_usage_posture.py | Implemented |
| ModelAvailability | model | Per-model enabled state under a vendor with `is_disabled` and `disabled_reason` (`manual` or `vendor_cascaded`); unique on `(vendor_model_config_id, model_name)` | backend/app/db/models/model_availability.py | Planned |
| ModelConfig.is_disabled | column | Vendor-level enable/disable boolean on `model_configs`; when true, every `ModelAvailability` row under the vendor cascades to `is_disabled = true` and `disabled_reason = vendor_cascaded` | backend/app/db/models/agents.py | Planned |
| ModelAvailabilityService | service | Control Center service owning vendor and per-model enabled state; exposes the pre-execution availability check consumed by Agent Runtime and materialises the vendor-cascade transaction | backend/app/services/control_center/model_availability_service.py | Planned |
| ModelAvailabilityDisabledReason | enum | Disabled-reason enum on `ModelAvailability`: `manual` (operator-driven per-model toggle) or `vendor_cascaded` (vendor `is_disabled` cascade) | backend/app/db/models/model_availability.py | Planned |
| ModelGuardrailPeriod | enum | Period enum on `ModelGuardrailConfiguration`: `hour`, `day`, `week`, `month`; one period per row | backend/app/db/models/model_guardrail_configuration.py | Planned |
| ModelUsageGuardrailService | service | Control Center service for per-guardrail CRUD and period-rollup aggregation (reworked from the previous flat per-model shape) | backend/app/services/control_center/model_usage_guardrail_service.py | Implemented (reworked) |
| list_model_usage_limits | endpoint | Lists configured per-guardrail rows (one period per item) for operators | backend/app/api/v1/agents.py | Implemented (reworked) |
| create_model_usage_limit | endpoint | Creates a single per-period guardrail row; body is `model_id`, `model_name`, `period`, `limit_value`, `unit`, `enforcement_posture`, `is_active`; returns 409 on `(model_id, model_name, period)` conflict | backend/app/api/v1/agents.py | Implemented (reworked) |
| get_model_usage_limit | endpoint | Fetches a single per-period guardrail configuration | backend/app/api/v1/agents.py | Implemented (reworked) |
| update_model_usage_limit | endpoint | Updates a single per-period guardrail row using the per-guardrail shape | backend/app/api/v1/agents.py | Implemented (reworked) |
| delete_model_usage_limit | endpoint | Deletes a single per-period guardrail configuration | backend/app/api/v1/agents.py | Implemented (reworked) |
| get_model_usage_posture | endpoint | Returns current posture rollups (within_limit, approaching_limit, breached) for configured per-period guardrails | backend/app/api/v1/agents.py | Implemented |
| set_vendor_disabled | endpoint | Toggles vendor-level `is_disabled` on `ModelConfig` and triggers the cascade transaction onto `ModelAvailability` | backend/app/api/v1/agents.py | Planned |
| set_model_availability | endpoint | Toggles a single `(vendor, model_name)` `ModelAvailability` row; sets `disabled_reason = manual` on operator-driven changes | backend/app/api/v1/agents.py | Planned |
| list_model_availability | endpoint | Returns the full vendor → model → enabled state for the dashboard hierarchy, including the cascade source indicator on each model row | backend/app/api/v1/agents.py | Planned |
| preflight_availability | endpoint | Agent Runtime pre-execution availability check; accepts `model_id` + `model_name`, returns `{ allowed, reason?, disabled_reason? }`; called before dispatch and used to set `AgentJob.termination_category` on deny | backend/app/api/v1/agents.py | Planned |
| AgentRuntimeExecutor._preflight_availability | method | New Agent Runtime hook that calls the Control Center preflight endpoint for the resolved model and either proceeds with dispatch or produces a policy-block outcome with `termination_category` of `model_disabled` or `vendor_disabled` | backend/app/services/agents/runtime_executor.py | Planned |
| ModelUsageGuardrailLimitCreate | schema | Request schema for per-period guardrail creation (`model_id`, `model_name`, `period`, `limit_value`, `unit`, `enforcement_posture`, `is_active`); replaces the previous four-limit shape | backend/app/schemas/agents.py | Implemented (reworked) |
| ModelUsageGuardrailLimitUpdate | schema | Request schema for per-period guardrail update using the per-guardrail shape | backend/app/schemas/agents.py | Implemented (reworked) |
| ModelUsageGuardrailLimitRead | schema | Response schema for a single per-period guardrail row | backend/app/schemas/agents.py | Implemented (reworked) |
| ModelUsagePostureRead | schema | Response schema for model posture rollup query | backend/app/schemas/agents.py | Implemented |
| ModelAvailabilityRead | schema | Response schema for a single `(vendor, model_name)` availability row | backend/app/schemas/agents.py | Planned |
| ModelAvailabilityListRead | schema | Response schema for the full vendor → model → enabled state used by the dashboard hierarchy | backend/app/schemas/agents.py | Planned |
| VendorDisabledUpdate | schema | Request schema for vendor-level `is_disabled` toggle | backend/app/schemas/agents.py | Planned |
| ModelAvailabilityUpdate | schema | Request schema for per-model availability toggle | backend/app/schemas/agents.py | Planned |
| PreflightAvailabilityRequest | schema | Request schema for the Agent Runtime pre-execution availability check | backend/app/schemas/agents.py | Planned |
| PreflightAvailabilityResponse | schema | Response schema for the pre-execution availability check (`allowed`, `reason?`, `disabled_reason?`) | backend/app/schemas/agents.py | Planned |
| ModelUsageGuardrailPanel | component | Flat per-model panel showing all four period limits in one row | frontend/src/components/agents/ModelUsageGuardrailPanel.tsx | ⚠️ Needs Rework — superseded by `VendorModelGuardrailPanel` |
| ModelUsageGuardrailDialog | component | Modal create/edit dialog for the flat per-model row with all four limit fields | frontend/src/components/agents/ModelUsageGuardrailDialog.tsx | ⚠️ Needs Rework — superseded by inline `AddGuardrailForm` |
| VendorModelGuardrailPanel | component | New hierarchy-aware panel rendering vendor rows → model rows → guardrail rows with vendor and per-model enable/disable toggles, cascade source badge, and per-guardrail edit/remove/enable controls | frontend/src/components/agents/VendorModelGuardrailPanel.tsx | Planned |
| AddGuardrailForm | component | New inline (non-modal) form rendered inside an expanded model row in `VendorModelGuardrailPanel`; period select is filtered to periods not yet configured on the model; dispatches a single per-period create call | frontend/src/components/agents/AddGuardrailForm.tsx | Planned |
| useModelUsagePosture | hook | Frontend server-state hook for model-usage posture data and refresh | frontend/src/hooks/useModelUsagePosture.ts | Implemented |
| useModelUsageLimits | hook | Frontend server-state hook for per-guardrail configurations and refresh | frontend/src/hooks/useModelUsagePosture.ts | Implemented |
| useAvailableModels | hook | Frontend hook that flattens `ModelConfig.enabled_models` into `AvailableModel[]` for guardrail configuration surfaces | frontend/src/hooks/useAvailableModels.ts | Implemented |
| useCreateModelUsageLimit | hook | Mutation hook to create a per-period guardrail row using the per-guardrail shape | frontend/src/hooks/useModelUsageGuardrailMutations.ts | Implemented (reworked) |
| useUpdateModelUsageLimit | hook | Mutation hook to update a per-period guardrail row using the per-guardrail shape | frontend/src/hooks/useModelUsageGuardrailMutations.ts | Implemented (reworked) |
| useDeleteModelUsageLimit | hook | Mutation hook to delete a per-period guardrail row | frontend/src/hooks/useModelUsageGuardrailMutations.ts | Implemented (reworked) |
| useModelAvailability | hook | Frontend server-state hook for the full vendor → model → enabled state and refresh | frontend/src/hooks/useModelAvailability.ts | Planned |
| useToggleVendorDisabled | hook | Mutation hook for the vendor-level `is_disabled` toggle (PUT /api/v1/agents/model-configs/{config_id}/disabled) | frontend/src/hooks/useModelAvailabilityMutations.ts | Planned |
| useToggleModelDisabled | hook | Mutation hook for the per-model availability toggle (PUT /api/v1/agents/model-configs/{config_id}/models/{model_name}/disabled) | frontend/src/hooks/useModelAvailabilityMutations.ts | Planned |
| usePreflightAvailability | hook | Mutation hook Agent Runtime (or a server-to-server test harness) uses to call the pre-execution availability check | frontend/src/hooks/usePreflightAvailability.ts | Planned |
| test_agent_runtime_controls_api | test | Backend API tests for recursion validation 422 on create/update and instance termination 204/404 | backend/tests/api/v1/test_agent_runtime_controls_api.py | Implemented |
| test_model_usage_guardrails_api | test | Backend API tests for per-guardrail CRUD endpoints and posture refresh query; extended to cover the `unit` field round-trip and the per-period shape (default `k` on create, explicit value preserved, get returns `unit`, update passes `unit` through, `(model_id, model_name, period)` conflict returns 409) | backend/tests/api/v1/test_model_usage_guardrails_api.py | Implemented (reworked) |
| test_model_availability_api | test | Backend API tests for the four new availability endpoints (vendor toggle, per-model toggle, list, preflight), including the cascade semantics and the deny paths with `disabled_reason` of `manual` and `vendor_cascaded` | backend/tests/api/v1/test_model_availability_api.py | Planned |
| b3c9d4e5f6a7_add_unit_to_model_guardrail_configurations | migration | Alembic migration that adds the `unit` column to `model_guardrail_configurations` with `server_default='k'` and the new `model_usage_unit_enum` PostgreSQL enum | backend/alembic/versions/b3c9d4e5f6a7_add_unit_to_model_guardrail_configurations.py | Implemented |
| restructure_model_guardrails_to_per_period | migration | Alembic migration that drops the four `usage_limit_*` columns from `model_guardrail_configurations`, adds `period` enum and `limit_value` int, adds a unique constraint on `(model_id, model_name, period)`, adds `is_disabled` boolean to `model_configs`, and creates `model_availability` with `(vendor_model_config_id, model_name)` uniqueness, the `disabled_reason` enum, and a backfill of `ModelAvailability` rows for every `(vendor, model_name)` currently in any `ModelConfig.enabled_models` | backend/alembic/versions/<rev>_restructure_model_guardrails_to_per_period.py | Planned |
| test_agent_guardrails | test | Backend unit tests for `detect_cycle_path` and delegation precheck blocking (extended) | backend/tests/unit/test_agent_guardrails.py | Implemented |
| test_runtime_control_persistence | test | Backend integration tests for terminate cascade persistence and denied-request policy outcomes | backend/tests/integration/test_runtime_control_persistence.py | Implemented |
| test_model_guardrail_persistence | test | Backend integration tests for per-guardrail defaults, period posture persistence, and threshold events (extended for the per-period shape) | backend/tests/integration/test_model_guardrail_persistence.py | Implemented (reworked) |
| test_model_availability_persistence | test | Backend real-database lifecycle test for the new schema, the cascade semantics, and the pre-execution availability contract; runs against the migrated real database | backend/tests/integration/test_model_availability_persistence.py | Planned |
| AgentInstanceDashboard.runtime-control.test | test | Frontend tests for dashboard session list loading, permission error, conversation session display, and execution details dialog (runtime-control panels were relocated to the dedicated page in FIX-20260601-145208) | frontend/src/__tests__/AgentInstanceDashboard.runtime-control.test.tsx | Implemented |
| RuntimeTopologyPanel.test | test | Frontend tests for topology grouping/selection and permission-gated terminate control state | frontend/src/__tests__/RuntimeTopologyPanel.test.tsx | Implemented |
| NodeTerminationDialog.test | test | Frontend tests for terminate scope/reason submission and inline permission/API error rendering | frontend/src/__tests__/NodeTerminationDialog.test.tsx | Implemented |
| RuntimeControlDashboardPage.test | test | Frontend tests for the dedicated `/agents/runtime-control` page — route registration, live SVG topology rendering, rect/line counts, and the new Model Guardrails hierarchy view | frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx | Implemented (reworked) |
| ModelUsageGuardrailDialog.modelDropdown.test | test | Frontend tests verifying the model picker is a Select (not free-text) populated from `availableModels` and dispatches `model_id` + `model_name` from the chosen option; also asserts `unit: 'k'` in the save payload | frontend/src/__tests__/ModelUsageGuardrailDialog.modelDropdown.test.tsx | ⚠️ Needs Rework — dialog is being replaced by inline `AddGuardrailForm` |
| ModelUsageGuardrailDialog.unit.test | test | Frontend tests verifying the unit Select in `ModelUsageGuardrailDialog`: default `k`, save dispatches `unit: 'k'`, operator can change the unit and the payload reflects the choice, and edit mode freezes the unit selector | frontend/src/__tests__/ModelUsageGuardrailDialog.unit.test.tsx | ⚠️ Needs Rework — dialog is being replaced by inline `AddGuardrailForm` |
| ModelUsageGuardrailManagement.test | test | Frontend tests for the model usage guardrail panel CRUD flow on the dedicated dashboard (create/edit affordances) | frontend/src/__tests__/ModelUsageGuardrailManagement.test.tsx | ⚠️ Needs Rework — flat panel is being replaced by `VendorModelGuardrailPanel` |
| VendorModelGuardrailPanel.test | test | Frontend tests for the new hierarchy panel: vendor rows with enable/disable toggle, model rows with per-model toggle and cascade source badge, guardrail rows with posture and per-guardrail controls, and standard dialog error-handling | frontend/src/__tests__/VendorModelGuardrailPanel.test.tsx | Planned |
| AddGuardrailForm.test | test | Frontend tests for the inline form: period select filtering to unconfigured periods, single per-period create dispatch, inline API/permission error rendering, and the terminate-default / `k`-default behaviour | frontend/src/__tests__/AddGuardrailForm.test.tsx | Planned |
| runtime-control-dashboard.spec | test | E2E scenarios for observe-only policy visibility, topology/terminate flow, recursion contract, real-backend runtime-control checks, and the new vendor/model availability hierarchy | e2e/tests/runtime-control-dashboard.spec.ts | Implemented (reworked) |
