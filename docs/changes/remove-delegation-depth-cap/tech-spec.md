# Technical Specification: remove-delegation-depth-cap

## Technical Overview

Delegation depth becomes configuration-authoritative in three places: Control Center surfaces the recorded depth and the configured maximum, Agent Runtime resolves and enforces depth from those values instead of constants, and the web UI stops clamping the configured value and stops folding a child's onward delegation into the parent's log peek.

The change is additive and subtractive only — one new field on an existing internal payload, several constant removals, and one client-side filter. There is no new service, no new endpoint, no schema change, and no migration. Only Control Center touches the database; Agent Runtime continues to learn depth and limits through the internal data plane it already calls, and Communication Hub remains a forward-only relay with no depth logic.

Core invariants preserved by design:

- The comparison every enforcement site makes is unchanged: a run is stopped when its own chain depth exceeds the configured maximum, and the task-loop delegation guard blocks a hop that would take the chain beyond it. A block still raises or emits the pre-existing guardrail reasons.
- Cycle detection, dead-loop detection, delegated-step budgets, iteration ceilings, timeouts, and token budgets are untouched.
- Execution-log queries remain single-session; the only log change is a display filter on the parent's direct-child peek.

---

## Component Breakdown

### 1. Control Center — internal session payload (depth surface)

| Item | Change |
|---|---|
| Internal session response model | New required integer field for the job's recorded delegation depth. |
| Internal session lookup handler | Populates the new field from the persisted job column. |
| Internal session client (Agent Runtime side) | Unchanged; the caller already returns the payload as a mapping, so the added key arrives without a signature change. |

The recorded depth is the authoritative starting point for a delegated child's run. It is never derived at read time from request payloads.

### 2. Control Center — A2A delegation preparation

| Item | Change |
|---|---|
| A2A preparation handler | Unchanged behaviour. Confirms that the parent link is resolved only when the requester identifier is an existing agent job. |
| Session enqueue service method | Unchanged behaviour. Child depth remains parent depth plus one, persisted at creation. |
| Conversational delegation | Documented limitation: when the requester is a conversation (no agent job behind the request), no parent job link is produced, so the delegated job's recorded depth is zero. No schema field is introduced to compensate. |

**Verified finding (task 1.2).** The A2A preparation handler resolves a parent job by treating `requester_instance_id` as a candidate `AgentJob` id and only linking it when that row exists (`select(AgentJob.id) where id == candidate`). A conversation turn has no backing `AgentJob` (its execution is sessionless and passes the conversation/turn session id as the requester), so resolution fails closed to `parent_job_id = None` and the enqueue path records `delegation_depth = 0` for that child. That is the accepted behaviour for this change: conversational delegation children start at their own recorded depth (zero when no parent job was linked), while task-agent delegations inherit the chain depth (`parent.delegation_depth + 1`). No production behaviour was altered and no compensating schema field was added.

The consequence is deliberate: conversational delegations start each hop at depth zero, while task-agent delegations inherit the chain depth. Both are bounded by the configured maximum at every hop, and neither reintroduces a platform cap.

### 3. Control Center — delegation status API

| Item | Change |
|---|---|
| Delegation status response model | Field set unchanged; the maximum-depth field no longer defaults to a one-level constant. |
| Delegation status handler | Returns the session agent type's configured maximum depth, read from the already eagerly loaded agent type. Falls back to the platform guardrail default if the agent type is unavailable. |
| Pending intervention handler | Unchanged. Remains direct-child scoped for log-scoping reasons. |

### 4. Control Center — guardrail validation

| Item | Change |
|---|---|
| REST guardrail contract validator | Delegation-depth ceiling removed; non-negative floor, integer coercion, and structured error reporting retained. |
| Assistant-managed structured validator | Same relaxation, keeping per-field structured problems and the conversational token-enforcement rule. |
| Depth bound constants (both modules) | Ceiling constant deleted from both modules; floor constant retained. |
| Assistant tool-schema field descriptions | Depth description no longer advertises a numeric ceiling. |
| Agent type create handler | Persists every submitted guardrail value on the new agent type row, including the configured maximum depth; previously the values were validated and dropped, so the column default was stored. |
| Agent type update contract | Enforces the same non-negative depth floor as the create contract; the update path has no upper bound. |

Both validators must agree on accept/reject outcomes for the depth field.

### 5. Agent Runtime — guardrail state resolution

| Item | Change |
|---|---|
| Guardrail state builder | Removes the input-type branch that forced a single delegated level; reads the starting depth from the job's recorded depth with the legacy input-data key as fallback, seeding both the tree depth and the delegation depth. |
| Guardrail state model | Unchanged shape. Values supplied now reflect configuration and real chain depth. |
| Task loop context | Maximum depth and starting depth supplied from the agent type configuration and the job's recorded depth instead of constants. |
| Control Center-side task loop | Loop context and its fallback guardrail state both derive from the same resolved agent-type configuration. |
| Act-phase fallback guardrail state | Derived from the loop context's configured maximum, budgets, and depth rather than constants. |
| Act-phase depth-blocked message | States that the configured maximum was reached; no longer asserts a one-level task-agent rule. |

### 6. Agent Runtime — enforcement sites (semantics retained)

| Item | Change |
|---|---|
| Runtime limit check | No semantic change. Blocks when the actual chain depth exceeds the configured maximum; iteration, step, and timeout checks untouched. |
| Task-loop delegation guard | No semantic change. Blocks a delegation when the next hop would exceed the configured maximum (next depth greater than the maximum), and the blocked outcome names that maximum. |
| LangChain delegation tool guard | New pre-dispatch hop check in the Agent Runtime delegation tool wrapper. Before logging `delegation_started` and before the A2A request, computes the current chain depth as the deeper of tree and delegation depth; when `current + 1` exceeds the configured maximum it records a `delegation_depth_blocked` event (target, current, next, max), returns a blocked tool result naming the configured maximum, and does not dispatch, increment delegated steps, or advance depth. |
| Guardrail callback depth check | No semantic change. Reads the configured maximum and the run's current chain depth; block condition remains "greater than". |
| Delegation tool-name resolution | Unchanged. Canonical and legacy prefixes both continue to identify delegation targets. |

### 7. Web UI — configuration inputs

| Item | Change |
|---|---|
| Agent Type form | Maximum attribute removed from the depth input; minimum retained; labels, defaults, and layout unchanged. |
| Agent Properties panel | Same removal; draft composition mapping unchanged. |
| Draft composition / conversational payload mapping | Verified to impose no depth ceiling; no change required. |

### 8. Web UI — execution log delegation card

| Item | Change |
|---|---|
| Direct-child peek filter (new pure helper) | Keeps the existing peek allow-list, additionally excludes delegation lifecycle event types and delegation tool-call / tool-response entries identified by tool name. Pure, synchronous, side-effect free. |
| Delegation card | Uses the helper for the short child progress peek only. Layout, timeline, status chips, and the drill-in action are unchanged. |
| Child log drill-in | Unchanged and unfiltered by the helper, so the child's own log and its own peek still show its delegation events. |

---

## API Changes

| Endpoint | Type | Change |
|---|---|---|
| `GET /internal/data/sessions/{session_id}` | Internal read | Additive: response gains an integer delegation depth field carrying the persisted job value. Existing fields and auth requirements unchanged. |
| `GET /agents/sessions/{session_id}/delegation/status` | Public read | Value semantics only: the maximum-depth field now reports the session agent type's configured maximum instead of a constant. Response shape unchanged. |
| `POST /internal/data/a2a/request` | Internal write | No contract change. Parent-link resolution and child depth derivation confirmed unchanged. |
| `POST /agents/types`, `PUT /agents/types/{id}` (and assistant-managed equivalents) | Public / assistant write | No contract change. Delegation depth validation accepts any non-negative integer; the fixed ceiling is removed. The public REST create path now persists the submitted guardrail values instead of dropping them, and the public REST update path rejects negative depths. Other guardrail bounds unchanged. |
| `GET /agents/sessions/{session_id}/logs`, `GET /agents/sessions/{session_id}/logs/stream` | Public read | No change. Still query a single session only; no recursive or descendant aggregation. |

No endpoints are added or removed.

---

## State Management

No global store, context provider, or new hook is introduced on the frontend.

- **Guardrail runtime state.** `RuntimeGuardrailState` remains the single carrier of iteration, depth, step, timeout, and token counters for a run. The only change is provenance: values now come from the resolved guardrail policy plus the job's recorded depth rather than from constants.
- **Task loop context.** The task loop context keeps its existing depth fields; they are seeded from the agent type configuration and the job's recorded depth. No new field is required for the Control Center-side loop because the resolved configuration supplies the maximum.
- **Delegation card peek.** The peek is derived per render. The new pure helper replaces an inline filter so the exclusion rule is testable and has no hidden state. The component keeps its existing fetched-entry state and streamed-entry merge; only the derived projection changes.
- **Child log view.** Deliberately unaffected — the helper is scoped to the parent's peek so the drill-in view keeps its existing state and contents.

---

## Data Access Patterns

| Concern | Pattern |
|---|---|
| Persisted delegation depth | Read by Control Center from the job row and exposed on the internal session payload; enumerated at enqueue from the parent job's depth. No Agent Runtime database access. |
| Configured maximum depth | Read by Control Center from the agent type row for the status API; read by Agent Runtime from the guardrail policy embedded in the execution context it already fetches. |
| Depth enforcement | In-process in Agent Runtime using the resolved guardrail state; one hard-limit check path and one callback path. |
| Execution logs | Control Center queries by a single session identifier in both the snapshot and streaming handlers; the parent's view performs no descendant traversal. |
| Child progress peek | Frontend fetches the direct child's own log via the existing session logs route and filters the projection locally; no server-side aggregation and no additional endpoint. |
| Configuration validation | Control Center validates on agent-type create and update for both direct and assistant-managed writes; the two validators share the same bounds. |

---

## Code Reference Map

| Symbol | Type | Description | File |
|---|---|---|---|
| `SessionResponse` | Pydantic model | Internal session metadata payload; gains the recorded delegation depth field | `backend/app/api/v1/internal/session_data.py` |
| `get_session` | route handler | Internal session lookup; populates the recorded delegation depth from the job | `backend/app/api/v1/internal/session_data.py` |
| `prepare_a2a_request` | route handler | Resolves the parent job link for A2A delegations and enqueues the delegated job | `backend/app/api/v1/internal/session_data.py` |
| `A2ADataRequest` | Pydantic model | A2A preparation request body; unchanged contract | `backend/app/api/v1/internal/session_data.py` |
| `AgentSessionService.enqueue` | method | Creates a job and derives child delegation depth from the parent job | `backend/app/services/agents/session_service.py` |
| `AgentSessionService.get_session` | method | Loads a job with its agent type eagerly for the delegation status handler | `backend/app/services/agents/session_service.py` |
| `DelegationStatusResponse` | Pydantic model | Delegation status payload; maximum-depth semantics change, shape retained | `backend/app/api/v1/agents.py` |
| `get_delegation_status` | route handler | Returns the session agent type's configured maximum depth | `backend/app/api/v1/agents.py` |
| `create_agent_type` | route handler | Agent type creation; persists every submitted guardrail value (including the configured maximum depth) on the new row | `backend/app/api/v1/agents.py` |
| `get_pending_intervention` | route handler | Returns pending interventions for direct child sessions only; scope unchanged | `backend/app/api/v1/agents.py` |
| `get_session_execution_logs` | route handler | Single-session execution log query; unchanged | `backend/app/api/v1/agents.py` |
| `stream_session_execution_logs` | route handler | Single-session execution log stream; unchanged | `backend/app/api/v1/agents.py` |
| `_validate_guardrail_contract` | function | REST guardrail contract validation; delegation-depth ceiling removed, floor retained | `backend/app/schemas/agents.py` |
| `_MAX_MAX_DELEGATION_DEPTH` (removed) | module constant (deleted) | Former delegation-depth ceiling; removed entirely from the validation path | `backend/app/schemas/agents.py` |
| `_MIN_MAX_DELEGATION_DEPTH` | module constant | Non-negative delegation-depth floor; retained | `backend/app/schemas/agents.py` |
| `AgentTypeUpdate._validate_guardrail_delegation_depth` | model validator | Enforces the non-negative delegation-depth floor on the update path; no upper bound | `backend/app/schemas/agents.py` |
| `_validate_guardrails_structured` | function | Assistant-managed guardrail validation mirroring the REST contract | `backend/app/api/v1/internal/management_tools.py` |
| `_MAX_MAX_DELEGATION_DEPTH` (management, removed) | module constant (deleted) | Mirrored delegation-depth ceiling; removed entirely from the validation path | `backend/app/api/v1/internal/management_tools.py` |
| `_MIN_MAX_DELEGATION_DEPTH` (management) | module constant | Mirrored non-negative floor; retained | `backend/app/api/v1/internal/management_tools.py` |
| `_GUARDRAIL_FIELDS` | module constant | Assistant tool-schema field descriptions; depth description loses its numeric ceiling | `backend/app/services/agents/system_tool_registry.py` |
| `get_agent_context` | route handler | Assembles the guardrail policy, including the configured maximum delegation depth | `backend/app/api/v1/internal/agent_data.py` |
| `AgentRuntimeExecutor` | class | Agent Runtime execution orchestration | `backend/app/services/agents/runtime_executor.py` |
| `_resolve_starting_delegation_depth` | function | Resolves a run's starting chain depth (recorded job depth first, legacy input key fallback) | `backend/app/services/agents/runtime_executor.py` |
| `_build_guardrail_state` | method | Resolves guardrail limits and the run's starting depth; input-type override removed | `backend/app/services/agents/runtime_executor.py` |
| `_build_agent_type_guardrail_state` | method | Resolves guardrail state from the agent type's configured profile + job depth (CC-side task loop context and fallback) | `backend/app/services/agents/runtime_executor.py` |
| `_check_runtime_limits_or_raise` | method | Hard limit enforcement; compares the configured maximum with the deepest known chain depth | `backend/app/services/agents/runtime_executor.py` |
| `_run_task_loop` | method | Control Center-side task loop; context and fallback guardrail state seeded from the agent type | `backend/app/services/agents/runtime_executor.py` |
| `_run_task_loop_ar` | method | Agent Runtime task loop; consumes the resolved guardrail state | `backend/app/services/agents/runtime_executor.py` |
| `_act` | method | Tool dispatch phase, including the delegation depth guard and blocked result | `backend/app/services/agents/runtime_executor.py` |
| `_extract_agent_delegation_target` | function | Identifies delegation targets from canonical and legacy tool-name prefixes | `backend/app/services/agents/runtime_executor.py` |
| `_make_delegation_tool` | function | AR delegation tool builder; runs the pre-dispatch depth-hop guard (block, log, return blocked result) before any A2A dispatch | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `_guardrail_depth` | function | Reads an integer depth attribute from a guardrail state (0 when absent) for the hop guard | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `RuntimeGuardrailState` | dataclass | Carries iteration, depth, step, timeout, and token limits and counters | `backend/app/services/agents/guardrails.py` |
| `PLATFORM_DEFAULT_MAX_DELEGATION_DEPTH` | module constant | Platform default (3) applied only when a configured depth is absent; never a cap | `backend/app/services/agents/guardrails.py` |
| `PLATFORM_DEFAULT_MAX_ITERATIONS`, `PLATFORM_DEFAULT_MAX_DELEGATED_STEPS`, `PLATFORM_DEFAULT_EXECUTION_TIMEOUT_SECONDS` | module constants | Sibling platform defaults (10 / 20 / 300) used when a caller builds guardrail state without a resolved policy snapshot | `backend/app/services/agents/guardrails.py` |
| `TaskAgentLoop` | dataclass | Task execution loop context with depth, maximum depth, and tree depth | `backend/app/services/agents/agent_loop.py` |
| `GuardrailCallback` | class | Runtime guardrail callback applied on model and tool activity | `backend/app/services/agents/guardrail_callback.py` |
| `_check_delegation_depth` | method | Delegation depth guard callback check; compares the configured maximum with the deepest known chain depth | `backend/app/services/agents/guardrail_callback.py` |
| `ControlCenterDataClient.get_session` | method | Fetches the internal session payload for a run; mapping result, no client change | `backend/app/agent_runtime/data_client.py` |
| `AgentJob` | ORM model | Job row carrying the parent link and the recorded delegation depth | `backend/app/db/models/agents.py` |
| `AgentType` | ORM model | Agent type row carrying the configured maximum delegation depth | `backend/app/db/models/agents.py` |
| `WorkingStepsPanel` | component | Renders working steps, including the delegation card and its progress peek | `frontend/src/components/executions/WorkingStepsPanel.tsx` |
| `DIRECT_CHILD_PEEK_EVENT_TYPES` | constant | Allow-list of event types surfaced in the parent's direct-child peek | `frontend/src/services/delegationPeek.ts` |
| `DELEGATION_LIFECYCLE_EVENT_TYPES` | constant | Delegation lifecycle event types never surfaced in a parent's peek | `frontend/src/services/delegationPeek.ts` |
| `isDelegationToolName` | function | Detect canonical `agent____<slug>` / legacy `agent__<slug>` delegation tool names | `frontend/src/services/delegationPeek.ts` |
| `isDelegationToolEntry` | function | Detects delegation tool-call and tool-response entries by tool name | `frontend/src/services/delegationPeek.ts` |
| `isDirectChildPeekEntry` | function | Pure predicate combining the allow-list and the delegation exclusion | `frontend/src/services/delegationPeek.ts` |
| `filterDirectChildPeekEntries` | function | Pure projection returning peek-eligible entries | `frontend/src/services/delegationPeek.ts` |
| `AgentTypeForm` | component | Agent type form containing the Max Delegation Depth input | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentPropertiesSection` | component | Agent panel guardrail inputs including Max Delegation Depth | `frontend/src/components/agents/panel/AgentPropertiesSection.tsx` |
| `LogPresenter` | module | Derives guardrail usage, including current and maximum delegation depth, from log entries | `frontend/src/services/LogPresenter.ts` |
| `useSessionExecutionLogStream` | hook | Streams the direct child's live log entries feeding the peek | `frontend/src/hooks/useSessionExecutionLogStream.ts` |
| `ExecutionLogEntry` | type | Frontend log entry shape consumed by the peek filter | `frontend/src/types/index.ts` |
| `test_delegation_depth_guard` | test module | Guardrail state resolution and depth-block behaviour tests; updated | `backend/tests/unit/test_delegation_depth_guard.py` |
| `test_agent_runtime_executor` | test module | Executor default, guardrail state, and agent-type-config resolution tests; updated | `backend/tests/unit/test_agent_runtime_executor.py` |
| `test_guardrail_callback` | test module | Depth check semantics tests; updated | `backend/tests/unit/test_guardrail_callback.py` |
| `test_conversation_intervention_turns` | test module | Intervention depth field tests; unaffected (no constant encoded) | `backend/tests/unit/test_conversation_intervention_turns.py` |
| `test_agent_schemas` | test module | Guardrail validation bound tests; extended for the removed ceiling and the `AgentTypeUpdate` non-negative floor | `backend/tests/unit/test_agent_schemas.py` |
| `test_delegation_depth_status_api` | test module | Internal session payload depth, delegation-status configured maximum, and direct-child intervention scope; new | `backend/tests/unit/test_delegation_depth_status_api.py` |
| `test_management_tool_full_field_parity` | test module | Assistant-managed field parity; extended for depth acceptance | `backend/tests/integration/test_management_tool_full_field_parity.py` |
| `test_agent_type_rest_create_guardrails` | test module | REST create persists the submitted guardrail values (depth 64 read back from the stored row); update accepts 1000 and rejects −1 without changing the stored value; new | `backend/tests/integration/test_agent_type_rest_create_guardrails.py` |
| `WorkingStepsPanel.test` | test module | Delegation card peek and drill-in behaviour; extended | `frontend/src/__tests__/WorkingStepsPanel.test.tsx` |
| `delegationPeek.test` | test module | Unit tests for the pure peek filter | `frontend/src/__tests__/delegationPeek.test.ts` |
| `delegationDepthInputs.test` | test module | Configuration input tests for depth above the former ceiling | `frontend/src/__tests__/delegationDepthInputs.test.tsx` |
| `LogPresenter.test` | test module | Derived maximum delegation depth comes from logged configuration values | `frontend/src/__tests__/LogPresenter.test.ts` |
| `agentTypeToDraftComposition.test` | test module | Draft composition imposes no delegation depth ceiling | `frontend/src/__tests__/agentTypeToDraftComposition.test.ts` |
| `delegation-depth-scoping.spec` | test module | Mocked E2E: depth above 32 submitted from both configuration inputs, parent log/peek scoping with drill-in, and 3-vs-7 status display; new | `e2e/tests/delegation-depth-scoping.spec.ts` |
| `delegation-depth-scoping.real-backend.spec` | test module | Live-stack E2E: REST create persists depth 64, update to 1000 persists, negative rejected; new | `e2e/tests/delegation-depth-scoping.real-backend.spec.ts` |
