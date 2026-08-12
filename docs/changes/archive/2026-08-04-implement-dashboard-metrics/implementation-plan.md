# Implementation Plan: Dashboard Operational Metrics

## Overview

Replace the current thin dashboard placeholder with a full operational metrics dashboard featuring ten permission-aware metric cards (seven snapshot-count, three time-sensitive), a date range picker for time-filtered data, and retention of the existing identity provider status section. All data aggregation happens server-side via a single new Control Center endpoint; the frontend renders cards based on the response, displaying permission-denied placeholders where access is restricted.

## Task Checklist

### Phase 1 — Backend: Dashboard Aggregation Endpoint + Service
- [x] 1.1 — Create `DashboardSummary` Pydantic model with snapshot_counts, time_sensitive, and permission_flags structures
- [x] 1.2 — Create `DashboardMetricsService` with per-domain permission-checked count aggregation
- [x] 1.3 — Create `DashboardRouter` FastAPI router with `GET /api/v1/dashboard/summary` endpoint
- [x] 1.4 — Register `DashboardRouter` in the v1 API router

### Phase 2 — Frontend: API Client + Hooks
- [x] 2.1 — Add `getDashboardSummary` API client function and TypeScript types for the dashboard response
- [x] 2.2 — Create `useDashboardMetrics` React Query hook with date range state management

### Phase 3 — Frontend: Dashboard Page Components
- [x] 3.1 — Create `StatCard` component (snapshot count card with icon, label, value, sub-label, zero-state, permission-denied state)
- [x] 3.2 — Create `TimeSensitiveCard` component (dual-value execution card variant and single-value breach card variant, with date range label, permission-denied state)
- [x] 3.3 — Create `DateRangePicker` component (start/end date+time picker with preset shortcuts for Last Hour, 24h, 7d)
- [x] 3.4 — Integrate permission-denied placeholder rendering into `StatCard` and `TimeSensitiveCard`
- [x] 3.5 — Refactor `DashboardPage` to render operational metrics grid, time-sensitive section, date range picker, and retained IdP status section

### Phase 4 — Integration: Wire Everything Together
- [x] 4.1 — Wire `DashboardPage` to `useDashboardMetrics` hook, passing date range from `DateRangePicker`
- [x] 4.2 — Implement loading skeleton states on all metric cards during initial fetch and date range changes
- [x] 4.3 — Implement error boundary / fallback for complete API failure (dashboard-level error, not per-card)

### Phase 5 — Testing
- [x] 5.1 — Write unit tests for `DashboardMetricsService` (all permission branches, edge-case counts)
- [x] 5.2 — Write backend integration tests for `GET /api/v1/dashboard/summary` (happy path, permission variations, invalid date range)
- [x] 5.3 — Write frontend unit tests for `StatCard`, `TimeSensitiveCard`, `DateRangePicker` components
- [x] 5.4 — Write frontend integration tests for `DashboardPage` with mocked API (loading, data, permission-denied, zero, error states)
- [x] 5.5 — Write E2E test for the dashboard happy path (page loads, date range change triggers refresh, cards render)

---

## Phase 1 — Backend: Dashboard Aggregation Endpoint + Service

### Task 1.1: Create `DashboardSummary` Pydantic Model

**Done when:**
- A new file `backend/app/schemas/dashboard.py` exists with at minimum these Pydantic v2 models:
  - `SnapshotCounts` — fields for each of the seven snapshot metrics (agent_types total, active, running; pending_interventions; model_configs; active_schedules; agent_identities; agent_roles; mcp_servers). All integer fields, defaults to 0.
  - `TimeSensitiveCounts` — fields for the three time-filtered metrics (guardrail_breaches; agent_executions with completed and failed sub-fields; posture_breaches). All integer fields, defaults to 0.
  - `CardPermissionFlags` — boolean flags matching each card's permission check result (agent_types, interventions, model_configs, schedules, identities, roles, mcp_servers, guardrail_breaches, executions, posture_breaches).
  - `DashboardSummary` — top-level model containing `snapshot_counts: SnapshotCounts`, `time_sensitive: TimeSensitiveCounts`, `permission_flags: CardPermissionFlags`.
- All models use `model_config = ConfigDict(from_attributes=True)` (Pydantic v2 style).
- The schema module is importable without circular dependencies.

### Task 1.2: Create `DashboardMetricsService`

**Done when:**
- A new file `backend/app/services/dashboard_metrics_service.py` exists with a class `DashboardMetricsService`.
- The class accepts `AsyncSession` and user claims as constructor arguments, and exposes a single async method `aggregate_metrics(start_time: datetime, end_time: datetime) -> DashboardSummary`.
- The method queries each data domain's table with a `SELECT COUNT(*)`-style aggregation (no retrieving full record sets).
- For each data domain, it checks permission using the existing `PermissionEngine` before executing the count query. If permission is denied, it sets the corresponding `permission_flags` field to `True` (indicating denied) and skips the count query, leaving the count as 0.
- Permission-to-domain mapping follows the architecture.md table exactly (see `Permission-to-domain mapping` in `docs/changes/implement-dashboard-metrics/architecture.md`).
- **Important note**: The `agent::human_intervention` permission check uses the "view" action (not "read"), as "view" is the action defined in `backend/app/core/resource_types.py`. Verify this against the architecture.md mapping during implementation.
- **Snapshot-count queries** (no date filter): `agent_types` (total + `is_active=true` + jobs with `status='running'`), `intervene_requests` (status='pending'), `model_configs` (is_disabled=false), `scheduled_jobs` (status='active'), `agent_identities`, `agent_roles`, `mcp_servers`.
- **Time-filtered queries** (filtered by start_time to end_time range): `guardrail_threshold_events` (emitted_at within range), `agent_jobs` (completed/failed breakdown by status, created_at within range), `model_usage_postures` (posture_state='breached', observed_at within range).
- If start_time and end_time are not provided, defaults to last 24 hours (now minus 24h to now).

### Task 1.3: Create `DashboardRouter`

**Done when:**
- A new file `backend/app/api/v1/dashboard.py` exists with a class `DashboardRouter`.
- The class has a `router: APIRouter` attribute with prefix `"/dashboard"` and tags `["Dashboard"]`.
- A single endpoint `GET /summary` is defined, accepting:
  - Query parameters `start_time: str | None = None` and `end_time: str | None = None` (ISO 8601 datetime strings, default: last 24 hours).
  - Injected JWT claims via `get_current_claims` dependency.
  - Injected `AsyncSession` via `get_db` dependency.
- The endpoint handler:
  - Validates the datetime parameters and returns 422 for invalid values.
  - Instantiates `DashboardMetricsService` with the session and claims.
  - Calls `aggregate_metrics(start_datetime, end_datetime)` and returns the `DashboardSummary`.
  - Wraps the call in a try/except and returns a structured 500 error for unexpected failures.
- The router does NOT apply a single `require_permission()` at the endpoint level — permission checks are per-domain inside the service.
- No individual card endpoint returns 403; permission-denied cards are indicated via boolean flags in the JSON response.

### Task 1.4: Register `DashboardRouter` in v1 Router

**Done when:**
- In `backend/app/api/v1/__init__.py`, the `DashboardRouter` is imported and included in the v1 router via `router.include_router(DashboardRouter)`.
- The include is placed in the "dashboard" section (new section, above Identity & auth or as a standalone section).
- A `python -m pytest backend/tests/ -x -k "test_router_includes_dashboard"` style check passes (or manual verification that `GET /api/v1/dashboard/summary` appears in the OpenAPI docs).

---

## Phase 2 — Frontend: API Client + Hooks

### Task 2.1: Add Dashboard API Client Function and Types

**Done when:**
- A new file `frontend/src/api/dashboardApi.ts` exists with:
  - An exported function `getDashboardSummary(startTime: string, endTime: string): Promise<DashboardSummary>` that calls `apiClient.get('/dashboard/summary', { params: { start_time: startTime, end_time: endTime } })`.
  - Imported `apiClient` from `frontend/src/api/apiClient.ts` (the injected axios instance).
- A new file `frontend/src/types/dashboard.ts` exists with TypeScript interfaces:
  - `SnapshotCounts` interface matching the Pydantic model fields.
  - `TimeSensitiveCounts` interface with `guardrail_breaches: number`, `agent_executions: { completed: number; failed: number }`, `posture_breaches: number`.
  - `CardPermissionFlags` interface with boolean fields for each of the ten cards.
  - `DashboardSummary` interface containing `snapshot_counts`, `time_sensitive`, `permission_flags`.
- All types are strongly typed, no `any` usage.
- The axios error is not swallowed — it propagates for the React Query hook to handle.

### Task 2.2: Create `useDashboardMetrics` Hook

**Done when:**
- A new file `frontend/src/hooks/useDashboardMetrics.ts` exists with an exported hook `useDashboardMetrics()`.
- The hook manages `startTime` and `endTime` state internally (default: 24 hours ago to now) and exposes a `setDateRange(start: string, end: string)` setter.
- It uses `useQuery` from `@tanstack/react-query` with:
  - `queryKey: ['dashboard', 'summary', startTime, endTime]`
  - `queryFn` calling `getDashboardSummary(startTime, endTime)`
  - `staleTime: 30_000` (30 seconds — data considered fresh for half a minute to avoid refetches on tab switches)
- Returns `{ data, isLoading, isError, error, startTime, endTime, setDateRange, refetch }`.
- The hook re-fetches automatically when `startTime` or `endTime` changes (react-query key invalidation).

---

## Phase 3 — Frontend: Dashboard Page Components

### Task 3.1: Create `StatCard` Component

**Done when:**
- A new file `frontend/src/components/dashboard/StatCard.tsx` exists with an exported `StatCard` component.
- Props interface:
  - `icon: ReactNode` — the card icon
  - `label: string` — descriptive label (e.g., "Agent Types")
  - `value: number` — the count to display
  - `subLabel?: string` — optional sub-label text shown below the value
  - `subBreakdowns?: Array<{ label: string; color?: string }>` — optional array of small breakdown chips (e.g., "8 active", "3 running")
  - `isLoading: boolean` — shows skeleton pulse animation
  - `isPermissionDenied: boolean` — shows lock icon, dashed border, "Permission Denied" text, hides value
  - `isZero?: boolean` — subtly mutes the value colour for zero counts
  - `colorVariant?: 'blue' | 'green' | 'purple' | 'orange' | 'red' | 'teal' | 'amber' | 'slate'` — icon background colour
- Visual behaviour matches the prototype (`docs/changes/implement-dashboard-metrics/prototype/index.html`):
  - Icon: 40x40 rounded square with colour variant background.
  - Label: uppercase, 12px, secondary text colour.
  - Value: 28px bold, primary text colour (muted when zero or permission denied).
  - Sub-breakdowns: small rounded pill chips.
  - Loading: skeleton pulse on icon, label, and value placeholders.
  - Permission denied: dashed border, reduced opacity (0.55), lock icon overlay top-right, "Permission Denied" label replaces value.
- Uses MUI 7 components (`Card`, `Box`, `Typography`, `Skeleton`) consistent with the existing codebase.
- All display text goes through i18next `t()`.

### Task 3.2: Create `TimeSensitiveCard` Component

**Done when:**
- A new file `frontend/src/components/dashboard/TimeSensitiveCard.tsx` exists with an exported `TimeSensitiveCard` component.
- Supports two display variants via props:
  - **Single-value variant**: for Guardrail Breaches and Posture Breaches — shows a single large number.
  - **Dual-value variant**: for Agent Executions — shows "completed / failed" with green/red colouring.
- Props interface:
  - `variant: 'single' | 'dual'`
  - `icon: ReactNode`, `label: string`
  - `value: number` (for single variant)
  - `completed?: number`, `failed?: number` (for dual variant)
  - `dateRangeLabel: string` — e.g., "Jul 7 08:00 — Jul 8 08:00", displayed below the value in italic
  - `isLoading`, `isPermissionDenied`, `colorVariant` — same as StatCard
- Visual behaviour matches prototype:
  - Left border accent (3px solid primary colour) to distinguish from snapshot cards.
  - Dual-value: completed in green, separator "/", failed in red.
  - Period label shown in italic below the value.
  - Same loading skeleton and permission-denied states as StatCard.
- Uses MUI 7 components.

### Task 3.3: Create `DateRangePicker` Component

**Done when:**
- A new file `frontend/src/components/dashboard/DateRangePicker.tsx` exists with an exported `DateRangePicker` component.
- Props interface:
  - `startTime: Date | null` — currently selected start date/time
  - `endTime: Date | null` — currently selected end date/time
  - `onChange: (start: Date, end: Date) => void` — callback on range change
  - `isRefreshing?: boolean` — disables interaction during refresh
- Renders start and end date+time pickers with quick preset shortcut buttons:
  - **Last Hour**, **Last 24 Hours**, **Last 7 Days** — clicking auto-fills the range and calls onChange
- Active preset button has filled primary background; inactive buttons have outline style.
- Displays the formatted date range label (e.g., "Jul 7 08:00 — Jul 8 08:00").
- Default range on mount: start = now minus 24 hours, end = now.
- Visual behaviour matches prototype: date+time inputs in a bordered group, preset buttons alongside, with a refresh button.
- All labels go through i18next `t()`.

### Task 3.4: Integrate Permission-Denied Placeholder

**Done when:**
- The `StatCard` and `TimeSensitiveCard` components already handle `isPermissionDenied` prop (per Task 3.1 and 3.2).
- No separate `PermDeniedPlaceholder` component is needed — the placeholder is integrated directly into the card components.
- **Done condition**: When `isPermissionDenied` is true, both card types render the dashed-border, reduced-opacity, lock-icon state exactly as shown in the prototype. The card is never hidden.

### Task 3.5: Refactor `DashboardPage`

**Done when:**
- The existing `frontend/src/pages/DashboardPage.tsx` is updated (not replaced from scratch) to:
  - **Retain** the existing page title ("Dashboard") and tagline from i18next.
  - **Retain** the existing identity provider status cards (user provider, agent provider, super admin) and the "Configure Identity Providers" quick-action button — but moved to a de-emphasised secondary section below the operational metrics, separated by a section title.
  - **Add** an "Operational Metrics" section with a 4-column responsive grid of seven `StatCard` components (Agent Types, Pending Interventions, Model Configurations, Active Schedules, Agent Identities, Agent Roles, MCP Servers).
  - **Add** a "Time-Sensitive Metrics" section with the `DateRangePicker` above a 3-column responsive grid of three `TimeSensitiveCard` components (Guardrail Breach Events, Agent Executions, Model Usage Posture Breaches).
  - **Use** the `useDashboardMetrics` hook to fetch all data.
  - **Pass** `permission_flags` from the API response to each card's `isPermissionDenied` prop.
  - **Pass** `isLoading` from the hook to each card's `isLoading` prop.
  - **Wire** `DateRangePicker` startTime/endTime/onChange to the hook's `startTime`/`endTime`/`setDateRange`.
  - All card labels, section titles, and period labels go through i18next `t()`.
  - The responsive grid collapses: 4 columns → 3 (below 1400px) → 2 (below 1024px) → 1 (below 640px) for snapshot cards; 3 → 2 → 1 for time-sensitive cards.
- The page-level loading state shows skeleton cards (not a single spinner).

---

## Phase 4 — Integration: Wire Everything Together

### Task 4.1: Wire DashboardPage with API Hook

**Done when:**
- `DashboardPage` calls `useDashboardMetrics()` and destructures the return value.
- `DateRangePicker` onChange calls `setDateRange` which triggers a re-fetch via the query key change.
- All ten metric cards receive their data from the hook's `data` response.
- The identity provider status section continues to use its existing `useQuery` calls unchanged.

### Task 4.2: Implement Loading Skeleton States

**Done when:**
- During initial page load (first visit, no cached data), all ten metric cards display the skeleton loading animation (pulsing placeholder blocks for icon, label, and value) matching the prototype.
- During date range changes, only the three time-sensitive cards show a loading/refreshing state (snapshot cards remain static since they are not date-dependent).
- The `isLoading` boolean from the hook drives the skeleton state.

### Task 4.3: Implement Error Handling

**Done when:**
- If the `GET /api/v1/dashboard/summary` call fails entirely (network error, 500):
  - The operational metrics section shows a single error banner/alert (not ten individual error states) with a retry button that re-fetches the query.
  - The identity provider status section remains unaffected (separate API call).
- If the call returns successfully but individual cards have `permission_denied: true`, those cards show the permission-denied placeholder — this is NOT an error state.
- No 403 errors appear in the UI; the backend never returns 403 for this endpoint.
- The `apiClient` interceptor's 401 redirect behaviour (for expired tokens) is not affected.

---

## Phase 5 — Testing

### Task 5.1: DashboardMetricsService Unit Tests

**Done when:**
- A new test file `backend/tests/test_dashboard_metrics_service.py` exists with tests covering:
  - `aggregate_metrics` returns correct snapshot counts when all permissions granted.
  - `aggregate_metrics` returns correct time-filtered counts for different date ranges.
  - `aggregate_metrics` sets `permission_flag = true` for domains the user lacks permission on (mock PermissionEngine to deny specific modules).
  - `aggregate_metrics` handles empty database (all counts zero, all permissions granted).
  - `aggregate_metrics` with custom date range returns correctly computed counts.
- Tests use an in-memory or test database with seeded data.
- Tests mock `PermissionEngine` (not the database) to control permission outcomes.

### Task 5.2: Dashboard API Integration Tests

**Done when:**
- A new test file `backend/tests/test_dashboard_api.py` exists with tests covering:
  - `GET /api/v1/dashboard/summary` without auth returns 401.
  - `GET /api/v1/dashboard/summary?start_time=<ISO>&end_time=<ISO>` with auth returns 200 and valid `DashboardSummary` JSON.
  - Response contains all required fields (`snapshot_counts`, `time_sensitive`, `permission_flags`).
  - Query parameter validation: invalid datetime returns 422.
  - A user with permission to only some domains gets correct `permission_flags` (some true, some false).
  - No endpoint-level 403 — permission denials are in the response body, not the HTTP status.
- Tests use the FastAPI `TestClient` with a test database.

### Task 5.3: Frontend Component Unit Tests

**Done when:**
- New test files under `frontend/src/__tests__/components/dashboard/` exist:
  - `StatCard.test.tsx` — tests rendering with data, zero state, loading skeleton, permission-denied state, sub-breakdown chips.
  - `TimeSensitiveCard.test.tsx` — tests single-value variant, dual-value variant (completed/failed), date range label display, loading state, permission-denied state.
  - `DateRangePicker.test.tsx` — tests rendering date/time inputs, preset shortcut buttons, default range, onChange callback, formatted label.
- All tests use Vitest + React Testing Library.

### Task 5.4: Frontend DashboardPage Integration Tests

**Done when:**
- A new or updated test file `frontend/src/__tests__/pages/DashboardPage.test.tsx` exists with tests covering:
  - Renders all ten metric cards when data is loaded.
  - Shows loading skeletons during fetch.
  - Shows permission-denied state on cards where `permission_flags` indicate denied.
  - Date range picker change triggers new API call with updated start/end parameters.
  - Zero counts display "0" (not blank, not hidden).
  - Identity provider status section is present below operational metrics.
  - API error shows error banner with retry button.
- Tests mock `getDashboardSummary` using `vi.mock` or MSW.

### Task 5.5: E2E Dashboard Tests

**Done when:**
- A new test file `e2e/tests/dashboard.spec.ts` exists with at least one test:
  - Navigates to `/`, verifies the dashboard page loads without console errors.
  - Verifies at least one metric card is visible with a non-zero value (or zero is displayed).
  - Changes the date range (e.g., via a preset shortcut), verifies the time-sensitive card values update.
  - (Optional) If feasible, verifies the IdP status section is present.
- Uses Playwright test runner.

---

## Completion Checklist

- [x] `GET /api/v1/dashboard/summary` endpoint returns 200 with valid JSON in OpenAPI docs
- [x] All ten metric cards render on the dashboard page with correct labels and values
- [x] Date range picker changes refresh time-sensitive cards without reloading snapshot cards
- [x] Default date range is last 24 hours on first visit
- [x] Permission-denied cards show lock icon and "Permission Denied" label instead of value
- [x] Permission-denied cards are never hidden — they remain visible with muted styling
- [x] Zero counts display "0" (not blank, not hidden)
- [x] Loading skeletons appear on first load for all cards
- [x] Identity provider status cards and quick-action button are retained below operational metrics
- [x] No 403 errors appear in the browser console during normal dashboard use
- [x] Dashboard loads within 2 seconds on first visit (cold cache within 5 seconds)
- [x] All UI text goes through i18next `t()` — no hardcoded English strings
- [x] All backend and frontend unit tests pass
- [x] E2E test passes
- [x] No regressions in existing tests
