# Agent Data Module Test Plan

## Scope

Covers the Agent Data admin page at `/admin/agent-data`, system tool allowlist updates for `save_data`, `get_data`, and `get_output` tools, backward-compatible removal of the "Results" tab from Agent Trails, and the `agent::data` resource type registration in both backend and frontend manifests.

---

## Critical Scenarios

- **WHEN** an unauthenticated request hits `GET /api/v1/agent-data`, **THEN** the API returns 401.
- **WHEN** an authorized operator filters by `agent_type_id` and `data_name`, **THEN** only matching records are returned with the correct total count.
- **WHEN** a record ID does not exist, **THEN** `GET /api/v1/agent-data/{id}` returns 404.
- **WHEN** a user lacks `agent::data:read`, **THEN** the API returns 403 and the UI renders a `PermissionDeniedAlert`.
- **WHEN** an agent saves intermediate data via `save_data`, **THEN** it appears on the Agent Data page with name, agent type, session, and full JSON in the detail drawer.

---

## Coverage Areas

### 1. Agent Data API

**What is tested:**
- `GET /api/v1/agent-data` endpoint registration, JWT authentication requirement, and paginated response structure
- `GET /api/v1/agent-data/{id}` single-record retrieval and 404 handling
- Filter parameters (`agent_type_id`, `data_name`, `session_id`) correctly filter results
- Pagination parameters (`page`, `page_size`) correctly paginate

**Acceptance criteria:**
- Endpoint returns 401 without JWT auth
- Paginated results include correct total count
- Filters narrow results as expected
- Non-existent ID returns 404

**Test files:**
- [backend/tests/integration/test_agent_data_api.py](../../../../backend/tests/integration/test_agent_data_api.py) — Agent Data API endpoint tests: auth, pagination, filtering, single record retrieval
- [backend/tests/unit/test_agent_data_service.py](../../../../backend/tests/unit/test_agent_data_service.py) — Service layer tests for query building and data mapping
- [backend/tests/unit/test_agent_data_sop_injection.py](../../../../backend/tests/unit/test_agent_data_sop_injection.py) — System tool allowlist injection tests for new SOP system tools

---

### 2. Resource Type Registration

**What is tested:**
- `RT_AGENT_DATA = "agent::data"` constant exists in backend
- Added to `ResourceTypeManifest` with `actions: ["read"]`
- Added to `MODULE_GROUPS` under `agent`
- Frontend mirror manifest includes `agent::data` entry

**Acceptance criteria:**
- New resource type usable in permission policies
- Matches both backend manifest and frontend mirror
- No 403 errors for system admin with wildcard permissions

**Test files:**
- [frontend/src/__tests__/ResourceTypeManifestMirror.test.ts](../../../../frontend/src/__tests__/ResourceTypeManifestMirror.test.ts) — Frontend manifest mirror: verifies all resource type entries including `agent::data`

---

### 3. System Tool Allowlist & SOP Injection

**What is tested:**
- `save_data`, `get_data`, and `get_output` system tools registered in the allowlist
- SOP injection correctly exposes these tools to SOP configurations
- No regression on existing system tool endpoints

**Acceptance criteria:**
- New tools available for SOP composition
- Existing tools continue to function unchanged
- System tool endpoint tests pass without modification

**Test files:**
- [backend/tests/integration/test_system_tool_endpoints.py](../../../../backend/tests/integration/test_system_tool_endpoints.py) — System tool endpoint tests covering save_data, get_data, get_output
- [backend/tests/unit/test_agent_data_sop_injection.py](../../../../backend/tests/unit/test_agent_data_sop_injection.py) — SOP system tool injection verification

---

### 4. Agent Trails Tab Removal

**What is tested:**
- AgentTrailsPage shows exactly 2 tabs: Executions and Conversation History
- No "Results" tab is visible
- Executions tab renders AgentInstanceDashboardPage correctly
- Conversation History tab renders ConversationHistoryPage correctly
- `/results` route removed from AppRouter (404 or redirect)

**Acceptance criteria:**
- Results tab fully removed from UI
- No broken navigation or inaccessible features
- Existing Executions and Conversation History tabs unaffected

**Test files:**
- Covered by existing agent trails and routing E2E tests — verify no Results tab regressions
- Agent trails page rendering verified in component integration tests

---

### 5. Frontend UI — Agent Data Page

**What is tested:**
- Page renders with filter bar and data table at `/admin/agent-data`
- Agent type dropdown populates with available agent types
- Table columns: Timestamp, Data Name, Agent Type, Session ID, Data Type
- Row click opens detail drawer with full JSON display
- Pagination controls work correctly
- Error state displays PermissionDeniedAlert
- Sidebar entry visible as "Agent Data" under Agents group
- Edge cases: large JSON values in detail drawer (scrollable), null agent_type_id/session_id (displays "—"), empty table (shows "No agent data records found")

**Acceptance criteria:**
- Page accessible from sidebar under Agents group
- All filter, pagination, and detail drawer interactions work
- Error states handled gracefully

**Test files:**
- Frontend component tests for AgentDataPage (covered by existing rendering test infrastructure)

---

## E2E Test Coverage

| Test File | Coverage |
|-----------|----------|
| Covered by existing agent management E2E flows | Sidebar navigation to Agent Data page, page rendering with mocked API, filter interactions (agent type dropdown), pagination, detail drawer on row click |

---

## Critical Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| Large JSON payloads in `data_value` | Detail drawer renders with scrollable `<pre>` block; truncated display for very large values |
| Null foreign keys (`agent_type_id`, `session_id`) | UI displays "—" placeholder; backend handles NULL gracefully in JOINs |
| Empty table state | Shows "No agent data records found" message; pagination controls hidden or disabled |
| Concurrent page navigation | React Router handles correctly; no stale state on component unmount |
| Permission denied for agent::data:read | PermissionDeniedAlert displayed; 401 for unauthenticated, 403 for unauthorized |

---

## Test Execution Summary

| Layer | Files | Status |
|-------|-------|--------|
| Backend — Unit | `test_agent_data_service.py`, `test_agent_data_sop_injection.py` | ✅ PASS |
| Backend — Integration | `test_agent_data_api.py`, `test_system_tool_endpoints.py` | ✅ PASS |
| Frontend | `ResourceTypeManifestMirror.test.ts` (agent::data entry) | ✅ PASS |
