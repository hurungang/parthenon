## Epic Overview

The Parthenon platform has placeholder code for a cron-based scheduling feature that was never completed or tested. This epic completes the implementation, allowing administrators to create, manage, and monitor cron-driven schedules that trigger agent or SOP executions with configurable input parameters. The scheduler runs inside the Control Center with a configurable check interval, recovers active schedules after service restarts, and provides full execution history visibility.

## Business Goals

- Enable unattended, time-based agent and SOP execution for recurring tasks (e.g., daily reports, hourly monitoring, weekly data processing)
- Reduce operational overhead by replacing manual agent triggers with automated schedules
- Provide visibility into scheduled job execution history for audit and troubleshooting
- Ensure reliability through service-restart recovery and configurable polling intervals

## Users & Personas

- **Platform Administrator** — Creates and manages schedules; needs intuitive cron editing, input parameter configuration, and execution history
- **Operator** — Monitors scheduled executions; needs to see success/failure status and drill into execution details
- **Agent Developer** — Defines agent types and SOPs that can be triggered by schedules; needs schedules to properly pass input parameters matching agent definitions

## User Stories

- As a Platform Administrator, I want to create a schedule with a visual cron editor, so that I can define the recurrence pattern without memorizing cron syntax
- As a Platform Administrator, I want to specify input parameters for a scheduled agent execution, so that the agent receives the correct inputs matching its definition
- As a Platform Administrator, I want to pause, resume, and delete schedules, so that I can manage execution timing without losing configuration
- As an Operator, I want to view execution history for each schedule, so that I can verify successful runs and debug failures
- As an Operator, I want the scheduler to recover after service restarts, so that I don't lose active schedules or miss executions
- As a Platform Administrator, I want to configure the scheduler check interval via the existing config system, so that I can tune polling frequency for my environment

## Acceptance Criteria

- Administrator can create a schedule with: name, description, cron expression (via visual editor), target type (agent/SOP), target UUID, and input parameter payload
- Created schedule appears in the schedule list and executes at the defined cron time
- Administrator can pause, resume, and delete schedules
- Deleted schedules are soft-deleted (status = deleted) and stop executing
- Schedule execution history shows: start time, end time, status (running/success/failure), and error details on failure
- After Control Center restart, all active schedules are reloaded from the database and resume execution
- Scheduler check/poll interval is configurable via environment variable or config YAML through the existing Pydantic Settings system
- Frontend uses a visual cron expression editor component instead of a plain text field
- Frontend schedule form includes a dynamic input parameters section for defining the agent execution payload

## Out of Scope

- Calendar-based scheduling UI (e.g., selecting specific dates on a calendar)
- Scheduling recurring SOPs with complex branching logic
- Notifications/alerts on schedule failure (this is covered by the existing notification MCP tools)
- Timezone selection per schedule (all schedules run in UTC)

## Dependencies & Constraints

- Backend: Existing SchedulingEngine (`backend/app/services/scheduling/scheduler.py`) uses APScheduler — must retain compatibility
- Backend: Scheduler runs inside Control Center service only (per architecture rule: only Control Center connects to the database)
- Frontend: Must use an existing React cron expression library (e.g., `@olehermanse/react-cron-builder` or similar)
- Frontend: All UI text must use i18next `t()` function — no hardcoded strings
- Config: Scheduler interval setting must use the existing Pydantic Settings pattern (field in `backend/app/core/config.py` Settings class)
- Database: Existing `scheduled_jobs` and `job_executions` tables exist in baseline migration — no new tables needed unless schema review reveals gaps
