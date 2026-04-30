# Module: scheduling — Tech Spec

## Overview

The scheduling module provides cron-based trigger capabilities for the platform, enabling agent interactions and SOP runs to be executed on a configured schedule without manual initiation. It is built on APScheduler with a PostgreSQL job store as the persistent backend, ensuring schedules survive service restarts. The module exposes REST endpoints for creating, reading, updating, deleting, pausing, and resuming scheduled jobs, as well as querying per-job execution history.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `SchedulingEngine` | APScheduler-based cron manager; uses the PostgreSQL job store to persist job definitions; fires prompts or SOP runs against the Agent Engine on schedule; integrates with `AgentInstanceManager` to spawn instances for triggered jobs |
| `ScheduleRouter` | FastAPI router providing full CRUD operations on scheduled jobs plus pause, resume, and execution history listing endpoints |
| `ScheduledJob` | SQLAlchemy model for a cron-based schedule record; stores the cron expression, target agent type or SOP, prompt payload, enabled/paused state, and APScheduler job ID |
| `JobExecution` | SQLAlchemy model for a single execution run of a scheduled job; records trigger time, completion time, status, and any error details |

### Frontend

| Component | Description |
|-----------|-------------|
| `ScheduleManagerPage` | Full schedule management page with a cron job list showing current status, create and edit form with cron expression builder, pause/resume/delete actions, and expandable execution history per job |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/schedules` | List all scheduled jobs |
| `POST` | `/api/v1/schedules` | Create a cron schedule |
| `GET` | `/api/v1/schedules/{job_id}` | Get schedule detail |
| `PUT` | `/api/v1/schedules/{job_id}` | Update a schedule |
| `DELETE` | `/api/v1/schedules/{job_id}` | Delete a schedule |
| `POST` | `/api/v1/schedules/{job_id}/pause` | Pause a scheduled job |
| `POST` | `/api/v1/schedules/{job_id}/resume` | Resume a paused job |
| `GET` | `/api/v1/schedules/{job_id}/executions` | List execution history for a job |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SchedulingEngine` | class | APScheduler cron manager with PostgreSQL job store; triggers agent/SOP execution on schedule | `backend/app/services/scheduling/scheduler.py` |
| `ScheduleRouter` | router | CRUD, pause, resume, and execution history endpoints for scheduled jobs; all operations guarded by `require_permission(RT_SCHEDULING, action)` | `backend/app/api/v1/scheduling.py` |
| `ScheduledJob` | model | SQLAlchemy model for a cron-based schedule (expression, target, payload, state) | `backend/app/db/models/scheduling.py` |
| `JobExecution` | model | SQLAlchemy model for a single scheduled job execution run | `backend/app/db/models/scheduling.py` |
| `ScheduleManagerPage` | component | Cron job list with status, create/edit form, pause/resume/delete, and execution history | `frontend/src/pages/scheduling/ScheduleManagerPage.tsx` |
