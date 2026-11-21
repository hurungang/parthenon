# Implementation Plan: remove-delegation-depth-cap

## Overview

Remove every platform-imposed delegation depth cap so the agent type's configured Max Delegation Depth is the sole limit for conversational and task agents, and make the delegation status report that configured maximum. The work is confined to Control Center depth plumbing, Agent Runtime depth resolution/enforcement, guardrail validation bounds, and one frontend log-peek filter — no schema change, no migration, no new endpoint.

## Task Checklist

### Phase 1 — Control Center depth plumbing (no schema change)

- [x] 1.1 — Expose the job's recorded delegation depth on the internal session payload
- [x] 1.2 — Verify delegated job parent linkage and document conversational depth behaviour
- [x] 1.3 — Return the configured maximum depth from the delegation-status endpoint
- [x] 1.4 — Remove the platform upper bound on the guardrail in the REST schema layer
- [x] 1.5 — Remove the mirrored upper bound in the assistant-managed validation path
- [x] 1.6 — Update the assistant-facing guardrail field description

### Phase 2 — Agent Runtime depth resolution and enforcement

- [x] 2.1 — Remove the forced single-level cap for non-conversational agents
- [x] 2.2 — Start each run from the job's recorded delegation depth
- [x] 2.3 — Seed the Control Center-side task loop from the agent type configuration
- [x] 2.4 — Replace the task-loop fallback guardrail state with the resolved configuration
- [x] 2.5 — Replace the act-phase fallback guardrail state and correct the blocked message
- [x] 2.6 — Confirm enforcement sites compare the configured limit with the actual chain depth

### Phase 3 — Frontend configuration and log scoping

- [x] 3.1 — Remove the hard-coded depth ceiling from the Agent Type form
- [x] 3.2 — Remove the hard-coded depth ceiling from the Agent Properties panel
- [x] 3.3 — Sweep remaining frontend and draft-composition validation for a depth ceiling
- [x] 3.4 — Add a pure direct-child peek filter helper
- [x] 3.5 — Apply the filter to the delegation card peek only

### Phase 4 — Tests

- [x] 4.1 — Update backend tests that encode the old fixed-depth behaviour
- [x] 4.2 — Add Agent Runtime depth-resolution and nested-delegation tests
- [x] 4.3 — Add Control Center API and validation-bound tests
- [x] 4.4 — Add frontend peek-filter and configuration-input tests
- [x] 4.5 — Run backend and frontend suites plus syntax checks

### Phase 5 — Consistency and handover

- [x] 5.1 — Sweep for residual hard-coded depth constants and stale wording
- [x] 5.2 — Confirm no schema, service-boundary, or endpoint changes
- [x] 5.3 — Record implementation notes for the tester and master-doc updates

---

## Phase 1 — Control Center depth plumbing (no schema change)

**1.1 — Expose the job's recorded delegation depth on the internal session payload**

Extend the Control Center internal session response model with an integer `delegation_depth` field and populate it from the `AgentJob` row in the internal session lookup handler. The payload is the only path by which Agent Runtime learns a delegated child's recorded depth, so the value must be the persisted job column, not a value derived from `input_data`. Keep every existing field and the existing route unchanged.

**Done when:** the internal session response model declares `delegation_depth` as a required integer, the handler returns the job's persisted depth, and no other construction site of that model exists (so no caller is left unpopulated).

**1.2 — Verify delegated job parent linkage and document conversational depth behaviour**

Confirm that the A2A preparation path resolves a parent job only when the requester identifier is an existing agent job, and that the enqueue path derives the child's depth from that parent. Do not add a schema field, and do not change the enqueue derivation. Confirm whether a conversational parent can be resolved through the conversation session's linked job; if resolution is not reliable for conversational delegations, record that conversational delegation children start at their own recorded depth (zero when no parent job was linked) and that this is the accepted behaviour for this change. Capture the finding in the technical spec rather than inventing new state.

**Done when:** the parent-link resolution rule and its conversational limitation are stated explicitly in the technical spec, and no production behaviour outside this change's scope has been altered.

**1.3 — Return the configured maximum depth from the delegation-status endpoint**

Stop returning a constant maximum from the delegation status handler. Return the session agent type's configured `guardrail_max_delegation_depth`, using the already eagerly loaded agent type on the session. Keep the response's field set and JSON shape identical; only the value's meaning changes. If the agent type cannot be resolved, fall back to the platform default guardrail value rather than to a one-level constant, so no caller can observe a cap. Leave the pending-intervention query scoped to direct children only.

**Done when:** the status handler returns the configured agent-type maximum for two agent types configured with different depths, the response model no longer defaults to a one-level cap, and the pending-intervention handler's query scope is unchanged.

**1.4 — Remove the platform upper bound on the guardrail in the REST schema layer**

Remove the maximum bound from the guardrail contract validation for Max Delegation Depth while keeping the non-negative floor, integer coercion, and the existing structured error text path. Change nothing about the other guardrail bounds. Keep the constant that represented the ceiling from being reused as an implicit limit elsewhere.

**Done when:** a delegation depth above the previously permitted ceiling passes validation, a negative value is still rejected, and every other guardrail bound rejects and accepts exactly as before.

**1.5 — Remove the mirrored upper bound in the assistant-managed validation path**

Apply the same relaxed bound to the structured validation used by assistant-managed agent-type writes, keeping its per-field structured error reporting and the conversational-token rule untouched. The two validation paths must accept and reject the same delegation depths.

**Done when:** an assistant-managed create or update with a delegation depth above the old ceiling validates successfully, and a parity check between the REST and assistant-managed validators shows identical accept/reject outcomes for the depth field.

**1.6 — Update the assistant-facing guardrail field description**

Update the assistant tool-schema description for the delegation depth field so it no longer advertises a fixed upper bound, while still stating the non-negative floor and the default. Do not change any other guardrail description or any tool wiring.

**Done when:** no assistant-visible description of Max Delegation Depth states a numeric ceiling, and the field remains discoverable with its default value.

---

## Phase 2 — Agent Runtime depth resolution and enforcement

**2.1 — Remove the forced single-level cap for non-conversational agents**

Delete the input-type branch in the guardrail state builder that overwrites the resolved maximum with a single level. The value resolved from the context's guardrail policy must be used unchanged for both conversational and task agents. Retain the platform default only for the case where the policy carries no value, and ensure it is applied as a default, never as a reduction.

**Done when:** a task agent with a configured depth of three resolves a maximum of three, a conversational agent with a configured depth of three resolves three, and an agent with no policy value resolves the unchanged platform default.

**2.2 — Start each run from the job's recorded delegation depth**

Change the guardrail state builder to read the run's starting depth from the job payload's recorded delegation depth, falling back to the legacy input-data depth key only for backward compatibility. Seed both the loop's tree depth and the guardrail state's delegation depth from that value so the enforcement sites compare the real chain depth rather than zero. Root runs must be unaffected because their recorded depth is zero.

**Done when:** a job payload carrying a recorded depth of two produces a guardrail state whose tree depth and delegation depth are both two, a payload carrying only the legacy input key still resolves the same way, and a payload carrying neither resolves zero.

**2.3 — Seed the Control Center-side task loop from the agent type configuration**

In the Control Center-side task loop, replace the constant maximum depth on the loop context with the agent type's configured guardrail maximum (defaulting to the platform default when absent), and seed the loop's own depth fields from the job's recorded depth. Keep the cycle, delegated-step, iteration, timeout, and token behaviour untouched.

**Done when:** the task loop context for a task agent configured deeper than one carries that depth, the loop's starting depth equals the job's recorded depth, and no code path in this loop constructs a loop context with a one-level cap.

**2.4 — Replace the task-loop fallback guardrail state with the resolved configuration**

Replace the inline guardrail state built from constants in the Control Center-side task loop with one derived from the same resolved configuration used by the loop context: iteration budget, delegation maximum, delegated-step budget, execution timeout, token settings, and a policy snapshot identifier tied to the agent type. The fallback must never impose a shallower depth than the configured value.

**Done when:** the task-loop fallback state reports the agent type's configured maximum, iteration budget, step budget, and timeout, and a grep of the task loop shows no remaining depth constant.

**2.5 — Replace the act-phase fallback guardrail state and correct the blocked message**

In the act phase, when no guardrail state is supplied, build the fallback from the loop context's configured maximum and depth instead of from constants, and keep the fallback consistent with the context's iteration, step, timeout, and token settings. Update the depth-blocked tool result text so it states that the configured maximum was reached instead of asserting a one-level task-agent rule. The block must still emit the existing depth-blocked execution event and return a blocked tool result.

**Done when:** an act-phase delegation with no supplied guardrail state blocks at the loop context's configured maximum, the emitted event carries the configured maximum, and no message asserts a fixed one-level limit.

**2.6 — Confirm enforcement sites compare the configured limit with the actual chain depth**

Review the runtime limit check and the guardrail callback's depth check and confirm their comparison semantics are unchanged: both compare the configured maximum against the run's own chain depth and stop the run only when that depth exceeds the limit. The task-loop delegation guard is a separate check and keeps its existing rule — a hop is blocked when it would create a depth beyond the configured maximum. Do not remove or relax enforcement, cycle detection, dead-loop detection, step budgets, iteration ceilings, timeouts, or token budgets. Where the comparison reads one depth field and the other reads a different one, make both read the same configured limit and the same actual chain depth.

**Done when:** the two run-level checks stop a run exactly when its own chain depth exceeds the configured maximum, the task-loop attempt guard still blocks a hop that would exceed it, blocks still raise or emit the pre-existing guardrail reasons, and a code review confirms all adjacent guardrails are untouched.

---

## Phase 3 — Frontend configuration and log scoping

**3.1 — Remove the hard-coded depth ceiling from the Agent Type form**

Remove the maximum attribute from the Max Delegation Depth numeric input in the Agent Type form while keeping the non-negative minimum and the existing change handler. Do not alter labels, defaults, layout, or any other guardrail input.

**Done when:** the form allows typing a depth above the old ceiling, still prevents negative input, and no other field's constraints changed.

**3.2 — Remove the hard-coded depth ceiling from the Agent Properties panel**

Apply the same removal to the Agent Properties panel input, keeping its minimum and change handler. Keep the panel's draft-composition mapping untouched.

**Done when:** the panel accepts a depth above the old ceiling, still enforces the non-negative minimum, and the draft it produces carries the typed value unchanged.

**3.3 — Sweep remaining frontend and draft-composition validation for a depth ceiling**

Search the frontend for any other numeric ceiling applied to the delegation depth, including draft composition, agent-type mapping, conversational management payload handling, and any client-side validation. Remove only genuine depth ceilings; leave unrelated limits (iterations, delegated steps, timeouts, token budgets) exactly as they are.

**Done when:** no frontend code path clamps the delegation depth to a fixed maximum, and the other guardrail limits are demonstrably unchanged.

**3.4 — Add a pure direct-child peek filter helper**

Add a small pure helper module that decides whether a log entry is eligible for a parent's direct-child progress peek. The predicate must accept an event type plus its data, keep the existing peek allow-list, and additionally exclude entries that represent the child's own delegation: delegation lifecycle event types and tool-call/tool-response entries whose tool name resolves to an agent delegation target (both the canonical and legacy delegation tool-name prefixes). The helper must not mutate input, must not fetch anything, and must be independently importable for unit testing.

**Done when:** the helper is exported with named functions and a named allow-list constant, has no React or network imports, and returns deterministic results for allow-listed, delegation-tool, and unlisted event types.

**3.5 — Apply the filter to the delegation card peek only**

Use the helper where the delegation card builds its short child progress peek, replacing the inline allow-list filter, and leave the entry slicing behaviour intact. Do not change the layout, timeline, status chips, or the existing View Execution Logs drill-in action. The child's own log view and the parent's own log must remain unfiltered by this helper, so opening the child's log still shows the child's own delegation events.

**Done when:** the parent's peek no longer shows the child's onward delegation tool calls or delegation lifecycle entries, the peek still shows the child's own initialization, tool, model, observation, and completion entries, and the drill-in renders the child log with its delegation entries intact.

---

## Phase 4 — Tests

**4.1 — Update backend tests that encode the old fixed-depth behaviour**

Update the existing unit tests that assert a forced one-level maximum for task agents, a fixed conversational default, the old depth-check shapes, and depth fields on intervention turns. Rewrite assertions to the new contract: configured value is authoritative for every input type, unconfigured types keep the unchanged default, and enforcement still blocks above the configured limit.

**Done when:** the delegation depth guard, agent runtime executor, guardrail callback, and conversation intervention turn unit suites pass with assertions that reference configured values rather than constants.

**4.2 — Add Agent Runtime depth-resolution and nested-delegation tests**

Add coverage that a nested task delegation is allowed while within the configured maximum, that a delegation is blocked when it would exceed the configured maximum, that a delegated child run starts from its recorded depth, and that the recorded depth wins over the legacy input-data key when both are present. Add coverage that the depth-blocked event carries the configured maximum.

**Done when:** the new tests fail against the old behaviour and pass after the change, and they cover allowed, blocked, and recorded-depth-start scenarios for both the Control Center-side task loop path and the delegated child run path.

**4.3 — Add Control Center API and validation-bound tests**

Add coverage that the internal session payload exposes the persisted delegation depth, that the delegation status returns the configured maximum for two agent types with different configurations, and that guardrail validation accepts depths above the old ceiling in both the direct API and assistant-managed paths while still rejecting negative values. Add a regression assertion that the pending-intervention query remains direct-child scoped.

**Done when:** the new Control Center tests pass and each assertion is tied to the configured value, the persisted job column, or the removed ceiling rather than to a constant.

**4.4 — Add frontend peek-filter and configuration-input tests**

Add unit tests for the peek filter helper covering allow-listed entries, canonical and legacy delegation tool-call entries, delegation tool responses, and delegation lifecycle entries. Add component coverage that the delegation card's peek excludes the child's onward delegation entries while the drill-in still yields the child log unfiltered. Add input coverage that the Agent Type form and Agent Properties panel accept a depth above the old ceiling.

**Done when:** the frontend suites covering the helper, the delegation card, and the two configuration inputs pass, and the peek test proves a sub-delegation can no longer leak into the parent's peek.

**4.5 — Run backend and frontend suites plus syntax checks**

Run the affected backend unit suites, then the full backend unit suite for regressions. Run the frontend Vitest suite using the JSON reporter and inspect the pass/fail counts. Run a Python syntax/compile check over every touched backend module and a TypeScript type check over the frontend. Confirm no test asserts a one-level platform cap remains.

**Done when:** all touched backend suites pass, the frontend suite reports zero failures, the backend modules compile cleanly, the TypeScript check reports no new errors, and no remaining test asserts a platform-imposed one-level depth.

---

## Phase 5 — Consistency and handover

**5.1 — Sweep for residual hard-coded depth constants and stale wording**

Search both services and the frontend for remaining one-level depth constants, comments referencing a Phase 1.1 task-agent override, log/tool messages asserting a one-level cap, and code comments that describe depth as input-type dependent. Correct wording only; do not change unrelated guardrail constants.

**Done when:** no comment, message, or constant in the touched modules implies a platform-imposed delegation depth cap, and unrelated guardrail constants are unchanged.

**5.2 — Confirm no schema, service-boundary, or endpoint changes**

Verify that no model or migration file changed, that Agent Runtime and Communication Hub still obtain depth and configuration only through Control Center internal calls, and that no route was added or removed. Confirm the internal session payload's new field is additive and consumed through the existing client method without a client-side signature change.

**Done when:** the change set contains no migration or model edits, no new route, and no direct database access added outside Control Center.

**5.3 — Record implementation notes for the tester and master-doc updates**

Summarise for the tester the changed behaviours, the new and updated test files, and the exact scenarios that must be re-verified, including the single-level log-scoping guarantee. Note the master-doc updates the architecture change document already calls for so they are not lost at the update-master stage.

**Done when:** the handover notes name the behaviours, the test entry points, and the deferred master-doc updates, and the tester has enough detail to build the test plan without re-reading the source.

---

## Completion Checklist

- [x] The configured Max Delegation Depth is the only depth limit for conversational and task agents.
- [x] Task agents configured for deeper delegation can delegate through additional levels while within their configured maximum.
- [x] Over-deep delegation is still blocked, recorded, and reported against the configured maximum.
- [x] A delegated child run evaluates nested delegation from its own recorded depth.
- [x] The delegation status response reports the session agent type's configured maximum.
- [x] Guardrail validation accepts any non-negative depth in both the direct and assistant-managed paths.
- [x] Frontend configuration inputs no longer clamp the depth to a fixed ceiling.
- [x] The parent delegation card's progress peek excludes the child's own delegation activity.
- [x] The child's own log still shows its own delegation events and its own peek.
- [x] Execution-log query scope remains single-session with no recursive aggregation.
- [x] Cycle detection, dead-loop detection, delegated-step budgets, iteration ceilings, timeouts, and token budgets are unchanged.
- [x] No migration, no model change, no new endpoint, and no service-boundary change.
- [x] Backend unit suites and the frontend Vitest suite pass with no regressions.
