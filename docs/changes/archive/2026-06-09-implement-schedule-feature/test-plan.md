## Test Strategy

- **Unit Tests** — Backend: test SchedulingEngine methods (add/remove/pause/resume/recover) in isolation with mock APScheduler. Frontend: test CronEditor, PayloadEditor, ExecutionHistory components.
- **Integration Tests** — Backend: test schedule CRUD API against test database with real APScheduler and async DB session. Verify `JobExecution` records are created on dispatch.
- **E2E Tests** — One real-backend E2E test that creates a schedule, waits for it to fire, and verifies execution history. Mock-based E2E tests for UI flows.

## Coverage Areas

| Area | Why Critical |
|------|-------------|
| Schedule CRUD | Core API — must work reliably for all CRUD operations |
| Cron trigger registration | APScheduler must fire jobs at the correct cron times |
| Execution dispatch | Jobs must correctly dispatch to AgentInstanceManager or SopOrchestrator |
| Execution history | Every run must produce a JobExecution record for audit |
| Schedule recovery | After restart, all active schedules must re-register |
| Pause/resume lifecycle | State transitions must work correctly and be reflected in APScheduler |
| Cron editor component | Must produce valid 5-field cron expressions |
| Payload editor | Key-value pairs must serialize correctly to the API payload field |
| i18n strings | All UI text must use translation keys |

## Critical Scenarios

### Backend Integration

- **WHEN** a POST request creates a schedule with valid data **THEN** the response is 201 with the schedule record including a `scheduler_job_id`
- **WHEN** a schedule is created with `cron_expression: "* * * * *"` **THEN** it fires within 60 seconds and a `JobExecution` record with `status: success` or `status: failure` is created
- **WHEN** a schedule is paused via `POST /schedules/{id}/pause` **THEN** its APScheduler job is paused and `status` changes to `paused`
- **WHEN** a paused schedule is resumed **THEN** its APScheduler job is resumed and `status` changes to `active`
- **WHEN** a schedule is deleted **THEN** its `status` changes to `deleted`, it is removed from APScheduler, and it no longer appears in list queries
- **WHEN** the Control Center restarts **THEN** all active schedules are reloaded from DB, registered with APScheduler, and resume firing

### Frontend

- **WHEN** a user clicks "Create Schedule" **THEN** a dialog opens with the visual cron editor, target selector, and payload editor
- **WHEN** a user selects a preset in the cron editor **THEN** the cron expression updates and the preview shows the next run time
- **WHEN** a user adds key-value pairs in the payload editor **THEN** they serialize correctly in the API request body
- **WHEN** a user clicks the execution history button on a schedule row **THEN** the history panel shows runs with status, timestamps, and error details

## Edge Cases & Risks

- **Empty cron expression** — Frontend must prevent submission; backend must validate
- **Invalid cron expression** — APScheduler's `CronTrigger.from_crontab()` validation will throw; must handle gracefully
- **Target ID points to deleted agent/SOP** — Dispatch should fail gracefully with a descriptive JobExecution error
- **Scheduler disabled** — When `scheduler_enabled: false`, API CRUD should still work but jobs should not be registered with APScheduler
- **Very frequent cron** — `* * * * *` (every minute) is valid; the system must handle it without resource exhaustion
- **Concurrent startup** — If multiple Control Center instances start simultaneously, schedule recovery could double-register. APScheduler's `replace_existing=True` mitigates this
- **DB connection loss** — If DB is down during recovery, the scheduler should log the error and continue without crashing

## Acceptance Criteria Checklist

| # | Criterion | Pass Condition |
|---|-----------|----------------|
| AC1 | Create schedule with cron editor | Visual cron editor produces valid expression saved to backend |
| AC2 | Create schedule with payload | Key-value payload editor produces `payload` JSON persisted in DB |
| AC3 | Schedule fires at cron time | JobExecution record created within 1 minute of cron time |
| AC4 | Pause/resume works | Schedule status toggles and APScheduler pauses/resumes |
| AC5 | Delete works | Soft delete sets status to `deleted`, stops firing |
| AC6 | Execution history visible | GET executions returns records ordered by started_at desc |
| AC7 | Scheduler recovers on restart | All active schedules re-registered after service restart |
| AC8 | Configurable interval | `SCHEDULER_CHECK_INTERVAL_SECONDS` env var changes scheduler behavior |

## Test File References

| Test | File |
|------|------|
| Backend: schedule CRUD integration tests | `backend/tests/test_scheduling.py` (NEW) |
| Backend: SchedulingEngine unit tests | `backend/tests/test_scheduling.py` (NEW) |
| Frontend: ScheduleManagerPage tests | `frontend/src/__tests__/ScheduleManagerPage.test.tsx` (NEW) |
| Frontend: CronEditor component tests | `frontend/src/__tests__/CronEditor.test.tsx` (NEW) |
| Frontend: PayloadEditor component tests | `frontend/src/__tests__/PayloadEditor.test.tsx` (NEW) |
| E2E: Schedule feature real-backend test | `e2e/tests/scheduling.spec.ts` (NEW) |

## Pre-Test Checklist for Database Changes

Since `has_db_changes: true`, verify before running backend tests:
- [ ] Migration applied: `alembic current` shows latest revision
- [ ] If not applied: `alembic upgrade head` before running tests
- [ ] Test database has the `scheduled_jobs` and `job_executions` tables
- [ ] One E2E test hits real backend (no mocks) to verify migration is effective
