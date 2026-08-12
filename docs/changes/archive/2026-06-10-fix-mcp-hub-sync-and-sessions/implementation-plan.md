# Implementation Plan: Fix MCP Hub Sync & Sessions

## Overview

This plan addresses four quality issues in the MCP Hub: duplicate System server entry in the server list, sync fragility when the initialize handshake fails, misleading sync action visibility for servers without sessions, and the absence of an explicit default session. The changes span database schema (adding `is_default` to McpSession), backend API logic (sync resilience, session resolution, duplicate dedup), and frontend UI (conditional sync, default session management, system entry styling).

## Task Checklist

### Phase 1 — Database Changes

- [x] 1.1 — Add `is_default` boolean field to `McpSession` ORM model
- [x] 1.2 — Generate and apply Alembic migration for `is_default` column
- [x] 1.3 — Add `is_default` to `McpSessionRead` Pydantic schema
- [x] 1.4 — Add `is_default` to `McpSessionCreate` and `McpSessionUpdate` Pydantic schemas

### Phase 2 — Backend API Changes

- [x] 2.1 — Fix duplicate System entry in `list_mcp_servers` endpoint
- [x] 2.2 — Add `session_count` to `McpServerRead` schema and populate in server list query
- [x] 2.3 — Add sync warnings capture to `ToolSyncService.sync` and `SyncResult` schema
- [x] 2.4 — Make sync endpoint resilient: return partial success when tools/list works despite initialize warnings
- [x] 2.5 — Gate sync endpoint: require at least one session for sync, return 422 with explanation when none exist
- [x] 2.6 — Implement default session resolution: use `is_default` flag instead of creation-order fallback in `sync_mcp_server`
- [x] 2.7 — Implement default session resolution in `McpProxyEngine._resolve_session`
- [x] 2.8 — Implement default session resolution in `test_mcp_tool` endpoint
- [x] 2.9 — Auto-set `is_default` on session create when it is the server's first/only session
- [x] 2.10 — Enforce at-most-one-default constraint on session update and create
- [x] 2.11 — Handle default session deletion: prevent deletion or require re-assignment when the default is deleted and others remain

### Phase 3 — Frontend Changes

- [x] 3.1 — Add `is_default` to `McpSession` TypeScript interface
- [x] 3.2 — Add `session_count` to `McpServer` TypeScript interface
- [x] 3.3 — Update `McpHubPage` server list: show System entry with distinct "Built-in" chip and disabled actions
- [x] 3.4 — Update `McpHubPage` server list: add session count column and conditionally enable sync button
- [x] 3.5 — Update `McpSessionManager`: display default session indicator ("Default" chip) and radio-button selection
- [x] 3.6 — Update `McpSessionManager`: auto-default message when only one session exists
- [x] 3.7 — Update `McpSessionManager`: handle default re-selection prompt when deleting the current default
- [x] 3.8 — Add i18n keys for new UI strings (default session labels, sync-disabled tooltip, system server, sync warnings)

### Phase 4 — Testing & Verification

- [x] 4.1 — Update backend unit tests for `ToolSyncService` to cover initialize-warning scenarios
- [x] 4.2 — Update backend unit tests for session CRUD to cover `is_default` auto-assignment and uniqueness
- [x] 4.3 — Update backend integration tests for MCP Hub API: sync gating, duplicate system fix, default session resolution
- [x] 4.4 — Add frontend unit tests for `McpSessionManager` default selection UI
- [x] 4.5 — Add frontend unit tests for `McpHubPage` sync button gating and System entry display
- [x] 4.6 — Update E2E tests: MCP Hub server list verifies single System entry and sync gating
- [x] 4.7 — Verify migration applies cleanly: run `alembic upgrade head` and confirm `is_default` column exists

## Phase 1 — Database Changes

### 1.1 — Add `is_default` to McpSession ORM model

Add `is_default: Mapped[bool]` field to the `McpSession` class in the SQLAlchemy model. Default value `False`, not nullable. Position the field between `is_active` and `created_at` to match the entity relationship diagram in `data-model.md`.

**Done when**: `McpSession` class in `backend/app/db/models/mcp_hub.py` has a new `is_default` column with `mapped_column(Boolean, nullable=False, default=False)`.

### 1.2 — Generate and apply Alembic migration

Generate a new Alembic migration with `alembic revision --autogenerate -m "add_is_default_to_mcp_sessions"`. Review the generated file to ensure it contains `op.add_column('mcp_sessions', sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()))`. Apply with `alembic upgrade head`.

**Done when**: `alembic current` shows the new migration revision as head, and `is_default` column exists in the `mcp_sessions` table.

### 1.3 — Add `is_default` to McpSessionRead schema

Add `is_default: bool` field to `McpSessionRead` Pydantic model. Since the ORM model now has this attribute and `from_attributes = True`, it will be automatically populated from model instances.

**Done when**: `McpSessionRead` in `backend/app/schemas/mcp_hub.py` includes `is_default: bool` field.

### 1.4 — Add `is_default` to create/update schemas

Add `is_default: bool | None = None` to `McpSessionCreate` and `McpSessionUpdate` schemas. Both are optional — when omitted on create, the backend auto-sets based on whether there are other sessions. On update, only set fields are applied.

**Done when**: Both `McpSessionCreate` and `McpSessionUpdate` schemas include the `is_default` optional field.

---

## Phase 2 — Backend API Changes

### 2.1 — Fix duplicate System entry in server list

In `list_mcp_servers`, when `offset == 0`, the system server is prepended as a virtual entry via `_system_server_read()`. However, `seed_system_tools()` also inserts the System server into the database, so it also appears in DB results. Filter the seeded system server (`SYSTEM_SERVER_ID`) from the DB query results before prepending the virtual entry. This ensures exactly one System entry appears.

**Done when**: `GET /mcp/servers?offset=0` returns exactly one System entry (the virtual one with ID `00000000-...-0001`). The seeded database copy is excluded from the response list.

### 2.2 — Add session_count to McpServerRead

Add `session_count: int` to `McpServerRead` (default `0`). In `list_mcp_servers`, eager-load the sessions relationship with `selectinload(McpServer.sessions)` and populate `session_count` by calling `McpServerRead.model_validate(server)` with an additional kwarg for the count. The system server virtual entry should have `session_count = 0`.

**Done when**: `GET /mcp/servers` response objects include a `session_count` field with the correct number of sessions per server.

### 2.3 — Add sync warnings to SyncResult

Add `warnings: list[str] = []` to the `SyncResult` Pydantic schema. Modify `ToolSyncService.sync` to accept and return an optional warnings list. When `_initialize_mcp_session` catches an exception, append a warning string to the list instead of just logging. The warnings list is surfaced in the API response.

**Done when**: `SyncResult` schema includes `warnings` field, and a sync where initialize fails but tools/list succeeds returns warnings alongside tool counts.

### 2.4 — Make sync endpoint resilient

Modify `sync_mcp_server` endpoint: if `ToolSyncService.sync` completes successfully (tools were fetched), return 200 with the `SyncResult` including any warnings. Only raise 502 when `tools/list` itself fails entirely. The endpoint should no longer raise `RuntimeError` for non-fatal issues — the sync service must distinguish between fatal errors (raise) and warnings (return in the result).

**Done when**: Syncing a server where initialize handshake fails but tools/list succeeds returns 200 with `tools_added > 0` and a non-empty `warnings` list.

### 2.5 — Gate sync endpoint on session existence

In `sync_mcp_server`, after verifying the server exists, query for any session (active or inactive) belonging to the server. If zero sessions exist, return HTTP 422 with detail `"This server has no configured sessions. Add a session before syncing."`. This prevents wasted sync attempts on sessionless servers.

**Done when**: `POST /mcp/servers/{id}/sync` returns 422 for a server with zero sessions, with a message explaining the requirement.

### 2.6 — Default session resolution in sync_mcp_server

Replace the current session lookup in `sync_mcp_server` (which uses `order_by(McpSession.created_at.asc()).limit(1)` to find any active session) with logic that:
- First, look for `is_default == True AND is_active == True`
- If none found, look for the sole active session (if exactly one active session exists, treat it as default)
- If multiple active sessions exist and none is default, return 422 with `"No default session configured. Please designate a default session."`
- If no active sessions at all, return 422 with `"No active sessions found."`

**Done when**: Sync uses the `is_default`-marked session, auto-selects the sole active session, and properly errors when the default is ambiguous.

### 2.7 — Default session resolution in McpProxyEngine

In `McpProxyEngine._resolve_session`, when no explicit `session_id` is provided, change the fallback behavior from `.limit(1)` (first active session) to:
- Query for `is_default == True AND is_active == True`
- If none found and only one active session exists, use it
- If multiple active sessions and no default, raise `McpProxyError("No default session configured for server {server_id}")`

**Done when**: Tool calls without an explicit session ID route to the `is_default` session when one exists.

### 2.8 — Default session resolution in test_mcp_tool endpoint

In `test_mcp_tool`, when `body.session_id` is `None` and the session found is `passthrough`, the current logic already auto-selects. Extend the non-passthrough path: if no `session_id` is provided, look for the default session by `is_default == True`. If a default exists (even non-passthrough), use it. Only require an explicit `session_id` when no default is configured.

**Done when**: Testing a tool without specifying `session_id` uses the server's default session if one exists.

### 2.9 — Auto-set is_default on session create

In `create_mcp_session`, after creating the session but before the connection test, check how many sessions exist for this server (including the new one). If this is the server's first session (`count == 1`), set `is_default = True` on the new session automatically.

**Done when**: Creating a session for a server with zero existing sessions automatically marks it `is_default = True`.

### 2.10 — Enforce at-most-one-default constraint

In both `create_mcp_session` and `update_mcp_session`, when `is_default` is explicitly set to `True`, set all other sessions for the same server to `is_default = False` before committing. This ensures at most one default session per server at any time.

**Done when**: Setting a session as default via create or update automatically clears the `is_default` flag on all other sessions of that server.

### 2.11 — Handle default session deletion

In `delete_mcp_session`, after identifying the session to delete, check if it is the current default (`is_default == True`). If so, check how many other sessions exist for this server. If other sessions exist, return HTTP 409 with detail `"The default session cannot be deleted while other sessions exist. Please designate another session as default first."`. If this is the last session, allow deletion (no default to reassign).

**Done when**: Deleting the default session when other sessions exist returns 409 with an actionable message. Deleting the last session succeeds normally.

---

## Phase 3 — Frontend Changes

### 3.1 — Add is_default to McpSession type

In `frontend/src/types/index.ts`, add `is_default: boolean` to the `McpSession` interface.

**Done when**: `McpSession` TypeScript interface includes `is_default: boolean`.

### 3.2 — Add session_count to McpServer type

In `frontend/src/types/index.ts`, add `session_count: number` to the `McpServer` interface.

**Done when**: `McpServer` TypeScript interface includes `session_count: number`.

### 3.3 — System entry with distinct styling

In `McpHubPage.tsx`, detect the System server by its ID (`00000000-0000-0000-0000-000000000001`). Render it with a distinct visual treatment:
- A "Built-in" chip (purple/info variant) next to the server name
- Disabled edit and delete buttons
- Disabled sync button
- "System managed" text instead of action buttons, matching the prototype
- A contextual info banner at the top of the server list explaining the System entry (matching the prototype's `.system-intro` section)

**Done when**: The System row in the server table shows a "Built-in" chip, all action buttons are disabled or replaced with "System managed" text, and the info banner is present.

### 3.4 — Conditional sync button with session count

In `McpHubPage.tsx`:
- Add a "Sessions" column to the server table showing the count from `server.session_count`
- When `session_count === 0`, disable the sync button and wrap it in a `Tooltip` with text explaining "Add a session before syncing"
- When `session_count > 0`, enable the sync button normally
- The System entry's sync is always disabled

**Done when**: The server table shows session counts, and the sync button is disabled with a tooltip for servers with zero sessions.

### 3.5 — Default session indicator and selection UI

In `McpSessionManager.tsx`:
- Show a "Default" chip (using a purple/violet color, matching the prototype's `.chip-default` class) next to the session name for the default session
- When multiple sessions exist, make session rows clickable with a radio-button style indicator (filled circle for default, empty circle for others) to set the default
- On click of a non-default session row, call `PUT /mcp/servers/{serverId}/sessions/{sessionId}` with `{ is_default: true }` and invalidate the sessions query
- Use `useMutation` from `@tanstack/react-query` for the set-default API call

**Done when**: The sessions table shows a "Default" chip on the default session, and clicking a non-default session marks it as default with radio-button visual feedback.

### 3.6 — Auto-default message for sole sessions

In `McpSessionManager.tsx`, when the server has exactly one session, display an info alert at the top of the sessions list: "Only one session exists — it is automatically treated as the default. Add more sessions to choose a different default." The sole session's radio indicator shows a special "auto" state (dimmed purple dot, matching the prototype).

**Done when**: A server with a single session shows the auto-default info alert and the session row displays a dimmed default indicator that is not clickable.

### 3.7 — Default re-selection prompt on delete

In `McpSessionManager.tsx`, when the user attempts to delete the default session and other sessions exist:
- Intercept the delete confirmation with a custom dialog or alert
- Show text: "This is the current default session. Please set another session as default before deleting this one."
- After the user sets a new default, allow the delete to proceed
- If the session is the last one, allow immediate deletion

**Done when**: Attempting to delete the default session when others exist shows a blocking prompt. After re-assigning default, deletion succeeds.

### 3.8 — Add i18n keys

Add the following keys to the English translation file:
- `mcp.system.builtIn`: "Built-in"
- `mcp.system.description`: "System entry represents Parthenon's built-in platform tools"
- `mcp.system.systemManaged`: "System managed"
- `mcp.system.aboutTitle`: "About the System entry"
- `mcp.system.aboutBody`: "The System entry represents Parthenon's built-in platform tools..."
- `mcp.sync.noSessions`: "Add a session before syncing"
- `mcp.sync.noSessionsError`: "This server has no configured sessions"
- `mcp.sync.warnings`: "Sync completed with warnings"
- `mcp.sessions.default`: "Default"
- `mcp.sessions.setDefault`: "Set as default"
- `mcp.sessions.autoDefaultInfo`: "Only one session exists — it is automatically treated as the default."
- `mcp.sessions.autoDefaultAddMore`: "Add more sessions to choose a different default."
- `mcp.sessions.cannotDeleteDefault`: "This is the current default session. Please set another session as default before deleting this one."
- `mcp.sessions.deleteDefaultBlocked`: "Cannot delete the default session while other sessions exist..."
- `mcp.sessions.selectDefaultHint`: "Select one session as the default..."
- `mcp.sessions.defaultFooterHint`: "Default session is used when syncing tools and for tool routing..."
- `mcp.servers.sessions`: "Sessions"

All keys defined in `frontend/src/i18n/locales/en.json` and used via `t()` in components. No additional language files exist yet.

**Done when**: All new UI strings are defined in `frontend/src/i18n/locales/en.json` and used via `t()` in components.

---

## Phase 4 — Testing & Verification

### 4.1 — Backend unit tests: ToolSyncService sync resilience

Updated tests in `backend/tests/unit/test_mcp_hub.py` (3 new tests):
- `test_sync_resilience_initialize_fails_but_tools_list_succeeds` — sync returns warnings when initialize handshake fails but tools/list succeeds
- `test_sync_fatal_failure_when_both_initialize_and_tools_list_fail` — sync raises when both operations fail
- `test_sync_updates_last_synced_at_on_success` — `last_synced_at` timestamp updated on successful sync

**Done when**: Unit tests cover both the resilient path (warnings returned) and the fatal path (exception raised) for `ToolSyncService.sync`.

### 4.2 — Backend unit tests: is_default schema validation

Updated tests in `backend/tests/unit/test_mcp_session.py` (5 new tests):
- `test_mcp_session_read_schema_includes_is_default` — `McpSessionRead` includes `is_default: bool`
- `test_mcp_session_create_schema_accepts_optional_is_default` — `McpSessionCreate` accepts optional `is_default`
- `test_mcp_session_update_schema_accepts_optional_is_default` — `McpSessionUpdate` accepts optional `is_default`
- `test_mcp_session_model_is_default_defaults_to_false` — ORM model defaults `is_default` to `False`
- `test_mcp_server_read_includes_session_count` — `McpServerRead` includes `session_count: int`

Business logic for CRUD operations (auto-set on create, clearing siblings, delete protection) is tested at the API integration level in 4.3.

**Done when**: Unit tests cover all schema field validation and ORM model defaults for `is_default`.

### 4.3 — Backend integration tests: MCP Hub API

Updated tests in `backend/tests/api/v1/test_mcp_hub_api.py` (6 new tests, 2 fixes):
- `test_list_servers_offset_zero_returns_one_system_entry` — System entry dedup at offset 0
- `test_list_servers_offset_nonzero_no_system_entry` — System entry excluded at non-zero offset
- `test_sync_server_with_no_sessions_returns_422` — sync gating when zero sessions
- `test_mcp_server_read_includes_session_count` — `session_count` field in server response
- `test_mcp_session_read_includes_is_default` — `is_default` field in session response
- `test_sync_resolves_default_session_by_is_default_flag` — sync uses `is_default`-marked session
- Also fixed 2 pre-existing tests (name validation, system tools in response) to work with new schemas

### 4.4 — Frontend unit tests: McpSessionManager default UI

Updated tests in `frontend/src/__tests__/McpSessionManager.test.tsx` (5 new tests in 2 new describe blocks):
- `McpSessionManager — Default session display` (4 tests):
  - Renders "Default" chip next to default session
  - Shows radio-button indicator for each session
  - Shows auto-default info alert when only one session exists
  - Shows Default chip for sole session even when `is_default=false` (auto-default logic)
- `McpSessionManager — Default session deletion blocking` (1 test):
  - Shows blocking delete prompt when deleting default with siblings

**Done when**: Vitest tests cover the default session UI states (default, auto-default, multi-session selection, delete protection).

### 4.5 — Frontend unit tests: McpHubPage display

Updated tests in `frontend/src/__tests__/McpHubPage.test.tsx` (5 new tests in 2 new describe blocks, plus 3 existing tests updated):
- `McpHubPage — System Entry` (3 tests):
  - System entry shows "Built-in" chip and disabled actions
  - System entry shows `platform://built-in` slug and no sync action enabled
  - System entry shows disabled actions and system-managed text
- `McpHubPage — Sync button visibility based on session_count` (2 tests):
  - Sync button disabled with tooltip when `session_count === 0`
  - Sync button enabled when `session_count > 0`
- Updated 3 existing sync button state tests for 3-row table (System + 2 servers)

**Done when**: Vitest tests cover the conditional rendering states for System entry, sync button gating, and session count display.

### 4.6 — E2E tests: MCP Hub server list

Updated `e2e/tests/mcp-hub.spec.ts` (4 new mocked tests, 2 real-backend tests):
- `MCP Hub — System Entry` (2 mocked tests): Built-in chip, disabled sync with tooltip
- `MCP Hub — Sync button visibility` (2 mocked tests): enabled with sessions, disabled without sessions
- `Real Backend Integration - MCP Default Session` (2 real-backend tests):
  - Creates a real server via API, verifies 422 on sync without sessions
  - Verifies exactly one System entry at offset 0
  - Cleanup after all tests

**Done when**: E2E tests pass including a real-backend variant that validates migration was applied correctly.

### 4.7 — Migration verification

Run `alembic upgrade head` and verify:
- `is_default` column exists in `mcp_sessions` table with default `false`
- Existing sessions all have `is_default = false` (no disruption)
- Backend starts without errors and serves MCP Hub endpoints

**Done when**: Migration applies cleanly, backend starts, and existing server/session data is intact.

---

## Completion Checklist

- [x] All database migrations applied and verified
- [x] Backend tests pass (unit + integration)
- [x] Frontend tests pass (unit)
- [x] E2E tests pass including real-backend variant
- [x] `GET /mcp/servers` returns exactly one System entry
- [x] Sync returns 422 for servers with zero sessions
- [x] Sync returns warnings when initialize fails but tools/list succeeds
- [x] `is_default` flag is auto-set on first session, enforced as unique per server
- [x] Frontend shows "Built-in" chip on System entry with disabled actions
- [x] Sync button is disabled with tooltip when no sessions exist
- [x] Session manager shows default indicator, radio selection, and auto-default message
- [x] All new UI strings are internationalized via `t()`
