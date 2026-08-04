# Module: agent-data — Tech Spec

## Overview

The **Agent Data** module exposes intermediate data saved by agents via the `save_data` system tool through a public read-only API and UI. It follows the same architecture pattern as Agent Outputs: a FastAPI router with `require_permission` gating, a service layer for database queries, Pydantic schemas for serialization, and a React Query-powered frontend with filter/table/detail-drawer UI.

No dedicated database tables — the module operates on the existing `agent_data` table. A new `agent::data` resource type with `read` action provides fine-grained access control.

The module is owned entirely by **Control Center**. The legacy "Results" tab in Agent Trails has been removed and superseded by this module and Agent Outputs.

---

## Key Components

### Backend — Resource Types

| Component | Description |
|-----------|-------------|
| `RT_AGENT_DATA` | Final constant for resource type `agent::data`. Registered in `ResourceTypeManifest` with `["read"]` action and included in `MODULE_GROUPS` under the `agent` module. |

### Backend — Services

| Component | Description |
|-----------|-------------|
| `AgentDataService.list_all()` | Paginated listing with optional filters — all filters (data_name, agent_type_id, session_id) are optional. Enriches results with `agent_type_name` from the agent type relationship. |
| `AgentDataService.get_by_id()` | Single record lookup by UUID. Returns full record including `data_value` JSON. |
| `AgentDataService.query_by_filters()` | Internal query method used by the `get_data` system tool. Requires at least one filter to be specified. Preserved unchanged. |

### Backend — API Routers

| Component | Description |
|-----------|-------------|
| `AgentDataRouter` | JWT-protected APIRouter at `/api/v1/agent-data`. Permission: `RT_AGENT_DATA:read`. |

### Backend — Schemas

| Component | Description |
|-----------|-------------|
| `AgentDataResponse` | Pydantic v2 response model: includes `agent_type_name` resolved from relationship. |
| `AgentDataListResponse` | Paginated list wrapper: `items[]`, `total`, `page`, `page_size`. |

### Frontend — Pages & Components

| Component | Description |
|-----------|-------------|
| `AgentDataPage` | Admin page for browsing intermediate agent data. Filter bar with agent type dropdown. Data table with columns: Timestamp, Data Name, Agent Type, Session ID, Data Type. Pagination. Row click opens detail drawer. Error state uses `PermissionDeniedAlert`. |
| `AgentDataDetailDrawer` | MUI Dialog showing full details of a single AgentData record. Metadata table (timestamp, data name, agent type, session ID, data type). Formatted JSON data value displayed in a `<pre>` block with monospace styling. |
| `AgentTrailsPage` | **MODIFIED**: Results tab removed. Renumbered from 3 tabs to 2: Executions (index 0), Conversation History (index 1). |
| `AppRouter` | **MODIFIED**: Added `Route path="/admin/agent-data"` with `AgentDataPage` element. Removed deprecated `Route path="/results"` with `ResultRepositoryPage` element. |
| `AppShell` | **MODIFIED**: Added "Agent Data" nav entry between Data Types and Agent Outputs in the Agents group, using `SaveAltIcon`. |

### Frontend — Hooks

| Component | Description |
|-----------|-------------|
| `useAgentData` | React Query hook for fetching agent data with filters and pagination. Calls `GET /api/v1/agent-data` via `apiClient`. Cache key: `['agent-data', params]`. |

### Frontend — Types

| Component | Description |
|-----------|-------------|
| `AgentDataResponse` | TS interface: `{id, data_name, data_value, data_type, agent_type_id, agent_type_name, session_id, created_at}` |
| `AgentDataQueryParams` | TS interface: filter/pagination params `{data_name?, agent_type_id?, session_id?, page?, page_size?}` |
| `AgentDataListResponse` | TS interface: `{items[], total, page, page_size}` |

### Frontend — i18n Keys

| Key Group | Description | File |
|-----------|-------------|------|
| `nav.agentData` | Sidebar "Agent Data" label | `frontend/src/i18n/locales/en.json` |
| `admin.agentData.*` | All UI string translations for Agent Data admin page and detail drawer | `frontend/src/i18n/locales/en.json` |

---

## API Endpoints

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| `GET` | `/api/v1/agent-data` | `agent::data:read` | Paginated list with optional filters (data_name, agent_type_id, session_id) |
| `GET` | `/api/v1/agent-data/{id}` | `agent::data:read` | Single record with full `data_value` JSON |

### Removed Routes

| Method | Route | Reason |
|--------|-------|--------|
| `GET` | `/results` | Deprecated results page; superseded by Agent Outputs and Agent Data modules |

---

## Code Reference Map

### Backend — Resource Types

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RT_AGENT_DATA` | constant | Resource type `agent::data` with `["read"]` action | `backend/app/core/resource_types.py` |

### Backend — Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentDataService` | class | Business logic for AgentData persistence and querying | `backend/app/services/agent_data/service.py` |
| `list_all` | method | Paginated listing with all filters optional | `backend/app/services/agent_data/service.py` |
| `get_by_id` | method | Single record lookup by UUID | `backend/app/services/agent_data/service.py` |
| `query_by_filters` | method | Internal query requiring at least one filter | `backend/app/services/agent_data/service.py` |

### Backend — API Routers

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentDataRouter` | APIRouter | `GET /agent-data`, `GET /agent-data/{id}`; permission: `RT_AGENT_DATA:read` | `backend/app/api/v1/agent_data.py` |

### Backend — Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentDataResponse` | schema | Response model with resolved `agent_type_name` | `backend/app/schemas/agent_data.py` |
| `AgentDataListResponse` | schema | Paginated list wrapper: items[], total, page, page_size | `backend/app/schemas/agent_data.py` |

### Frontend — Pages & Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentDataPage` | page | Admin page with filter bar, data table, pagination, detail drawer | `frontend/src/pages/agent-data/AgentDataPage.tsx` |
| `AgentDataDetailDrawer` | component | MUI Dialog with metadata table and formatted JSON data_value | `frontend/src/pages/agent-data/AgentDataDetailDrawer.tsx` |
| `AgentTrailsPage` | page | **MODIFIED**: Results tab removed; 2 tabs (Executions, Conversation History) | `frontend/src/pages/trails/AgentTrailsPage.tsx` |
| `AppRouter` | component | **MODIFIED**: Added `/admin/agent-data` route, removed `/results` route | `frontend/src/app/AppRouter.tsx` |
| `AppShell` | component | **MODIFIED**: Added "Agent Data" sidebar nav entry | `frontend/src/app/AppShell.tsx` |

### Frontend — Hooks

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useAgentData` | hook | React Query hook; cache key: `['agent-data', params]` | `frontend/src/hooks/useAgentData.ts` |

### Frontend — Types

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentDataResponse` | interface | Agent data record with resolved names | `frontend/src/types/index.ts` |
| `AgentDataQueryParams` | interface | Filter and pagination params for agent data queries | `frontend/src/types/index.ts` |
| `AgentDataListResponse` | interface | Paginated list wrapper | `frontend/src/types/index.ts` |

---

## Data Access Patterns

### Agent Data Listing

Server-side pagination and filtering via `GET /api/v1/agent-data` API query params. React Query manages caching with key `['agent-data', params]` — auto-invalidated on filter/page changes.

### Agent Data Detail

Server-side single-record fetch by UUID via `GET /api/v1/agent-data/{id}`. Detail drawer uses local `useState` — not persisted in URL.

### Agent Types Dropdown

Client-side fetch from existing `useAgentTypes()` hook — no additional API call required.

### Relationship to Agent Data Table

The module queries the existing `agent_data` table. Records are populated by the `save_data` system tool during agent execution. Each record has `data_name`, `data_value`, and is linked to agent type and session via FKs. Separate from final output which is singular per session.
