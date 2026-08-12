# Dashboard Operational Metrics Test Plan

## Scope

Covers the Dashboard operational metrics feature: 10 permission-aware stat cards (7 snapshot counts + 3 time-sensitive metrics), the `DashboardMetricsService` backend aggregation service, the `GET /dashboard/summary` API endpoint with date range filtering, the `DateRangePicker` component, `StatCard` and `TimeSensitiveCard` components, and the identity provider status section retention.

---

## Coverage Areas

### 1. DashboardMetricsService — Count Aggregation

**What is tested:**
- Snapshot counts (no date filter): `agent_types` total/active/running, `pending_interventions`, `model_configs`, `active_schedules`, `agent_identities`, `agent_roles`, `mcp_servers`
- Time-filtered counts: `guardrail_breaches`, `agent_executions` (completed/failed breakdown), `posture_breaches`
- Zero-value handling: all counts return `0` when tables are empty or no rows match
- Date range filtering: only timestamps within the window are counted
- Filter correctness: disabled model configs excluded, only pending interventions counted, only active schedules counted

**Acceptance criteria:**
- All counts use `SELECT COUNT(*)` with correct WHERE filters
- Zero counts are integer `0`, not `null`
- A single failed domain query does not crash the entire endpoint
- Response always returns HTTP 200 for authenticated users

**Test files:**
- [backend/tests/test_dashboard_metrics_service.py](../../../../backend/tests/test_dashboard_metrics_service.py) — Unit tests: empty DB returns all zero counts; snapshot counts reflect seeded records; time-filtered queries filter by date range correctly; permission-denied when no user/sub found; disabled model configs not counted; only active schedules counted
- [backend/tests/test_dashboard_api.py](../../../../backend/tests/test_dashboard_api.py) — Integration tests: `GET /dashboard/summary` returns 200 with valid shape; custom date range params accepted; invalid datetime returns 422; seeded data reflected in counts

---

### 2. Permission Checks Per Domain

**What is tested:**
- All ten domains checked independently via `PermissionEngine.authorize()`
- Correct module-action pairs: `agent::human_intervention` uses `view` action; `agent` shared by Agent Types and Agent Executions; `agent::model_configs` shared by Model Configurations and Posture Breaches
- Permission denial is per-domain via `permission_flags` — never causes 403 response
- No endpoint-level `require_permission()` decorator — any authenticated user gets 200
- System administrator with wildcard permissions sees all cards with real values

**Acceptance criteria:**
- `permission_flags` contains ten boolean fields matching card list (`true` = denied)
- Mix of permissions: denied domains show `true` flags, permitted domains show real counts
- All-ten-denied returns 200 with ten `true` flags and all zero counts
- No single denial blocks the entire response

**Test files:**
- [backend/tests/test_dashboard_metrics_service.py](../../../../backend/tests/test_dashboard_metrics_service.py) — Covers permission-denied paths with empty user, no sub in claims, and mocked PermissionEngine

---

### 3. Date Range Filtering & Validation

**What is tested:**
- Both `start_time` and `end_time` accept ISO 8601 datetime strings
- Default: start_time = now minus 24 hours, end_time = now
- Malformed datetimes return HTTP 422 with clear error
- Snapshot counts ignore date range (only `time_sensitive` counts change)
- Boundary-inclusive: records at window edges are included

**Acceptance criteria:**
- Invalid datetime → 422 with descriptive error
- Changing date range only affects time-sensitive cards
- Date range label displays correctly on TimeSensitiveCards

**Test files:**
- [backend/tests/test_dashboard_api.py](../../../../backend/tests/test_dashboard_api.py) — Integration tests: custom date range params, invalid datetime rejection

---

### 4. StatCard Component

**What is tested:**
- Normal state: icon, label, numeric value, optional sub-breakdown chips, sub-label
- Zero state: displays "0" with muted styling (not blank, not hidden)
- Loading state: skeleton pulse animation in place of numeric value
- Permission-denied state: dashed border, reduced opacity (0.55), lock icon overlay, "Permission Denied" label
- Sub-breakdown: Agent Types card shows active/running counts as chips

**Acceptance criteria:**
- All four visual states (normal, zero, loading, permission-denied) render correctly
- Sub-breakdown chips visible only when data present, hidden when permission-denied

**Test files:**
- [frontend/src/__tests__/components/dashboard/StatCard.test.tsx](../../../../frontend/src/__tests__/components/dashboard/StatCard.test.tsx) — Renders value and label; sub-breakdown chips; sub-label text; zero state; loading skeleton; permission-denied state with lock icon

---

### 5. TimeSensitiveCard Component

**What is tested:**
- Single-value variant: one large number, date range label below, left-border accent
- Dual-value variant: completed (green) / failed (red) split display, date range label
- Loading state: skeleton animation in value area
- Permission-denied state: consistent with StatCard (dashed border, lock icon, placeholder)
- Date range label changes when picker value changes

**Acceptance criteria:**
- Both single and dual variants render correctly
- Four visual states consistent with StatCard
- Date range label reflects current selection

**Test files:**
- [frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx](../../../../frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx) — Single-value variant; dual-value variant with completed/failed split; date range label; loading skeleton; permission-denied state; zero state in dual variant

---

### 6. DateRangePicker Component

**What is tested:**
- Date/time pickers for start and end
- Preset shortcuts: Last Hour, Last 24 Hours, Last 7 Days
- Default range: start = now - 24h, end = now
- `onChange` triggers re-fetch via `useDashboardMetrics`
- Formatted range label displayed
- Only time-sensitive cards show loading during date range change; snapshot cards remain static

**Acceptance criteria:**
- Preset buttons auto-fill correct ranges and trigger data refresh
- Re-fetch during date range change does not affect snapshot cards

**Test files:**
- [frontend/src/__tests__/components/dashboard/DateRangePicker.test.tsx](../../../../frontend/src/__tests__/components/dashboard/DateRangePicker.test.tsx) — Renders preset buttons and refresh button; onChange called when preset clicked; formatted range label displayed

---

### 7. DashboardPage Composition

**What is tested:**
- Operational metrics section with all 7 snapshot cards
- Time-sensitive metrics section with DateRangePicker and 3 time-sensitive cards
- Identity provider status cards retained in de-emphasized section below metrics
- Existing "Dashboard" header and tagline preserved
- Error banner shown when full fetch fails; retry button calls refetch
- Individual card permission denials do not trigger error banner

**Acceptance criteria:**
- All cards render in correct sections
- IdP status cards — User Provider, Agent Provider, Super Admin — remain on page
- "Configure Identity Providers" button navigates to `/system/identity-providers`
- Full-fetch error shows retry banner; permission denials handled per-card

**Test files:**
- [frontend/src/__tests__/pages/DashboardPage.test.tsx](../../../../frontend/src/__tests__/pages/DashboardPage.test.tsx) — Page title/tagline; all 7 stat card labels; all 3 time-sensitive card labels; IdP status section retained; date range picker presets rendered

---

### 8. useDashboardMetrics Hook & API Layer

**What is tested:**
- Query key: `['dashboard', 'summary', startTime, endTime]` — date range changes create new key
- Default date range: start = now - 24h, end = now
- Stale time: 30 seconds
- `getDashboardSummary` API function calls `GET /api/v1/dashboard/summary?start_time=<ISO>&end_time=<ISO>`
- TypeScript types match backend Pydantic models exactly

**Acceptance criteria:**
- Changing date range triggers fresh fetch
- Cached data used within stale time window
- Type-safe response mapping

**Test files:**
- Covered by `DashboardPage.test.tsx` integration (mocked API with typed DashboardSummary response)

---

## E2E Test Coverage

| Test File | Coverage |
|-----------|----------|
| [e2e/tests/dashboard.spec.ts](../../../../e2e/tests/dashboard.spec.ts) | Dashboard renders without console errors; page has content; app shell layout; navigation sidebar; operational metric cards; time-sensitive metrics section; IdP status section; date range picker preset buttons. Uses `page.route()` mocks for `/api/v1/dashboard/summary` with full `DashboardSummary` shape. |

---

## Critical Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| Permission check uses wrong action for Human Interventions (must be `view`, not `read`) | Backend integration test verifies correct action constant used |
| Large `agent_jobs` table causing slow `COUNT(*)` | Document index requirement on `agent_jobs.created_at`; `EXPLAIN ANALYZE` review recommended |
| Frontend interprets `permission_flags` backwards (treats `true` as allowed) | Frontend test feeds known `permission_flags` values and verifies card states match |
| Failed individual domain query crashes entire endpoint | Service wraps each domain query in try-catch; other domains continue to aggregate |
| Date range change triggers unnecessary re-fetch of snapshot data | Verify snapshot cards do not show skeleton during date range change |
| Loading state flicker during date range change (uses `isLoading` not `isFetching`) | Frontend test verifies snapshot cards remain static during re-fetch |
| Existing E2E tests break due to response shape change | E2E mocks updated to match new `DashboardSummary` structure |
| i18n keys missing for new labels | Verify all new labels resolve via `t()` in all locale files |

---

## Test Execution Summary

| Layer | Files | Tests | Status |
|-------|-------|-------|--------|
| Backend (pytest) | `test_dashboard_metrics_service.py`, `test_dashboard_api.py` | 14 | ✅ ALL PASS |
| Frontend (Vitest) | `StatCard.test.tsx`, `TimeSensitiveCard.test.tsx`, `DateRangePicker.test.tsx`, `DashboardPage.test.tsx` | 24 | ✅ ALL PASS |
| E2E (Playwright) | `dashboard.spec.ts` | 11 | ✅ ALL PASS |
