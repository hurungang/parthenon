# Module: scheduling — Tech Spec

## Overview

The scheduling module provides cron-based trigger capabilities for the platform, enabling agent interactions to be executed on a configured schedule without manual initiation. It is built on APScheduler (`AsyncIOScheduler`) running inside the Control Center process with a PostgreSQL job store as the persistent backend, ensuring schedules survive service restarts. On each cron trigger, the `SchedulingEngine._dispatch()` enqueues a new agent session via `GatewayLifecycleHandler.launch()`, which delegates execution to the Agent Runtime through the Communication Hub. On service restart, all active schedules are reloaded from the database and re-registered with APScheduler. The module exposes REST endpoints for creating, reading, updating, deleting, pausing, and resuming scheduled jobs, as well as querying per-job execution history.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `SchedulingEngine` | Singleton wrapper around APScheduler's `AsyncIOScheduler`; manages cron jobs via the PostgreSQL job store; dispatches triggered jobs to `GatewayLifecycleHandler.launch()` for agent execution |
| `ScheduleRouter` | FastAPI router providing full CRUD operations on scheduled jobs plus pause, resume, and execution history listing endpoints |
| `ScheduledJob` | SQLAlchemy model for a cron-based schedule record; stores the cron expression, target agent type, payload, enabled/paused state, and APScheduler job ID |
| `JobExecution` | SQLAlchemy model for a single execution run of a scheduled job; records trigger time, completion time, status, error details, and a linked `agent_session` |
| `LinkedAgentSession` | Pydantic schema summarising the linked agent execution session (session ID, status, output, error, timestamps, agent type name) |

### Frontend

| Component | Description |
|-----------|-------------|
| `ScheduleManagerPage` | Full schedule management page with a cron job list showing current status, create and edit form with cron expression builder, payload editor, pause/resume/delete actions, and execution history per job |
| `CronEditor` | Cron expression editor wrapping `react-js-cron` (antd-based) with a raw text field and `cronstrue` human-readable description |
| `PayloadEditor` | Key-value payload editor for schedule input parameters |
| `ExecutionHistory` | Execution history dialog with pagination; shows linked `agent_session` status and a "View Agent Result" `OpenInNew` icon button |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/schedules` | List all scheduled jobs (paginated) |
| `POST` | `/api/v1/schedules` | Create a cron schedule |
| `GET` | `/api/v1/schedules/{job_id}` | Get schedule detail |
| `PUT` | `/api/v1/schedules/{job_id}` | Update a schedule (re-registers cron) |
| `DELETE` | `/api/v1/schedules/{job_id}` | Soft-delete a schedule |
| `POST` | `/api/v1/schedules/{job_id}/pause` | Pause a scheduled job |
| `POST` | `/api/v1/schedules/{job_id}/resume` | Resume a paused job |
| `GET` | `/api/v1/schedules/{job_id}/executions` | List execution history for a job (paginated) |
| `POST` | `/api/v1/schedules/seed-defaults` | *(optional)* Utility endpoint for seeding demo schedules |

---

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

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SchedulingEngine` | class | APScheduler wrapper that manages cron jobs via the PostgreSQL job store; dispatches triggered jobs for agent execution | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine.start()` | method | Start background scheduler | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine.shutdown()` | method | Shutdown scheduler | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine.add_job()` | method | Register cron job with scheduler | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine._execute_job()` | method | Execute job: load from DB, create execution record, dispatch, record result | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine._dispatch()` | method | Route to gateway lifecycle handler for agent-target jobs | `backend/app/services/scheduling/scheduler.py` |
| `SchedulingEngine.recover_schedules()` | method | Load active jobs from DB and re-register with scheduler on restart | `backend/app/services/scheduling/scheduler.py` |
| `get_scheduling_engine()` | function | Singleton accessor for `SchedulingEngine` | `backend/app/services/scheduling/scheduler.py` |
| `ScheduleRouter` | router | FastAPI `APIRouter` with CRUD, pause, resume, and execution-history endpoints for scheduled jobs | `backend/app/api/v1/scheduling.py` |
| `ScheduledJob` | model | SQLAlchemy model for a cron-based schedule record (expression, target, payload, state) | `backend/app/db/models/scheduling.py` |
| `JobExecution` | model | SQLAlchemy model for a single execution run of a scheduled job | `backend/app/db/models/scheduling.py` |
| `ScheduledJobCreate` | schema | Pydantic create schema | `backend/app/schemas/scheduling.py` |
| `ScheduledJobUpdate` | schema | Pydantic update schema | `backend/app/schemas/scheduling.py` |
| `ScheduledJobRead` | schema | Pydantic response schema | `backend/app/schemas/scheduling.py` |
| `LinkedAgentSession` | schema | Pydantic schema for the linked agent execution session summary | `backend/app/schemas/scheduling.py` |
| `JobExecutionRead` | schema | Pydantic response schema; includes optional `agent_session` field | `backend/app/schemas/scheduling.py` |
| `Settings.scheduler_enabled` | field | Master scheduler enable/disable toggle | `backend/app/core/config.py` |
| `Settings.scheduler_check_interval_seconds` | field | Scheduler check interval in seconds (default 60) | `backend/app/core/config.py` |
| `_start_scheduling_engine()` | function | Start scheduler + recover schedules on application startup | `backend/app/main.py` |
| `_stop_scheduling_engine()` | function | Shutdown scheduler on application shutdown | `backend/app/main.py` |
| `startup_event` | handler | Application startup event handler; calls scheduling engine start | `backend/app/main.py` |
| `shutdown_event` | handler | Application shutdown event handler; calls scheduling engine stop | `backend/app/main.py` |
| `CommunicationHubClient.trigger_execution` | method | POSTs an agent execution trigger to the Communication Hub service | `backend/app/services/control_center/comm_hub_client.py` |
| `ScheduleManagerPage` | component | Schedule management page with cron job list, create/edit form, pause/resume/delete, and execution history | `frontend/src/pages/scheduling/ScheduleManagerPage.tsx` |
| `CronEditor` | component | Cron expression editor with raw text field and human-readable description | `frontend/src/components/scheduling/CronEditor.tsx` |
| `PayloadEditor` | component | Key-value payload editor for schedule input parameters | `frontend/src/components/scheduling/PayloadEditor.tsx` |
| `ExecutionHistory` | component | Execution history dialog with pagination; "View Agent Result" button for linked sessions | `frontend/src/components/scheduling/ExecutionHistory.tsx` |
| `JobTargetType` | type | TypeScript union type; only `'agent'` value (SOP targeting removed) | `frontend/src/types/index.ts` |
| `ScheduledJob` | type | TypeScript interface for scheduled job data | `frontend/src/types/index.ts` |
| `LinkedAgentSession` | type | TypeScript interface for linked agent session summary | `frontend/src/types/index.ts` |
| `JobExecution` | type | TypeScript interface for job execution data; includes `agent_session` field | `frontend/src/types/index.ts` |
