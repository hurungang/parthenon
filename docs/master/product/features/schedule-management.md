# Schedule Management

## Epic Overview

Schedule Management enables platform administrators to automate recurring Agent executions through cron-based schedules, eliminating the need for manual triggers. Administrators create schedules using a visual cron editor, configure input parameters that match the target agent's expected inputs, and monitor every execution through a detailed history view. The scheduler runs within the Control Center, survives service restarts by recovering active schedules from the database, and provides full auditability through tracked execution history with drill-down into individual agent session results.

## Business Goals

- Enable unattended, time-based agent execution for recurring tasks such as daily reports, hourly monitoring, and weekly data processing
- Reduce operational overhead by replacing manual agent triggers with automated schedules
- Provide full visibility into scheduled job execution history for audit, compliance, and troubleshooting
- Ensure reliability through automatic schedule recovery after service restarts and configurable polling intervals
- Allow administrators to pause, resume, and edit schedules without losing existing configuration

## Users & Personas

- **Platform Administrator** — Creates, edits, and manages schedules; needs visual cron editing, agent parameter configuration, and lifecycle controls (pause/resume/delete)
- **Operator** — Monitors scheduled executions; needs to see success/failure status, execution timing, and drill into agent session details for investigation
- **Compliance Auditor** — Reviews execution history to verify that scheduled processes ran successfully and on time; needs clear audit trail with timestamps and outcomes

## User Stories

- As a Platform Administrator, I want to create a schedule using a visual cron editor with preset shortcuts, so that I can define recurrence patterns without memorizing cron syntax
- As a Platform Administrator, I want to select a target agent type and configure its input parameters, so that the agent receives the correct inputs matching its definition on each scheduled run
- As a Platform Administrator, I want to edit an existing schedule, so that I can update the cron expression, target, or parameters without recreating it from scratch
- As a Platform Administrator, I want to pause, resume, and delete schedules, so that I can manage execution timing and clean up unused schedules
- As an Operator, I want to view execution history for each schedule with pagination, so that I can verify successful runs and investigate failures across many executions
- As an Operator, I want to click a "View Agent Result" button on any execution, so that I can drill into the agent session details and see the full execution output
- As an Administrator, I want the scheduler to recover automatically after a service restart, so that active schedules continue running without manual intervention

## Acceptance Criteria

- Administrator can create a schedule with: name, description, cron expression (via visual cron editor with preset shortcuts), target agent type, and input parameters matching the agent's input schema
- Created schedule immediately appears in the schedule list and executes at the defined cron time
- Administrator can edit an existing schedule — edit form pre-populates with current values, changes persist on save, and the schedule list refreshes automatically
- Administrator can pause a schedule (stops execution, status changes to paused) and resume it (status returns to active, execution resumes)
- Administrator can delete a schedule with confirmation — schedule is soft-deleted, stops firing, and no longer appears in the list
- Schedule list shows name, cron expression, target type, and status for every schedule with pagination
- Execution history dialog displays runs with: started timestamp, finished timestamp, status (success/failure/running), error details, and linked agent session status
- Each execution with an agent session shows a "View Agent Result" icon button that opens the agent execution details dialog
- Execution history supports pagination with configurable rows per page (10/25/50/100)
- After Control Center restart, all active schedules are reloaded from the database and resume execution
- Scheduler check/poll interval is configurable via environment variable through the existing config system
- Validation errors shown for invalid input; required fields (name, cron expression, target) enforced on save

## Out of Scope

- Calendar-based scheduling UI (e.g., selecting specific dates on a calendar)
- Scheduling workflows or SOPs — only agent types are supported as schedule targets
- Notifications or alerts on schedule failure (covered by existing notification infrastructure)
- Timezone selection per schedule — all schedules run in UTC
- Complex branching or conditional execution logic within schedules
- One-time (non-recurring) scheduled executions — all schedules are cron-based recurring jobs

## Dependencies & Constraints

- Scheduler runs inside the Control Center service only — the only service with database access
- Scheduler check interval is configurable through the existing configuration system
- Visual cron editor is provided on the frontend for defining recurrence patterns
- All schedule UI text uses i18n function calls with translations in locale files — no hardcoded strings
- Active schedules are persisted in the database and recovered automatically on restart
- Execution history references agent sessions to enable drill-down; agent session data is managed by the Agent Runtime service
