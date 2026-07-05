# Implementation Plan: Agent Data Module

## Overview

Expose intermediate agent data (saved via `save_data` system tool) through a public read-only API and UI, following the same pattern as Agent Outputs. Remove the obsolete "Results" tab from Agent Trails.

## Task Checklist

### Phase 1 — Backend Resource Type

- [x] 1.1 — Add `RT_AGENT_DATA = "agent::data"` constant in `resource_types.py`
- [x] 1.2 — Add entry to `ResourceTypeManifest` with `actions: ["read"]`
- [x] 1.3 — Add to `MODULE_GROUPS` under `agent` module

### Phase 2 — Backend API

- [x] 2.1 — Create `AgentDataResponse` and `AgentDataListResponse` schemas in `agent_data.py`
- [x] 2.2 — Add `list_all()` and `get_by_id()` methods to `AgentDataService`
- [x] 2.3 — Create public API router `agent_data.py` with `GET /agent-data` and `GET /agent-data/{id}`
- [x] 2.4 — Register router in `api/v1/__init__.py`

### Phase 3 — Frontend Types & Hooks

- [x] 3.1 — Add `AgentDataResponse`, `AgentDataQueryParams`, `AgentDataListResponse` TypeScript types
- [x] 3.2 — Create `useAgentData` React Query hook
- [x] 3.3 — Add `agent::data` to frontend resource type manifest

### Phase 4 — Frontend UI

- [x] 4.1 — Create `AgentDataPage` component with filter bar (agent type dropdown) and data table
- [x] 4.2 — Create `AgentDataDetailDrawer` component showing full JSON value
- [x] 4.3 — Add `/admin/agent-data` route in `AppRouter`
- [x] 4.4 — Add sidebar entry with `SaveAltIcon` in `AppShell`
- [x] 4.5 — Add i18n translations for all UI strings

### Phase 5 — Remove Obsolete Results Tab

- [x] 5.1 — Remove Results tab from `AgentTrailsPage` (reduce from 3 tabs to 2)
- [x] 5.2 — Remove `/results` route from `AppRouter`
- [x] 5.3 — Remove `ResultRepositoryPage` import from `AppRouter` and `AgentTrailsPage`

### Phase 6 — Testing

- [x] 6.1 — Verify system tool endpoint tests still pass (4/4)
- [x] 6.2 — Add integration test for Agent Data API endpoint registration and auth
- [x] 6.3 — Verify frontend TypeScript compilation (no new errors)
- [x] 6.4 — Verify frontend Vitest suite (1026 passed, 4 pre-existing failures)

## Phase 1 — Backend Resource Type

### 1.1 — Add RT_AGENT_DATA constant

**Scope:** `backend/app/core/resource_types.py:25`

Added `RT_AGENT_DATA: Final[str] = "agent::data"` after `RT_AGENT_DATA_TYPES` and before `RT_AGENT_OUTPUTS`.

### 1.2 — Add to ResourceTypeManifest

**Scope:** `backend/app/core/resource_types.py:77-79`

Added entry with `"actions": ["read"]`.

### 1.3 — Add to MODULE_GROUPS

**Scope:** `backend/app/core/resource_types.py:111`

Added `RT_AGENT_DATA` to agent module group between `RT_AGENT_DATA_TYPES` and `RT_AGENT_OUTPUTS`.

## Phase 2 — Backend API

### 2.1 — Create schemas

**Scope:** New file `backend/app/schemas/agent_data.py`

`AgentDataResponse` with `id`, `agent_type_id`, `session_id`, `data_name`, `data_value`, `data_type`, `is_active`, `created_at`, `agent_type_name` (resolved). `AgentDataListResponse` with `items`, `total`, `page`, `page_size`.

### 2.2 — Add service methods

**Scope:** `backend/app/services/agent_data/service.py`

Added `list_all()` — paginated listing with optional filters (all optional, unlike `query_by_filters`). Added `get_by_id()` — single record lookup by UUID.

### 2.3 — Create public API router

**Scope:** New file `backend/app/api/v1/agent_data.py`

- `GET /agent-data` — paginated list with optional `data_name`, `agent_type_id`, `session_id` filters
- `GET /agent-data/{record_id}` — single record with full JSON value
- All endpoints require `require_permission(RT_AGENT_DATA, "read")`

### 2.4 — Register router

**Scope:** `backend/app/api/v1/__init__.py`

Added import and `router.include_router(AgentDataRouter)` in the "Data Types, Agent Data & Agent Outputs" section.

## Phase 3 — Frontend Types & Hooks

### 3.1 — Add TypeScript types

**Scope:** `frontend/src/types/index.ts`

Added `AgentDataResponse`, `AgentDataQueryParams`, `AgentDataListResponse` interfaces matching the backend schemas.

### 3.2 — Create useAgentData hook

**Scope:** New file `frontend/src/hooks/useAgentData.ts`

React Query hook calling `GET /api/v1/agent-data` with filter/pagination params.

### 3.3 — Add to frontend manifest

**Scope:** `frontend/src/constants/resourceTypes.ts`

Added `"agent::data": { actions: ["read"] }` to `RESOURCE_TYPE_MANIFEST` and `MODULE_GROUPS.agents.submodules`.

## Phase 4 — Frontend UI

### 4.1 — Create AgentDataPage

**Scope:** New file `frontend/src/pages/agent-data/AgentDataPage.tsx`

Filter bar with agent type dropdown. Table with columns: Timestamp, Data Name, Agent Type, Session ID, Data Type. Click row opens detail drawer. Pagination via `usePagination`.

### 4.2 — Create AgentDataDetailDrawer

**Scope:** New file `frontend/src/pages/agent-data/AgentDataDetailDrawer.tsx`

MUI Dialog showing metadata table and formatted JSON data value in a `<pre>` block.

### 4.3 — Add route

**Scope:** `frontend/src/app/AppRouter.tsx`

Added `Route path="/admin/agent-data"` with `AgentDataPage` element. Removed `ResultRepositoryPage` import and `/results` route.

### 4.4 — Add sidebar entry

**Scope:** `frontend/src/app/AppShell.tsx`

Added nav entry `{ labelKey: 'nav.agentData', path: '/admin/agent-data', icon: <SaveAltIcon /> }` between Data Types and Agent Outputs.

### 4.5 — Add i18n translations

**Scope:** `frontend/src/i18n/locales/en.json`

Added `nav.agentData` key and `admin.agentData` section with all UI string translations.

## Phase 5 — Remove Obsolete Results Tab

### 5.1 — Remove Results tab from AgentTrailsPage

**Scope:** `frontend/src/pages/trails/AgentTrailsPage.tsx`

Reduced from 3 tabs (Executions, Results, Logs) to 2 tabs (Executions, Logs). Removed `ResultRepositoryPage` import and tab panel.

### 5.2 — Remove /results route

**Scope:** `frontend/src/app/AppRouter.tsx`

Removed `/results` route and `ResultRepositoryPage` import.

### 5.3 — Clean up unused imports

Removed unused import across both files.

## Phase 6 — Testing

### 6.1 — System tool tests

All 4 existing system tool endpoint tests pass.

### 6.2 — Agent Data API tests

**Scope:** New file `backend/tests/integration/test_agent_data_api.py`

Tests verify endpoint registration reaches auth/permission checks with correct 401 response.

### 6.3 — Frontend TypeScript

No new TypeScript errors introduced by the change.

### 6.4 — Frontend Vitest

1026 passed, 4 failed (all pre-existing, unrelated to this change).
