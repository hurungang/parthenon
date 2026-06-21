# Test Plan: Enhance Agent Output System

## Test Strategy

| Layer | Scope | Approach | Responsibility |
|-------|-------|----------|----------------|
| **Unit (Backend)** | `DataTypeService`, `OutputService`, `SchemaValidationService` | Pure service-logic tests with mocked DB session or in-memory SQLite. Validate business rules: duplicate names, field validation, delete guard, enum membership, required field enforcement. | Developer (Phase 1.7, 4.12) |
| **Integration (Backend)** | API endpoints (public + internal + system tools) | Real PostgreSQL via testcontainers or ephemeral DB. Verify HTTP status codes, response bodies, error shapes, FK constraint enforcement, migration effects. **All internal endpoints tested with mTLS cert fixture.** | Developer (Phase 1.7, 4.12, 7.6) |
| **Database (Migration)** | Alembic migrations, schema constraints | Apply all 5 migrations to fresh DB. Query `information_schema` to verify columns, FKs, indexes, enum types exist. Insert data violating FK constraints to confirm referential integrity. | Tester (pre-test checklist) |
| **Unit (Frontend)** | `TypedOutputRenderer`, `OutputTypeResultTab`, `DataTypeFormDialog`, `DataTypeSelector` | Vitest + React Testing Library. Test rendering of all 5 field types, validation error states, form validation, dialog open/close, i18n string usage. | Developer (Phase 5.8) |
| **E2E (Mocked)** | Full CRUD flows on DataTypes and AgentOutputs pages | Playwright with `page.route()` interceptors. Test UI navigation, dialog flows, table refresh after CRUD, filter behavior, CSV export button. | Tester |
| **E2E (Real Backend)** | Data type CRUD + typed agent execution flow | Playwright against real running backend (no mocks). **One suite variant** hitting real API to catch migration/backend issues. | Tester (critical for `has_db_changes`) |

---

## Pre-Test Checklist (Database Changes)

Before running any test suite:

- [ ] Verify all migrations applied: `cd backend && python -m alembic current` shows latest revision matching `backend/alembic/versions/` most recent file
- [ ] If not applied: `python -m alembic upgrade head`
- [ ] Check `agent_data_types` table exists in the database
- [ ] Check `agent_outputs` table exists with FKs to `agent_data_types`, `agent_types`, `agent_jobs`
- [ ] Check `agent_types` has `output_data_type_id` nullable FK column
- [ ] Check `agent_jobs` has `output_id` nullable FK column
- [ ] Check `AgentOutputValidationStatus` enum type exists with values `valid`, `validation_error`
- [ ] Verify backend test fixture applies migrations (`alembic upgrade head` in setup)

---

## Coverage Areas

### 1. Agent Data Type Registry (Backend CRUD API)

**Why critical:** Foundation of the entire feature — all downstream features (output assignment, validation, querying) depend on correct data type persistence and retrieval.

**What must be tested:**
- Create data type with valid name, slug, description, mixed field types → 201
- Create duplicate name → 422 with clear error
- Create empty fields list → 422 (`at_least_one_field` validation)
- Create with invalid field type string → 422
- Create with duplicate field names → 422
- Get by ID returns full schema with all fields → 200
- Get non-existent ID → 404
- Update name, description, fields → 200
- Update without changes (idempotent) → 200
- Delete unreferenced data type → 204
- Delete data type referenced by agent types → 409 with `referencing_agent_types` list
- After deletion, same name is reusable → create with deleted name succeeds
- Paginated list with `?page=1&page_size=10` works
- Search filtering via `?search=` narrows results
- `?usage=true` returns reference counts alongside data types
- Name maximum length enforced
- Slug auto-generation uniqueness enforced

### 2. Agent Type Output Assignment (Backend + Frontend)

**Why critical:** Links the data type registry to the agent execution pipeline. Errors here mean agents cannot produce typed outputs.

**What must be tested:**
- Create agent type with `output_data_type_id` set (non-conversational) → 201, FK persisted
- Update agent type from untyped to `output_data_type_id` set → 200
- Create agent type with `output_type=typed` but no `output_data_type_id` → 422
- Update agent type to clear `output_data_type_id` → allowed (back to untyped)
- Conversational agent type ignores `output_data_type_id` (field not in form)
- `output_data_type_name` resolved in GET response
- Frontend `DataTypeSelector` renders only non-conversational forms
- Frontend output type badge shows data type name when assigned

### 3. Schema Validation Service

**Why critical:** Core business logic — incorrect validation means bad data gets stored as valid, or valid data gets rejected.

**What must be tested:**
- String field: valid string accepted, number/boolean rejected
- Number field: valid number accepted (`42`, `3.14`), string `"abc"` rejected
- Boolean field: `true`/`false` accepted, string `"yes"` rejected
- Date field: ISO 8601 date accepted (`2026-06-20`), free text rejected
- Enum field: value in `enum_values` accepted, value outside rejected
- Required field: missing → field-level error reported
- Optional field (required=false): missing → allowed
- Default value: when field absent from payload, default applied
- Mixed fields: all fields validated simultaneously, multiple errors collected
- Empty payload: all required fields flagged
- Extra fields in payload: ignored (not validated)
- Null values for non-nullable fields: rejected

### 4. Typed Output Persistence (Internal Endpoints + save_result Enhancement)

**Why critical:** The two-phase write (validate then persist) must work correctly for both valid and invalid outputs. Execution records must never be lost.

**What must be tested:**
- `POST /internal/validate-output`: valid payload → `{valid: true, errors: []}`
- `POST /internal/validate-output`: invalid payload → `{valid: false, errors: [field-level errors]}`
- `POST /internal/validate-output`: unknown `data_type_id` → 404
- `POST /internal/validate-output`: missing `data_type_id` → 422
- `POST /internal/agent-outputs`: creates `AgentOutput` row with correct FK values
- `POST /internal/agent-outputs`: validated output stored with `validation_status=valid`
- `POST /internal/agent-outputs`: failed validation still persisted with `validation_status=validation_error`, `field_values` is null, `raw_output` stores fallback
- `save_result` enhanced path: typed agent type → calls validation + `OutputService.save_typed`
- `save_result` backward compat: untyped agent type → uses existing `ResultRecord` path unchanged
- `AgentJob.output_id` correctly linked after typed save

### 5. Execution Log Typed Rendering (Frontend)

**Why critical:** Operators must see structured, readable output in the execution log. This is the primary consumption UI for typed results.

**What must be tested:**
- `TypedOutputRenderer` renders all 5 field types correctly: string as text, number as formatted number, boolean as toggle/Switch, date as locale-formatted date, enum as chip
- Field labels shown next to values
- Fields ordered according to schema field order
- Null/undefined values show placeholder (e.g., "—" or "No value")
- Long strings do not break layout (truncation/wrapping)
- `OutputTypeResultTab` detects typed output (`data_type_id` present), fetches schema, renders via `TypedOutputRenderer`
- `OutputTypeResultTab` badge shows data type name (`Result [IncidentReport]`)
- `OutputTypeResultTab` validation error state: error `Alert` displayed prominently, raw output shown as fallback below
- `OutputTypeResultTab` unchanged for untyped outputs (existing JSON tree view preserved)

### 6. Agent Outputs Admin Page (Frontend + API)

**Why critical:** Primary query interface for past agent results. Operators, auditors, and analysis workflows depend on it.

**What must be tested:**
- Page renders with filter bar: data type selector, date range picker, agent type selector
- Data type filter: selecting a type dynamically generates table columns from its field schema
- Changing data type re-renders table columns
- Date range filter: results filtered to range, datetime boundaries inclusive
- Agent type filter: results filtered by agent type
- Multiple filters combine with AND logic
- Pagination: pages displayed, page size respected, navigating pages works
- Row click opens detail drawer with full field-by-field rendering
- Detail drawer shows validation errors when `validation_status=validation_error`
- Detail drawer includes session navigation link
- CSV export: button triggers download with current filters
- CSV content: column headers match field names, rows contain correct data
- CSV export with no data type filter: fallback columns (timestamp, agent type, data type, status)
- Loading state shown during fetch
- Error state shown on network failure with retry button
- Empty state shown when no results match filters

### 7. `query_result` System Tool

**Why critical:** Enables agent-to-result analysis workflows. Must be secure, accurate, and follow the explicit-trigger pattern.

**What must be tested:**
- `query_result` recognized as system tool: `is_system_tool("query_result")` → true
- Tool schema registered in `SystemToolRegistry` with correct input params
- CH routes `system____query_result` to CC internal endpoint
- CC endpoint resolves `data_type_name` to `AgentDataType.id` (by slug first, then name)
- Returns matching outputs for valid `data_type_name`
- `date_from` / `date_to` filters applied correctly
- `field_filters` — JSONB containment filter works (e.g., `{"severity": "high"}`)
- Unknown `data_type_name` returns descriptive error (not 500)
- No results found → returns empty list (not error)
- Authorization: tool call requires valid service certificate
- Follows explicit-trigger pattern — must be referenced in agent instructions to be used

### 8. Migration & Backward Compatibility

**Why critical:** Existing untyped agent types and execution workflows must continue functioning unchanged.

**What must be tested:**
- Data migration for existing `typed` agent types: `AgentDataType` entries created from inline `output_schema` JSON
- Existing untyped agent types (`output_type: auto`, `output_type: markdown`) continue to work with unmodified `save_result` path
- Conversational agent types (`input_type: conversation`) do not show output data type field in form
- Conversational agent execution does NOT trigger schema validation
- Pre-existing untyped agent execution logs render as before (JSON tree view)
- All existing backend and frontend tests pass with zero regressions

---

## Critical Scenarios

### SC-1: Create and manage a Data Type with fields

```
GIVEN a platform administrator with appropriate permissions
WHEN they create a new data type named "IncidentReport" with fields:
  - "severity" (enum: critical, high, medium, low)
  - "description" (string, required)
  - "resolved" (boolean)
  - "occurred_at" (date)
THEN the data type is created with status 201
AND it appears in the data types list immediately
AND all 4 fields are stored with correct types

WHEN they edit the data type to add a "priority" (number) field
THEN the data type is updated with status 200
AND the fields list now shows 5 fields including "priority"
AND the table refreshes without manual page reload

WHEN they attempt to create another data type with name "IncidentReport"
THEN the request is rejected with status 422
AND the error message clearly indicates the name is taken
```

### SC-2: Delete guard prevents deletion of referenced Data Type

```
GIVEN an "IncidentReport" data type that is assigned to an Agent Type "TicketAnalyzer"
WHEN the platform administrator attempts to delete "IncidentReport"
THEN the deletion is rejected with status 409
AND the response includes a list referencing "TicketAnalyzer" by name
AND the frontend shows a non-dismissable alert listing the referencing agent types
AND the delete button is disabled

WHEN the administrator removes the data type assignment from "TicketAnalyzer" first
AND then retries the deletion
THEN the data type is deleted with status 204
AND the data type name "IncidentReport" can be reused for a new type
```

### SC-3: Assign Data Type to Agent Type and execute

```
GIVEN an "IncidentReport" data type with fields (severity: enum, description: string required)
AND a non-conversational Agent Type "TicketAnalyzer" with output_data_type_id pointing to "IncidentReport"
WHEN the agent executes and produces a valid output:
  {"severity": "high", "description": "Database connection timeout"}
THEN the agent execution completes successfully
AND the output is validated against the schema
AND the result is persisted to the agent_outputs table with validation_status = "valid"
AND the execution log Result tab shows the output as a structured field-by-field view
AND the Result tab badge reads "Result [IncidentReport]"
```

### SC-4: Invalid typed agent execution

```
GIVEN an "IncidentReport" data type with fields (severity: enum[critical,high], description: string required)
AND Agent Type "TicketAnalyzer" with this data type assigned
WHEN the agent executes and produces an invalid output:
  {"severity": "unknown", "description": "Something happened"}
THEN the agent execution completes (does NOT crash)
AND the validation result is validation_error
AND the result is persisted with field_values=null and raw_output as fallback
AND the execution log Result tab shows a prominent validation error alert
AND the raw output is displayed below the alert as fallback
```

### SC-5: Query outputs by data type and date range

```
GIVEN multiple agent outputs exist across 3 data types ("IncidentReport", "PerformanceReport", "AuditLog")
AND outputs span dates from June 1 to June 20
WHEN the operator selects "IncidentReport" in the data type filter
AND sets date range from June 10 to June 15
THEN the Agent Outputs table shows only results matching "IncidentReport" within that date range
AND the table columns dynamically update to include field columns from "IncidentReport" schema
AND pagination shows correct page count for filtered results
```

### SC-6: `query_result` tool call by analysis agent

```
GIVEN an analysis agent type "IncidentAnalyzer" with instructions referencing the query_result tool
AND there are 5 IncidentReport outputs stored in the system with severity = "high"
WHEN the "IncidentAnalyzer" agent calls system____query_result with:
  {"data_type_name": "IncidentReport", "filters": {"field_filters": {"severity": "high"}}}
THEN the tool returns a list of 5 matching typed results
AND each result includes the field values conforming to the IncidentReport schema
AND the tool response is structured for the agent to reason across

WHEN the same agent calls query_result with data_type_name = "NonExistentType"
THEN the tool returns a descriptive error: "Unknown data type: NonExistentType"
AND no exception or crash occurs
```

### SC-7: CSV export of filtered outputs

```
GIVEN 100 agent outputs filtered to "IncidentReport" type in the last 7 days
WHEN the operator clicks the "Export CSV" button
THEN a CSV file is downloaded with the filename agent-outputs-{current-date}.csv
AND the first row contains field names as column headers
AND subsequent rows contain the field values matching current filters
AND all 100 matching rows are included (no pagination limit)
```

---

## Edge Cases & Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Referential integrity on data type deletion** | Orphan agent types referencing deleted data type → runtime failures | Delete guard (409) blocks deletion when `agent_types.output_data_type_id` references the type. `ON DELETE SET NULL` on FK ensures agent types survive without schema reference. |
| **Schema change race: editing data type while execution in progress** | Agent validates against old schema but output was validated with new schema → inconsistency | Schema is resolved from DB at validation time (read-committed isolation). Agent output stores `data_type_id` but the schema is resolved at read time. Acceptable: the output self-describes which schema version it was validated against (by FK). |
| **Concurrent executions writing to same agent type** | Duplicate or interleaved output records | Each execution has a unique `execution_session_id` → `AgentOutput` rows are independent. No concurrency issue beyond normal RDBMS row-level locking. |
| **Missing query_result authorization** | Agent queries outputs it should not see | All internal endpoints require mTLS service certificate. Agents can only call `query_result` if their instructions explicitly reference the tool (explicit-trigger pattern). |
| **Large payloads / many fields** | Cumbersome rendering, slow CSV export, DB storage bloat | Fields stored as JSONB (no schema per field). Frontend rendering handles long fields with truncation. CSV export uses streaming response. No hard limit on fields but UI pagination for table. |
| **CSV export with large datasets (10k+ rows)** | Memory exhaustion on server, browser download timeout | Export uses `StreamingResponse` in FastAPI — no full result set loaded into memory. Consider production limit at 100k rows if performance becomes an issue. |
| **Null vs undefined field values** | Frontend renderers crash or show confusing states | All field renderers handle null/undefined gracefully with placeholder display. Schema allows optional fields. |
| **Data type name change after outputs exist** | `query_result` resolves by slug (immutable), not name | Slug is created once and never changed. Name can be updated for display. `query_result` resolves by slug first, then by name — existing outputs remain linked by `data_type_id` FK. |
| **Migration rollback drops tables with FK references** | Cannot downgrade if outputs reference deleted data types | Migrations must handle downgrade with FK checking or data preservation. Review downgrade scripts carefully. |
| **Conversational agent types with output_data_type_id set via API** | Bypass frontend guard — conversational agents get typed validation | Backend must also enforce the rule: `input_type=conversation` and `output_data_type_id` non-null → reject with 422. Not just a frontend guard. |
| **Backend overwrites output_id on AgentJob during retry execution** | Output_id links to wrong output record | Each execution creates a new `AgentOutput`. `AgentJob.output_id` is updated only on first completion. If agent re-executes, new output is created but `AgentJob.output_id` remains pointing to original. |

---

## Acceptance Criteria Checklist

Maps to PRD acceptance criteria as testable assertions.

### Agent Data Type Registry (CRUD)

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-01 | Create data type with unique name, description, typed fields (string, number, boolean, date, enum) | API+E2E | `POST /api/v1/data-types` returns 201; created type appears in list |
| AC-02 | Created data type appears in list immediately with all fields displayed | E2E | Table row shows name, field count, created date; fields match input |
| AC-03 | Edit existing data type fields and metadata | API+E2E | `PUT /api/v1/data-types/{id}` returns 200; fields updated in response |
| AC-04 | After editing, list refreshes without page reload | E2E | Parent data types table shows updated values immediately after dialog closes |
| AC-05 | Delete with confirmation, blocked if referenced (clear message) | API+E2E | `DELETE` returns 409 with `referencing_agent_types`; UI shows alert listing agent types |
| AC-06 | Deleted type removed from list; name reusable | API+E2E | `DELETE` returns 204; type gone from list; create with same name succeeds |
| AC-07 | Duplicate name rejected with clear error | API | `POST` with same name returns 422; error message indicates duplicate |
| AC-08 | At least one field enforced, empty definition rejected | API | `POST` with `fields: []` returns 422; `at_least_one_field` validation error |

### Agent Type Output Assignment

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-09 | Agent Type form includes "Output Data Type" selector | Component | `AgentTypeForm` renders `DataTypeSelector` for non-conversational types |
| AC-10 | Only non-conversational types show the field | Component | `input_type=conversation` → field hidden; UI indicates why |
| AC-11 | Assigned data type sets `output_type=typed` and links schema | API | `POST /api/v1/agents` with `output_data_type_id` persists FK; response includes `output_data_type_name` |
| AC-12 | Output type badge shows assigned data type name | Component | Agent Management table shows data type name chip, not generic "Typed" |

### Typed Agent Execution

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-13 | Output validated against schema on execution completion | Integration | `POST /internal/validate-output` called; result with valid payload returns valid=true |
| AC-14 | Mismatched output flagged with validation error, execution completes | Integration | Invalid payload → agent execution still completes; result has `validation_status=validation_error` |
| AC-15 | Validated result saved with data type schema reference | Integration | `AgentOutput` row created with `data_type_id` FK, `validation_status=valid`, correct `field_values` |
| AC-16 | `save_result` enhanced to persist typed outputs | Integration | Typed agent calling `save_result` → calls validation + `OutputService.save_typed` |

### Execution Log Typed Output Display

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-17 | Result tab renders typed output as structured field-by-field view | Component | `TypedOutputRenderer` shows all fields with labels and type-aware formatting |
| AC-18 | Each field formatted by type: string→text, bool→toggle, date→formatted, enum→chip | Component | All 5 field type renderers produce correct output for valid values |
| AC-19 | Tab label includes data type name badge | Component | Badge `[IncidentReport]` appended to "Result" tab label |
| AC-20 | Validation error displayed prominently with raw output fallback | Component | `validation_error` → Alert shown; raw JSON displayed below |

### Agent Outputs Admin Page

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-21 | Agent Outputs page in admin nav with filter bar | E2E+Component | Nav link exists; page renders data type, date range, agent type selectors |
| AC-22 | Dynamic columns based on selected data type fields | Component | Selecting data type adds field columns matching schema |
| AC-23 | Results refresh on filter change | Component | Changing filter triggers refetch; table updates with new data |
| AC-24 | Pagination for large result sets | API+Component | `page`/`page_size` params work; frontend shows page controls |
| AC-25 | CSV export for filtered results | Integration+E2E | Export endpoint returns CSV stream; button triggers download with correct filename |

### `query_result` System Tool

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-26 | Tool available to all agents by default | Unit | `is_system_tool("query_result")` → true; schema registered in `SystemToolRegistry` |
| AC-27 | Agents call with data type name + optional filters | Integration | Valid call returns matching typed outputs; date range + field_filters work |
| AC-28 | Returns matching results conforming to requested schema | Integration | Response includes `AgentOutputResponse` records with correct field values |
| AC-29 | Enables result-analysis agent workflows | Integration | Analysis agent can call `query_result` and receive structured results |

### Error Handling

| # | Criterion | Layer | Verification |
|---|-----------|-------|-------------|
| AC-30 | Validation errors shown inline in data type form | Component | Form dialog shows field-level error messages for invalid input |
| AC-31 | Data type lookup failure during execution → warning logged, execution completes | Integration | Unknown `data_type_id` → agent completes with warning, no crash |
| AC-32 | Network errors on Agent Outputs page → clear message with retry | Component | Network failure shows error state with retry button |
| AC-33 | Invalid data type name in `query_result` → descriptive error | Integration | Unknown name returns error message, not 500 |

---

## Test File References

### Backend Unit & Integration Tests

| Test File | Coverage | Phase |
|-----------|----------|-------|
| `backend/tests/api/v1/test_data_types.py` | Data type CRUD endpoints: create, read, update, delete, duplicate names, field validation, usage counts, pagination, search | Phase 1 |
| `backend/tests/api/v1/test_agent_outputs.py` | Public agent outputs query/export endpoints: filtering, pagination, CSV streaming, error handling | Phase 6 |
| `backend/tests/internal/test_validate_output.py` | Internal `POST /validate-output` endpoint: valid payloads, invalid payloads, field-level errors, unknown data type, missing required fields | Phase 4 |
| `backend/tests/internal/test_agent_outputs_internal.py` | Internal `POST/GET /internal/agent-outputs`: persistence, query, validation_status handling, FK constraints, backward compatibility | Phase 4 |
| `backend/tests/services/test_data_type_service.py` | `DataTypeService` unit: create, duplicate detection, delete guard, slug generation, reference checking, paginated list | Phase 1 |
| `backend/tests/services/test_output_service.py` | `OutputService` unit: save_typed, list_outputs with all filter combinations, CSV export generation, output_id linking | Phase 4 |
| `backend/tests/services/test_schema_validation_service.py` | `SchemaValidationService`: all 5 field types, required/optional, enum membership, default values, field-level error collection, mixed valid/invalid | Phase 4 |
| `backend/tests/agents/test_runtime_executor.py` | AR execution completion: typed output validation dispatch, untyped backward compat, conversational agent isolation, error handling | Phase 4 |
| `backend/tests/agents/test_query_result_tool.py` | `query_result` system tool: full flow from CC endpoint through CH routing, data type resolution, date/field filters, unknown type error, empty results | Phase 7 |

### Frontend Unit Tests

| Test File | Coverage | Phase |
|-----------|----------|-------|
| `frontend/src/__tests__/DataTypesPage.test.tsx` | `DataTypesPage` + `DataTypeFormDialog`: data type list rendering, create/edit dialog, field editor, delete guard UI, pagination, error states | Phase 2 |
| `frontend/src/__tests__/AgentOutputsPage.test.tsx` | `AgentOutputsPage` + `AgentOutputDetailDrawer`: filter bar, dynamic table columns, row detail, CSV export trigger, loading/empty/error states | Phase 6 |
| `frontend/src/__tests__/DataTypeSelector.test.tsx` | `DataTypeSelector` component: renders data type list, selection triggers onChange, "None" option, loading/error states | Phase 3 |
| `frontend/src/__tests__/ExecutionLogDialog.test.tsx` | `OutputTypeResultTab` + `TypedOutputRenderer`: typed output rendering (all 5 types), validation error display, raw fallback, data type badge, untyped backward compat | Phase 5 |

### E2E Tests

| Test File | Coverage | Notes |
|-----------|----------|-------|
| `e2e/tests/data-types-crud.spec.ts` | Full CRUD lifecycle: page renders, list data types with field counts/slugs, create dialog opens, delete guard for referenced types, empty state placeholder (9 tests) | Mocked API, `**/api/v1/...` glob route patterns |
| `e2e/tests/agent-outputs-query.spec.ts` | Agent Outputs page: filter bar, data type/agent type display, validation status badges, CSV export button, empty state, row detail drawer (9 tests) | Mocked API, `**/api/v1/...` glob route patterns |
| `e2e/tests/typed-execution-flow.spec.ts` | End-to-end: agent management shows data type badge/typed indicator, detail dialog shows data type name, execution logs show typed sessions, agent outputs page shows typed output (5 tests) | Mocked API, `**/api/v1/...` glob route patterns |
