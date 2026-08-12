# Module: data-types — Tech Spec

## Overview

The **Data Type Registry** is a centralized, Control Center-owned schema management system that enables administrators to define reusable typed output schemas. Each data type describes a set of fields — each with a name, type (string, number, boolean, date, or enum), optional enum values, required flag, and default value — that together form a contract for structured agent outputs.

Agent Types can optionally reference a data type via `output_data_type_id`. When a typed agent completes execution, Agent Runtime calls Control Center's internal validation endpoint to validate the output payload against the assigned schema, then persists the validated (or validation-failed) result as an `AgentOutput` record. The frontend provides admin pages for managing data types (CRUD) and querying/exporting typed agent outputs.

The module is owned entirely by **Control Center** — all database tables, services, and API endpoints reside within CC. Agent Runtime has no direct database access; it interacts via mTLS-protected internal endpoints.

---

## Key Components

### Backend — Models

| Component | Description |
|-----------|-------------|
| `AgentDataType` | SQLAlchemy model for a data type definition: `name` (unique), `slug` (unique), `description`, `fields` (JSONB array of field definitions). Referenced by `AgentType.output_data_type_id` FK. |
| `AgentOutput` | SQLAlchemy model for a typed execution result: `data_type_id` FK, `agent_type_id` FK, `execution_session_id` FK, `field_values` (JSONB), `validation_status` (enum), `raw_output` (Text fallback). Linked from `AgentJob.output_id` FK. |
| `AgentOutputValidationStatus` | Python StrEnum: `valid`, `validation_error` |

### Backend — Services

| Component | Description |
|-----------|-------------|
| `DataTypeService` | Full CRUD for `AgentDataType`. Enforces uniqueness on name and slug. Delete is blocked (409) if any `AgentType` references the data type — returns the list of referencing agent types. List supports pagination and search. Usage counts available via `count_usage()`. |
| `OutputService` | Typed output persistence and querying. `save_typed()` creates an `AgentOutput` row and wires its ID back to `AgentJob.output_id`. `list_outputs()` supports filtering by data type, agent type, and date range with pagination. `export_csv()` returns a `StreamingResponse` with schema-derived column headers. |
| `SchemaValidationService` | Validates a payload dict against a data type's `fields` schema. Checks required field presence, field type conformance, and enum value membership. Returns `ValidationResult` with `{valid: bool, errors: list[FieldError]}`. |

### Backend — Public API Routers

| Component | Description |
|-----------|-------------|
| `DataTypeRouter` | JWT-protected CRUD router at `/api/v1/data-types`. Supports `?usage=true` for usage counts (referencing agent type IDs and names). Permission: `RT_DATA_TYPE`. |
| `OutputRouter` (public) | JWT-protected query router at `/api/v1/agent-outputs`. Paginated listing with filters (data_type_id, agent_type_id, date range). CSV export at `/api/v1/agent-outputs/export`. Permission: `RT_RESULT`, `"read"`. |

### Backend — Internal Endpoints

| Component | Description |
|-----------|-------------|
| `POST /api/v1/internal/validate-output` | mTLS-protected. Accepts `{data_type_id, payload}`. Returns `ValidationResult` with field-level errors. Called by Agent Runtime during execution completion. |
| `POST /api/v1/internal/agent-outputs` | mTLS-protected. Persists a typed output record. Verifies data type and agent type exist. Returns `AgentOutputResponse` with resolved names. |
| `GET /api/v1/internal/agent-outputs` | mTLS-protected. Queries typed outputs with filters and pagination. Resolves data_type_name and agent_type_name per result. Used by `query_result` system tool. |

### Backend — Schemas

| Component | Description |
|-----------|-------------|
| `DataTypeFieldType` | String enum: `string`, `number`, `boolean`, `date`, `enum` |
| `DataTypeFieldCreate` / `DataTypeFieldResponse` | Field definition: name, type, enum_values, required, default |
| `DataTypeCreate` / `DataTypeUpdate` / `DataTypeResponse` | Data type CRUD contracts |
| `DataTypeListResponse` | Paginated list wrapper with optional usage info |
| `AgentOutputCreate` / `AgentOutputResponse` / `AgentOutputListResponse` | Output record contracts |
| `ValidationResult` | `{valid: bool, errors: list[{field, message}]}` |

### Frontend — Pages

| Component | Description |
|-----------|-------------|
| `DataTypesPage` | Admin page listing all data types with create/edit/delete actions, pagination, search, and field count display. Delete triggers usage check — blocked with a dialog listing referencing agent types. |
| `AgentOutputsPage` | Admin page for querying typed outputs: filter bar (data type, agent type, date range), dynamic table with schema-based columns derived from the selected data type's fields, validation status badges (green "Valid" / amber "Error"), CSV export button, row click → detail drawer. |

### Frontend — Dialogs & Components

| Component | Description |
|-----------|-------------|
| `DataTypeFormDialog` | Create/edit dialog with name, slug, description fields and a dynamic field editor (add/remove/reorder rows; each row: name, type selector, enum values for enum type, required toggle). Follows Dialog Error Handling Standard. |
| `DataTypeSelector` | Dropdown/autocomplete for selecting a data type. Used in Agent Type form. Implemented inline in `AgentTypeForm` following existing Material-UI patterns. |
| `AgentOutputDetailDrawer` | MUI Drawer showing full typed output details: metadata grid (agent type, data type, timestamp, validation status), `TypedOutputRenderer` for schema-based field display, validation error banner, and raw output fallback section. |
| `TypedOutputRenderer` | Renders typed output fields as a structured field-by-field view following a data type schema. Delegates to type-aware sub-renderers (BooleanFieldValue, DateFieldValue, EnumFieldValue, NumberFieldValue, StringFieldValue). |
| `TypedFieldRenderers` | Collection of type-aware field value renderers: `BooleanFieldValue` (true/false chip), `DateFieldValue` (locale-formatted date), `EnumFieldValue` (coloured chip), `NumberFieldValue` (formatted number), `StringFieldValue` (text). |
| `OutputTypeResultTab` | **MODIFIED**: Detects typed outputs via `data_type_id` in session output data; fetches data type schema; renders via `TypedOutputRenderer`; shows data type name badge and validation errors with raw fallback. |

### Frontend — Hooks

| Component | Description |
|-----------|-------------|
| `useDataTypes` | React Query hook for paginated data type list (`GET /api/v1/data-types`). Query key: `['data-types', params]`. |
| `useDataTypesWithUsage` | React Query hook: data types with referencing agent type counts (`GET /api/v1/data-types?usage=true`). Query key: `['data-types', 'usage']`. |
| `useDataType` | React Query hook: single data type by ID. Enabled only when ID is truthy. |
| `useCreateDataType` / `useUpdateDataType` / `useDeleteDataType` | React Query mutations with cache invalidation on `['data-types']` and `['data-types', 'usage']`. |
| `fetchDataTypeUsage` | Standalone function to fetch referencing agent types for delete-guard UI. |
| `useAgentOutputs` | React Query hook: paginated agent outputs query with filter/pagination params. Query key: `['agent-outputs', params]`. |
| `useExportAgentOutputs` | React Query mutation: `GET /api/v1/agent-outputs/export` as blob download; filename: `agent-outputs-{date}.csv`. |

### Frontend — Types

| Component | Description |
|-----------|-------------|
| `DataTypeFieldType` | Union: `'string' \| 'number' \| 'boolean' \| 'date' \| 'enum'` |
| `AgentDataTypeField` | Interface: `{name, type, enum_values?, required?, default}` |
| `AgentDataType` | Interface: `{id, name, slug, description, fields[], created_at, updated_at}` |
| `ReferencingAgentType` | Interface: `{id, name}` — used in delete-guard UI |
| `DataTypeCreate` / `DataTypeUpdate` / `DataTypeListResponse` | Request/response types for data type CRUD |
| `AgentOutputResponse` | Interface: `{id, data_type_id, data_type_name, agent_type_id, agent_type_name, execution_session_id, field_values, validation_status, raw_output, created_at}` |
| `AgentOutputQueryParams` | Interface: `{data_type_id?, agent_type_id?, date_from?, date_to?, page?, page_size?}` |
| `AgentOutputListResponse` | Interface: `{items[], total, page, page_size}` |
| `AgentOutputExportParams` | Interface: filter params without pagination for CSV export |

### Frontend — i18n Keys

| Key Group | Description | File |
|-----------|-------------|------|
| `admin.dataTypes.*` | Data types page: title, create, edit, delete, name, slug, description, fields, field editor labels, in-use warning | `frontend/src/i18n/locales/en.json` |
| `nav.dataTypes` | Sidebar "Data Types" label | `frontend/src/i18n/locales/en.json` |
| `admin.agentOutputs.*` | Agent outputs page: title, filters, export, columns, status labels, detail drawer | `frontend/src/i18n/locales/en.json` |
| `nav.agentOutputs` | Sidebar "Agent Outputs" label | `frontend/src/i18n/locales/en.json` |
| `agents.types.outputDataType` | "Output Data Type" form label | `frontend/src/i18n/locales/en.json` |
| `typedField.*` | Type-aware field renderer strings: true, false, null, empty | `frontend/src/i18n/locales/en.json` |

---

## API Endpoints

### Public (JWT-protected)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/data-types` | List data types (paginated, searchable). `?usage=true` includes referencing agent type info. |
| `POST` | `/api/v1/data-types` | Create a data type with field schema. Returns 201. |
| `GET` | `/api/v1/data-types/{id}` | Get single data type with full field schema. |
| `PUT` | `/api/v1/data-types/{id}` | Update data type fields or metadata. |
| `DELETE` | `/api/v1/data-types/{id}` | Delete data type. 204 on success, 409 with `{referencing_agent_types: [{id, name}]}` if in use. |
| `GET` | `/api/v1/agent-outputs` | Query typed outputs with filters and pagination. |
| `GET` | `/api/v1/agent-outputs/export` | CSV export of filtered outputs. `text/csv` streaming response. |

### Internal (mTLS-protected, for Agent Runtime)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/internal/validate-output` | Validate payload against a data type schema. |
| `POST` | `/api/v1/internal/agent-outputs` | Persist a typed output record. |
| `GET` | `/api/v1/internal/agent-outputs` | Query typed outputs with filters. |

### Error Codes

| Status | Context | Meaning |
|--------|---------|---------|
| 409 | `DELETE /data-types/{id}` | Referenced by one or more agent types. Body: `{referencing_agent_types: [{id, name}]}`. |
| 422 | `POST /data-types` | Validation failure: duplicate name/slug, empty fields list, invalid field type, duplicate field names. |
| 404 | `GET /data-types/{id}` | Data type not found. |

---

## Code Reference Map

### Backend Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentDataType` | model | Data type registry model: id, name (unique), slug (unique), description, fields (JSONB), timestamps | `backend/app/db/models/agent_data_type.py` |
| `AgentOutput` | model | Typed execution result: id, data_type_id FK, agent_type_id FK, execution_session_id FK, field_values (JSONB), validation_status (enum), raw_output (Text), created_at | `backend/app/db/models/agent_output.py` |
| `AgentOutputValidationStatus` | enum | `valid`, `validation_error` | `backend/app/db/models/agent_output.py` |

### Backend Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DataTypeFieldType` | enum | `string`, `number`, `boolean`, `date`, `enum` | `backend/app/schemas/data_types.py` |
| `DataTypeFieldCreate` | schema | Field definition: name, type, enum_values, required, default | `backend/app/schemas/data_types.py` |
| `DataTypeFieldResponse` | schema | Field definition in API responses | `backend/app/schemas/data_types.py` |
| `DataTypeCreate` | schema | Creation request: name, slug, description, fields[] | `backend/app/schemas/data_types.py` |
| `DataTypeUpdate` | schema | Update request: all fields optional | `backend/app/schemas/data_types.py` |
| `DataTypeResponse` | schema | Response: all fields including timestamps | `backend/app/schemas/data_types.py` |
| `DataTypeListResponse` | schema | Paginated list with optional usage counts | `backend/app/schemas/data_types.py` |
| `DataTypeUsageInfo` | schema | Usage info: referencing_agent_types[] | `backend/app/schemas/data_types.py` |
| `AgentOutputCreate` | schema | Create request (internal): data_type_id, agent_type_id, execution_session_id, field_values, validation_status, raw_output | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputResponse` | schema | Response with resolved names: data_type_name, agent_type_name | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputQueryParams` | schema | Filter/pagination params for output queries | `backend/app/schemas/agent_outputs.py` |
| `AgentOutputListResponse` | schema | Paginated list wrapper | `backend/app/schemas/agent_outputs.py` |
| `ValidationResult` | schema | `{valid: bool, errors: list[FieldError]}` | `backend/app/schemas/agent_outputs.py` |

### Backend Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DataTypeService` | class | CRUD for AgentDataType: create, get, get_by_slug, update, delete (guarded), list (paginated, searchable), count_usage | `backend/app/services/data_types/service.py` |
| `DataTypeNotFoundError` | exception | 404 — data type not found | `backend/app/services/data_types/service.py` |
| `DataTypeConflictError` | exception | 409 — deletion blocked by referencing agent types | `backend/app/services/data_types/service.py` |
| `DataTypeDuplicateError` | exception | 409 — duplicate name or slug | `backend/app/services/data_types/service.py` |
| `OutputService` | class | Persist and query typed outputs: save_typed, list_outputs (filtered), get_output, export_csv | `backend/app/services/outputs/service.py` |
| `SchemaValidationService` | class | Validate payload against data type schema: required fields, type checking, enum membership | `backend/app/services/validation/schema_validation_service.py` |

### Backend Public API Routers

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DataTypeRouter` | APIRouter | `GET/POST /data-types`, `GET/PUT/DELETE /data-types/{id}`; `?usage=true` returns referencing agent types; permission: `RT_AGENT_DATA_TYPES` | `backend/app/api/v1/data_types.py` |
| `OutputRouter` (public) | APIRouter | `GET /agent-outputs` (filtered, paginated), `GET /agent-outputs/export` (CSV); permission: `RT_AGENT_OUTPUTS`, `"read"` | `backend/app/api/v1/agent_outputs.py` |

### Backend Internal Endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `InternalOutputsRouter` | APIRouter | mTLS-protected: validate, create, query typed outputs | `backend/app/api/v1/internal/outputs.py` |
| `validate_output` | endpoint | `POST /internal/validate-output` — validate payload against data type schema | `backend/app/api/v1/internal/outputs.py` |
| `create_internal_output` | endpoint | `POST /internal/agent-outputs` — persist typed output (201) | `backend/app/api/v1/internal/outputs.py` |
| `query_internal_outputs` | endpoint | `GET /internal/agent-outputs` — query typed outputs with filters and pagination | `backend/app/api/v1/internal/outputs.py` |
| `RT_AGENT_DATA_TYPES` | constant | Resource type identifier for data type permission checks | `backend/app/core/resource_types.py` |

### Frontend Pages & Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DataTypesPage` | page | Admin data types list with CRUD, pagination, usage display, delete guard | `frontend/src/pages/data-types/DataTypesPage.tsx` |
| `DataTypeFormDialog` | component | Create/edit dialog with dynamic field editor (5 field types); Dialog Error Handling Standard | `frontend/src/pages/data-types/DataTypeFormDialog.tsx` |
| `AgentOutputsPage` | page | Admin outputs page with filter bar, dynamic schema-based columns, CSV export, detail drawer | `frontend/src/pages/agent-outputs/AgentOutputsPage.tsx` |
| `AgentOutputDetailDrawer` | component | Output detail drawer with TypedOutputRenderer, validation error banner, raw fallback | `frontend/src/pages/agent-outputs/AgentOutputDetailDrawer.tsx` |
| `TypedOutputRenderer` | component | Schema-based field-by-field typed output renderer | `frontend/src/components/executions/TypedOutputRenderer.tsx` |
| `TypedFieldRenderers` | module | Type-aware field renderers: BooleanFieldValue, DateFieldValue, EnumFieldValue, NumberFieldValue, StringFieldValue | `frontend/src/components/executions/TypedFieldRenderers.tsx` |
| `OutputTypeResultTab` | component | **MODIFIED**: Detects typed outputs, fetches schema, renders via TypedOutputRenderer | `frontend/src/components/executions/OutputTypeResultTab.tsx` |

### Frontend Hooks

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useDataTypes` | hook | Paginated data type list; query key: `['data-types', params]` | `frontend/src/hooks/useDataTypes.ts` |
| `useDataTypesWithUsage` | hook | Data types with usage counts; query key: `['data-types', 'usage']` | `frontend/src/hooks/useDataTypes.ts` |
| `useDataType` | hook | Single data type by ID | `frontend/src/hooks/useDataTypes.ts` |
| `useCreateDataType` | hook | Create mutation; invalidates `['data-types']` | `frontend/src/hooks/useDataTypes.ts` |
| `useUpdateDataType` | hook | Update mutation; invalidates `['data-types']` | `frontend/src/hooks/useDataTypes.ts` |
| `useDeleteDataType` | hook | Delete mutation; invalidates data types cache | `frontend/src/hooks/useDataTypes.ts` |
| `fetchDataTypeUsage` | function | Fetch referencing agent types for delete guard | `frontend/src/hooks/useDataTypes.ts` |
| `useAgentOutputs` | hook | Paginated outputs query; query key: `['agent-outputs', params]` | `frontend/src/hooks/useAgentOutputs.ts` |
| `useExportAgentOutputs` | hook | CSV export mutation as blob download | `frontend/src/hooks/useAgentOutputs.ts` |

### Frontend Types

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `DataTypeFieldType` | type | `'string' \| 'number' \| 'boolean' \| 'date' \| 'enum'` | `frontend/src/types/index.ts` |
| `AgentDataTypeField` | interface | `{name, type, enum_values?, required?, default}` | `frontend/src/types/index.ts` |
| `AgentDataType` | interface | `{id, name, slug, description, fields[], created_at, updated_at}` | `frontend/src/types/index.ts` |
| `ReferencingAgentType` | interface | `{id, name}` | `frontend/src/types/index.ts` |
| `DataTypeCreate` | interface | Create payload: name, slug, description?, fields[] | `frontend/src/types/index.ts` |
| `DataTypeUpdate` | interface | Update payload: all fields optional | `frontend/src/types/index.ts` |
| `DataTypeListResponse` | interface | Paginated list: items[], total, page, page_size, usage? | `frontend/src/types/index.ts` |
| `AgentOutputResponse` | interface | Output record with resolved data_type_name and agent_type_name | `frontend/src/types/index.ts` |
| `AgentOutputQueryParams` | interface | Filter params: data_type_id, agent_type_id, date_from, date_to, page, page_size | `frontend/src/types/index.ts` |
| `AgentOutputListResponse` | interface | `{items[], total, page, page_size}` | `frontend/src/types/index.ts` |
| `AgentOutputExportParams` | interface | Export filter params (no pagination) | `frontend/src/types/index.ts` |

### Test Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_data_types_api.py` | test | Backend: DataTypeService/Controller CRUD, duplicate detection, pagination, search | `backend/tests/test_data_types_api.py` |
| `test_output_validation.py` | test | Backend: SchemaValidationService — required, type, enum checks | `backend/tests/test_output_validation.py` |
| `test_agent_outputs_api.py` | test | Backend: OutputService and endpoints — persistence, query, export | `backend/tests/test_agent_outputs_api.py` |
| `test_query_result_tool.py` | test | Backend: query_result tool flow — name resolution, filters, 404 | `backend/tests/test_query_result_tool.py` |
| `DataTypesPage.test.tsx` | test | Frontend: renders title, list, CRUD buttons, empty/loading states | `frontend/src/__tests__/DataTypesPage.test.tsx` |
| `AgentOutputsPage.test.tsx` | test | Frontend: renders filters, dynamic columns, export, status chips | `frontend/src/__tests__/AgentOutputsPage.test.tsx` |
| `AgentOutputDetailDrawer.test.tsx` | test | Frontend: renders typed fields, validation error, raw fallback | `frontend/src/__tests__/AgentOutputDetailDrawer.test.tsx` |
| `DataTypeFormDialog.test.tsx` | test | Frontend: create/edit modes, field add/remove, validation | `frontend/src/__tests__/DataTypeFormDialog.test.tsx` |
| `OutputTypeResultTab.test.tsx` | test | Frontend: typed output rendering, validation error display | `frontend/src/__tests__/OutputTypeResultTab.test.tsx` |
| `TypedOutputRenderer.test.tsx` | test | Frontend: all field type renderers, empty/null states | `frontend/src/__tests__/TypedOutputRenderer.test.tsx` |

### Alembic Migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `a69529d1090f` | migration | Creates `agent_data_types` table | `backend/alembic/versions/a69529d1090f_add_agent_data_types_table.py` |
| `3131c85e74e0` | migration | Creates `agent_outputs` table + `output_id` FK on `agent_jobs` | `backend/alembic/versions/3131c85e74e0_add_agent_outputs_table_and_output_id_.py` |
| `76078a3ecff2` | migration | Adds `output_data_type_id` FK to `agent_types` | `backend/alembic/versions/76078a3ecff2_add_output_data_type_id_to_agent_types.py` |
| `a1d4e8f2b3c5` | migration | Data migration: backfills typed agent types | `backend/alembic/versions/a1d4e8f2b3c5_migrate_existing_typed_agent_types.py` |

---

## Data Access Patterns

### Data Type Registry

Data types are created, read, updated, and deleted exclusively through CC API endpoints. The `agent_data_types` table is read by:
- **SchemaValidationService** — fetches schema for output validation during execution completion
- **CC API layer** — resolves data type ID to name for response enrichment
- **Agent Runtime indirectly** — AR never queries the table directly; it calls CC internal endpoints

### Output Persistence

Two-phase write via CC internal API during agent execution completion:
1. **Phase 1 — Validation:** AR calls `POST /internal/validate-output` with output payload and `data_type_id`. CC fetches schema, validates fields, returns `{valid, errors[]}`.
2. **Phase 2 — Persistence:** AR calls `POST /internal/agent-outputs` with full output data. CC creates `AgentOutput` row and updates `AgentJob.output_id`. If validation failed, the record is still persisted with `validation_status = validation_error` and `raw_output` as fallback.

### Backward Compatibility

All existing code paths preserved:
- `AgentType.output_data_type_id` is nullable — agents without it use the existing untyped flow
- `OutputTypeResultTab` checks for `data_type_id` in output data; absent → renders via JSON tree view
- `save_result` remains a general-purpose system tool for mid-execution checkpoints, independent of typed output
