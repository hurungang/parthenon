# Module: conversations — Tech Spec

## Overview

The conversations module provides complete and durable persistence of every interaction that passes through the platform. Each conversation session groups a bounded set of turns; each turn captures a single message from a participant (user, agent, system, or tool); each tool call within a turn is separately recorded. This three-level structure ensures full audit trails and supports session replay for debugging and compliance purposes.

For **conversation-type agents**, the module provides persistent, user-named sessions with automatic title generation, session lifecycle management (active → closed → archived), and full turn history preservation. Users can start, resume, end, and archive conversation sessions through a dedicated Sessions tab in the agent type view.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `ConversationStore` | Service class that writes conversation sessions, turns, and tool call records synchronously during agent execution; extended with `update_title`, `archive_session`, and user-scoped `list_sessions` methods |
| `ConversationSessionManager` | New service owning session lifecycle; validates ownership; delegates writes to ConversationStore; enforces state transitions (active → closed / archived) |
| `SessionAutoNamer` | New background-task service; generates session title via LLM; writes via ConversationStore.update_title; pushes WebSocket event; falls back to truncated first message on LLM failure |
| `ConversationRouter` | FastAPI router exposing filtered listing of conversation sessions and detailed retrieval of a single session with all its turns and embedded tool call records; extended with create, resume, end, and archive endpoints |
| `ConversationSession` | SQLAlchemy model for a bounded interaction context; modified to add `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at`; promoted `agent_type_id` to FK; removed legacy `agent_instance_id` and `initiator_subject` fields |
| `ConversationStatus` | Lifecycle status enum (active, closed, archived, error); `archived` value added |
| `ConversationTurn` | SQLAlchemy model for a single message within a session; stores the role (user/agent/system/tool), content, timestamp, and sequence number |
| `ToolCallRecord` | SQLAlchemy model recording a tool invocation that occurred within a specific turn; stores the tool name, input arguments, result, and timing |
| `AgentSessionService` | WebSocket lifecycle handler for agent sessions; extended to dispatch SessionAutoNamer and push `title_update` events |

### Frontend

| Component | Description |
|-----------|-------------|
| `ConversationHistoryPage` | Session list with date range and agent type filters; expands to a turn-by-turn conversation viewer with tool call detail inline |
| `ConversationSessionsTab` | New sessions list UI with start/resume/end/archive actions; embedded in AgentManagementPage for conversation agents; displays session title, status, and last active time |
| `ChatPage` | Real-time chat interface; updated to support session creation and resume via route param; displays live `sessionTitle` received from WebSocket `title_update` event |
| `useConversationSessions` | New React Query hook; exposes sessions list, create/end/archive mutations for a given agent type |
| `useChatSession` | WebSocket session manager hook; handles `sessionTitle`, additive `chat_status` events, and folded delegation snippets |
| `ConversationDialog` | Embedded conversation surface used in agent execution flows; renders compact status and folded delegation snippets |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/conversations` | List conversation sessions (filterable by agent type, user, status, date); supports pagination; ordered by `updated_at DESC` |
| `GET` | `/api/v1/conversations/{session_id}` | Get a session with all turns and embedded tool call records |
| `POST` | `/api/v1/conversations` | Create a new conversation session for a given agent type; requires authenticated user; sets `triggered_by_user_id` from JWT |
| `POST` | `/api/v1/conversations/{session_id}/resume` | Return full session context (metadata + all turns with tool call records); validates session ownership |
| `POST` | `/api/v1/conversations/{session_id}/end` | Transition session status to `closed`; validates ownership |
| `POST` | `/api/v1/conversations/{session_id}/archive` | Transition session status to `archived`; validates ownership |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationSession` | model | SQLAlchemy ORM model for a conversation session; modified to add `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at` and remove legacy fields | `backend/app/db/models/conversations.py` |
| `ConversationStatus` | enum | Lifecycle status values (active, closed, archived, error); `archived` value added | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | Single message in a conversation session; unchanged | `backend/app/db/models/conversations.py` |
| `ToolCallRecord` | model | Tool invocation record within a turn; unchanged | `backend/app/db/models/conversations.py` |
| `ConversationStore` | service | Data-access class for all conversation persistence; extended with `update_title`, `archive_session`, user-scoped `list_sessions` | `backend/app/services/conversations/store.py` |
| `ConversationSessionManager` | service | New service owning session lifecycle; validates ownership; delegates writes to ConversationStore | `backend/app/services/conversations/manager.py` |
| `SessionAutoNamer` | service | New background-task service; generates session title via LLM; writes via ConversationStore.update_title; pushes WebSocket event | `backend/app/services/conversations/auto_namer.py` |
| `ConversationSessionCreate` | schema | New Pydantic request schema for POST /conversations | `backend/app/schemas/conversations.py` |
| `ConversationSessionRead` | schema | Pydantic response schema; updated to include `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at`; removes legacy fields | `backend/app/schemas/conversations.py` |
| `ConversationSessionDetailRead` | schema | Extends ConversationSessionRead with nested `turns`; no structural change beyond inherited field updates | `backend/app/schemas/conversations.py` |
| `ConversationRouter` | router | FastAPI router at /conversations; extended with create, resume, end, archive endpoints; guarded by `require_permission(RT_CONVERSATION, "read")` | `backend/app/api/v1/conversations.py` |
| `AgentSessionService` | service | WebSocket lifecycle handler for agent sessions; extended to dispatch SessionAutoNamer and push `title_update` events | `backend/app/services/agents/session_service.py` |
| `useConversationSessions` | hook | New React Query hook; exposes sessions list, create/end/archive mutations for a given agent type | `frontend/src/hooks/useConversationSessions.ts` |
| `ChatRole` | TypeScript type | Role union used for chat turn rendering in conversation surfaces | `frontend/src/hooks/useChatSession.ts` |
| `ChatMessage` | TypeScript interface | Conversation message model for user/agent/system turns | `frontend/src/hooks/useChatSession.ts` |
| `ChatStatus` | TypeScript interface | Transient status model for thinking/delegating/waiting/tool-use/timeout states | `frontend/src/hooks/useChatSession.ts` |
| `DelegationSnippetLine` | TypeScript interface | Folded snippet line model derived from delegation-related status/tool events | `frontend/src/hooks/useChatSession.ts` |
| `useChatSession` | hook | WebSocket session manager hook; handles `sessionTitle`, additive status parsing, and delegation snippet aggregation | `frontend/src/hooks/useChatSession.ts` |
| `ConversationSessionsTab` | component | New sessions list UI with start/resume/end/archive actions; embedded in AgentManagementPage for conversation agents | `frontend/src/components/agents/ConversationSessionsTab.tsx` |
| `ConversationDialog` | component | Conversation dialog surface with compact status indicator and folded delegation snippet panel | `frontend/src/components/agents/ConversationDialog.tsx` |
| `ChatPage` | component | Real-time chat interface; updated to support session creation and resume via route param; displays live `sessionTitle` | `frontend/src/pages/chat/ChatPage.tsx` |
| `AgentManagementPage` | component | Agent type list and detail management; updated to show Sessions tab for conversation-type agents | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentTypeDetailsDialog` | component | Agent type detail dialog; updated to show Sessions tab (index 3) conditionally for conversation-type agents | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentInstanceDashboardPage` | component | Global execution dashboard; updated with Session title column for conversation-type agent jobs | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` |
| `ConversationHistoryPage` | component | Existing read-only conversation history view; receives schema updates to ConversationSession type | `frontend/src/pages/conversations/ConversationHistoryPage.tsx` |
| `ConversationSession` | TypeScript interface | Frontend type for session; updated to add `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at`, `channel`, `turn_count`, `closed_at`; remove `agent_instance_id`, `initiator_subject` | `frontend/src/types/index.ts` |
| `ConversationSessionDetail` | TypeScript interface | Extends ConversationSession with a `turns: ConversationTurn[]` array; used by ChatPage when loading resumed session history | `frontend/src/types/index.ts` |
| `conversations.sessions.*` | i18n namespace | Conversation session labels, live status strings, and delegation snippet panel copy | `frontend/src/i18n/locales/en.json` |
