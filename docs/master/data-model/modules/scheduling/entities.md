# Scheduling — Entities

```mermaid
erDiagram
    ScheduledJob {
        uuid id
        string name
        string description
        string cron_expression
        enum target_type "agent"
        uuid target_id
        json payload
        enum status "active|paused|deleted"
        string scheduler_job_id
        datetime created_at
        datetime updated_at
    }
    JobExecution {
        uuid id
        uuid job_id
        enum status "running|success|failure"
        string error
        json result
        datetime started_at
        datetime finished_at
    }

    ScheduledJob ||--o{ JobExecution : "has executions"
```

**Source**: `backend/app/db/models/scheduling.py`

## Entity Descriptions

| Entity | Description |
|--------|-------------|
| **ScheduledJob** | A cron-based schedule that triggers an agent at a recurring interval; carries the target identity, input payload, and APScheduler correlation ID for lifecycle management. |
| **JobExecution** | An immutable record of a single scheduled job run; captures start/finish timestamps, status outcome, optional error detail, and execution result. |

## Business Rules

- **Soft-delete**: Scheduled jobs are never hard-deleted. The `deleted` status hides them from active lists while preserving execution history.
- **Immutable execution history**: `JobExecution` records are append-only. Once created, they are never modified — status and results are set at completion and remain stable.
- **UTC only**: All schedule expressions (`cron_expression`) and timestamps are in UTC.
- **target_type is agent only**: The `target_type` currently supports only `agent`. SOP-based scheduling was removed.
- **CASCADE delete**: Deleting a `ScheduledJob` cascades to all its `JobExecution` records.
- **APScheduler correlation**: `scheduler_job_id` links the database record to an APScheduler job for runtime lifecycle operations (pause, resume, remove).

## Status Transitions

```mermaid
stateDiagram-v2
    [*] --> active : Create schedule
    active --> paused : Pause
    paused --> active : Resume
    active --> deleted : Soft delete
    deleted --> [*]

    [*] --> running : Job triggered
    running --> success : Completion
    running --> failure : Error
```
