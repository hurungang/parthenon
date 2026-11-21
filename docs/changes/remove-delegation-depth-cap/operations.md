# Operations Notes: Remove the Hard-Coded Delegation Depth Cap

Operational impact of making the per-agent-type **Max Delegation Depth** guardrail the sole delegation depth limit for conversational and task agents. No new service, endpoint, schema, or migration. Depth is now configuration-authoritative, so depth stops are diagnosed as configuration, not as a platform cap.

---

## 1. Monitoring

**No new metrics, alerts, or dashboards are introduced.** Existing guardrail series remain the signals; only their interpretation changes.

**What changes in the signals**

- Delegation chains may now be deeper. Task (non-conversational) agents and delegated agents can delegate onward while within their configured maximum, so chains that previously stopped after one delegated level can extend further.
- Depth-related stops are now attributable to one agent type's configuration. The same stop reason can appear at different depths for different agent types; compare by `agent_type` before treating a change as a regression.
- Depth guardrail stops remain a policy outcome, not a functional failure. Terminal classification continues to separate guardrail stops from `failed`.
- Agents with no configured depth keep today's effective default, so their stop behaviour should not change.

**What to watch (existing telemetry only)**

- **Delegation depth stops** — `guardrail_stop_total` filtered to reason `delegation_depth_exceeded`, and `guardrail_delegation_budget_hit_total` filtered to `limit_type=depth`. A sustained rise concentrated on one or two agent types indicates a configuration that is too shallow for the workflow, not a platform regression.
- **Terminal stop classification** — `session_terminal_state_total` with the delegation stop category. Confirm depth stops are still classified as policy stops rather than `failed`.
- **Runaway depth** — use the Runtime Control topology (existing depth columns) to spot chains that keep growing. A chain whose delegation entries keep appearing without reaching `delegation_resumed` or a terminal outcome is the runaway pattern to escalate; deeper trees are otherwise expected and valid.
- **Delegation volume and duration** — existing session throughput, execution duration, and Agent Runtime instance metrics reflect the extra work deeper chains create. Watch for latency and instance-pressure drift after operators raise depth values; this is capacity observation, not a new alert.
- **Cycle and recursion signals unchanged** — cycle blocks and recursion validation still apply and are independent of depth. A cycle-block rise after a depth increase is a workflow-design issue, not a depth side effect.

**Alerting posture**

- No alert thresholds change and none need to be created. Existing `DelegationBudgetExhaustion` and guardrail stop-rate alerting continue to work; treat a firing on a single agent type as a configuration review trigger.

---

## 2. Logging

**Log files (per repository configuration)**

| File | Carries |
|---|---|
| `backend/logs/control-center.log` | Delegation status and execution-log queries, session/enqueue and executor guardrail events, depth-guard decisions and stop metadata |
| `backend/logs/agent-runtime.log` | Agent Runtime execution, delegation tool calls, depth-blocked outcomes, and task-loop depth checks |
| `backend/logs/communication-hub.log` | A2A delegation forwarding and execution-trigger relay; no depth logic lives here |

Files rotate at ~10 MB with `.1` and `.2` retained.

### Log scoping contract (product guarantee, preserved)

- An agent's execution log contains that agent's own execution plus its direct delegation lifecycle events (`delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`).
- A delegated agent's further delegation does **not** appear recursively in the parent log. To follow a chain, drill into the delegated agent's own execution log via the existing **View Execution Logs** action.
- The parent's direct-child progress peek is filtered: the child's own delegation tool calls and responses, and its delegation lifecycle entries, are excluded from the peek. The child's full log and the child's own peek are unaffected.
- The backend execution-log endpoints remain single-session queries (snapshot and stream). There is no recursive aggregation, no descendant traversal, and no chain-wide search.
- Consequences for triage: never expect a grandchild entry in a parent log; open the intermediate agent's log instead.

### What is logged about depth

- Depth guardrail events carry the observed depth and the limit used in the decision, plus the delegation chain depth field; the limit is now the agent type's configured maximum.
- Depth-blocked delegation emits a lifecycle event in the blocking agent's own log and returns a blocked tool outcome; the message names the configured maximum that was reached.
- Delegation status responses (what the execution-log viewer displays) report the agent type's configured maximum, so the displayed limit matches the configuration screen.
- No prompt, tool payload, token, or credential content is added to these events.

### Grep hints for depth investigations

- Depth stops: search for the delegation depth guardrail event and the delegation depth reason in `control-center.log` and `agent-runtime.log`.
- Delegation lifecycle: search for the delegation lifecycle event prefixes (`delegation_`) to reconstruct one hop; filter by session identifier.
- Configured limit: search for the maximum delegation depth and threshold fields on the guardrail event to confirm the value equals the agent type's setting.
- Chain position: search for the delegation chain depth field on depth and delegated-step events.
- A2A hops: search `communication-hub.log` for the A2A request path when a delegation does not appear in the child session.
- Correlation: carry the session identifier or trace identifier from the parent log into the child log; the child log is a separate session, not a continuation of the parent's entries.

---

## 3. Common Issues

### A workflow stops at a delegation depth

- **Meaning** — the agent type's configured Max Delegation Depth was reached. This is now a configuration outcome, not a hidden platform cap.
- **Check** — compare the agent type's configured value with the depth-blocked event's reported limit and observed depth; confirm the event's limit equals the configuration screen value.
- **Resolve** — raise the limit on the relevant agent type if the workflow legitimately needs another hop, or restructure the workflow. Do not look for a platform setting; none exists.
- **Do not** — treat this as a functional failure or open a platform defect when the limit matches configuration.

### A delegated agent appears not to be delegating

- **Check** — the delegated agent's *own* agent type guardrail (not the parent's), and the delegation depth recorded for its session; a child that inherited a deep chain position may be at its limit immediately.
- **Check** — that the child run exists at all: `communication-hub.log` for the A2A forward, `control-center.log` for the enqueued child session.
- **Check** — `agent-runtime.log` for a delegation depth block on the child session.
- **Note** — conversational delegations start each hop at depth zero by design, while task-agent delegations inherit chain depth. A difference in observed depth between the two paths is expected, not a defect.

### Operator cannot see a grandchild's activity in the parent log

- **Expected behaviour.** The parent log is single-agent scoped; grandchild entries are deliberately excluded.
- **Resolve** — open the delegated agent's log via **View Execution Logs** on the delegation entry, then continue one hop at a time.
- **Do not** — request a merged, recursive, or chain-wide log view; that is out of scope and would violate the scoping guarantee.

### Delegation status shows an unexpected or default maximum

- **Meaning** — the session's agent type could not be resolved, so the status falls back to the platform default maximum.
- **Check** — that the session's agent type still exists and is not deleted or renamed mid-run; confirm the session identifier resolves.
- **Resolve** — restore or correct the agent type, then reopen the log. A resolved agent type reports its configured maximum.

### Values above the former 32 ceiling are now accepted

- **Verify** — save a depth above the former ceiling through the agent type form and confirm no input clamp remains; confirm the same value is accepted by the assistant-managed configuration path as well as the direct API.
- **Verify** — both validation paths agree on accept/reject outcomes and still reject negative values.
- **Note** — an accepted large value applies immediately at the next execution; no migration or restart of data is needed.

### Guardrail block misdiagnosed as a failure

- **Guidance** — a depth block is a policy outcome: the run ended or continued exactly as the configured guardrail dictates. It is reported with a canonical guardrail reason and a terminal stop classification.
- **Resolve** — triage as policy: review the configured limit and the workflow design. Only escalate when the guardrail event is missing, the reported limit disagrees with configuration, or the block is recorded as `failed`.

---

## 4. Master Operations Update Instructions

### `docs/master/operations/runbooks/agent-execution-guardrails.md`

- Replace any wording that a delegated agent cannot pass work on, that task agents are limited to one delegation level, or that a fixed platform cap applies.
- State that delegation depth is configuration-authoritative: the agent type's Max Delegation Depth is the sole limit, for conversational and task agents alike, and is never silently reduced.
- State that depth limits vary per agent type, so comparisons and baselines must be grouped by agent type rather than by agent category.
- Add triage guidance: an unexpected depth stop is diagnosed by comparing the agent type's configured value against the depth-blocked event's reported limit and observed depth; resolution is a configuration change or a workflow restructure.
- Note that delegated agents inherit the chain's recorded depth (conversational delegations restart at depth zero), so a child can be near its limit on arrival.
- Add the log-scoping note: a parent log shows only its own execution plus direct delegation lifecycle events, and deeper activity is reached by drilling into the delegated agent's log.
- Keep the existing statements that cycle detection, delegated-step budgets, iteration ceilings, timeouts, and token budgets are unaffected.

### `docs/master/operations/logging-agents.md`

- Update the delegation depth guardrail event description: the threshold reported is the agent type's configured maximum, not a platform constant.
- Keep and clarify the delegation chain depth field as the way to locate a stop within a chain.
- Add that a depth block appears in the blocking agent's own session log and that the parent log does not contain the grandchild's entries.
- Confirm the canonical reason taxonomy is unchanged and that depth blocks remain distinguishable from functional failures.

### `docs/master/operations/logging.md` and `docs/master/operations/logging-platform.md`

- Amend the agent delegation event rows so they describe direct-child delegation lifecycle only, scoped to a single session.
- Add the drill-in instruction for following a chain one hop at a time, and state explicitly that no recursive or chain-wide log aggregation exists.

### `docs/master/operations/monitoring-metrics.md`, `monitoring-dashboards.md`, `monitoring-alerts.md`

- Verify only — no new series, panels, or thresholds. Where the delegation depth stop is described, note that `limit_type=depth` now reflects each agent type's configured maximum and that deeper chains are expected.
- Where the existing delegation budget alert or panel is documented, point its first diagnostic step at agent type configuration instead of a platform cap.

### `docs/master/operations/README.md`

- Update the Agent Execution Guardrails runbook description so it reflects configuration-authoritative depth triage and single-level log scoping with drill-in.
- Verify no other operations document asserts a fixed delegation depth for any agent category; correct such statements to reference the configured guardrail.
