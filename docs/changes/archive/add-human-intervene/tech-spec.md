# Technical Specification: Add Human Intervene

## Technical Overview

The human intervene feature adds a `system____human_intervene` system tool available to all agents during the observe-reason-act loop, following the same pattern as the existing `system____save_result` tool. When an agent calls this tool, the Agent Runtime persists the current execution context, transitions the session to `waiting_for_human` state, and pauses further LLM and tool calls. The Control Center stores the request in the `InterveneRequest` table and emits a notification event. An operator views pending requests via the Web UI, responds through a type-specific dialog (approval Yes/No, choice selection, or free-form text), and the response flows back through the Communication Hub to the Agent Runtime, which restores the context and resumes the loop with the human's input injected as the tool's return value.

The implementation extends four existing services (Control Center, Agent Runtime, Communication Hub, Web UI) and the notification integration system. No new services are introduced. The key architectural principle is that the Agent Runtime still has no direct database access — session state transitions and context persistence all flow through the Control Center's internal data API.

## Component Breakdown

### Control Center — Requests API
**Responsibility**: Persists intervene requests and responses, enforces lifecycle state transitions, provides REST API for listing and responding to requests, manages `waiting_for_human` session state.

| Concern | Detail |
|---------|--------|
| Data persistence | `InterveneRequest` and `InterveneResponse` tables (new models in `backend/app/db/models/intervene.py`) |
| Session state | `AgentJobStatus.waiting_for_human` new enum value; state machine transitions enforced in `InterveneRequestStore` |
| Permission guard | `intervene:view` on list/detail endpoints; `intervene:respond` on respond/cancel endpoints |
| Notification trigger | Emit `intervene_request_created` and `intervene_request_responded` events |

### Control Center — Internal Data API
**Responsibility**: Provides internal endpoints consumed by Agent Runtime for session state transitions and context persistence.

| Concern | Detail |
|---------|--------|
| State write | Internal PATCH endpoint for transitioning session to `waiting_for_human` |
| Context snapshot | Internal POST endpoint for persisting/recovering the execution context snapshot |
| Resume signal | Internal callback triggered when `InterveneResponse` is written |

### Agent Runtime — Loop Modification
**Responsibility**: Detects `human_intervene` tool calls in the LangChain observe-reason-act loop, suspends execution, and provides a resume endpoint to re-enter the loop.

| Concern | Detail |
|---------|--------|
| Tool interception | Intercept `human_intervene` in tool call result processing before MCP dispatch |
| Context snapshot | Serialise messages, iteration count, and tool results before suspending |
| Suspension | Exit loop with `waiting_for_human` state; no further LLM/tool calls |
| Resume | Accept response value, restore context, inject as tool result, re-enter loop |

### Agent Runtime — Tool Definition Registration
**Responsibility**: Registers `human_intervene` as a system tool available to all agents by default.

| Concern | Detail |
|---------|--------|
| Tool definition | Add `_HUMAN_INTERVENE_TOOL_DEF` to `runtime_executor.py` |
| System tool registry | Add `human_intervene` to `SYSTEM_TOOL_NAMES` in `system_tools.py` |

### Communication Hub — Tool Routing
**Responsibility**: Routes `system____human_intervene` tool calls from Agent Runtime to Control Center for persistence, and relays `intervene_response` control messages from Web UI to Control Center to Agent Runtime.

| Concern | Detail |
|---------|--------|
| Tool routing | Add `system____human_intervene` to the system tool routing table (alongside `save_result`) |
| Control relay | Forward POST respond from Web UI to Control Center; forward resume signal from Control Center to Agent Runtime |

### Web UI — Dashboard
**Responsibility**: Displays pending intervene requests, provides type-specific response dialogs, shows `waiting_for_human` as a filterable status, and renders a pending count badge.

| Concern | Detail |
|---------|--------|
| Request list | Card/table view of intervene requests with agent name, reason, type, elapsed time |
| Approval dialog | Yes/No button pair with agent reason and execution context |
| Choice dialog | Selectable option cards/radio buttons with agent question |
| Text dialog | Text area with character count and agent prompt |
| Dashboard filter | Add `waiting_for_human` to existing status filter dropdown |
| Navigation badge | Pending count displayed as a badge indicator |
| Execution detail | Inline section showing intervene request history for a session |

### Web UI — Execution Log Page Inline Intervene
**Responsibility**: When a user is watching a live execution log stream and the agent triggers an intervene request, a popup interrupts the stream inline. After response, the stream resumes.

| Concern | Detail |
|---------|--------|
| WebSocket listener | Subscribe to `intervene_request_created` events for the currently viewed `session_id`; show popup when event arrives |
| Stream freeze | Pause log rendering behind the popup (last visible entries remain); resume SSE/WebSocket log stream on close |
| Intervene popup | Same type-specific dialogs (approval/choice/text), triggered via WebSocket push rather than manual navigation |
| Persistent banner | If user dismisses popup, show a non-intrusive banner at top of log page: "Agent is waiting for your response" with "Respond" action |
| Stream resume | After response submitted, close popup/banner and re-attach to the log stream; new log entries appear seamlessly |

### Notification System — Trigger Integration
**Responsibility**: Adds `intervene_request_created` and `intervene_request_responded` as new notification trigger types dispatchable through configured channels (email, Slack, Teams, webhook, in-app).

| Concern | Detail |
|---------|--------|
| Trigger registration | New trigger types in the notification event catalog |
| Content formatting | Notification body templates for intervene request created (reason, agent, execution link) and responded (response value, operator) |

## API Changes

### New REST Endpoints (Control Center)

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| `GET` | `/api/v1/intervene/requests` | JWT + `intervene:view` | List intervene requests with optional filters (status, intervention_type, agent_session_id, from/to date, pagination) |
| `GET` | `/api/v1/intervene/requests/{id}` | JWT + `intervene:view` | Get a single request with full context, including the response if resolved |
| `POST` | `/api/v1/intervene/requests/{id}/respond` | JWT + `intervene:respond` | Submit an operator response. Body contains the intervention-type-specific response value |
| `POST` | `/api/v1/intervene/requests/{id}/cancel` | JWT + `intervene:respond` | Cancel a pending request (marks as `cancelled`, sets `responded_at`) |
| `GET` | `/api/v1/intervene/metrics` | JWT + `intervene:view` | Dashboard metrics: pending count, average response time in seconds, resolution rate percentage |

### New Internal Endpoints (Control Center — Internal Data API)

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| `POST` | `/api/v1/internal/data/intervene/requests` | mTLS (service cert) | Create a new intervene request from Agent Runtime via Communication Hub |
| `PATCH` | `/api/v1/internal/data/sessions/{id}/status` | mTLS (service cert) | Extended to support `waiting_for_human` and `running` transition from that state |

### New Endpoint (Agent Runtime)

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| `POST` | `/resume` | mTLS (agent-instance cert) | Resume a suspended session with the operator's response value. Accepts `session_id` and `response_value`, restores context, re-enters the observe-reason-act loop |

### Modified Endpoints

| Method | Route | Change |
|--------|-------|--------|
| `POST` | `/internal/tools/call` (Communication Hub) | Now routes `system____human_intervene` tool names to Control Center persistence instead of MCP dispatch |

## State Management

### Frontend State

| State Slice | Source | Consumer | Description |
|-------------|--------|----------|-------------|
| `pendingRequests` | API poll / WebSocket | Navigation badge, request list component | Array of `InterveneRequest` objects with `status=pending`; refreshed on interval or via WebSocket push |
| `metrics` | API poll | Navigation badge, dashboard | `{ pending_count, avg_response_time_seconds, resolution_rate }` |
| `dialogState` | Component local (useState) | Response dialog | Tracks open/closed, selected variant (approval/choice/text), form input values, submission loading |
| `dialogError` | Component local (useState) | Response dialog content area | API error state cleared on dialog open/close; displayed per dialog error handling standard |
| `activeFilter` | Dashboard local (useState) | Execution dashboard | Status filter state includes `waiting_for_human` option alongside existing values |
| `incomingInterveneRequest` | WebSocket push | Execution log page | Pushed via WebSocket when agent triggers `human_intervene` while user watches the log stream. Contains full request payload + session context. Triggers the inline popup. Cleared on response or dismiss. |
| `streamPaused` | Component local (useState) | Execution log page | Boolean flag that freezes log rendering when intervene popup is open; set to `false` when user responds and popup closes |

### Server-side State (Control Center)

| State | Location | Description |
|-------|----------|-------------|
| `InterveneRequest` rows | `intervene_requests` table | Persisted requests with lifecycle status, timestamps, and FK to `agent_jobs` |
| `InterveneResponse` rows | `intervene_responses` table | Persisted operator responses, 1:1 with requests |
| `AgentJob.status` | `agent_jobs` table | Updated to `waiting_for_human` on suspend, back to `running` on resume |

### Server-side State (Agent Runtime)

| State | Location | Description |
|-------|----------|-------------|
| Execution context snapshot | In-memory (persisted via CC) | Messages, iteration count, tool results at suspend point; restored on resume |

## Data Access Patterns

### Client-side (Frontend → Control Center)

| Pattern | Endpoint | Rationale |
|---------|----------|-----------|
| List pending requests | `GET /api/v1/intervene/requests?status=pending` | Operators need to see all pending requests across all agents without querying individual sessions. Client-side aggregation is simpler than server-side push for initial load |
| Submit response | `POST /api/v1/intervene/requests/{id}/respond` | Response submission is a write operation that must be authorised. Only the Control Center has the permission context to validate `intervene:respond` |
| Poll metrics | `GET /api/v1/intervene/metrics` | Lightweight count endpoint avoids fetching full request list just for badge display. Poll interval of 15-30 seconds is sufficient for visibility |
| View request detail | `GET /api/v1/intervene/requests/{id}` | Single-request fetch provides full context (including execution snapshot) for the response dialog |

### Server-side (Agent Runtime → Control Center via Communication Hub)

| Pattern | Endpoint | Rationale |
|---------|----------|-----------|
| Create request | `POST /api/v1/internal/data/intervene/requests` | Agent Runtime has no database access. All persistence flows through Control Center's internal API. The Communication Hub routes the tool call to this internal endpoint |
| Transition to waiting | `PATCH /api/v1/internal/data/sessions/{id}/status` | Session state is managed centrally by Control Center. The Agent Runtime signals the transition, Control Center applies it |
| Submit response | Via Communication Hub relay to `POST /intervene/requests/{id}/respond` | Response flows from Web UI → Communication Hub (public) → Control Center (internal). This maintains the service segregation boundary |
| Resume signal | Control Center → Communication Hub → Agent Runtime internal API | After response is persisted, Control Center triggers resume via Communication Hub relay to Agent Runtime's `/resume` endpoint |

### Why Not Direct Database Access

- **Agent Runtime** does not have database credentials per the project's service segregation rules (`top_priority_rules`). All data flows through the Control Center's internal API
- **Web UI** cannot access the database directly per project conventions. All reads and writes go through REST endpoints with JWT authentication and permission checks
- The intervene request lifecycle involves three services (Agent Runtime, Communication Hub, Control Center), so a centralised persistence layer with internal APIs is the correct pattern

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `InterveneRequestStatus` | enum | Enum: `pending`, `responded`, `cancelled`, `expired` | `backend/app/db/models/intervene.py` |
| `InterventionType` | enum | Enum: `approval`, `choice`, `text` | `backend/app/db/models/intervene.py` |
| `InterveneRequest` | model | SQLAlchemy model for intervene request persistence | `backend/app/db/models/intervene.py` |
| `InterveneResponse` | model | SQLAlchemy model for operator response persistence | `backend/app/db/models/intervene.py` |
| `AgentJobStatus.waiting_for_human` | enum value | New execution state added to existing enum | `backend/app/db/models/agents.py` |
| `InterveneRequestStore` | service | CRUD + metrics for intervene requests | `backend/app/services/agents/intervene_service.py` |
| `InterveneRouter` | router | FastAPI router for `/api/v1/intervene/*` endpoints | `backend/app/api/v1/intervene.py` |
| `_HUMAN_INTERVENE_TOOL_DEF` | constant | OpenAI function-calling tool definition dict | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._run_task_loop_ar` | method | Modified to intercept `human_intervene` tool calls | `backend/app/services/agents/runtime_executor.py` |
| `AgentRuntimeExecutor._handle_human_intervene` | method | New: suspend logic for human intervene tool call | `backend/app/services/agents/runtime_executor.py` |
| `ControlCenterDataClient.mark_session_waiting_for_human` | method | New: transition session to `waiting_for_human` via internal API | `backend/app/agent_runtime/data_client.py` |
| `ControlCenterDataClient.create_intervene_request` | method | New: persist intervene request via internal API | `backend/app/agent_runtime/data_client.py` |
| `resume_dispatcher` | endpoint | New: `POST /resume` on Agent Runtime to re-enter loop | `backend/app/agent_runtime/api/execute.py` |
| `CommHubToolClient` | client | Extended to route `human_intervene` tool calls | `backend/app/agent_runtime/comm_hub_client.py` |
| `SYSTEM_TOOL_NAMES` | constant | Extended with `human_intervene` entry | `backend/app/services/system_tools.py` |
| `InterveneRequestCreate` | schema | Pydantic model for request creation input | `backend/app/schemas/intervene.py` |
| `InterveneRequestRead` | schema | Pydantic model for request response output | `backend/app/schemas/intervene.py` |
| `InterveneResponseSubmit` | schema | Pydantic model for operator response input | `backend/app/schemas/intervene.py` |
| `InterveneResponseRead` | schema | Pydantic model for response output | `backend/app/schemas/intervene.py` |
| `InterveneMetrics` | schema | Pydantic model for dashboard metrics | `backend/app/schemas/intervene.py` |
| `InterveneRequest` (TS) | type | TypeScript interface for intervene request | `frontend/src/types/index.ts` |
| `InterveneResponse` (TS) | type | TypeScript interface for intervene response | `frontend/src/types/index.ts` |
| `InterveneRequestStatus` (TS) | type | TypeScript union type for request status | `frontend/src/types/index.ts` |
| `InterventionType` (TS) | type | TypeScript union type for intervention type | `frontend/src/types/index.ts` |
| `InterveneMetrics` (TS) | type | TypeScript interface for metrics | `frontend/src/types/index.ts` |
| `getInterveneRequests` | function | API client: list intervene requests | `frontend/src/api/interveneApi.ts` |
| `getInterveneRequest` | function | API client: get single request | `frontend/src/api/interveneApi.ts` |
| `submitInterveneResponse` | function | API client: submit operator response | `frontend/src/api/interveneApi.ts` |
| `cancelInterveneRequest` | function | API client: cancel pending request | `frontend/src/api/interveneApi.ts` |
| `getInterveneMetrics` | function | API client: get metrics | `frontend/src/api/interveneApi.ts` |
| `useInterveneRequests` | hook | React hook for intervene state and actions | `frontend/src/hooks/useInterveneRequests.ts` |
| `InterveneResponseDialog` | component | Dialog container routing to type-specific variant | `frontend/src/components/agents/InterveneResponseDialog.tsx` |
| `ApprovalResponseContent` | component | Approval variant: Yes/No buttons + reason | `frontend/src/components/agents/InterveneResponseDialog.tsx` |
| `ChoiceResponseContent` | component | Choice variant: selectable option cards | `frontend/src/components/agents/InterveneResponseDialog.tsx` |
| `TextResponseContent` | component | Text variant: free-form text area + character count | `frontend/src/components/agents/InterveneResponseDialog.tsx` |
| `InterveneRequestList` | component | Pending request list with action buttons | `frontend/src/components/agents/InterveneRequestList.tsx` |
| `AgentInstanceDashboardPage` | page | Modified: filter includes `waiting_for_human` | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` |
| `AgentJobPage` | page | Modified: inline intervene request section; WebSocket listener for incoming intervene events; stream freeze/resume logic | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `useExecutionLogStream` | hook | Hook managing SSE/WebSocket log stream; exposes `pause()` and `resume()` for intervene flow | `frontend/src/hooks/useExecutionLogStream.ts` |
| `InterveneInlinePopup` | component | Popup that appears on execution log page when agent triggers intervene; wraps type-specific dialogs | `frontend/src/components/agents/InterveneInlinePopup.tsx` |
| `IntervenePendingBanner` | component | Persistent banner shown if user dismisses intervene popup without responding | `frontend/src/components/agents/IntervenePendingBanner.tsx` |
| `NotificationService` | service | Extended with intervene request trigger types | `backend/app/services/notifications/notification_service.py` |
| `InterveneRequestStoreMetrics` | method | Metrics query: pending count, avg response time, resolution rate | `backend/app/services/agents/intervene_service.py` |
| `test_intervene_service` | test suite | Backend unit tests for `InterveneRequestStore` | `backend/tests/services/test_intervene_service.py` |
| `test_intervene_api` | test suite | Backend integration tests for intervene endpoints | `backend/tests/api/v1/test_intervene.py` |
| `test_InterveneResponseDialog` | test suite | Frontend component tests for response dialogs | `frontend/src/__tests__/components/test_InterveneResponseDialog.tsx` |
| `intervene.spec` | test suite | E2E tests for human-in-the-loop flow | `e2e/tests/intervene.spec.ts` |
