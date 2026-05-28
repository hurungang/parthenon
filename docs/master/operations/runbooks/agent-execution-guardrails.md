# Runbook: Agent Execution Guardrails

Triage for cycle blocks, iteration/timeout/delegation budget stops, conversational token-threshold behavior, token fallback activation, and stop-metadata integrity.

---

## 1. Recursive Delegation Cycle Blocks

**Trigger Alerts**: `CycleBlockSurge`, `GuardrailStopRateSpike` (with cycle-heavy reason mix).

**Symptoms**: Increased `guardrail_cycle_block_total`; repeated `guardrail.precheck.blocked_cycle` events for the same agent types.

**Likely Causes**:
- New direct or indirect delegation loop introduced by agent/SOP mapping changes.
- Policy snapshot drift after role or workflow rollout.

**Resolution**:
1. Group blocked-cycle events by `agent_type_id`, `session_id`, and `policy_snapshot_id`.
2. Identify repeated delegation chains and isolate the cycle edge.
3. Disable or roll back the affected workflow mapping.
4. Verify `guardrail_cycle_block_total` returns to baseline after rollback.

---

## 2. Iteration, Timeout, and Delegation Budget Stops

**Trigger Alerts**: `TimeoutRegression`, `DelegationBudgetExhaustion`, `GuardrailStopRateSpike`.

**Symptoms**: Spikes in `guardrail_iteration_limit_hit_total`, `guardrail_timeout_limit_hit_total`, or `guardrail_delegation_budget_hit_total`.

**Likely Causes**:
- Workflow expansion increased delegated work without guardrail policy re-baselining.
- External dependency slowdown causing longer end-to-end execution.
- Delegation depth or delegated-step budgets below current operating profile.

**Resolution**:
1. Compare current stop reason distribution against the previous stable baseline by `agent_type`.
2. Correlate timeout spikes with LLM/MCP latency metrics.
3. Confirm whether one limit type dominates (`depth` vs `delegated_steps`).
4. Apply the minimum policy adjustment needed, or roll back the triggering workflow rollout.
5. Validate that stop rates normalize and functional failure rates do not increase.

---

## 3. Conversational Token Threshold and Continuation Behavior

**Trigger Alerts**: `ConversationalTokenVisibilityGap`, `ConversationalTokenHardStopDetected`.

**Symptoms**:
- Missing `guardrail_conversational_token_usage_snapshot_total` despite active conversational sessions.
- Conversational sessions ending with token-budget hard-stop classification.

**Likely Causes**:
- Execution mode misclassification during policy evaluation.
- Conversational continuation branch not selected.
- Event emission gap in conversational token usage snapshots.

**Resolution**:
1. Validate `execution_mode` on affected terminal sessions and guardrail events.
2. Confirm conversational sessions emit `guardrail.runtime.conversational_token_usage_snapshot` and `guardrail.runtime.conversational_token_threshold_observed`.
3. If conversational sessions are hard-stopped on token budget, treat as a regression and roll back the token-mode policy change.
4. Reconfirm conversational continuation behavior with live telemetry after rollback/fix.

---

## 4. Token Fallback Overuse

**Trigger Alert**: `TokenFallbackOveruse`.

**Symptoms**: Sustained increase in `guardrail_token_fallback_applied_total`; frequent `guardrail.runtime.token_fallback_applied` events.

**Likely Causes**:
- Provider/model capability mismatch for strict token enforcement.
- Policy routing sending strict-cap flows to unsupported providers.

**Resolution**:
1. Break down fallback events by `provider`, `model`, and `fallback_mode`.
2. Verify capability mapping and policy-targeting for affected providers.
3. Move strict token-cap workloads to supported providers where required.
4. Monitor fallback rate until it returns to expected baseline.

---

## 5. Guardrail Stop Metadata Integrity

**Trigger Alert**: `StopReasonMissing`.

**Symptoms**: Terminal sessions without `stop_category` or canonical guardrail reason; missing correlation between terminal state and guardrail events.

**Likely Causes**:
- Field mapping mismatch between runtime emission and persistence.
- Truncation or drop of stop metadata across service boundaries.
- Non-canonical reason values introduced by drift.

**Resolution**:
1. Verify required fields on guardrail events: `session_id`, `guardrail_reason`, `execution_mode`, `current_value`, `threshold_value`, `policy_snapshot_id`.
2. Confirm `guardrail_reason` values match canonical taxonomy in operations logging reference.
3. Trace one affected session end-to-end with `trace_id` and verify metadata at each hop.
4. Treat missing or non-canonical reason propagation as a high-priority observability defect.

---

## Escalation

- Escalate to platform on-call immediately for Critical guardrail alerts.
- Escalate to workflow owners when cycle blocks or delegation-budget stops are tied to a recent rollout.
- Escalate to observability owners when stop metadata integrity checks fail.