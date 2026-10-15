# Scheduling — Entities

```mermaid
erDiagram
    ScheduledJob {
        uuid id
        uuid tenant_id "mandatory at creation; job executes under its owning tenant's context"
        string name "unique per tenant"
        string description
        string cron_expression
        enum target_type "agent"
        uuid target_id
        json payload
        enum status "active|paused|deleted"
        string scheduler_job_id
        uuid scheduled_by_user_id "nullable; FK -> Identity (schedule creator)"
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
    Identity {
        uuid id
        string subject
        string display_name
    }

    ScheduledJob ||--o{ JobExecution : "has executions"
    Identity ||--o{ ScheduledJob : "scheduled by"
```

**Source**: `backend/app/db/models/scheduling.py`, `backend/app/db/models/identity.py`

## Entity Descriptions

| Entity | Description |
|--------|-------------|
| **ScheduledJob** | A cron-based schedule that triggers an agent at a recurring interval; carries the target identity, input payload, the APScheduler correlation ID for lifecycle management, and the creating user identity (`scheduled_by_user_id`) used as the trigger-provenance anchor for schedule-triggered agents. |
| **JobExecution** | An immutable record of a single scheduled job run; captures start/finish timestamps, status outcome, optional error detail, and execution result. |

## Business Rules

- **Mandatory tenant binding**: `tenant_id` is set at creation (when multi-tenancy is disabled, everything binds to the root tenant — never tenant-less). Dispatch never falls back through `job → agent type` chains to a NULL tenant; each job executes under its owning tenant's context (quotas, scoping, tool resolution). Job names are unique per tenant only. `JobExecution` inherits scope via its parent job.
- **Soft-delete**: Scheduled jobs are never hard-deleted. The `deleted` status hides them from active lists while preserving execution history.
- **Immutable execution history**: `JobExecution` records are append-only. Once created, they are never modified — status and results are set at completion and remain stable.
- **UTC only**: All schedule expressions (`cron_expression`) and timestamps are in UTC.
- **target_type is agent only**: The `target_type` currently supports only `agent`. SOP-based scheduling was removed.
- **Trigger provenance**: `scheduled_by_user_id` records who created the schedule. When the schedule fires, the value is copied into the triggered `AgentJob.triggered_by_user_id` at trigger time, so a schedule-triggered agent surfaces the schedule's creator as its trigger source.
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
