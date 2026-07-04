# Agent Data Types & Typed Outputs Test Plan

## Scope

Covers the Agent Data Type registry (CRUD), Agent Outputs query/admin page, typed output persistence and validation, schema validation service, the `query_result` system tool, and the frontend rendering pipeline for typed agent outputs. Also covers database migration verification and backward compatibility for existing untyped agent workflows.

---

## Coverage Areas

### 1. Agent Data Type Registry (CRUD)

**What is tested:**
- Create data type with name, description, and mixed field types (string, number, boolean, date, enum)
- Duplicate name rejection with clear error message
- Empty fields list rejection (must have at least one field)
- Invalid field type string rejection
- Duplicate field names within a single type
- Get by ID returns full schema with all fields
- Get non-existent ID returns 404
- Update name, description, and fields
- Paginated list with search filtering
- Usage counts via `?usage=true` parameter
- Slug auto-generation and uniqueness

**Acceptance criteria:**
- `POST /api/v1/data-types` returns 201; created type appears in list
- Duplicate name returns 422 with descriptive error
- Empty fields list returns 422 with `at_least_one_field` validation error
- After deletion, same name is reusable

**Test files:**
- [backend/tests/test_data_types_api.py](../../../../backend/tests/test_data_types_api.py) — Backend API tests: CRUD operations, validation, pagination, search, usage counts
- [frontend/src/__tests__/DataTypesPage.test.tsx](../../../../frontend/src/__tests__/DataTypesPage.test.tsx) — Frontend: data type list rendering, create/edit dialog, field editor, delete guard UI, pagination, error states

---

### 2. Schema Validation Service

**What is tested:**
- String field: valid string accepted, non-string rejected
- Number field: valid number accepted, non-numeric rejected
- Boolean field: `true`/`false` accepted, non-boolean rejected
- Date field: ISO 8601 date accepted, free text rejected
- Enum field: value in `enum_values` accepted, value outside rejected
- Required field: missing triggers field-level error
- Optional field: missing is allowed
- Default values: applied when field absent from payload
- Mixed fields: all validated simultaneously, multiple errors collected
- Empty payload: all required fields flagged
- Extra fields in payload: ignored
- Null values for non-nullable fields: rejected

**Acceptance criteria:**
- Valid payload returns `{valid: true, errors: []}`
- Invalid payload returns `{valid: false, errors: [field-level errors]}`
- All 5 field type validators produce correct results

**Test files:**
- [backend/tests/test_output_validation.py](../../../../backend/tests/test_output_validation.py) — Backend: schema validation for all 5 field types, required/optional, enum membership, edge cases

---

### 3. Typed Output Persistence (Agent Outputs)

**What is tested:**
- `POST /internal/validate-output`: valid payload returns valid=true
- `POST /internal/validate-output`: invalid payload returns field-level errors
- `POST /internal/validate-output`: unknown data_type_id returns 404
- Creating `AgentOutput` row with correct FK values (data_type_id, agent_type_id, agent_job_id)
- Validated output stored with `validation_status=valid`
- Failed validation still persisted with `validation_status=validation_error`, field_values=null, raw_output fallback
- `save_result` enhanced path: typed agent type calls validation + `OutputService.save_typed`
- `save_result` backward compat: untyped agent type uses existing `ResultRecord` path
- `AgentJob.output_id` correctly linked after typed save
- Public query endpoint with filtering by data type, date range, agent type
- CSV export with streaming response and correct column headers

**Acceptance criteria:**
- Agent execution with valid typed output persists correctly with validation_status=valid
- Agent execution with invalid typed output still completes; result persisted with validation_status=validation_error
- Existing untyped agent types continue to use legacy save_result path unchanged
- CSV export button triggers download with correct filename and headers

**Test files:**
- [backend/tests/test_agent_outputs_api.py](../../../../backend/tests/test_agent_outputs_api.py) — Backend: agent output query, export, persistence, FK constraints
- [backend/tests/test_save_result_typed.py](../../../../backend/tests/test_save_result_typed.py) — Backend: typed save_result path, valid/invalid/fallback scenarios
- [frontend/src/__tests__/AgentOutputsPage.test.tsx](../../../../frontend/src/__tests__/AgentOutputsPage.test.tsx) — Frontend: filter bar, dynamic table columns, row detail, CSV export trigger, loading/empty/error states

---

### 4. `query_result` System Tool

**What is tested:**
- Tool registered as system tool (`is_system_tool("query_result")` returns true)
- Tool schema registered in `SystemToolRegistry` with correct input params
- Communication Hub routes `system____query_result` to Control Center internal endpoint
- Resolves data_type_name by slug first, then by name
- Returns matching outputs for valid data_type_name
- Date range filters (`date_from`/`date_to`) applied correctly
- JSONB containment field_filters work correctly
- Unknown data_type_name returns descriptive error (not 500)
- No results found returns empty list (not error)
- Follows explicit-trigger pattern

**Acceptance criteria:**
- Agents can call `query_result` with data type name and optional filters
- Response includes matching `AgentOutputResponse` records with correct field values
- Unknown data type name returns descriptive error message

**Test files:**
- [backend/tests/test_query_result_tool.py](../../../../backend/tests/test_query_result_tool.py) — Backend: query_result tool, slug/name resolution, date range, field filters, error handling

---

### 5. Execution Log Typed Rendering (Frontend)

**What is tested:**
- `TypedOutputRenderer` renders all 5 field types correctly: string as text, number as formatted number, boolean as toggle/switch, date as locale-formatted date, enum as chip
- Field labels shown next to values
- Fields ordered according to schema field order
- Null/undefined values show placeholder
- `OutputTypeResultTab` detects typed output (data_type_id present), fetches schema, renders via `TypedOutputRenderer`
- Result tab badge shows data type name (e.g., "Result [IncidentReport]")
- Validation error state: error alert displayed prominently, raw output shown below as fallback
- Backward compat: untyped outputs render as before (JSON tree view)

**Acceptance criteria:**
- Typed output renders as structured field-by-field view with type-aware formatting
- Tab label includes data type name badge
- Validation error prominently displayed with raw output fallback

**Test files:**
- [frontend/src/__tests__/OutputTypeResultTab.test.tsx](../../../../frontend/src/__tests__/OutputTypeResultTab.test.tsx) — Frontend: typed output detection, schema fetch, rendering via TypedOutputRenderer, validation error state, data type badge
- [frontend/src/__tests__/TypedOutputRenderer.test.tsx](../../../../frontend/src/__tests__/TypedOutputRenderer.test.tsx) — Frontend: all 5 field type renderers, null handling, field ordering

---

### 6. Migration & Backward Compatibility

**What is tested:**
- All database migrations applied correctly (tables, columns, FKs, indexes, enum types)
- Existing untyped agent types continue to work with unmodified `save_result` path
- Conversational agent types do not show output data type field in form
- Conversational agent execution does NOT trigger schema validation
- Pre-existing untyped agent execution logs render as before (JSON tree view)
- All existing backend and frontend tests pass with zero regressions

**Acceptance criteria:**
- All 1260+ existing tests pass (baseline migration guardrail)
- Alembic `upgrade head` and `downgrade -1` work correctly

---

## E2E Test Coverage

| Test File | Coverage |
|-----------|----------|
| [e2e/tests/data-types-crud.spec.ts](../../../../e2e/tests/data-types-crud.spec.ts) | Full data type CRUD lifecycle: page renders, list with field counts/slugs, create dialog, delete guard, empty state (9 tests, mocked API) |
| [e2e/tests/agent-outputs-query.spec.ts](../../../../e2e/tests/agent-outputs-query.spec.ts) | Agent Outputs page: filter bar, data type/agent type display, validation status badges, CSV export button, empty state, row detail drawer (9 tests, mocked API) |
| [e2e/tests/typed-execution-flow.spec.ts](../../../../e2e/tests/typed-execution-flow.spec.ts) | End-to-end typed execution: agent management shows data type badge, detail dialog shows data type name, execution logs show typed sessions, agent outputs page shows typed output (5 tests, mocked API) |

---

## Critical Edge Cases & Risks

| Risk | Mitigation |
|------|------------|
| Delete guard: data type referenced by agent types | 409 with `referencing_agent_types` list; `ON DELETE SET NULL` FK ensures agent types survive without schema reference |
| Schema change race during execution | Schema resolved at validation time (read-committed); output stores `data_type_id` FK |
| Concurrent executions writing same agent type | Each execution has unique `execution_session_id`; `AgentOutput` rows are independent |
| Large payloads / many fields | JSONB storage (no per-field columns); frontend truncates long fields; CSV uses streaming |
| Data type name change after outputs exist | `query_result` resolves by slug (immutable), not name; outputs linked by `data_type_id` FK |
| Conversational agent types with output_data_type_id | Backend enforces: `input_type=conversation` and `output_data_type_id` non-null → reject with 422 |
