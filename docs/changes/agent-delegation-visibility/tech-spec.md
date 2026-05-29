# Technical Specification: agent-delegation-visibility

## 1. Technical Overview

This adjustment scopes the change to minimal, user-facing chat status signals only:

- Show a thinking animation immediately after the user sends a message and while the conversational agent turn is still running.
- When delegation starts, show text in this exact format: `Delegating to agent <agent_type>`.
- After delegation starts, keep a waiting animation visible until the delegated step returns or the existing timeout path is reached.

Core delegation/runtime behavior remains unchanged. No new services, no orchestration redesign, no database changes, and no new REST endpoints are introduced.

## 2. Component Breakdown

### `runtime_executor` (additive status metadata only)

**File:** `backend/app/services/agents/runtime_executor.py`

- Reuse existing delegation target parsing from tool names (`agent____<slug>` via current parsing helpers).
- Emit lightweight, additive conversation status metadata when a delegation tool call begins.
- Do not alter permission checks, delegation dispatch, wait timeout values, or response composition logic.

### `websocket_chat` and `_process_message` (pass-through status events)

**File:** `backend/app/api/ws/chat.py`

- Keep the current request/response turn flow.
- Add minimal status event messages over the existing WebSocket channel so frontend can render thinking/delegating/waiting feedback during execution.
- Continue sending final agent reply, title update, and guardrail update as currently done.

### `useChatSession` (status event handling)

**File:** `frontend/src/hooks/useChatSession.ts`

- Extend WebSocket message handling with a small status-event branch.
- Track transient chat status state for: thinking, delegating, waiting, timeout/failure end-state.
- Parse delegated target slug from payload and surface it to UI for the required `Delegating to agent <agent_type>` label.

### `ChatPage` (simple status UI)

**File:** `frontend/src/pages/chat/ChatPage.tsx`

- Render a compact status row/bubble in the chat area using existing MUI building blocks.
- Show animation for thinking/waiting states.
- Show delegation label exactly per requirement when delegation status is active.
- Clear transient status when final response arrives or a timeout/failure terminal status is emitted.

### Locale strings (translation keys)

**File:** `frontend/src/i18n/locales/en.json`

- Add keys for thinking/waiting/timeout labels.
- Add delegation label template with agent placeholder.
- Keep all user-facing text under i18n (`t()`).

## 3. API Changes

No REST API changes.

Additive WebSocket event contract update on existing `/ws/sessions/{session_id}` channel:

- Existing chat payloads remain unchanged for backward compatibility.
- Add a small status-event shape used only for transient UI indicators.
- Event types are limited to what UI needs: thinking started, delegation started (with `agent_type`), waiting, and timeout/failure terminal state.

This is additive and does not change existing message semantics.

## 4. State Management

`useChatSession` adds a minimal transient status object independent from persisted chat history messages.

- Status is set to thinking on outbound send.
- Status transitions to delegation/waiting when matching WebSocket status events arrive.
- Status is cleared on final agent response or on terminal timeout/failure display completion.

`ChatPage` reads this status and conditionally renders one lightweight indicator block. No new global store is introduced.

## 5. Data Access Patterns

No new data-access pattern is introduced.

- No database reads/writes are added for this feature.
- Existing runtime delegation detection (tool name parsing) is reused only to produce additive UI status metadata.
- Frontend consumes transient status events from existing WebSocket connection only.

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_extract_agent_delegation_target` | function | Parses delegated target slug from `agent____<slug>` tool names | `backend/app/services/agents/runtime_executor.py` |
| `_canonicalize_tool_name_for_log` | function | Existing canonical tool-name normalization used around tool-call handling | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn` | method | Conversation-turn execution path where delegation tool calls are dispatched | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn_from_context` | method | Context-based conversation execution path with delegation handling | `backend/app/services/agents/runtime_executor.py` |
| `websocket_chat` | function | Existing WebSocket endpoint; emits chat/status updates to client | `backend/app/api/ws/chat.py` |
| `_process_message` | function | Processes one user message and returns reply plus metadata | `backend/app/api/ws/chat.py` |
| `_call_llm` | function | Delegates conversation turn execution to Agent Runtime | `backend/app/api/ws/chat.py` |
| `ChatRole` | type | Existing chat role union used by message rendering | `frontend/src/hooks/useChatSession.ts` |
| `ChatMessage` | interface | Existing chat message model for user/agent/system turns | `frontend/src/hooks/useChatSession.ts` |
| `useChatSession` | hook | WebSocket lifecycle + inbound event parsing + transient status state | `frontend/src/hooks/useChatSession.ts` |
| `ChatPage` | component | Chat UI surface that renders message list and transient status indicator | `frontend/src/pages/chat/ChatPage.tsx` |
| `conversations.sessions.*` | i18n keys | Existing conversation UI copy section for chat-related labels | `frontend/src/i18n/locales/en.json` |
