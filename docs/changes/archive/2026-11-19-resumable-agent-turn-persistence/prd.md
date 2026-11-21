# PRD: Resumable Agent Turn Persistence

## Epic Overview

Parthenon's conversational chat — the Control Center Assistant and conversational agents — can pause a turn to ask a human for confirmation before performing a change. Today that paused turn lives entirely inside the memory of the single backend server that paused it. If that server is restarted during a pending confirmation (a deployment, a crash, routine maintenance), the pause is gone: when the operator later approves or denies, they are told "Delegated step timed out or failed." — even though the conversation, the pending request, and the operator's intent are all still perfectly valid. The practical result is that operators cannot trust the assistant across deployments, must avoid approving anything near a release window, and the platform cannot safely scale or fail over because a conversation resumed on a different server cannot continue its own work. A previous change made the *status* of a turn persistent, so the interface now shows the right activity — but the *work in flight* is still trapped in one process. This epic makes a paused conversational turn durably resumable: after a restart, or on any other backend instance, approving or denying continues the assistant's work; and when a turn genuinely cannot be resumed, it resolves cleanly with one clear, actionable message instead of a misleading timeout.

## Business Goals

- Operators who approve or deny a pending confirmation after a restart get the assistant's continued work, not a confusing timeout — measured as zero misleading "timed out or failed" outcomes for turns whose confirmation was still outstanding.
- 100% of in-flight conversational turns remain valid across service restarts and are correctly handled by any backend instance, making deployments, scaling, and failover invisible to users.
- Routine operations (restart, scale up/down, instance replacement) no longer require operators to avoid or abandon approvals; restart-related assistant incidents and escalations drop to zero.
- Genuinely unrecoverable turns resolve with a single clear, actionable message naming what happened and what to do next, instead of a generic failure that invites guessing.
- Reliability is gained without weakening the platform's segregation guarantees: resuming work never requires an execution service to hold identity tokens, database credentials, or other secrets.

## Users & Personas

- **Platform / Tenant Administrators** — use the assistant for multi-step agent administration; need an approval they gave after a restart to actually take effect.
- **Operations / SRE Staff** — restart, scale, and fail over backend services; need to do so at any moment without breaking paused conversations or coaching users around release windows.
- **Compliance & Security Reviewers** — need assurance that durability does not widen access to secrets and that every resumed action stays attributed to the responding user.
- **Agent Builders** — rely on human-in-the-loop steps being dependable by default, without designing their own workarounds for restarts.
- **Returning / Reconnecting Users** — come back to a conversation with a pending confirmation and need it to still be actionable.

## User Stories

- As an administrator awaiting a confirmation, I want my approval given after a restart to continue the assistant's work from where it paused, so that a multi-step task is not lost because of a deployment.
- As an administrator, I want a denial after a restart to resolve the turn cleanly with nothing written, so that I remain in control of changes.
- As an operator, I want a turn that is genuinely dead to tell me clearly what happened and what to do next, so that I am never left guessing whether my action worked.
- As an SRE, I want in-flight conversational work to survive a restart and to be servable by any backend instance, so that deployments, scaling, and failover are safe at any time.
- As an SRE, I want to restart a single service without corrupting paused approvals, so that routine maintenance carries no user-visible risk.
- As a security reviewer, I want resumption to work without execution services holding tokens or database credentials, so that reliability does not erode segregation.
- As an agent builder, I want human-in-the-loop steps to be durable by default, so that I do not have to design my agents around restarts.
- As a returning user, I want a pending confirmation that is still valid to still be actionable when I come back to the conversation.

## Acceptance Criteria

### Approving and Denying After a Restart

- A confirmation that was pending when a backend service restarted is still presented as pending when the operator returns, and approving it continues the assistant's work rather than producing a timeout.
- Denying that confirmation after a restart resolves the turn cleanly — the assistant acknowledges the rejection and offers to adjust — and nothing is written.
- The resumed turn keeps the same conversation history and context as before the restart: no duplicated turns, no missing turns, and no repeated side effects (a confirmed change is applied exactly once).
- A restart of any service in the path — not only the one hosting the chat view — leaves a pending confirmation actionable.

### Any Server, Scaling and Failover

- A conversation whose turn paused on one backend instance can be continued on a different instance: the approval is accepted there and the work proceeds.
- Two instances serving the same conversation in sequence do not treat the turn as lost, and the operator sees one coherent conversation.
- Increasing or decreasing the number of backend instances does not change the outcome of a paused confirmation.

### Clear Resolution When a Turn Cannot Be Resumed

- When a paused turn genuinely cannot be resumed (for example the confirmation is answered after the allowed window, or the work was deliberately ended), the operator sees one clear message explaining what happened and the next step (such as re-issuing the request).
- The misleading "delegated step timed out or failed" message is not shown for a turn whose confirmation was still valid.
- A turn that cannot be resumed does not leave the conversation stuck: status reaches a terminal state, message input is re-enabled, and the outstanding confirmation is no longer presented as actionable.
- The conversation distinguishes, in plain terms, between waiting for the user, resumed and continuing, resolved, and no longer resumable.
- Acknowledging a no-longer-resumable turn never silently retries or double-applies a change.

### Consistency of Confirmed Actions

- Approving a confirmation results in exactly one application of the confirmed change, even when the approval is delivered more than once (reconnect, repeated click, or an instance change mid-response).
- A denied or expired confirmation never results in a change being applied.
- The response and the resumed outcome each appear once, in order, in conversation history and in replay.

### Segregation and Privacy

- Resuming a turn never requires an execution service to hold identity tokens, database credentials, or other secrets, and the durable turn information itself contains no sensitive material.
- A resumed turn stays scoped to its own conversation and tenant, and remains attributed to the user who actually responded.

## Out of Scope

- Changing the confirm-before-write preview format or the approval/denial interaction design itself.
- Any new assistant management capability, or any change to what the assistant can create or update.
- Model selection, model quality, or the assistant's reasoning behaviour.
- Resumption of non-conversational (typed/task) executions and their logs.
- General exactly-once guarantees for external systems that tools already contacted — this epic covers the conversational turn, not third-party side-effect compensation.
- Multi-region or active-active data topologies, or changing the single-database ownership boundary.
- Redesigning the activity/thinking indicator (already delivered by the persistent activity state change).

## Dependencies & Constraints

- **Builds on the persistent activity state change**: that change made a turn's *status* durable; this epic extends durability to the *work in flight*. The two must agree — a turn shown as "waiting for your input" must actually be resumable.
- **Service segregation is non-negotiable**: three fully segregated backend services, agents run only in Agent Runtime, only Control Center connects to the database, and agents never hold sensitive data (identity tokens, database credentials). Durable resumption must therefore be coordinated in a way that preserves these boundaries.
- **Assumption — meaning of "resumable"**: the approved or denied answer is accepted and the turn continues from the pause point; a model call interrupted mid-reasoning is not replayed mid-stream. Where the pause point cannot be re-established, the turn resolves with the clear terminal message instead.
- **Assumption — bounded validity**: a paused confirmation does not remain actionable forever. Answering after the window is treated as a legitimately unrecoverable turn with an actionable message; the exact window is a configuration decision, not a product promise.
- **Assumption — conversational surfaces covered**: the Control Center Assistant, conversational agent types used in the Control Center, and conversational third-party client sessions — every surface that can pause for human input.
- Depends on existing conversational session persistence, reconnect behaviour, and the existing human-intervention path; no new approval mechanism is introduced.
- Depends on the existing permission model: resuming never elevates privileges, and the responding user's scope still governs what the resumed action may do.
- Restart and failover must remain safe at any point in a turn, including while a confirmation is being answered.
- When multi-tenancy is enabled, a resumed turn stays inside its conversation's tenant; resumption never crosses tenants.
