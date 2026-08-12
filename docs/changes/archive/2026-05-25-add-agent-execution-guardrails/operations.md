# Operations: Add Agent Execution Guardrails

Feature: add-agent-execution-guardrails  
Date: 2026-05-22  
Status: Ready for operations integration

## Purpose
Define operational controls for monitoring, logging, and triage of agent execution guardrails:
- Recursive delegation cycle detection and pre-execution block
- Cumulative iteration ceiling including delegated chain activity
- Per-agent execution timeout
- Mode-aware token controls: conversational current-session token visibility with continuation, and token-budget enforcement for non-conversational or automated runs with explicit fallback behavior

## Monitoring

### Monitoring Objectives
- Detect guardrail stop-rate changes quickly and distinguish policy stops from functional failures.
- Detect recursion/cycle blocks before they become broad execution disruption.
- Detect threshold misconfiguration (too strict or too lenient) for iteration, timeout, and delegated budgets.
- Detect conversational token-usage visibility gaps or token-budget-only hard-stop regressions.
- Detect token guardrail fallback activation frequency and unsupported-provider patterns.

### Metrics to Track
| Metric | Source | Labels | Why It Matters |
| --- | --- | --- | --- |
| guardrail_stop_total | Agent Runtime session monitor | reason, agent_type, execution_mode | Primary signal for policy-enforced termination volume |
| guardrail_cycle_block_total | Pre-execution validator | agent_type, root_session | Detects recursive delegation configurations |
| guardrail_iteration_limit_hit_total | Runtime loop | agent_type, parent_session | Validates cumulative iteration cap behavior |
| guardrail_timeout_limit_hit_total | Runtime loop | agent_type | Detects long-running session termination pressure |
| guardrail_delegation_budget_hit_total | Runtime loop | limit_type, agent_type | Detects depth/step budget saturation |
| guardrail_token_budget_hit_total | Model binding layer | provider, model, agent_type, execution_mode | Tracks hard token budget terminations for non-conversational or automated runs |
| guardrail_conversational_token_usage_snapshot_total | Conversation execution loop | provider, model, agent_type | Tracks conversational token-usage visibility event cadence |
| guardrail_conversational_token_threshold_reached_total | Conversation execution loop | provider, model, agent_type | Tracks conversational token-threshold reach events that allow continuation |
| guardrail_token_fallback_applied_total | Runtime loop | provider, fallback_mode, agent_type | Tracks unsupported hard-enforcement paths |
| session_terminal_state_total | Session status pipeline | state, stop_category | Confirms guardrail stops are separated from functional failures |

### Alert Recommendations
| Alert Name | Condition | Severity | Routing |
| --- | --- | --- | --- |
| GuardrailStopRateSpike | guardrail_stop_total above baseline for 5 minutes | Warning | Operations on-call |
| CycleBlockSurge | guardrail_cycle_block_total above baseline for 5 minutes | Warning | Operations plus workflow owner |
| TimeoutRegression | guardrail_timeout_limit_hit_total sustained above baseline for 10 minutes | Warning | Operations on-call |
| DelegationBudgetExhaustion | guardrail_delegation_budget_hit_total sustained above baseline for 5 minutes | Warning | Operations on-call |
| ConversationalTokenVisibilityGap | guardrail_conversational_token_usage_snapshot_total drops to zero while active conversational sessions exist for 5 minutes | Critical | Immediate escalation |
| ConversationalTokenHardStopDetected | terminal sessions with conversational mode and token-budget stop reason greater than zero for 2 minutes | Critical | Immediate escalation |
| TokenFallbackOveruse | guardrail_token_fallback_applied_total sustained above baseline for 15 minutes | Warning | AI platform operations |
| StopReasonMissing | non-zero terminal sessions without stop reason classification for 2 minutes | Critical | Immediate escalation |

## Logging

### Required Events
| Event | Level | Description |
| --- | --- | --- |
| guardrail.precheck.allowed | INFO | Pre-execution validation passed |
| guardrail.precheck.blocked_cycle | WARN | Recursive delegation cycle detected and blocked |
| guardrail.runtime.iteration_limit_exceeded | WARN | Cumulative iteration ceiling reached |
| guardrail.runtime.timeout_exceeded | WARN | Per-agent wall-clock timeout reached |
| guardrail.runtime.delegation_depth_exceeded | WARN | Delegation depth limit reached |
| guardrail.runtime.delegated_steps_exceeded | WARN | Delegated-step budget reached |
| guardrail.runtime.token_budget_exceeded_non_conversational | WARN | Token budget hard cap exceeded for non-conversational or automated run |
| guardrail.runtime.conversational_token_threshold_observed | INFO | Conversational token threshold reached while continuation remains allowed |
| guardrail.runtime.conversational_token_usage_snapshot | INFO | Conversational current-session token usage snapshot emitted |
| guardrail.runtime.token_fallback_applied | INFO | Token fallback path activated for unsupported hard enforcement |
| guardrail.session.terminal | INFO | Session ended by guardrail with canonical reason |

### Required Fields
All guardrail events should include:
- timestamp
- service_name
- trace_id
- span_id
- session_id
- agent_type_id
- guardrail_reason
- execution_mode
- current_value
- threshold_value
- token_usage_current_session (when applicable)
- continuation_allowed (when applicable)
- policy_snapshot_id
- fallback_mode (when applicable)
- delegation_chain_depth (when applicable)

### Logging Constraints
- Do not log sensitive credentials, tokens, or decrypted secret material.
- Keep guardrail reason taxonomy canonical and stable for analytics queries.
- Ensure forwarded stop metadata is preserved across service boundaries without truncation.

## Common Issues

### 1. Repeated cycle-blocked sessions after new SOP rollout
Symptoms:
- Spike in guardrail.precheck.blocked_cycle.
Likely causes:
- New direct or indirect recursive delegation path.
Operator actions:
- Identify cycle path from logs.
- Disable or patch affected SOP/agent-type linkage.
- Re-run controlled validation before re-enabling.

### 2. Iteration limit hits on previously stable workflows
Symptoms:
- Increased guardrail.runtime.iteration_limit_exceeded.
Likely causes:
- New delegated work volume not reflected in policy threshold.
Operator actions:
- Compare current counter snapshots with historical baselines.
- Adjust agent-type limit if justified.
- Confirm no hidden recursion is inflating iteration counts.

### 3. Timeout spikes during dependency slowdown
Symptoms:
- Increased guardrail.runtime.timeout_exceeded.
Likely causes:
- Downstream latency increase or overly aggressive timeout threshold.
Operator actions:
- Correlate with dependency latency telemetry.
- Tune timeout policy only after confirming external performance state.
- Re-validate session completion behavior after adjustment.

### 4. Frequent token fallback activation
Symptoms:
- Increased guardrail.runtime.token_fallback_applied.
Likely causes:
- Unsupported provider/model path or capability regression.
Operator actions:
- Validate provider capability metadata.
- Prioritize supported models for strict token cap requirements.
- Review cost controls for fallback-mode sessions.

### 5. Conversational sessions stop on token budget threshold
Symptoms:
- Terminal conversational sessions with token-budget guardrail stop reason.
Likely causes:
- Execution mode misclassification in runtime policy resolution.
- Incorrect token enforcement branch selected for conversational execution.
Operator actions:
- Validate execution-mode field in context payload and runtime logs.
- Validate conversational continuation policy settings.
- Treat as high-priority behavior regression and roll back token-mode configuration if needed.

### 6. Missing guardrail reason in terminal sessions
Symptoms:
- Terminal sessions appear without stop-category metadata.
Likely causes:
- Forwarding/persistence field mismatch across services.
Operator actions:
- Validate Communication Hub passthrough behavior.
- Validate Control Center session persistence mapping.
- Treat as high-priority observability defect.

## Master Operations Update Instructions
Update the following master operations docs once implementation is complete:
- docs/master/operations/monitoring.md
  - Add guardrail metrics, dashboards, and alerts for cycle, iteration, timeout, delegation budgets, conversational token visibility and continuation, token budget, and token fallback.
- docs/master/operations/logging.md
  - Add guardrail event catalog, canonical reason taxonomy, required fields, and sensitive-data exclusions.
- docs/master/operations/runbooks/agent-execution-guardrails.md
  - Add triage flow for cycle blocks, iteration/timeout/delegation budget stops, conversational token-threshold continuation behavior, token fallback behavior, and metadata integrity checks.
- docs/master/operations/README.md
  - Add links to the new guardrail monitoring/logging sections and runbook.
