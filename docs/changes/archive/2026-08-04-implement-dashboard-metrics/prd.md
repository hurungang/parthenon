# Dashboard Operational Metrics — PRD

## Epic Overview

The Parthenon dashboard is currently a thin placeholder showing only identity provider configuration status and a super-admin indicator. Platform operators have no way to assess platform health or identify issues requiring attention without navigating into individual admin pages. This epic replaces the placeholder dashboard with a real-time operational overview that surfaces actionable, attention-worthy metrics — enabling operators to scan the dashboard and immediately know what needs attention, without information overload.

## Business Goals

- **Reduce mean time to awareness** — Operators can see pending human interventions, guardrail breaches, and execution failures at a glance without navigating to individual pages
- **Provide platform health snapshot** — At-a-glance counts of agent types, identities, roles, model configs, MCP servers, and active schedules give operators immediate awareness of platform scale and configuration state
- **Surface time-sensitive risk** — Time-filtered breach events and execution failure trends let operators spot emerging problems before they escalate
- **Respect the permission model** — Dashboard metrics never leak data the operator is not authorized to see; each widget enforces the same permissions as the underlying admin screen

## Users & Personas

- **Platform Operators** — Need to monitor platform health, identify issues (failed executions, pending interventions, guardrail breaches), and triage quickly. Value density over volume.
- **Enterprise Admins** — Need to understand platform configuration scale (how many agent types, identities, roles, model configs are active) and whether anything is misconfigured or under-utilised.
- **Compliance Auditors** — Need to rapidly verify guardrail posture (any breached thresholds?) and execution health trends.

## User Stories

- As a platform operator, I want to see counts of agent types (with active/running breakdown), pending human interventions, enabled model configurations, and active schedules so that I can assess platform scale and operational load at a glance
- As a platform operator, I want to see how many agent identities, agent roles, and MCP servers are configured so that I understand platform adoption and integration scope
- As a platform operator, I want to see guardrail breach events, agent execution completions/failures, and model usage posture breaches filtered by a selectable time period (last hour, last 24 hours, last 7 days) so that I can spot emerging risks and trends
- As a platform operator, I want each stat to respect my permissions — if I lack access to a data domain, I want to see a "Permission Denied" placeholder instead of either a misleading value or an error
- As a platform operator, I want the dashboard to load quickly and show fresh data on every visit so that I can rely on it as my primary operational overview

## Acceptance Criteria

### Real-Time Stat Cards (Snapshot Counts)

- Dashboard page at `/` displays a grid of real-time stat cards
- Stat cards include:
  - **Agent Types** — Total count, with active/running breakdown (active = agent types currently in use; running = agent executions currently in progress)
  - **Pending Interventions** — Count of human intervention requests awaiting operator response
  - **Model Configurations** — Count of enabled model provider configurations
  - **Active Schedules** — Count of active scheduled jobs
  - **Agent Identities** — Total count of provisioned agent identities
  - **Agent Roles** — Total count of defined agent roles
  - **MCP Servers** — Total count of registered MCP servers
- Each card shows a numeric count and a descriptive label
- Cards showing zero display "0" — not blank, not hidden
- Identity provider configuration status cards are retained but moved to a smaller secondary section or collapsed area below the operational metrics

### Time-Sensitive Metrics (Date-Range Filtered)

- A date range picker is present above the time-sensitive metrics section, allowing the user to define a custom start date/time and end date/time
- Changing the date range immediately refreshes the time-sensitive cards
- The date range picker includes both date and time selection (hours and minutes), with sensible defaults:
  - Default start time is 24 hours before the current time
  - Default end time is the current time
- Time-sensitive cards include:
  - **Guardrail Breach Events** — Combined count of all guardrail threshold breach events and guardrail breach log entries within the selected date range
  - **Agent Executions** — Count of completed and failed agent executions within the selected date range, displayed as two numbers (e.g., "42 completed / 3 failed")
  - **Model Usage Posture Breaches** — Count of model usage posture breaches observed within the selected date range
- Time-sensitive cards display the count and the selected date range label (e.g., "Jul 7 08:00 — Jul 8 08:00")
- The date range picker provides quick preset shortcuts (Last Hour, Last 24 Hours, Last 7 Days) for convenience while allowing custom ranges

### Permission Awareness

- Each card queries data behind a permission check matching the underlying data domain:
  - Operators who can manage agents see Agent Types and Execution stats
  - Operators who can view and respond to human interventions see Pending Interventions
  - Operators who can view model configurations and usage posture see Model Configs and Posture Breaches
  - Operators who can view schedules see Active Schedules
  - Operators who can view agent identities see Agent Identities
  - Operators who can view agent roles see Agent Roles
  - Operators who can view the MCP Hub see MCP Servers
  - Operators who can view agent execution trails see Guardrail Breach Events
  - Each card's permission check corresponds to the read/view permission of the relevant admin section
- When the user lacks a required permission, the corresponding card displays a "Permission Denied" placeholder instead of the stat value
- The permission-denied state is visually distinct (e.g., muted styling, lock icon) but does not hide the card entirely — operators know the data domain exists even if they cannot access it
- No 403 errors or broken UI states appear for any permission combination

### General Behaviour

- Dashboard loads within 2 seconds on first visit (cold cache acceptable within 5 seconds)
- Stats cards are organised in a responsive grid (2–4 columns depending on viewport width)
- Cards have consistent visual treatment (icon, label, value) across all metric types
- The page title remains the existing "Dashboard" header and tagline
- A loading state (skeleton or spinner) is shown while each card's data is being fetched

## Out of Scope

- Drill-down or click-through from stat cards to filtered list views (future enhancement)
- Trend charts, sparklines, or time-series graphs (future enhancement)
- Alerting thresholds or notification triggers based on dashboard metrics
- Customisable dashboard layouts or user-configurable card order
- Exporting dashboard data
- Real-time WebSocket push updates — cards refresh on page load and on period change only
- Mobile-specific responsive design (desktop-first for this epic)
- Adding new API endpoints for aggregate metrics if existing list/read endpoints suffice for count queries
- Changing the sidebar navigation structure

## Dependencies & Constraints

- Dashboard data must be available via the existing data domains — agent management, interventions, model configurations, schedules, identities, roles, MCP hub, and execution trails — with no new data entities required
- Dashboard metrics must be retrievable without degrading performance of the underlying admin list pages (count queries must be efficient and not require retrieving full record sets)
- Permission enforcement must use the existing `require_permission` / policy engine — no new permission bypass patterns
- The identity provider status section must be retained (not removed) for first-run setup context
- Follows existing MUI component patterns and i18next internationalisation conventions per `docs/config.yaml`
