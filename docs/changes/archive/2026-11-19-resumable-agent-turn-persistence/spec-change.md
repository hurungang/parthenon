# Spec Change: Resumable Agent Turn Persistence

## Affected Spec Areas

- [Conversation Management](../../master/product/features/conversation-management.md) — intervention wait state, resume/reconnect behaviour, session lifecycle, turn history integrity
- [Control Center Assistant](../../master/product/features/control-center-assistant.md) — confirm-before-write approval continuity across restarts
- [Control Center](../../master/product/features/control-center.md) — ownership of an in-flight conversational turn and who can continue it
- [Communication Hub](../../master/product/features/communication-hub.md) — intervention response relay and resume signalling, session context continuity
- [Agent Execution](../../master/product/features/agent-execution.md) — human-in-the-loop intervention lifecycle (awaiting human input → resumed), conversational delegation interventions
- [Agent Runtime Monitor](../../master/product/features/agent-runtime-monitor.md) — pending interventions remaining visible and answerable after a restart
- [Third-Party Agent Integration](../../master/product/features/third-party-agent-integration.md) — conversational client sessions that pause for human input
- [Strict Tenant Isolation](../../master/product/features/strict-tenant-isolation.md) — resumption stays inside the conversation's tenant and inside service-segregation boundaries

## New Capabilities

- **Durable paused turn**: a conversational turn that pauses for human input remains valid beyond the lifetime of the server process that paused it, and remains answerable later.
- **Resumption on any instance**: a pending confirmation can be answered on a different backend instance than the one that paused it, and the turn continues there with the same history and context.
- **Resume-versus-resolve distinction**: the product distinguishes plainly between *waiting for the user*, *resumed and continuing*, *resolved*, and *no longer resumable*, both in the conversation and in its status.
- **Single-application guarantee for confirmed changes**: a confirmed change is applied exactly once even when the approval is delivered more than once (reconnect, repeat click, instance change mid-response).
- **Post-restart intervention continuity**: a pending intervention still appears as awaiting human input after a restart — in the conversation, in the session list, and on the Agent Runtime Monitor — and is still answerable.
- **Actionable terminal outcome**: a turn that cannot be resumed ends with one clear message naming the cause and the next step, rather than a generic failure.

## Modified Capabilities

- **Answering a confirmation after a restart (before → after)**
  - Before: approving or denying a confirmation whose server restarted produces "Delegated step timed out or failed." and the turn is lost.
  - After: the answer is accepted, the assistant continues from the pause point, and a denial resolves cleanly with nothing written.
- **Turn ownership across instances (before → after)**
  - Before: in-flight conversational work belongs to one process; a conversation routed to another instance cannot continue it.
  - After: in-flight work is durable and can be continued by any instance, so scaling and failover are transparent to users.
- **Intervention lifecycle termination (before → after)**
  - Before: a paused request could end in a generic failure status that misrepresents a still-valid turn.
  - After: a paused request ends only when it genuinely cannot be resumed, with an explanatory, actionable outcome; a blocked guardrail and an expired confirmation are still distinguishable to the user.
- **Pending-intervention visibility (before → after)**
  - Before: the persistent status indicator can show "waiting for your input" while the underlying turn no longer exists, so the state is right but the action fails.
  - After: what is shown as waiting is exactly what can be answered — status and turn validity always agree.
- **Restart and deployment safety (before → after)**
  - Before: operations teams must avoid restarting services, or warn users not to approve anything, during release windows.
  - After: restarts, scaling, and instance replacement are safe at any point in a turn.
- **Conversation history integrity (before → after)**
  - Before: a lost turn can leave a response recorded with no outcome, or an ambiguous half-finished exchange.
  - After: the response and the resumed (or resolved) outcome each appear once, in order, in history and replay.

## Removed Capabilities

- No user-facing capability is withdrawn.
- The generic "delegated step timed out or failed" message is no longer shown when the operator's confirmation was still valid; genuinely unresumable turns get a specific, actionable message instead.

## Spec Update Instructions

- **conversation-management.md**: document that a paused intervention is durable and answerable after a restart or on another instance; add the explicit waiting → resumed → resolved / no-longer-resumable status vocabulary; state that the "waiting for your input" indicator only appears when the turn is actually answerable; add the single-application guarantee for confirmed changes and turn-history integrity; keep existing intervention blocking behaviour unchanged.
- **control-center-assistant.md**: update the "Confirmation Before Any Write" and conversation-session sections to state that an approval or rejection remains effective across service restarts and instance hand-offs, that nothing is written until approval (unchanged), and that an unresumable request is explained with a clear next step rather than a timeout.
- **control-center.md**: describe conversational turn supervision as owning a durable turn that survives the serving process, without changing the existing turn-supervision protections; note that the existing terminal outcomes remain and that the misleading failure case is removed.
- **communication-hub.md**: update the intervention response/resume relay description so it reflects that a response can be delivered to a turn that was paused by a different instance, without granting the hub or the runtime new data access.
- **agent-execution.md**: align the human-in-the-loop intervention lifecycle (awaiting human input → resumed) with durable resumption; note that a pending intervention surviving a restart is still answerable and remains visible on the Agent Runtime Monitor; keep termination-cancels-pending-interventions behaviour.
- **agent-runtime-monitor.md**: state that interventions awaiting human input remain visible (with the existing alert icon) and answerable after a restart, and clear correctly once resolved.
- **third-party-agent-integration.md**: state that conversational client sessions that pause for human input are covered by the same durable-resumption behaviour, with identical tenant and permission scoping.
- **strict-tenant-isolation.md**: confirm that durable turn information carries no sensitive material and that resumption stays within the conversation's tenant and within existing service boundaries (agents only in Agent Runtime, database access only from Control Center).
- **Multi-tenancy note sweep**: where affected features carry a multi-tenancy note, confirm that resumed turns remain tenant-scoped; no behavioural change when multi-tenancy is disabled.
- **qa test plans (docs/master/qa/)**: add coverage for (1) approve/deny after a restart of each service in the path, (2) continuing a paused turn on a different instance, (3) exactly-once application under duplicate/repeated responses, (4) clear terminal outcome and input re-enablement for unresumable turns, (5) no misleading timeout for still-valid turns, and (6) no sensitive material in durable turn information.
- **Architecture / data-model / deployment / operations master docs**: to be updated by the architect, database designer, and developer from this change's `architecture.md`, `data-model.md`, `deployment.md`, and `operations.md` — this delta intentionally does not prescribe how resumption is achieved.
