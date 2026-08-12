# Implementation Plan: Add Human Intervene

## Overview

This change adds a `system____human_intervene` system tool that enables agents to suspend execution and request human input (approval, choice selection, or free-form text) during the observe-reason-act loop. The implementation spans all four backend services — Control Center (persistence + API), Agent Runtime (suspend/resume loop), Communication Hub (tool routing + control messages) — plus the Web UI (dashboard filters, response dialogs, notification badges) and the existing notification integration system.

## Task Checklist

### Phase 1 — Backend Model + Migration
- [x] 1.1 — Define new enums (`InterveneRequestStatus`, `InterventionType`) — _Done when: enums defined in `intervene.py` with all required values (`pending`, `responded`, `cancelled`, `expired`; `approval`, `choice`, `text`)_
- [x] 1.2 — Create `InterveneRequest` SQLAlchemy model — _Done when: model defined with all fields from data-model.md (id, agent_session_id, agent_type_id, intervention_type, reason, choices, status, created_at, responded_at, expires_at) plus UUID FK to agent_jobs_
- [x] 1.3 — Create `InterveneResponse` SQLAlchemy model — _Done when: model defined with all fields from data-model.md (id, request_id, operator_user_id, approval_value, selected_choice, text_value, responded_at)_
- [x] 1.4 — Extend `AgentJobStatus` enum with `waiting_for_human` — _Done when: new value added, state machine rules documented in class docstring_
- [x] 1.5 — Add `intervene_requests` relationship to `AgentJob` — _Done when: one-to-many relationship added, cascade rules set_
- [x] 1.6 — Register new models in `backend/app/db/models/__init__.py` — _Done when: `InterveneRequest` and `InterveneResponse` imported for Alembic autogenerate detection_
- [x] 1.7 — Generate Alembic migration — _Done when: `alembic revision --autogenerate` produces a migration creating the two tables, altering the agent_job_status_enum, and adding the FK constraint_
- [x] 1.8 — Create Pydantic request/response schemas — _Done when: `InterveneRequestCreate`, `InterveneRequestRead`, `InterveneResponseSubmit`, `InterveneResponseRead`, and `InterveneMetrics` schemas defined in `backend/app/schemas/agents.py` or new `intervene.py`_

### Phase 2 — Backend API Endpoints
- [x] 2.1 — Create `InterveneRequestStore` service class — _Done when: service with methods `create_request`, `get_request`, `list_requests` (filterable by status/type/agent_session_id), `submit_response`, `cancel_request`, `get_metrics` exists in `backend/app/services/agents/`_
- [x] 2.2 — Create API router for `/api/v1/intervene/*` endpoints — _Done when: router with GET list, GET detail, POST respond, POST cancel, GET metrics endpoints registered on Control Center_
- [x] 2.3 — Register intervene router in main FastAPI app — _Done when: `InterveneRouter` included in `backend/app/main.py` or top-level API router_
- [x] 2.4 — Implement permission checks on respond/cancel endpoints — _Done when: `intervene:respond` permission checked on POST respond and POST cancel; list/detail require `intervene:view` or equivalent_

### Phase 3 — Agent Runtime Changes
- [x] 3.1 — Define `human_intervene` system tool definition (`_HUMAN_INTERVENE_TOOL_DEF`) — _Done when: tool definition dict with parameters (reason, intervention_type, choices optional, prompt optional) follows the same pattern as `_SAVE_RESULT_TOOL_DEF` in `runtime_executor.py`_
- [x] 3.2 — Register `human_intervene` in `system_tools.py` — _Done when: `human_intervene` added to `SYSTEM_TOOL_NAMES` frozenset and canonical name helpers resolve it correctly_
- [x] 3.3 — Implement tool handler in Agent Runtime to intercept `human_intervene` calls — _Done when: tool handler snapshots execution context, sends suspend request to Communication Hub, and returns the pending request ID to the calling loop_
- [x] 3.4 — Implement suspend logic in the LangChain observe-reason-act loop — _Done when: when `human_intervene` is called, the loop pauses after persisting context; no further LLM or tool calls execute; state set to `waiting_for_human`_
- [x] 3.5 — Create resume dispatcher endpoint in Agent Runtime API — _Done when: new `POST /resume` endpoint accepts an intervene response (request_id + response value), restores context, and re-enters the loop_
- [x] 3.6 — Update `_run_task_loop_ar` to handle `human_intervene` tool call — _Done when: the task loop recognises `human_intervene` in tool results, transitions to suspend state, and can resume via the resume endpoint_
- [x] 3.7 — Handle stale request cleanup on session termination — _Done when: when a `waiting_for_human` session is terminated, all pending intervene requests are automatically marked `cancelled`_

### Phase 4 — Communication Hub Changes
- [x] 4.1 — Add `human_intervene` to the tool routing table — _Done when: Communication Hub recognises `system____human_intervene` and forwards tool calls to Control Center for persistence_
- [x] 4.2 — Add `intervene_response` control message relay — _Done when: Web UI → Communication Hub → Control Center relay established for POST respond; Control Center → Communication Hub → Agent Runtime relay established for resume signals_
- [x] 4.3 — Add notification trigger for `intervene_request_created` — _Done when: Communication Hub emits an event when a new intervene request is persisted, routed to the Notification Integration system_

### Phase 5 — Frontend Changes
- [x] 5.1 — Add TypeScript types for intervene request/response — _Done when: `InterveneRequest`, `InterveneResponse`, `InterveneRequestStatus`, `InterventionType` types defined in `frontend/src/types/index.ts`_
- [x] 5.2 — Create API client functions for intervene endpoints — _Done when: `getInterveneRequests`, `getInterveneRequest`, `submitInterveneResponse`, `cancelInterveneRequest`, `getInterveneMetrics` functions in `frontend/src/api/`_
- [x] 5.3 — Create React hook for intervene request state management — _Done when: `useInterveneRequests` hook provides `pendingRequests`, `submitResponse`, `cancelRequest`, `metrics`, `isLoading` with real-time polling or WebSocket updates_
- [x] 5.4 — Create response dialog components — _Done when: three dialog variants (ApprovalDialog with Yes/No buttons, ChoiceDialog with selectable cards/radios, TextDialog with text area + character count) follow the dialog error handling standard from conventions_
- [x] 5.5 — Create pending intervene request list component — _Done when: component displays pending requests with agent name, execution ID, reason, intervention type, timestamp, and elapsed wait time; links to execution detail_
- [x] 5.6 — Add `waiting_for_human` filter to agent execution dashboard — _Done when: dashboard status filter includes `waiting_for_human` option alongside running/completed/failed/terminated_
- [x] 5.7 — Add pending intervene count badge to navigation — _Done when: a badge or indicator in the nav shows the count of pending intervene requests, updating in real time_
- [x] 5.8 — Add intervene requests section to execution detail view — _Done when: `AgentJobPage` or execution detail includes inline section showing pending and resolved intervene requests with response audit trail_
- [x] 5.9 — Add i18n translation keys — _Done when: all new UI strings have corresponding entries in the project's i18n locale files_

### Phase 6 — Notifications Integration
- [x] 6.1 — Add `intervene_request_created` and `intervene_request_responded` as notification trigger types — _Done when: new trigger types registered in the notification integration system, dispatchable through configured channels_
- [x] 6.2 — Wire up notification dispatch from Control Center on intervene lifecycle events — _Done when: Control Center emits `intervene_request_created` and `intervene_request_responded` events that are consumed by the notification service_
- [x] 6.3 — Add OpenTelemetry events for intervene request lifecycle — _Done when: OTEL spans and events emitted for `intervene.created`, `intervene.responded`, `intervene.cancelled`, `intervene.expired` with relevant attributes_

### Phase 7 — Testing and Verification
- [x] 7.1 — Write backend unit tests for `InterveneRequestStore` — _Done when: tests cover create, get, list, respond, cancel, metrics operations with mocked DB session_
- [x] 7.2 — Write backend integration tests for API endpoints — _Done when: tests cover all intervene endpoints with real DB, including permission checks, duplicate rejection, stale request handling, and error cases_
- [ ] 7.3 — Write frontend component tests for response dialogs — _Done when: tests verify each dialog variant renders correctly, validates input, handles API errors, and shows success confirmation_
- [ ] 7.4 — Write E2E tests for the human-in-the-loop flow — _Done when: E2E test creates an agent execution, triggers intervene request via the tool, responds via UI, and verifies the agent resumes with the response value_
- [x] 7.5 — Run full test suite and fix regressions — _Done when: `pytest backend/tests/` and `npx vitest run` pass with no failures or regressions_

---

## Phase 1 — Backend Model + Migration

### Task 1.1 — Define new enums

Create `InterveneRequestStatus` enum with values `pending`, `responded`, `cancelled`, `expired` and `InterventionType` enum with values `approval`, `choice`, `text` in the new `backend/app/db/models/intervene.py` file. Follow the existing pattern from `agents.py` where enums inherit `str, enum.Enum` and have descriptive docstrings.

**Done when:** enums defined, importable, and all values match the data model specification.

### Task 1.2 — Create `InterveneRequest` model

Define the `InterveneRequest` SQLAlchemy model in `backend/app/db/models/intervene.py` with:
- `id`: UUID primary key
- `agent_session_id`: FK to `agent_jobs.id`, not nullable
- `agent_type_id`: FK to `agent_types.id`, not nullable
- `intervention_type`: Enum `InterventionType`, not nullable
- `reason`: Text field, not nullable
- `choices`: JSON field, nullable (only for `choice` type)
- `status`: Enum `InterveneRequestStatus`, default `pending`
- `created_at`, `responded_at`, `expires_at`: DateTime with timezone
- Relationships: `agent_session` back to `AgentJob`, `response` 1:0..1 to `InterveneResponse`

**Done when:** model defined with all columns, FKs, and relationships; no migration yet.

### Task 1.3 — Create `InterveneResponse` model

Define `InterveneResponse` with:
- `id`: UUID primary key
- `request_id`: FK to `intervene_requests.id`, unique (enforces 1:1), not nullable
- `operator_user_id`: FK to `identities.id`, not nullable
- `approval_value`: Boolean, nullable
- `selected_choice`: String, nullable
- `text_value`: Text, nullable
- `responded_at`: DateTime with timezone, not nullable
- Relationship back to `InterveneRequest`

**Done when:** model defined with all columns and FKs; business rule that exactly one response field is populated per intervention type is enforced at the application layer (not DB constraint).

### Task 1.4 — Extend `AgentJobStatus` enum

Add `waiting_for_human = "waiting_for_human"` to the `AgentJobStatus` enum in `backend/app/db/models/agents.py`. Update the class docstring to document the new state and its allowed transitions (from `running`, to `running`/`terminated`/`failed`).

**Done when:** enum value added, docstring updated, no migration yet.

### Task 1.5 — Add relationship to `AgentJob`

Add `intervene_requests: Mapped[list["InterveneRequest"]] = relationship(...)` to the `AgentJob` model, with `back_populates="agent_session"` and appropriate cascade rules. Use a forward reference string since `InterveneRequest` is in a separate module.

**Done when:** relationship defined, no migration yet.

### Task 1.6 — Register new models in `__init__.py`

Add `InterveneRequest` and `InterveneResponse` imports to `backend/app/db/models/__init__.py` so Alembic autogenerate detects them. Follow the existing import pattern.

**Done when:** both models imported in `__init__.py`.

### Task 1.7 — Generate Alembic migration

Run `alembic revision --autogenerate -m "add_intervene_requests"` from the `backend/` directory. Review the generated migration to ensure:
- `intervene_requests` and `intervene_responses` tables are created with correct columns and FK constraints
- `ALTER TYPE agent_job_status_enum ADD VALUE 'waiting_for_human'` is present
- The migration handles enum type correctly for PostgreSQL (use `postgresql.ENUM` with `create_type=False` for enum types already created by model import)
- Downgrade reverses all changes

Apply the migration with `alembic upgrade head`.

**Done when:** migration generated, reviewed, and applied; `alembic current` shows the new revision.

### Task 1.8 — Create Pydantic schemas

Create request/response schemas following the existing patterns in `backend/app/schemas/agents.py` or a new `backend/app/schemas/intervene.py`:
- `InterveneRequestCreate`: input fields for creating a request (session_id, intervention_type, reason, choices)
- `InterveneRequestRead`: full response model with all fields, timestamps, and nested response data
- `InterveneResponseSubmit`: operator response (request_id, approval_value OR selected_choice OR text_value)
- `InterveneResponseRead`: response data with operator info and timestamps
- `InterveneMetrics`: pending count, avg response time, resolution rate

**Done when:** all schemas defined with proper validation (e.g., mutually exclusive response fields, choices required when type=choice).

---

## Phase 2 — Backend API Endpoints

### Task 2.1 — Create `InterveneRequestStore` service

Create `backend/app/services/agents/intervene_service.py` with:
- `create_request(db, session_id, intervention_type, reason, choices, expires_at)`: creates a pending request, validates no duplicate pending request for this session
- `get_request(db, request_id)`: returns full request with response
- `list_requests(db, status, intervention_type, agent_session_id, limit, offset)`: filterable list
- `submit_response(db, request_id, operator_user_id, response_data)`: validates request is pending, creates response, updates status to `responded`
- `cancel_request(db, request_id)`: cancels a pending request
- `get_metrics(db)`: returns pending count, avg response time, resolution rate

Use the existing `AgentSessionService` as a pattern reference.

**Done when:** service class with all methods implemented and returning proper Pydantic models.

### Task 2.2 — Create API router

Create `backend/app/api/v1/intervene.py` with endpoints:

| Endpoint | Method | Permission | Purpose |
|----------|--------|------------|---------|
| `/api/v1/intervene/requests` | GET | `intervene:view` | List intervene requests with filters |
| `/api/v1/intervene/requests/{id}` | GET | `intervene:view` | Get single request with full context |
| `/api/v1/intervene/requests/{id}/respond` | POST | `intervene:respond` | Submit operator response |
| `/api/v1/intervene/requests/{id}/cancel` | POST | `intervene:respond` | Cancel a pending request |
| `/api/v1/intervene/metrics` | GET | `intervene:view` | Dashboard metrics |

Follow the existing pattern from `backend/app/api/v1/results.py` for router structure and `backend/app/api/v1/agents.py` for permission handling.

**Done when:** router created with all endpoints, proper HTTP error handling (404 for not found, 409 for conflict, 403 for permissions).

### Task 2.3 — Register router in main app

Include the intervene router in the main FastAPI application in `backend/app/main.py` (or the appropriate API mounting point). Follow the existing pattern of `app.include_router(InterveneRouter)`.

**Done when:** router registered and accessible at `/api/v1/intervene/...`.

### Task 2.4 — Implement permission checks

Add `intervene:view` and `intervene:respond` permission checks using the existing `require_permission` dependency. Only authorized operators can view and respond to requests. Follow the permission pattern established in `backend/app/api/v1/results.py`.

**Done when:** POST respond and POST cancel return 403 for users without `intervene:respond`; GET endpoints enforce `intervene:view`.

---

## Phase 3 — Agent Runtime Changes

### Task 3.1 — Define tool definition

Define `_HUMAN_INTERVENE_TOOL_DEF` in `runtime_executor.py` following the same pattern as `_SAVE_RESULT_TOOL_DEF`. Parameters:
- `reason` (string, required): explanation of why human input is needed
- `intervention_type` (string, required, enum: `approval`, `choice`, `text`)
- `choices` (array of strings, optional): available options when type is `choice`
- `prompt` (string, optional): descriptive prompt when type is `text`

**Done when:** tool definition dict matches the format expected by the LLM function-calling API; description explains the tool's purpose clearly.

### Task 3.2 — Register in `system_tools.py`

Add `"human_intervene"` to the `SYSTEM_TOOL_NAMES` frozenset in `backend/app/services/system_tools.py`. Verify `is_system_tool` and `get_canonical_name` resolve it correctly. Update the `_canonicalize_tool_name_for_log` helper in `runtime_executor.py` if needed.

**Done when:** `is_system_tool("human_intervene")` returns `True`; `is_system_tool("system____human_intervene")` returns `True`.

### Task 3.3 — Implement tool handler

Add handling in the Agent Runtime's tool execution path (in `runtime_executor.py`) to:
1. Detect when the LLM calls `human_intervene`
2. Snapshot the current execution context (messages, iteration, tool results)
3. Persist the snapshot via the `mark_session_waiting` call to Control Center
4. Send a `suspend` request to Communication Hub with the tool arguments
5. Return the pending request ID to the agent as the tool result

**Done when:** agent can call the tool and receive back a `{request_id, status: "pending"}` result; execution context is persisted.

### Task 3.4 — Implement suspend logic

Modify the LangChain observe-reason-act loop in `_run_task_loop_ar` so that when `human_intervene` is called:
1. The session status transitions to `waiting_for_human`
2. The loop exits cleanly (no error) after persisting context
3. No further LLM calls or tool calls occur
4. The executor marks the session as suspended in Control Center

This requires adding a `mark_session_waiting_for_human` method to `ControlCenterDataClient`.

**Done when:** loop exits after `human_intervene` call; session status is `waiting_for_human`; no further iterations execute.

### Task 3.5 — Create resume dispatcher endpoint

Create `POST /resume` endpoint in `backend/app/agent_runtime/api/execute.py` (or a new `resume.py`) that:
1. Accepts `request_id` and `response_value`
2. Retrieves the stored execution context snapshot
3. Restores the context into a new loop iteration
4. Injects the response value as the `human_intervene` tool's return value
5. Re-enters the observe-reason-act loop with `data_client.mark_session_running(session_id)`

**Done when:** endpoint accepts a resume request, restores context, and the agent continues execution with the human's input available as the tool result.

### Task 3.6 — Update `_run_task_loop_ar`

Modify the task loop to recognise `human_intervene` in the tool call results and route to the suspend handler rather than executing through the normal MCP tool path. The tool name `human_intervene` (canonical) or `system____human_intervene` (full) should be intercepted before MCP dispatch.

**Done when:** the loop intercepts `human_intervene` calls, routes to suspend logic, and does not attempt to dispatch them as MCP tool calls.

### Task 3.7 — Handle stale request cleanup

When a session in `waiting_for_human` state is terminated (via the existing termination flow), cascade to mark all pending intervene requests for that session as `cancelled`. This should happen in the Control Center termination handler using `InterveneRequestStore.cancel_request()`.

**Done when:** terminating a waiting session cancels all its pending requests; cancelled requests show the correct status in the UI.

---

## Phase 4 — Communication Hub Changes

### Task 4.1 — Add tool routing

Update the Communication Hub's tool routing table in `backend/app/communication_hub/api/dispatch.py` or the relevant routing module to recognise `system____human_intervene` as a system tool that should be forwarded to Control Center rather than dispatched as an MCP tool call.

**Done when:** Communication Hub routes `human_intervene` tool calls to Control Center's intervene persistence endpoints.

### Task 4.2 — Add control message relay

Implement the `intervene_response` control message relay:
1. Web UI → Communication Hub: `POST /intervene/respond` forwards to Control Center
2. Control Center → Communication Hub: resume signal forwarded to Agent Runtime

This follows the existing message relay pattern established for A2A communication.

**Done when:** operator responses flow from UI to AR through CH; resume signals flow from CC to AR through CH.

### Task 4.3 — Add notification trigger

When Control Center persists a new intervene request, emit a notification event that the existing notification integration system can consume. Add `intervene_request_created` and `intervene_request_responded` to the event catalog in `backend/app/services/notifications/notification_service.py`.

**Done when:** intervene request creation triggers a notification dispatch through configured channels.

---

## Phase 5 — Frontend Changes

### Task 5.1 — Add TypeScript types

Add the following types to `frontend/src/types/index.ts`:
- `InterveneRequestStatus`: `'pending' | 'responded' | 'cancelled' | 'expired'`
- `InterventionType`: `'approval' | 'choice' | 'text'`
- `InterveneRequest`: interface with all fields from data-model
- `InterveneResponse`: interface with all fields from data-model
- `InterveneMetrics`: `{ pending_count, avg_response_time_seconds, resolution_rate }`

**Done when:** types defined, importable, used by API functions and components.

### Task 5.2 — Create API client functions

Create `frontend/src/api/interveneApi.ts` with:
- `getInterveneRequests(filters)`: GET `/api/v1/intervene/requests`
- `getInterveneRequest(id)`: GET `/api/v1/intervene/requests/{id}`
- `submitInterveneResponse(requestId, response)`: POST `/api/v1/intervene/requests/{id}/respond`
- `cancelInterveneRequest(requestId)`: POST `/api/v1/intervene/requests/{id}/cancel`
- `getInterveneMetrics()`: GET `/api/v1/intervene/metrics`

Use the existing `apiClient` instance from `apiClient.ts`. Follow the pattern in existing API modules.

**Done when:** all functions defined, typed, and callable.

### Task 5.3 — Create React hook

Create `frontend/src/hooks/useInterveneRequests.ts` with:
- `pendingRequests`, `respondedRequests`, `metrics`, `isLoading`, `error`
- `submitResponse(requestId, value)`: calls API, refreshes list
- `cancelRequest(requestId)`: calls API, refreshes list
- Polling interval (or WebSocket subscription) for real-time updates
- Filtering by status, intervention type, date range

**Done when:** hook provides all necessary state and actions; updates are reflected in real-time.

### Task 5.4 — Create response dialog components

Create `frontend/src/components/agents/InterveneResponseDialog.tsx` (and variants):
- **Approval variant**: Shows agent's reason, Yes/No buttons, execution context summary
- **Choice variant**: Shows question, selectable cards/radio buttons for each choice, submit button
- **Text variant**: Shows prompt, text area with character count (configurable max), submit button

All variants must follow the dialog error handling standard:
- `dialogError` state cleared on open/close
- API call wrapped in try-catch
- Error displayed in `DialogContent` using `PermissionDeniedAlert`
- Loading state on submit button during API call

**Done when:** three dialog variants work correctly; errors display properly; submission confirms success.

### Task 5.5 — Create pending request list

Create `frontend/src/components/agents/InterveneRequestList.tsx` that displays pending intervene requests in a table or card layout with:
- Agent name, execution ID (linked to execution detail), reason, intervention type (with icon/badge), timestamp, elapsed wait time
- Action button to open the appropriate response dialog
- Empty state when no pending requests

**Done when:** list renders correctly with all data; clicking opens the correct dialog variant.

### Task 5.6 — Add dashboard filter

Modify the agent execution dashboard (`frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` or the relevant dashboard component) to include `waiting_for_human` in the status filter options alongside existing statuses.

**Done when:** filter option exists; selecting it shows only executions in `waiting_for_human` state.

### Task 5.7 — Add navigation badge

Add a pending intervene count badge to the navigation. This could be:
- A badge on the "Agent Executions" nav link showing count of `waiting_for_human` sessions
- A new nav item "Interventions" with a pending count badge

Use the `getInterveneMetrics` API or WebSocket push for real-time updates.

**Done when:** badge shows accurate pending count; updates without page refresh.

### Task 5.8 — Add execution detail section

Add an "Intervention Requests" section to the execution detail view (`frontend/src/pages/agents/AgentJobPage.tsx` or equivalent) showing:
- Pending requests with respond button
- Resolved requests with response details (who responded, what was chosen, timestamp)
- Timeline of intervene events during execution

**Done when:** section renders inline; pending requests can be responded to directly from the detail view.

### Task 5.9 — Add i18n translations

Add translation keys for all new UI strings to the project's i18n locale files. Keys should follow the existing naming convention (e.g., `intervene.request.pending`, `intervene.response.approval.title`, `intervene.dashboard.filter.waiting`).

**Done when:** all UI strings use `t()` function calls; translations exist in locale files.

---

## Phase 6 — Notifications Integration

### Task 6.1 — Add notification trigger types

Add `intervene_request_created` and `intervene_request_responded` to the notification trigger type enumeration or configuration in `backend/app/services/notifications/notification_service.py`. Create handlers that format the notification content appropriately for each trigger (request reason, agent name, execution link, response value).

**Done when:** trigger types registered and format handlers defined.

### Task 6.2 — Wire up dispatch

In the Control Center's intervene service, after creating a request or receiving a response, emit a notification event via the existing notification service. Follow the pattern used for other trigger types (e.g., SOP completion, agent failure).

**Done when:** notifications are dispatched for intervene lifecycle events through configured channels (email, Slack, Teams, webhook, in-app).

### Task 6.3 — Add OTEL events

Add OpenTelemetry spans and events for intervene request lifecycle in the Control Center service:
- `intervene.created`: when request is persisted (attributes: request_id, intervention_type, session_id)
- `intervene.responded`: when operator responds (attributes: request_id, operator_id, response_type)
- `intervene.cancelled`: when request is cancelled (attributes: request_id, reason)
- `intervene.expired`: when timeout elapses (attributes: request_id)

**Done when:** OTEL events visible in traces; attributes contain relevant context for observability dashboards.

---

## Phase 7 — Testing and Verification

### Task 7.1 — Backend unit tests

Write tests for `InterveneRequestStore` in `backend/tests/services/test_intervene_service.py`:
- Create request with valid parameters
- Reject duplicate pending request for same session
- List requests with various filters
- Submit response (approval, choice, text types)
- Reject response on already-responded request
- Cancel pending request
- Get metrics with mixed statuses

**Done when:** all unit tests pass; coverage includes normal flows, edge cases, and error paths.

### Task 7.2 — Backend integration tests

Write integration tests in `backend/tests/api/v1/test_intervene.py`:
- POST respond with valid data returns 200
- POST respond with invalid data returns 422
- POST respond without permission returns 403
- POST cancel on already-cancelled request returns 409
- GET list with status filter returns filtered results
- GET metrics returns correct counts
- Verify FK cascade behavior on session deletion

**Done when:** integration tests pass against real database; migration applied before tests run.

### Task 7.3 — Frontend component tests

Write tests for the response dialogs in `frontend/src/__tests__/components/test_InterveneResponseDialog.tsx`:
- Approval dialog renders Yes/No buttons
- Choice dialog renders all options; selection required before submit
- Text dialog renders text area; enforces character limit
- Error state displays permission-denied alert
- Loading state disables submit button
- Success state shows confirmation message

**Done when:** all component tests pass; mock API calls work correctly.

### Task 7.4 — E2E tests

Write Playwright E2E tests in `e2e/tests/intervene.spec.ts`:
- Create agent execution, call `human_intervene`, verify session enters `waiting_for_human` state
- Navigate to dashboard, verify `waiting_for_human` filter shows the execution
- Open response dialog, submit Yes approval, verify agent resumes
- Verify audit trail in execution detail view shows the intervene history

Include at least one test that hits the real backend (no mocks) to catch migration issues.

**Done when:** E2E tests pass; real backend test verifies end-to-end flow.

### Task 7.5 — Full test suite

Run the complete test suite:
- `pytest backend/tests/` — all backend tests pass
- `npx vitest run` — all frontend tests pass
- `npx playwright test` — all E2E tests pass

Fix any regressions introduced by the change. Ensure existing tests continue to pass.

**Done when:** all three test suites pass with zero failures.

---

## Completion Checklist

- [x] Backend model `InterveneRequest` and `InterveneResponse` created and migrated
- [x] `AgentJobStatus` extended with `waiting_for_human`
- [x] Pydantic schemas defined for all request/response types
- [x] `InterveneRequestStore` service with full CRUD + metrics
- [x] REST API endpoints for list, get, respond, cancel, metrics
- [x] Permission checks (`intervene:view`, `intervene:respond`) enforced
- [x] `human_intervene` system tool definition registered
- [x] Suspend logic pauses LangChain loop cleanly
- [x] Resume dispatcher restores context and re-enters loop
- [x] Stale requests cancelled on session termination
- [x] Communication Hub routes tool calls and control messages
- [x] Notification triggers for intervene lifecycle events
- [x] Frontend TypeScript types defined
- [x] API client functions created
- [x] Response dialogs (approval, choice, text) with error handling
- [x] Pending request list component
- [x] Dashboard filter for `waiting_for_human` status
- [x] Navigation badge for pending count
- [x] Intervene section in execution detail view
- [x] i18n translation keys added
- [x] OpenTelemetry events for intervene lifecycle
- [x] Backend unit and integration tests passing
- [x] Frontend component tests passing
- [x] E2E tests covering the full flow
- [x] Full test suite passes with no regressions
