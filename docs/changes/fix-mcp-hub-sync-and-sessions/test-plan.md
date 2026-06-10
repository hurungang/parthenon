# Test Plan: Fix MCP Hub Sync & Sessions

## Pre-Test Checklist — Database Migration

**CRITICAL**: This change includes `has_db_changes: true`. Before running ANY tests:

1. **Verify migration status** — Run `python -m alembic current` — must show the latest migration ID that includes the `is_default` column addition
2. **Apply pending migrations** — If `is_default` migration is not applied, run `python -m alembic upgrade head`
3. **Re-verify** — Run `python -m alembic current` again — confirm the migration ID matches the latest file in `backend/alembic/versions/`
4. **Check column presence** — After migration, the `mcp_sessions` table must have an `is_default` column of type `BOOLEAN`, defaulting to `false`, non-nullable
5. **Restart backend** — If migration was just applied, restart the backend services (`.\parthenon.ps1 restart -Services backend -Force`) so the ORM models pick up the new schema

---

## 1. Test Strategy

### Overall Approach

| Layer | Scope | Framework | Coverage Target |
|-------|-------|-----------|-----------------|
| **Backend Unit** | Model schema, Pydantic schemas, business logic for `is_default` validation, sync service resilience | pytest + SQLite in-memory | All new/modified functions, all enum/bool branches |
| **Backend Integration** | DB round-trip for `is_default` column, API endpoint behavior for session CRUD with default flag, sync endpoint behavior with session dependency | pytest + httpx (ASGI transport) + SQLite StaticPool | Full CRUD lifecycle for sessions with `is_default`, schema constraint verification |
| **Backend API (real DB)** | Real PostgreSQL integration: `is_default` column existence, constraint enforcement, sync with real session routing | pytest + `DATABASE_URL` pointing to PostgreSQL | At least one test against real Postgres verifying `information_schema` column properties |
| **Frontend Unit** | Component rendering for System entry dedup, sync button visibility based on session count, default session badge/chip, session dialog default toggle | Vitest + React Testing Library | New/modified UI elements, conditional rendering logic, state transitions |
| **E2E** | Full UI flows: server list with one System entry, sync button visibility, default session creation/display/deletion | Playwright (mocked API) | Critical user journeys |
| **E2E Real Backend** | At least one complete CRUD lifecycle test against the real backend (no API mocks) verifying `is_default` persistence and retrieval | Playwright + real backend | Verifies real DB integration, migration effectiveness |

### Dependency Order

- Backend unit tests run first (no DB required beyond SQLite in-memory)
- Backend integration tests run second (SQLite StaticPool; catches schema/model mismatches)
- Backend PostgreSQL-specific test runs third (requires real Postgres and applied migration)
- Frontend unit tests run fourth (Vitest, independent of backend)
- E2E (mocked) tests run fifth (Playwright, independent of backend)
- E2E real backend tests run last (requires full stack running with migrated DB)

---

## 2. Coverage Areas

### Area 1: System Entry Deduplication (`backend/app/db/models/mcp_hub.py`, frontend MCP Hub page)

**Why critical**: A duplicate System entry confuses administrators, undermines trust in the MCP Hub, and could lead to selecting the wrong "server" for operations.

**What must be tested**:
- Backend server list endpoint returns zero or one System entry, never two
- Frontend server list renders only one System row
- System entry is visually distinguishable from user-registered servers (virtual/platform label)
- Creating/deleting real MCP servers does not affect the System entry count
- System entry has no sessions, no sync button, no edit/delete controls

### Area 2: Sync Resilience (`backend/app/services/mcp/` sync module)

**Why critical**: Admins cannot verify tool availability if sync fails on servers that are otherwise functional. The initialize handshake can fail while tools/list succeeds; sync should handle this gracefully.

**What must be tested**:
- Sync succeeds when `tools/list` works even if `initialize` fails or returns unexpected response
- Sync failure when both `initialize` and `tools/list` fail returns specific, actionable error messages
- Sync results include discovered tool count and any warnings from handshake issues
- Sync updates `last_synced_at` timestamp on success
- Sync does not update `last_synced_at` on failure
- Sync error messages differ by failure mode (no network vs. auth failure vs. protocol error)

### Area 3: Sync Visibility & Session Dependency (frontend MCP Hub page, server row actions)

**Why critical**: Admins waste time clicking sync on servers with zero sessions — an action guaranteed to fail. The UI must guide them to the correct action (create a session) instead.

**What must be tested**:
- Server with **one or more sessions**: sync button/action is **visible and enabled**
- Server with **zero sessions**: sync button/action is **hidden or disabled** with explanatory tooltip
- After creating a session via dialog, sync button becomes visible/enabled in the parent server row (parent table refresh)
- After deleting all sessions, sync button becomes hidden/disabled (parent table refresh)
- System entry never shows sync action regardless of state

### Area 4: Default Session (`backend/app/db/models/mcp_hub.py`, `backend/app/schemas/mcp_hub.py`, frontend session management UI)

**Why critical**: Without an explicit default, tool routing when multiple sessions exist is unpredictable. The `is_default` flag gives admins control over which session's credentials are used.

**What must be tested**:
- **Schema and Model**:
  - `is_default` column exists on `mcp_sessions` table, type `BOOLEAN`, nullable false, default `false`
  - Pydantic `McpSessionCreate` schema accepts optional `is_default` field
  - Pydantic `McpSessionUpdate` schema accepts optional `is_default` field
  - Pydantic `McpSessionRead` schema includes `is_default` in response
  - Encrypted credentials are still excluded from all response schemas

- **Business Logic — Single Session**:
  - When server has exactly one session, it is automatically treated as default regardless of `is_default` flag value
  - Creating the first session on a server defaults `is_default` to `true` on the backend
  - The sole session is visibly indicated as default in the sessions list

- **Business Logic — Multiple Sessions**:
  - Admin can set `is_default = true` on exactly one session per server
  - Setting a new session as default automatically unsets `is_default` on the previously-default session (only one per server)
  - Default session is visually distinguished in sessions list (badge, chip, or icon)
  - If default session is deleted and other sessions remain, admin must explicitly select a new default (or creation fails/prompts)
  - Creating a new session does not auto-override existing default

- **Business Logic — Sync Routing**:
  - Sync uses the default session when no specific session is specified
  - If no default session exists and multiple sessions exist, sync fails with a clear error indicating no default
  - Tool calls use the default session when no specific session is specified

- **Passthrough Compatibility**:
  - Sessions with `auth_type = passthrough` are eligible to be default
  - Setting a passthrough session as default works correctly

- **Backward Compatibility**:
  - Existing sessions without `is_default` set (or `false`) continue to work
  - Role-to-session mappings are unaffected

### Area 5: Parent Table Refresh (CRITICAL — Cross-cutting)

**Why critical**: Many bugs occur when parent tables don't refresh after dialog operations. This affects all four coverage areas above.

**What must be tested**:
- After creating a session → server row in parent table updates without page reload
- After editing session (setting `is_default`) → session list refreshes, default badge updates
- After deleting a session → parent table and session list refresh
- Session count changes reflect in UI immediately after create/delete

---

## 3. Critical Scenarios

### System Entry Deduplication

| # | Scenario |
|---|----------|
| S1 | **WHEN** the MCP server list is loaded **THEN** exactly one System entry is displayed, visually distinct from real servers |
| S2 | **WHEN** a new real MCP server is registered **THEN** the System entry count remains exactly one, the new server appears separately |
| S3 | **WHEN** a real MCP server is deleted **THEN** the System entry remains unchanged and visible |
| S4 | **WHEN** the System entry row is inspected **THEN** no sync action, no edit action, and no delete action are available |

### Sync Resilience

| # | Scenario |
|---|----------|
| S5 | **WHEN** sync is triggered on a server where `tools/list` succeeds but `initialize` returns an error **THEN** sync completes, tools are discovered, and a warning about the initialize issue is displayed |
| S6 | **WHEN** sync is triggered and both `initialize` and `tools/list` fail **THEN** sync fails with an error message that specifically indicates the failure reason (e.g., connection refused vs. authentication error vs. protocol mismatch) |
| S7 | **WHEN** sync succeeds **THEN** `last_synced_at` timestamp updates on the server record |
| S8 | **WHEN** sync fails **THEN** `last_synced_at` timestamp does NOT update |

### Sync Visibility & Session Dependency

| # | Scenario |
|---|----------|
| S9 | **WHEN** viewing a server with one or more configured sessions **THEN** the sync action is visible and enabled |
| S10 | **WHEN** viewing a server with zero configured sessions **THEN** the sync action is hidden or disabled with a tooltip explaining that sessions are required |
| S11 | **WHEN** the last session on a server is deleted **THEN** the sync action becomes hidden/disabled (parent table updates without page reload) |
| S12 | **WHEN** a session is created for a server that previously had zero sessions **THEN** the sync action becomes visible/enabled (parent table updates without page reload) |

### Default Session — Single Session

| # | Scenario |
|---|----------|
| S13 | **WHEN** the first session is created on a server **THEN** `is_default` is automatically set to `true` on the backend |
| S14 | **WHEN** a server has exactly one session **THEN** that session is visibly marked as default in the sessions list regardless of the actual `is_default` column value |
| S15 | **WHEN** a server's sole session is fetched via API **THEN** the response includes `is_default: true` |

### Default Session — Multiple Sessions

| # | Scenario |
|---|----------|
| S16 | **WHEN** an admin sets a session as default via the UI **THEN** that session shows a default indicator and the previously-default session loses its indicator |
| S17 | **WHEN** an admin sets a session as default via API (`PUT` with `is_default: true`) **THEN** that session's `is_default` becomes `true` and all other sessions for the same server have `is_default` reset to `false` |
| S18 | **WHEN** attempting to set two sessions on the same server as default via API **THEN** the second request automatically unsets the first (business rule: at most one default per server) |
| S19 | **WHEN** the default session is deleted and other sessions remain on the server **THEN** the admin is prompted to select a new default (or the delete is rejected until a new default is chosen) |
| S20 | **WHEN** a non-default session is deleted **THEN** the default session remains unchanged |

### Default Session — Sync & Tool Routing

| # | Scenario |
|---|----------|
| S21 | **WHEN** sync is triggered without specifying a session **THEN** the default session is used for the connection |
| S22 | **WHEN** multiple sessions exist but none is marked default **THEN** sync fails with a clear error indicating no default session is configured |

### Passthrough & Backward Compatibility

| # | Scenario |
|---|----------|
| S23 | **WHEN** a passthrough session is marked as default **THEN** it functions correctly as the default for sync and tool calls |
| S24 | **WHEN** existing sessions created before this change are loaded **THEN** they display `is_default: false` and function without errors |

---

## 4. Edge Cases & Risks

### Edge Cases

| # | Edge Case | Risk Level | Mitigation |
|---|-----------|------------|------------|
| E1 | Server with exactly one session that is `is_active = false` — should it still be treated as default? | Medium | Test that inactive sole sessions are still indicated as default but sync may fail gracefully |
| E2 | Server with one passthrough session as sole/default — sync with passthrough without a caller token | Medium | Test that the error message clearly indicates the missing agent identity requirement |
| E3 | Rapid toggle of `is_default` between two sessions (race condition) | Medium | Test with concurrent requests; ensure last-write-wins consistency |
| E4 | Session with `is_default = true` is deactivated (`is_active = false`) — should sync auto-fall to another session? | Low | Documented behavior: sync uses active default session; if default is inactive, sync fails with clear message |
| E5 | Server slug collision with System entry namespace | Low | Verify System entry uses a reserved slug that normal registration rejects |
| E6 | Sync with no sessions but session count cache is stale | Low | Ensure session count is always queried fresh from DB before sync button visibility decision |
| E7 | Deleting the last session (which was default) — server transitions to zero-session state | Medium | Verify sync button disappears, no stale default indicators remain |
| E8 | Migration applied on database with existing sessions — `is_default` defaults to `false` for all | High | Test migration on a DB with existing sessions; verify none are accidentally set default; admin must explicitly configure |
| E9 | `is_default` column not nullable — must always have a value | High | Test that inserting a session without specifying `is_default` succeeds (defaults to `false`) and that NULL inserts are rejected |

### Risk Areas

| Risk | Impact | Mitigation |
|------|--------|------------|
| Migration not applied before testing | All `is_default` tests fail with "column does not exist" | Pre-test checklist enforces migration verification |
| Parent table not refreshing after session dialog operations | Stale UI state; sync button visibility wrong | Every CRUD scenario includes explicit parent refresh assertion |
| System entry appearing as a real server in search/filter | Confusion; possible deletion attempts | Dedicated tests for System entry properties (non-editable, non-deletable) |
| Sync service changes breaking MCP Demo App | Demo app tool discovery fails | Cross-reference existing `mcp-demo-app/tests/` and verify no regressions |
| Default session logic not handling concurrent session creation | Two sessions created simultaneously both get `is_default = true` | Test concurrent session creation; verify server-side enforcement of uniqueness |
| Encrypted credentials leaking in new `is_default` response field | Security breach | Explicit tests that `McpSessionRead` with `is_default` does NOT include encrypted_credentials |

---

## 5. Acceptance Criteria Checklist

Maps PRD acceptance criteria to test areas:

### Duplicate System Entry

- [ ] **AC1**: MCP server list displays exactly one System entry — no duplicates
  - Tests: S1, S2, S3
- [ ] **AC2**: System entry is visually distinct from real MCP servers (virtual/platform label)
  - Tests: S1, S4
- [ ] **AC3**: Creating or deleting real MCP servers does not affect the System entry
  - Tests: S2, S3

### Sync Resilience

- [ ] **AC4**: Sync succeeds for servers where `tools/list` works, even if `initialize` handshake has issues
  - Tests: S5
- [ ] **AC5**: Sync results clearly indicate which tools were discovered and any warnings
  - Tests: S5, S7
- [ ] **AC6**: Sync failure messages are specific and actionable (not generic "error")
  - Tests: S6

### Sync Visibility & Session Dependency

- [ ] **AC7**: Sync action is visible and enabled only when a server has at least one configured session
  - Tests: S9, S10, S11, S12
- [ ] **AC8**: For servers with zero sessions, sync action is hidden or disabled with explanatory tooltip
  - Tests: S10

### Default Session

- [ ] **AC9**: When a server has multiple sessions, admin can designate exactly one as default
  - Tests: S16, S17, S18
- [ ] **AC10**: When a server has exactly one session, it is automatically the default
  - Tests: S13, S14, S15
- [ ] **AC11**: Default session is visibly indicated in the sessions list
  - Tests: S14, S16
- [ ] **AC12**: If default session is deleted and other sessions remain, admin is prompted to select a new default
  - Tests: S19
- [ ] **AC13**: Sync and tool calls use the default session when no specific session is specified
  - Tests: S21, S22

---

## 6. Test File References

### Backend Tests

| File | Layer | Coverage |
|------|-------|----------|
| `backend/tests/unit/test_mcp_hub.py` | Unit | **Updated**: Added 3 new tests — `test_sync_resilience_initialize_fails_but_tools_list_succeeds`, `test_sync_fatal_failure_when_both_initialize_and_tools_list_fail`, `test_sync_updates_last_synced_at_on_success` — covering sync resilience, fatal failure, and last_synced_at timestamp update |
| `backend/tests/unit/test_mcp_session.py` | Unit | **Updated**: Added 5 new tests — `test_mcp_session_read_schema_includes_is_default`, `test_mcp_session_create_schema_accepts_optional_is_default`, `test_mcp_session_update_schema_accepts_optional_is_default`, `test_mcp_session_model_is_default_defaults_to_false`, `test_mcp_server_read_includes_session_count` — covering is_default schema validation, model defaults, and session_count schema |
| `backend/tests/api/v1/test_mcp_hub_api.py` | API Integration | **Updated**: Added 6 new tests — `test_list_servers_offset_zero_returns_one_system_entry`, `test_list_servers_offset_nonzero_no_system_entry`, `test_sync_server_with_no_sessions_returns_422`, `test_mcp_server_read_includes_session_count`, `test_mcp_session_read_includes_is_default`, `test_sync_resolves_default_session_by_is_default_flag` — covering System entry dedup, sync session gating, session_count in response, is_default in response, and default session resolution. Also fixed 2 pre-existing tests (name validation, system tools in response) |
| `backend/tests/integration/test_mcp_hub.py` | Integration | No changes needed — existing passthrough tests already cover is_default-neutral scenarios |

### Frontend Tests

| File | Layer | Coverage |
|------|-------|----------|
| `frontend/src/__tests__/McpHubPage.test.tsx` | Unit | **Updated**: Added 5 new tests across 2 new describe blocks — `McpHubPage — System Entry` (3 tests: Built-in chip, disabled actions, platform slug) and `McpHubPage — Sync button visibility based on session_count` (2 tests: disabled when 0, enabled when >0). Updated 3 existing sync button state tests for 3-row table (System + 2 servers). Updated all mock data with `session_count` field |
| `frontend/src/__tests__/McpSessionManager.test.tsx` | Unit | **Updated**: Added 5 new tests across 2 new describe blocks — `McpSessionManager — Default session display` (4 tests: Default chip, radio buttons, auto-default alert, sole session chip) and `McpSessionManager — Default session deletion blocking` (1 test: blocking delete prompt). Updated all mock session data with `is_default` field |

### E2E Tests

| File | Layer | Coverage |
|------|-------|----------|
| `e2e/tests/mcp-hub.spec.ts` | E2E (mocked) | **Updated**: Added 4 new tests across 2 new describe blocks — `MCP Hub — System Entry` (2 tests: Built-in chip, disabled sync) and `MCP Hub — Sync button visibility` (2 tests: enabled with sessions, disabled without). Updated all mock data with `session_count` and `is_default` fields |
| `e2e/tests/mcp-hub.spec.ts` | E2E (real backend) | **Updated**: Added `Real Backend Integration - MCP Default Session` describe block with 2 tests — `GET /mcp/servers returns exactly one System entry at offset 0` and `POST /mcp/servers/{id}/sync returns 422 when no sessions exist` — both hitting the real backend via page.evaluate fetch (no mocks). Tests create a real server, verify 422 on sync without sessions, and cleanup after |

### Pre-Existing Tests at Risk

| File | Reason |
|------|--------|
| `backend/tests/integration/test_mcp_hub.py` | Existing passthrough tests use `is_active` only — must still pass after `is_default` column is added (default = false should not affect passthrough assertions) |
| `backend/tests/api/v1/test_mcp_hub_api.py` | Session create/read test payloads lack `is_default` — schema must accept it as optional with default false |
| `e2e/tests/mcp-hub.spec.ts` | MOCK_SESSION objects lack `is_default` field — mock data must be updated; existing tests may need `is_default` added to mock payloads |
| `frontend/src/__tests__/McpSessionManager.test.tsx` | Existing session creation tests — must accept new `is_default` field in form; default behavior should not break existing tests |
| `mcp-demo-app/tests/` | MCP Demo App tests — must continue to work; no regression in demo app behavior |

---

## 7. Data-Seeding for Tests

### Required Test Fixtures

| Fixture | Purpose |
|---------|---------|
| Server with 0 sessions | Verify sync button hidden/disabled |
| Server with 1 session | Verify auto-default behavior, sync button visible |
| Server with 2+ sessions, none default | Verify default assignment flow |
| Server with 2+ sessions, one marked default | Verify default badge, sync uses correct session |
| Server with 1 passthrough session | Verify passthrough as default compatibility |
| Server with 1 inactive session | Verify inactive session can be default but sync may warn |
| "System" server entry | Verify visually distinct, no sync/edit/delete actions |

### Test Data Naming Convention

All test-created entities must use identifiable prefixes:
- Server slugs: `e2e-test-srv-{timestamp}`
- Session names: `e2e-test-sess-{timestamp}`
- Clean up all test data in `afterEach` or `afterAll` hooks

---

## 8. Test Execution Order & Dependencies

```
1. Pre-test checklist (migration verification)
2. Backend unit tests (backend/tests/unit/)
3. Backend integration tests — SQLite (backend/tests/integration/)
4. Backend API tests (backend/tests/api/)
5. Backend PostgreSQL-specific test (DATABASE_URL → real Postgres)
6. Frontend unit tests (frontend/src/__tests__/)
7. E2E mocked tests (e2e/tests/mcp-hub.spec.ts — existing + new mock scenarios)
8. E2E real backend test (e2e/tests/mcp-hub.spec.ts — new real backend describe block)

Start backend: .\parthenon.ps1 start -Services backend
Start frontend: .\parthenon.ps1 start -Services frontend
Run all tests: follow test runner commands per layer
```
