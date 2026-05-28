## Overview
This change adds deterministic execution guardrails for agent sessions by combining pre-execution delegation graph validation with runtime enforcement of bounded execution. The implementation keeps execution decisions in Agent Runtime and keeps all persistence, policy source-of-truth, and governance logging in Control Center, aligned with top-priority segregation rules in docs/config.yaml. Delivery is phased to reduce risk: contract first, enforcement second, then observability, propagation, and test hardening. Token behavior is mode-aware: conversational sessions expose current-session token consumption and allow continuation, while non-conversational and automated runs keep token-budget enforcement policy.

## Task Checklist

### Phase 1 — Guardrail Contract and Policy Surface
- [x] 1.1 — Define agent-type guardrail policy contract for iterations, timeout, depth, and token budget mode
- [x] 1.2 — Extend Control Center internal data payloads to return effective guardrail policy snapshot
- [x] 1.3 — Add validation rules for policy bounds and fallback mode semantics
- [x] 1.4 — Add integration tests for policy retrieval and invalid policy rejection

### Phase 2 — Pre-Execution Delegation Graph Validation
- [x] 2.1 — Build delegation graph resolver for direct and indirect agent delegation edges
- [x] 2.2 — Implement recursive cycle detection with explicit cycle path output
- [x] 2.3 — Enforce pre-execution block on cyclic graphs before first runtime iteration
- [x] 2.4 — Emit structured pre-execution guardrail decision logs and status payloads

### Phase 3 — Runtime Guardrail Enforcement in Agent Runtime
- [x] 3.1 — Add cumulative iteration accounting across local and delegated execution
- [x] 3.2 — Add delegated depth and delegated-step budget accounting to the runtime context
- [x] 3.3 — Enforce per-agent wall-clock timeout with deterministic termination behavior
- [x] 3.4 — Add mode-aware token guardrail behavior (conversational visibility plus automated enforcement) with unsupported-provider fallback handling

### Phase 4 — Stop-Reason Propagation and Session State Semantics
- [x] 4.1 — Define stop-reason taxonomy for cycle, iteration, depth, timeout, token, and fallback outcomes
- [x] 4.2 — Propagate stop reason through Agent Runtime to Control Center session status updates
- [x] 4.3 — Distinguish guardrail stops from functional failures in persisted session state
- [x] 4.4 — Ensure Communication Hub forwards guardrail terminal outcomes without behavior drift

### Phase 5 — Guardrail Observability and Audit Logging
- [x] 5.1 — Standardize guardrail decision event schema for execution logs
- [x] 5.2 — Capture pre-check and runtime guardrail counters in structured data fields
- [x] 5.3 — Add policy snapshot fingerprint and fallback mode details to audit events
- [x] 5.4 — Add regression assertions for log completeness and stop-reason visibility

### Phase 6 — Verification, Hardening, and Documentation Updates
- [x] 6.1 — Add unit tests for cycle detection edge cases and graph traversal limits
- [x] 6.2 — Add integration tests for timeout, iteration, depth, and token fallback behavior
- [x] 6.3 — Add A2A path tests proving delegated activity counts toward parent execution ceiling
- [x] 6.4 — Update master docs and operational runbooks for guardrail triage semantics

## Phase 1 — Guardrail Contract and Policy Surface

### 1.1 — Define agent-type guardrail policy contract for iterations, timeout, depth, and token budget mode
Description: Define the canonical guardrail policy shape resolved by Control Center and consumed by Agent Runtime at execution start. Include mandatory fields (max_iterations, max_delegation_depth, max_delegated_steps, execution_timeout_seconds) and token controls that are mode-aware (token_budget, token_enforcement_mode, conversational_token_visibility_mode, conversational_continuation_policy).
Done when:
- A single policy schema is documented and versioned for internal service use.
- Mandatory fields have explicit min/max constraints and defaults.
- Token guardrail semantics define conversational visibility and continuation behavior separately from non-conversational and automated enforcement behavior.

### 1.2 — Extend Control Center internal data payloads to return effective guardrail policy snapshot
Description: Add effective guardrail policy to the context returned by Control Center internal data APIs so Agent Runtime can enforce without direct database access.
Done when:
- Agent Runtime context retrieval includes a policy snapshot payload.
- Effective policy resolution follows role and agent-type ownership already used in Control Center.
- No guardrail persistence logic is added to Agent Runtime or Communication Hub.

### 1.3 — Add validation rules for policy bounds and fallback mode semantics
Description: Validate policy values at creation/update and at context-resolution time to prevent invalid runtime states, including mode-aware token policy semantics.
Done when:
- Invalid policy values are rejected with explicit validation messages.
- Conversational policy combinations that imply token hard-stop-only behavior are rejected.
- Fallback mode is required when hard provider token limit is unavailable for non-conversational and automated execution paths.
- Validation behavior is covered by API-level tests.

### 1.4 — Add integration tests for policy retrieval and invalid policy rejection
Description: Add tests for positive and negative guardrail policy resolution paths in Control Center internal APIs.
Done when:
- Tests verify successful retrieval of effective policy snapshot.
- Tests verify invalid policies are rejected and not returned to runtime clients.
- Tests assert no direct database access from Agent Runtime paths.

## Phase 2 — Pre-Execution Delegation Graph Validation

### 2.1 — Build delegation graph resolver for direct and indirect agent delegation edges
Description: Resolve delegation edges from SOP step definitions and agent-type references to construct an execution-time delegation graph rooted at the requested agent.
Done when:
- Resolver returns deterministic node and edge sets for a given agent type.
- Nested delegation relationships are included.
- Missing or inactive targets are surfaced as validation errors.

### 2.2 — Implement recursive cycle detection with explicit cycle path output
Description: Add DFS-based cycle detection that identifies direct self-recursion and indirect recursion chains and returns the full cycle path for diagnostics.
Done when:
- Cycle detection flags self-loop and multi-node recursive cycles.
- Returned diagnostics include ordered cycle path and root agent.
- Algorithm has safeguards for large graphs and malformed data.

### 2.3 — Enforce pre-execution block on cyclic graphs before first runtime iteration
Description: Integrate cycle detector into Agent Runtime pre-check flow so execution is denied before any model call or tool dispatch.
Done when:
- Cyclic delegation requests stop before first LLM request.
- Session terminal state contains guardrail stop metadata.
- No side-effecting tool calls are issued on blocked runs.

### 2.4 — Emit structured pre-execution guardrail decision logs and status payloads
Description: Emit explicit pre-execution decisions (allow or deny) with reason and graph summary fields.
Done when:
- Pre-check decision logs are persisted in execution log entries.
- Denied decisions include reason code and cycle path details.
- Log format is stable for operator filtering and incident triage.

## Phase 3 — Runtime Guardrail Enforcement in Agent Runtime

### 3.1 — Add cumulative iteration accounting across local and delegated execution
Description: Replace local-only fixed iteration loops with cumulative counters that include delegated activity attributed back to the parent session execution budget.
Done when:
- Parent session stops when cumulative iteration budget is exhausted.
- Delegated progress updates increment parent counters consistently.
- Counter semantics are deterministic for retries and transient tool failures.

### 3.2 — Add delegated depth and delegated-step budget accounting to the runtime context
Description: Track delegation depth and delegated-step consumption as first-class runtime counters to prevent unbounded fan-out.
Done when:
- Depth and delegated-step limits are enforced independently from iteration limit.
- Exceeded depth or step budgets trigger terminal guardrail stop reason.
- Runtime context includes counters for observability.

### 3.3 — Enforce per-agent wall-clock timeout with deterministic termination behavior
Description: Introduce timeout checks that stop execution when elapsed wall-clock time exceeds policy for the current session.
Done when:
- Timeout is measured from execution start and enforced in runtime loop boundaries.
- Timeout stop reason is explicit and propagated to persisted session state.
- Timeout enforcement is independent of iteration/delegation counters.

### 3.4 — Add mode-aware token guardrail behavior (conversational visibility plus automated enforcement) with unsupported-provider fallback handling
Description: For conversational sessions, continuously surface current-session token usage and permit continuation even when configured token thresholds are reached. For non-conversational and automated runs, enforce token budget when provider usage accounting supports hard control, and apply configured fallback mode when hard enforcement is unavailable.
Done when:
- Conversational sessions emit continuous current-session token usage snapshots in runtime and status/log pathways.
- Conversational sessions are not terminally stopped solely because token budget threshold is reached; continuation remains available while cycle, iteration, depth, and timeout guardrails stay active.
- Non-conversational and automated runs trigger token-budget stop when budget is exceeded on supported providers.
- Unsupported providers execute fallback mode behavior exactly as configured.
- Fallback and conversational continuation decisions are logged with provider capability and execution-mode context.

## Phase 4 — Stop-Reason Propagation and Session State Semantics

### 4.1 — Define stop-reason taxonomy for cycle, iteration, depth, timeout, token, and fallback outcomes
Description: Define a strict stop-reason enum/taxonomy so UI, operations, and tests can distinguish policy stops from generic failures.
Done when:
- Stop reasons are centrally defined and documented.
- Each guardrail condition maps to one canonical stop reason.
- Conversational token-threshold visibility events are defined as non-terminal informational outcomes and do not conflict with terminal stop reasons.
- Unknown stop reasons are rejected by validation.

### 4.2 — Propagate stop reason through Agent Runtime to Control Center session status updates
Description: Ensure runtime guardrail decisions and conversational token-usage visibility outcomes flow through internal status/result APIs with stable payload fields.
Done when:
- Control Center receives stop reason in failed/terminated updates.
- Session result and status payloads are consistent across paths, including conversational token usage snapshots and continuation eligibility markers.
- No stop-reason metadata is lost in Communication Hub forwarding.

### 4.3 — Distinguish guardrail stops from functional failures in persisted session state
Description: Persist guardrail outcomes in a way that allows operators to separate policy-enforced stops from code/runtime defects.
Done when:
- Session state can be queried for guardrail vs functional failure categories.
- Conversational token-threshold visibility events are queryable as informational guardrail outcomes and are not mislabeled as failures.
- Existing dashboards can display stop category without ambiguous parsing.
- Backward compatibility is maintained for existing status consumers.

### 4.4 — Ensure Communication Hub forwards guardrail terminal outcomes without behavior drift
Description: Verify Communication Hub forwarding does not alter terminal payload semantics and preserves stop reasons for upstream callers.
Done when:
- Forwarded responses preserve stop reason and structured outcome fields.
- A2A and direct execution forwarding paths both preserve semantics.
- Regression tests cover both forwarded success and guardrail-stop scenarios.

## Phase 5 — Guardrail Observability and Audit Logging

### 5.1 — Standardize guardrail decision event schema for execution logs
Description: Define structured execution log event types and required fields for guardrail decisions, checks, and terminal outcomes.
Done when:
- Event names and required keys are documented and enforced.
- Guardrail events are emitted in both pre-check and runtime phases.
- Conversational token-usage visibility and continuation-path events are included with explicit execution-mode context.
- Event schema remains compatible with existing log viewer expectations.

### 5.2 — Capture pre-check and runtime guardrail counters in structured data fields
Description: Include counters and thresholds in execution log data to support post-mortem analysis.
Done when:
- Logs include current and limit values for iteration, depth, delegated steps, and elapsed time.
- Logs include current-session token usage and configured token threshold values with execution-mode context.
- Counter snapshots are emitted at stop decision points.
- Logs are queryable for threshold-near events.

### 5.3 — Add policy snapshot fingerprint and fallback mode details to audit events
Description: Include stable policy identifiers/fingerprints and token fallback mode details in decision logs for audit traceability.
Done when:
- Each guardrail event can be traced to a policy snapshot identifier.
- Token fallback mode and provider capability are included where relevant.
- Audit logs avoid sensitive credential data.

### 5.4 — Add regression assertions for log completeness and stop-reason visibility
Description: Add tests validating that all terminal guardrail outcomes produce expected structured log events.
Done when:
- Tests fail if required guardrail event fields are missing.
- Tests confirm stop reason appears in session status and logs.
- Coverage includes cycle, iteration, timeout, depth, token fallback outcomes, and conversational token-visibility continuation outcomes.

## Phase 6 — Verification, Hardening, and Documentation Updates

### 6.1 — Add unit tests for cycle detection edge cases and graph traversal limits
Description: Cover single-node loops, deep indirect cycles, acyclic chains, and malformed graph inputs.
Done when:
- Unit tests cover positive and negative cycle detection cases.
- Traversal limit protections are tested.
- Failures provide actionable diagnostics.

### 6.2 — Add integration tests for timeout, iteration, depth, and token fallback behavior
Description: Validate end-to-end guardrail enforcement across runtime and control-center status updates.
Done when:
- Integration tests assert stop reasons and persisted outcomes for each guardrail type.
- Conversational-session integration tests assert current-session token usage visibility and continuation behavior when token thresholds are reached.
- Token enforcement and fallback are tested for non-conversational and automated runs across supported and unsupported provider capability paths.
- Tests run against real internal API boundaries without bypassing segregation.

### 6.3 — Add A2A path tests proving delegated activity counts toward parent execution ceiling
Description: Add tests for parent-child delegation flows that consume cumulative guardrail budgets and terminate at correct boundaries.
Done when:
- Delegated iterations and steps contribute to parent budget counters.
- Parent session guardrail stop occurs at configured thresholds.
- A2A outcomes preserve stop-reason propagation.

### 6.4 — Update master docs and operational runbooks for guardrail triage semantics
Description: Update architecture, product, QA, and operations docs to reflect guardrail controls and operator triage expectations.
Done when:
- Master docs include guardrail lifecycle and segregation ownership boundaries.
- QA test plan includes required guardrail scenarios.
- Operations docs include stop-reason interpretation guidance.

## Completion Checklist
- [x] Guardrail policy contract is implemented and validated at Control Center boundaries
- [x] Pre-execution cycle detection blocks recursive delegation before model execution starts
- [x] Runtime enforces cumulative iteration, delegated depth/steps, and timeout limits
- [x] Conversational sessions show current-session token consumption and allow continuation without token-budget-only hard stop
- [x] Non-conversational and automated runs enforce token budget where available with deterministic fallback where unavailable
- [x] Guardrail stop reasons propagate end-to-end across Agent Runtime, Communication Hub, and Control Center
- [x] Execution log events include structured guardrail decision data for audit and triage
- [x] Unit, integration, and A2A regression tests pass for all guardrail paths
- [x] Documentation updates are complete and aligned with docs/config.yaml top-priority segregation rules

