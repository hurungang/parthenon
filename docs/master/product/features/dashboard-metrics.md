# Dashboard Metrics

## Overview

The Dashboard Metrics feature replaces the original placeholder dashboard — which showed only identity provider configuration status cards — with a full operational overview. Platform operators land on the dashboard and immediately see platform health, configuration scale, pending human interventions, and time-filtered risk indicators without navigating into individual admin pages. Every metric widget is permission-aware: operators see only the data domains they are authorized to access, and domains they cannot access show a clear "Permission Denied" placeholder rather than a misleading value or a broken UI.

## Who Uses It

- **Platform Operators** — Monitor platform health, identify issues (failed executions, pending interventions, guardrail breaches), and triage quickly with a single-page overview
- **Enterprise Admins** — Assess platform configuration scale (how many agent types, identities, roles, model configs are active) and identify under-utilised resources
- **Compliance Auditors** — Rapidly verify guardrail posture and execution health trends across configurable time windows

## What It Does

- Displays **seven real-time stat cards** showing snapshot counts of key platform resources, each with a descriptive label and numeric value
- Provides **three time-sensitive metric cards** filtered by a date range picker, surfacing guardrail breach events, agent execution outcomes, and model usage posture breaches over a selectable time window
- Enforces **permission awareness** on every card — data queries are gated behind the same permissions as the corresponding admin screen, and unauthorized operators see a "Permission Denied" placeholder
- Retains the existing identity provider configuration status cards in a secondary, visually de-emphasised area below the operational metrics for first-run setup context

## Key Concepts

- **Real-Time Stat Cards**: Snapshot-count widgets that fetch a count from their data domain on page load. Cards display "0" for domains with no data — they are never hidden or blank.
- **Active/Running Breakdown**: The Agent Types card shows both the total count and a breakdown of agent types currently in use (active) versus agent executions currently in progress (running).
- **Time-Sensitive Metrics**: Three metric cards whose values change based on a user-selected date range. A date range picker with date and time selection (hours and minutes) sits above these cards.
- **Date Range Picker**: Provides quick preset shortcuts (Last Hour, Last 24 Hours, Last 7 Days) and custom date/time selection. Default range is the last 24 hours. Changing the range immediately refreshes all time-sensitive cards.
- **Permission-Denied Placeholder**: When an operator lacks the required permission for a metric's underlying data domain, the card displays a muted "Permission Denied" message with a lock icon instead of the count. The card remains visible so operators know the domain exists even if they cannot access it.
- **IdP Status Cards**: The original identity provider configuration status cards (user provider, agent provider, super-admin indicator) are retained but moved to a secondary or collapsed area below the operational metrics.

## Stat Cards Reference

### Real-Time Snapshot Cards

| Card | What It Shows | Permission Required |
|---|---|---|
| **Agent Types** | Total count, with active/running breakdown | View agent types |
| **Pending Interventions** | Count of human intervention requests awaiting operator response | View and respond to interventions |
| **Model Configurations** | Count of enabled model provider configurations | View model configurations |
| **Active Schedules** | Count of active scheduled jobs | View schedules |
| **Agent Identities** | Total count of provisioned agent identities | View agent identities |
| **Agent Roles** | Total count of defined agent roles | View agent roles |
| **MCP Servers** | Total count of registered MCP servers | View MCP Hub |

### Time-Sensitive Metric Cards

| Card | What It Shows | Permission Required |
|---|---|---|
| **Guardrail Breach Events** | Combined count of all guardrail threshold breach events and breach log entries within the selected date range | View agent execution trails |
| **Agent Executions** | Count of completed and failed agent executions within the selected date range, displayed as two numbers (e.g., "42 completed / 3 failed") | View agent executions |
| **Model Usage Posture Breaches** | Count of model usage posture breaches observed within the selected date range | View model configurations |

## Layout & UX Behaviour

- Stat cards are organised in a **responsive grid** (2–4 columns depending on viewport width) with consistent visual treatment: icon, label, and value for every card
- A **loading state** (skeleton or spinner) is shown while each card's data is being fetched; cards populate independently as their data arrives
- The page title remains the existing "Dashboard" header and tagline
- **Desktop-first design** for this feature; mobile-specific responsive layout is out of scope
- The dashboard loads within 2 seconds on a warm visit; cold cache may take up to 5 seconds
- The date range picker includes date and time selection with hours and minutes, defaulting to the last 24 hours
- Identity provider configuration status cards are retained in a secondary section or collapsed area below the operational metrics

## Acceptance Criteria

### Real-Time Stat Cards
- Dashboard page displays a grid of seven stat cards, each with a numeric count and descriptive label
- Agent Types card shows total count plus active/running breakdown
- Cards with zero data display "0" — not blank, not hidden
- Identity provider status cards are retained but moved to a secondary or collapsed area below the operational metrics

### Time-Sensitive Metrics
- A date range picker with date and time selection is present above the time-sensitive metrics section
- Quick preset shortcuts (Last Hour, Last 24 Hours, Last 7 Days) are available alongside custom date/time selection
- Default range is the last 24 hours (current time minus 24 hours to current time)
- Changing the date range immediately refreshes all three time-sensitive cards
- Each time-sensitive card displays the count and the selected date range label
- Agent Executions card shows completed and failed counts as two distinct numbers

### Permission Awareness
- Each card's data query is gated behind the corresponding admin section's view/read permission
- Cards for domains the operator cannot access display a "Permission Denied" placeholder with muted styling and a lock icon
- The permission-denied placeholder never hides the card entirely — operators know the data domain exists
- No 403 errors or broken UI states appear for any permission combination

### General Behaviour
- Dashboard loads within 2 seconds on first visit (cold cache acceptable within 5 seconds)
- Each card shows a loading state (skeleton or spinner) while its data is being fetched
- Cards populate independently as data arrives
- The page title and tagline remain unchanged from the existing dashboard

## Out of Scope

- Drill-down or click-through from stat cards to filtered list views
- Trend charts, sparklines, or time-series graphs
- Alerting thresholds or notification triggers based on dashboard metrics
- Customisable dashboard layouts or user-configurable card order
- Exporting dashboard data
- Real-time WebSocket push updates — cards refresh on page load and on date range change only
- Mobile-specific responsive design
- Changing the sidebar navigation structure
- Adding new aggregate data endpoints if existing list/read endpoints suffice for count queries

## Dependencies & Constraints

- Dashboard data must be retrievable from existing data domains — agent management, interventions, model configurations, schedules, identities, roles, MCP hub, and execution trails — with no new data entities required
- Count queries must be efficient and must not degrade performance of the underlying admin list pages
- Permission enforcement must use the existing policy engine — no new permission bypass patterns
- The identity provider status section must be retained for first-run setup context
- Follows existing UI component and internationalisation conventions
