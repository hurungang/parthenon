# Implementation Plan — Conversation Agent Sessions

## Overview

This change promotes `ConversationSession` to a first-class, user-facing entity with persistent titles, lifecycle management (active → ended → archived), and a dedicated Sessions tab inside each conversation agent type's detail view. Implementation spans data model migration, two new backend services (Conversation Session Manager and Session Auto-Namer), extended REST/WebSocket APIs, and coordinated frontend UI additions.

## Task Checklist

### Phase 1 — Data Model & Migration

- [x] 1.1 — Update `ConversationSession` SQLAlchemy model
- [x] 1.2 — Add `archived` value to `ConversationStatus` enum
- [x] 1.3 — Generate Alembic migration via autogenerate
- [x] 1.4 — Apply and verify migration locally

### Phase 2 — Backend Services

- [x] 2.1 — Extend `ConversationStore` with user-scoped query and lifecycle methods
- [x] 2.2 — Create `ConversationSessionManager` service
- [x] 2.3 — Create `SessionAutoNamer` service

### Phase 3 — Backend API

- [x] 3.1 — Update Pydantic schemas in `conversations.py`
- [x] 3.2 — Add session management endpoints to `ConversationRouter`
- [x] 3.3 — Wire `session_id` into WebSocket connection and push title-update events

### Phase 4 — Frontend Types & Data Layer

- [x] 4.1 — Extend TypeScript types for updated `ConversationSession`
- [x] 4.2 — Extend `useChatSession` to handle title-update WebSocket messages
- [x] 4.3 — Add `useConversationSessions` data hook

### Phase 5 — Frontend UI Components

- [x] 5.1 — Create `ConversationSessionsTab` component
- [x] 5.2 — Add Sessions tab to `AgentTypeDetailsDialog` for conversation agents
- [x] 5.3 — Update `ChatPage` to create a session and support resume flow
- [x] 5.4 — Add end/archive session actions to session list items
- [x] 5.5 — Update `AgentInstanceDashboardPage` to show session title for conversation agents

### Phase 6 — Navigation & i18n

- [x] 6.1 — Add routes for session list and chat resume
- [x] 6.2 — Add i18n keys for all new UI text

### Phase 7 — Tests

- [x] 7.1 — Backend unit tests: `ConversationSessionManager` lifecycle transitions
- [x] 7.2 — Backend unit tests: `SessionAutoNamer` title generation and write-back
- [x] 7.3 — Backend integration tests: new REST endpoints
- [x] 7.4 — Frontend component tests: `ConversationSessionsTab` list and actions
- [x] 7.5 — E2E test: start, view, resume, and end a conversation session

---

## Phase 1 — Data Model & Migration

### 1.1 — Update `ConversationSession` SQLAlchemy model

Modify `backend/app/db/models/conversations.py`:

- Add `title: Mapped[str | None]` (nullable string, auto-set by `SessionAutoNamer`)
- Add `triggered_by_user_id: Mapped[uuid.UUID | None]` with `ForeignKey("identities.id", ondelete="SET NULL")`
- Add `agent_job_id: Mapped[uuid.UUID | None]` with `ForeignKey("agent_jobs.id", ondelete="SET NULL")`
- Add `updated_at: Mapped[datetime]` with `onupdate=func.now()` for recency sorting
- Promote `agent_type_id` column to a proper `ForeignKey("agent_types.id", ondelete="SET NULL")`
- Remove `agent_instance_id` column and its FK
- Remove `initiator_subject` column

**Done when:** The model file contains all new mapped columns with correct FK references, and removed columns are absent.

### 1.2 — Add `archived` value to `ConversationStatus` enum

In `backend/app/db/models/conversations.py`, add `archived = "archived"` to the `ConversationStatus` enum.

**Done when:** `ConversationStatus.archived` is importable and the enum has four values: `active`, `closed`, `archived`, `error`.

### 1.3 — Generate Alembic migration via autogenerate

Run `alembic revision --autogenerate -m "promote_conversation_session"` and review the generated migration for correctness (correct ADD COLUMN, DROP COLUMN, FK creation, enum value addition).

**Done when:** A new file exists under `backend/alembic/versions/` with all expected DDL changes and no unexpected extra changes.

### 1.4 — Apply and verify migration locally

Run `alembic upgrade head` against the local development database. Query `information_schema.columns` to confirm new columns exist and removed columns are absent.

**Done when:** `alembic current` shows the new revision; all new columns are present and removed columns are gone in the database.

---

## Phase 2 — Backend Services

### 2.1 — Extend `ConversationStore` with user-scoped query and lifecycle methods

Modify `backend/app/services/conversations/store.py`:

- Update `create_session` to accept `triggered_by_user_id` and set `updated_at`
- Add `update_title(session_id, title, db)` method that sets `title` and touches `updated_at`
- Add `archive_session(session_id, db)` method that transitions status to `archived`
- Update `list_sessions` to accept `triggered_by_user_id` filter and order by `updated_at DESC`
- Update `close_session` to also set `updated_at`

**Done when:** All new methods are present in `ConversationStore`; existing methods retain their signatures; no raw SQL used.

### 2.2 — Create `ConversationSessionManager` service

Create `backend/app/services/conversations/manager.py` with class `ConversationSessionManager`:

- `create(agent_type_id, triggered_by_user_id, db)` — validates agent type exists and has `input_type=conversation`; calls `ConversationStore.create_session`; returns the new `ConversationSession`
- `resume(session_id, requesting_user_id, db)` — validates session ownership; fetches full history via `ConversationStore.get_session_with_turns`; returns session with turns
- `end(session_id, requesting_user_id, db)` — validates ownership; delegates to `ConversationStore.close_session`
- `archive(session_id, requesting_user_id, db)` — validates ownership; delegates to `ConversationStore.archive_session`

Ownership validation raises `PermissionError` if `triggered_by_user_id` does not match `requesting_user_id`.

**Done when:** All four methods are implemented; ownership checks are in place; service is importable from `app.services.conversations`.

### 2.3 — Create `SessionAutoNamer` service

Create `backend/app/services/conversations/auto_namer.py` with class `SessionAutoNamer`:

- `generate_and_save(session_id, first_user_message, agent_type_id, db)` — constructs a concise title-generation prompt; resolves the model config via the agent type's `model_id`; calls the LLM synchronously (or via `asyncio`); writes the result via `ConversationStore.update_title`; returns the generated title string
- Handles LLM errors gracefully: falls back to a truncated first message if title generation fails, and logs the error without raising
- Is designed to be called as a background task after the first user message is stored

**Done when:** `SessionAutoNamer.generate_and_save` produces a non-empty title, writes it to the database, and returns it; LLM failure results in a fallback title rather than an exception.

---

## Phase 3 — Backend API

### 3.1 — Update Pydantic schemas in `conversations.py`

Modify `backend/app/schemas/conversations.py`:

- Add `ConversationSessionCreate` schema with `agent_type_id: uuid.UUID`
- Update `ConversationSessionRead` to include `title: str | None`, `triggered_by_user_id: uuid.UUID | None`, `agent_job_id: uuid.UUID | None`, `updated_at: datetime`; remove `agent_instance_id` and `initiator_subject`
- Ensure `ConversationStatus.archived` is represented in the read schema

**Done when:** All new fields appear in `ConversationSessionRead`; removed fields are absent; schema validates from ORM attributes.

### 3.2 — Add session management endpoints to `ConversationRouter`

Modify `backend/app/api/v1/conversations.py`:

- `POST /conversations` — calls `ConversationSessionManager.create`; returns `ConversationSessionRead`; requires authenticated user
- `POST /conversations/{session_id}/resume` — calls `ConversationSessionManager.resume`; returns `ConversationSessionDetailRead`
- `POST /conversations/{session_id}/end` — calls `ConversationSessionManager.end`; returns `ConversationSessionRead`
- `POST /conversations/{session_id}/archive` — calls `ConversationSessionManager.archive`; returns `ConversationSessionRead`
- Update `GET /conversations` to accept `agent_type_id` and `triggered_by_user_id` query parameters for filtering; also accept `status`, `limit`, and `offset`; sort by `updated_at DESC`

All mutating endpoints extract the requesting user's identity from `request.state.identity` and pass it to the manager for ownership validation. Ownership violations return `403 Forbidden`.

**Done when:** All five endpoint paths exist; Swagger/OpenAPI reflects updated request/response shapes; ownership errors produce 403 responses.

### 3.3 — Wire `session_id` into WebSocket and push title-update events

Modify the WebSocket handler in `backend/app/services/agents/session_service.py` (or the relevant gateway handler):

- On WebSocket connection, associate the incoming `session_id` with the open connection
- After the first user message is stored, dispatch `SessionAutoNamer.generate_and_save` as a background task (`asyncio.create_task` or `BackgroundTasks`)
- When the title is generated, push a `{"type": "title_update", "title": "<generated title>"}` JSON message to the active WebSocket client

**Done when:** A first message in a new session triggers auto-naming in the background; the WebSocket client receives a `title_update` event after the name is written; existing message echo behaviour is unchanged.

---

## Phase 4 — Frontend Types & Data Layer

### 4.1 — Extend TypeScript types for updated `ConversationSession`

Modify `frontend/src/types/index.ts`:

- Add `title: string | null`, `triggered_by_user_id: string | null`, `agent_job_id: string | null`, `updated_at: string` to the `ConversationSession` interface
- Add `'archived'` to the `ConversationStatus` union type
- Remove `agent_instance_id` and `initiator_subject` from the interface
- Add `ConversationSessionCreate` interface with `agent_type_id: string`

**Done when:** No TypeScript errors in files that use `ConversationSession`; `ConversationStatus` includes `'archived'`.

### 4.2 — Extend `useChatSession` to handle title-update WebSocket messages

Modify `frontend/src/hooks/useChatSession.ts`:

- Add `sessionTitle: string | null` to the hook's returned state
- In the `ws.onmessage` handler, detect `type === 'title_update'` and update `sessionTitle` state
- Export `sessionTitle` from the hook return value

**Done when:** The hook returns `sessionTitle`; receiving a `title_update` WebSocket message updates the value without adding it to the `messages` array.

### 4.3 — Add `useConversationSessions` data hook

Create `frontend/src/hooks/useConversationSessions.ts` with:

- `useConversationSessions(agentTypeId: string)` — queries `GET /conversations?agent_type_id=<id>` and returns session list sorted by `updated_at`
- `useEndConversationSession()` — mutation calling `POST /conversations/{id}/end`; invalidates the sessions query
- `useArchiveConversationSession()` — mutation calling `POST /conversations/{id}/archive`; invalidates the sessions query
- `useCreateConversationSession()` — mutation calling `POST /conversations`; invalidates the sessions query and navigates to the new session

**Done when:** Hook file exists; all four exports compile without errors; each mutation correctly invalidates the relevant React Query cache key.

---

## Phase 5 — Frontend UI Components

### 5.1 — Create `ConversationSessionsTab` component

Create `frontend/src/components/agents/ConversationSessionsTab.tsx`:

- Accepts `agentTypeId: string` as prop
- Renders a list of sessions fetched via `useConversationSessions`
- Each row shows: auto-generated title (or a placeholder if null), status chip, `updated_at` timestamp, and action buttons (Resume, End, Archive)
- "Start New Conversation" button calls `useCreateConversationSession` and navigates to `ChatPage` with the new session
- End and Archive actions show a confirmation dialog (using `useDialogErrorHandler` pattern) before calling the mutation

**Done when:** Component renders without errors for an empty list; all three action buttons call their respective mutations; no hardcoded UI strings (all use `t()`).

### 5.2 — Add Sessions tab to `AgentTypeDetailsDialog` for conversation agents

Modify `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`:

- When an `AgentType` has `input_type === 'conversation'`, render a "Sessions" tab (index 3) alongside existing tabs
- Embed `ConversationSessionsTab` as the tab content, passing `agentTypeId`

**Done when:** The Sessions tab is visible only for conversation-type agents; non-conversation agents are unaffected; tab selection does not break existing routing.

### 5.3 — Update `ChatPage` to create a session and support resume flow

Modify `frontend/src/pages/chat/ChatPage.tsx`:

- Accept an optional `sessionId` route param in addition to `agentTypeId`
- If `sessionId` is provided, call `POST /conversations/{id}/resume` to load history and connect the WebSocket with the existing session
- If starting fresh, call `POST /conversations` to create a session, then connect WebSocket
- Display the `sessionTitle` from `useChatSession` in the page header (updating live as the auto-name arrives)

**Done when:** Navigating to the chat route with an existing `sessionId` loads prior message history; new sessions receive and display an auto-generated title without a page refresh.

### 5.4 — Add end/archive session actions to session list items

This is covered by the `ConversationSessionsTab` component in 5.1. No separate component is needed. Confirm action dialogs use `useDialogErrorHandler` per the project's Dialog Error Handling Standard.

**Done when:** End and Archive confirmation dialogs appear before executing the mutation; errors from the API are shown inline in the dialog.

### 5.5 — Update `AgentInstanceDashboardPage` to show session title for conversation agents

Modify `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx`:

- Add a "Session" column to the sessions table
- For rows where the backing `AgentJob` is linked to a `ConversationSession`, display the session title (or em-dash if not yet named)
- Column is only populated for conversation-type agents (resolved via `agentTypes` data already in scope)

**Done when:** The dashboard table shows a Session column; it is non-empty for jobs linked to conversation sessions; existing non-conversation rows show an em-dash.

---

## Phase 6 — Navigation & i18n

### 6.1 — Add routes for session list and chat resume

Update the frontend router configuration (in `frontend/src/app/` or `main.tsx`):

- Add route `/agents/:agentTypeId/sessions` → renders `AgentManagementPage` with the Sessions tab pre-selected
- Add route `/agents/:agentTypeId/chat/:sessionId` → renders `ChatPage` in resume mode

**Done when:** Both routes resolve without 404; deep-linking to `/agents/:id/chat/:sessionId` loads the correct session history.

### 6.2 — Add i18n keys for all new UI text

Add keys to the default English locale file(s) under `frontend/src/i18n/` for:

- Sessions tab label
- "Start New Conversation" button
- Session status labels for `archived`
- Resume, End, Archive action labels
- Confirmation dialog titles and body text
- Session title placeholder (for null titles)
- Dashboard "Session" column header

**Done when:** No hardcoded strings exist in any new or modified component; all new keys have English values; the `t()` function resolves them without fallback warnings.

---

## Phase 7 — Tests

### 7.1 — Backend unit tests: `ConversationSessionManager` lifecycle transitions

Create `backend/tests/unit/conversations/test_session_manager.py`:

- Test `create` rejects non-conversation agent types
- Test `end` transitions status to `closed`
- Test `archive` transitions status to `archived`
- Test `resume` returns full turn history
- Test ownership validation raises `PermissionError` for a mismatched user

**Done when:** All tests pass; no real database required (use mocked `AsyncSession`).

### 7.2 — Backend unit tests: `SessionAutoNamer` title generation and write-back

Create `backend/tests/unit/conversations/test_auto_namer.py`:

- Test that `generate_and_save` calls `ConversationStore.update_title` with the LLM result
- Test fallback to truncated first message when LLM raises an exception
- Test that an empty LLM response produces a non-empty fallback title

**Done when:** All tests pass with the LLM provider mocked.

### 7.3 — Backend integration tests: new REST endpoints

Add tests to `backend/tests/integration/test_conversations.py` (or create it):

- `POST /conversations` creates a session and returns `session_id`
- `POST /conversations/{id}/end` transitions status to `closed`
- `POST /conversations/{id}/archive` transitions status to `archived`
- `POST /conversations/{id}/resume` returns full history
- `POST /conversations/{id}/end` by a different user returns 403
- `GET /conversations?agent_type_id=<id>` returns sessions filtered correctly

Run against a real test database with `alembic upgrade head` applied.

**Done when:** All integration tests pass; 403 ownership test fails before the ownership check is added and passes after.

### 7.4 — Frontend component tests: `ConversationSessionsTab` list and actions

Create `frontend/src/__tests__/ConversationSessionsTab.test.tsx`:

- Renders session titles and status chips from mocked API data
- "Start New Conversation" button calls the create mutation
- Archive action shows confirmation dialog before mutating
- Empty state renders a message (no crash on empty list)

**Done when:** All component tests pass via `vitest`; no real API calls made (React Query mocked).

### 7.5 — E2E test: start, view, resume, and end a conversation session

Create `e2e/tests/conversation-sessions.spec.ts`:

- Start a new conversation with a conversation-type agent
- Verify the session title appears (after auto-naming)
- Navigate away and return to the Sessions tab
- Resume the session and verify history is restored
- End the session and verify it no longer appears in the active list (one test variant runs against real backend — no `page.route()` mocking for the lifecycle transitions)

**Done when:** All E2E scenarios pass in the dev environment; the real-backend variant exercises actual migration changes.

---

## Completion Checklist

- [ ] All Alembic migrations applied; `alembic current` matches head
- [ ] All unit tests pass (`pytest backend/tests/unit/`)
- [ ] All integration tests pass against real database
- [ ] All frontend component tests pass (`vitest run`)
- [ ] All E2E tests pass, including real-backend variant
- [ ] No hardcoded UI strings in new or modified components
- [ ] `docs/master/data-model/modules/communication/entities.md` updated per `data-model.md` instructions
- [ ] `docs/master/product/conversation-agents.md` updated with session management flow
- [ ] `.change.yaml` updated: `developer: true`
