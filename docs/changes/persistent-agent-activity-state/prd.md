# PRD: Persistent Agent Activity State

## Epic Overview

The Control Center Assistant (and conversational agents generally) shows a "thinking" activity indicator while working. Today that indicator is driven by ephemeral signals with no single, persisted, authoritative record of what the assistant is doing right now. As a result the indicator is unreliable: it can vanish before a human-intervention prompt appears (leaving a confusing blank gap), disappear entirely when a user exits and re-enters a conversation that is still running, keep spinning after the assistant has finished, or disappear while the assistant is still working. This epic delivers a single, persisted, authoritative activity state for the assistant so that users always see an accurate live processing status, and so that in-flight work can be recovered after a service restart or a hand-off to another backend server. This is the foundation that makes conversational processing dependable and lets the platform scale and fail over without confusing users.

## Business Goals

- Users always see an accurate, live indication of what the assistant is doing — thinking, calling a tool, delegating, waiting for the user, or finished — with no wrong or misleading status.
- Eliminate blank gaps and stuck spinners around human-intervention ("confirm-before-write") flows: the "waiting for your input" state is shown continuously from the moment the assistant pauses until the intervention is resolved.
- Any user who closes, reopens, or reloads a conversation sees the assistant's latest status immediately, matching what was shown before they left.
- The assistant's in-flight work survives a service restart and can be resumed on any backend server, so the platform can scale and fail over without losing or misrepresenting conversational progress.

## Users & Personas

- **Platform / Tenant Administrators** — rely on the assistant for agent administration and need to trust that the indicator reflects real progress, especially when an approval prompt is expected.
- **Returning / Reconnecting Users** — close and reopen conversations mid-task and must be able to pick up exactly where they left off, seeing that the assistant is still working (or waiting).
- **Compliance & Security Reviewers** — need assurance that the persisted activity state never contains sensitive material (identity tokens, database credentials, decrypted secrets).
- **Operations / SRE Staff** — restart or scale backend services and need conversational work to recover cleanly with no user-visible corruption or stuck state.

## User Stories

- As an administrator, I want the assistant to show me exactly what it is doing at any moment (thinking, calling a tool, delegating, waiting for me, or finished), so that I always know whether it is my turn to act.
- As an administrator awaiting a confirm-before-write approval, I want the "waiting for your input" state to stay visible from the moment the assistant pauses until I respond, so that I am never left with a confusing blank gap.
- As a returning user, I want to close and reopen (or reload) a conversation and immediately see the assistant's latest status, so that I can tell whether it is still working, waiting for me, or finished.
- As an operator, I want the assistant's in-flight work to survive a service restart and resume on any backend server, so that platform scaling and failover never loses or misrepresents my conversation.
- As a security reviewer, I want the persisted activity record to contain only status information and never any sensitive credential or token, so that persisting activity does not widen the exposure of secrets.

## Acceptance Criteria

### Accurate Live Status

- While the assistant is working, the chat window shows a visible activity indicator that reflects the assistant's actual current activity: thinking, calling a tool, delegating to another agent, waiting for the user, or finished.
- The indicator changes state promptly as the assistant moves between activities, without lingering in a previous state.
- When the assistant finishes a turn, the indicator stops and a clear finished (or timeout/failure) state is shown; the indicator never keeps spinning after completion.

### Human-Intervention Flows

- When the assistant pauses to request human input (e.g. a confirm-before-write approval), the "waiting for your input" state is shown continuously from the moment the assistant pauses until the user resolves the intervention — there is no blank gap.
- While an intervention is outstanding, the chat window blocks new input and clearly shows the waiting state, consistent with the existing intervention dialog behavior.
- When the user resolves or rejects the intervention, the status advances correctly to the next activity (resumed work or finished), with no stuck spinner.

### Resume, Reload, and Reconnect

- If a user closes and reopens (or reloads) a conversation while the assistant is still working, the chat window immediately shows the assistant's current status (working, delegating, waiting for input, or finished) rather than an empty or stale view.
- If a user reconnects to a conversation that was mid-intervention, the pending intervention and its "waiting for your input" status are re-surfaced automatically, consistent with existing intervention behavior.
- The restored status matches the assistant's real state at the moment of reconnection, not the state at the time the user left.

### Restart and Failover Resilience

- If a backend service restarts while the assistant is mid-turn, the assistant's current activity state is preserved and the correct status is shown when the user (or any backend server) resumes the conversation.
- A conversation that was in flight can be resumed on a different backend server with the assistant's latest status intact, supporting multi-server scaling and failover.
- Stale or orphaned activity states do not persist indefinitely: work that can no longer be resumed resolves to a clear terminal status (finished, failed, or timed out) rather than a perpetual "working" or "waiting" indicator.

### Privacy and Scope

- The persisted activity state contains only status information; it never includes identity tokens, database credentials, decrypted connection secrets, or any other sensitive material.
- The activity state is scoped per conversation (and per tenant when multi-tenancy is enabled) so one user's status can never leak into another's conversation.

## Out of Scope

- Changes to the assistant's management capabilities or the resources it can create/update — this change is only about how its activity is tracked and displayed.
- Changes to the confirm-before-write preview format or the approval/rejection flow itself.
- Changes to non-conversational execution status surfaces (e.g. the Agent Runtime Monitor and execution logs) beyond ensuring the shared delegation and intervention status signals remain consistent.
- New deletion capabilities or any expansion of what the assistant can do.
- Content generation quality, model selection, or the underlying reasoning of the assistant.

## Dependencies & Constraints

- Service segregation (top-priority rules) must hold: agents run only in the Agent Runtime, only the Control Center connects to the database, and agents never receive sensitive data (identity tokens, database credentials). The persisted activity state must respect this boundary and never carry sensitive material across service boundaries.
- The activity states must align with the platform's existing conversational concepts — thinking/working indicators, delegation visibility cues, and the "waiting for your input" intervention block — so the new status model extends rather than duplicates existing behavior.
- Assumption: the observable activity states are "thinking", "calling a tool", "delegating", "waiting for the user", and "finished" (with terminal "failed" and "timed out" outcomes). The change applies to the conversational chat surface (the Control Center Assistant and other conversational agents); non-conversational execution keeps its existing status surfaces.
- Assumption: a single, authoritative activity record is the intended source of truth, replacing the current ephemeral, in-memory signals. This record is persisted by the platform (through the Control Center, which owns data) and readable by the chat surface regardless of which backend server is handling the conversation.
- Depends on the existing resumable-session and reconnect behavior so that restoring a conversation also restores its activity status.
