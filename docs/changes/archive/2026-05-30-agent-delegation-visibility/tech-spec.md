# Technical Specification: agent-delegation-visibility

## 1. Technical Overview

This refinement extends visibility in two user-facing paths while keeping core delegation/runtime behavior unchanged:

- Conversational path: continue real-time chat status signaling, and add delegation execution log snippets that are folded by default and expandable on demand.
- Non-conversation path: stream session execution logs live while a run is active so users do not need manual refresh to observe progress.

Scope remains additive:

- No changes to delegation authorization, role resolution, or runtime business logic.
- No schema changes.
- Existing pull-based log endpoints remain for compatibility and fallback.

## 2. Component Breakdown

### `runtime_executor` (status and snippet-source events)

**File:** `backend/app/services/agents/runtime_executor.py`

- Continue emitting additive conversation status events (`thinking`, `delegating`, `waiting`, `using_tool`, terminal timeout/failure).
- Keep delegation target extraction from canonical tool names as the source for `agent_type` display text.
- Provide stable event ordering so chat snippet aggregation remains deterministic for UI folding/expansion.
- Do not alter permission checks, delegation dispatch, wait timeout values, or response composition logic.

### `websocket_chat` and Agent Runtime streaming bridge (chat transport)

**File:** `backend/app/api/ws/chat.py`

- Keep current WebSocket request/response turn flow.
- Continue forwarding status events from Agent Runtime streaming to chat clients as `chat_status` messages.
- Preserve backward compatibility for existing chat payloads while adding fields required for snippet rendering (`tool_name`, `agent_type`, timestamp).

### Agent Runtime conversational streaming endpoint

**File:** `backend/app/agent_runtime/api/conversation.py`

- Continue NDJSON streaming for conversation turns when status streaming is requested.
- Maintain `status_event` and `final` event sequence so Communication Hub can forward low-latency updates.

### Session execution-log live stream endpoint (non-conversation)

**File:** `backend/app/api/v1/agents.py`

- Add a live stream endpoint for per-session execution logs during active runs.
- Stream append-only execution log entries in timestamp order and emit a terminal marker when session reaches terminal status.
- Keep existing `GET /logs` and `GET /execution-logs` endpoints as pull/fallback APIs.

### `useChatSession` (status + snippet model)

**File:** `frontend/src/hooks/useChatSession.ts`

- Keep current transient status model for thinking/delegating/waiting/tool-use/timeout.
- Add a lightweight in-memory snippet list derived from delegation-related status/tool events.
- Expose folded-by-default snippet state and toggle handlers to chat UI consumers.
- Parse and normalize `agent_type`/`tool_name` for both status label and snippet preview lines.

### `ChatPage` and `ConversationDialog` (folded snippet UX)

**Files:**

- `frontend/src/pages/chat/ChatPage.tsx`
- `frontend/src/components/agents/ConversationDialog.tsx`

- Keep the compact status indicator for immediate feedback.
- Keep the live waiting/delegating status indicator visible during active delegation even before the first delegated agent reply is rendered.
- Add a delegation snippet panel in chat that is collapsed by default.
- Show preview text while collapsed; allow manual expand/collapse to inspect snippet lines.
- Keep exact delegation label format `Delegating to agent <agent_type>`.

### Non-conversation live log consumers

**Files:**

- `frontend/src/pages/agents/AgentJobPage.tsx`
- `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx`
- `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx`
- `frontend/src/components/executions/LogViewer.tsx`
- `frontend/src/components/executions/WorkingStepsPanel.tsx`

- Replace refresh-only behavior with live append while session is running.
- Feed streamed entries into existing span-based presentation (`LogViewer` + `WorkingStepsPanel`) to preserve hierarchy.
- Retain pull fallback for reconnect/recovery and historical replay.

### Locale strings (translation keys)

**File:** `frontend/src/i18n/locales/en.json`

- Keep existing status keys for thinking/delegating/waiting/timeout.
- Add snippet-panel labels (title, folded preview, expand/collapse controls, empty-state text).
- Keep all user-facing text under i18n (`t()`).

## 3. API Changes

### Existing (unchanged)

- `GET /api/v1/agents/sessions/{session_id}/logs`
- `GET /api/v1/agents/sessions/{session_id}/execution-logs`
- `WS /ws/sessions/{session_id}` chat channel continues sending additive `chat_status` events.
- `POST /internal/conversation/turn` in Agent Runtime continues optional NDJSON status streaming for conversation turns.

### New (additive)

- Live execution-log stream endpoint for non-conversation sessions under `agents/sessions/{session_id}`.
- Event payload carries incremental execution-log entries and terminal completion marker.
- Contract is append-only; no mutation/deletion events.

### Chat status/snippet event contract

- Existing chat payloads remain backward compatible.
- `chat_status` events include normalized fields used by snippet extraction:
	- `status`
	- optional `agent_type`
	- optional `tool_name`
	- `timestamp`
- Snippet rendering derives from this event stream; no separate persistence schema is introduced.

All changes are additive and do not change existing message semantics.

## 4. State Management

### Conversational state (`useChatSession`)

- Keep transient `chatStatus` independent from persisted messages.
- Add transient `delegationSnippets` collection with folded-by-default UI state.
- Keep terminal timeout/failure behavior sticky until next outbound message.

### Non-conversation state (`AgentJobPage` and log dialogs)

- Split state into:
	- Session lifecycle state (queued/running/completed/failed).
	- Live execution-log stream state (connected/reconnecting/fallback).
	- Render-ready log entry list for `LogViewer`.
- Use stream as primary source while running; reconcile with pull endpoint on reconnect and at terminal completion.

No new global store is introduced.

## 5. Data Access Patterns

### Conversational path

- Client receives status/snippet source events via existing chat WebSocket.
- Status/snippet data remains transient in frontend state; persisted conversation turns remain unchanged.

### Non-conversation path

- Primary: live stream endpoint for execution-log append events during active runs.
- Fallback/recovery: existing pull endpoint (`/logs`) for backfill, reconnect recovery, and terminal consistency checks.
- Existing execution prompt log endpoint (`/execution-logs`) remains used for prompt/system-instruction context.

No new database tables are introduced; feature relies on existing execution-log persistence and transport additions only.

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_extract_agent_delegation_target` | function | Parses delegated target slug from `agent____<slug>` tool names | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn_from_context` | method | Emits additive status/tool events used by chat status and snippet rendering | `backend/app/services/agents/runtime_executor.py` |
| `_build_chat_status_event` | function | Normalizes status payload shape sent to chat clients | `backend/app/api/ws/chat.py` |
| `websocket_chat` | function | WebSocket endpoint that sends `chat_status` and agent replies | `backend/app/api/ws/chat.py` |
| `_delegate_conversation_turn_to_agent_runtime` | function | Streams Agent Runtime status events and forwards to chat WebSocket | `backend/app/api/ws/chat.py` |
| `execute_conversation_turn` | function | Agent Runtime API endpoint supporting NDJSON status streaming | `backend/app/agent_runtime/api/conversation.py` |
| `get_session_execution_logs` | function | Pull endpoint for chronological execution log entries | `backend/app/api/v1/agents.py` |
| `get_session_prompt_logs` | function | Pull endpoint for system-instruction/user-prompt capture | `backend/app/api/v1/agents.py` |
| `stream_session_execution_logs` | function | Live NDJSON stream endpoint for non-conversation execution logs with terminal completion marker | `backend/app/api/v1/agents.py` |
| `ChatRole` | type | Existing chat role union used by message rendering | `frontend/src/hooks/useChatSession.ts` |
| `ChatMessage` | interface | Existing chat message model for user/agent/system turns | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatus` | interface | Transient chat status shape for thinking/delegating/waiting/tool/timeout states | `frontend/src/hooks/useChatSession.ts` |
| `DelegationSnippetLine` | interface | Folded-snippet line model derived from delegation-related status/tool events | `frontend/src/hooks/useChatSession.ts` |
| `useChatSession` | hook | WebSocket lifecycle, status parsing, and delegation snippet aggregation | `frontend/src/hooks/useChatSession.ts` |
| `ChatPage` | component | Chat page rendering status indicator and folded delegation snippets | `frontend/src/pages/chat/ChatPage.tsx` |
| `ConversationDialog` | component | In-dialog chat surface rendering status indicator and folded delegation snippets | `frontend/src/components/agents/ConversationDialog.tsx` |
| `useExecutionLogs` | hook | Prompt/system-instruction log fetch for session context | `frontend/src/hooks/useExecutionLogs.ts` |
| `useSessionExecutionLogStream` | hook | Live stream consumer with reconnect and fallback state for non-conversation execution logs | `frontend/src/hooks/useSessionExecutionLogStream.ts` |
| `AgentJobPage` | component | Non-conversation session view that consumes live logs and shows progress | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `AgentExecutionDetailsDialog` | component | Execution details dialog that merges live streamed entries into `LogViewer` | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `SessionExecutionLogsDialog` | component | Execution logs dialog using live stream updates with span-based `LogViewer` rendering | `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx` |
| `LogViewer` | component | Span-based execution log visualization container | `frontend/src/components/executions/LogViewer.tsx` |
| `WorkingStepsPanel` | component | Collapsible hierarchical step visualization for execution spans | `frontend/src/components/executions/WorkingStepsPanel.tsx` |
| `conversations.sessions.*` | i18n keys | Existing conversation UI copy section for chat-related labels | `frontend/src/i18n/locales/en.json` |
| `agents.sessions.logViewer.*` | i18n keys | Existing execution log viewer labels and status copy for session log surfaces | `frontend/src/i18n/locales/en.json` |
