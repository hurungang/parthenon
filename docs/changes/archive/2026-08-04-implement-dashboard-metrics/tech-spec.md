# Technical Specification: Dashboard Operational Metrics

## 1. Technical Overview

The dashboard operational metrics feature replaces the placeholder dashboard page with a permission-aware metrics overview. A single new aggregation endpoint on the Control Center performs server-side `COUNT(*)` queries across ten data domains (seven snapshot, three time-filtered), checks the caller's permissions per domain via the existing `PermissionEngine`, and returns a consolidated `DashboardSummary` JSON response containing counts and per-card permission flags. The frontend renders ten metric cards based on this response, displaying permission-denied placeholders for inaccessible domains without any 403 errors reaching the UI. Snapshot counts are not date-dependent; time-sensitive counts are filtered by a user-defined date range (start time and end time) that drives a React Query key change. The existing identity provider status cards are retained in a de-emphasised secondary section.

This feature introduces no new database tables, no inter-service communication, and no changes to the authentication or authorization infrastructure. It follows all `top_priority_rules` from `docs/config.yaml`: only Control Center connects to the database; the frontend calls only CC REST APIs; all endpoints require JWT authentication.

## 2. Component Breakdown

### Backend Components

**DashboardSummary (Pydantic model)** — `backend/app/schemas/dashboard.py`
- Responsibility: Define the shape of the aggregation response. Contains three nested models: `SnapshotCounts` (seven integer counts for non-time-filtered metrics), `TimeSensitiveCounts` (integer counts and a nested execution-completed/failed breakdown for time-filtered metrics), and `CardPermissionFlags` (ten boolean fields, one per card, where `true` means permission denied). All fields default to zero/false.

**SnapshotCounts (Pydantic model)** — `backend/app/schemas/dashboard.py`
- Responsibility: Carry the nine snapshot count values (spanning seven metric cards): agent_types (total count), agent_types_active, agent_types_running, pending_interventions, model_configs, active_schedules, agent_identities, agent_roles, mcp_servers. All integer fields with default 0.

**TimeSensitiveCounts (Pydantic model)** — `backend/app/schemas/dashboard.py`
- Responsibility: Carry the three time-filtered count values: guardrail_breaches (single integer), agent_executions (nested object with completed and failed integers), posture_breaches (single integer). All default to zero.

**CardPermissionFlags (Pydantic model)** — `backend/app/schemas/dashboard.py`
- Responsibility: Carry per-card boolean flags indicating whether the caller lacks permission for that data domain. Ten boolean fields matching each metric card. When `true`, the card should display the permission-denied placeholder.

**DashboardMetricsService** — `backend/app/services/dashboard_metrics_service.py`
- Responsibility: Accept an `AsyncSession` and user claims, then iterate over each data domain to check permission and execute a `COUNT(*)` aggregation query. For snapshot domains, count records matching status/active filters. For time-sensitive domains, additionally filter by a timestamp column within the requested date range (start_time to end_time). Compose all results into a `DashboardSummary` and return it. Must not retrieve full record sets — only aggregate counts. Instrumented with OpenTelemetry spans.

**DashboardRouter** — `backend/app/api/v1/dashboard.py`
- Responsibility: Expose `GET /dashboard/summary` under the `/api/v1` prefix. Accept optional `start_time` and `end_time` query parameters (ISO 8601 datetime strings). If omitted, defaults to start_time = 24 hours ago, end_time = now. Inject JWT claims and database session via FastAPI dependencies. Instantiate `DashboardMetricsService` and delegate to its `aggregate_metrics` method. No endpoint-level `require_permission()` — permission enforcement is per-domain inside the service. Returns 422 for invalid datetime values, 200 with `DashboardSummary` on success, 500 on unexpected errors.

### Frontend Components

**DashboardPage** — `frontend/src/pages/DashboardPage.tsx`
- Responsibility: Top-level dashboard view component. Calls `useDashboardMetrics` hook to fetch aggregated data. Renders the page title/tagline, the "Operational Metrics" section with a responsive grid of seven `StatCard` components, the "Time-Sensitive Metrics" section with `DateRangePicker` and three `TimeSensitiveCard` components, and retains the existing identity provider status cards in a collapsed/de-emphasised secondary section below. Passes `permission_flags` and `isLoading` from the hook to each card. All labels use i18next `t()`.

**StatCard** — `frontend/src/components/dashboard/StatCard.tsx`
- Responsibility: Reusable card component for snapshot (non-time-filtered) metrics. Displays an icon with colour variant, a label, a large numeric value, optional sub-breakdown chips (e.g., "8 active", "3 running"), and a sub-label. Handles four visual states: normal (with data), zero (muted value), loading (skeleton pulse animation), and permission-denied (dashed border, reduced opacity, lock icon overlay, "Permission Denied" label replacing value). Uses MUI 7 `Card`, `Skeleton`, `Typography`, `Box`.

**TimeSensitiveCard** — `frontend/src/components/dashboard/TimeSensitiveCard.tsx`
- Responsibility: Reusable card component for time-filtered metrics. Supports two variants: single-value (one large number, for guardrail/posture breaches) and dual-value (completed/failed split with green/red colouring, for agent executions). Displays a left-border accent to visually distinguish from snapshot cards, and a date range label in italic below the value. Handles the same four visual states as `StatCard`.

**DateRangePicker** — `frontend/src/components/dashboard/DateRangePicker.tsx`
- Responsibility: Date range selection component allowing users to define a custom start date/time and end date/time. Includes date and time (hours/minutes) pickers for both start and end. Provides quick preset buttons for convenience (Last Hour, Last 24 Hours, Last 7 Days) that auto-fill the range. Displays the currently selected range as a formatted label (e.g., "Jul 7 08:00 — Jul 8 08:00"). Exposes `startTime`, `endTime`, `onChange`, and optional `isRefreshing` props. Default values: start = now minus 24 hours, end = now.

**Permission-Denied Placeholder** — Integrated into `StatCard` and `TimeSensitiveCard`
- Responsibility: The permission-denied state is not a standalone component. It is a visual state within `StatCard` and `TimeSensitiveCard`, triggered by an `isPermissionDenied` boolean prop. When active: card border becomes dashed, opacity drops to 0.55, a lock icon overlays the top-right corner, the numeric value is hidden, and a "Permission Denied" label is shown instead. The card container remains visible — operators know the data domain exists even if they cannot access it.

**useDashboardMetrics (hook)** — `frontend/src/hooks/useDashboardMetrics.ts`
- Responsibility: Encapsulate all dashboard data fetching and date range state. Uses React Query's `useQuery` with `queryKey: ['dashboard', 'summary', startTime, endTime]` to fetch via `getDashboardSummary(startTime, endTime)`. Manages `startTime` and `endTime` state internally (default: now minus 24 hours to now) and exposes `setDateRange(startTime, endTime)` for the `DateRangePicker` to call. Returns `data`, `isLoading`, `isError`, `error`, `startTime`, `endTime`, `setDateRange`, `refetch`. Stale time set to 30 seconds.

**getDashboardSummary (API function)** — `frontend/src/api/dashboardApi.ts`
- Responsibility: Thin wrapper around the shared `apiClient` axios instance. Calls `GET /dashboard/summary` with `start_time` and `end_time` query parameters (ISO 8601 strings). Returns a typed `DashboardSummary` promise. Does not catch errors — lets React Query handle error propagation.

**Dashboard types** — `frontend/src/types/dashboard.ts`
- Responsibility: TypeScript interface definitions matching the backend Pydantic models: `DashboardSummary`, `SnapshotCounts`, `TimeSensitiveCounts`, `AgentExecutionsBreakdown`, `CardPermissionFlags`.

## 3. API Changes

### New Endpoint: `GET /api/v1/dashboard/summary`

- **Route**: `GET /dashboard/summary` (mounted under `/api/v1` via the v1 router)
- **Auth**: Requires valid JWT token. The endpoint itself has no `require_permission()` guard — the caller always receives a 200 response. Permission enforcement is per-data-domain inside the service, reflected in the `permission_flags` response field.
- **Query parameters**: `start_time` (optional, ISO 8601 datetime string, default: now minus 24 hours), `end_time` (optional, ISO 8601 datetime string, default: now). Returns 422 for invalid datetime values.
- **Response** (200): `DashboardSummary` JSON object with three top-level keys:
  - `snapshot_counts` — Object with integer fields: `agent_types` (total), `agent_types_active`, `agent_types_running`, `pending_interventions`, `model_configs`, `active_schedules`, `agent_identities`, `agent_roles`, `mcp_servers`.
  - `time_sensitive` — Object with fields: `guardrail_breaches` (int), `agent_executions` (object: `completed` int, `failed` int), `posture_breaches` (int).
  - `permission_flags` — Object with boolean fields (one per card): `agent_types`, `interventions`, `model_configs`, `schedules`, `identities`, `roles`, `mcp_servers`, `guardrail_breaches`, `executions`, `posture_breaches`. A `true` value means permission is **denied** for that card.
- **Response** (401): Standard JWT validation failure.
- **Response** (422): Invalid `start_time` or `end_time` value.
- **Response** (500): Unexpected server error with structured error detail.

### Permission-to-Domain Mapping (Server-Side)

Each data domain within `DashboardMetricsService.aggregate_metrics` calls `PermissionEngine.authorize()` with the module and action below. If denied, the count query is skipped and the corresponding `permission_flags` field is set to `true`.

| Card | Module Constant | Action |
|------|----------------|--------|
| Agent Types (count + active/running) | `RT_AGENT` | `"read"` |
| Agent Executions (completed/failed) | `RT_AGENT` | `"read"` |
| Pending Interventions | `RT_AGENT_HUMAN_INTERVENTION` | `"view"` |
| Model Configurations | `RT_AGENT_MODEL_CONFIGS` | `"read"` |
| Model Usage Posture Breaches | `RT_AGENT_MODEL_CONFIGS` | `"read"` |
| Active Schedules | `RT_AGENT_SCHEDULES` | `"read"` |
| Agent Identities | `RT_AGENT_IDENTITIES` | `"read"` |
| Agent Roles | `RT_AGENT_ROLES` | `"read"` |
| MCP Servers | `RT_INTEGRATION_MCP_HUB` | `"read"` |
| Guardrail Breach Events | `RT_AGENT_TRAILS` | `"read"` |

**Note**: The Human Interventions module uses `"view"` (not `"read"`) as defined in `backend/app/core/resource_types.py`. This differs from the architecture.md mapping which uses `"read"` — the implementation must use the action that matches the manifest (`"view"`).

## 4. State Management

### Frontend State

- **Date range state**: Managed internally by `useDashboardMetrics` hook via `useState<Date | null>` for both `startTime` and `endTime` (default: start = now minus 24 hours, end = now). Exposed as `startTime`, `endTime`, and `setDateRange(start, end)`. Changing the date range updates React Query's `queryKey`, triggering an automatic re-fetch.
- **Dashboard data**: Cached by React Query under key `['dashboard', 'summary', startTime, endTime]`. Stale time set to 30 seconds. No manual cache invalidation needed — the key change on date range update handles re-fetching.
- **Loading states**: Derived from React Query's `isLoading` (initial load) and `isFetching` (re-fetch after date range change). Passed to individual cards to toggle skeleton animations. During date range changes, only time-sensitive cards show loading; snapshot cards remain static because their data is unchanged.
- **Permission flags per card**: Read from `data.permission_flags` and passed to each card's `isPermissionDenied` prop. No frontend permission logic — the backend tells the frontend what to show.
- **Error state**: React Query's `isError` and `error` drive a dashboard-level error banner with a retry button (calls `refetch()` from the query result). Individual card permission denials are not errors.
- **Identity provider status**: Uses separate, existing `useQuery` calls (unchanged from current `DashboardPage`). Not affected by the dashboard summary endpoint.

### Backend State

- No server-side state or caching. Each request to `GET /dashboard/summary` executes fresh count queries. Future optimisation could add Redis caching with cache-busting on data mutation events, but this is out of scope for the current implementation.

## 5. Data Access Patterns

### Backend Aggregation (Server-Side)

All count queries execute on the Control Center server using SQLAlchemy 2 async sessions. No data is transmitted to the frontend except the final aggregate integer counts and boolean permission flags.

**Snapshot-count queries** (no date range filter):
- `agent_types`: `SELECT COUNT(*)` from the agent_types table. Additional filtered counts for `is_active = true` and agent jobs with `status = 'running'`.
- `intervene_requests`: `SELECT COUNT(*)` where `status = 'pending'`.
- `model_configs`: `SELECT COUNT(*)` where `is_disabled = false`.
- `scheduled_jobs`: `SELECT COUNT(*)` where `status = 'active'`.
- `agent_identities`: `SELECT COUNT(*)` from agent_identities table.
- `agent_roles`: `SELECT COUNT(*)` from agent_roles table.
- `mcp_servers`: `SELECT COUNT(*)` from mcp_servers table.

**Time-filtered queries** (date range applied to timestamp column):
- `guardrail_threshold_events`: `SELECT COUNT(*)` where `emitted_at >= start_time AND emitted_at <= end_time`.
- `agent_jobs`: `SELECT COUNT(*)` where `created_at >= start_time AND created_at <= end_time`, grouped by status for completed/failed breakdown.
- `model_usage_postures`: `SELECT COUNT(*)` where `posture_state = 'breached'` and `observed_at >= start_time AND observed_at <= end_time`.

### Frontend Data Access

The frontend makes a single HTTP request: `GET /api/v1/dashboard/summary?start_time=<ISO>&end_time=<ISO>`. No per-card fetching, no client-side counting or filtering from list endpoints, no direct database access. The response contains all ten metric cards' data. On date range change, a new request is issued with the updated `start_time` and `end_time` parameters; React Query automatically manages re-fetching and cache.

## 6. Code Reference Map

### Backend — New Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardSummary` | Pydantic model | Top-level aggregation response with snapshot_counts, time_sensitive, permission_flags | `backend/app/schemas/dashboard.py` |
| `SnapshotCounts` | Pydantic model | Nine snapshot count fields (agent_types total/active/running, interventions, model_configs, schedules, identities, roles, mcp_servers) | `backend/app/schemas/dashboard.py` |
| `TimeSensitiveCounts` | Pydantic model | Time-filtered count fields with nested AgentExecutionsBreakdown (guardrail_breaches, agent_executions, posture_breaches) | `backend/app/schemas/dashboard.py` |
| `AgentExecutionsBreakdown` | Pydantic model | Nested breakdown: completed and failed integer counts | `backend/app/schemas/dashboard.py` |
| `CardPermissionFlags` | Pydantic model | Ten boolean permission-denied flags (one per card) | `backend/app/schemas/dashboard.py` |
| `DashboardMetricsService` | class | Per-domain permission check + count aggregation service | `backend/app/services/dashboard_metrics_service.py` |
| `aggregate_metrics` | async method | Entry point: accepts start_time and end_time datetimes, returns DashboardSummary | `backend/app/services/dashboard_metrics_service.py` |
| `DashboardRouter` | APIRouter | FastAPI APIRouter exposing GET /dashboard/summary | `backend/app/api/v1/dashboard.py` |

### Backend — Modified Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `router` (v1) | APIRouter | Updated to `include_router(DashboardRouter)` | `backend/app/api/v1/__init__.py` |

### Backend — Dependencies (Existing, Unchanged)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_permission` | dependency factory | Permission-engine enforcement (not used at endpoint level for dashboard, only inside service) | `backend/app/api/deps.py` |
| `get_current_claims` | dependency | Extracts JWT claims from request state | `backend/app/api/deps.py` |
| `get_db` | dependency | Provides async database session | `backend/app/db/session.py` |
| `PermissionEngine` | class | Policy-based authorization engine | `backend/app/services/permissions/permission_engine.py` |
| `RT_AGENT` | constant | Resource type: `"agent"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_ROLES` | constant | Resource type: `"agent::roles"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_IDENTITIES` | constant | Resource type: `"agent::identities"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_MODEL_CONFIGS` | constant | Resource type: `"agent::model_configs"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_SCHEDULES` | constant | Resource type: `"agent::schedules"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_TRAILS` | constant | Resource type: `"agent::trails"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_HUMAN_INTERVENTION` | constant | Resource type: `"agent::human_intervention"` | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_MCP_HUB` | constant | Resource type: `"integration::mcp_hub"` | `backend/app/core/resource_types.py` |

### Frontend — New Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `getDashboardSummary` | function | API client function calling GET /dashboard/summary | `frontend/src/api/dashboardApi.ts` |
| `DashboardSummary` | TypeScript interface | Response shape: snapshot_counts, time_sensitive, permission_flags | `frontend/src/types/dashboard.ts` |
| `SnapshotCounts` | TypeScript interface | Snapshot count fields matching backend model | `frontend/src/types/dashboard.ts` |
| `TimeSensitiveCounts` | TypeScript interface | Time-filtered count fields including nested agent_executions | `frontend/src/types/dashboard.ts` |
| `AgentExecutionsBreakdown` | TypeScript interface | Nested completed/failed breakdown inside TimeSensitiveCounts | `frontend/src/types/dashboard.ts` |
| `CardPermissionFlags` | TypeScript interface | Per-card boolean permission-denied flags | `frontend/src/types/dashboard.ts` |
| `useDashboardMetrics` | hook | React Query hook: fetches dashboard data, manages date range state | `frontend/src/hooks/useDashboardMetrics.ts` |
| `StatCard` | component | Snapshot metric card (icon, label, value, sub-breakdowns, loading/permission-denied/zero states) | `frontend/src/components/dashboard/StatCard.tsx` |
| `TimeSensitiveCard` | component | Time-filtered metric card (single/dual value variants, date range label, loading/permission-denied states) | `frontend/src/components/dashboard/TimeSensitiveCard.tsx` |
| `DateRangePicker` | component | Date range picker with date+time inputs and preset shortcuts (Last Hour, 24h, 7d) | `frontend/src/components/dashboard/DateRangePicker.tsx` |

### Frontend — Modified Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardPage` | component | Refactored dashboard page: operational metrics + time-sensitive section + retained IdP status | `frontend/src/pages/DashboardPage.tsx` |

### Frontend — Dependencies (Existing, Unchanged)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `apiClient` | AxiosInstance | Configured axios client with JWT auth interceptors | `frontend/src/api/apiClient.ts` |
| `getIdentityProviders` | function | Existing API function for IdP status cards (unchanged) | `frontend/src/api/systemConfigApi.ts` |
| `getSuperAdminStatus` | function | Existing API function for super admin indicator (unchanged) | `frontend/src/api/systemConfigApi.ts` |

### Test Files — New

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| — | test file | Unit tests for DashboardMetricsService | `backend/tests/test_dashboard_metrics_service.py` |
| — | test file | Integration tests for GET /dashboard/summary endpoint | `backend/tests/test_dashboard_api.py` |
| — | test file | Unit tests for StatCard component | `frontend/src/__tests__/components/dashboard/StatCard.test.tsx` |
| — | test file | Unit tests for TimeSensitiveCard component | `frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx` |
| — | test file | Unit tests for DateRangePicker component | `frontend/src/__tests__/components/dashboard/DateRangePicker.test.tsx` |
| — | test file | Integration tests for DashboardPage | `frontend/src/__tests__/pages/DashboardPage.test.tsx` |
| — | test file | E2E tests for dashboard happy path | `e2e/tests/dashboard.spec.ts` |
