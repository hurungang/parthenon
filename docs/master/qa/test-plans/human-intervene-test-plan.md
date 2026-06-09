# Test Plan — Human Intervene (Agent-Driven Human-in-the-Loop)

## 1. Test Strategy

### Unit Testing (Backend Services)
Test each service component in isolation with mocked dependencies. Focus on business logic correctness, state transitions, and error handling.

- **`InterveneRequestStore`**: validate CRUD operations, status transition rules (`pending→responded`, `pending→cancelled`, `pending→expired`), duplicate prevention (same session cannot have two `pending` requests), metrics aggregation (pending count, avg response time, resolution rate), and expiry logic.
- **`AgentRuntimeExecutor._handle_human_intervene`**: validate context snapshot serialization (messages, iteration count, tool results), loop suspension with no further LLM/tool calls, and resume flow where response value is injected as tool result.
- **`ControlCenterDataClient`**: validate `mark_session_waiting_for_human` and `create_intervene_request` internal API calls with correct payloads and mTLS headers.
- **Tool registration**: validate `_HUMAN_INTERVENE_TOOL_DEF` structure follows the same pattern as `system____save_result` and is registered in `SYSTEM_TOOL_NAMES`.
- **Notification triggers**: validate `intervene_request_created` and `intervene_request_responded` events are emitted and formatted correctly for all configured channels.
- **Permission validation**: validate `intervene:view` and `intervene:respond` permission checks at service layer.

### Integration Testing (Backend API + Real Database)
Test the full request path: router → service → repository → PostgreSQL. All integration tests must use a real PostgreSQL database with migrations applied.

- **Database migration verification**: integration test setup must run `alembic upgrade head` and confirm the new `intervene_requests` and `intervene_responses` tables exist along with the `waiting_for_human` enum value in `AgentJobStatus`.
- **CRUD lifecycle**: create intervene request → respond → verify response persisted → cancel pending request → verify expired status.
- **State machine integrity**: verify allowed state transitions (`running→waiting_for_human→running`, `running→waiting_for_human→terminated`, `running→waiting_for_human→failed`) and rejected transitions (e.g., `completed→waiting_for_human`).
- **Authorization enforcement**: requests without JWT, without `intervene:view`, or without `intervene:respond` must be rejected with 401/403.
- **Constraint validation**: duplicate `human_intervene` call for same session while `pending` returns existing request ID (not 500); respond to resolved request returns 409; API rejects invalid intervention type payloads (choice without `choices` list, text without prompt, etc.).
- **Internal API mTLS enforcement**: internal endpoints reject non-mTLS requests.

### E2E Testing (Playwright + Real Backend)
Validate complete user flows through the browser. At least one test suite must hit the real backend without mocks.

- **Intervene request list view**: operator views pending requests sorted by timestamp with correct agent name, reason, type, and elapsed wait time.
- **Approval response flow**: operator approves a request → agent state transitions from `waiting_for_human` back to `running` → tool returns `approved: true`.
- **Choice response flow**: operator selects an option → agent resumes with selected value.
- **Text response flow**: operator enters free-form text → agent resumes with text value.
- **Cancel flow**: operator cancels a pending request → status becomes `cancelled`.
- **Navigation badge**: pending count indicator visible and accurate in navigation.
- **Dashboard filter**: `waiting_for_human` appears as a filterable status in the execution dashboard.
- **Real backend integration variant**: labelled `test.describe('Real Backend Integration - Human Intervene')`, no `page.route()` mocks, runs against the live application stack.

### Manual Testing (Human Verification Required)
Some scenarios cannot be fully automated:

- Live notification delivery through email, Slack, Teams, or webhook when a new intervene request is created.
- Agent execution resume observed in real-time via the execution log stream.
- Cross-service resume signal propagation (Agent Runtime → Communication Hub → Control Center → back) verified by operators with access to service logs.

---

## 2. Coverage Areas

### Intervene Request Creation (Tool)
The `system____human_intervene` tool is the entry point for the entire feature. Agents must be able to call it with correct parameters and the execution must pause immediately.

- Agent calls `human_intervene` with `reason`, `intervention_type`, and type-specific parameters (`choices` for choice, `prompt` for text)
- Agent execution pauses and transitions to `waiting_for_human` state
- Tool call returns a unique intervene request ID
- Request persisted and immediately visible in the UI with full context
- Duplicate `human_intervene` call from same session while pending returns existing request ID (not 500, not duplicate)
- Tool definition registered in `SYSTEM_TOOL_NAMES` and follows `system____human_intervene` naming convention

### Approval Response Type
The yes/no approval flow is the simplest pattern and the most likely compliance use case.

- Operator views approval request with agent's reason
- Approve action: request transitions to `responded`, approval_value = true, agent resumes with `approved: true`
- Reject action: request transitions to `responded`, approval_value = false, agent resumes with `approved: false`
- UI displays clear Yes/No button pair
- Cannot submit without making a selection

### Choice Response Type
Choice requests enable guided decision-support scenarios where agents present options.

- Operator views choice request with agent's question and available options
- Exactly one option selectable from the provided list
- After selection, request transitions to `responded`, selected_choice = chosen value
- Agent resumes with the selected option value
- UI prevents submission if no option is selected
- `choices` list persisted correctly on the `InterveneRequest` record

### Text Response Type
Text requests handle cases where agents need contextual information only a human can provide.

- Operator views text request with agent's prompt for information
- Free-form text area with character count display
- Configurable maximum character limit enforced
- After submission, request transitions to `responded`, text_value = operator input
- Agent resumes with the text value
- Empty text values rejected (minimum input validation)

### Execution State Machine
The `waiting_for_human` state is a new `AgentJobStatus` enum value. State transitions must be enforced at the database level and via service logic.

- `running` → `waiting_for_human`: only allowed when agent calls `human_intervene`
- `waiting_for_human` → `running`: only allowed when operator responds
- `waiting_for_human` → `terminated`: operator terminates the waiting session
- `waiting_for_human` → `failed`: system error during resume
- `completed`/`failed`/`terminated` → `waiting_for_human`: must be rejected
- Multiple concurrent `pending` requests per session: not permitted (duplicate returns existing ID)
- When session transitions from `waiting_for_human` to `terminated`, all `pending` intervene requests for that session are auto-marked `cancelled`

### API Authentication and Authorization
All endpoints require valid authentication and the correct permission scope.

- Unauthenticated requests to `/api/v1/intervene/*` return 401
- Authenticated users without `intervene:view` permission return 403 on list/detail endpoints
- Authenticated users without `intervene:respond` permission return 403 on respond/cancel endpoints
- Internal endpoints (`/api/v1/internal/data/intervene/*`) require mTLS (service cert), reject JWT and agent-instance certs
- Agent Runtime `/resume` endpoint requires mTLS (agent-instance cert)

### Frontend UI — Request List and Navigation
The UI must display pending requests clearly and enable quick triage.

- `InterveneRequestList` displays pending requests with agent name, execution ID, request reason, intervention type, timestamp, and elapsed wait time
- Navigation badge shows pending count, updates automatically without page reload
- Dashboard filter includes `waiting_for_human` status alongside existing values
- Completed/cancelled requests visible in history with resolution details
- Loading states displayed during async operations
- All UI text goes through `t()` (i18next)

### Frontend UI — Response Dialogs
Three type-specific dialogs following the project's Dialog Error Handling Standard.

- All dialogs display errors inline (`PermissionDeniedAlert`) per Dialog Error Handling Standard
- Dialog errors cleared on open/close
- Approval dialog: Yes/No button pair, agent reason displayed, execution context visible
- Choice dialog: selectable option cards or radio buttons, agent question displayed
- Text dialog: text area with character count, agent prompt displayed, max length enforced
- After response, UI shows confirmation that response was delivered and agent is resuming
- `dialogError` state managed via `useDialogErrorHandler` hook pattern

### Execution Context Display
Operators need context about what the agent was doing to make informed decisions.

- Response dialogs show execution context: what the agent was doing, recent tool calls, current output
- Agent session page (`AgentJobPage`) shows inline intervene request history
- Audit log visible in execution details view for each agent run
- Context snapshot includes messages, iteration count, and tool results

### Notifications
New intervene request events must trigger notifications through the existing notification system.

- `intervene_request_created` notification trigger registered and dispatchable through all channels
- `intervene_request_responded` notification trigger registered and dispatchable through all channels
- In-app notification generated on request creation
- Notification body includes reason, agent name, and execution link
- Responded notification includes response value and operator name

### Audit and Compliance
Every intervene action must be fully auditable.

- Every intervene request logged with: request ID, agent ID, execution ID, intervention type, request timestamp, reason/prompt
- Every response logged with: operator user ID, response value, response timestamp
- Cancelled and expired requests recorded with timestamp and outcome
- Audit log accessible to authorized users (platform admins, auditors)
- OTEL spans emitted for create, respond, cancel, and expire operations

### Error Handling and Timeouts
The system must handle all failure modes gracefully without crashing or data corruption.

- Request timeout (expiry) automatically transitions `pending` → `expired` after configured duration
- Responding to an already-resolved request returns 409 Conflict with clear error message
- Responding to a cancelled/expired request shows clear error message
- Terminating a `waiting_for_human` session auto-cancels all pending requests for that session
- Operator without `intervene:respond` permission sees `PermissionDeniedAlert` in dialog
- Backend validation rejects malformed tool call parameters (missing `reason`, invalid `intervention_type`, no `choices` for choice type, negative timeout values)
- Agent execution termination while waiting marks the request stale/cancelled

---

## 3. Critical Scenarios

### Request Creation through Agent Tool Call

**WHEN** an agent calls `system____human_intervene` with a reason, `intervention_type=approval`, and type-specific parameters during its observe-reason-act loop  
**THEN** the execution pauses, the session transitions to `waiting_for_human` state, and an `InterveneRequest` record with `status=pending` is persisted and visible in the UI

**WHEN** an agent calls `system____human_intervene` with `intervention_type=choice` and a `choices` list containing three options  
**THEN** the execution pauses and the request appears in the UI with all three options displayed as selectable choices

**WHEN** an agent calls `system____human_intervene` with `intervention_type=text` and a prompt asking for contextual information  
**THEN** the execution pauses and the request appears in the UI with a text area and the agent's prompt displayed

**WHEN** an agent calls `human_intervene` while a `pending` request already exists for the same session  
**THEN** the tool returns the existing request ID instead of creating a duplicate, and no new `InterveneRequest` record is created

### Approval Response

**WHEN** an operator with `intervene:respond` permission clicks "Approve" on a pending approval-type request  
**THEN** the request transitions to `responded`, `approval_value=true` is persisted, the agent execution resumes, and the tool returns `approved: true` to the agent

**WHEN** an operator clicks "Reject" on a pending approval-type request  
**THEN** the request transitions to `responded`, `approval_value=false` is persisted, the agent execution resumes, and the tool returns `approved: false` to the agent

### Choice Response

**WHEN** an operator selects exactly one option from the choices list on a pending choice-type request  
**THEN** the request transitions to `responded`, `selected_choice` is set to the chosen option, the agent resumes, and the tool returns the selected value

**WHEN** an operator attempts to submit a choice-type response without selecting an option  
**THEN** the UI prevents submission and shows a validation message

### Text Response

**WHEN** an operator enters free-form text within the character limit on a pending text-type request  
**THEN** the request transitions to `responded`, `text_value` is set to the operator's input, the agent resumes, and the tool returns the text value

**WHEN** an operator attempts to submit a text response exceeding the configured maximum character limit  
**THEN** the UI shows a character count error and prevents submission

### Execution Lifecycle and State Management

**WHEN** an operator terminates an agent session while it is in `waiting_for_human` state  
**THEN** all pending intervene requests for that session are automatically marked `cancelled`, the session transitions to `terminated`, and the cancelled requests are visible in the audit history

**WHEN** a pending intervene request reaches its configured timeout without an operator response  
**THEN** the request status transitions to `expired`, the session remains in `waiting_for_human` state, and an escalation notification is dispatched if configured

**WHEN** an operator tries to respond to an `InterveneRequest` that has already been responded to or cancelled  
**THEN** the API returns 409 Conflict and the response is not applied

### UI — Request List and Navigation

**WHEN** an operator navigates to the agent execution dashboard  
**THEN** executions with `status=waiting_for_human` are visible and filterable, and the navigation shows a pending count badge

**WHEN** a new intervene request is created  
**THEN** the pending count badge increments automatically and the request appears in the request list without a page reload

**WHEN** an operator responds to a pending request  
**THEN** the request is removed from the pending list, the navigation badge decrements, and the execution resumes without manual intervention

### Authorization

**WHEN** an unauthenticated request is made to `GET /api/v1/intervene/requests`  
**THEN** the API returns 401 Unauthorized

**WHEN** an authenticated user without `intervene:view` permission calls `GET /api/v1/intervene/requests`  
**THEN** the API returns 403 Forbidden

**WHEN** an authenticated user without `intervene:respond` permission clicks the respond button on a request  
**THEN** the dialog shows a `PermissionDeniedAlert` inline and does not allow submission

**WHEN** a request is made to an internal endpoint (`/api/v1/internal/data/intervene/requests`) without mTLS  
**THEN** the API returns 401 or 403 and the request is not created

### Metrics Endpoint

**WHEN** an operator accesses the dashboard and the UI calls `GET /api/v1/intervene/metrics`  
**THEN** the API returns `pending_count`, `avg_response_time_seconds`, and `resolution_rate` reflecting the current state of all intervene requests

---

## 4. Edge Cases & Risks

### Concurrent Operations
- Two operators attempt to respond to the same intervene request simultaneously — only the first should succeed (responded), the second should receive 409 Conflict
- Agent calls `human_intervene` while an operator is about to respond to an existing pending request for the same session — request is not duplicated, existing request ID returned
- High-frequency `human_intervene` calls across many agents simultaneously — metrics endpoint must handle concurrent reads without locking

### Timeout and Expiry
- Request timeout fires while an operator has the response dialog open — operator attempts to respond to an expired request should return 409
- Timeout value set to zero or negative — must be rejected at API validation level
- Very short timeout (e.g., 1 second) — expiry logic must handle rapid state transitions cleanly
- Agent session terminated while timeout is about to fire — both cancelled and expired states must not conflict (cancelled takes precedence if both occur near-simultaneously)

### State Machine Violations
- Attempting to transition `completed` session to `waiting_for_human` — must be rejected at service layer
- Attempting to transition `waiting_for_human` to `waiting_for_human` again — rejected, existing request ID returned
- Attempting to respond to a request whose session is no longer in `waiting_for_human` state (e.g., operator responded but session was separately terminated) — returns clear error, response still persisted for audit
- Orphaned `pending` requests for sessions that no longer exist — must be handled gracefully (return empty session details or null FK reference)

### Data Integrity
- `InterveneResponse` created without a corresponding `InterveneRequest` — FK constraint prevents this
- `InterveneRequest.choices` is null for `approval` and `text` types — validation must reject any code path that assumes choices is always populated
- `InterveneRequest.agent_session_id` references a deleted/non-existent session — FK constraint enforces referential integrity
- `InterveneResponse.operator_user_id` must reference a valid `Identity` record — FK constraint required
- Multiple `InterveneResponse` records for a single `InterveneRequest` — business rule mandates 1:0..1 relationship; unique constraint or service-level check required

### Edge Cases — Intervention Types
- `choices` list contains only one option — valid, but edge case worth testing
- `choices` list contains duplicate option strings — system should not deduplicate (options array is presented as-is)
- `choices` list contains options with special characters, HTML, or very long strings — must be stored and displayed without encoding issues
- `text` response with only whitespace — should be rejected as empty; empty string should be rejected (minimum non-whitespace length > 0)
- `text` response equal to maximum character limit exactly — should be accepted (boundary value)
- `approval` request keyed in by agent without a `reason` — `reason` field is required; API validation must reject missing reason

### Authorization Edge Cases
- User with `intervene:view` but not `intervene:respond` can see request details but respond button is disabled/hidden
- User with `intervene:respond` on one resource but not another — permission is global per current spec, not resource-scoped
- Agent Runtime calling internal endpoints with agent-instance cert instead of service cert — must be rejected per service segregation rules
- Deleted user who previously responded to requests — operator_user_id FK must handle this (consider ON DELETE SET NULL or soft delete)

### UI Responsiveness
- No pending requests: navigation badge shows zero or is hidden
- Hundreds of pending requests: list pagination works, badge shows three-digit count correctly
- Request list updates while operator is reading details — avoid UI flicker or data inconsistency via stable request IDs
- Dialog open while stale request becomes resolved — close dialog gracefully or show "request already resolved" message

### Service Segregation
- Agent Runtime must not have direct database access — all persistence goes through Control Center internal API
- Communication Hub must correctly route `system____human_intervene` tool calls to Control Center (not MCP dispatch)
- Communication Hub must relay response signals from Web UI → Control Center → Agent Runtime correctly
- mTLS certificate validation must be enforced at each service boundary per existing service segregation rules

---

## 5. Acceptance Criteria Checklist

| PRD Acceptance Criterion | Test Coverage |
|---|---|
| Agents can call `human_intervene` with reason, intervention type, and type-specific parameters | Unit: tool registration and parameter validation; Integration: full API call with real database |
| When agent calls `human_intervene`, execution pauses immediately and transitions to "Waiting for Human Intervention" state | Integration: session state transition verified in database; E2E: UI shows `waiting_for_human` status |
| Tool call returns a unique intervene request ID to the agent | Integration: verify `POST /api/v1/internal/data/intervene/requests` returns ID |
| Request persisted and immediately visible in UI with full context | E2E: create request via API, verify it appears in UI request list without page reload |
| Approvers can view all open "approval" type requests with agent's reason | E2E: pending approval requests displayed in `InterveneRequestList` with correct data |
| Approvers can approve or reject request with single click | E2E: click Approve/Reject → request resolved, badge updates, agent resumes |
| After approval, agent resumes and tool returns `approved: true` | Integration: response submitted → session status `running` → tool return value verified |
| After rejection, agent resumes and tool returns `approved: false` | Integration: same pattern as approval with rejection |
| Approvers can view choice-type requests with question and options | E2E: choice request displays all options as selectable cards |
| Approvers can select exactly one option from choices | E2E: select option → submit → request resolved |
| UI prevents submission if no option is selected | Component: submit button disabled when no selection |
| Approvers can view text-type requests with agent's prompt | E2E: text request shows prompt and text area |
| Approvers can enter free-form text as response | E2E: type text → submit → request resolved |
| UI enforces configurable maximum character limit on text responses | Component: character count displayed; API: 422 on exceeded limit |
| Agent execution enters `waiting_for_human` state distinguishable from other states | Integration: `information_schema` confirms enum value exists; E2E: status filter includes `waiting_for_human` |
| Agent session remains active but paused — no further LLM/tool calls | Integration: execution loop exits; no MCP dispatch for waiting session |
| When human responds, execution auto-resumes without manual restart | E2E (real backend): create request → respond → verify session status transitions back to `running` |
| If agent execution terminated while waiting, pending requests auto-cancelled | Integration: terminate session → verify all `pending` requests for that session are `cancelled` |
| Dashboard shows filterable view of executions waiting for human intervention | E2E: status filter dropdown includes `waiting_for_human` option |
| Pending requests displayed with agent name, execution ID, reason, type, timestamp, elapsed time | E2E: request list cards contain all fields with correct values |
| Pending count visible as badge/indicator in navigation | E2E: badge shows correct number on page load and updates after respond/cancel |
| Completed/cancelled requests visible in history with resolution | E2E: resolved requests visible in request history view |
| Approval response UI shows agent reason and Yes/No buttons | Component: dialog renders with reason text and two buttons |
| Choice response UI shows agent question and selectable options | Component: dialog renders with question and radio/option cards |
| Text response UI shows agent prompt and text area with character count | Component: dialog renders with prompt, text area, and character counter |
| After responding, UI confirms response delivered and agent resuming | Component: success state shown after submission; E2E: session resumes |
| Response UIs show execution context (what agent was doing, recent tool calls, current output) | Component: context section populated in dialog |
| In-app notification generated on new intervene request | Integration: notification trigger fired on request creation; E2E: notification appears in-app |
| Notification dispatched through configured channels | Integration: notification service called with correct trigger type; Manual: verify live channel delivery |
| Every intervene request logged with full audit trail | Integration: audit fields populated correctly in database |
| Audit log visible in execution details view | E2E: intervene request history section visible on AgentJobPage |
| Audit log accessible to authorized users (admins, auditors) | Integration: 403 for unauthorized users; 200 for authorized |
| Configurable timeout with escalation or termination | Integration: expiry logic transitions pending→expired after timeout |
| Permission-denied messages shown in UI for unauthorized operators | Component: `PermissionDeniedAlert` displayed in dialog; E2E: button disabled or error shown |
| Responding to stale/terminated request shows clear error | Integration: 409 on respond to already-resolved request |
| System rejects duplicate requests from same execution point | Integration: duplicate call returns existing request ID (same ID, not 500) |

---

## 6. Database Migration Requirements (CRITICAL)

Backend integration tests **must** satisfy the following requirements because this change introduces new tables (`intervene_requests`, `intervene_responses`) and a new enum value (`waiting_for_human`):

### Pre-Test Checklist
- Verify migration was applied: `python -m alembic current` shows the expected migration revision ID
- If not applied: `python -m alembic upgrade head` before running any tests
- Test database must match production schema — use the same Alembic migration chain

### Schema Verification Tests (information_schema)
At least one integration test must query `information_schema` to confirm:

- `intervene_requests` table exists with columns: `id` (uuid), `agent_session_id` (uuid), `agent_type_id` (uuid), `intervention_type` (enum or text), `reason` (text), `choices` (nullable json), `status` (enum or text), `created_at` (timestamptz), `responded_at` (nullable timestamptz), `expires_at` (nullable timestamptz)
- `intervene_responses` table exists with columns: `id` (uuid), `request_id` (uuid), `operator_user_id` (uuid), `approval_value` (nullable boolean), `selected_choice` (nullable text), `text_value` (nullable text), `responded_at` (timestamptz)
- `AgentJobStatus` enum includes `waiting_for_human` value
- Foreign key: `intervene_requests.agent_session_id` references `agent_jobs.id`
- Foreign key: `intervene_requests.agent_type_id` references `agent_types.id`
- Foreign key: `intervene_responses.request_id` references `intervene_requests.id`
- Foreign key: `intervene_responses.operator_user_id` references `identities.id`

### Constraint Violation Tests
- Attempt to insert a duplicate `InterveneResponse` for the same `request_id` — must raise a unique constraint violation (or service layer must enforce 1:1)
- Attempt to create an `InterveneRequest` with `intervention_type=choice` and `choices=null` — must be rejected at API validation (not caught by DB; service layer enforcement)
- Attempt to insert an `InterveneRequest` with a non-existent `agent_session_id` — must raise FK violation
- Attempt to transition a session from `completed` to `waiting_for_human` — must be rejected by service layer state machine (not by DB constraint alone)
- Attempt to respond to a `cancelled` or `expired` request — must be rejected at service layer; API returns 409

---

## 7. E2E Real Backend Requirements (CRITICAL)

At least one E2E test suite must run against the real backend stack with **no `page.route()` mocks**. This catches migration issues, enum type registration failures, and integration bugs that mocked tests cannot detect.

- **Label**: `test.describe('Real Backend Integration - Human Intervene')`
- **What it must cover**:
  - Verify backend health endpoint is reachable
  - Create an intervene request via `POST /api/v1/internal/data/intervene/requests` (internal endpoint, requires mTLS or bypass for test) — or via the full tool call path through Control Center
  - Verify the request appears in `GET /api/v1/intervene/requests` with `status=pending`
  - Submit a response via `POST /api/v1/intervene/requests/{id}/respond` with a valid response payload
  - Verify the request transitions to `responded` and `InterveneResponse` is persisted
  - Cancel a second pending request via `POST /api/v1/intervene/requests/{id}/cancel`
  - Verify `GET /api/v1/intervene/metrics` returns accurate counts
  - Clean up test data (delete created intervene requests and responses if the API supports it, or leave for TTL-based cleanup)
- **Why**: Mocked E2E tests would pass even if migrations were not applied, the `waiting_for_human` enum value was not registered, or the internal API router was misconfigured

---

## 8. Test File References

| Test Layer | File Path |
|---|---|
| Backend unit — `InterveneRequestStore` service | [backend/tests/services/test_intervene_service.py](../../../backend/tests/services/test_intervene_service.py) |
| Backend integration — Intervene API endpoints | [backend/tests/api/v1/test_intervene.py](../../../backend/tests/api/v1/test_intervene.py) |
| Backend integration — Schema migration verification | [backend/tests/api/v1/test_intervene.py](../../../backend/tests/api/v1/test_intervene.py) |
| Frontend component — Response dialogs (approval, choice, text) | [frontend/src/__tests__/components/test_InterveneResponseDialog.tsx](../../../frontend/src/__tests__/components/test_InterveneResponseDialog.tsx) |
| Frontend component — Request list | [frontend/src/__tests__/components/test_InterveneRequestList.tsx](../../../frontend/src/__tests__/components/test_InterveneRequestList.tsx) |
| E2E — Full human-in-the-loop flows | [e2e/tests/intervene.spec.ts](../../../e2e/tests/intervene.spec.ts) |
| E2E — Real backend integration (no mocks) | [e2e/tests/intervene.spec.ts](../../../e2e/tests/intervene.spec.ts) (as `describe` block within the same file or a separate suite) |
