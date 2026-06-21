# Technical Specification: Enhance Agent Output System

## 1. Technical Overview

The agent output system is enhanced by introducing a centralized **Agent Data Type Registry** — a new domain entity owned by Control Center that stores reusable typed schemas. The `AgentType` model gains an optional foreign key to this registry, enabling administrators to assign a typed output schema to any non-conversational agent type. At execution completion, Agent Runtime calls a new CC internal validation endpoint to validate the agent's output against the assigned schema; the validated (or validation-failed) result is persisted to a new `agent_outputs` table with a schema reference. The frontend Execution Log dialog is updated to detect typed outputs and render them as a structured field-by-field view using schema-aware components. A dedicated **Agent Outputs** admin page provides filtering, dynamic column rendering, and CSV export. A new `query_result` system tool allows agents to query past typed outputs programmatically, routed through Communication Hub to Control Center. The existing `save_result` tool and untyped execution paths remain fully backward-compatible.

The design follows the existing service segregation: CC owns all new database tables and exposes both public REST endpoints (for UI) and internal mTLS-protected endpoints (for AR). AR has no direct database access — it calls CC internal endpoints for validation, output persistence, and output querying. CH routes the new `query_result` tool call using its existing tool-routing infrastructure.

---

## 2. Component Breakdown

### 2.1 New Backend Components

| Component | Service | Responsibility |
|-----------|---------|----------------|
| `AgentDataType` model | CC | SQLAlchemy model for the data type registry: name, slug, description, fields JSONB, timestamps. Located in `backend/app/db/models/agent_data_type.py`. |
| `AgentOutput` model | CC | SQLAlchemy model for typed execution results: data_type_id FK, agent_type_id FK, execution_session_id FK, field_values JSONB, validation_status enum, raw_output Text. Located in `backend/app/db/models/agent_output.py`. |
| `DataTypeService` | CC | Business logic for data type CRUD operations: create, read, update, delete (blocked if referenced), list (paginated, searchable), get-by-slug, reference checking. Located in `backend/app/services/data_types/service.py`. |
| `OutputService` | CC | Business logic for typed output persistence and querying: save_typed, list_outputs (with filters), get_output, export_csv. Located in `backend/app/services/outputs/service.py`. |
| `SchemaValidationService` | CC | Validates a payload against a data type schema: checks required fields, field types (string, number, boolean, date, enum), enum value membership. Returns field-level validation errors. Located in `backend/app/services/validation/schema_validation_service.py`. |
| `DataTypeController` | CC | REST API router for data type CRUD: `GET/POST /api/v1/data-types`, `GET/PUT/DELETE /api/v1/data-types/{id}`. Includes usage query parameter for delete-guard UI. Located in `backend/app/api/v1/data_types.py`. |
| `OutputController` (public) | CC | REST API router for agent output querying and export: `GET /api/v1/agent-outputs`, `GET /api/v1/agent-outputs/export`. JWT-protected for UI consumption. Located in `backend/app/api/v1/agent_outputs.py`. |
| Internal Validation Endpoint | CC | `POST /api/v1/internal/validate-output` — mTLS-protected, accepts data_type_id + payload, returns validation result with field-level errors. Added to `backend/app/api/v1/internal/` router set. |
| Internal Output Endpoints | CC | `POST /api/v1/internal/agent-outputs` (create), `GET /api/v1/internal/agent-outputs` (query) — mTLS-protected for AR consumption. Added to `backend/app/api/v1/internal/` router set. |
| `query_result` Internal Endpoint | CC | `POST /api/v1/internal/system-tools/query-result` — mTLS-protected, resolves data_type_name to ID, calls OutputService, returns matching results. Added to `backend/app/api/v1/internal/system_tools.py`. |

### 2.2 Modified Backend Components

| Component | Service | Change |
|-----------|---------|--------|
| `AgentType` model | CC | Add `output_data_type_id` nullable FK column referencing `agent_data_types.id`. Located in `backend/app/db/models/agents.py`. |
| `AgentJob` model | CC | Add `output_id` nullable FK column referencing `agent_outputs.id` for convenience linking. Located in `backend/app/db/models/agents.py`. |
| `save_result` system tool handler | CC | Enhanced to detect typed agent types by checking `output_data_type_id` on the session's `AgentType`. If set, validate payload and persist via `OutputService.save_typed` instead of the untyped `ResultStore.save` path. Backward-compatible: untyped agents use existing flow. Located in `backend/app/api/v1/internal/system_tools.py`. |
| `runtime_executor.py` | AR | Execution completion logic enhanced: after agent completes, check if `agent_type.output_data_type_id` is set. If yes, call CC validation endpoint, then CC output persistence endpoint. Wire returned `output_id` back to `AgentJob.output_id`. Located in `backend/app/services/agents/runtime_executor.py`. |
| `SystemToolRegistry` | AR | Register `query_result` tool definition with input schema. Located in `backend/app/services/agents/system_tool_registry.py`. |
| `system_tools.py` | CC | Add `"query_result"` to `SYSTEM_TOOL_NAMES` frozenset. Located in `backend/app/services/system_tools.py`. |
| CH `tool_routing.py` | CH | Add `query_result` route entry mapping `system____query_result` to `{cc_base}/api/v1/internal/system-tools/query-result`. Located in `backend/app/communication_hub/api/internal/tool_routing.py`. |

### 2.3 New Frontend Components

| Component | Responsibility |
|-----------|----------------|
| `DataTypesPage` | Admin page listing all data types with create/edit/delete actions, pagination, usage display. Located at `frontend/src/pages/data-types/DataTypesPage.tsx`. |
| `DataTypeFormDialog` | Create/edit dialog with name, slug, description fields and a dynamic field editor supporting string/number/boolean/date/enum field types. Located at `frontend/src/pages/data-types/DataTypeFormDialog.tsx`. |
| `DataTypeSelector` | Dropdown/autocomplete component for selecting a data type. Used in Agent Type form. Located at `frontend/src/components/data-types/DataTypeSelector.tsx`. |
| `AgentOutputsPage` | Admin page for querying typed outputs: filter bar (data type, date range, agent type), dynamic table with schema-based columns, row detail drawer, CSV export. Located at `frontend/src/pages/agent-outputs/AgentOutputsPage.tsx`. |
| `AgentOutputDetailDrawer` | Drawer showing full typed output details with schema-based field rendering, validation error display, raw fallback. Located at `frontend/src/pages/agent-outputs/AgentOutputDetailDrawer.tsx`. |
| `TypedOutputRenderer` | Component rendering typed output as a structured field-by-field view following a data type schema. Uses type-aware sub-components. Located at `frontend/src/components/executions/TypedOutputRenderer.tsx`. |
| `TypedFieldRenderers` | Collection of type-aware field value renderers: `BooleanFieldValue`, `DateFieldValue`, `EnumFieldValue`, `NumberFieldValue`, `StringFieldValue`. Located at `frontend/src/components/executions/TypedFieldRenderers.tsx`. |

### 2.4 Modified Frontend Components

| Component | Change |
|-----------|--------|
| `OutputTypeResultTab` | Updated to detect typed outputs, fetch data type schema, render via `TypedOutputRenderer`, show data type name badge, display validation errors with raw fallback. Located at `frontend/src/components/executions/OutputTypeResultTab.tsx`. |
| `AgentTypeForm` | Added "Output Data Type" selector (conditionally rendered for non-conversational agent types). Updated form values to include `output_data_type_id`. Located at `frontend/src/pages/agents/AgentTypeForm.tsx`. |
| `AgentManagementPage` | Output type badge now displays assigned data type name when `output_data_type_id` is set. Located at `frontend/src/pages/agents/AgentManagementPage.tsx`. |
| `SessionExecutionLogsDialog` | Fetch data type schema before rendering Result tab for typed sessions. Located at `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx`. |
| `AgentTypeDetailsDialog` | Show assigned data type name in output type details section. Located at `frontend/src/components/agents/AgentTypeDetailsDialog.tsx`. |
| `AppRouter` | Add new routes: `/admin/data-types`, `/admin/agent-outputs`. Located at `frontend/src/app/AppRouter.tsx`. |
| `AppShell` (nav) | Add nav links for "Data Types" and "Agent Outputs" to the admin sidebar. Located at `frontend/src/app/AppShell.tsx`. |

### 2.5 New Frontend Hooks

| Hook | Responsibility |
|------|----------------|
| `useDataTypes` | React Query hook for data type CRUD: paginated list, create/update/delete mutations with cache invalidation. Located at `frontend/src/hooks/useDataTypes.ts`. |
| `useDataTypesWithUsage` | React Query hook for data types enriched with referencing agent type counts. Located at `frontend/src/hooks/useDataTypes.ts`. |
| `useAgentOutputs` | React Query hook for querying agent outputs with filters and pagination, plus export mutation for CSV download. Located at `frontend/src/hooks/useAgentOutputs.ts`. |

### 2.6 New TypeScript Types

| Type | Responsibility |
|------|----------------|
| `AgentDataTypeField` | Interface for a single field definition: name, type, enum_values, required, default. Located in `frontend/src/types/index.ts`. |
| `AgentDataType` | Interface for the full data type entity: id, name, slug, description, fields, timestamps. Located in `frontend/src/types/index.ts`. |
| `DataTypeFieldType` | Union type: `'string' \| 'number' \| 'boolean' \| 'date' \| 'enum'`. Located in `frontend/src/types/index.ts`. |
| `AgentOutputResponse` | Interface for typed output record with resolved names. Located in `frontend/src/types/index.ts`. |
| `AgentOutputQueryParams` | Interface for output query filters. Located in `frontend/src/types/index.ts`. |

---

## 3. API Changes

### 3.1 New Public Endpoints (JWT-protected, for Frontend)

| Method | Path | Description | Query Params |
|--------|------|-------------|-------------|
| `GET` | `/api/v1/data-types` | List data types (paginated). `?usage=true` returns usage counts. | `page`, `page_size`, `search`, `usage` (bool) |
| `POST` | `/api/v1/data-types` | Create a new data type. Body: `{name, slug, description, fields}`. Returns 201. | — |
| `GET` | `/api/v1/data-types/{id}` | Get single data type with full schema. Returns 404 if not found. | — |
| `PUT` | `/api/v1/data-types/{id}` | Update data type fields or metadata. Returns 200. | — |
| `DELETE` | `/api/v1/data-types/{id}` | Delete data type. Returns 204 on success, 409 if referenced by agent types (body lists referencing types). | — |
| `GET` | `/api/v1/agent-outputs` | Query typed outputs with filters. Returns paginated list. | `data_type_id`, `agent_type_id`, `date_from`, `date_to`, `page`, `page_size` |
| `GET` | `/api/v1/agent-outputs/export` | CSV export of filtered outputs. Same filter params. Returns `text/csv` stream. | `data_type_id`, `agent_type_id`, `date_from`, `date_to` |

### 3.2 New Internal Endpoints (mTLS-protected, for Agent Runtime)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/internal/validate-output` | Validate a payload against a data type schema. Returns `{valid, errors[]}`. | Service certificate |
| `POST` | `/api/v1/internal/agent-outputs` | Persist a typed output record. Creates `AgentOutput` row. Returns output record ID. | Service certificate |
| `GET` | `/api/v1/internal/agent-outputs` | Query typed outputs (used by `query_result` tool). Returns list of output records. | Service certificate |
| `POST` | `/api/v1/internal/system-tools/query-result` | `query_result` system tool handler. Resolves data type name, calls OutputService, returns matching results. | Service certificate |

### 3.3 Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/api/v1/agents` | Accepts optional `output_data_type_id` field. When set alongside `output_type = typed`, links the agent type to a data type. |
| `PUT` | `/api/v1/agents/{id}` | Accepts optional `output_data_type_id` field. Updates the data type link. |
| `GET` | `/api/v1/agents/{id}` | Response includes `output_data_type_id` and resolved `output_data_type_name` for display. |
| `POST` | `/api/v1/internal/system-tools/save-result` | Enhanced: checks session's agent type for `output_data_type_id`. If set, validates and persists typed output. If not set, uses existing untyped persistence path. |

### 3.4 Error Codes

| Status | Context | Meaning |
|--------|---------|---------|
| 409 | `DELETE /api/v1/data-types/{id}` | Data type is referenced by one or more agent types. Response body includes `referencing_agent_types: [{id, name}]`. |
| 422 | `POST /api/v1/data-types` | Validation failure: duplicate name, empty fields list, invalid field type, duplicate field names. |
| 404 | `GET /api/v1/internal/system-tools/query-result` | Unknown data type name/slug provided. |

---

## 4. State Management

### 4.1 React Query Cache

| Query Key | Data | Invalidated By |
|-----------|------|----------------|
| `['data-types', params]` | Paginated data type list | Create, update, delete mutations |
| `['data-types', { id }]` | Single data type with schema | Update mutation |
| `['data-types', 'usage']` | Data types with usage counts | Create, delete mutations |
| `['agent-outputs', params]` | Paginated output list | (Read-only — outputs are immutable) |
| `['agent-types', ...]` | Agent type list (existing) | Agent type create/update with `output_data_type_id` |

### 4.2 Component State (Frontend)

| Component | State Variable | Type | Purpose |
|-----------|---------------|------|---------|
| `DataTypeFormDialog` | `fields` | `AgentDataTypeField[]` | Mutable array of field definitions in the field editor |
| `DataTypeFormDialog` | `dialogError` | `unknown` | Error state per Dialog Error Handling Standard |
| `DataTypesPage` | `deleteTarget` | `AgentDataType \| null` | Data type pending deletion confirmation |
| `DataTypesPage` | `deleteUsageInfo` | `AgentType[] \| null` | Referencing agent types for delete guard |
| `AgentOutputsPage` | `filters` | `AgentOutputQueryParams` | Current filter selections |
| `AgentOutputsPage` | `selectedOutput` | `AgentOutputResponse \| null` | Output selected for detail drawer |
| `AgentTypeForm` | `outputDataTypeId` | `string \| null` | Selected data type ID (new field in form values) |
| `OutputTypeResultTab` | `dataTypeSchema` | `AgentDataType \| null` | Fetched schema for typed output rendering |
| `OutputTypeResultTab` | `schemaLoading` | `boolean` | Loading state while fetching schema |

### 4.3 Data Flow (Agent Outputs Page)

```
User selects data type filter
  → data_type_id added to filters
  → useAgentOutputs refetches with new filter
  → table columns recompute from selected data type's fields array
  → field value columns appear/disappear dynamically
  → pagination resets to page 1

User selects date range
  → filters update
  → debounced refetch triggers
  → table updates results

User clicks Export CSV
  → useExportAgentOutputs mutation fires
  → GET /api/v1/agent-outputs/export with current filters
  → blob response triggers file download
```

---

## 5. Data Access Patterns

### 5.1 Data Type Registry (CC-owned)

**Pattern:** CRUD via SQLAlchemy async session, always within CC service boundary.

Data type definitions are created, read, updated, and deleted exclusively through CC API endpoints. The `agent_data_types` table is read by:
- **CC services** (SchemaValidationService — fetches schema for validation)
- **CC API layer** (resolves data type ID to name for response enrichment)
- **AR indirectly** — AR never queries the table directly; it calls CC internal endpoints

The delete guard checks the `agent_types.output_data_type_id` FK column via a `SELECT count(*) FROM agent_types WHERE output_data_type_id = :id` query before allowing deletion.

### 5.2 Output Persistence (CC-owned)

**Pattern:** Two-phase write via CC internal API.

When a typed agent completes execution:
1. **Phase 1 — Validation:** AR calls `POST /api/v1/internal/validate-output` with the output payload and the assigned `data_type_id`. CC fetches the schema from `AgentDataType`, validates field types/required/enum constraints, returns `{valid, errors[]}`.
2. **Phase 2 — Persistence:** AR calls `POST /api/v1/internal/agent-outputs` with `{data_type_id, agent_type_id, execution_session_id, field_values, validation_status, raw_output}`. CC creates an `AgentOutput` row and updates the `AgentJob.output_id` FK.

If validation fails, Phase 2 still runs with `validation_status = validation_error` and `field_values` = null (raw output stored as fallback). This ensures the execution record is always persisted.

### 5.3 Output Querying

**Pattern:** Filtered SQLAlchemy queries with pagination.

The public `GET /api/v1/agent-outputs` endpoint builds a dynamic query from filter parameters:
- `data_type_id` — exact match on FK
- `agent_type_id` — exact match on FK
- `date_from` / `date_to` — range filter on `created_at`
- `page` / `page_size` — standard offset pagination

The internal `GET /api/v1/internal/agent-outputs` (used by `query_result`) supports the same filters plus optional `field_filters` — key-value pairs that filter `field_values` JSONB using PostgreSQL `@>` containment operator or individual key extraction.

CSV export reuses the same filtering logic but returns a `StreamingResponse` with no pagination limit. Column headers are derived from the fields of the selected data type (if a single `data_type_id` is specified) or fall back to a fixed set of base columns (timestamp, agent type, data type, status).

### 5.4 `query_result` Tool Call Flow

**Pattern:** AR → CH → CC (multi-hop, existing system tool routing pattern).

1. Agent calls `system____query_result` with `{data_type_name: string, filters?: {date_from?, date_to?, field_filters?: Record<string, unknown>}}`.
2. AR identifies the tool as a system tool via `is_system_tool()` and routes through CH.
3. CH matches `system____query_result` in its tool routing map and forwards to CC's `POST /api/v1/internal/system-tools/query-result`.
4. CC resolves `data_type_name` to `AgentDataType.id` (by slug first, then by name), calls `OutputService.list_outputs` with the resolved `data_type_id` and optional filters, returns matching results.
5. Results flow back through CH to AR, which formats them as a tool response for the agent.

### 5.5 Backward Compatibility

**Pattern:** Conditional branching based on `output_data_type_id` presence.

All existing code paths are preserved:
- `save_result` handler checks `session.agent_type.output_data_type_id`; if null, uses existing `ResultStore.save` path unchanged.
- Execution completion in `runtime_executor.py` checks `agent_type.output_data_type_id`; if null, uses existing completion flow.
- `OutputTypeResultTab` checks for `data_type_id` in output data; if absent, renders via existing JSON tree view.
- `AgentTypeForm` conditionally renders the data type selector only when `input_type !== 'conversation'`.

### 5.6 Enum Handling (Alembic Migrations)

All new enum types (`AgentOutputValidationStatus`) must use `postgresql.ENUM(..., create_type=False)` in migration files to avoid conflicts with the type already created by model import. No parameterized DDL statements in migrations.

---

## 6. Code Reference Map

### 6.1 Backend — New Models

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentDataType` | model | SQLAlchemy model for data type registry: id, name, slug, description, fields (JSONB), created_at, updated_at | `backend/app/db/models/agent_data_type.py` |
| `AgentOutput` | model | SQLAlchemy model for typed execution results: id, data_type_id FK, agent_type_id FK, execution_session_id FK, field_values (JSONB), validation_status (enum), raw_output (Text), created_at | `backend/app/db/models/agent_output.py` |
| `AgentOutputValidationStatus` | enum | Python StrEnum: `valid`, `validation_error` | `backend/app/db/models/agent_output.py` |

### 6.2 Backend — Modified Models

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentType` | model | **MODIFIED**: Added `output_data_type_id` nullable FK column to `agent_data_types.id`; added `output_data_type` relationship | `backend/app/db/models/agents.py` |
| `AgentJob` | model | **MODIFIED**: Added `output_id` nullable FK column to `agent_outputs.id`; added convenience relationship | `backend/app/db/models/agents.py` |

### 6.3 Backend — New Schemas

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `DataTypeFieldType` | enum | String enum of supported field types: string, number, boolean, date, enum | `backend/app/schemas/data_types.py` |
| `DataTypeFieldCreate` | schema | Field definition: name, type enum, enum_values, required, default | `backend/app/schemas/data_types.py` |
| `DataTypeFieldResponse` | schema | Field definition in API responses | `backend/app/schemas/data_types.py` |
| `DataTypeCreate` | schema | Data type creation request: name, slug, description, fields[] | `backend/app/schemas/data_types.py` |
| `DataTypeUpdate` | schema | Data type update request: all fields optional | `backend/app/schemas/data_types.py` |
| `DataTypeResponse` | schema | Data type response: all fields including timestamps | `backend/app/schemas/data_types.py` |
| `DataTypeListResponse` | schema | Paginated list wrapper with optional usage counts | `backend/app/schemas/data_types.py` |
| `DataTypeUsageInfo` | schema | Usage information returned when ?usage=true | `backend/app/schemas/data_types.py` |
| `AgentOutputCreate` | schema | Typed output create request (internal) | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputResponse` | schema | Typed output response with resolved names | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputQueryParams` | schema | Filter/pagination params for output query | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputListResponse` | schema | Paginated output list wrapper | `backend/app/schemas/agent_outputs.py` |
| `ValidationResult` | schema | Validation result: `{valid: bool, errors: list[FieldError]}` | `backend/app/schemas/agent_outputs.py` |

### 6.4 Backend — New Services

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `DataTypeService` | class | CRUD operations for AgentDataType: create, get, update, delete (blocked if referenced), list (paginated, searchable), get_by_slug, count_usage, _get_referencing_agent_types | `backend/app/services/data_types/service.py` |
| `DataTypeNotFoundError` | exception | Raised when a data type is not found | `backend/app/services/data_types/service.py` |
| `DataTypeConflictError` | exception | Raised when deletion is blocked by referencing agent types | `backend/app/services/data_types/service.py` |
| `DataTypeDuplicateError` | exception | Raised when creating/updating with a duplicate name or slug | `backend/app/services/data_types/service.py` |
| `OutputService` | class | Typed output persistence and query: save_typed, list_outputs (with filters), get_output, export_csv | `backend/app/services/outputs/service.py` |
| `SchemaValidationService` | class | Payload validation against data type schema: field type checking, required field validation, enum value membership, field-level error collection | `backend/app/services/validation/schema_validation_service.py` |

### 6.5 Backend — New API Routers

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `DataTypeRouter` | APIRouter | `GET/POST /api/v1/data-types`, `GET/PUT/DELETE /api/v1/data-types/{id}`. `?usage=true` returns usage counts. All endpoints protected by `require_permission(RT_DATA_TYPE, ...)` | `backend/app/api/v1/data_types.py` |
| `OutputRouter` (public) | APIRouter | `GET /api/v1/agent-outputs` (paginated, filtered), `GET /api/v1/agent-outputs/export` (CSV StreamingResponse). JWT-protected via `require_permission(RT_RESULT, "read")`. Registered in `backend/app/api/v1/__init__.py` import + `router.include_router(OutputRouter)`. | `backend/app/api/v1/agent_outputs.py` |

### 6.6 Backend — Modified API Routers

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRouter` | APIRouter | **MODIFIED**: Accepts `output_data_type_id` in create/update AgentType payloads; returns `output_data_type_name` in responses | `backend/app/api/v1/agents.py` |
| `InternalSystemToolsRouter` | router | **MODIFIED**: Enhanced `POST /save-result` for typed output persistence; added `POST /query-result` endpoint | `backend/app/api/v1/internal/system_tools.py` |

### 6.7 Backend — New Internal Endpoints

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `validate_output` | endpoint | `POST /api/v1/internal/validate-output` — mTLS-protected, validates payload against data type schema | `backend/app/api/v1/internal/` (new file or added to existing) |
| `create_internal_output` | endpoint | `POST /api/v1/internal/agent-outputs` — mTLS-protected, persists typed output record | `backend/app/api/v1/internal/` |
| `query_internal_outputs` | endpoint | `GET /api/v1/internal/agent-outputs` — mTLS-protected, queries typed outputs with filters | `backend/app/api/v1/internal/` |
| `query_result_tool` | endpoint | `POST /api/v1/internal/system-tools/query-result` — mTLS-protected, resolves data type name, returns matching outputs | `backend/app/api/v1/internal/system_tools.py` |

### 6.8 Backend — Modified Services

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `runtime_executor.py` | module | **MODIFIED**: Execution completion checks `agent_type.output_data_type_id`, calls CC validation and output persistence for typed agents | `backend/app/services/agents/runtime_executor.py` |
| `SystemToolRegistry` | class | **MODIFIED**: Registers `query_result` tool with input schema definition | `backend/app/services/agents/system_tool_registry.py` |
| `system_tools.py` | module | **MODIFIED**: Added `"query_result"` to `SYSTEM_TOOL_NAMES` frozenset | `backend/app/services/system_tools.py` |
| `ResultStore` | class | **Unchanged** — `save_result` enhancement is in `system_tools.py` handler, not in this class. Class remains backward-compatible | `backend/app/services/results/store.py` |

### 6.9 Backend — Communication Hub

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `tool_routing.py` | module | **MODIFIED**: Added `query_result` route mapping `system____query_result` to CC internal endpoint | `backend/app/communication_hub/api/internal/tool_routing.py` |

### 6.10 Frontend — New Pages

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `DataTypesPage` | page | Admin data types list with CRUD actions, pagination, usage display. Uses `useDataTypes` hook for data fetching and `DataTypeFormDialog` for create/edit. Delete confirmation fetches usage info and blocks deletion if referenced. | `frontend/src/pages/data-types/DataTypesPage.tsx` |
| `DataTypeFormDialog` | component | Create/edit dialog with field editor supporting 5 field types (string/number/boolean/date/enum). Follows Dialog Error Handling Standard. Dynamic field rows with name, type selector, enum_values, required toggle. | `frontend/src/pages/data-types/DataTypeFormDialog.tsx` |
| `AgentOutputsPage` | page | Admin agent outputs page with filter bar (data type, agent type, date range), dynamic table with schema-based columns, validation status badges, CSV export, row click → detail drawer | `frontend/src/pages/agent-outputs/AgentOutputsPage.tsx` |
| `AgentOutputDetailDrawer` | component | MUI Drawer opened on row click showing full output detail with TypedOutputRenderer, metadata (agent type, data type, timestamp, validation status), validation error banner, raw output fallback | `frontend/src/pages/agent-outputs/AgentOutputDetailDrawer.tsx` |

### 6.11 Frontend — New Components

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `DataTypeSelector` | component | Data type dropdown selector — implemented inline in `AgentTypeForm` following existing `FormControl`+`InputLabel`+`Select` pattern instead of a separate component file | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `TypedOutputRenderer` | component | Renders typed output fields as a structured field-by-field view | `frontend/src/components/executions/TypedOutputRenderer.tsx` |
| `TypedFieldRenderers` | module | Collection of type-aware field renderers (BooleanFieldValue, DateFieldValue, EnumFieldValue, NumberFieldValue, StringFieldValue) | `frontend/src/components/executions/TypedFieldRenderers.tsx` |

### 6.12 Frontend — Modified Components

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `OutputTypeResultTab` | component | **MODIFIED**: Detects typed outputs, fetches schema, renders via TypedOutputRenderer, shows data type badge and validation errors | `frontend/src/components/executions/OutputTypeResultTab.tsx` |
| `AgentTypeForm` | component | **MODIFIED**: Added conditional Output Data Type selector; updated form values interface | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentManagementPage` | page | **MODIFIED**: Output type badge shows assigned data type name | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentExecutionDetailsDialog` | component | **MODIFIED**: Extracts typed output metadata (`__data_type_id`, `__data_type_name`, `validation_status`, `raw_output`) from session output_data and passes to OutputTypeResultTab for schema-aware rendering | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `AgentTypeDetailsDialog` | component | **MODIFIED**: Shows assigned data type name in output details | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AppRouter` | component | **MODIFIED**: Added route `<Route path="/admin/agent-outputs" element={<AgentOutputsPage />} />` | `frontend/src/app/AppRouter.tsx` |
| `AppShell` | component | **MODIFIED**: Added nav link `nav.agentOutputs` → `/admin/agent-outputs` in System group with ListAltIcon | `frontend/src/app/AppShell.tsx` |

### 6.13 Frontend — New Hooks

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `useDataTypes` | hook | React Query hook: paginated data type list (`GET /api/v1/data-types` with page/page_size/search params). Query key: `['data-types', params]`. | `frontend/src/hooks/useDataTypes.ts` |
| `useDataTypesWithUsage` | hook | React Query hook: data types with referencing agent type counts. Calls `GET /api/v1/data-types?usage=true`. Query key: `['data-types', 'usage']`. | `frontend/src/hooks/useDataTypes.ts` |
| `useDataType` | hook | React Query hook: single data type by ID (`GET /api/v1/data-types/{id}`). Enabled only when id is truthy. | `frontend/src/hooks/useDataTypes.ts` |
| `useCreateDataType` | hook | React Query mutation: `POST /api/v1/data-types`. Invalidates `['data-types']` query key on success. | `frontend/src/hooks/useDataTypes.ts` |
| `useUpdateDataType` | hook | React Query mutation: `PUT /api/v1/data-types/{id}`. Invalidates `['data-types']` query key on success. | `frontend/src/hooks/useDataTypes.ts` |
| `useDeleteDataType` | hook | React Query mutation: `DELETE /api/v1/data-types/{id}`. Invalidates both `['data-types']` and `['data-types', 'usage']` query keys on success. | `frontend/src/hooks/useDataTypes.ts` |
| `fetchDataTypeUsage` | function | Standalone API call to fetch referencing agent types for a data type. Used by delete-guard UI. | `frontend/src/hooks/useDataTypes.ts` |
| `useAgentOutputs` | hook | React Query hook: paginated agent outputs query (`GET /api/v1/agent-outputs` with filter/pagination params). Query key: `['agent-outputs', params]`. | `frontend/src/hooks/useAgentOutputs.ts` |
| `useExportAgentOutputs` | hook | React Query mutation: `GET /api/v1/agent-outputs/export` with responseType `blob`. Triggers browser file download on success with filename `agent-outputs-{YYYY-MM-DD}.csv`. | `frontend/src/hooks/useAgentOutputs.ts` |

### 6.14 Frontend — Types

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `DataTypeFieldType` | type | Union: `'string' \| 'number' \| 'boolean' \| 'date' \| 'enum'` | `frontend/src/types/index.ts` |
| `AgentDataTypeField` | interface | Single field definition: name, type, enum_values?, required?, default | `frontend/src/types/index.ts` |
| `AgentDataType` | interface | Full data type entity: id, name, slug, description, fields[], created_at, updated_at | `frontend/src/types/index.ts` |
| `ReferencingAgentType` | interface | Referencing agent type info: id, name. Used in delete-guard UI. | `frontend/src/types/index.ts` |
| `DataTypeCreate` | interface | Data type creation request payload: name, slug, description?, fields[] | `frontend/src/types/index.ts` |
| `DataTypeUpdate` | interface | Data type update payload: all fields optional | `frontend/src/types/index.ts` |
| `DataTypeListResponse` | interface | Paginated list response: items[], total, page, page_size, usage?, referencing_agent_types? | `frontend/src/types/index.ts` |
| `AgentOutputResponse` | interface | Typed output response with resolved names: id, data_type_id, data_type_name, agent_type_id, agent_type_name, execution_session_id, field_values, validation_status, raw_output, created_at | `frontend/src/types/index.ts` |
| `AgentOutputQueryParams` | interface | Output query filter params: data_type_id, agent_type_id, date_from, date_to, page, page_size | `frontend/src/types/index.ts` |
| `AgentOutputListResponse` | interface | Paginated list response: items[], total, page, page_size | `frontend/src/types/index.ts` |
| `AgentOutputExportParams` | interface | CSV export filter params (subset of query params without pagination): data_type_id, agent_type_id, date_from, date_to | `frontend/src/types/index.ts` |

### 6.15 Frontend — i18n Keys (New)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `admin.dataTypes.*` | key group | Data types page strings: title, create, edit, delete, name, slug, slugHelper, description, fields, fieldName, fieldType, enumValues, required, addField, removeField, fieldCount, inUse, referencedBy, confirmDelete, confirmDeleteMessage, atLeastOneField | `frontend/src/i18n/locales/en.json` |
| `nav.dataTypes` | key | Nav sidebar "Data Types" label | `frontend/src/i18n/locales/en.json` |
| `admin.agentOutputs.*` | key group | Agent outputs page strings: title, filterDataType, filterAgentType, filterDateFrom, filterDateTo, exportCsv, columnTimestamp, columnAgentType, columnDataType, columnStatus, statusValid, statusError, detailTitle, noResults, loading, error | `frontend/src/i18n/locales/en.json` |
| `nav.agentOutputs` | key | Nav sidebar "Agent Outputs" label | `frontend/src/i18n/locales/en.json` |
| `agents.types.outputDataType` | key | "Output Data Type" label for agent type form | `frontend/src/i18n/locales/en.json` |
| `agents.types.noOutputDataType` | key | "None — no data type assigned" option in selector | `frontend/src/i18n/locales/en.json` |
| `agents.types.outputDataTypeHint` | key | Helper text below the data type selector | `frontend/src/i18n/locales/en.json` |
| `executionLog.result.*` | key group | Typed output display strings: dataTypeBadge, validationError, fieldErrors, rawFallback (Phase 5) | `frontend/src/i18n/locales/en.json` |
| `typedField.*` | key group | Type-aware field renderer strings: true, false, null, empty (Phase 5) | `frontend/src/i18n/locales/en.json` |

### 6.16 Backend — Existing API Clients

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `apiClient` | AxiosInstance | Configured axios client with JWT auth injection (frontend) | `frontend/src/api/apiClient.ts` |
| `CommunicationHubClient` | class | CC → CH HTTP client for dispatching messages | `backend/app/services/control_center/comm_hub_client.py` |

### 6.17 Backend — Existing Models (Referenced)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentType` | model | Agent type definition: output_type, output_schema, and new output_data_type_id | `backend/app/db/models/agents.py` |
| `AgentJob` | model | Execution session (AgentJob): status, output_data, and new output_id | `backend/app/db/models/agents.py` |
| `ResultRecord` | model | Existing untyped result record (unchanged) | `backend/app/db/models/results.py` |

### 6.18 Backend — Existing Services (Referenced)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `ResultStore` | class | Existing untyped result persistence (unchanged) | `backend/app/services/results/store.py` |
| `is_system_tool` | function | System tool name detection | `backend/app/services/system_tools.py` |
| `get_canonical_name` | function | Tool name normalization | `backend/app/services/system_tools.py` |
| `SystemToolRegistry` | class | System tool schema registry | `backend/app/services/agents/system_tool_registry.py` |

### 6.19 Backend — Existing Dependencies

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `require_service_certificate` | dep | mTLS authentication for internal endpoints | `backend/app/api/deps.py` |
| `require_permission` | dep | JWT-based RBAC auth for public endpoints | `backend/app/api/deps.py` |
| `DbSession` | type | Async SQLAlchemy session dependency | `backend/app/db/session.py` |
| `RT_DATA_TYPE` | constant | Resource type identifier for data_type permission checks | `backend/app/core/resource_types.py` |

### 6.20 Test Files

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `test_data_types_api.py` | test | Backend tests for DataTypeService and DataTypeController: create (201), duplicate name (409), get by id (200/404), update (200/404/409), delete unreferenced (204), delete referenced (409), empty fields (422), invalid field type (422), pagination, search | `backend/tests/test_data_types_api.py` |
| `test_output_validation.py` | test | Backend tests for SchemaValidationService | `backend/tests/test_output_validation.py` |
| `test_agent_outputs_api.py` | test | Backend tests for OutputService and internal/public endpoints | `backend/tests/test_agent_outputs_api.py` |
| `test_save_result_typed.py` | test | Backend tests for enhanced save_result with typed output flow | `backend/tests/test_save_result_typed.py` |
| `test_query_result_tool.py` | test | Backend integration tests for query_result tool flow | `backend/tests/test_query_result_tool.py` |
| `DataTypesPage.test` | test | Frontend tests for DataTypesPage: renders title, data types list, slugs, field counts, create/edit/delete buttons, empty state, loading state | `frontend/src/__tests__/DataTypesPage.test.tsx` |
| `AgentOutputsPage.test` | test | Frontend tests for AgentOutputsPage: renders title, filter selectors, export button, output entries with data type/agent type names, validation status chips, empty state, loading state | `frontend/src/__tests__/AgentOutputsPage.test.tsx` |
| `AgentOutputDetailDrawer.test` | test | Frontend tests for AgentOutputDetailDrawer: renders nothing when null output, valid output with TypedOutputRenderer, validation error status with raw fallback, close button | `frontend/src/__tests__/AgentOutputDetailDrawer.test.tsx` |
| `DataTypeFormDialog.test` | test | Frontend tests for DataTypeFormDialog: create mode with empty fields, edit mode with pre-populated data, add/remove field, cancel, save with onClose | `frontend/src/__tests__/DataTypeFormDialog.test.tsx` |
| `AgentTypeForm.test` | test | **UPDATED**: Added data type selector tests — renders dropdown label, hint text, opens options, selects value and calls onChange with correct output_data_type_id | `frontend/src/__tests__/AgentTypeForm.test.tsx` |
| `AgentManagementPage.test` | test | **UPDATED**: Added Data Type column tests — renders column header, shows data type name chip when assigned, shows dash when null | `frontend/src/__tests__/AgentManagementPage.test.tsx` |
| `OutputTypeResultTab.test` | test | **UPDATED**: Frontend tests for typed output rendering, validation error display (Phase 5) | `frontend/src/__tests__/OutputTypeResultTab.test.tsx` |
| `TypedOutputRenderer.test` | test | Frontend tests for typed output renderer covering all field types (Phase 5) | `frontend/src/__tests__/TypedOutputRenderer.test.tsx` |

### 6.21 Migration Files

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `a69529d1090f_add_agent_data_types_table.py` | migration | Creates `agent_data_types` table | `backend/alembic/versions/a69529d1090f_add_agent_data_types_table.py` |
| `3131c85e74e0_add_agent_outputs_table_and_output_id_.py` | migration | Creates `agent_outputs` table with `AgentOutputValidationStatus` enum + adds `output_id` FK to `agent_jobs` | `backend/alembic/versions/3131c85e74e0_add_agent_outputs_table_and_output_id_.py` |
| `76078a3ecff2_add_output_data_type_id_to_agent_types.py` | migration | Adds `output_data_type_id` FK to `agent_types` (Phase 3) | `backend/alembic/versions/76078a3ecff2_add_output_data_type_id_to_agent_types.py` |
| `3131c85e74e0_add_agent_outputs_table_and_output_id_.py` | migration | Adds `output_id` FK to `agent_jobs` (included in Phase 4 migration) | `backend/alembic/versions/3131c85e74e0_add_agent_outputs_table_and_output_id_.py` |
| `a1d4e8f2b3c5_migrate_existing_typed_agent_types.py` | migration | Data migration for existing `typed` agent types | `backend/alembic/versions/a1d4e8f2b3c5_migrate_existing_typed_agent_types.py` |

### 6.22 Spec Documents (Master — to be updated post-implementation)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| Agent Data Type Registry | doc | New data type registry feature spec | `docs/master/product/features/agent-data-types.md` |
| Agent Types feature spec | doc | Update to describe output data type assignment | `docs/master/product/features/agent-types.md` |
| Agent Execution feature spec | doc | Update to describe typed execution, enhanced save_result, query_result tool | `docs/master/product/features/agent-execution.md` |
| Agent Session Logs feature spec | doc | Update Result tab to describe typed output rendering | `docs/master/product/features/agent-session-logs.md` |
| Result Management feature spec | doc | Update to describe typed outputs, Agent Outputs page | `docs/master/product/features/result-management.md` |
| Overall data model | doc | Add AgentDataType, AgentOutput entities | `docs/master/data-model/overview.md` |
| Control Center architecture | doc | Add Data Type Registry, Output Store, Schema Validation Service modules | `docs/master/architecture/modules/control-center/architecture.md` |
| Agent Runtime architecture | doc | Add query_result handler, execution completion validation | `docs/master/architecture/modules/agent-runtime/architecture.md` |
| Communication Hub architecture | doc | Add query_result routing to tool call flow | `docs/master/architecture/modules/communication-hub/architecture.md` |
| System overview architecture | doc | Update diagrams with new components and data flows | `docs/master/architecture/system-overview.md` |
| Master tech spec | doc | Add code reference map entries for all new/modified symbols | `docs/master/technology/modules/agents/tech-spec.md` |
| Master UI test plan | doc | Add test scenarios for Data Types page, Agent Outputs page, typed rendering | `docs/master/qa/test-plans/agents-ui-test-plan.md` |
