## Implementation Plan: implement-schedule-feature

### Overview

Complete the scheduling feature from its current placeholder state. Work covers: adding a configurable check interval to the Pydantic Settings, wiring the SchedulingEngine into Control Center startup/recovery, integrating a visual cron editor and payload editor into the frontend, adding execution history, and writing tests for the full flow.

## Task Checklist

### Phase 1 — Backend: Config & Scheduler Wiring
- [x] 1.1 — Add `scheduler_check_interval_seconds` to Pydantic Settings
- [x] 1.2 — Wire SchedulingEngine startup/shutdown into Control Center lifecycle
- [x] 1.3 — Implement schedule recovery on service restart (load active jobs from DB)
- [x] 1.4 — Add execution history API endpoint enhancements if needed

### Phase 2 — Frontend: Cron Editor & Payload UI
- [x] 2.1 — Install and integrate a React cron expression builder library
- [x] 2.2 — Replace plain text cron field with visual cron editor component
- [x] 2.3 — Add dynamic input parameter (payload) editor to schedule dialog
- [x] 2.4 — Add execution history view to schedule manager page
- [x] 2.5 — Add i18n translations for all new schedule UI text

### Phase 3 — Testing & Verification
- [ ] 3.1 — Write backend integration tests for schedule CRUD + execution
- [ ] 3.2 — Write frontend unit tests for schedule components
- [ ] 3.3 — Verify end-to-end: create schedule, verify it fires, check execution history

## Phase 1 — Backend: Config & Scheduler Wiring

### Task 1.1 — Add `scheduler_check_interval_seconds` to Pydantic Settings

**File:** `backend/app/core/config.py`

Add a new field to the `Settings` class in the `# Scheduling` section:

```python
scheduler_check_interval_seconds: int = 60
```

This controls how often the APScheduler's default check interval operates. It defaults to 60 seconds and is overridable via `SCHEDULER_CHECK_INTERVAL_SECONDS` env var.

**Done when:** The field exists in Settings, is readable via `get_settings().scheduler_check_interval_seconds`, and defaults to 60.

### Task 1.2 — Wire SchedulingEngine startup/shutdown into Control Center lifecycle

**File:** `backend/app/main.py`

Add two new startup tasks:
- `_start_scheduling_engine()` — called in the `startup_event` handler
- A shutdown handler that stops the scheduler

The startup should:
1. Check `settings.scheduler_enabled` — skip if false
2. Create/get the SchedulingEngine singleton
3. Call `engine.start()`
4. Load all active schedules from DB and register each with APScheduler

Add to `startup_event`:
```python
await _start_scheduling_engine()
```

Also register a shutdown handler:
```python
@app.on_event("shutdown")
async def shutdown_event():
    await _stop_scheduling_engine()
```

**Done when:** SchedulingEngine starts with Control Center, active schedules are loaded from DB, and the engine stops cleanly on shutdown.

### Task 1.3 — Implement schedule recovery on service restart

**File:** `backend/app/services/scheduling/scheduler.py`

Add a `recover_schedules()` method to SchedulingEngine:

```python
async def recover_schedules(self, db_factory: Any) -> int:
    """Load all active jobs from DB and register with APScheduler."""
    async with db_factory() as db:
        result = await db.execute(
            select(ScheduledJob).where(ScheduledJob.status == JobStatus.active)
        )
        jobs = list(result.scalars().all())
    for job in jobs:
        await self.add_job(job, db_factory)
    return len(jobs)
```

**Done when:** After Control Center restart, logs show "Recovered N schedules from database" and each active cron job fires at its scheduled time.

### Task 1.4 — Add execution history API endpoint enhancements

**File:** `backend/app/api/v1/scheduling.py`

The existing `GET /{job_id}/executions` returns last 100 executions. Verify this is sufficient. Consider adding a summary count endpoint or enhancing with pagination if the current implementation is insufficient.

**Done when:** Execution history is available via API and frontend can display it.

## Phase 2 — Frontend: Cron Editor & Payload UI

### Task 2.1 — Install and integrate a React cron expression builder library

Install a cron expression builder package. Options:
- `@olehermanse/react-cron-builder` — simple, lightweight
- `@react-cron-builder/core` — more customizable
- Build a custom component if library requirements don't fit

**Done when:** A cron editor component renders in the schedule dialog and returns a valid 5-field cron expression.

### Task 2.2 — Replace plain text cron field with visual cron editor component

**File:** `frontend/src/pages/scheduling/ScheduleManagerPage.tsx`

Replace the current `<TextField>` for `cron_expression` with the cron editor component. The component should:
- Show preset buttons (every hour, daily, weekly, etc.)
- Allow fine-tuning minute, hour, day-of-week
- Display the resulting cron expression and next run time preview
- Write the cron expression string back to the form state

**Done when:** The schedule create/edit dialog shows a visual cron editor instead of a plain text field, and the cron expression is properly captured.

### Task 2.3 — Add dynamic input parameter (payload) editor to schedule dialog

**File:** `frontend/src/pages/scheduling/ScheduleManagerPage.tsx`

Add a payload editor section below the target selector that:
- Shows when a target is selected
- Allows adding/removing key-value pairs
- Serializes to the `payload` field as `Record<string, string>`
- Optionally shows input hints if agent type definition has input schema

**Done when:** Users can define input parameters for a schedule that get passed as payload to the agent/SOP on execution.

### Task 2.4 — Add execution history view to schedule manager page

**File:** `frontend/src/pages/scheduling/ScheduleManagerPage.tsx`

Add an execution history tab or expandable section per schedule row showing:
- Run timestamp (started_at, finished_at)
- Status (success/failure/running)
- Error message on failure
- Pagination for long histories

**Done when:** Users can expand a schedule row and see its recent execution history.

### Task 2.5 — Add i18n translations for all new schedule UI text

**Files:** `frontend/src/i18n/locales/*/translation.json`

Add translation keys for all new UI strings in the schedule feature including:
- Cron editor labels and presets
- Payload editor labels
- Execution history column headers
- Status labels

**Done when:** All new UI text uses `t()` function calls and translations exist in locale files.

## Phase 3 — Testing & Verification

### Task 3.1 — Write backend integration tests for schedule CRUD + execution

**Files:** `backend/tests/test_scheduling.py`

Test the full scheduling flow:
- CRUD operations via API
- Pause/resume transitions
- Soft delete (status changes to deleted)
- Execution history recording
- Schedule recovery after simulated restart

**Done when:** All tests pass and verify the scheduling feature end-to-end.

### Task 3.2 — Write frontend unit tests for schedule components

**Files:** `frontend/src/__tests__/ScheduleManagerPage.test.tsx`

Test the schedule manager components:
- Schedule list renders correctly
- Create dialog opens and validates required fields
- Cron editor updates form state
- Payload editor adds/removes rows
- Execution history displays runs

**Done when:** All frontend tests pass with the vitest JSON reporter.

### Task 3.3 — Verify end-to-end: create schedule, verify it fires, check execution history

Manual E2E verification:
1. Start the full stack (infra + backend + frontend)
2. Create a schedule with "every 2 minutes" cron
3. Verify it appears in the schedule list
4. Wait for the cron to fire (up to 2 min)
5. Check execution history shows a success entry
6. Pause the schedule, verify it stops firing
7. Resume the schedule, verify it resumes
8. Delete the schedule, verify it disappears from list

**Done when:** All E2E steps pass successfully.

## Completion Checklist

- [x] `scheduler_check_interval_seconds` config field added and documented
- [x] SchedulingEngine starts/shuts down with Control Center
- [x] Active schedules recovered from DB on restart
- [x] Visual cron editor renders in schedule dialog with presets
- [x] Dynamic payload editor allows defining input parameters per schedule
- [x] Execution history viewable per schedule
- [x] All UI text uses i18n t() function
- [ ] Backend tests pass for CRUD + execution flow
- [ ] Frontend tests pass for schedule components
- [ ] E2E verified: schedule created, fires, appears in history
