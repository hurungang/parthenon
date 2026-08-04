# Spec Change: Dashboard Operational Metrics

## Affected Spec Areas

- `docs/master/product/features/foundation-platform.md` — update Dashboard/Welcome page description from "placeholder with IdP status" to "operational dashboard with real-time metrics"
- `docs/master/product/features/` — create new `dashboard-metrics.md` feature spec describing the operational dashboard in detail
- `docs/master/product/README.md` — add Dashboard Metrics entry to the Feature Index

## New Capabilities

- **Real-time stat cards** — Seven snapshot-count cards on the dashboard page showing: Agent Types (with active/running breakdown), Pending Interventions, Enabled Model Configurations, Active Schedules, Agent Identities, Agent Roles, Registered MCP Servers. Each card fetches a count from its respective data domain and displays it as a labelled numeric value.

- **Time-sensitive metrics with date range picker** — A date range picker (with date + time selection and quick preset shortcuts for Last Hour, Last 24 Hours, Last 7 Days) filters three time-series cards: Guardrail Breach Events (combined from all guardrail breach sources), Agent Executions (completed/failed counts), and Model Usage Posture Breaches (breached posture records). Changing the date range immediately refreshes the displayed counts.

- **Permission-aware dashboard widgets** — Each stat card checks the user's permissions against the relevant resource type before fetching data. If the user lacks the required permission, the card displays a "Permission Denied" placeholder instead of the value. No card is completely hidden — operators know the domain exists even if they cannot access the underlying data.

## Modified Capabilities

- **Dashboard page (`/`)** — Before: thin placeholder showing only identity provider configuration status cards (user provider, agent provider, super-admin) and a "Configure Identity Providers" quick-action button. After: primary content is the operational metrics dashboard (stat cards grid + time-sensitive metrics with date range picker). The identity provider status cards are retained but moved to a secondary, collapsed, or visually de-emphasised area below the operational metrics.

## Removed Capabilities

- None. All existing dashboard content (identity provider status, quick-action button) is preserved but repositioned.

## Spec Update Instructions

- Update `docs/master/product/features/foundation-platform.md` — replace or extend the Dashboard/Welcome page description; change from "placeholder with IdP status cards" to "operational dashboard with stat cards, time-sensitive metrics, and permission-aware widgets"
- Create `docs/master/product/features/dashboard-metrics.md` — new feature spec describing:
  - The seven real-time stat cards with their data sources and permission checks
  - The three time-sensitive metric cards with date range picker behaviour
  - The permission-denied placeholder pattern
  - Layout, loading states, and general UX behaviour
- Update `docs/master/product/README.md` — add "Dashboard Metrics" entry to the Feature Index linking to the new spec
- Update `docs/master/product/features/foundation-platform.md` sidebar navigation section — note that the Dashboard is no longer a thin entry but a full operational overview
