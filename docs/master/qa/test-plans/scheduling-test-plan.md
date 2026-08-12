# Scheduling Test Plan

## What to Test

### Schedule CRUD — API
- `POST /api/v1/schedules` with valid data returns 201 with schedule record including `scheduler_job_id`
- `GET /api/v1/schedules` returns paginated list of active schedules (status ≠ `deleted`)
- `GET /api/v1/schedules/{id}` returns full schedule record by ID
- `GET /api/v1/schedules/{id}` returns 404 for unknown schedule ID
- `PUT /api/v1/schedules/{id}` updates fields (name, description, cron_expression, payload, target_id)
- `DELETE /api/v1/schedules/{id}` performs a soft delete (status → `deleted`); record still exists but excluded from list
- Duplicate name registration is rejected with appropriate 4xx error
- Permission enforcement on all schedule endpoints (`scheduling:read`, `scheduling:create`, `scheduling:update`, `scheduling:delete`)
- 403 structured error responses with resource type, action, and resource ID

### Schedule Pause/Resume Lifecycle — API
- `POST /api/v1/schedules/{id}/pause` transitions `active` schedule to `paused`; APScheduler job paused
- `POST /api/v1/schedules/{id}/resume` transitions `paused` schedule to `active`; APScheduler job resumed
- Pausing an already-deleted schedule returns 404
- Idempotent pause/resume: calling pause twice does not error

### Execution History — API
- `GET /api/v1/schedules/{id}/executions` returns empty list for a schedule with no runs
- `GET /api/v1/schedules/{id}/executions` returns records ordered by `started_at` desc
- Pagination support on execution list (skip/limit parameters)
- Execution records include `status`, `error`, `result`, `started_at`, `finished_at`, and `agent_session` fields
- `GET /api/v1/schedules/{id}/executions` returns 404 for unknown schedule ID

### Scheduling Engine
- Engine starts and shuts down cleanly; no orphaned APScheduler jobs remain
- `add_job` registers an APScheduler job with the correct cron trigger; `scheduler_job_id` assigned
- `remove_job` removes the job from APScheduler; no-op if job does not exist (no crash)
- `pause_job` / `resume_job` toggles APScheduler job state
- `recover` loads all active schedules from DB on startup and re-registers them with APScheduler
- `recover` handles empty active-schedule list gracefully (no crash)
- Invalid cron expressions raise descriptive validation errors (not 500)
- Engine dispatches via `_dispatch()` which calls `GatewayLifecycleHandler.launch()` to enqueue an AgentJob session through the Communication Hub
- Only `JobTargetType.agent` is supported (SOP targeting was removed); `JobTargetType` enum contains only `agent`

### Frontend — ScheduleManagerPage
- Schedule list renders schedule names, cron expressions, and status labels from the API response
- Title and create button use i18n translation keys (`schedules.title`, `schedules.createSchedule`)
- Create Schedule button triggers a dialog with cron editor (visual picker) and payload editor
- Save in create dialog calls POST API and closes the dialog
- Action buttons (history, pause/resume, delete) render per schedule row
- Full item lifecycle visible: create, read, update, delete all reflected without page reload

### Frontend — CronEditor
- Component renders without crashing; displays preset options and an interactive cron builder
- Preset selection updates the cron expression string
- Preview shows the next intended run time derived from the current expression

### Frontend — PayloadEditor
- Renders with pre-populated key-value pairs when initial payload is provided
- Renders an empty row when no initial value is given
- User can add new parameter rows dynamically
- User can remove existing parameter rows
- Typing in key/value fields triggers `onChange` callback with updated payload object
- Payload serializes correctly in the API request body on save

### Frontend — ExecutionHistory
- Dialog renders when `open=true`; does not render when `open=false`
- Shows a loading state while fetching execution data
- Displays execution records with status, timestamps, and error details
- "View Agent Result" button opens `AgentExecutionDetailsDialog` with linked AgentJob details from the `agent_session` field

### Cross-Cutting
- All new endpoints require authentication; unauthenticated requests rejected
- Permission enforcement across all schedule operations
- i18n string keys used for all UI labels; no hardcoded display strings in components

## Critical Scenarios
- Admin creates a schedule with visual cron editor → schedule appears in list with `active` status
- Admin edits a schedule name → updated name visible in list immediately without page reload
- Admin pauses an active schedule → status changes to `paused`; APScheduler job paused
- Admin resumes a paused schedule → status changes to `active`; APScheduler job resumed
- Admin deletes a schedule → schedule removed from list; re-creating with same name succeeds
- Admin opens execution history for a schedule → table shows runs with status, timestamps, and `agent_session` link
- Schedule fires at its cron time → `JobExecution` record created; dispatch calls `GatewayLifecycleHandler.launch()`
- Control Center restarts → all active schedules re-register with APScheduler and resume firing
- User without `scheduling:read` receives 403 on `GET /api/v1/schedules`
- User without `scheduling:create` receives 403 on `POST /api/v1/schedules`

## Edge Cases
- Invalid cron expression blocked by frontend validation; backend also rejects with clear error
- Very frequent cron (`* * * * *` — every minute) handled without resource exhaustion
- Duplicate schedule name returns appropriate error to the user
- Schedule with no payload (null) accepted; persisted correctly
- Pause called on already-deleted schedule returns 404
- Engine recovers when zero active schedules exist (graceful no-op)
- DB connection loss during recovery — scheduler logs error, continues without crashing
- Permission revoked between schedule create and next execution — dispatch handles 403 gracefully
- Concurrent startup with multiple Control Center instances is mitigated by APScheduler's `replace_existing=True`

## Known Limitations
- All 7 E2E tests are mock-based; there is no real-backend E2E test that fires a scheduled job end-to-end
- SOP targeting was removed during implementation; only `agent` target type is supported
- No dedicated test for `SCHEDULER_CHECK_INTERVAL_SECONDS` env var behavior (covered by SchedulingEngine unit tests indirectly)

## Test File References

### Backend
- `backend/tests/test_scheduling.py` — 22 tests (21 pass, 1 skipped) covering:
  - `TestScheduleCRUD` — create 201, list, get by ID, 404, update, soft delete, duplicate name rejection
  - `TestSchedulePauseResume` — pause, resume, pause-deleted 404
  - `TestExecutionHistory` — empty list, with data, pagination, 404 for unknown schedule
  - `TestSchedulingEngine` — start/shutdown, add/remove job, remove nonexistent, pause/resume job, recover (with and without active schedules), invalid cron expression

### Frontend
- `frontend/src/__tests__/ScheduleManagerPage.test.tsx` — 8 tests: list rendering, cron display, status labels, i18n title, create button, dialog open, save flow, action buttons
- `frontend/src/__tests__/CronEditor.test.tsx` — 1 test: renders without crashing
- `frontend/src/__tests__/ExecutionHistory.test.tsx` — 3 tests: dialog visibility toggle, loading state, content rendering
- `frontend/src/__tests__/PayloadEditor.test.tsx` — 6 tests: initial key-value rendering, empty initial, add row, remove row, key/value field change callbacks

### E2E
- `e2e/tests/scheduling.spec.ts` — 7 tests covering the full lifecycle: list, create, pause, resume, delete, execution history, edit

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| implement-schedule-feature | Initial scheduling feature: schedule CRUD, pause/resume lifecycle, execution history, SchedulingEngine with APScheduler, cron editor, payload editor, and E2E lifecycle coverage | 2026-06-09 |
