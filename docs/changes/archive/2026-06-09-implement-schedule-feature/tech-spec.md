## Technical Overview

The scheduling feature uses APScheduler (already a dependency) running inside the Control Center process. Schedules are stored in the `scheduled_jobs` table with cron expressions and payload parameters. On each cron trigger, the SchedulingEngine dispatches to either `AgentInstanceManager` (for agent targets) or `SopOrchestrator` (for SOP targets). A configurable check interval allows tuning the scheduler's polling behavior. On service restart, all active schedules are reloaded from the database and re-registered with APScheduler.

## Component Breakdown

### SchedulingEngine (`backend/app/services/scheduling/scheduler.py`)

- Singleton wrapper around APScheduler's `AsyncIOScheduler`
- Methods: `start()`, `shutdown()`, `add_job()`, `remove_job()`, `pause_job()`, `resume_job()`, `recover_schedules()`
- Internal `_execute_job()` loads job from DB, creates `JobExecution` record, dispatches to target, records result
- Internal `_dispatch()` routes to `AgentInstanceManager` or `SopOrchestrator` based on `target_type`

### Schedule API (`backend/app/api/v1/scheduling.py`)

- `GET /schedules` — list active schedules (paginated)
- `POST /schedules` — create schedule, register with APScheduler
- `GET /schedules/{id}` — get single schedule
- `PUT /schedules/{id}` — update schedule, re-register cron
- `DELETE /schedules/{id}` — soft delete, remove from APScheduler
- `POST /schedules/{id}/pause` — pause APScheduler job
- `POST /schedules/{id}/resume` — resume APScheduler job
- `GET /schedules/{id}/executions` — list execution history

### Config (`backend/app/core/config.py`)

- `scheduler_enabled: bool = True` — master enable/disable (already exists)
- `scheduler_check_interval_seconds: int = 60` — scheduler check interval (NEW)

### Frontend ScheduleManagerPage (`frontend/src/pages/scheduling/ScheduleManagerPage.tsx`)

- Schedule list table with name, cron, target, status, actions
- Create/edit dialog with visual cron editor and payload editor
- Execution history view (expandable per row or separate tab)
- Uses MUI components + react-query for data fetching

### CronEditor Component (new)

- Visual cron expression builder with presets
- Minute, hour, day-of-week pickers
- Preview showing the computed cron expression and next run time
- Outputs 5-field cron string

## API Changes

| Method | Route | Change |
|--------|-------|--------|
| GET | `/schedules` | Existing — verify pagination works |
| POST | `/schedules` | Existing — ensure payload field is fully supported |
| PUT | `/schedules/{id}` | Existing — verify update re-registers cron |
| DELETE | `/schedules/{id}` | Existing — soft delete |
| POST | `/schedules/{id}/pause` | Existing |
| POST | `/schedules/{id}/resume` | Existing |
| GET | `/schedules/{id}/executions` | Existing — add pagination support |
| POST | `/schedules/seed-defaults` | Add optional utility endpoint for seeding demo schedules |

## State Management

- **React Query** — schedule list and execution history use `useQuery` with `['schedules']` key; mutations invalidate and refetch
- **Form state** — local `useState` in the dialog for create/edit form fields, payload key-value pairs, and dialog error state

## Data Access Patterns

| Operation | Pattern | Reason |
|-----------|---------|--------|
| List schedules | Server-side API query with pagination | Pagination avoids loading all records |
| Create/update schedule | API mutation → invalidate query cache | Ensures UI reflects persisted state |
| Execution history | Server-side API query (per schedule) | History can be large; server filters by job_id |
| Schedule recovery | Direct DB load on startup | Only active schedules needed; done once on boot |

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SchedulingEngine` | class | APScheduler wrapper, manages cron jobs | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine.start()` | method | Start APScheduler background scheduler | `backend/app/services/scheduling/scheduler.py:26` |
| `SchedulingEngine.shutdown()` | method | Shutdown APScheduler | `backend/app/services/scheduling/scheduler.py:33` |
| `SchedulingEngine.add_job()` | method | Register cron job with APScheduler | `backend/app/services/scheduling/scheduler.py:40` |
| `SchedulingEngine.recover_schedules()` | method | Load active jobs from DB on restart | `backend/app/services/scheduling/scheduler.py:159` |
| `SchedulingEngine._execute_job()` | method | Execute job, record result | `backend/app/services/scheduling/scheduler.py:85` |
| `SchedulingEngine._dispatch()` | method | Route to AgentInstanceManager or SopOrchestrator | `backend/app/services/scheduling/scheduler.py:113` |
| `get_scheduling_engine()` | function | Singleton accessor | `backend/app/services/scheduling/scheduler.py:163` |
| `ScheduleRouter` | router | FastAPI routes for schedule CRUD | `backend/app/api/v1/scheduling.py:17` |
| `ScheduledJob` | model | SQLAlchemy model for schedule records | `backend/app/db/models/scheduling.py:36` |
| `JobExecution` | model | SQLAlchemy model for execution records | `backend/app/db/models/scheduling.py:77` |
| `ScheduledJobCreate` | schema | Pydantic create schema | `backend/app/schemas/scheduling.py:12` |
| `ScheduledJobUpdate` | schema | Pydantic update schema | `backend/app/schemas/scheduling.py:21` |
| `ScheduledJobRead` | schema | Pydantic response schema | `backend/app/schemas/scheduling.py:28` |
| `JobExecutionRead` | schema | Pydantic response schema | `backend/app/schemas/scheduling.py:44` |
| `get_settings()` | function | Cached settings accessor | `backend/app/core/config.py:259` |
| `Settings.scheduler_enabled` | field | Master scheduler enable/disable | `backend/app/core/config.py:234` |
| `_start_scheduling_engine()` | function | Start scheduler + recover on startup | `backend/app/main.py:303` |
| `_stop_scheduling_engine()` | function | Shutdown scheduler on app stop | `backend/app/main.py:319` |
| `startup_event` | handler | Calls _start_scheduling_engine after CA init | `backend/app/main.py:234` |
| `shutdown_event` | handler | Calls _stop_scheduling_engine on shutdown | `backend/app/main.py:246` |
| `Settings.scheduler_check_interval_seconds` | field | Scheduler check interval | `backend/app/core/config.py:235` |
| `ScheduleManagerPage` | component | Schedule management page | `frontend/src/pages/scheduling/ScheduleManagerPage.tsx` |
| `CronEditor` | component | Visual cron expression editor with presets | `frontend/src/components/scheduling/CronEditor.tsx` |
| `PayloadEditor` | component | Key-value payload editor | `frontend/src/components/scheduling/PayloadEditor.tsx` |
| `ExecutionHistory` | component | Execution history dialog with pagination | `frontend/src/components/scheduling/ExecutionHistory.tsx` |
| `ScheduledJob` | type | TypeScript interface | `frontend/src/types/index.ts:566` |
| `JobExecution` | type | TypeScript interface | `frontend/src/types/index.ts:580` |
