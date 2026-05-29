# Implementation Plan: agent-delegation-visibility

## Overview

Implement minimal chat UX signals only:

- thinking animation while the conversational turn is in progress,
- one delegation label in format `Delegating to agent <agent_type>` when delegation starts,
- waiting animation until delegated response or timeout.

No delegation/runtime business logic redesign is included.

## Task Checklist

### Phase 1 — Backend status signal plumbing (additive, non-invasive)

- [x] 1.1 Add lightweight delegation status metadata at the point where delegation tool calls are identified in conversation execution.  _Done when: delegation start includes parsed `agent_type` from `agent____<slug>` without changing dispatch behavior._
- [x] 1.2 Emit additive WebSocket status events from the existing chat flow (`thinking`, `delegating`, `waiting`, `timeout_or_failed`).  _Done when: existing chat messages still work unchanged and status events are visible on the same socket stream._

### Phase 2 — Frontend state handling

- [x] 2.1 Extend `useChatSession` with transient status state for thinking/delegating/waiting/timeout.  _Done when: hook updates status from outbound sends plus inbound status events and clears status on terminal conditions._
- [x] 2.2 Parse delegation target from status payload and expose a display-ready label value.  _Done when: hook provides `agent_type` for `Delegating to agent <agent_type>` with safe fallback for malformed payloads._

### Phase 3 — Chat UI rendering

- [x] 3.1 Add a compact animated status indicator to `ChatPage` for thinking and waiting states.  _Done when: animation appears during processing and disappears when final reply is received._
- [x] 3.2 Render delegation text exactly as `Delegating to agent <agent_type>` when delegation starts.  _Done when: displayed text matches required format and remains visible during waiting state._
- [x] 3.3 Add i18n keys for thinking, waiting, and timeout/failure status copy.  _Done when: all new status strings resolve via `t()` and no hardcoded user-facing text is introduced._

### Phase 4 — Verification

- [x] 4.1 Backend unit test for delegation status payload generation from `agent____<slug>`.  _Done when: test validates correct `agent_type` extraction and no behavior change in delegation call path._
- [x] 4.2 Frontend Vitest for `useChatSession` status transitions.  _Done when: tests cover send -> thinking, delegation event -> delegating/waiting, final response/timeout -> status clear or terminal label._
- [x] 4.3 Frontend component test for `ChatPage` status rendering text and animation visibility.  _Done when: required delegation label format and waiting/thinking indicators are asserted._

## Completion Checklist

- [x] Thinking animation appears while conversational processing is active.
- [x] Delegation label appears as `Delegating to agent <agent_type>` at delegation start.
- [x] Waiting animation persists until delegated response or timeout/failure signal.
- [x] Existing runtime/delegation behavior remains unchanged.
- [x] No new REST endpoints, services, or schema changes were introduced.
- [x] Unit tests and frontend tests for new status behavior pass.
