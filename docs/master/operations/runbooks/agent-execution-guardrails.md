# Runbook: Agent Execution Guardrails

Triage for cycle blocks, iteration/timeout/delegation budget stops, conversational token-threshold behavior, token fallback activation, stop-metadata integrity, model-usage guardrail enforcement, and runtime control dashboard issues.

---

## 0. Model-Usage Guardrail Hierarchy (vendor → model → guardrail)

**Context**: Model-usage guardrails are organised under a three-level hierarchy. Each model carries one to four per-period guardrail records (hour, day, week, month). Vendors group their models. Disabling a vendor cascades to every model under it; the per-model disable affordances remain visible to show the cascade source.

**Schema Reference**: `model_guardrail_configurations` (one row per `(model_id, model_name, period)` with unique constraint), `model_availability` (per-model disabled state with `disabled_reason` of `manual` or `vendor_cascaded`), `model_usage_postures` (within_limit / approaching_limit / breached), `guardrail_threshold_events` (append-only threshold transitions).

**Trigger Alerts**: `GuardrailBreachSurge`, `ModelDisabledSurge`, `VendorDisabledSurge`, `ApproachingLimitSurge`.

**Symptoms**:
- Spikes in `model_disabled` / `vendor_disabled` / `guardrail_breached` `ExecutionEventCategory` events.
- New `AgentJob.termination_category` values of `model_disabled` or `vendor_disabled`.
- `model_usage_postures.posture_state` shifting from `within_limit` to `approaching_limit` or `breached` for a sustained period.

**Likely Causes**:
- Operator-driven vendor or model disable toggle (expected during incident response).
- Multi-vendor guardrail breach (e.g. usage across multiple vendors exceeded the configured period threshold).
- Stale posture rollup — last_updated_at is older than expected.
- Missing migration `c1a2b3d4e5f6` (vendor → model → guardrail restructure) — old `usage_limit_*` columns still present.

**Resolution**:
1. Query `guardrail_threshold_events` for the latest events; group by `event_category` and `posture_state`.
2. For `vendor_disabled` cascades, verify `model_configs.is_disabled` is the source and inspect operator audit log.
3. For `guardrail_breached` with `enforcement_posture = terminate`, expect execution block; for `observe-only`, expect alert but continued execution.
4. For stale posture rollups, hit `GET /api/v1/agents/guardrails/model-usage-posture?refresh=true` to force a refresh.
5. For multi-vendor breach dominance, ensure `ModelAvailabilityService._check_guardrail_breach()` is returning the most severe reason.

---

## 0.1 Per-Period Guardrail CRUD Issues

**Symptoms**: `409 Conflict` on `POST /api/v1/agents/guardrails/model-usage-limits`; `unit` field round-trip mismatch; default `enforcement_posture` not `terminate`.

**Resolution**:
1. Verify `(model_id, model_name, period)` uniqueness rule is enforced server-side; 409 on duplicate is the correct response.
2. Verify `unit` defaults to `k` on create when not specified; explicit value preserved through update.
3. Verify `enforcement_posture` defaults to `terminate` for new configurations.

---

## 0.2 Vendor Disable Cascade Issues

**Symptoms**: Vendor disable does not cascade to all child models; cascade source badge missing; `disabled_reason` not set to `vendor_cascaded`; per-model disable affordances hidden.

**Resolution**:
1. Verify `ModelConfig.is_disabled = true` triggers the cascade transaction onto every `ModelAvailability` row under the vendor.
2. Verify `model_availability.disabled_reason = vendor_cascaded` is set.
3. Verify the dashboard's `VendorModelGuardrailPanel` keeps per-model disable affordances visible to show the cascade source.
4. Re-enable should restore each row to its prior manual state — verify by toggling back and checking the `disabled_reason` returns to its previous value.

---

## 1. Recursive Delegation Cycle Blocks

**Trigger Alerts**: `CycleBlockSurge`, `GuardrailStopRateSpike` (with cycle-heavy reason mix).

**Symptoms**: Increased `guardrail_cycle_block_total`; repeated `guardrail.precheck.blocked_cycle` events for the same agent types.

**Likely Causes**:
- New direct or indirect delegation loop introduced by agent/SOP mapping changes.
- Policy snapshot drift after role or workflow rollout.
- Recursion/dead-loop risk not validated at create, update, or run initiation.

**Resolution**:
1. Group blocked-cycle events by `agent_type_id`, `session_id`, and `policy_snapshot_id`.
2. Inspect `sop_recursion_validation_checks` and `sop_recursion_validation_findings` for the most recent check that failed.
3. Identify repeated delegation chains and isolate the cycle edge from the `cycle_path_json` field.
4. Disable or roll back the affected workflow mapping.
5. Verify `guardrail_cycle_block_total` returns to baseline after rollback.

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

## 6. Operator-Initiated Termination Issues

**Trigger Alerts**: `TerminateRequestFailure`, `TerminateCascadeIncomplete`, `TerminatedOutcomeDrift`.

**Symptoms**:
- Operator clicks "Terminate" on a running node and the request fails or never completes.
- Parent termination stops the parent but does not cascade to delegated children.
- `AgentJob.status` flips to `terminated` but children remain `running`.
- 4xx/5xx errors on `POST /api/v1/agents/runtime/terminate` or in the Communication Hub forwarder.
- Late-arriving status updates from the underlying LangChain framework land on a terminated `AgentJob`.

**Likely Causes**:
- Agent Runtime rejects terminate request because the caller certificate is not `service:communication-hub` (regression of the v2 fix). Check `agent-runtime.log` for `rejected` lines from `ControlCenterCertificateMiddleware`.
- Communication Hub terminate forwarder path is not registered (`_AGENT_TERMINATE_PATH_PREFIX` not mounted).
- Cascade termination walks the wrong delegation graph (parent not found in `agent_run_relationships`).
- Terminal-state guards in `update_session_status` are not rejecting late updates — would surface as a test failure.

**Resolution**:
1. Confirm the call chain: Control Center → Communication Hub → Agent Runtime. If the request went directly from Control Center to Agent Runtime, the certificate middleware will reject it; route the request through the Communication Hub.
2. Check `agent-runtime.log` for the cancel outcome. 404 is treated as success; 503 indicates a transient availability issue (retry); 502 indicates a permanent failure.
3. Inspect `termination_requests` and `termination_cascade_outcomes` for the request_id; verify each affected child has a `TerminationCascadeOutcome` row.
4. For sleep conversations (no live agent job), the operator should see "End session" instead of "Terminate"; verify the dashboard renders `SleepConversationActions` for `kind === 'conversation' && status === 'sleep'`.
5. For late updates on terminated jobs, verify `update_session_status` rejects with a clear error — this is the terminal-state guard, not a regression.

---

## 7. Runtime Control Dashboard Issues

**Trigger Alerts**: `RuntimeTopologyPollingFailure`, `RuntimeControlAPIFailure`.

**Symptoms**:
- `/agents/runtime-control` page renders no nodes despite active agents.
- Topology filter legend does not toggle node visibility.
- Sleep conversations (no live agent) appear with a "Terminate" button instead of "End session".
- Status colors do not distinguish between `terminated` (operator-initiated) and `failed` (genuine agent or runtime error).
- Multi-row nodes wrap vertically (legacy layout) instead of horizontally (current layout).

**Likely Causes**:
- `GET /api/v1/agents/runtime/topology` returning 401/403 — operator lacks runtime control permission.
- `RuntimeTopologyController` not merging the three sources (`AgentJob` + `ConversationSession` + `AgentInstance`).
- Frontend filter state (page-level `Set<string>` with `DEFAULT_VISIBLE_KEYS`) excludes the relevant `kind:status` key.
- The change to remove `MAX_NODES_PER_COL` row-wrap did not land — nodes appear in vertical stacks.

**Resolution**:
1. Verify `GET /api/v1/agents/runtime/topology` returns 200 with `nodes` and `edges` arrays.
2. Verify the topology controller merges three sources and synthesizes `active`/`sleep` for conversations based on backing `AgentJob` state.
3. Verify the legend checkboxes toggle node visibility; the default filter excludes `conversation:sleep`.
4. Verify the page passes `visibleKeys`/`onToggleKey` to the diagram and the diagram renders `data-node-id={node.session_id}`.
5. For layout regression, check `RuntimeTopologyDiagram` uses the single-row-per-depth layout (no `MAX_NODES_PER_COL`) and a wrapping Box with `overflowX: 'auto'`.

---

## Escalation

- Escalate to platform on-call immediately for Critical guardrail alerts.
- Escalate to workflow owners when cycle blocks or delegation-budget stops are tied to a recent rollout.
- Escalate to observability owners when stop metadata integrity checks fail.
- Escalate to service-segregation owners when terminate calls fail with certificate-rejection errors.