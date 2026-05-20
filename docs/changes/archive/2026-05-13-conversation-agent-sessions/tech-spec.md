# Technical Specification — Conversation Agent Sessions

## 1. Technical Overview

The change promotes `ConversationSession` from an internal execution record to the primary user-facing entity for conversational agent interactions. Two new backend services are introduced — `ConversationSessionManager` (lifecycle orchestration) and `SessionAutoNamer` (async LLM-driven title generation) — alongside extended REST endpoints and WebSocket push events. The frontend gains a dedicated Sessions tab on conversation-type agent detail views, a live-updating chat header, and mutations for ending and archiving sessions.

## 2. Component Breakdown

| Component | Responsibility |
|---|---|
| **`ConversationSession` model** | Persistent record for a bounded user–agent conversation; updated to carry `title`, `triggered_by_user_id` FK, `agent_job_id` FK, `updated_at`; `archived` lifecycle state added to `ConversationStatus` enum. |
| **`ConversationStore`** | Data-access layer; all reads and writes against `ConversationSession`, `ConversationTurn`, and `ToolCallRecord`; extended with user-scoped listing, `update_title`, and `archive_session` methods. |
| **`ConversationSessionManager`** | Service layer owning lifecycle transitions: create, resume, end, archive; validates session ownership against the authenticated user; raises `PermissionError` on mismatch. |
| **`SessionAutoNamer`** | Triggered as a background task after the first user turn is stored; builds a title-generation prompt; calls the agent type's configured LLM; writes the result via `ConversationStore.update_title`; pushes a `title_update` WebSocket event to the active client; falls back to a truncated first message on LLM failure. |
| **`ConversationRouter`** | FastAPI router at `/conversations`; extended with `POST /` (create), `POST /{id}/resume`, `POST /{id}/end`, `POST /{id}/archive`; existing `GET /` updated to filter by user and sort by `updated_at`. |
| **`AgentSessionService`** | WebSocket session handler; updated to associate `session_id` on connect and to dispatch `SessionAutoNamer` as a background task after the first message; pushes `title_update` JSON to the client. |
| **`useConversationSessions` hook** | Frontend data hook; encapsulates `GET /conversations` query and create/end/archive mutations; manages React Query cache invalidation. |
| **`useChatSession` hook** | Frontend WebSocket hook; extended to handle `title_update` message type; exports `sessionTitle` state for display in `ChatPage`. |
| **`ConversationSessionsTab` component** | Sessions list UI for a given `agentTypeId`; renders title, status, recency, and action buttons (Resume, End, Archive); embeds a "Start New Conversation" entry point. |
| **`ChatPage`** | Real-time chat interface; updated to accept an optional `sessionId` route param for resume mode; calls `POST /conversations/{id}/resume` on load when resuming; displays live session title from `useChatSession`. |
| **`AgentManagementPage`** | Top-level agent management view; opens `AgentTypeDetailsDialog` on agent type selection; unchanged except for delegating session management to the dialog. |
| **`AgentInstanceDashboardPage`** | Global executions dashboard; updated to display a Session column with the linked conversation session title for conversation-type agents. |

## 3. API Changes

### New Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/conversations` | Create a new conversation session for a given agent type. Body: `{ agent_type_id }`. Returns `ConversationSessionRead`. Requires authenticated user; `triggered_by_user_id` is set from JWT claims. Rejects non-conversation agent types with 422. |
| `POST` | `/conversations/{session_id}/resume` | Return the full session context (metadata + all turns with tool call records) for a given session. Validates that the requesting user owns the session; returns 403 on mismatch. Returns `ConversationSessionDetailRead`. |
| `POST` | `/conversations/{session_id}/end` | Transition session status to `closed`. Validates ownership. Returns updated `ConversationSessionRead`. |
| `POST` | `/conversations/{session_id}/archive` | Transition session status to `archived`. Validates ownership. Archived sessions are excluded from the default active listing. Returns updated `ConversationSessionRead`. |

### Modified Endpoints

| Method | Path | Change |
|---|---|---|
| `GET` | `/conversations` | Adds optional `agent_type_id` query parameter for filtering sessions by agent type. Adds optional `triggered_by_user_id` query parameter for user-scoped listing. Adds optional `status` filter. Adds `limit` and `offset` pagination params. Response objects now include `title`, `triggered_by_user_id`, `agent_job_id`, and `updated_at`; `agent_instance_id` and `initiator_subject` are removed from the response schema. Results ordered by `updated_at DESC`. |
| `GET` | `/conversations/{session_id}` | Response schema updated to match new `ConversationSessionDetailRead` (removes `agent_instance_id` / `initiator_subject`; adds `title`, `updated_at`). |

### WebSocket Protocol Change

The WebSocket endpoint at `/sessions/{session_id}` gains a new server-to-client message type:

| Message type | Direction | Payload | Trigger |
|---|---|---|---|
| `title_update` | Server → Client | `{ "type": "title_update", "title": "<string>" }` | Sent once after `SessionAutoNamer` writes the generated title, approximately 1–3 seconds after the first user message is processed. |

Existing message types (`ack`, agent response) are unchanged.

## 4. State Management

### React Query Keys

| Key | Data | Invalidated by |
|---|---|---|
| `['conversations', agentTypeId]` | Session list for a specific agent type | Create, end, archive mutations |
| `['conversations', sessionId]` | Single session detail (turns + metadata) | End, archive mutations |

### Component-Level State

| Component | State added |
|---|---|
| `ChatPage` | `sessionTitle: string \| null` — received via `useChatSession`; updates live via `title_update` WebSocket event |
| `AgentManagementPage` | `activeTab: number` — extended to include the Sessions tab index for conversation agents |
| `ConversationSessionsTab` | `confirmAction: { type: 'end' \| 'archive', sessionId: string } \| null` — controls confirmation dialog visibility |

### `useChatSession` Hook Extensions

The hook adds `sessionTitle: string | null` to its return value. Internally it detects `data.type === 'title_update'` in the `onmessage` handler and calls `setSessionTitle(data.title)` instead of appending to the messages array.

## 5. Data Access Patterns

All data access follows the project convention: the **frontend calls backend REST APIs exclusively**; there is no direct database access from the frontend.

| Operation | Caller | Target | Rationale |
|---|---|---|---|
| Create session | Frontend → `POST /conversations` | `ConversationSessionManager.create` → `ConversationStore` → PostgreSQL | Requires server-side validation of agent type ownership and `input_type` check |
| List sessions | Frontend → `GET /conversations` | `ConversationStore.list_sessions` → PostgreSQL | User-scoped query with `triggered_by_user_id` filter enforced server-side |
| Resume session | Frontend → `POST /conversations/{id}/resume` | `ConversationSessionManager.resume` → `ConversationStore.get_session_with_turns` | Ownership check and full eager-load of turns/tool calls performed server-side |
| End / Archive session | Frontend → `POST /conversations/{id}/end\|archive` | `ConversationSessionManager.end/archive` → `ConversationStore` | Lifecycle state machine enforced in service layer; ownership validated before write |
| Auto-name session | Background task (server-internal) | `SessionAutoNamer` → LLM API → `ConversationStore.update_title` | LLM credentials and model config are server-side secrets; cannot be called from frontend |
| Title push to client | Backend → WebSocket | `AgentSessionService` → `useChatSession` | Real-time push; no polling needed |
| Fetch turn history | Frontend → `POST /conversations/{id}/resume` | Returns embedded turns array | Avoids a second round-trip; history is part of the resume response |

## 6. Code Reference Map

| Symbol | Type | Description | File |
|---|---|---|---|
| `ConversationSession` | model | SQLAlchemy ORM model for a conversation session; modified to add `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at` and remove legacy fields | `backend/app/db/models/conversations.py` |
| `ConversationStatus` | enum | Lifecycle status values (`active`, `closed`, `archived`, `error`); `archived` value added | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | Single message in a conversation session; unchanged | `backend/app/db/models/conversations.py` |
| `ToolCallRecord` | model | Tool invocation record within a turn; unchanged | `backend/app/db/models/conversations.py` |
| `ConversationStore` | service | Data-access class for all conversation persistence; extended with `update_title`, `archive_session`, user-scoped `list_sessions` | `backend/app/services/conversations/store.py` |
| `ConversationSessionManager` | service | New service owning session lifecycle; validates ownership; delegates writes to `ConversationStore` | `backend/app/services/conversations/manager.py` |
| `SessionAutoNamer` | service | New background-task service; generates session title via LLM; writes via `ConversationStore.update_title`; pushes WebSocket event | `backend/app/services/conversations/auto_namer.py` |
| `ConversationSessionCreate` | schema | New Pydantic request schema for `POST /conversations` | `backend/app/schemas/conversations.py` |
| `ConversationSessionRead` | schema | Pydantic response schema; updated to include `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at`; removes legacy fields | `backend/app/schemas/conversations.py` |
| `ConversationSessionDetailRead` | schema | Extends `ConversationSessionRead` with nested `turns`; no structural change beyond inherited field updates | `backend/app/schemas/conversations.py` |
| `ConversationRouter` | router | FastAPI router at `/conversations`; extended with create, resume, end, archive endpoints | `backend/app/api/v1/conversations.py` |
| `AgentSessionService` | service | WebSocket lifecycle handler for agent sessions; extended to dispatch `SessionAutoNamer` and push `title_update` events | `backend/app/services/agents/session_service.py` |
| `AgentLoopContext` | dataclass | Base execution context for agent loops; carries message thread and tool results | `backend/app/services/agents/agent_loop.py` |
| `ConversationalAgentLoop` | dataclass | Execution context for multi-turn conversational agents; no structural changes | `backend/app/services/agents/agent_loop.py` |
| `AgentType` | model | Agent type definition; `input_type` enum already includes `conversation`; no schema changes | `backend/app/db/models/agents.py` |
| `useConversationSessions` | hook | New React Query hook; exposes sessions list, create/end/archive mutations for a given agent type | `frontend/src/hooks/useConversationSessions.ts` |
| `useChatSession` | hook | WebSocket session manager hook; extended with `sessionTitle` state and `title_update` handling | `frontend/src/hooks/useChatSession.ts` |
| `useAgentTypes` | hook | Fetches all agent types; provides `input_type` for tab conditional rendering | `frontend/src/hooks/useAgentTypes.ts` |
| `ConversationSessionsTab` | component | New sessions list UI with start/resume/end/archive actions; embedded in `AgentManagementPage` for conversation agents | `frontend/src/components/agents/ConversationSessionsTab.tsx` |
| `ChatPage` | component | Real-time chat interface; updated to support session creation and resume via route param; displays live `sessionTitle` | `frontend/src/pages/chat/ChatPage.tsx` |
| `AgentManagementPage` | component | Agent type list and detail management; updated to show Sessions tab for conversation-type agents | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentTypeForm` | component | Agent type create/edit form; output type field hidden when `input_type === 'conversation'` | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentInstanceDashboardPage` | component | Global execution dashboard; updated with Session title column for conversation-type agent jobs | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` |
| `ConversationHistoryPage` | component | Existing read-only conversation history view; receives schema updates to `ConversationSession` type | `frontend/src/pages/conversations/ConversationHistoryPage.tsx` |
| `AgentType` | TypeScript interface | Frontend type for agent type; `input_type` already includes `'conversation'`; no structural changes | `frontend/src/types/index.ts` |
| `ConversationSession` | TypeScript interface | Frontend type for session; updated to add `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at`, `channel`, `turn_count`, `closed_at`; remove `agent_instance_id`, `initiator_subject` | `frontend/src/types/index.ts` |
| `ConversationSessionDetail` | TypeScript interface | Extends `ConversationSession` with a `turns: ConversationTurn[]` array; used by `ChatPage` when loading resumed session history | `frontend/src/types/index.ts` |
| `AgentTypeDetailsDialog` | component | Agent type detail dialog; updated to show Sessions tab (index 3) conditionally for conversation-type agents | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AppRouter` | component | React Router 7 route tree; added `/agents/:agentTypeId/chat/:sessionId` route for session resume | `frontend/src/app/AppRouter.tsx` |
| `test_session_manager` | test | Unit tests for `ConversationSessionManager` lifecycle transitions and ownership validation | `backend/tests/unit/conversations/test_session_manager.py` |
| `test_auto_namer` | test | Unit tests for `SessionAutoNamer` title generation, LLM fallback, and truncation | `backend/tests/unit/conversations/test_auto_namer.py` |
| `test_conversations` | test | Integration tests for conversation REST endpoints (create, end, archive, resume) | `backend/tests/integration/test_conversations.py` |
| `ConversationSessionsTab.test` | test | Frontend component tests for session list, start/archive actions, and empty state | `frontend/src/__tests__/ConversationSessionsTab.test.tsx` |
| `conversation-sessions.spec` | test | E2E tests (mocked + real backend) for full session lifecycle | `e2e/tests/conversation-sessions.spec.ts` |
