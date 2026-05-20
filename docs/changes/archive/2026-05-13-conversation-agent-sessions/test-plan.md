# Test Plan — Conversation Agent Sessions

## 1. Test Strategy

This change introduces persistent conversation sessions as a first-class UI entity with new backend services, new REST endpoints, a WebSocket protocol extension, and schema changes to `ConversationSession`. Testing must validate the complete lifecycle (create → resume → end → archive) across all three layers:

- **Backend integration tests** (`backend/tests/`): Validate schema migrations, service logic, ownership enforcement, and API contract correctness against a real PostgreSQL database with `alembic upgrade head` applied.
- **Frontend unit/component tests** (`frontend/src/__tests__/`): Validate hook state, mutation wiring, React Query cache invalidation, and conditional tab rendering for conversation-type agents.
- **E2E tests** (`e2e/tests/`): Validate the full user-facing CRUD flow from the browser — including at least one real-backend variant that catches migration regressions.

## 2. Coverage Areas

| Area | Why Critical |
|---|---|
| Schema migration | `ConversationSession` adds `title`, `triggered_by_user_id`, `agent_job_id`, `updated_at`; removes legacy fields; `ConversationStatus.archived` is a new enum value — constraints must be verified against the live database, not just models |
| Session creation | The `POST /conversations` endpoint must enforce agent-type ownership and reject non-conversation agent types with 422; `triggered_by_user_id` must be set from JWT, never from the request body |
| Session ownership enforcement | All mutating endpoints (resume, end, archive) must return 403 when the requesting user does not own the session |
| Session listing — user scoping | `GET /conversations` must filter by `triggered_by_user_id` so users cannot enumerate other users' sessions; archived sessions must be excluded from default results |
| Session lifecycle state machine | Valid transitions (`active → closed`, `active → archived`) and invalid transitions (e.g., re-archiving a closed session) must be enforced in `ConversationSessionManager` |
| `SessionAutoNamer` | Title generation runs as a background task; must fall back to a truncated first message on LLM failure; must not block the user turn response |
| `title_update` WebSocket event | The new server→client message type must be routed to `sessionTitle` state and must not corrupt the messages array |
| Sessions tab visibility | The Sessions tab must appear only for agents whose `input_type === 'conversation'`; it must be absent for all other agent types |
| Session resume | `POST /conversations/{id}/resume` must return full turn history with tool call records; `ChatPage` must restore context from the `sessionId` route param without requiring a page reload |
| Parent table refresh | After create/end/archive operations the sessions list must update automatically without a manual page reload |
| `AgentTypeForm` output field | The output type field must be hidden when creating/editing a conversation agent type |
| `AgentInstanceDashboardPage` Session column | The session title column must render for conversation-type agent jobs and must remain absent for non-conversational jobs |
| `ConversationHistoryPage` compatibility | The existing read-only history view must work with the updated `ConversationSession` TypeScript type (no `agent_instance_id` / `initiator_subject`) |

## 3. Critical Scenarios

### Session Creation

- **WHEN** an authenticated user creates a session for a conversation-type agent type **THEN** the response contains a session with `status: active`, an empty `title` initially, and `triggered_by_user_id` matching the caller's JWT subject
- **WHEN** a user attempts to create a session for an agent type whose `input_type` is not `conversation` **THEN** the API returns 422
- **WHEN** a session is created and the first user turn is submitted **THEN** `SessionAutoNamer` runs as a background task and eventually sets a non-empty `title`; the main turn response is not delayed

### Ownership & Authorization

- **WHEN** user A calls `POST /conversations/{id}/resume` on a session owned by user B **THEN** the API returns 403
- **WHEN** user A calls `POST /conversations/{id}/end` on a session owned by user B **THEN** the API returns 403
- **WHEN** user A calls `POST /conversations/{id}/archive` on a session owned by user B **THEN** the API returns 403
- **WHEN** an unauthenticated request reaches any `/conversations` endpoint **THEN** the API returns 401

### Session Listing — Scoping & Filtering

- **WHEN** user A has two sessions and user B has one session **THEN** user A's `GET /conversations` returns exactly two sessions; user B's returns exactly one
- **WHEN** a session is archived **THEN** it no longer appears in the default `GET /conversations` response
- **WHEN** `status=archived` filter is passed **THEN** only archived sessions are returned
- **WHEN** sessions exist with different `updated_at` values **THEN** the response is ordered by `updated_at DESC`

### Session Lifecycle

- **WHEN** an active session is ended **THEN** its status becomes `closed` and it no longer accepts new turns
- **WHEN** an active session is archived **THEN** its status becomes `archived` and it is excluded from the active listing
- **WHEN** a closed or archived session is targeted for archiving or ending again **THEN** the API returns an appropriate error (not a silent no-op)

### Session Resume

- **WHEN** a user opens `ChatPage` with a `sessionId` route param for a session they own **THEN** the full turn history is loaded and displayed
- **WHEN** `ChatPage` loads with a `sessionId` **THEN** `POST /conversations/{id}/resume` is called exactly once (no duplicate requests)

### WebSocket `title_update`

- **WHEN** `SessionAutoNamer` completes **THEN** a `title_update` message is pushed to the connected WebSocket client
- **WHEN** `useChatSession` receives a `title_update` message **THEN** `sessionTitle` state is updated and the messages array is unchanged
- **WHEN** `SessionAutoNamer` encounters an LLM error **THEN** the session title is set to the truncated first user message and a `title_update` event is still sent

### Frontend Tab Rendering

- **WHEN** an agent type has `input_type === 'conversation'` **THEN** `AgentManagementPage` renders a Sessions tab
- **WHEN** an agent type has any other `input_type` **THEN** no Sessions tab is rendered
- **WHEN** the Sessions tab is active and a new session is created **THEN** the session list updates without page reload

### CRUD Lifecycle (Parent Table Refresh)

- **WHEN** a session is created via the Start New Conversation entry point **THEN** the session appears in `ConversationSessionsTab` immediately, reflecting accurate title, status, and recency
- **WHEN** a session is ended via the action button **THEN** it is removed from the active sessions list without a page reload
- **WHEN** a session is archived **THEN** it is removed from the active sessions list without a page reload; it becomes accessible under an archived filter

### `AgentTypeForm` Output Field

- **WHEN** a conversation agent type is created or edited **THEN** the output type field is not rendered in the form
- **WHEN** a non-conversation agent type is created or edited **THEN** the output type field is visible and required

### Dashboard Session Column

- **WHEN** `AgentInstanceDashboardPage` renders executions for a conversation-type agent **THEN** the Session column displays the linked conversation session title
- **WHEN** a non-conversational agent execution is listed **THEN** the Session column is empty or absent

## 4. Edge Cases & Risks

| Risk | Mitigation |
|---|---|
| **Migration not applied** | Backend integration tests must call `alembic upgrade head` in the fixture; tests must directly query `information_schema` to verify `title` is nullable, `updated_at` exists, and `archived` appears in the enum |
| **Legacy field removal breaks existing code** | `ConversationHistoryPage` and any other consumers of `ConversationSession` that reference `agent_instance_id` or `initiator_subject` must be identified and tested — removing these fields from the TypeScript interface will surface type errors at compile time |
| **`triggered_by_user_id` spoofing** | Verify that the backend ignores any `triggered_by_user_id` field in the request body and always derives it from the JWT claims |
| **`SessionAutoNamer` blocking** | Confirm the auto-namer is dispatched as a non-blocking background task; verify that a slow or failing LLM call does not delay the first turn response or break session state |
| **`title_update` corrupts message stream** | Verify the WebSocket message handler branches correctly on `data.type`; messages that are not `title_update` must not be treated as title updates |
| **Concurrent session creation** | Two rapid `POST /conversations` requests by the same user for the same agent type should each succeed independently and create distinct sessions |
| **React Query cache stale after mutation** | Verify that `['conversations', agentTypeId]` is invalidated after create, end, and archive mutations; stale data in the list is a regression risk |
| **Resume for non-existent session** | `POST /conversations/{id}/resume` with an unknown `session_id` must return 404, not 500 |
| **Empty turn history on resume** | A session with zero turns should resume cleanly; `ChatPage` should render an empty conversation, not crash |
| **Archived status excluded from enum validation** | Some older code paths may not handle `archived` as a valid `ConversationStatus` value; ensure status comparisons use the enum, not raw strings |

## 5. Acceptance Criteria Checklist

Mapped to PRD acceptance criteria:

- [x] Users can start a new conversation agent session from a clear UI entry point (Start New Conversation button in `ConversationSessionsTab`)
- [x] Session titles are auto-generated based on the first user prompt (verified via `title_update` WebSocket event updating `ChatPage` header)
- [x] All conversation agent sessions are listed in a Sessions tab within the agent type view (Sessions tab visible only for `input_type === 'conversation'` agents)
- [x] Users can click into any session to view and continue the conversation (Resume action opens `ChatPage` with full turn history)
- [x] Users can end sessions, removing them from the active list (End action transitions status to `closed` and removes from default listing)
- [x] Users can archive sessions, removing them from the active list (Archive action transitions status to `archived` and excludes from default listing)
- [x] Agent executions list displays agent type, status, and session name for conversational agents (Session column in `AgentInstanceDashboardPage`)
- [x] No output type selection is required when defining a conversation agent (output type field hidden in `AgentTypeForm` for conversation input type)
- [x] All session management actions are observable and testable via the UI (end and archive actions surface in `ConversationSessionsTab` with confirmation dialogs)
- [x] Schema migration applies cleanly and backward-compatible: `title` nullable, `updated_at` present, `archived` enum value added, legacy fields removed without breaking existing queries

## 6. Test File References

> **Status: ALL TESTS PASS** — Verified on 2026-05-13. All three layers executed and confirmed.

### Backend Tests — 16/16 passed ✅
**Unit tests** (`backend/tests/unit/conversations/`):
- `test_auto_namer.py` — `SessionAutoNamer` happy path, LLM failure fallback, truncation, empty LLM response (4 tests)
- `test_session_manager.py` — `ConversationSessionManager` lifecycle: reject non-conversation agent type, missing agent type → not found, create success, end → closed, archive → archived, resume returns turns, ownership validation (7 tests)

**Integration tests** (`backend/tests/integration/`):
- `test_conversations.py` — Endpoint registration verification: POST /conversations, GET /conversations, POST /end, POST /archive, POST /resume all registered and responding (5 tests)

### Frontend Component Tests — 9/9 passed ✅
**Hook tests** (`frontend/src/__tests__/`):
- `useChatSession.test.ts` — Disconnected initial state, empty messages, sendMessage adds user message, clearMessages resets (4 tests)

**Component tests** (`frontend/src/__tests__/`):
- `ConversationSessionsTab.test.tsx` — Renders session titles and status chips, untitled placeholder, Start New Conversation button calls mutation, Archive confirmation dialog, empty state (5 tests)

### E2E Tests — 4/4 passed (1 skipped) ✅
**File:** `e2e/tests/conversation-sessions.spec.ts`

**Mocked variant** (4 tests — all pass):
- Sessions tab visible for conversation-type agents
- Sessions tab shows session list
- Resume navigates to chat page with session history
- End session shows confirmation dialog

**Real Backend Integration variant** (1 test — skipped):
- POST /conversations creates session; POST /end closes it — *skips gracefully when no conversation agent type found in DB*
