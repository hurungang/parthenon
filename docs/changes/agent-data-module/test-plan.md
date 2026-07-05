# Test Plan — Agent Data Module

## 1. Test Strategy

| Layer | Approach | Scope |
|-------|----------|-------|
| **Integration (Backend)** | FastAPI TestClient with overridden auth — verify endpoint registration, auth check, and response structure | `GET /api/v1/agent-data`, `GET /api/v1/agent-data/{id}` |
| **System Tool (Backend)** | Existing system tool endpoint tests — verify no regression from allowlist changes | `save_data`, `get_data`, `get_output` endpoints |
| **Frontend** | Vitest component tests — verify page rendering with mocked API | `AgentDataPage` rendering, filters, table, detail drawer |
| **Manual** | Visual inspection — Agent Data page in browser, sidebar entry, removed Results tab | Page layout, data display, sidebar navigation |

## 2. Coverage Areas

### 2.1 Agent Data API

**Why critical:** New public endpoint must be correctly registered and gated by permission.

- `GET /agent-data` returns 401 without JWT auth (endpoint is registered and protected)
- `GET /agent-data` returns paginated results with correct total count
- `GET /agent-data/{id}` returns single record or 404
- Filters (`agent_type_id`, `data_name`, `session_id`) correctly filter results
- Pagination parameters (`page`, `page_size`) correctly paginate

### 2.2 Resource Type

**Why critical:** New `agent::data` resource type must be usable in policies.

- `RT_AGENT_DATA = "agent::data"` constant exists
- Added to `ResourceTypeManifest` with `actions: ["read"]`
- Added to `MODULE_GROUPS` under `agent`
- Frontend mirror manifest includes `agent::data`

### 2.3 Agent Trails Tab Removal

**Why critical:** Confirm Results tab is removed without breaking other tabs.

- AgentTrailsPage shows only 2 tabs: Executions and Conversation History
- No Results tab is visible
- Executions tab still renders AgentInstanceDashboardPage
- Conversation History tab still renders ConversationHistoryPage
- `/results` route no longer accessible (404 or redirect)

### 2.4 Frontend UI

**Why critical:** New page must be functional and consistent with existing pages.

- Agent Data page renders with filter bar and data table
- Agent type dropdown populates with available agent types
- Pagination controls work correctly
- Row click opens detail drawer with full JSON display
- Error state displays PermissionDeniedAlert
- Sidebar entry visible as "Agent Data" with icon

## 3. Critical Scenarios

| Scenario | Expected Result |
|----------|----------------|
| Operator navigates to `/admin/agent-data` | Page loads with filter bar, empty table, pagination |
| Operator selects an agent type filter | Table refreshes showing only data for that agent type |
| Operator clicks a row | Detail drawer opens showing metadata and JSON value |
| Operator without `agent::data:read` permission | Gets 401 (unauthenticated) or 403 (unauthorized) |

## 4. Edge Cases & Risks

- Agent data with large JSON values — detail drawer renders with scrollable pre block
- Agent data with null `agent_type_id` — displays "—" as agent type name
- Agent data with null `session_id` — displays "—" as session ID
- Empty agent data table — shows "No agent data records found" message
- Concurrent page navigation — React Router handles correctly

## 5. Acceptance Criteria Checklist

- [x] New "Agent Data" page at `/admin/agent-data` accessible from sidebar under Agents group
- [x] Table displays columns: Timestamp, Data Name, Agent Type, Session ID, Data Type
- [x] Filter supports agent type dropdown selection
- [x] Pagination is supported
- [x] Clicking a row opens a detail drawer showing the full `data_value` JSON and metadata
- [x] API endpoints require `agent::data` resource type with `read` permission
- [x] "Results" tab removed from Agent Trails page
- [x] `/results` route removed from AppRouter
- [x] New `RT_AGENT_DATA = "agent::data"` in both backend and frontend manifest
- [x] No new TypeScript compilation errors

## 6. Test File References

| File | Description |
|------|-------------|
| `backend/tests/integration/test_system_tool_endpoints.py` | System tool endpoint tests (4/4 passing) |
| `backend/tests/integration/test_agent_data_api.py` | Agent Data API endpoint tests (2/2 passing) |
