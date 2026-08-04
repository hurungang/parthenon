# Technical Specification — Agent Data Module

## 1. Technical Overview

The Agent Data module exposes intermediate data saved by agents via the `save_data` system tool through a public read-only API and UI. It follows the same architecture pattern as Agent Outputs: a FastAPI router with `require_permission` gating, a service layer for database queries, Pydantic schemas for serialization, and a React Query-powered frontend with filter/table/detail-drawer UI.

No database schema changes are required — the existing `agent_data` table is sufficient. A new `agent::data` resource type with `read` action provides fine-grained access control.

The obsolete "Results" tab in Agent Trails is removed, consolidating from 3 tabs (Executions, Results, Logs) to 2 tabs (Executions, Logs). The `ResultRepositoryPage` component is no longer routed but the underlying `ResultRecord` model is preserved (no DB changes or model deletions in this change).

## 2. Component Breakdown

### 2.1 Backend — Resource Types (`resource_types.py`)

**Responsibility:** Single source of truth for all resource type identifiers.

**Change:** Added `RT_AGENT_DATA = "agent::data"` constant with `["read"]` action in `ResourceTypeManifest`. Added to `MODULE_GROUPS` under `agent` module. Total: 18 resource types (17 prior + 1 new).

### 2.2 Backend — Agent Data Service (`agent_data/service.py`)

**Responsibility:** Business logic for AgentData persistence and querying.

**Change:** Added two new public methods:
- `list_all()` — pageable listing with optional filters (unlike `query_by_filters`, all filters are optional)
- `get_by_id()` — single record lookup by UUID

Existing `query_by_filters()` method preserved for the `get_data_tool` system endpoint.

### 2.3 Backend — Agent Data Router (`api/v1/agent_data.py`)

**Responsibility:** Public API endpoints for querying AgentData records.

**Routes:**
- `GET /api/v1/agent-data` — permission `RT_AGENT_DATA:read`. Paginated list with optional filters (`data_name`, `agent_type_id`, `session_id`)
- `GET /api/v1/agent-data/{record_id}` — permission `RT_AGENT_DATA:read`. Single record with full `data_value` JSON

### 2.4 Backend — Schemas (`schemas/agent_data.py`)

**Responsibility:** Pydantic v2 serialization for AgentData API.

`AgentDataResponse` includes resolved `agent_type_name` from the relationship. `AgentDataListResponse` provides pagination metadata.

### 2.5 Frontend — Resource Types Constants (`resourceTypes.ts`)

**Responsibility:** Mirrors backend manifest for policy editor and resource type references.

**Change:** Added `"agent::data": { actions: ["read"] }` to `RESOURCE_TYPE_MANIFEST` and `MODULE_GROUPS`.

### 2.6 Frontend — useAgentData Hook (`hooks/useAgentData.ts`)

**Responsibility:** React Query hook for fetching agent data with filters and pagination.

Calls `GET /api/v1/agent-data` via `apiClient`. Cache key: `['agent-data', params]`.

### 2.7 Frontend — AgentDataPage (`pages/agent-data/AgentDataPage.tsx`)

**Responsibility:** Admin page for browsing intermediate agent data.

Filter bar with agent type dropdown. Data table with columns: Timestamp, Data Name, Agent Type, Session ID, Data Type. Pagination via `usePagination` hook. Row click opens detail drawer. Error state uses `PermissionDeniedAlert`.

### 2.8 Frontend — AgentDataDetailDrawer (`pages/agent-data/AgentDataDetailDrawer.tsx`)

**Responsibility:** MUI Dialog showing full details of a single AgentData record.

Metadata table (timestamp, data name, agent type, session ID, data type). Formatted JSON data value displayed in a `<pre>` block with monospace styling.

### 2.9 Frontend — AgentTrailsPage (`pages/trails/AgentTrailsPage.tsx`)

**Responsibility:** Tabbed page combining Agent Executions and Conversation History.

**Change:** Removed Results tab (previously index 1). Renumbered tabs from 3 to 2: Executions (index 0), Conversation History (index 1).

### 2.10 Frontend — AppRouter (`app/AppRouter.tsx`)

**Responsibility:** React Router 7 route tree.

**Changes:**
- Added `Route path="/admin/agent-data"` with `AgentDataPage` element
- Removed `Route path="/results"` with `ResultRepositoryPage` element
- Removed `ResultRepositoryPage` import, added `AgentDataPage` import

### 2.11 Frontend — AppShell (`app/AppShell.tsx`)

**Responsibility:** Sidebar navigation and app layout.

**Change:** Added "Agent Data" nav entry between Data Types and Agent Outputs in the Agents group, using `SaveAltIcon`.

### 2.12 Frontend — i18n (`i18n/locales/en.json`)

**Responsibility:** Translation strings.

**Changes:** Added `nav.agentData: "Agent Data"` and `admin.agentData` section with all UI string translations.

## 3. API Changes

### New Endpoints

| Method | Route | Permission | Description |
|--------|-------|------------|-------------|
| `GET` | `/api/v1/agent-data` | `agent::data:read` | Paginated list with optional filters |
| `GET` | `/api/v1/agent-data/{id}` | `agent::data:read` | Single record with full JSON value |

### Removed Routes

| Method | Route | Reason |
|--------|-------|--------|
| `GET` | `/results` | Deprecated results page; superseded by Agent Outputs |

## 4. State Management

- Agent Data list uses React Query with cache key `['agent-data', params]` — auto-invalidated on filter/page changes
- Agent types dropdown reuses existing `useAgentTypes()` hook
- Detail drawer uses local `useState` (not persisted in URL)

## 5. Data Access Patterns

- **AgentData listing:** Server-side pagination and filtering via API query params
- **AgentData detail:** Server-side single-record fetch by UUID
- **Agent types dropdown:** Client-side fetch from existing hook

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RT_AGENT_DATA` | constant | Resource type `agent::data` | `backend/app/core/resource_types.py:25` |
| `AgentDataResponse` | schema | Public response schema | `backend/app/schemas/agent_data.py:7` |
| `AgentDataListResponse` | schema | Paginated list schema | `backend/app/schemas/agent_data.py:26` |
| `AgentDataRouter` | router | Public API router | `backend/app/api/v1/agent_data.py:22` |
| `list_all` | method | Paginated listing (all filters optional) | `backend/app/services/agent_data/service.py:73` |
| `get_by_id` | method | Single record lookup | `backend/app/services/agent_data/service.py:133` |
| `query_by_filters` | method | Internal query (requires filter) | `backend/app/services/agent_data/service.py:155` |
| `useAgentData` | hook | React Query hook | `frontend/src/hooks/useAgentData.ts:8` |
| `AgentDataPage` | component | Admin page | `frontend/src/pages/agent-data/AgentDataPage.tsx:29` |
| `AgentDataDetailDrawer` | component | Detail dialog | `frontend/src/pages/agent-data/AgentDataDetailDrawer.tsx:22` |
| `AgentDataResponse` | type | TS interface | `frontend/src/types/index.ts:873` |
| `AgentDataQueryParams` | type | TS interface | `frontend/src/types/index.ts:884` |
| `AgentDataListResponse` | type | TS interface | `frontend/src/types/index.ts:892` |
| `AgentTrailsPage` | component | Updated: 2 tabs | `frontend/src/pages/trails/AgentTrailsPage.tsx:26` |
| `AppRouter` | component | Updated: routes | `frontend/src/app/AppRouter.tsx:145` |
| `AppShell` | component | Updated: sidebar | `frontend/src/app/AppShell.tsx` |
