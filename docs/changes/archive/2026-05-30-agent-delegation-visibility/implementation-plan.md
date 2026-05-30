# Implementation Plan: agent-delegation-visibility

## Overview

Initial implementation delivered minimal chat UX signals:

- thinking animation while the conversational turn is in progress,
- one delegation label in format `Delegating to agent <agent_type>` when delegation starts,
- waiting animation until delegated response or timeout.

Refinement scope adds:

- live streaming for non-conversation execution logs,
- folded-by-default delegation execution log snippets in chat surfaces.

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

### Phase 5 — Backend non-conversation live log streaming

- [x] 5.1 Add additive live execution-log stream endpoint for agent sessions in `backend/app/api/v1/agents.py`.  _Done when: clients can subscribe to per-session log entries while status is non-terminal and receive ordered append-only events._
- [x] 5.2 Implement terminal-state completion signaling on the stream with graceful close semantics.  _Done when: stream emits an explicit completion marker for completed/failed sessions and closes without breaking existing pull APIs._
- [x] 5.3 Keep pull endpoints as fallback/backfill path.  _Done when: `GET /agents/sessions/{id}/logs` and `GET /agents/sessions/{id}/execution-logs` continue unchanged and remain usable for reconnect recovery._

### Phase 6 — Frontend non-conversation live log consumption

- [x] 6.1 Add a dedicated stream-consumption hook for session execution logs in `frontend/src/hooks`.  _Done when: hook exposes connection state, incremental entries, and reconnect/fallback handling._
- [x] 6.2 Integrate live stream into `AgentJobPage` for running non-conversation sessions.  _Done when: log entries append in near real time without manual refresh while preserving existing terminal refetch safeguards._
- [x] 6.3 Update non-conversation log surfaces to use live updates consistently.  _Done when: `AgentExecutionDetailsDialog` and `SessionExecutionLogsDialog` reflect newly appended entries during active runs._
- [x] 6.4 Preserve span-based presentation while streaming.  _Done when: streamed entries continue to render through `LogViewer`/`WorkingStepsPanel` without regression to flat table/list output._

### Phase 7 — Chat folded snippet UX refinement

- [x] 7.1 Extend `useChatSession` to accumulate delegation snippet lines from status/tool events.  _Done when: hook returns ordered snippet data including `agent_type`/`tool_name` context for preview rendering._
- [x] 7.2 Add folded-by-default snippet panel to `ChatPage`.  _Done when: panel starts collapsed, shows concise preview, and expands on user action without disrupting message flow._
- [x] 7.3 Add folded-by-default snippet panel to `ConversationDialog`.  _Done when: dialog mirrors `ChatPage` behavior for collapse/expand and snippet preview consistency._
- [x] 7.4 Extend i18n copy for snippet panel labels and empty state.  _Done when: all snippet UI text is translated via `t()` with no hardcoded labels._

### Phase 8 — Refinement verification

- [x] 8.1 Add backend tests for live execution-log stream lifecycle.  _Done when: tests cover incremental emission, terminal marker behavior, and backward compatibility with existing log endpoints._
- [x] 8.2 Expand `useChatSession` tests for snippet aggregation and folded defaults.  _Done when: tests verify snippet list accumulation, collapse default, and timeout/terminal interactions._
- [x] 8.3 Expand chat UI component tests for snippet preview and expand/collapse interactions.  _Done when: `ChatPage` and `ConversationDialog` tests assert folded default, preview content, and explicit user expansion._
- [x] 8.4 Add frontend tests for non-conversation live log rendering.  _Done when: tests verify running sessions append logs live and fallback poll/reconnect behavior remains stable._

## Completion Checklist

- [x] Thinking animation appears while conversational processing is active.
- [x] Delegation label appears as `Delegating to agent <agent_type>` at delegation start.
- [x] Waiting animation persists until delegated response or timeout/failure signal.
- [x] Existing runtime/delegation behavior remains unchanged.
- [x] One additive REST endpoint was introduced for live execution-log streaming; no new services or schema changes were introduced.
- [x] Unit tests and frontend tests for new status behavior pass.
