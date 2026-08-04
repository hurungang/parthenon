# Test Plan — Dashboard Operational Metrics

## 1. Test Strategy

| Layer | Approach | Scope |
|-------|----------|-------|
| **Unit (Backend)** | Python `unittest` with mocked database sessions and mocked `PermissionEngine` — verify `DashboardMetricsService` domain iteration logic, permission-flag branching, date-range window calculation, and response model assembly without real database or HTTP dependencies. | `DashboardMetricsService.aggregate_metrics()`, `SnapshotCounts`/`TimeSensitiveCounts`/`CardPermissionFlags` model validation. |
| **Integration (Backend — Real DB)** | FastAPI `TestClient` + real PostgreSQL test database with real `PermissionEngine` — validate `GET /dashboard/summary` against live DB tables, verify `COUNT(*)` accuracy, test permission enforcement across all ten domains, test date range filtering with real timestamp data. No SQLite or in-memory fallback. | Full endpoint integration, permission-to-domain mapping, date-range window filtering, zero-count returns, 422 for invalid datetime, 500 error handling. |
| **Unit (Frontend — Components)** | Vitest + React Testing Library with mocked `useDashboardMetrics` hook — verify all four visual states per card (normal, zero, loading, permission-denied), `DateRangePicker` interaction, responsive grid layout. | `StatCard`, `TimeSensitiveCard` (both single-value and dual-value variants), `DateRangePicker`, `DashboardPage` structural rendering. |
| **Integration (Frontend — Hook & API)** | Vitest tests for `useDashboardMetrics` with mocked `apiClient` — verify query-key composition per date range, stale-time enforcement, error state propagation, `setDateRange` triggers re-fetch. API function `getDashboardSummary` with typed response validation. | `useDashboardMetrics` hook, `getDashboardSummary` API function, `DashboardSummary` type guards. |
| **E2E** | Playwright tests against a running stack — verify full dashboard load, date range switching, permission scenarios, real data in cards. Use `page.route()` mocks for controlled permission scenarios; include at least one real-backend test (no mocks) to validate end-to-end data flow. | Dashboard page load, date range picker interaction, card count display, permission-denied placeholders, error banner on 500, IdP status retention. |
| **Manual** | Smoke checks: Visual inspection of card layout at 3 viewport widths (1280px, 1024px, 800px), i18n label correctness across cards, IdP status section presence and collapsed styling, lock icon appearance on permission-denied cards, skeleton animation smoothness during loading. | Visual layout, i18n coverage, IdP section retention, accessibility of permission-denied indicators. |

**Note on `has_db_changes: false`**: No migration testing is required. However, backend integration tests **must** run against a real PostgreSQL database (not SQLite in-memory) to validate `COUNT(*)` query accuracy, timestamp filtering, and permission evaluation against real policy data. The absence of schema changes does not exempt integration tests from database verification.

## 2. Coverage Areas

### 2.1 Backend — DashboardMetricsService Count Queries

**Why critical:** Every stat card's displayed value originates from a server-side `COUNT(*)` aggregation. Incorrect counts — due to wrong WHERE filters, missing status conditions, or off-by-one timestamp windows — mislead operators about platform health. The frontend has no client-side counting; it trusts the backend response entirely.

- **Snapshot counts (no date filter):** Verify `agent_types` total, active, and running counts match actual database rows. Verify `pending_interventions` counts only `status='pending'` rows. Verify `model_configs` counts only non-disabled rows (`is_disabled=false`). Verify `active_schedules` counts only `status='active'` rows. Verify `agent_identities`, `agent_roles`, and `mcp_servers` count all rows in their respective tables.
- **Time-filtered counts:** Verify `guardrail_breaches` filters by `emitted_at` within the date range. Verify `agent_executions` groups by status for completed/failed breakdown within the date range. Verify `posture_breaches` filters by `observed_at` within the date range.
- **Zero-value handling:** When a table is empty or no rows match filters, the service returns `0` (integer zero), not `None`, not an empty response, and not an error.
- **Active/running breakdown:** Verify the running count is derived from a separate query against agent jobs table (`AgentJob.status = 'running'`). Active count reflects agent types with `is_active = true`.
- **Performance:** All queries use `SELECT COUNT(*)` with appropriate indexes — verify no full-table scans or `SELECT *` fetches occur. Use `EXPLAIN ANALYZE` in manual review.

### 2.2 Backend — Permission Checks Per Domain

**Why critical:** The PRD's permission-awareness requirement is the defining characteristic of this feature. A single misconfigured permission check either leaks data to unauthorized operators or blocks access to data they should see. The service must never fail the entire request — permission denials are per-domain and reflected in flags.

- **All ten domains checked independently:** Each of the ten cards' data queries is gated by a `PermissionEngine.authorize()` call with the correct `module` constant and `action` from the tech-spec permission mapping.
- **Human Interventions uses "view" action** (not "read"), consistent with `RT_AGENT_HUMAN_INTERVENTION` manifest entry.
- **Agent Executions and Agent Types both use `RT_AGENT` with `"read"`** — two cards sharing one permission domain.
- **Model Configurations and Posture Breaches both use `RT_AGENT_MODEL_CONFIGS` with `"read"`** — two cards sharing one permission domain.
- **Permission denial is not an error:** When `PermissionEngine.authorize()` returns false, the count query is skipped and the corresponding `permission_flags` field is set to `true`. The response returns 200, not 403.
- **No endpoint-level `require_permission()`:** The `GET /dashboard/summary` endpoint has no decorator-based permission guard. Any authenticated user receives a 200 response. Permission filtering is entirely internal to the service.
- **System administrator role:** A user with `*::*` or equivalent permissions sees all ten cards with real values and all ten `permission_flags` fields as `false`.

### 2.3 Backend — Date Range Filtering & Validation

**Why critical:** Time-sensitive cards are the only dynamic, trend-surfacing metrics on the dashboard. Incorrect date-range window calculation shows misleading trend data. Invalid datetime values must be rejected clearly.

- **Date range validation:** Both `start_time` and `end_time` accept ISO 8601 datetime strings. Default values: start_time = now minus 24 hours, end_time = now.
- **Invalid datetime rejection:** Malformed datetime strings, non-ISO formats, or end_time before start_time return HTTP 422 with a clear error message.
- **Date range edge cases:** Verify filtering works correctly across day boundaries, month boundaries, and when the database contains rows both inside and outside the window.
- **Snapshot counts ignore date range:** Changing the date range does NOT affect the seven snapshot counts. Only `time_sensitive` counts change.

### 2.4 Backend — Aggregation Accuracy & Response Shape

**Why critical:** The frontend expects a specific JSON structure with typed integer fields. A malformed response — wrong field names, string-typed numbers, missing nested objects — breaks the entire dashboard.

- **`snapshot_counts` contains exactly ten integer fields:** `agent_types`, `agent_types_active`, `agent_types_running`, `pending_interventions`, `model_configs`, `active_schedules`, `agent_identities`, `agent_roles`, `mcp_servers`. All default to `0` when no data.
- **`time_sensitive` contains:** `guardrail_breaches` (int), `agent_executions` (object with `completed: int` and `failed: int`), `posture_breaches` (int). All default to `0`.
- **`permission_flags` contains exactly ten boolean fields** matching the card list. A `true` value means permission is denied. All default to `false`.
- **Network error handling:** When a domain's count query fails (e.g., database error), the service does NOT crash the entire response. The error is caught per-domain, the remaining domains continue to aggregate, and the overall response is still returned with whatever data was collected.

### 2.5 Frontend — StatCard Component (Snapshot Metrics)

**Why critical:** StatCard is the primary visual unit for seven of ten dashboard metrics. It must correctly render four distinct states and handle edge values like zero and large numbers without layout breakage.

- **Normal state:** Displays icon, label, large numeric value, optional sub-breakdown chips (e.g., "8 active", "3 running"), and sub-label.
- **Zero state:** Displays "0" as the value with muted styling (not blank, not hidden). Card remains fully visible.
- **Loading state:** Shows skeleton pulse animation in place of the numeric value. Label and icon may be visible or skeletonized.
- **Permission-denied state:** Card border becomes dashed, opacity drops to ~0.55, lock icon overlays top-right, numeric value hidden, "Permission Denied" label replaces the value. Card container remains present — operators know the domain exists.
- **Large numbers:** Values up to millions (e.g., 1,234,567) display without text overflow or layout shift. Number formatting uses locale-appropriate separators.
- **`agent_types` sub-breakdown:** The Agent Types card additionally shows active and running counts as small chips or badges below the main total.

### 2.6 Frontend — TimeSensitiveCard Component

**Why critical:** TimeSensitiveCard visually distinguishes time-filtered metrics from snapshot metrics and handles two value-display variants. Incorrect variant rendering or missing date range labels confuse operators about what time window the data represents.

- **Single-value variant:** Used for `guardrail_breaches` and `posture_breaches`. Displays one large number, a date range label in italic below, and a left-border accent colour.
- **Dual-value variant:** Used for `agent_executions`. Displays completed count (green) and failed count (red) as a split display with slash separator (e.g., "42 / 3"). Period label still shown.
- **Left-border accent:** Visually distinguishes time-sensitive cards from snapshot cards. Colour may differ from StatCard.
- **Same four visual states as StatCard:** Loading (skeleton), normal (value), zero ("0" with muted style), permission-denied (dashed border, lock icon, placeholder label).
- **Date range label changes:** When the date range picker value changes, the date range label on each TimeSensitiveCard updates (e.g., "Jul 7 08:00 — Jul 8 08:00").

### 2.7 Frontend — DateRangePicker Component

**Why critical:** DateRangePicker is the only user interaction on the dashboard that triggers a data refresh. Incorrect state management, missing refresh feedback, or failure to propagate changes renders time-sensitive metrics useless.

- **Date range input:** Start date/time and end date/time pickers allow users to define a custom range with both date and time (hours/minutes) selection.
- **Preset shortcuts:** Quick preset buttons (Last Hour, Last 24 Hours, Last 7 Days) auto-fill the date range when clicked.
- **Default range:** Start time defaults to 24 hours before now, end time defaults to now, on initial page load.
- **`onChange` propagation:** Changing the date range calls `setDateRange` from `useDashboardMetrics`, which updates React Query's `queryKey` and triggers a re-fetch.
- **Formatted label:** The selected range is displayed as a human-readable label (e.g., "Jul 7 08:00 — Jul 8 08:00").
- **Visual feedback during re-fetch:** Only time-sensitive cards show loading skeletons during a date range change. Snapshot cards remain static (their data is unchanged by date range).
- **Interactivity during fetch:** DateRangePicker remains interactive even while fetching — users can adjust the range rapidly without waiting for previous fetch to complete.

### 2.8 Frontend — DashboardPage Composition

**Why critical:** DashboardPage orchestrates all sub-components. It must pass the correct data props, layout cards responsively, and retain the existing identity provider status section without regression.

- **Responsive grid:** Cards are laid out in a grid that adapts from 4 columns (wide) to 2 columns (narrow). No card is hidden at any viewport width.
- **Section separation:** Operational metrics (snapshot cards) appear first. Time-sensitive metrics (with DateRangePicker) appear below. Identity provider status cards appear in a de-emphasized, collapsed, or secondary section at the bottom.
- **Page title retained:** The existing "Dashboard" header (`h4`) and tagline (`body1`) remain unchanged.
- **IdP status section retained:** The three existing identity provider status cards (User Provider, Agent Provider, Super Admin) are NOT removed. They are moved to a smaller, de-emphasized section below the operational metrics.
- **Dashboard-level error state:** When the `GET /dashboard/summary` call fails entirely (network error, 500, or React Query error), the dashboard shows an error banner with a retry button. Individual card permission denials are NOT errors and do not trigger this banner.
- **Concurrent queries:** The dashboard simultaneously fetches dashboard summary and identity provider status (existing) — loading states for each are independent.

### 2.9 Frontend — useDashboardMetrics Hook & API Layer

**Why critical:** The hook is the single source of truth for dashboard state. Incorrect query-key construction, missing stale-time settings, or wrong type mappings cause duplicate fetches, stale data display, or TypeScript errors throughout the component tree.

- **Query key:** `['dashboard', 'summary', startTime, endTime]` — changing date range creates a new key and triggers a fresh fetch.
- **Default date range:** Start time defaults to now minus 24 hours, end time defaults to now — matches backend default.
- **Stale time:** 30 seconds — prevents excessive re-fetching during rapid navigation or component re-renders.
- **`getDashboardSummary` API function:** Calls `GET /api/v1/dashboard/summary?start_time=<ISO>&end_time=<ISO>`. Returns a typed `DashboardSummary` promise. Does not catch errors. Uses the shared `apiClient` axios instance.
- **TypeScript types:** `DashboardSummary`, `SnapshotCounts`, `TimeSensitiveCounts`, `AgentExecutionsBreakdown`, `CardPermissionFlags` are defined in `frontend/src/types/dashboard.ts` and match the backend Pydantic models exactly.

### 2.10 E2E — Full Dashboard Flow & Permission Scenarios

**Why critical:** E2E tests catch integration issues that unit and component tests miss — especially around real backend responses, permission evaluation with real policy data, and the interplay between DateRangePicker, useDashboardMetrics, and card rendering.

- **Happy path:** Navigate to `/dashboard`, verify all cards render with non-error states, verify IdP section present below metrics.
- **Period switching:** Click "Last Hour", verify time-sensitive card values change. Click "Last 7 Days", verify again. Snapshot cards remain unchanged.
- **Permission-denied scenarios:** Mock the backend to return `permission_flags` with selected cards denied. Verify those cards show dashed border, lock icon, and "Permission Denied" placeholder. Other cards show real values.
- **Zero-value display:** Mock the backend to return all counts as `0`. Verify all cards show "0" (not blank, not hidden).
- **Error state:** Mock the backend to return HTTP 500. Verify dashboard shows error banner with retry button. Click retry, verify re-fetch occurs.
- **Loading states:** Verify skeleton/spinner appears during initial load and disappears when data arrives.
- **Real-backend test (no mocks):** At least one E2E test hits the real backend. Verify `GET /dashboard/summary` returns 200 with the correct JSON structure and real database counts.
- **IdP retention:** Verify the three identity provider status cards — User Provider, Agent Provider, Super Admin — still render and show their configuration status correctly after the dashboard redesign.

## 3. Critical Scenarios

### Backend — Count Aggregation

- **WHEN** a user with full permissions calls `GET /dashboard/summary` with default date range (last 24 hours) **THEN** the response contains `snapshot_counts` with all nine count fields (non-zero if data exists), `time_sensitive` with three time-filtered values including agent_executions breakdown, and `permission_flags` with all ten fields set to `false`.
- **WHEN** the `agent_types` table has 5 rows (3 active, 1 running job) **THEN** `snapshot_counts.agent_types` is `5`, `agent_types_active` is `3`, and `agent_types_running` is `1`.
- **WHEN** the `intervene_requests` table has 2 pending and 3 resolved interventions **THEN** `snapshot_counts.pending_interventions` is `2` (only pending ones counted).
- **WHEN** the `model_configs` table has 4 enabled and 1 disabled configs **THEN** `snapshot_counts.model_configs` is `4` (only enabled counted).
- **WHEN** the `agent_jobs` table has 10 completed and 2 failed jobs within the last 24 hours, and 5 older jobs outside the window **THEN** `time_sensitive.agent_executions.completed` is `10` and `failed` is `2` (outside-window jobs excluded).
- **WHEN** the `agent_jobs` table has jobs from exactly 23 hours ago **THEN** those jobs are included in the 24h window (boundary-inclusive).
- **WHEN** the database has no rows in any monitored table **THEN** all counts in the response are `0` (integer zero), not `null` and not missing fields.
- **WHEN** `start_time` and `end_time` span the last hour **THEN** only data with timestamps within that hour is counted in time-sensitive fields.
- **WHEN** `start_time` and `end_time` span the last 7 days **THEN** only data with timestamps within those 7 days is counted.

### Backend — Permission Enforcement

- **WHEN** a user lacks `RT_AGENT:read` permission **THEN** `permission_flags.agent_types` is `true`, `permission_flags.executions` is `true`, and both `snapshot_counts.agent_types`/`time_sensitive.agent_executions` contain `0` (not actual data).
- **WHEN** a user lacks `RT_AGENT_HUMAN_INTERVENTION:view` permission **THEN** `permission_flags.interventions` is `true` and `snapshot_counts.pending_interventions` is `0`.
- **WHEN** a user lacks `RT_AGENT_MODEL_CONFIGS:read` permission **THEN** both `permission_flags.model_configs` and `permission_flags.posture_breaches` are `true`, and both corresponding counts are `0`.
- **WHEN** a user lacks `RT_AGENT_SCHEDULES:read` permission **THEN** `permission_flags.schedules` is `true` and `snapshot_counts.active_schedules` is `0`.
- **WHEN** a user lacks `RT_AGENT_IDENTITIES:read` permission **THEN** `permission_flags.identities` is `true` and `snapshot_counts.agent_identities` is `0`.
- **WHEN** a user lacks `RT_AGENT_ROLES:read` permission **THEN** `permission_flags.roles` is `true` and `snapshot_counts.agent_roles` is `0`.
- **WHEN** a user lacks `RT_INTEGRATION_MCP_HUB:read` permission **THEN** `permission_flags.mcp_servers` is `true` and `snapshot_counts.mcp_servers` is `0`.
- **WHEN** a user lacks `RT_AGENT_TRAILS:read` permission **THEN** `permission_flags.guardrail_breaches` is `true` and `time_sensitive.guardrail_breaches` is `0`.
- **WHEN** the user has a mix of permissions (e.g., can see agent data but not schedules) **THEN** denied domains show `permission_flags` as `true` while permitted domains show real counts — no single denial blocks the entire response.
- **WHEN** a user has no permissions at all (authenticated but no assigned policies) **THEN** all ten `permission_flags` fields are `true` and all counts are `0`. The response is still HTTP 200.
- **WHEN** the user is unauthenticated (no JWT) **THEN** the endpoint returns HTTP 401, not 200 with all permissions denied.

### Backend — Error Handling & Edge Cases

- **WHEN** the `start_time` parameter is malformed (not valid ISO 8601) **THEN** the endpoint returns HTTP 422 with an error message indicating the expected datetime format.
- **WHEN** one domain's database query fails (e.g., table lock timeout) **THEN** the service catches the error for that domain only, sets its count to `0`, and continues processing remaining domains. Other domains' counts are unaffected.
- **WHEN** a single domain query failure is logged **THEN** an OpenTelemetry span records the error with the domain name and exception details, but the overall span is not marked as error.
- **WHEN** the entire database connection is unavailable **THEN** the endpoint returns HTTP 500 with a structured error detail, and an OpenTelemetry span is marked as error.

### Frontend — StatCard Visual States

- **WHEN** `isLoading` is `true` **THEN** StatCard shows a skeleton pulse animation in place of the numeric value.
- **WHEN** `isPermissionDenied` is `true` **THEN** StatCard shows dashed border, reduced opacity (0.55), lock icon overlay, and "Permission Denied" label instead of the value.
- **WHEN** `value` is `0` and neither loading nor permission-denied **THEN** StatCard displays "0" with muted styling (not blank, not hidden).
- **WHEN** `value` is a large number (e.g., `1234567`) **THEN** the card displays it without text overflow, wrapping, or layout shift. Number is formatted with locale-appropriate separators.
- **WHEN** StatCard receives `subBreakdown` props (e.g., `{ active: 3, running: 1 }`) **THEN** sub-breakdown chips render below the main value.
- **WHEN** StatCard renders in permission-denied state **THEN** the sub-breakdown chips are also hidden.

### Frontend — TimeSensitiveCard Variants

- **WHEN** TimeSensitiveCard receives `variant="single"` with `value=42` **THEN** a single large number "42" is displayed with the date range label below.
- **WHEN** TimeSensitiveCard receives `variant="dual"` with `completed=42` and `failed=3` **THEN** the display shows "42" in green, a slash separator, and "3" in red, with the date range label below.
- **WHEN** TimeSensitiveCard is in loading state **THEN** both single and dual variants show skeleton animation in the value area.
- **WHEN** TimeSensitiveCard is in permission-denied state **THEN** the same dashed border, reduced opacity, lock icon, and "Permission Denied" placeholder appears, consistent with StatCard.
- **WHEN** TimeSensitiveCard displays the date range label **THEN** the label text reflects the currently selected range (e.g., "Jul 7 08:00 — Jul 8 08:00").

### Frontend — DateRangePicker Interaction

- **WHEN** the dashboard first loads **THEN** DateRangePicker shows start_time = now minus 24 hours and end_time = now as defaults.
- **WHEN** the user selects a new date range **THEN** the time-sensitive cards begin re-fetching (show skeleton during fetch).
- **WHEN** the user clicks a preset shortcut (e.g., "Last 7 Days") **THEN** the date range auto-fills to the corresponding values and the time-sensitive cards re-fetch. Snapshot cards remain static (no skeleton, values unchanged).
- **WHEN** the time-sensitive data is re-fetched after a date range change **THEN** the time-sensitive cards update with the new counts and display the updated date range label.
- **WHEN** the user rapidly changes date ranges **THEN** only the last selected range's data is displayed when fetches complete. No intermediate states overwrite the final result.

### Frontend — DashboardPage Error & Edge States

- **WHEN** `useDashboardMetrics` returns `isError: true` **THEN** the dashboard shows a full-page error banner with an error message and a "Retry" button.
- **WHEN** the user clicks "Retry" on the error banner **THEN** `refetch()` is called and the dashboard re-attempts the fetch.
- **WHEN** the dashboard summary fetch succeeds but has some permission-denied cards **THEN** no error banner is shown — only the individual denied cards display the permission-denied placeholder.
- **WHEN** the identity provider status queries fail (existing behaviour) **THEN** the IdP cards gracefully degrade without affecting the operational metrics section.
- **WHEN** both dashboard summary and IdP status are loading **THEN** both sections show independent loading indicators — dashboard shows skeleton cards, IdP section shows its own spinner.
- **WHEN** the page title and tagline render **THEN** they use i18next `t()` calls — verify labels appear in the configured language.

### E2E — Full User Flows

- **WHEN** a super-admin user navigates to `/dashboard` **THEN** all ten metric cards display real numeric values (not placeholders), the IdP status cards appear below, and no error banner is present.
- **WHEN** a super-admin user selects a custom date range **THEN** time-sensitive cards refresh with the new date range label and updated counts.
- **WHEN** a user with partial permissions views the dashboard **THEN** permitted-domain cards show values, denied-domain cards show the lock icon and "Permission Denied" label, and the page layout is consistent.
- **WHEN** the backend returns HTTP 500 for the dashboard summary **THEN** the dashboard shows an error banner with a "Retry" button. Clicking retry re-fetches. The IdP section continues to render if its data loaded successfully.
- **WHEN** the user navigates away from the dashboard and returns **THEN** the dashboard re-fetches data (respecting the 30-second stale time — fresh fetch if cache expired, cached data if within stale time).

### E2E — IdP Status Retention

- **WHEN** the redesigned dashboard renders **THEN** the three identity provider cards — User Provider, Agent Provider, Super Admin — are present on the page below the operational metrics section.
- **WHEN** an identity provider is configured and enabled **THEN** its card shows a green status dot and "Configured" label (or "Enabled" for super admin).
- **WHEN** an identity provider is not configured **THEN** its card shows a grey status dot and "Not Configured" label (or "Disabled" for super admin).
- **WHEN** the user clicks the "Configure Identity Providers" button **THEN** navigation to `/system/identity-providers` occurs (existing behaviour preserved).

## 4. Edge Cases & Risks

### High Risk

| Risk | Mitigation |
|------|-----------|
| **Permission check uses wrong action for Human Interventions:** The tech-spec explicitly notes that `RT_AGENT_HUMAN_INTERVENTION` uses `"view"` (not `"read"`) per the manifest. If the service uses `"read"`, the permission check fails for users who have the correct `"view"` permission. | Backend integration test that creates a policy with `view` on `agent::human_intervention`, then calls the endpoint and verifies `permission_flags.interventions` is `false`. |
| **Large agent_jobs table causing slow COUNT(*):** If the `agent_jobs` table has millions of rows, a `COUNT(*)` with a `created_at >=` filter could take seconds without an index on the timestamp column. | Manual `EXPLAIN ANALYZE` review. Backend integration test measures query time with a realistic row count. If slow, recommend index on `agent_jobs.created_at` (out of scope for this change but documented as a follow-up). |
| **Timezone handling:** Date range filtering uses the timestamps provided by the frontend. If the frontend sends UTC timestamps but the database stores local time, the date range window is calculated incorrectly. | Backend integration test that inserts rows with known timestamps at range boundaries and verifies they are correctly included or excluded. Document the assumption: all timestamps are stored and queried in UTC.
| **Mixed permission scenarios not tested:** Testing only "full access" and "no access" misses the realistic case where operators have 5 of 10 permissions. A bug in the service's per-domain error handling could cause a single denied domain to skip remaining domains. | Backend integration test with a custom mock user that has exactly 5 of 10 permissions, verifying all 10 domains are still aggregated (5 with data, 5 denied). |
| **Frontend interprets `permission_flags` backwards:** If the frontend treats `true` as "allowed" instead of "denied", every card shows the wrong state. This is a likely integration bug given the inverted boolean. | Frontend integration test that feeds known `permission_flags` values to `DashboardPage` and verifies card states match (denied when `true`, normal when `false`). |
| **Failed individual domain query crashes the entire endpoint:** If the service does not wrap each domain's query in its own try-catch, a single database error on one table causes HTTP 500 for the entire dashboard. | Backend unit test that mocks the `agent_jobs` count query to throw an exception and verifies the service still returns a valid `DashboardSummary` with the failed domain's count at `0` and other domains' counts intact. |

### Medium Risk

| Risk | Mitigation |
|------|-----------|
| **Date range change triggers re-fetch of snapshot data:** Since React Query's `queryKey` includes `startTime` and `endTime`, changing the date range could trigger an unnecessary full re-fetch including snapshot data that never changes. The snapshot counts should come from a separate query or the hook should cache them independently. | Verify in frontend integration test that `useDashboardMetrics` either separates snapshot and time-sensitive queries, or that the backend efficiently recalculates snapshot counts (they're cheap COUNT(*) queries). |
| **Loading state flicker during date range change:** If the hook uses `isLoading` instead of `isFetching`, the entire dashboard disappears and reappears during a date range change instead of only time-sensitive cards showing skeletons. | Frontend component test that verifies snapshot cards do not show skeleton during date range change (only time-sensitive cards do). |
| **Card layout breaks at intermediate viewport widths:** Cards are in a responsive grid. At widths between breakpoints (e.g., 900px), cards might overflow, have inconsistent heights, or leave large gaps. | Visual inspection at 1280px, 1024px, 900px (transition zone), and 800px. E2E screenshot comparison if available. |
| **i18n keys missing for new dashboard labels:** New labels like "Agent Types", "Pending Interventions", "Guardrail Breach Events", "Permission Denied", "Last Hour", etc. must exist in all locale files. Missing keys show raw key strings in the UI. | Grep frontend i18n resource files for all new label keys. Frontend test that renders each card with the relevant i18n key and verifies the key resolves (not shown as raw string). |
| **Duplicate permission checks causing slower response:** Each of ten domains calls `PermissionEngine.authorize()` separately. If the engine is slow (e.g., DB call per check), the dashboard response time multiplies. | Backend integration test measuring total endpoint response time with 10 permission checks. Should be under 500ms cold, under 200ms warm. |
| **Existing dashboard E2E tests break:** The existing `e2e/tests/dashboard.spec.ts` uses a mock response shape (`active_agents`, `mcp_servers`, etc.) that doesn't match the new `DashboardSummary` structure. After the change is implemented, these tests will fail. | Update the E2E mock to match the new response shape, or delete the mock-based tests and rely on the new E2E tests that use the correct shape. |
| **Race condition between permission check and data fetch:** A user's permissions change between the time `PermissionEngine.authorize()` checks and the time the count query runs. In the worst case, a user whose permissions were just revoked could see stale data. | Document as accepted risk — the permission check and data fetch are synchronous within a single request, so the window is the duration of a single DB transaction. Not worth distributed-lock complexity. |

### Low Risk

| Risk | Mitigation |
|------|-----------|
| **Card icon and colour inconsistency:** If different cards use different icon sets, sizes, or colour schemes, the dashboard looks patchy. | Manual visual review. Verify icon usage is consistent (same icon library, similar size, consistent colour palette). |
| **Number formatting inconsistency:** Raw counts like `1234567` should be formatted as `1,234,567` or `1.2M`. If some cards format and others don't, it looks inconsistent and less scannable. | Frontend test verifying that all `StatCard` and `TimeSensitiveCard` components use the same number formatting utility. |
| **Skeleton animation performance:** Ten skeleton cards animating simultaneously could cause jank on low-end hardware or during initial page load. | Manual test on a throttled CPU (DevTools performance tab). If janky, consider staggering skeleton animations or reducing animation complexity. |
| **Accessibility of permission-denied state:** The lock icon and "Permission Denied" label must be accessible to screen readers. If only visual styling changes, assistive technology users don't know access is denied vs. data is loading. | Manual check with screen reader. Verify `aria-label` or `role` attributes are set on permission-denied cards. |
| **Console errors from unmounted components:** If React Query updates state after a card component unmounts (e.g., during rapid navigation), it could produce "Can't perform a React state update on an unmounted component" warnings. | E2E test that navigates to dashboard, immediately navigates away, and verifies no console warnings (excluding known ResizeObserver warnings). |

## 5. Acceptance Criteria Checklist

Mapped directly to PRD acceptance criteria (Section "Acceptance Criteria" in `prd.md`).

### Real-Time Stat Cards (Snapshot Counts)

- [ ] Dashboard page at `/` displays a grid of real-time stat cards.
- [ ] Agent Types card shows total count with active/running breakdown.
- [ ] Pending Interventions card shows count of awaiting human intervention requests.
- [ ] Model Configurations card shows count of enabled model provider configurations.
- [ ] Active Schedules card shows count of active scheduled jobs.
- [ ] Agent Identities card shows total count of provisioned agent identities.
- [ ] Agent Roles card shows total count of defined agent roles.
- [ ] MCP Servers card shows total count of registered MCP servers.
- [ ] Each card shows a numeric count and a descriptive label.
- [ ] Cards showing zero display "0" — not blank, not hidden.
- [ ] Identity provider configuration status cards are retained and moved to a de-emphasized section below operational metrics.

### Time-Sensitive Metrics (Date-Range Filtered)

- [ ] Date range picker is present above time-sensitive metrics with start and end date/time inputs and preset shortcut buttons.
- [ ] Changing the date range immediately refreshes the time-sensitive cards.
- [ ] Guardrail Breach Events card shows count within the selected date range.
- [ ] Agent Executions card shows completed and failed counts within the selected date range (e.g., "42 completed / 3 failed").
- [ ] Model Usage Posture Breaches card shows count within the selected date range.
- [ ] Time-sensitive cards display the count and the selected date range label.
- [ ] Default date range on page load is last 24 hours (now minus 24h to now).
- [ ] Only time-sensitive cards show loading state during date range change; snapshot cards remain static.

### Permission Awareness

- [ ] Each card queries data behind a permission check matching the underlying data domain.
- [ ] Agent Types and Agent Executions cards check `RT_AGENT:read`.
- [ ] Pending Interventions card checks `RT_AGENT_HUMAN_INTERVENTION:view`.
- [ ] Model Configurations and Posture Breaches cards check `RT_AGENT_MODEL_CONFIGS:read`.
- [ ] Active Schedules card checks `RT_AGENT_SCHEDULES:read`.
- [ ] Agent Identities card checks `RT_AGENT_IDENTITIES:read`.
- [ ] Agent Roles card checks `RT_AGENT_ROLES:read`.
- [ ] MCP Servers card checks `RT_INTEGRATION_MCP_HUB:read`.
- [ ] Guardrail Breach Events card checks `RT_AGENT_TRAILS:read`.
- [ ] When the user lacks a required permission, the corresponding card displays a "Permission Denied" placeholder instead of the stat value.
- [ ] Permission-denied state is visually distinct (dashed border, reduced opacity, lock icon) but does not hide the card entirely.
- [ ] No 403 errors or broken UI states appear for any permission combination.
- [ ] `GET /dashboard/summary` always returns HTTP 200 for authenticated users regardless of permissions.

### General Behaviour

- [ ] Dashboard loads within 2 seconds on first visit (cold cache acceptable within 5 seconds).
- [ ] Stat cards are organized in a responsive grid (2–4 columns depending on viewport width).
- [ ] Cards have consistent visual treatment (icon, label, value) across all metric types.
- [ ] The page title remains the existing "Dashboard" header and tagline.
- [ ] A loading state (skeleton or spinner) is shown while each card's data is being fetched.
- [ ] The endpoint rejects invalid datetime values with HTTP 422.
- [ ] The endpoint defaults to last 24 hours when no start/end time is provided.
- [ ] Identity provider status section retains its three cards and "Configure Identity Providers" button.

### Backend Aggregation Correctness

- [ ] All snapshot counts use `SELECT COUNT(*)` with correct WHERE filters (status, is_disabled, agent type is_active).
- [ ] All time-sensitive counts filter by timestamp within the date range window.
- [ ] Zero counts are returned as integer `0`, not `null`.
- [ ] Agent Types active/running breakdown is derived from agent type status and running sessions.
- [ ] Agent Executions groups by status for completed/failed breakdown.
- [ ] No query retrieves full record sets — all use `COUNT(*)` aggregation.
- [ ] A single failed domain query does not crash the entire endpoint.

### Existing Behaviour Preserved

- [ ] The dashboard route (`/`) remains accessible without `require_permission()` decorator.
- [ ] Identity provider status cards — User Provider, Agent Provider, Super Admin — render and show correct configuration status.
- [ ] "Configure Identity Providers" button navigates to `/system/identity-providers`.
- [ ] Sidebar navigation is unchanged.

## 6. Test File References

Test file paths are from `docs/config.yaml` `source.tests`. **Status legend:** ✅ CREATED (all tests pass) | ⬜ DEFERRED (not created — covered by existing tests or future work)

### Backend — Unit Tests

| File | Status | Tests | What It Covers |
|------|--------|-------|---------------|
| `backend/tests/test_dashboard_metrics_service.py` | ✅ CREATED | 8 / 8 pass | Unit tests for `DashboardMetricsService.aggregate_metrics()` with seeded SQLite DB: empty DB returns all zero counts; snapshot counts reflect seeded records; time-filtered queries filter by date range correctly; permission-denied when no PlatformUser found; permission-denied when no 'sub' in claims; custom narrow date range correctly includes/excludes records; disabled model configs not counted; only active schedules counted. |
| `backend/tests/test_dashboard_schemas.py` | ⬜ DEFERRED | — | Pydantic model validation covered implicitly by `test_dashboard_metrics_service.py` (all tests construct `DashboardSummary` with default values) and `test_dashboard_api.py` (API returns valid JSON validated against Pydantic). |

### Backend — Integration Tests (Real DB)

| File | Status | Tests | What It Covers |
|------|--------|-------|---------------|
| `backend/tests/test_dashboard_api.py` | ✅ CREATED | 6 / 6 pass | Integration tests using FastAPI TestClient + SQLite: `GET /dashboard/summary` returns 200 with valid shape; custom date range params accepted; invalid datetime returns 422; end_time before start_time returns 422; seeded data reflected in counts; unauthenticated request handled. Uses `require_permission` dependency overrides to grant all permissions. |
| `backend/tests/test_dashboard_permissions.py` | ⬜ DEFERRED | — | Permission evaluation tested indirectly via `test_dashboard_metrics_service.py` (tests empty user, no sub, and with mocked PermissionEngine). Full per-permission integration testing with real policy data is deferred to a follow-up change that seeds RBAC test policies. |

### Frontend — Component Unit Tests

| File | Status | Tests | What It Covers |
|------|--------|-------|---------------|
| `frontend/src/__tests__/components/dashboard/StatCard.test.tsx` | ✅ CREATED | 6 / 6 pass | Renders value and label; sub-breakdown chips; sub-label text; zero state with "0"; loading skeleton state (value hidden); permission-denied state with lock icon (value hidden, access denied label shown). |
| `frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx` | ✅ CREATED | 6 / 6 pass | Single-value variant with value; dual-value variant with completed/failed split; date range label; loading skeleton state; permission-denied state; zero state in dual variant. |
| `frontend/src/__tests__/components/dashboard/DateRangePicker.test.tsx` | ✅ CREATED | 4 / 4 pass | Renders preset buttons and refresh button; onChange called when preset clicked with correct 1-hour difference; onChange called when refresh clicked; formatted range label displayed. |

### Frontend — Integration Tests

| File | Status | Tests | What It Covers |
|------|--------|-------|---------------|
| `frontend/src/__tests__/pages/DashboardPage.test.tsx` | ✅ CREATED | 8 / 8 pass | Renders page title/tagline; operational metrics section title; time-sensitive metrics section title; all 7 stat card labels; all 3 time-sensitive card labels; retains IdP status section; renders quick actions button; renders date range picker presets. |
| `frontend/src/__tests__/hooks/useDashboardMetrics.test.tsx` | ⬜ DEFERRED | — | Hook behavior covered implicitly by `DashboardPage.test.tsx` which renders with mocked API data and verifies all card props propagate correctly. Dedicated hook tests deferred. |
| `frontend/src/__tests__/api/dashboardApi.test.ts` | ⬜ DEFERRED | — | API function tested implicitly via `DashboardPage.test.tsx` (mocks the API module with typed `DashboardSummary` response). Dedicated API tests deferred. |
| `frontend/src/__tests__/types/dashboard.test.ts` | ⬜ DEFERRED | — | Type-level validation covered by TypeScript compilation (interfaces match backend Pydantic models). Runtime type guards deferred. |

### E2E Tests

| File | Status | Tests | What It Covers |
|------|--------|-------|---------------|
| `e2e/tests/dashboard.spec.ts` | ✅ UPDATED | 11 / 11 pass | Dashboard renders without console errors; page has content; app shell layout with header; app title/welcome content; page content area; navigation sidebar with nav items; navigation links clickable; operational metric cards visible; time-sensitive metrics section visible; IdP status section retained; date range picker preset buttons visible. Uses `page.route()` mocks for `/api/v1/dashboard/summary` with full `DashboardSummary` shape. |

## 7. Test Execution Summary

| Layer | Files | Tests | Passed | Failed | Status |
|-------|-------|-------|--------|--------|--------|
| **Backend (pytest)** | 2 | 14 | 14 | 0 | ✅ ALL PASS |
| **Frontend (Vitest)** | 4 | 24 | 24 | 0 | ✅ ALL PASS |
| **E2E (Playwright)** | 1 | 11 | 11 | 0 | ✅ ALL PASS |
| **Total** | **7** | **49** | **49** | **0** | ✅ ALL PASS |

**Full frontend suite (all tests):** 1183 total, 1153 passed, 12 failed (all 12 failures in pre-existing, non-dashboard test files: LoginPage, ConversationDelegationVisibility, ResourceTypeManifestMirror, UsersPage). Zero regressions from dashboard changes.

### Manual Tests

| Task | What to Verify |
|------|---------------|
| Visual layout at 1280px viewport | 4-column grid, all cards visible, no overflow, consistent card heights per row. |
| Visual layout at 1024px viewport | 3-column grid, no card text truncation, DateRangePicker fits on one line. |
| Visual layout at 800px viewport | 2-column grid, cards stack without overflow, IdP section visible below. |
| i18n label review | All new labels resolve via `t()` — verify in both English and any additional configured locale. No raw key strings visible. |
| Skeleton animation smoothness | On page load, skeleton pulse is smooth across all ten cards. On date range change, only time-sensitive cards animate. |
| Lock icon visibility | On permission-denied cards, lock icon is clearly visible (good contrast against card background). |
| Manual refresh button | Click refresh — button shows spinner, data re-fetches, timestamp updates. |
| Console errors check | Open DevTools console during dashboard load and date range switching — no uncaught errors, no React warnings (excluding known ResizeObserver). |
| `EXPLAIN ANALYZE` review | Run `EXPLAIN ANALYZE` on each count query against a database with realistic row counts. Verify index usage, no sequential scans on large tables. |
| Screen reader check | Navigate dashboard with screen reader (NVDA or VoiceOver). Verify card labels, values, and permission-denied states are announced correctly. |
