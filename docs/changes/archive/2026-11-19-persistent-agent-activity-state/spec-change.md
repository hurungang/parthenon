# Spec Change: Persistent Agent Activity State

## Affected Spec Areas

- [Conversation Management](../../master/product/features/conversation-management.md) — thinking/waiting indicators, delegation visibility cues, intervention block states, and session resumption
- [Control Center Assistant](../../master/product/features/control-center-assistant.md) — the assistant's processing indicator and resumable-session behavior
- [Control Center](../../master/product/features/control-center.md) — the embedded assistant integration surface and its activity visibility
- [Communication Hub](../../master/product/features/communication-hub.md) — session context and real-time status delivery
- [Agent Execution](../../master/product/features/agent-execution.md) — delegation and intervention status lifecycle for in-flight work

## New Capabilities

- **Persisted authoritative activity state**: the platform maintains a single, persisted record of the assistant's current activity (thinking, calling a tool, delegating, waiting for the user, or finished) for each conversational turn.
- **Accurate live processing status**: the chat window reflects the assistant's true activity at all times, with prompt transitions between states and no stale indicators.
- **Continuous intervention-wait visibility**: the "waiting for your input" state persists without gaps from the moment the assistant pauses until the intervention is resolved.
- **Status restoration on resume**: reopening or reloading a conversation restores the assistant's current status, including re-surfacing a pending intervention and its waiting state.
- **Restart and failover resilience**: the assistant's in-flight activity state survives a service restart and can be resumed on any backend server.

## Modified Capabilities

- **Processing indicator (before → after)**
  - Before: the thinking indicator is driven by ephemeral, in-memory signals and is unreliable — it can disappear before an intervention prompt appears, vanish on re-entry, keep spinning after completion, or vanish mid-work.
  - After: the indicator is backed by a single persisted authoritative activity state and always reflects the assistant's real current status.
- **Intervention-wait state (before → after)**
  - Before: a blank gap can appear between the assistant pausing and the intervention dialog surfacing.
  - After: the "waiting for your input" state is shown continuously through the whole pause, with no gap.
- **Conversation resume (before → after)**
  - Before: a user who exits and re-enters a still-running conversation cannot tell whether the assistant is working.
  - After: reconnecting restores the assistant's latest status, matching its real state at reconnection.
- **In-flight work recovery (before → after)**
  - Before: in-flight work is tied to the current service process and cannot be reliably resumed after a restart or a hand-off to another server.
  - After: in-flight work is recoverable and resumable on any backend server, with correct status.
- **Stale-state handling (before → after)**
  - Before: stuck spinners and orphaned "working" states can persist.
  - After: states transition promptly, and work that can no longer be resumed resolves to a clear terminal status rather than a perpetual indicator.

## Removed Capabilities

- None. No existing assistant or conversation capability is withdrawn; the change replaces the unreliable in-memory activity signals with a persisted authoritative state.

## Spec Update Instructions

- **conversation-management.md**: update the "Delegation Visibility Cues" and thinking-indicator descriptions to reference a persisted, authoritative activity state as the source of the processing status; document continuous intervention-wait visibility (no blank gap), status restoration on resume/reload, and restart/failover recovery; add terminal-state resolution for stale work.
- **control-center-assistant.md**: update the conversational-session and processing-indicator descriptions to state that the assistant's current activity is always known and persisted, and that resuming a session restores the latest status.
- **control-center.md**: note in the embedded-assistant integration description that its processing status is backed by a persisted activity state and is accurate across resume, restart, and failover.
- **communication-hub.md**: update the session-context and real-time-status descriptions to reflect delivery of the assistant's persisted activity state to the chat surface regardless of which backend server is serving the conversation.
- **agent-execution.md**: align delegation and intervention status-lifecycle descriptions with the persisted activity state, including recovery of in-flight work across restart/failover.
- **qa test plans (docs/master/qa/)**: add coverage for (1) accurate live status across all activity states, (2) gap-free intervention-wait visibility, (3) status restoration on reload/reconnect, (4) in-flight work recovery across a service restart and a server hand-off, and (5) no sensitive data in the persisted activity state.
