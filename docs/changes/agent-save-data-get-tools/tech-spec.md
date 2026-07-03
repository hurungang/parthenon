## Technical Specification: agent-save-data-get-tools

## 1. Technical Overview

This change introduces a dedicated `AgentData` model and persistence service for intermediate named saves, replaces the legacy `save_result` system tool with `save_data` in the `SystemToolRegistry` and LangChain tool layer, and adds two new query tools (`get_data`, `get_output`) that retrieve `AgentData` and `AgentOutput` records respectively. All agent tool calls follow the established system-tool routing path: Agent Runtime LangChain tools call through `CommHubToolClient` → Communication Hub permission/routing layer → Control Center system-tool endpoints → database. All database operations remain exclusively in Control Center. The `ResultRecord` model and `ResultStore` service are not deleted in this change but are decoupled from the live tool path: `save_result` is removed from `SystemToolRegistry` and `LangChainSaveResultTool` is removed from the agent execution loop.

## 2. Component Breakdown

### AgentData model (`backend/app/db/models/agent_data.py`)
Defines the new `agent_data` table. Stores one record per `save_data` call: `id`, `agent_type_id` (nullable FK to `agent_types`), `session_id` (nullable FK to `agent_jobs`), `data_name`, `data_value` (JSON), `data_type` (String, default `"json"`), `is_active`, and `created_at`. Indexed on `(agent_type_id, data_name)` and `(session_id, data_name)` to serve the expected query patterns efficiently.

### AgentDataService (`backend/app/services/agent_data/service.py`)
Control Center service responsible for all `AgentData` persistence and querying. Provides `save()` to create a record and `query_by_filters()` to retrieve records matching one or more of `data_name`, `agent_type_id`, and `session_id`. Enforces that at least one filter is present on queries to prevent full-table scans. Used exclusively by Control Center internal API endpoints; never imported by Agent Runtime.

### OutputService extension (`backend/app/services/outputs/service.py`)
Extends the existing `OutputService` with `query_output_history()`, a new method that filters `AgentOutput` rows by `agent_type_id`, `session_id`, `date_from`, and `date_to`. This method is the backend of the `get_output` tool query path and is intentionally separate from the existing `list_outputs` method used by operator-facing API routes.

### System-tool endpoint additions (`backend/app/api/v1/internal/system_tools.py`)
The three new endpoints (`save-data`, `get-data`, `get-output`) were added directly to the existing `system_tools.py` router rather than a separate file. All three handlers follow the same pattern as the existing `save_result`, `send_notification`, and `human_intervene` handlers: they require `require_service_certificate`, delegate business logic entirely to `AgentDataService` or `OutputService`, and contain no inline query logic.

### Communication Hub endpoint map (`backend/app/communication_hub/api/internal/tool_routing.py`)
The `endpoint_map` dict in `_route_to_system_tool()` is extended with three new entries: `save_data`, `get_data`, and `get_output`, each mapping to the corresponding Control Center system-tool URL. No other changes to CommHub are required; the existing permission-check and routing infrastructure already handles any `system____*` prefixed tool name.

### LangChain tool classes (`backend/app/services/agents/langchain_system_tools.py`)
Three new `BaseTool` subclasses: `LangChainSaveDataTool`, `LangChainGetDataTool`, and `LangChainGetOutputTool`. Each holds a `comm_hub_client` reference injected at session construction time — following the same pattern as `LangChainSendNotificationTool` and `LangChainGetRecipientGroupTool`. `_arun` implementations call `comm_hub_client.call_tool("save_data" | "get_data" | "get_output", ...)` and return a JSON string result to the LLM. `LangChainSaveResultTool` is marked deprecated and removed from session tool construction.

### SystemToolRegistry updates (`backend/app/services/agents/system_tool_registry.py`)
`save_data`, `get_data`, and `get_output` are registered as `SystemTool` instances. `save_result` registration is removed. The registry remains the single source of truth for tool names, descriptions, and OpenAI function schemas; all consumers (context builder, runtime executor, mTLS tool dispatcher) derive their tool lists from it.

### system_tools.py name catalog (`backend/app/services/system_tools.py`)
`SYSTEM_TOOL_NAMES` frozenset is updated: `save_result` is removed, `save_data`, `get_data`, and `get_output` are added. `is_system_tool()` and `get_canonical_name()` helper functions continue to work correctly with the updated set.

## 3. API Changes

### New: POST /api/v1/internal/system-tools/save-data (Control Center)
Saves one `AgentData` record on behalf of an agent session. Called by CommHub when routing a `save_data` system tool call. Accepts `agent_type_id`, `session_id`, `data_name`, `data_value`, and `data_type` in the request body. Returns the saved record including its `id` and `created_at`. Requires mTLS service certificate.

### New: POST /api/v1/internal/system-tools/get-data (Control Center)
Queries `AgentData` records. Called by CommHub when routing a `get_data` system tool call. Accepts filter fields in the request body: `data_name`, `agent_type_id`, `session_id`, `limit`, `offset`. At least one filter must be provided. Returns a list of matching records. Requires mTLS service certificate.

### New: POST /api/v1/internal/system-tools/get-output (Control Center)
Queries `AgentOutput` records. Called by CommHub when routing a `get_output` system tool call. Accepts filter fields in the request body: `agent_type_id`, `session_id`, `date_from`, `date_to`, `limit`, `offset`. Returns a list of `AgentOutput` records ordered by `created_at` descending. Requires mTLS service certificate.

### Modified: CommHub endpoint_map in `tool_routing.py`
Three new entries added to the `endpoint_map` dict in `_route_to_system_tool()`: `save_data`, `get_data`, and `get_output`, each pointing to the corresponding Control Center URL above.

### Modified: /api/v1/internal/data/agent-types/{id}/context
The `tool_definitions` field in the response will include `save_data`, `get_data`, and `get_output` and will no longer include `save_result`. This change is automatic once `SystemToolRegistry` is updated, since the context builder derives tool definitions from the registry via `SystemToolRegistry.get_all_schemas()`.

### Unchanged: All existing /api/v1/internal/agent-outputs endpoints
The `InternalOutputsRouter` endpoints for typed output validation and persistence are not modified.

### Unchanged: /api/v1/results endpoints
The `ResultRouter` (public-facing query for `ResultRecord`) is not modified. `ResultRecord` data remains queryable by operators but `save_result` no longer writes new records via the agent tool path.

## 4. State Management

This change does not introduce frontend UI changes. No React components, hooks, or frontend state management are affected.

## 5. Data Access Patterns

### save_data flow
Agent Execution Loop (AR) → `LangChainSaveDataTool._arun()` → `CommHubToolClient.call_tool("save_data", ...)` → CommHub `/internal/tools/call` → `_route_to_system_tool()` → `POST /api/v1/internal/system-tools/save-data` (CC, mTLS) → `AgentDataService.save()` → `agent_data` row inserted into PostgreSQL.

All agent tool calls pass through CommHub for permission validation. No direct AR → CC path is used for these tools.

### get_data flow
Agent Execution Loop (AR) → `LangChainGetDataTool._arun()` → `CommHubToolClient.call_tool("get_data", ...)` → CommHub `/internal/tools/call` → `_route_to_system_tool()` → `POST /api/v1/internal/system-tools/get-data` (CC, mTLS) → `AgentDataService.query_by_filters()` → filtered query on `agent_data` table.

At least one of `data_name`, `agent_type_id`, or `session_id` must be provided; the service rejects unbounded queries to prevent full-table scans.

### get_output flow
Agent Execution Loop (AR) → `LangChainGetOutputTool._arun()` → `CommHubToolClient.call_tool("get_output", ...)` → CommHub `/internal/tools/call` → `_route_to_system_tool()` → `POST /api/v1/internal/system-tools/get-output` (CC, mTLS) → `OutputService.query_output_history()` → filtered query on `agent_outputs` table.

The `query_output_history` method is kept separate from the operator-facing `list_outputs` to maintain a clean boundary between agent tool API and operator API semantics.

### save_result retirement
`LangChainSaveResultTool` calls `ControlCenterDataClient.save_output()` which targets `POST /internal/data/sessions/{id}/result` on Control Center. This path is not removed from `ControlCenterDataClient` as it is also used by the final session completion flow in `langchain_tool_wrapper.py`. Only the `save_result` LangChain tool binding to agent sessions is removed.

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentData` | class | New SQLAlchemy model for intermediate named agent saves | `backend/app/db/models/agent_data.py` |
| `ResultRecord` | class | Legacy SQLAlchemy model for save_result; decoupled from agent tool path | `backend/app/db/models/results.py` |
| `AgentOutput` | class | Immutable typed output model; queried by get_output tool | `backend/app/db/models/agent_output.py` |
| `AgentJob` | class | Agent execution session model; FK target for AgentData.session_id | `backend/app/db/models/agents.py` |
| `AgentType` | class | Agent type model; FK target for AgentData.agent_type_id | `backend/app/db/models/agents.py` |
| `AgentDataService` | class | Control Center service for saving and querying AgentData records | `backend/app/services/agent_data/service.py` |
| `ResultStore` | class | Legacy service for ResultRecord; decoupled from active agent tool path | `backend/app/services/results/store.py` |
| `OutputService` | class | Control Center service for AgentOutput persistence and querying | `backend/app/services/outputs/service.py` |
| `save_typed` | method | Existing method on OutputService for persisting a typed AgentOutput | `backend/app/services/outputs/service.py` |
| `list_outputs` | method | Existing operator-facing query method on OutputService | `backend/app/services/outputs/service.py` |
| `query_output_history` | method | New agent-facing query method on OutputService for get_output tool | `backend/app/services/outputs/service.py` |
| `save_data_tool` | endpoint | New POST /api/v1/internal/system-tools/save-data handler | `backend/app/api/v1/internal/system_tools.py` |
| `get_data_tool` | endpoint | New POST /api/v1/internal/system-tools/get-data handler | `backend/app/api/v1/internal/system_tools.py` |
| `get_output_tool` | endpoint | New POST /api/v1/internal/system-tools/get-output handler | `backend/app/api/v1/internal/system_tools.py` |
| `InternalAgentDataRouter` | router | Existing router for agent configuration data (plan, context, model-config) | `backend/app/api/v1/internal/agent_data.py` |
| `InternalOutputsRouter` | router | Existing router for typed output validation and persistence | `backend/app/api/v1/internal/outputs.py` |
| `InternalSessionDataRouter` | router | Existing router for session lifecycle management | `backend/app/api/v1/internal/session_data.py` |
| `router` | router | Existing router for system tool dispatch; now includes save-data, get-data, get-output | `backend/app/api/v1/internal/system_tools.py` |
| `ControlCenterDataClient` | class | Agent Runtime HTTP client for all Control Center data calls | `backend/app/agent_runtime/data_client.py` |
| `LangChainSaveDataTool` | class | LangChain tool for save_data; routes via CommHub | `backend/app/services/agents/langchain_system_tools.py` |
| `LangChainGetDataTool` | class | LangChain tool for get_data; routes via CommHub | `backend/app/services/agents/langchain_system_tools.py` |
| `LangChainGetOutputTool` | class | LangChain tool for get_output; routes via CommHub | `backend/app/services/agents/langchain_system_tools.py` |
| `LangChainSaveResultTool` | class | Deprecated; retained for session-completion flow only | `backend/app/services/agents/langchain_system_tools.py` |
| `build_langchain_tools_for_ar_path` | function | Assembles LangChain tools for AR execution path; now includes save_data/get_data/get_output | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `save_output` | method | Renamed from `submit_result`; saves the final session output to Control Center | `backend/app/agent_runtime/data_client.py` |
| `persist_typed_output` | method | Existing method on ControlCenterDataClient for typed output persistence | `backend/app/agent_runtime/data_client.py` |
| `CommHubToolClient` | class | Agent Runtime client that routes all tool calls through Communication Hub | `backend/app/agent_runtime/comm_hub_client.py` |
| `call_tool` | method | Sends a tool call to CommHub `/internal/tools/call` with mTLS | `backend/app/agent_runtime/comm_hub_client.py` |
| `_route_to_system_tool` | function | CommHub function that maps bare tool name to CC system-tool endpoint URL | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `endpoint_map` | dict | CommHub mapping of bare tool names to Control Center internal URLs; extended with save_data, get_data, get_output | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `SystemToolRegistry` | class | Single source of truth for all registered system tool names and schemas | `backend/app/services/agents/system_tool_registry.py` |
| `SystemTool` | class | Descriptor for a single built-in system tool entry in the registry | `backend/app/services/agents/system_tool_registry.py` |
| `SYSTEM_TOOL_NAMES` | constant | Frozenset of canonical bare system tool names; updated in this change | `backend/app/services/system_tools.py` |
| `SYSTEM_TOOL_DISPLAY_NAMES` | constant | Frozenset of prefixed display names derived from SYSTEM_TOOL_NAMES | `backend/app/services/system_tools.py` |
| `is_system_tool` | function | Returns True if a name refers to a registered system tool | `backend/app/services/system_tools.py` |
| `get_canonical_name` | function | Strips system/ or system_ prefix from a tool name | `backend/app/services/system_tools.py` |
