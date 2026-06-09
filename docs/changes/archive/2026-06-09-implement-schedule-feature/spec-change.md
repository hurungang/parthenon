## Affected Spec Areas

- `docs/master/product/features/scheduling.md` — New feature spec to create (schedule management is currently undocumented)
- `docs/master/architecture/system-overview.md` — Control Center component diagram needs scheduler sub-component
- `docs/master/data-model/overview.md` — ER diagram needs `ScheduledJob` and `JobExecution` entities
- `docs/master/technology/modules/scheduling/tech-spec.md` — New module tech spec needed

## New Capabilities

- Visual cron expression editor on the schedule creation/edit form using a React cron builder library
- Dynamic input parameter payload editor that adapts to the selected agent type's expected inputs
- Execution history view per schedule showing run status, timing, and error details
- Scheduler lifecycle management: start/stop/restart with the Control Center service
- Configurable scheduler check interval via Pydantic Settings (`SCHEDULER_CHECK_INTERVAL_SECONDS`)
- Automatic recovery of active schedules from the database on Control Center restart

## Modified Capabilities

- **Schedule Creation Dialog** — Enhanced from a plain text cron field to a visual cron editor with parameter payload configuration
- **Schedule List Page** — Enhanced to show execution counts and per-schedule execution history
- **SchedulingEngine** — Enhanced from placeholder to fully wired service that starts/stops with Control Center lifecycle
- **Existing Config** — New `scheduler_check_interval_seconds` field added to the Settings class alongside existing `scheduler_enabled`

## Removed Capabilities

- Plain text cron expression field on the schedule creation form (replaced by visual editor)

## Spec Update Instructions

- Create `docs/master/product/features/scheduling.md` documenting the scheduling feature as a first-class product capability
- Update `docs/master/architecture/system-overview.md` to add the scheduling engine sub-component within Control Center
- Update `docs/master/data-model/overview.md` to include `ScheduledJob` and `JobExecution` entities in the ER diagram
- Create `docs/master/technology/modules/scheduling/tech-spec.md` with code reference map for scheduling module
- Update `docs/master/qa/test-plans/scheduling-test-plan.md` with test coverage for scheduling
