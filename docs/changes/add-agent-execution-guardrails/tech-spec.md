## Technical Overview
This technical specification defines guardrail controls for agent execution that prevent recursive delegation loops, enforce bounded runtime behavior, and improve operator-visible stop semantics. The target design enforces pre-execution delegation graph validation and runtime ceilings for cumulative iterations, delegated depth and step budgets, per-agent timeout, and mode-aware token policy behavior. The design preserves top-priority segregation in docs/config.yaml: Agent Runtime performs execution and enforcement decisions, Communication Hub routes messages and outcomes, and only Control Center persists policy/state and accesses the database.

Guardrail capability scope:
- Pre-execution delegation graph analysis with recursive cycle detection across direct and indirect delegation chains.
- Runtime enforcement for max iterations, delegated depth, delegated step budget, and execution timeout.
- Mode-aware token controls: conversational current-session token visibility with continuation, and token-budget enforcement for non-conversational or automated runs with explicit fallback mode when hard provider limits are unavailable.
- Structured guardrail decision logging and stop-reason propagation through internal APIs and session state.

## Component Breakdown

Agent Runtime
- Runtime enforcement owner for execution-time guardrails.
- Extends pre-check flow to perform delegation graph and cycle validation before first LLM/tool action.
- Extends runtime loop to enforce cumulative budgets and per-agent timeout.
- Emits conversational current-session token-usage snapshots and continuation eligibility signals without applying token-budget-only hard stop to conversational sessions.
- Emits guardrail decision events and terminal stop reasons through Control Center data APIs.

Control Center
- Policy source-of-truth and database owner.
- Resolves and returns effective guardrail policy snapshot in runtime context payloads.
- Persists stop outcomes and execution log entries for auditability and operations triage.
- Maintains internal API contracts used by Agent Runtime and Communication Hub.

Communication Hub
- Forwarding and routing owner for execute triggers and A2A delegation paths.
- Must preserve guardrail terminal payload semantics, including stop reason and guardrail category.
- Must not perform guardrail persistence or policy ownership logic.

Cross-service observability
- Execution log entries include pre-check decisions, runtime counter snapshots, conversational token-usage visibility events, fallback mode details, and terminal stop reason.
- Session status payloads distinguish guardrail stop outcomes from functional failures.

## API Changes

Control Center internal data APIs
- Extend context response for GET /api/v1/internal/data/agent-types/{agent_type_id}/context to include effective guardrail policy snapshot, including mode-aware token behavior fields that distinguish conversational continuation semantics from non-conversational or automated enforcement semantics.
- Extend PATCH /api/v1/internal/data/sessions/{session_id}/status payload handling to persist structured stop reason metadata for guardrail outcomes.
- Continue using POST /api/v1/internal/data/sessions/{session_id}/log for structured guardrail decision events, including conversational token-usage visibility snapshots and continuation-path events.

Agent Runtime internal execution flow
- No new public endpoint required; guardrail behavior is integrated into existing POST /execute processing and execution loops.
- Runtime-to-Control-Center calls continue through existing internal data client APIs, with expanded payload fields.

Communication Hub forwarding behavior
- No new route required for guardrails; existing forwarding endpoints must preserve stop-reason fields without remapping or loss.
- A2A request/response paths must carry parent/delegated guardrail outcomes unchanged, including conversational token-usage visibility metadata where applicable.

Backward compatibility
- Existing clients consuming session status remain compatible.
- New stop-reason and conversational token-visibility metadata fields are additive and should not break callers that only inspect status and error_message.

## State Management
State Management is applicable.

Runtime state
- Add in-memory guardrail counters in runtime execution context: cumulative_iterations, delegation_depth, delegated_steps, elapsed_seconds, token_usage_current_session.
- Add mode-aware token state fields in runtime context: token_threshold_reached, conversational_continuation_allowed, token_enforcement_applied.
- Add policy snapshot hash or identifier for correlating runtime decisions to resolved policy.

Persisted state
- Persist terminal guardrail stop details in session update payloads through Control Center.
- Persist structured guardrail decision events in execution log entries for pre-check and runtime phases.
- Persist conversational token-usage visibility snapshots and continuation-path metadata as non-terminal session telemetry.

Stop-reason taxonomy
- Define canonical guardrail reason values for cycle_detected, iteration_limit_exceeded, delegation_depth_exceeded, delegated_steps_exceeded, execution_timeout_exceeded, token_budget_exceeded_non_conversational, and token_guardrail_fallback_applied.
- Define non-terminal informational guardrail event reason values for conversational token-threshold visibility outcomes so they do not conflict with terminal stop reasons.
- Ensure taxonomy is stable across runtime, forwarding, and persistence layers.

## Data Access Patterns
- Agent Runtime performs zero direct database access and obtains policy/context via Control Center internal data APIs using ControlCenterDataClient.
- Guardrail policy retrieval occurs during context loading before execution loop begins.
- Guardrail decision and terminal updates are written through Control Center status/log APIs; Communication Hub forwards only and does not persist.
- Conversational token-usage visibility and continuation-path metadata are emitted from Agent Runtime and persisted via Control Center status/log APIs.
- A2A delegated execution results must propagate budget consumption and terminal guardrail reasons to parent session context through existing routing paths.

Segregation compliance expectations:
- Agent Runtime executes and enforces guardrails, but does not persist policy nor access database directly.
- Control Center remains sole persistence and governance authority.
- Communication Hub remains transport/router and must not assume policy-source ownership.

## Code Reference Map
| Symbol | Path | Role in Guardrail Change |
| --- | --- | --- |
| AgentRuntimeExecutor | backend/app/services/agents/runtime_executor.py | Primary runtime loop and pre-execution integration point for cycle checks, iteration/depth/timeout/token guardrails, and guardrail event emission |
| _run_task_loop_ar | backend/app/services/agents/runtime_executor.py | Task execution loop where cumulative iteration, timeout, and token guardrails are enforced |
| execute_conversation_turn | backend/app/services/agents/runtime_executor.py | Conversation execution loop requiring aligned iteration/timeout behavior, current-session token visibility, and continuation semantics |
| _extract_agent_delegation_target | backend/app/services/agents/runtime_executor.py | Delegation target parsing helper used to identify delegated steps in budget accounting |
| ControlCenterDataClient | backend/app/agent_runtime/data_client.py | Agent Runtime client for fetching policy/context and sending status/log updates without direct DB access |
| get_agent_context | backend/app/agent_runtime/data_client.py | Retrieves context payload to be extended with effective guardrail policy snapshot |
| mark_session_failed | backend/app/agent_runtime/data_client.py | Status update path for terminal guardrail stop propagation on non-conversational or automated enforcement outcomes |
| log_execution_event | backend/app/agent_runtime/data_client.py | Structured execution logging call used for guardrail decision events |
| trigger_execution | backend/app/agent_runtime/api/execute.py | Existing runtime entrypoint where guardrail-enabled execution lifecycle starts |
| _execute_session | backend/app/agent_runtime/api/execute.py | Background execution runner that must preserve guardrail stop handling |
| SessionDispatcher | backend/app/services/agents/session_dispatcher.py | Poll/dispatch worker path that must keep guardrail stop propagation consistent |
| trigger_agent_execution | backend/app/communication_hub/api/internal/agent_execute.py | Communication Hub forwarding path that must preserve guardrail terminal outcomes |
| CommHubToolClient | backend/app/agent_runtime/comm_hub_client.py | Runtime routing client for tool and A2A calls that participate in delegated budget consumption |
| call_a2a_request | backend/app/agent_runtime/comm_hub_client.py | Delegation request path where delegated depth and step tracking semantics must remain intact |
| request_a2a | backend/app/communication_hub/api/a2a.py | Communication Hub A2A route handling that must preserve stop reason and guardrail metadata |
| prepare_a2a_request | backend/app/api/v1/internal/session_data.py | Control Center A2A preparation endpoint involved in delegated execution flow |
| update_session_status | backend/app/api/v1/internal/session_data.py | Control Center persistence endpoint to store terminal guardrail stop outcomes |
| LogExecutionEventRequest | backend/app/api/v1/internal/session_data.py | Structured log payload schema to carry guardrail decision details |
| post_session_result | backend/app/api/v1/internal/session_data.py | Result persistence endpoint that must remain compatible with guardrail terminal metadata |
| get_agent_context | backend/app/api/v1/internal/agent_data.py | Control Center context endpoint to include effective guardrail policy fields |
| AgentContextResponse | backend/app/api/v1/internal/agent_data.py | Context response model to carry guardrail policy snapshot to runtime |
| AgentType | backend/app/db/models/agents.py | Agent configuration model likely extended with guardrail configuration fields |
| AgentJob | backend/app/db/models/agents.py | Session persistence model storing status/output/error used by stop-reason propagation |
| AgentTypeCreate | backend/app/schemas/agents.py | API input schema potentially extended with guardrail policy configuration fields |
| AgentTypeUpdate | backend/app/schemas/agents.py | API update schema potentially extended with guardrail policy configuration fields |
| AgentTypeRead | backend/app/schemas/agents.py | API read schema potentially extended to expose configured guardrail policy |
| ExecutionLogEntry | backend/app/db/models/session_logs.py | Persisted structured log entity used for guardrail decision and counter audit events |
| ExecutionLogEntryRead | backend/app/schemas/agents.py | API read schema for execution log entries containing guardrail events |
| AgentTypeRouter | backend/app/api/v1/agents.py | API router owning agent-type create/update/read workflows where guardrail config fields are validated |
| create_agent_type | backend/app/api/v1/agents.py | Agent-type create operation where policy validation and defaults are applied |
| update_agent_type | backend/app/api/v1/agents.py | Agent-type update operation where policy-bound checks and compatibility validations are applied |
| ModelBindingLayer | backend/app/services/agents/model_binding.py | Provider integration layer needed for token accounting capability checks and fallback decisions |
| complete_from_context | backend/app/services/agents/model_binding.py | Runtime provider call method where token usage extraction hooks are integrated |
| extract_text | backend/app/services/agents/model_binding.py | Response parser referenced by guarded runtime loop |
| extract_tool_calls | backend/app/services/agents/model_binding.py | Tool-call parser referenced by guarded runtime loop and delegated-step accounting |
| docs/config.yaml top_priority_rules | docs/config.yaml | Governing segregation constraints: runtime-only execution, Control-Center-only DB access, and sensitive data boundaries |
