# Module: dashboard — Tech Spec

## Overview

The dashboard metrics feature provides a permission-aware operational metrics overview that replaces the placeholder dashboard page. A single aggregation endpoint on the Control Center performs server-side `COUNT(*)` queries across ten data domains (seven snapshot, three time-filtered), checks the caller's permissions per domain via the existing `PermissionEngine`, and returns a consolidated `DashboardSummary` JSON response containing counts and per-card permission flags. The frontend renders ten metric cards based on this response, displaying permission-denied placeholders for inaccessible domains without any 403 errors reaching the UI. Snapshot counts are not date-dependent; time-sensitive counts are filtered by a user-defined date range that drives a React Query key change. The existing identity provider status cards are retained in a de-emphasised secondary section. The feature introduces no new database tables, no inter-service communication, and no changes to the authentication or authorization infrastructure.

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/dashboard/summary` | Returns aggregated metric counts across ten data domains with per-card permission flags. Accepts optional `start_time` and `end_time` query parameters (ISO 8601); defaults to last 24 hours. No endpoint-level `require_permission()` — permission enforcement is per-domain inside the service. |

### Permission-to-Domain Mapping

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

---

## Code Reference Map

### Backend Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardSummary` | Pydantic model | Top-level aggregation response with `snapshot_counts`, `time_sensitive`, `permission_flags` | `backend/app/schemas/dashboard.py` |
| `SnapshotCounts` | Pydantic model | Nine snapshot count fields: `agent_types`, `agent_types_active`, `agent_types_running`, `pending_interventions`, `model_configs`, `active_schedules`, `agent_identities`, `agent_roles`, `mcp_servers` | `backend/app/schemas/dashboard.py` |
| `TimeSensitiveCounts` | Pydantic model | Time-filtered count fields: `guardrail_breaches`, `agent_executions` (nested `completed`/`failed`), `posture_breaches` | `backend/app/schemas/dashboard.py` |
| `AgentExecutionsBreakdown` | Pydantic model | Nested breakdown inside `TimeSensitiveCounts`: `completed` and `failed` integer counts | `backend/app/schemas/dashboard.py` |
| `CardPermissionFlags` | Pydantic model | Ten boolean fields (one per metric card); `true` means permission is denied for that domain | `backend/app/schemas/dashboard.py` |

### Backend Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardMetricsService` | class | Per-domain permission check + `COUNT(*)` aggregation service; accepts `start_time` and `end_time` datetimes; composes `DashboardSummary` | `backend/app/services/dashboard_metrics_service.py` |
| `aggregate_metrics` | async method | Entry point: iterates each data domain, checks permission, executes count query, returns `DashboardSummary` | `backend/app/services/dashboard_metrics_service.py` |

### Backend API

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardRouter` | APIRouter | FastAPI APIRouter exposing `GET /dashboard/summary` with optional `start_time`/`end_time` query params | `backend/app/api/v1/dashboard.py` |
| `router` (v1) | APIRouter | Updated to include `DashboardRouter` via `include_router()` | `backend/app/api/v1/__init__.py` |

### Backend Dependencies (Existing, Unchanged)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_permission` | dependency factory | Permission-engine enforcement (used inside service, not at endpoint level) | `backend/app/api/deps.py` |
| `get_current_claims` | dependency | Extracts JWT claims from request state | `backend/app/api/deps.py` |
| `get_db` | dependency | Provides async database session | `backend/app/db/session.py` |
| `PermissionEngine` | class | Policy-based authorization engine | `backend/app/services/permissions/permission_engine.py` |
| `RT_AGENT` | constant | Resource type `"agent"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_ROLES` | constant | Resource type `"agent::roles"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_IDENTITIES` | constant | Resource type `"agent::identities"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_MODEL_CONFIGS` | constant | Resource type `"agent::model_configs"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_SCHEDULES` | constant | Resource type `"agent::schedules"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_TRAILS` | constant | Resource type `"agent::trails"` | `backend/app/core/resource_types.py` |
| `RT_AGENT_HUMAN_INTERVENTION` | constant | Resource type `"agent::human_intervention"` | `backend/app/core/resource_types.py` |
| `RT_INTEGRATION_MCP_HUB` | constant | Resource type `"integration::mcp_hub"` | `backend/app/core/resource_types.py` |

### Frontend API Client

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `getDashboardSummary` | function | Calls `GET /dashboard/summary` with `start_time` and `end_time` params; returns typed `DashboardSummary` promise | `frontend/src/api/dashboardApi.ts` |
| `apiClient` | AxiosInstance | Configured axios client with JWT auth interceptors (unchanged) | `frontend/src/api/apiClient.ts` |

### Frontend Types

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardSummary` | TypeScript interface | Response shape: `snapshot_counts`, `time_sensitive`, `permission_flags` | `frontend/src/types/dashboard.ts` |
| `SnapshotCounts` | TypeScript interface | Snapshot count fields matching backend model | `frontend/src/types/dashboard.ts` |
| `TimeSensitiveCounts` | TypeScript interface | Time-filtered count fields including nested `agent_executions` | `frontend/src/types/dashboard.ts` |
| `AgentExecutionsBreakdown` | TypeScript interface | Nested `completed`/`failed` breakdown inside `TimeSensitiveCounts` | `frontend/src/types/dashboard.ts` |
| `CardPermissionFlags` | TypeScript interface | Per-card boolean permission-denied flags | `frontend/src/types/dashboard.ts` |

### Frontend Hooks

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useDashboardMetrics` | hook | React Query hook wrapping `getDashboardSummary`; manages `startTime`/`endTime` state internally; exposes `data`, `isLoading`, `isError`, `error`, `setDateRange`, `refetch`; stale time 30s; query key `['dashboard', 'summary', startTime, endTime]` | `frontend/src/hooks/useDashboardMetrics.ts` |

### Frontend Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DashboardPage` | component | Top-level dashboard view; renders operational metrics grid of `StatCard` components, time-sensitive section with `DateRangePicker` and `TimeSensitiveCard` components, and retained identity provider status section; all labels use i18next `t()` | `frontend/src/pages/DashboardPage.tsx` |
| `StatCard` | component | Snapshot metric card with icon, label, numeric value, sub-breakdown chips; handles four visual states: normal, zero (muted), loading (skeleton), permission-denied (dashed border, lock icon, "Permission Denied" label) | `frontend/src/components/dashboard/StatCard.tsx` |
| `TimeSensitiveCard` | component | Time-filtered metric card supporting single-value and dual-value (completed/failed) variants; left-border accent, date range label; handles same four visual states as `StatCard` | `frontend/src/components/dashboard/TimeSensitiveCard.tsx` |
| `DateRangePicker` | component | Date range selection with date+time (hours/minutes) pickers and preset shortcuts (Last Hour, Last 24 Hours, Last 7 Days); exposes `startTime`, `endTime`, `onChange`; default: now minus 24h to now | `frontend/src/components/dashboard/DateRangePicker.tsx` |

### Frontend Dependencies (Existing, Unchanged)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `getIdentityProviders` | function | Existing API function for IdP status cards | `frontend/src/api/systemConfigApi.ts` |
| `getSuperAdminStatus` | function | Existing API function for super admin indicator | `frontend/src/api/systemConfigApi.ts` |

---

## Test Files

| Description | File |
|-------------|------|
| Unit tests for `DashboardMetricsService` | `backend/tests/test_dashboard_metrics_service.py` |
| Integration tests for `GET /dashboard/summary` | `backend/tests/test_dashboard_api.py` |
| Unit tests for `StatCard` component | `frontend/src/__tests__/components/dashboard/StatCard.test.tsx` |
| Unit tests for `TimeSensitiveCard` component | `frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx` |
| Unit tests for `DateRangePicker` component | `frontend/src/__tests__/components/dashboard/DateRangePicker.test.tsx` |
| Integration tests for `DashboardPage` | `frontend/src/__tests__/pages/DashboardPage.test.tsx` |
| E2E tests for dashboard happy path | `e2e/tests/dashboard.spec.ts` |
