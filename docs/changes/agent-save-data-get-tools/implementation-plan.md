## Implementation Plan: agent-save-data-get-tools

## Overview

This change replaces the legacy `save_result` system tool with `save_data` and adds two new query tools, `get_data` and `get_output`. A new `AgentData` model separates intermediate named saves from the existing single-per-session `AgentOutput` final artifact, and all persistence and querying flows through Control Center internal APIs as required by the service segregation constraint.

## Task Checklist

### Phase 1 — Database Layer
- [x] 1.1 — Create AgentData SQLAlchemy model
- [x] 1.2 — Register AgentData in models __init__.py
- [x] 1.3 — Generate Alembic migration for agent_data table
- [x] 1.4 — Apply migration and verify schema

### Phase 2 — Control Center Service Layer
- [x] 2.1 — Create AgentDataService with save and query methods
- [x] 2.2 — Add query_output_history method to OutputService

### Phase 3 — Control Center System-Tool Endpoints
- [x] 3.1 — Add save-data handler to CC system-tools router
- [x] 3.2 — Add get-data handler to CC system-tools router
- [x] 3.3 — Add get-output handler to CC system-tools router

### Phase 4 — Communication Hub Routing
- [x] 4.1 — Add save_data, get_data, get_output to CommHub endpoint_map

### Phase 5 — Agent Runtime Tool Layer
- [x] 5.1 — Add LangChainSaveDataTool class
- [x] 5.2 — Add LangChainGetDataTool class
- [x] 5.3 — Add LangChainGetOutputTool class
- [x] 5.4 — Retire LangChainSaveResultTool

### Phase 6 — Tool Registry and Name Catalog
- [x] 6.1 — Register save_data, get_data, get_output in SystemToolRegistry
- [x] 6.2 — Remove save_result from SystemToolRegistry
- [x] 6.3 — Update SYSTEM_TOOL_NAMES in services/system_tools.py

### Phase 7 — Tests
- [x] 7.1 — Unit tests for AgentDataService
- [x] 7.2 — Integration tests for new internal API endpoints
- [x] 7.3 — Unit tests for LangChain tool classes
- [x] 7.4 — Verify save_result is no longer exposed in agent tool context

## Phase 1 — Database Layer

### 1.1 — Create AgentData SQLAlchemy model

Create `backend/app/db/models/agent_data.py` with the `AgentData` model. The table must include: `id` (UUID PK), `agent_type_id` (FK to `agent_types`, nullable, SET NULL), `session_id` (FK to `agent_jobs`, nullable, SET NULL), `data_name` (String, required), `data_value` (JSON, required), `data_type` (String, default `"json"`), `is_active` (Boolean, default True), and `created_at` (DateTime, server default). Add an index on `(agent_type_id, data_name)` and on `(session_id, data_name)` to support the query patterns defined in the data model.

**Done when**: `agent_data.py` exists, all fields and FKs match the data model spec, and the module imports cleanly without errors.

### 1.2 — Register AgentData in models __init__.py

Add the `AgentData` import to `backend/app/db/models/__init__.py` so Alembic autogenerate detects the model and SQLAlchemy Base registers the table.

**Done when**: `from app.db.models.agent_data import AgentData` is present in the `__init__.py` and no import error occurs when loading the module.

### 1.3 — Generate Alembic migration for agent_data table

Run `python -m alembic revision --autogenerate -m "add_agent_data_table"` from the `backend/` directory. Review the generated migration file to confirm: the `agent_data` table is created, both FK constraints reference `agent_types.id` and `agent_jobs.id`, all indexes are present, and `downgrade()` drops the table cleanly.

**Done when**: A valid migration file exists in `backend/alembic/versions/` with a non-empty `upgrade()` that creates `agent_data`, and `downgrade()` drops it.

### 1.4 — Apply migration and verify schema

Run `python -m alembic upgrade head` and then query `information_schema.columns` to confirm the `agent_data` table exists with all expected columns and correct nullability. Run `python -m alembic current` to confirm the head revision is active.

**Done when**: `alembic current` shows the new migration revision, and a direct SQL query confirms the table and all columns exist in the database.

## Phase 2 — Control Center Service Layer

### 2.1 — Create AgentDataService with save and query methods

Create `backend/app/services/agent_data/service.py` with an `AgentDataService` class. The service must expose at minimum: `save(db, agent_type_id, session_id, data_name, data_value, data_type)` returning the created `AgentData` record, and `query_by_filters(db, data_name, agent_type_id, session_id, limit, offset)` returning a filtered list of records. All parameters except `data_name` are optional for the query method, and at least one filter must be provided to prevent unbounded queries. Create the `__init__.py` for the new package.

**Done when**: `AgentDataService` can be imported, `save()` persists a record and returns it, and `query_by_filters()` returns correctly filtered results when tested against the database.

### 2.2 — Add query_output_history method to OutputService

Extend `backend/app/services/outputs/service.py` with a `query_output_history(db, agent_type_id, session_id, date_from, date_to, limit, offset)` method. All parameters are optional. The method queries `AgentOutput` rows using the provided filters, ordered by `created_at` descending. This separates the agent-facing query path from the existing operator-facing `list_outputs` method.

**Done when**: `query_output_history` exists on `OutputService`, accepts all specified optional parameters, applies them as SQL filters, and returns a list of `AgentOutput` records.

## Phase 3 — Control Center System-Tool Endpoints

### 3.1 — Add save-data handler to CC system-tools router

Add a `save_data` endpoint handler to the existing system-tools router in `backend/app/api/v1/internal/system_tools.py` (or the appropriate router file following the `save-result` handler pattern). The handler accepts `agent_type_id`, `session_id`, `data_name`, `data_value`, and `data_type` in the request body and persists a record via `AgentDataService.save()`. Requires service certificate authentication.

**Done when**: `POST /api/v1/internal/system-tools/save-data` exists on the CC app, requires mTLS, and returns the saved record with `id` and `created_at`.

### 3.2 — Add get-data handler to CC system-tools router

Add a `get_data` endpoint handler to the same router. The handler accepts filter fields (`data_name`, `agent_type_id`, `session_id`, `limit`, `offset`) in the request body and returns records via `AgentDataService.query_by_filters()`. At least one filter must be present; return a 400 if all filters are absent. Requires service certificate.

**Done when**: `POST /api/v1/internal/system-tools/get-data` exists, enforces the at-least-one-filter rule, and returns correctly filtered `AgentData` records.

### 3.3 — Add get-output handler to CC system-tools router

Add a `get_output` endpoint handler. Accepts `agent_type_id`, `session_id`, `date_from`, `date_to`, `limit`, `offset` in the request body and returns records via `OutputService.query_output_history()`. All filters optional. Requires service certificate.

**Done when**: `POST /api/v1/internal/system-tools/get-output` exists, delegates to `OutputService.query_output_history()`, and returns serialized `AgentOutput` records ordered by `created_at` descending.

## Phase 4 — Communication Hub Routing

### 4.1 — Add save_data, get_data, get_output to CommHub endpoint_map

In `backend/app/communication_hub/api/internal/tool_routing.py`, add three new entries to the `endpoint_map` dict inside `_route_to_system_tool()`: `"save_data"`, `"get_data"`, and `"get_output"`, each pointing to the corresponding `POST /api/v1/internal/system-tools/<tool>` URL on Control Center. No other CommHub changes are needed; existing permission-check and certificate-forwarding infrastructure handles these tool calls automatically.

**Done when**: Calling `CommHubToolClient.call_tool("save_data", ...)` from a test reaches the CC `save-data` handler without an "Unknown system tool" error, and the same holds for `get_data` and `get_output`.

## Phase 5 — Agent Runtime Tool Layer

### 5.1 — Add LangChainSaveDataTool class

Add `LangChainSaveDataTool` to `backend/app/services/agents/langchain_system_tools.py`. The tool name is `save_data`. It accepts `data_name` (string) and `data_value` (object) args, and optional `data_type` (string, default `"json"`). It holds a `comm_hub_client` reference (same pattern as `LangChainSendNotificationTool`). The `_arun` implementation calls `comm_hub_client.call_tool("save_data", ...)` and returns a JSON confirmation string.

**Done when**: `LangChainSaveDataTool` is importable, has the correct `name`, `description`, and `args_schema`, and `_arun` calls `comm_hub_client.call_tool` with the right tool name and args.

### 5.2 — Add LangChainGetDataTool class

Add `LangChainGetDataTool` to `langchain_system_tools.py`. Tool name is `get_data`. Args: `data_name` (optional string), `agent_type_id` (optional string), `session_id` (optional string). Holds a `comm_hub_client` reference. `_arun` calls `comm_hub_client.call_tool("get_data", ...)` and returns the serialized result.

**Done when**: `LangChainGetDataTool` is importable, correct arg schema, `_arun` calls `comm_hub_client.call_tool("get_data", ...)`.

### 5.3 — Add LangChainGetOutputTool class

Add `LangChainGetOutputTool` to `langchain_system_tools.py`. Tool name is `get_output`. Args: `agent_type_id` (optional string), `session_id` (optional string), `date_from` (optional ISO date string), `date_to` (optional ISO date string). Holds a `comm_hub_client` reference. `_arun` calls `comm_hub_client.call_tool("get_output", ...)` and returns the serialized result.

**Done when**: `LangChainGetOutputTool` is importable, correct arg schema, `_arun` calls `comm_hub_client.call_tool("get_output", ...)`.

### 5.4 — Retire LangChainSaveResultTool

Mark `LangChainSaveResultTool` as deprecated by adding a deprecation notice to its docstring. Remove it from the tool-construction code in `runtime_executor.py` (or wherever tools are assembled for the agent execution loop) so it is no longer bound to new agent sessions. Do not delete the class yet to allow safe rollback. The underlying `ControlCenterDataClient.save_output()` method (renamed from `submit_result`) remains in place as it is still used by the session completion flow in `langchain_tool_wrapper.py`.

**Done when**: `LangChainSaveResultTool` is no longer included in the set of tools built for any new agent session, and the three new tools (`LangChainSaveDataTool`, `LangChainGetDataTool`, `LangChainGetOutputTool`) are included instead.

## Phase 6 — Tool Registry and Name Catalog

### 6.1 — Register save_data, get_data, get_output in SystemToolRegistry

In `backend/app/services/agents/system_tool_registry.py`, call `SystemToolRegistry.register(SystemTool(...))` for each of `save_data`, `get_data`, and `get_output` with their correct descriptions and parameter schemas. These registrations must use the same schema structure as the corresponding `LangChainXxxTool` args schemas.

**Done when**: `SystemToolRegistry.get_names()` includes `save_data`, `get_data`, and `get_output`, and `SystemToolRegistry.get_schema("save_data")` returns a valid OpenAI function schema.

### 6.2 — Remove save_result from SystemToolRegistry

Remove the `SystemToolRegistry.register()` call for `save_result`. Confirm no other code references `save_result` as a tool name by searching the codebase. If any reference is found in a tool-routing path, update it to `save_data`.

**Done when**: `SystemToolRegistry.get_names()` no longer contains `save_result`, and no routing or dispatch code references `save_result` as an active tool name.

### 6.3 — Update SYSTEM_TOOL_NAMES in services/system_tools.py

In `backend/app/services/system_tools.py`, update the `SYSTEM_TOOL_NAMES` frozenset: remove `save_result`; add `save_data`, `get_data`, and `get_output`. `query_result` is retained as it remains an active tool. Update `SYSTEM_TOOL_DISPLAY_NAMES` accordingly. Verify `is_system_tool("save_data")` returns `True` and `is_system_tool("save_result")` returns `False`.

**Done when**: Both frozensets in `system_tools.py` reflect the new tool names, and `is_system_tool` returns the correct result for all old and new tool names.

## Phase 7 — Tests

### 7.1 — Unit tests for AgentDataService

Add tests in `backend/tests/` for `AgentDataService`: verify `save()` persists a record with correct field values; verify `query_by_filters()` returns only records matching the given filter; verify that calling `query_by_filters()` with no filters raises an error or returns an empty list as designed. Tests run against the test database fixture with migrations applied.

**Done when**: All new tests pass, and coverage includes the happy path for save and at least three filter combinations for query.

### 7.2 — Integration tests for new internal API endpoints

Add integration tests for the three new endpoints: `POST /api/v1/internal/system-tools/save-data`, `POST /api/v1/internal/system-tools/get-data`, and `POST /api/v1/internal/system-tools/get-output`. Each test uses a valid service certificate, sends a request, and asserts the correct HTTP status and response shape. Tests run against the real test database, not mocked responses.

**Done when**: All three endpoint tests pass, each test exercises the real database path, and the at-least-one-filter guard on `get-data` is verified.

### 7.3 — Unit tests for LangChain tool classes

Add tests in `backend/tests/unit/test_agent_save_data_tools.py` for `LangChainSaveDataTool`, `LangChainGetDataTool`, and `LangChainGetOutputTool`: verify each tool has the correct `name`, the expected fields in `args_schema`, and that `_arun` delegates to `comm_hub_client.call_tool` with the matching tool name. Verify `SystemToolRegistry` contains `save_data`, `get_data`, and `get_output` and that `is_system_tool` returns `True` for each.

**Done when**: All tool definition tests pass and every new tool class is covered.

### 7.4 — Verify save_result is no longer exposed in agent tool context

Write or extend an existing test that calls `GET /internal/data/agent-types/{id}/context` for a known agent type and asserts that the returned `tool_definitions` list does not contain a tool named `save_result` (canonical or display form). Also assert that `save_data`, `get_data`, and `get_output` are present in the tool list.

**Done when**: The test passes, confirming that no agent session will receive `save_result` as an available tool, and all three new tools are present.

## Completion Checklist

- [x] `agent_data` table exists in the database and all FK constraints are correct
- [x] `AgentDataService` is imported and usable from Control Center service layer
- [x] All three new CC system-tool endpoints are reachable and require mTLS
- [x] CommHub endpoint_map contains entries for `save_data`, `get_data`, and `get_output`
- [x] Agent execution loop uses `LangChainSaveDataTool`, `LangChainGetDataTool`, `LangChainGetOutputTool` with `comm_hub_client`
- [x] `save_result` is absent from `SystemToolRegistry.get_names()`
- [x] `SYSTEM_TOOL_NAMES` contains `save_data`, `get_data`, `get_output` and not `save_result`
- [x] All Phase 7 tests pass
- [x] Control Center starts cleanly after migration (`alembic current` = head)
- [x] Agent Runtime starts cleanly with new tool registrations active
