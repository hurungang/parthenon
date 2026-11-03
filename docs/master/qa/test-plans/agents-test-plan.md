# Agents Test Plan: System Tools (save_data / get_data / get_output)

## Scope

Covers the agent system tools for intermediate data persistence (`save_data`), named data retrieval (`get_data`), and output history query (`get_output`), plus the Agent Outputs Query UI page. Also covers tool naming regression (removal of legacy `save_result`) and filter guardrail enforcement.

---

## Coverage Areas

### 1. System Tool Naming and Context

**What is tested:**
- `save_data`, `get_data`, and `get_output` are present in agent tool context definitions
- Legacy `save_result` is absent from active system tool paths
- Frontend displays `save_data` / `get_data` / `get_output` in system tool listings
- `is_system_tool()` correctly identifies `system____` prefixed tool names

**Acceptance criteria:**
- Agent context tool definitions include `save_data`, `get_data`, `get_output`
- Agent context tool definitions exclude `save_result`
- Frontend system tools UI labels use the new tool names

**Test files:**
- [frontend/src/__tests__/system-tools-naming.test.ts](../../../../frontend/src/__tests__/system-tools-naming.test.ts) — Frontend tool name display and label verification
- [backend/tests/integration/test_system_tool_schemas.py](../../../../backend/tests/integration/test_system_tool_schemas.py) — Backend schema registration and tool definition structure
- [e2e/tests/agent-save-data-get-tools.spec.ts](../../../../e2e/tests/agent-save-data-get-tools.spec.ts) — E2E validation that context endpoint exposes save_data/get_data/get_output and excludes save_result

---

### 2. save_data Tool — Intermediate Data Persistence

**What is tested:**
- Records stored with required metadata: `data_name`, `data_value`, `agent_type`, `session_id`, and a server-generated timestamp
- Multiple distinct records can be saved per session (repeatable data capture)
- Service layer correctness for insert, query, and metadata integrity
- Internal API routing: Agent Runtime → Control Center internal path

**Acceptance criteria:**
- Each `save_data` invocation creates a distinct persisted record
- Stored metadata includes correct `agent_type` and `session_id` identifiers
- Multiple calls with different `data_name` values produce separate records

**Test files:**
- [backend/tests/unit/test_agent_data_service.py](../../../../backend/tests/unit/test_agent_data_service.py) — Data persistence service unit tests
- [backend/tests/unit/test_agent_save_data_tools.py](../../../../backend/tests/unit/test_agent_save_data_tools.py) — save_data LangChain tool binding and metadata handling
- [backend/tests/integration/test_system_tool_endpoints.py](../../../../backend/tests/integration/test_system_tool_endpoints.py) — Internal tool-call endpoint integration
- [e2e/tests/agent-save-data-get-tools.spec.ts](../../../../e2e/tests/agent-save-data-get-tools.spec.ts) — E2E multi-record save validation within one session

---

### 3. get_data Tool — Named Data Retrieval with Filter Guardrail

**What is tested:**
- Query filters accepted: `data_name`, `agent_type`, `session_id` (any combination)
- Results constrained by provided filters
- At least one filter required — unfiltered requests rejected with validation error
- Pagination (`limit`/`offset`) consistent between service and API layers
- Internal API routing: Agent Runtime → Control Center internal path

**Acceptance criteria:**
- Single-filter queries (`data_name` only, `agent_type` only, `session_id` only) return correctly constrained results
- Multi-filter queries (e.g., `data_name` + `agent_type` + `session_id`) satisfy all filters
- Unfiltered requests (no filter provided) return 400 with a descriptive error; no query is executed
- Batch queries with large result sets handle pagination correctly

**Test files:**
- [backend/tests/unit/test_agent_data_service.py](../../../../backend/tests/unit/test_agent_data_service.py) — Filter logic, pagination, and guardrail enforcement
- [backend/tests/unit/test_agent_save_data_tools.py](../../../../backend/tests/unit/test_agent_save_data_tools.py) — get_data LangChain tool binding and filter argument handling
- [backend/tests/integration/test_system_tool_endpoints.py](../../../../backend/tests/integration/test_system_tool_endpoints.py) — End-to-end filter validation against real database
- [e2e/tests/agent-save-data-get-tools.spec.ts](../../../../e2e/tests/agent-save-data-get-tools.spec.ts) — E2E guardrail: unfiltered request returns 400 with handled_gracefully flag

---

### 4. get_output Tool — Output History Query

**What is tested:**
- Returns `AgentOutput` records filtered by `agent_type`, `session_id`, and date range (`date_from` / `date_to`)
- Records inside the requested date window are returned; records outside are excluded
- Internal API routing: Agent Runtime → Control Center internal path

**Acceptance criteria:**
- `get_output` with `date_from` and `date_to` returns only records within the time window
- `get_output` with `agent_type` and date range returns only records matching both constraints
- Response includes the query parameters (`date_from`, `date_to`) for traceability

**Test files:**
- [backend/tests/test_query_result_tool.py](../../../../backend/tests/test_query_result_tool.py) — Query result tool backend tests
- [backend/tests/test_agent_outputs_api.py](../../../../backend/tests/test_agent_outputs_api.py) — Agent outputs API endpoint tests
- [e2e/tests/agent-save-data-get-tools.spec.ts](../../../../e2e/tests/agent-save-data-get-tools.spec.ts) — E2E date-range output history retrieval

---

### 5. Agent Outputs Query UI

**What is tested:**
- Agent Outputs page renders at `/admin/agent-outputs` without crashing
- Page is accessible (not redirected to login) for authenticated users
- Output records display with data type names and agent type names
- Validation status badges rendered (valid, validation_error)
- Filter controls visible (data type selector, agent type selector)
- Export CSV button visible and functional
- Empty state renders when no outputs match filters
- Row click opens detail view (drawer/dialog)

**Acceptance criteria:**
- Page renders without JavaScript errors
- Data type and agent type columns display human-readable names
- Validation status badges display correctly for each status value
- Empty state is shown without error when no results exist

**Test files:**
- [e2e/tests/agent-outputs-query.spec.ts](../../../../e2e/tests/agent-outputs-query.spec.ts) — Full UI coverage: rendering, filters, badges, export, empty state, detail view
- [backend/tests/test_agent_outputs_api.py](../../../../backend/tests/test_agent_outputs_api.py) — Backend API for agent outputs listing, filtering, and export

---

### 6. Regression Safety — submit_result

**What is tested:**
- Existing final output completion path (`submit_result`) remains unchanged and functional
- Agent sessions that submit final output through the existing path still succeed
- No regression in result repository or output persistence workflows

**Acceptance criteria:**
- `submit_result` tool calls complete successfully after the system tool changes
- Final outputs are persisted and retrievable through existing result repository flows

**Test files:**
- [backend/tests/integration/test_agent_session_lifecycle.py](../../../../backend/tests/integration/test_agent_session_lifecycle.py) — Session lifecycle including final output submission
- [backend/tests/integration/test_system_tool_endpoints.py](../../../../backend/tests/integration/test_system_tool_endpoints.py) — System tool endpoint integration covering both old and new tools

---

### 7. Optimized Plan Tab — Failure Visibility & Retire States

**What is tested:**
- A plan in `needs_feedback` renders its status distinctly, shows the persisted failure reason, and prompts the operator to steer the next attempt via feedback
- The failure reason is read from the plan's `error` field (already served by the API) and rendered with i18n-wrapped text
- The failure reason is persisted server-side for a failed plan, so it survives a tab reload
- A non-ready (`failed` / `needs_feedback`) plan never promotes scripts into serving artifacts
- Retire with nothing active (plan already `retired`) shows a clear "nothing to retire" state and disables the retire action — no request is issued
- Retire invalidates the whole agent-type query scope so the launch/Run Agent action re-gates immediately (cache-refresh regression, no page reload)

**Acceptance criteria:**
- `needs_feedback` shows both the status and the human-readable failure reason; the steer prompt is present
- Empty / very long / unicode reasons render safely (no crash, no layout break)
- Retire on an already-retired plan issues no API call and the retire control is disabled
- After a successful retire, dependent queries refresh without a manual reload

**Test files:**
- [backend/tests/test_optimized_plan.py](../../../../backend/tests/test_optimized_plan.py) — non-ready plan promotes no scripts; `error` persisted on a failed plan (`mark_failed`); self-reflection read surfaces (`get_scripts`, `get_execution_log`, `get_optimized_implementation_plan`); retire endpoint marks rows retired without deleting and stops serving
- [frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx](../../../../frontend/src/__tests__/AgentOptimizedPlanTab.test.tsx) — `needs_feedback` status + failure reason + steer prompt; "nothing to retire" state with retire disabled and no request; retire query-scope invalidation

**Notes:**
- Mandatory self-reflection ordering (`get_scripts` → `get_execution_log` → `get_optimized_implementation_plan` before authoring, skip-when-healthy) is enforced in the optimization mission prompt; the three read surfaces each have backend coverage, but the literal ordering is not asserted by a test.
- The "nothing to retire" empty state is component-level only — the Optimized Plan tab lives inside a nested agent-type dialog flow, so there is no dedicated E2E spec.
- Semantic tool-error detection and the fallback/repair/re-optimization reactions were deferred by product decision; no test claims them.

---

## Edge Cases & Risks

- **Unbounded query risk**: Missing `get_data` filter guard may trigger full-table scans — validated by guardrail tests
- **Naming regression risk**: Legacy `save_result` references persisting in tool allowlists, schemas, or seeded defaults — validated by context/schema tests
- **Contract drift risk**: LangChain tool args or internal API params not matching between layers — validated by integration tests
- **Date filtering risk**: Timezone boundary mismatches in `get_output` date range — validated by query tests
- **Pagination risk**: `limit`/`offset` inconsistency between service and API layers — validated by data service unit tests
- **Metadata integrity risk**: `agent_type` or `session_id` null unexpectedly in stored records — validated by unit tests
- **Security risk**: Internal endpoints must remain certificate-protected — validated by segregation audit tests
- **Architecture risk**: Agent Runtime must not access database directly — validated by segregation audit tests

---

## Architecture Compliance

All three tools (`save_data`, `get_data`, `get_output`) use the **Agent Runtime → Control Center internal API → PostgreSQL** path, preserving the top-priority service segregation rule that only Control Center connects to the database. Agent Runtime never holds database credentials.

---

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| agent-save-data-get-tools | System tools for intermediate data persistence, named data retrieval, and output history query; legacy save_result removal; Agent Outputs Query UI | 2026-07-03 |
| sandboxed-scripting-follow-ups | Optimized Plan tab failure visibility (`error` on `needs_feedback`), "nothing to retire" empty state, retire cache-refresh regression, mandatory self-reflection ordering (prompt-enforced) | 2026-11-03 |
