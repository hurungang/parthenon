# Test Plan: Add Agent Execution Guardrails

Created by: Tester Agent
Date: 2026-05-22
Status: Planned

## 1. Test Strategy

This plan validates enterprise guardrails for agent execution across pre-check and runtime phases, with explicit coverage for recursion prevention, bounded execution, timeout controls, token budget behavior, and segregation compliance.

Strategy principles:
- Validate guardrails as policy outcomes, not generic failures, so operations can distinguish stop reasons from functional errors.
- Validate full lifecycle behavior across direct execution and delegated execution chains (parent plus downstream sessions).
- Validate token-budget behavior by session mode: conversational sessions expose current-session token usage without a token-budget hard stop, while non-conversational automated sessions retain deterministic budget enforcement.
- Validate execution-summary visibility for guardrail usage so conversational token usage is visible without opening raw logs.
- Validate Control Center guardrail editor presentation so token budgets appear in k tokens and default to 1000k.
- Validate top-priority segregation rules from docs/config.yaml: execution and enforcement in Agent Runtime, persistence and policy authority in Control Center, forwarding only in Communication Hub, and no direct database access outside Control Center.

Test layers aligned to docs/config.yaml source.tests:
- Backend tests in backend/tests/ for cycle detection, chain-wide iteration accounting, timeout termination semantics, token guardrail logic, and internal API payload contracts.
- Frontend tests in frontend/src/__tests__/ for operator-visible session stop reasons, guardrail taxonomy rendering, and distinction between policy stop and runtime failure.
- E2E tests in e2e/tests/ for end-to-end delegated execution behavior, stop reason propagation across Communication Hub, and deterministic terminal status.
- Supporting integration tests in mcp-demo-app/tests/ where provider capability simulation is needed for token-budget supported vs unsupported behavior.

Execution guidance:
- Run all layers for completion criteria.
- Include at least one real-backend e2e path for critical guardrail stop propagation (not only mocked routing) to reduce false confidence.
- Capture evidence for each stop taxonomy value required by the spec.

## 2. Coverage Areas

1. Delegation cycle prevention
- Direct cycle detection (A delegates to A).
- Multi-hop cycle detection (A to B to C to A).
- Pre-execution block behavior with explicit cycle stop reason.

2. Chain-wide iteration guardrail
- Iteration budget includes direct and delegated activity in one cumulative ceiling.
- Parent session and delegated sessions converge on deterministic iteration-limit stop outcome.
- Counter snapshots are logged for operations triage.

3. Per-agent timeout guardrail
- Timeout enforces deterministic stop when elapsed time crosses policy.
- Timeout stop reason is consistent across runtime state, session status, and execution logs.
- Timeout behavior remains consistent when delegation exists.

4. Token budget behavior by session mode
- Conversational sessions surface current-session token usage to operators/users and allow continuation without hard-stop solely due to token budget.
- Non-conversational/automated sessions enforce token budget with deterministic outcomes when provider supports hard limits.
- Non-conversational/automated sessions use deterministic fallback behavior when provider cannot enforce hard limits.
- Token-budget mode and outcomes remain visible in logs and session metadata without disabling other guardrails.

6. Stop-reason taxonomy and observability
- Canonical guardrail reasons are emitted and persisted (cycle_detected, iteration_limit_exceeded, delegation_depth_exceeded, delegated_steps_exceeded, execution_timeout_exceeded, token_budget_exceeded_non_conversational, token_guardrail_fallback_applied).
- Session payloads and logs preserve guardrail category and reason without loss through forwarding.

6. Segregation and boundary compliance
- Agent Runtime performs guardrail enforcement decisions but does not persist directly to database.
- Control Center remains policy and persistence owner.
- Communication Hub forwards and preserves guardrail metadata without policy ownership or persistence side effects.

## 3. Critical Scenarios (WHEN/THEN)

1. Direct recursive delegation cycle
- WHEN an agent execution path delegates to the same agent identity/type in a direct loop.
- THEN execution is blocked before first unsafe delegated action and terminal reason is cycle_detected.

2. Indirect multi-hop delegation cycle
- WHEN a delegated chain forms A to B to C to A.
- THEN the chain is blocked deterministically with cycle_detected and no runaway continuation occurs.

3. Max iterations across delegated chain
- WHEN parent and delegated sessions collectively exceed configured max iterations.
- THEN execution stops with iteration_limit_exceeded and all participating session states reflect the same policy-stop classification.

4. Per-agent timeout enforcement
- WHEN elapsed runtime exceeds configured execution timeout for the agent type.
- THEN execution stops with execution_timeout_exceeded and terminal status remains distinguishable from functional exception failure.

5. Conversational session token usage visibility
- WHEN a conversational session accumulates token usage to or beyond configured budget thresholds for visibility.
- THEN current-session token usage is visible to users/operators and the session can continue without hard-stop solely from token budget.
- AND the execution summary reflects the current-session token usage in the friendly log view.

6. Automated session token budget supported provider path
- WHEN a non-conversational/automated session runs on a provider that supports hard token budget enforcement and consumption exceeds configured budget.
- THEN execution stops with token_budget_exceeded_non_conversational and usage evidence is recorded in guardrail logs.

7. Automated session token budget unsupported provider path
- WHEN a non-conversational/automated session runs on a provider that does not support hard token limit enforcement.
- THEN system applies deterministic fallback mode, emits token_guardrail_fallback_applied visibility, and keeps other guardrails active.

8. Guardrail metadata propagation through Communication Hub
- WHEN a delegated request is terminated by a guardrail in downstream execution.
- THEN forwarding preserves stop reason and guardrail category unchanged to parent and operator-visible session views.

9. Segregation-safe enforcement path
- WHEN guardrails are evaluated and terminal status is persisted.
- THEN Agent Runtime performs enforcement logic only, Control Center performs persistence only, and no direct non-Control-Center database access occurs.

## 4. Edge Cases

- Boundary-at-threshold behavior where counters or elapsed time are exactly equal to configured limits.
- Simultaneous delegated branches consuming shared iteration or delegated-step budgets near exhaustion.
- Late-arriving delegated response after parent has already reached a timeout or iteration stop.
- Provider capability changes between executions causing token guardrail mode changes; fallback decision must remain explicit and deterministic per run.
- Missing or malformed guardrail policy fields in context payload; runtime should fail safely with clear operational signal.
- Duplicate or reordered internal status/log updates; persisted terminal reason must remain stable and not oscillate.
- Communication Hub payload transformations accidentally dropping new additive stop-reason fields.
- Distinguishing guardrail policy stops from transport or tool errors to avoid mis-triage.

## 5. Acceptance Criteria Checklist

- [ ] Direct and indirect recursive delegation loops are detected and blocked with clear cycle_detected outcomes.
- [ ] Max iteration limits are enforced across parent plus delegated execution activity, not parent-only counting.
- [ ] Per-agent timeout is enforced with deterministic execution_timeout_exceeded outcomes.
- [ ] Conversational sessions show current-session token usage and do not hard-stop solely due to token budget.
- [ ] Non-conversational/automated sessions enforce token budget when provider hard limits are supported.
- [ ] Deterministic token fallback mode is applied and visible for non-conversational/automated sessions when hard token limits are not supported.
- [ ] Guardrail stop reasons are operator-visible in session and execution-log views and are distinguishable from functional failures.
- [ ] Communication Hub forwarding preserves guardrail metadata without loss or remapping.
- [ ] Segregation constraints remain intact: Agent Runtime executes/enforces, Control Center persists/owns policy, Communication Hub routes only.
- [ ] No direct database access is introduced outside Control Center as part of guardrail logic.
- [ ] All required test layers from source.tests are covered and passing for this change scope.

## 6. Test File References

Planned backend tests (backend/tests/):
- backend/tests/unit/services/agents/test_runtime_guardrails_cycle_detection.py
- backend/tests/unit/services/agents/test_runtime_guardrails_iteration_chain.py
- backend/tests/unit/services/agents/test_runtime_guardrails_timeout.py
- backend/tests/unit/services/agents/test_runtime_guardrails_token_budget.py
- backend/tests/integration/agent_runtime/test_guardrail_stop_reason_propagation.py
- backend/tests/integration/agent_runtime/test_guardrail_segregation_boundaries.py

Planned frontend tests (frontend/src/__tests__/):
- frontend/src/__tests__/agent-sessions/GuardrailStopReasons.test.tsx
- frontend/src/__tests__/agent-sessions/GuardrailFallbackVisibility.test.tsx
- frontend/src/__tests__/LogPresenter.test.ts
- frontend/src/__tests__/LogSummaryPanel.test.tsx
- frontend/src/__tests__/AgentTypeForm.test.tsx
- frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx

Planned e2e tests (e2e/tests/):
- e2e/tests/agent-guardrails-recursion-and-iteration.spec.ts
- e2e/tests/agent-guardrails-timeout-and-token-budget.spec.ts
- e2e/tests/agent-guardrails-segregation-metadata.spec.ts

Planned supporting integration tests (mcp-demo-app/tests/):
- mcp-demo-app/tests/test_provider_token_capability_modes.py
