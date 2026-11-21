# Module: agents — Execution Pipeline

> Part of the [agents hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

This page covers what happens after an agent type is defined: session enqueue and dispatch, the LangChain deep-agent runtime loop, tool wrapping and MCP session context, A2A delegation, guardrails and the model-usage hierarchy, human intervention, structured (typed) outputs, and the runtime monitor.

Execution happens only in Agent Runtime; Control Center owns the queue, the configuration, the guardrails, the logs and the results. Tool calls always route through Communication Hub.

---

## Key Components

### Queue and sessions

| Component | Description |
|-----------|-------------|
| `AgentSessionService` | Enqueues sessions (`INSERT` with `status = queued`; delegation inherits the parent's triggering user), manages `queued → running → waiting_for_human → completed / failed / terminated`, persists results, tracks `conversation_history`, joins agent type and triggered-by names on reads, and computes the optimization gate (see [plans-optimization.md](plans-optimization.md)) |
| `SessionDispatcher` | Background worker; claims queued sessions with `SELECT … FOR UPDATE SKIP LOCKED`; dispatches to AR; manages concurrency |
| `AgentJobLaunchDialog` (UI) | Dynamic input form per `input_type`; execution-only (no optimization opt-in) |

### Runtime

| Component | Description |
|-----------|-------------|
| `AgentRuntimeExecutor` | Orchestrates execution: validates identity → role assignment, captures prompt logs before the first LLM call, builds the tool set, loads MCP session context, enforces delegation depth, emits delegation status events, injects the output-type prompt, persists results |
| `TaskAgentLoop` / `ConversationalAgentLoop` | LangChain deep-agent loops (single structured/markdown result; multi-turn with `conversation_history`) |
| `LangChainToolWrapper` / `build_langchain_tools_for_ar_path` | Wraps each tool so calls route through Communication Hub, preserving mTLS and segregation; records canonical tool names and delegation targets |
| `LangChainSystemTools` | `save_data`, `get_data`, `get_output`, `human_intervene` and (optimization/assistant contexts) the optimization tool set; all routed to CC |
| `ExecutionLoggingCallback` | Emits structured execution-log entries (LLM start/end, tool start/end, chain events) incl. replayable tool arguments/responses with caps |
| `ControlCenterDataClient` (AR) | Fetches context/model/session state, persists status, outputs, logs and tool-call records |
| `CommHubToolClient` | AR → CH tool/A2A egress (signed tenant headers, identity injected per call) |

### Guardrails and model usage

| Component | Description |
|-----------|-------------|
| `GuardrailCallback` | Async callback evaluated before every LLM call (per-period limits, vendor/model disabled state); raises `GuardrailStop`; emits threshold events |
| `GuardrailStop` / `GuardrailStopReason` | Bounded stop (incl. `repeated_tool_call` for command/optimization turns) |
| Guardrail hierarchy | Vendor (`ModelConfig.is_disabled`) → per-model `ModelAvailability` (`manual` / `vendor_cascaded`) → per-period `ModelGuardrailConfiguration` (`terminate` / `observe_only`, unit `k`/`tokens`) |
| `ModelUsageGuardrailService` / `ModelAvailabilityService` | Per-guardrail CRUD and posture rollups; availability cascade and pre-execution check |
| `AgentRuntimeExecutor._preflight_availability` | Policy-block outcome when the resolved model/vendor is disabled |

### Delegation and intervention

| Component | Description |
|-----------|-------------|
| A2A delegation | Delegated runs link through `AgentJob.parent_job_id` (+ `AgentRunRelationship`); target agent types must be in the caller's delegation set; non-conversational delegation is depth-1 |
| Delegation status events | `delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed` |
| `human_intervene` tool | Pauses for approval/choice/text; task agents use LangGraph interrupt; conversational turns use the durable pause/resume machinery documented in [conversations](../conversations/tech-spec.md) |
| `InterveneRequestStore` | CRUD + metrics; pending lists by job/conversation; response submission creates the `intervene_response` turn; pause path stamps the tenant resume TTL |

### Structured outputs

| Component | Description |
|-----------|-------------|
| `AgentDataType` / `AgentOutput` | Reusable typed schema and typed execution result (`valid` / `validation_error`, raw fallback) |
| `SchemaValidationService` | Validates payloads against the data type's fields |
| `OutputService` | Typed persistence, filtered queries, CSV export; links `AgentJob.output_id` |
| `save_data` / `get_data` / `get_output` / `query_result` | Agent-facing data and output tools |
| `ToolStrategy` response format | Native structured output when `output_data_type_id` is set (no system-prompt injection) |

### Runtime monitor

| Component | Description |
|-----------|-------------|
| `RuntimeTopologyController` | Merges live `AgentJob`, `ConversationSession` (synthetic active/sleep) and `AgentInstance` nodes; resolves provenance, tool-call routes, pending interventions and delegation edges; supports a recent-terminal window |
| `TerminationOrchestrator` | Permission-gated terminate + cascade through CC → CH → AR; records request and per-node outcomes |
| `AgentRuntimeMapCanvas` | Full-page interactive map: delegation-tree containers, hub firewall bar, orthogonal tool routes, contrast-focus isolation, stream-first feed with polling fallback |

---

## API Endpoints

### Sessions

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/agents/sessions` | Enqueue a normal run (202 + session id) |
| `GET` | `/api/v1/agents/sessions` | List sessions (`status`, `since`, `agent_type_id`) |
| `GET` | `/api/v1/agents/sessions/{id}` | Status and timing |
| `GET` | `/api/v1/agents/sessions/{id}/result` | Full output (409 until completed) |
| `GET` | `/api/v1/agents/sessions/{id}/execution-logs` | Captured system instruction + user prompt |
| `GET` | `/api/v1/agents/sessions/{id}/logs` | Ordered execution-log entries |
| `GET` | `/api/v1/agents/sessions/{id}/logs/stream` | Live NDJSON log stream with terminal marker |

### Intervene

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/intervene/requests` | List (status, type, agent session, pagination) |
| `GET` | `/api/v1/intervene/requests/{id}` | Detail with response |
| `POST` | `/api/v1/intervene/requests/{id}/respond` | Submit an answer |
| `POST` | `/api/v1/intervene/requests/{id}/cancel` | Cancel |
| `GET` | `/api/v1/intervene/metrics` | Pending count, average response time, resolution rate |

### Runtime, termination and model usage

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/runtime/topology` | Topology projection (`recent_minutes` window) |
| `GET` | `/api/v1/agents/runtime/topology/stream` | SSE stream (`?token=`) recomputed ~2 s, hash-deduped, heartbeats |
| `POST` | `/api/v1/agents/runtime/termination` | Permission-gated terminate request |
| `GET` | `/api/v1/agents/runtime/termination/{id}/outcomes` | Cascade outcomes |
| `GET` | `/api/v1/agents/runtime/policy-events` | Policy/guardrail/termination events |
| `GET` | `/api/v1/agents/model-usage/posture` | Posture rollups |
| `GET` / `POST` | `/api/v1/agents/model-usage/limits` | List / create per-period guardrails |
| `GET` / `PUT` / `DELETE` | `/api/v1/agents/model-usage/limits/{id}` | Single guardrail CRUD |
| `POST` | `/api/v1/agents/model-availability/vendors/{id}/disabled` | Vendor toggle + cascade |
| `PUT` | `/api/v1/agents/model-availability/models/{vendor_id}/{model_name}` | Per-model availability |
| `GET` | `/api/v1/agents/model-availability` | Vendor → model → enabled state |
| `POST` | `/api/v1/agents/model-availability/preflight` | Pre-execution availability check |
| `GET` | `/api/v1/dashboard/token-health` | Identity/session token health (see [control-center security](../control-center/security-layer.md)) |

---

## Data Access Patterns

- **CC owns the queue and all persistence.** AR receives context/config identifiers over mTLS internal routes and reports statuses, outputs and logs back; AR never writes the database.
- **Tool calls always traverse CH.** AR holds no tokens; CH resolves/injects identity per call from CC's authorisation.
- **Execution logs are append-only and replayable.** LLM tool calls record structured arguments and responses (10,000 / 50,000-char caps, truncation flags); sandbox tool calls record the full response. This is the replay source for optimization (see [sandboxed-scripting](../sandboxed-scripting/tech-spec.md)).
- **Typed output is validated then persisted** in one completion flow; a validation error keeps the raw output.
- **Prompt capture precedes the first LLM call** so the full system instruction and user prompt exist for audit even if the run fails.
- **Termination is a distinct state** (`terminated`), never conflated with `failed`; late updates from the terminated run are rejected.

---

## Code Reference Map

### Models and schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentJob` / `AgentJobStatus` | model / enum | Async session (`queued`, `running`, `waiting_for_human`, `completed`, `failed`, `terminated`), `conversation_history`, `output_id` | `backend/app/db/models/agents.py` |
| `AgentPromptLog` | model | Prompt capture before the first LLM call (table `execution_logs`) | `backend/app/db/models/agents.py` |
| `ExecutionLogEntry` / `ExecutionEventCategory` | model / enum | Structured execution-log entries and categories (guardrail/model/vendor events) | `backend/app/db/models/session_logs.py` |
| `RuntimeToolCall` / `RuntimeToolCallSessionKind` / `RuntimeToolCallRouteType` / `RuntimeToolCallStatus` | model / enums | Tool-call audit (polymorphic session id, route type, ledger pointer) | `backend/app/db/models/tool_calls.py` |
| `AgentData` | model | Intermediate named saves (`data_name`, `data_value`, `data_type`) | `backend/app/db/models/agent_data.py` |
| `AgentDataType` / `AgentOutput` / `AgentOutputValidationStatus` | models / enum | Data type registry and typed outputs | `backend/app/db/models/agent_data_type.py`, `backend/app/db/models/agent_output.py` |
| `InterveneRequest` / `InterveneRequestStatus` / `InterventionType` / `InterveneResponse` | models / enums | Job- and conversation-scoped interventions | `backend/app/db/models/intervene.py` |
| `AgentRunRelationship` | model | Parent-child runtime relationship for topology | `backend/app/db/models/agent_run_relationship.py` |
| `TerminationRequest` / `TerminationCascadeOutcome` | models | Termination request and per-node cascade result | `backend/app/db/models/termination_request.py`, `termination_cascade_outcome.py` |
| `ModelUsagePosture` / `ModelGuardrailEvaluation` / `GuardrailThresholdEvent` | models | Posture snapshots, per-run evaluations, threshold alerts | `backend/app/db/models/model_usage_posture.py`, `model_guardrail_evaluation.py`, `guardrail_threshold_event.py` |
| `SopRecursionValidationCheck` / `SopRecursionValidationFinding` | models | Recursion-risk validation audit | `backend/app/db/models/sop_recursion_validation_check.py`, `sop_recursion_validation_finding.py` |
| `AgentJobCreate` / `AgentJobStatusRead` / `AgentJobRead` | schemas | Session create/status/full read contracts | `backend/app/schemas/agents.py` |
| `ExecutionLogRead` / `ExecutionLogEntryRead` | schemas | Prompt-log and entry contracts | `backend/app/schemas/agents.py` |
| `InterveneRequestCreate` / `InterveneRequestRead` / `InterveneResponseSubmit` / `InterveneResponseRead` / `InterveneMetrics` | schemas | Intervention contracts | `backend/app/schemas/intervene.py` |

### Services and runtime

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentSessionService` | class | Session lifecycle, result persistence, gate computation | `backend/app/services/agents/session_service.py` |
| `SessionDispatcher` | class | Queue claim and dispatch | `backend/app/services/agents/session_dispatcher.py` |
| `AgentRuntimeExecutor` | class | Execution orchestration (LangChain loop, tools, delegation, results) | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn` / `execute_conversation_turn_from_context` | methods | Conversational execution paths | `backend/app/services/agents/runtime_executor.py` |
| `_run_task_loop_ar` / `_extract_agent_delegation_target` / `_get_agent_identity_jwt` / `_load_role_mcp_session_map` | methods / functions | Task loop enforcement, delegation labels, passthrough identity, MCP session map | `backend/app/services/agents/runtime_executor.py` |
| `_preflight_model_availability` | method | Model/vendor policy pre-check | `backend/app/services/agents/runtime_executor.py` |
| `_record_tool_call_safely` / `_build_tool_call_recorder` | methods | Best-effort tool-call recording hooks | `backend/app/services/agents/runtime_executor.py` |
| `build_conversation_guardrail_usage` | function | Conversation-kind guardrail usage payload | `backend/app/services/agents/runtime_executor.py` |
| `TaskAgentLoop` / `ConversationalAgentLoop` | classes | LangChain deep-agent loops | `backend/app/services/agents/agent_loop.py` |
| `LangChainToolWrapper` / `build_langchain_tools_from_definitions` / `build_langchain_tools_for_ar_path` | class / functions | Tool wrapping and AR tool-set assembly | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `LangChainSaveDataTool` / `LangChainGetDataTool` / `LangChainGetOutputTool` / `LangChainHumanInterveneTool` | classes | LangChain system tools routed through CH | `backend/app/services/agents/langchain_system_tools.py` |
| `ExecutionLoggingCallback` | class | Structured log emission incl. replayable tool evidence | `backend/app/services/agents/execution_logging_callback.py` |
| `GuardrailCallback` / `GuardrailStop` | class / exception | Pre-call guardrail evaluation and bounded stop | `backend/app/services/agents/guardrail_callback.py`, `backend/app/services/agents/guardrails.py` |
| `InterveneRequestStore` | service | Intervention persistence, pending lists, response submission, resume TTL stamping | `backend/app/services/agents/intervene_service.py` |
| `AgentDataService` | class | Named data save/query (at least one filter required) | `backend/app/services/agent_data/service.py` |
| `OutputService` | class | Typed output persistence/query/export; `query_output_history` | `backend/app/services/outputs/service.py` |
| `DataTypeService` / `DataTypeNotFoundError` / `DataTypeConflictError` / `DataTypeDuplicateError` | service / exceptions | Data type CRUD with reference protection | `backend/app/services/data_types/service.py` |
| `SchemaValidationService` | class | Payload validation against the data type | `backend/app/services/validation/schema_validation_service.py` |
| `RuntimeTopologyController` / `_resolve_mcp_slug` | service / function | Topology projection and slug resolution | `backend/app/services/control_center/runtime_topology_controller.py` |
| `TerminationOrchestrator` / `RecursionValidationService` / `ModelAvailabilityService` / `ModelUsageGuardrailService` | services | Termination cascade, recursion validation, availability and guardrail management | `backend/app/services/control_center/` |

### API and internal routes

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentJobRouter` | router | `/agents/sessions` surface | `backend/app/api/v1/agents.py` |
| `get_session_execution_logs` / `stream_session_execution_logs` / `get_session_prompt_logs` | endpoints | Log pull, live stream, prompt logs | `backend/app/api/v1/agents.py` |
| `get_runtime_topology` / `stream_runtime_topology` | endpoints | Topology projection and SSE stream | `backend/app/api/v1/agents.py` |
| `request_runtime_termination` / `get_runtime_termination_outcomes` / `list_runtime_policy_events` | endpoints | Termination and policy events | `backend/app/api/v1/agents.py` |
| `get_model_usage_posture` / `list_model_usage_limits` / `create_model_usage_limit` / `get_model_usage_limit` / `update_model_usage_limit` / `delete_model_usage_limit` | endpoints | Per-period guardrail CRUD and posture | `backend/app/api/v1/agents.py` |
| `set_vendor_disabled` / `set_model_availability` / `list_model_availability` / `preflight_availability` | endpoints | Availability hierarchy and preflight | `backend/app/api/v1/agents.py` |
| `InterveneRouter` | router | `/intervene/*` surface | `backend/app/api/v1/intervene.py` |
| `human_intervene_tool` | endpoint | Creates the intervention (conversation-scoped requests carry a nullable job id) | `backend/app/api/v1/internal/system_tools.py` |
| `save_data_tool` / `get_data_tool` / `get_output_tool` / `query_result_tool` | endpoints | Agent data/output tools | `backend/app/api/v1/internal/system_tools.py` |
| `InternalOutputsRouter` | router | Output validation/persistence/query | `backend/app/api/v1/internal/outputs.py` |
| `DataTypeRouter` / `OutputRouter` | routers | Public data type and output APIs | `backend/app/api/v1/data_types.py`, `backend/app/api/v1/agent_outputs.py` |
| `record_tool_calls` | endpoint | Tool-call batch ingestion | `backend/app/api/v1/internal/session_data.py` |
| `forward_terminate_session` | endpoint | CH terminate forwarder (30 s read timeout, 3 attempts) | `backend/app/communication_hub/api/internal/agent_terminate.py` |
| `terminate_session` | endpoint | AR terminate + delegation cascade | `backend/app/agent_runtime/api/terminate.py` |
| `_AGENT_RUNTIME_RELAY_PATH_PREFIXES` | constant | Control-plane relay prefixes that include the terminate path | `backend/app/communication_hub/middleware/control_plane.py` |

### Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentJobPage` | component | Session page (status polling / chat / result / logs) | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `AgentInstanceDashboardPage` / `AgentExecutionsDialog` / `AgentExecutionDetailsDialog` | components | Execution list and detail dialogs | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx`, `frontend/src/components/agents/AgentExecutionsDialog.tsx`, `AgentExecutionDetailsDialog.tsx` |
| `RuntimeControlDashboardPage` / `AgentRuntimeMapCanvas` / `AgentDetailBubble` / `TriggerDetailBubble` / `runtimeNodeMeta` / `NodeTerminationDialog` | components / module | Runtime monitor map, bubbles, termination | `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx`, `frontend/src/components/agents/AgentRuntimeMapCanvas.tsx`, `AgentDetailBubble.tsx`, `TriggerDetailBubble.tsx`, `runtimeNodeMeta.ts`, `NodeTerminationDialog.tsx` |
| `RuntimeTopologyPanel` | component | Legacy flat runtime tree (retained, not rendered) | `frontend/src/components/agents/RuntimeTopologyPanel.tsx` |
| `useRuntimeTopology` / `isNodeVisibleByDefault` / `useNodeTermination` / `getPendingInterventionForNode` | hooks / functions | Stream-first feed, visibility, termination, pending intervention | `frontend/src/hooks/useRuntimeTopology.ts`, `useNodeTermination.ts`, `frontend/src/api/interveneApi.ts` |
| `useModelUsagePosture` / `useModelUsageLimits` / `useAvailableModels` / `useCreateModelUsageLimit` / `useUpdateModelUsageLimit` / `useDeleteModelUsageLimit` / `useModelAvailability` / `useSetVendorDisabled` / `useSetModelDisabled` / `usePreflightAvailability` | hooks | Guardrail/availability server state | `frontend/src/hooks/useModelUsagePosture.ts`, `useAvailableModels.ts`, `useModelUsageGuardrailMutations.ts`, `useModelAvailability.ts`, `usePreflightAvailability.ts` |
| `useEndConversationSession` | hook | End a sleep conversation session | `frontend/src/hooks/useConversationSessions.ts` |
| `LogViewer` / `LogSummaryPanel` / `WorkingStepsPanel` / `RawLogToggle` / `presentLog` | components / service | Execution log presentation | `frontend/src/components/executions/`, `frontend/src/services/LogPresenter.ts` |
| `useExecutionLogs` / `useSessionExecutionLogStream` | hooks | Log pull and live stream | `frontend/src/hooks/useExecutionLogs.ts`, `useSessionExecutionLogStream.ts` |
| `IntervenePage` / `InterveneRequestList` / `InterveneResponseDialog` / `useInterveneRequests` / `interveneApi` | page / components / hook / module | Dashboard intervention surfaces | `frontend/src/pages/agents/IntervenePage.tsx`, `frontend/src/components/agents/InterveneRequestList.tsx`, `InterveneResponseDialog.tsx`, `frontend/src/hooks/useInterveneRequests.ts`, `frontend/src/api/interveneApi.ts` |
| `RuntimeTopologyNode` / `RuntimeTopologyEdge` / `RuntimeTopologyProjection` / `ToolCallRoute` / `AvailableModel` / `ModelAvailability` / `ModelUsagePosture` | types | Runtime/model-usage frontend contracts | `frontend/src/types/index.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_agent_runtime_executor` | test module | Executor unit tests (incl. passthrough identity) | `backend/tests/unit/test_agent_runtime_executor.py` |
| `test_intervene_service` / `test_intervene_api` | test suites | Intervention CRUD, transitions, metrics, API lifecycle | `backend/tests/services/test_intervene_service.py`, `backend/tests/api/v1/test_intervene.py` |
| `test_agent_data_service` / `test_agent_save_data_tools` / `test_system_tool_endpoints` | tests | Data save/query services, LangChain tools, internal endpoints | `backend/tests/unit/test_agent_data_service.py`, `backend/tests/unit/test_agent_save_data_tools.py`, `backend/tests/integration/test_system_tool_endpoints.py` |
| `test_data_types_api.py` / `test_output_validation.py` / `test_agent_outputs_api.py` / `test_query_result_tool.py` | tests | Data type CRUD, validation, typed outputs, query tool | `backend/tests/` |
| `test_runtime_topology_controller` / `test_termination_orchestrator` / `test_agent_runtime_client_terminate` / `test_session_status_update_guards` | tests | Topology, cascade, CH-routed terminate, late-update guards | `backend/tests/unit/services/test_runtime_topology_controller.py`, `backend/tests/services/test_termination_orchestrator.py`, `test_agent_runtime_client_terminate.py`, `backend/tests/api/v1/internal/test_session_status_update_guards.py` |
| `test_agent_runtime_controls_api` / `test_model_usage_guardrails_api` / `test_model_availability_api` | tests | Recursion/termination API, guardrail CRUD, availability endpoints | `backend/tests/api/v1/` |
| `RuntimeControlDashboardPage.test` / `AgentRuntimeMapCanvas.test` / `AgentDetailBubble.test` / `TriggerDetailBubble.test` / `RuntimeTopologyPanel.test` / `LogPresenter.test` / `LogSummaryPanel.test` | frontend tests | Monitor, canvas, bubbles, log presentation | `frontend/src/__tests__/` |
| `runtime-control-dashboard.spec.ts` / `agent-save-data-get-tools.spec.ts` / `agent-outputs-query.spec.ts` | E2E tests | Monitor/terminate, data tools, output queries | `e2e/tests/` |
