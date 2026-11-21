# Module: agents — Plans and Optimization

> Part of the [agents hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

Plan work has two layers:

1. **Base implementation plan** — high-level steps and topology authored by an LLM, persisted on `AgentPlan`. Generated **only** on an explicit request (`POST /agents/types/{id}/regenerate-plan`), never as a side effect of saving an agent.
2. **Optimization** — a separate action that authors a verified `OptimizedImplementationPlan` (and optionally promotes scripts), then serves it ahead of the base plan. Optimization exists in two forms that share one mission and one plan lifecycle:
   - a **one-shot command** execution (`POST /agents/sessions/optimize` → `__command: optimize-and-verify`), and
   - an **optimization-mode conversation** (`POST /conversations/optimization`) on the subject agent type itself.

There is no "Run with optimization" run mode: a normal Run always executes the agent's own instructions and never optimizes.

**Verification is replay-only.** `execute_script` replays the selected reference execution's input and recorded tool responses; a miss is a terminal stop, never a live call. The only live work is an explicit, operator-approved, single-use **live test of one saved script version** inside an optimization conversation.

**Authoring model.** Plan generation and optimization resolve one tenant-level authoring model (`workflow_generation_model_id`). There is no fallback to the agent's runtime model or an arbitrary config; an unset/disabled selection produces a structured "not configured / re-select" error and writes nothing. The optimization **conversation** additionally supports a dedicated `optimizer_model_id` that inherits the authoring model when unset.

---

## Base plan generation

| Aspect | Behaviour |
|--------|-----------|
| Trigger | `POST /agents/types/{type_id}/regenerate-plan` only |
| Preconditions | Non-conversational agent **and** a usable authoring model; checked before retiring serving versions; failure → `412 plan_generation_unavailable` with `reason_code`, nothing written |
| Input | Agent context (instructions, role, own bindings, or the full role graph when unbound) |
| Output | Ordered `plan_steps` + deterministic `nodes`/`edges` topology, upserted into `AgentPlan` |
| Failure | `generation_status = "failed"` + `generation_error`, preserving the last successful steps/topology/hash/`generated_at` |
| Step typing | `processing` plus `sop_invocation` / `skill_invocation` / `tool_call` / `agent_delegation` only when the step references an existing entity; otherwise reclassified to `processing`. Optional explicit references and `parent_order` are preserved |
| Consumption | `AgentRuntimeLoader` injects the plan into the running agent's system context; graceful degradation when absent |

---

## Optimize action and gate

`GET /agents/types/{type_id}/optimization-gate` computes, read-only, in this precedence order:

1. `is_conversational` — conversational agents cannot use the one-shot action.
2. `workflow_model_configured` / `workflow_model_id` — authoring model usable in this workspace (a stored-but-disabled id is visible with `configured = false`).
3. `successful_executions` — at least one completed normal run.

Derived flags: `can_generate_plan = workflow_model_configured && !is_conversational`; `can_optimize = can_generate_plan && successful_executions > 0`; `reason_code` names the first unmet precondition. The trigger re-checks server-side and returns `412 {error: "optimize_gate_unmet", reason_code, reason}`; nothing is created, counted or dispatched when blocked. The same helper (`_resolve_launch_preflight`) is shared with a normal Run for provenance, quota and recursion checks.

Failure codes: `conversational_agent`, `authoring_model_not_configured`, `authoring_model_not_enabled`, `no_successful_execution`, plus `authoring_model_unavailable` (race at execution time, fails closed).

---

## `optimize-and-verify` command

A command execution whose mission replaces the agent's business instruction. It receives the optimization system tools and a dedicated token budget.

- **Pre-authoring self-reflection** in a fixed order: `get_scripts` → `get_execution_log` (including failures) → `get_optimized_implementation_plan` → `get_implementation_plan`.
- **Skip when healthy**: re-author only for a missing `ready` plan, failing scripts, repeated execution errors or a changed base plan.
- **Replay verification**: use the reference `input`/`input_schema` keys exactly; never invent a tool call the reference did not make; `execute_script` never calls live tools or mutates data.
- **Bounded stop**: on terminal failure call `generate_optimized_plan` with `status: "needs_feedback"` and a concise `error` reason (persisted and shown to the user).
- **Final answer**: the final message is the business result, not meta-commentary.
- **Repeat guard**: the identical-tool-call guard is enabled for command/optimization runs (`guardrail_repeated_tool_call`).

`COMMAND_MAX_ITERATIONS` / `COMMAND_TOKEN_BUDGET` / `MAX_SCRIPT_ATTEMPTS` bound the run.

---

## Optimized plan lifecycle

| Status | Meaning | Serving |
|--------|---------|---------|
| `generating` | Authoring/verification in progress | Not served |
| `ready` | Authored and verified | Served ahead of the base plan while fresh; scripts may be compiled |
| `needs_feedback` | Authoring stopped and needs human input; `error` holds the reason | Not served |
| `failed` | Authoring/generation failure; `error` holds the reason | Not served |
| `requires_fix` | A later execution fell back to the LLM because of a script from this plan | Not served (`get_fresh_optimized_plan` serves only `ready`) |
| `retired` | Explicitly retired by the operator | Not served; row kept for reference |

**Feedback.** `feedback_comments` is an append-only JSON list. Manual entries carry `source: "manual"`; execution-derived entries carry `source: "execution_derived"` + `source_execution_id` and optionally `source_fallback_event_id`. All entries enter the next authoring prompt.

**Fallback → requires_fix.** When AR reports `fell_back`, `ScriptRegistryService.record_fallback` resolves `script_version_id → ScriptDefinition.source_optimized_plan_id → plan` and, for a live plan, calls `mark_requires_fix` with an execution-derived feedback entry in the same transaction. The Optimized Plan tab surfaces the chip, alert and a re-optimize path that carries the prior plan plus feedback.

**Retire** marks rows `retired` (never deletes); exactly one active record per agent type.

---

## Optimization conversation

An optimization conversation is an ordinary `ConversationSession` whose `agent_type_id` is the subject and whose `channel` is `"optimization"`. No optimizer agent type, identity, role or binding is seeded; the conversation runs with exactly the subject agent type's identity, role, model bindings and tool grants.

| Contract | Behaviour |
|----------|-----------|
| Creation | `POST /conversations/optimization` with `{agent_type_id}` only; typed and conversational subjects accepted; requires `agent::read`. Creation succeeds even when a precondition is missing (availability is returned so the chat can explain) |
| Subject immutability | The subject is set at insert; no update path accepts `agent_type_id` or `channel`; listing filters by channel so optimization and business history never mix |
| Routing | `channel == "optimization"` always dispatches the AR conversational loop, regardless of `input_type`; normal business runs keep their routing; the mode is re-resolved on every turn and on resume |
| Context | The optimization mission replaces the business instruction/SOP/skill summaries; tools are the inherent optimization set + `system____request_live_test` (business MCP tools are NOT in the turn tool set); typed output schema is suppressed; identity/role/guardrails are unchanged |
| Scope guard | `require_subject_match` is applied to every optimization-domain handler accepting an `agent_type_id`; a mismatch returns structured `out_of_scope` and writes nothing. Requests without a conversation id keep legacy behaviour |
| Ask/decide | Reuses `human_intervene` → `InterveneRequest` → durable resume; rendered inline in the chat (no queue, no dashboard); an unanswered question starts no work |
| Permissions | `agent::read` to open, `agent::execute` to start work — the same grants the one-shot action needs |

### Live-test approval ledger (single use)

A live test runs **one saved script version end to end** — not individual tool calls. MCP tools are assumed to work; the approval proves the script.

| Step | Behaviour |
|------|-----------|
| Request | `system____request_live_test` with `{script_version_id, reason}`; the tool-call preview is derived server-side from the version's `tools.call(...)` lines; no operation list is supplied |
| Validation | The version exists in the tenant, belongs to the subject, has source, contains at least one literal `tools.call`, and the preview is within the subject's own grants; one pending request per conversation and a per-session approved cap. Refusals: `out_of_scope`, `invalid_script_version`, `script_version_not_found`, `no_tool_calls`, `operation_not_permitted`, `live_test_already_pending`, `live_test_quota_exhausted` |
| Ledger | `OptimizationLiveTestRequest`: status `pending → approved → executed \| failed` (or `denied` / `expired` / `cancelled`), script version FK, preview, script run record, timings |
| Single-use | (1) a conditional transition on execution start; (2) the resume record's idempotency key + applied marker. A re-delivered approval never re-executes |
| Expiry | Decision TTL sweep (startup + periodic) closes overdue rows, cancels the intervention, resolves the pause `unresumable/expired`, appends a bounded-stop turn |
| Execution | CC loads the approved `python_source` + reference input → CH → AR: one sandbox run under the subject's own identity/tenant/grants, hard wall clock; every `tools.call` is a `RuntimeToolCall` carrying the ledger pointer. No LLM is involved |
| Audit | Replay evidence stays `VerificationRun` / `ScriptExecutionRecord`; live evidence is the ledger row + pointered tool calls |

### Replay vs live

Replay is the default and the only verification path (`ReplayToolClient`). The only live route is the approved ledger row above. Denial/expiry keeps the session replay-only and the plan `needs_feedback` with a specific reason. No "always allow", no remembered approval, no automatic second test.

### Optimizer model

Tenant setting `optimizer_model_id` (session tenant; root when tenancy is off). Resolution: explicit and usable → `source: "optimizer"`; unset → the authoring model (`source: "authoring"`); explicit but unusable → `optimizer_model_not_enabled` (no fallback); unset and authoring unusable → `optimizer_model_not_configured`. Never falls back to the agent's runtime model, never rewrites the setting, never persists a resolved value. Used only for the optimization conversation's context and the availability projection.

### Availability and failure surfaces

| Condition | Surface |
|-----------|---------|
| No usable optimizer model | Chat model alert + System Config link; composer disabled; internal context `412 optimizer_model_unavailable` |
| No successful reference execution | Explained; work not started (`no_successful_execution`) |
| No base/optimized plan yet | Informational "nothing to optimize yet — I can start from your description"; conversation opens |
| Conversational agent type | Conversation entry available; only the one-shot action keeps `conversational_agent` |
| Operator lacks permission | Entry disabled; API `403` |
| Turn hang/failure | Structured outcome (heartbeat + per-call timeout + watchdog + iteration budget) |

---

## API Endpoints

### Public (Control Center)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/agents/sessions` | Normal run — no `optimize` field, no plan generation |
| `POST` | `/api/v1/agents/sessions/optimize` | One-shot optimization (gate → preflight → `__command` dispatch) |
| `POST` | `/api/v1/agents/types/{type_id}/regenerate-plan` | The only base-plan generation path (gated) |
| `GET` | `/api/v1/agents/types/{type_id}/optimization-gate` | Gate + conversation availability + optimizer-model state |
| `GET` | `/api/v1/agents/types/{type_id}/optimized-plan` | Plan payload (status, feedback with `source`) |
| `POST` | `/api/v1/agents/types/{type_id}/optimize-plan/feedback` | Manual feedback (`source: "manual"`) |
| `POST` | `/api/v1/agents/types/{type_id}/optimized-plan/retire` | Retire the active plan |
| `GET` / `PUT` | `/api/v1/agents/model-configs/workflow-generation` | Authoring model (tenant-scoped; `422` if not enabled; `null` clears) |
| `GET` / `PUT` | `/api/v1/agents/model-configs/optimizer-model` | Optimizer model (inherit sentinel; `422` if not enabled) |
| `POST` | `/api/v1/conversations/optimization` | Open an optimization conversation |
| `GET` | `/api/v1/conversations/{id}/optimization` | Subject + availability + audit |
| `GET` | `/api/v1/conversations/{id}/live-test-requests` | Live-test ledger |

### Internal

| Route | Purpose |
|-------|---------|
| `GET /internal/data/agent-types/{id}/context?session_id=&conv_session_id=` | Command/optimization model identifiers, mission instruction, optimization tools, `optimization` block; `412` when unusable |
| `POST /internal/conversation/{turn,resume}` | Conversation turn/resume (mode re-resolved) |
| `POST /internal/system-tools/get-execution-log` | Reference execution + text log + `input` + `input_schema` + replay `tool_calls` |
| `POST /internal/system-tools/execute-script` | Replay-only verification |
| `POST /internal/system-tools/generate-optimized-plan` | Authoring allow-list (`ready` / `failed` / `needs_feedback`), persists `error` |
| `POST /internal/system-tools/request-live-test` | Ledger + approval intervention creation |
| `POST /internal/live-test/run` (CH → AR) | One approved-script sandbox run |
| `POST /internal/scripts/fallbacks` | Records the fallback and marks the attributed plan `requires_fix` |
| `GET /internal/scripts/optimized-plan` | Fresh `ready` plan only |
| `WebSocket chat` | `chat_error` codes: `optimizer_model_not_configured` / `_not_enabled`, `optimization_out_of_scope`, `optimization_permission_denied`; `chat_blocked` while a decision is pending; `live_test` block on `intervene_request`; `live_test_result` chunk |

---

## Frontend

- **Optimized Plan tab** — compact entry (optimizer model + "Talk to optimizer" + help), plan status/feedback, `requires_fix` alert + auto feedback + re-optimize with bounded auto-refresh, `needs_feedback` "Optimization needs your input" warning with blocker + replay-only note, absent state opens the conversation, retire states.
- **Optimization chat** — `ConversationDialog` in optimization mode: subject name + mode chip (identity parity as a tooltip), `OptimizationSessionBar` (collapsed "what ran in this session"), model alert, inline `OptimizerAskCard` / `LiveTestApprovalCard`, `OptimizerActivityBlock`, `OptimizerAuditBlock`; plan/ledger invalidation when a turn settles.
- **Plan generation** — Implementation Plan tab owns an explicit **Generate plan** action with empty / blocked (reason + System Config shortcut) / stale states; hidden for conversational agents. Saving an agent generates nothing.
- **System Config** — authoring-model section (three uses, workspace scope, advisory larger-model recommendation, unset/stale reminder) and optimizer-model section (conversation-only explanation, inherit-from-authoring option, catalogue-only options, stale value blocked until re-selected, no-substitution note).

---

## Code Reference Map

### Data model and migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentPlan` / `AgentPlanStatus` | model / enum | Base plan persistence (`pending` / `success` / `failed`), `plan_steps`, `topology`, `generation_status`, `generation_error`, `agent_config_hash` | `backend/app/db/models/agents.py` |
| `OptimizedImplementationPlan` / `OptimizedPlanStatus` | model / enum | Optimized plan lifecycle incl. `requires_fix`; feedback JSON, `error` | `backend/app/db/models/optimized_plan.py` |
| `OptimizationLiveTestRequest` / `OptimizationLiveTestStatus` | model / enum | Live-test ledger (`pending` / `approved` / `executed` / `failed` / `denied` / `expired` / `cancelled`) | `backend/app/db/models/optimization_live_test.py` |
| `RuntimeToolCall.optimization_live_test_request_id` | column | Ledger pointer on live tool calls | `backend/app/db/models/tool_calls.py` |
| `command_prompts` | model | Stored, operator-editable command missions | `backend/app/db/models/command_prompt.py` |
| `requires_fix` migration | migration | Additive enum value for `requires_fix` (no-op downgrade) | `backend/alembic/versions/a7b8c9d0e1f2_optimized_plan_requires_fix_status.py` |
| Live-test ledger migration | migration | Table + enum + nullable ledger pointer | `backend/alembic/versions/3d7c2a5940bc_optimization_live_test_requests.py` |
| Live-test script-version migration | migration | Nullable `script_version_id` FK (`SET NULL`) | `backend/alembic/versions/7b1e4c2d9f03_optimization_live_test_script_version.py` |

### Authoring, plans and command

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PlanGenerationService` / `_invoke_llm` / `_enforce_step_types` / `_parse_plan_steps` | class / methods | Explicit base-plan authoring with the authoring model; step typing; preserved last success | `backend/app/services/agents/plan_generation_service.py` |
| `TopologyBuilderService` | class | Binding-filtered graph → deterministic topology | `backend/app/services/agents/topology_builder_service.py` |
| `AgentRuntimeLoader` | class | Injects the saved plan into the agent's context | `backend/app/services/agents/runtime_loader.py` |
| `AuthoringModelState` / `AuthoringModel` / `AuthoringModelNotConfigured` | types / exception | Authoring-model state, resolution and reason codes | `backend/app/services/agents/workflow_generation_settings.py` |
| `get_authoring_model_state` / `require_authoring_model` / `REASON_AUTHORING_MODEL_NOT_CONFIGURED` / `REASON_AUTHORING_MODEL_NOT_ENABLED` | functions / constants | Non-raising and raising resolvers; no fallback branch | `backend/app/services/agents/workflow_generation_settings.py` |
| `get_workflow_generation_model_id` / `set_workflow_generation_model_id` / `adopt_legacy_app_yaml_value` | functions | Tenant setting read/write and one-time legacy adoption | `backend/app/services/agents/workflow_generation_settings.py` |
| `OptimizedPlanService` / `mark_requires_fix` / `_append_feedback_entry` / `add_feedback` / `retire_optimized_plan` | class / methods | Plan persistence, requires-fix marking, feedback sources, retire | `backend/app/services/agents/optimized_plan_service.py` |
| `ScriptRegistryService.record_fallback` / `_flag_optimized_plan_for_fallback` / `_resolve_optimized_artifact_plan` / `get_fresh_optimized_plan` | methods | Fallback attribution and serving predicate | `backend/app/services/script_registry/service.py` |
| `OPTIMIZE_AND_VERIFY_SLUG` / `OPTIMIZE_AND_VERIFY_COMMAND` / `build_command_mission` / `get_command_prompt` / `COMMAND_MAX_ITERATIONS` / `COMMAND_TOKEN_BUDGET` / `MAX_SCRIPT_ATTEMPTS` | constants / functions | Command mission and bounds | `backend/app/services/agents/command_prompts.py` |
| `OptimizationGate` / `get_optimization_gate` / `count_successful_executions` | dataclass / functions | Gate composition and execution count | `backend/app/services/agents/session_service.py` |
| `_recent_normal_jobs` / `_select_reference_job` / `_tool_calls_from_entries` / `_build_reference_transcript` / `_optimized_plan_result` | functions | Reference selection, replay transcript, plan result projection | `backend/app/api/v1/internal/optimization_tools.py` |
| `generate_optimized_plan` / `execute_script` / `get_execution_log` / `get_implementation_plan` (handlers) | endpoints | Authoring allow-list, replay-only verification, reference log, auto-generated base plan | `backend/app/api/v1/internal/optimization_tools.py` |

### Optimization conversation and live test

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `OPTIMIZATION_CHANNEL` / `OptimizationMode` / `resolve_optimization_mode` / `require_subject_match` / `compose_optimization_mission` / `get_optimization_conversation_availability` | module | Mode resolution, subject guard, mission composition, availability | `backend/app/services/agents/optimization_mode.py` |
| `OPTIMIZER_MODEL_KEY` / `OptimizerModelState` / `OptimizerModelNotConfigured` / `get_optimizer_model_state` / `require_optimizer_model` / `get_optimizer_model_id` / `set_optimizer_model_id` | module | Optimizer model resolution and persistence (explicit → authoring) | `backend/app/services/agents/optimizer_model_settings.py` |
| `OptimizationLiveTestService` (`create_request`, `mark_approved`, `mark_denied`, `begin_execution`, `complete_execution`, `build_script_run_record`, `is_overdue`, `mark_expired`, `settle_expired_pause`, `expire_overdue`, `cancel_for_session`, `list_for_session`, `find_replay`, `pending_intervention_summaries`, `session_audit`, `render_script_live_test_reason`) | service | Ledger state machine, script-scoped validation, single-use gate, audit projection | `backend/app/services/agents/optimization_live_test_service.py` |
| `create_optimization` / `_create_session` | methods | Optimization-channel session creation (typed + conversational) | `backend/app/services/conversations/manager.py` |
| `prepare_live_test_decision` / `execute_approved_live_test` / `expire_and_settle_live_test` / `push_live_test_result` | functions | Approval consumption, script run, expiry settlement, result delivery | `backend/app/services/conversations/turn_resolution.py` |
| `LiveTestExpirySweeper` / `sweep_expired_live_tests` | service / function | Periodic + startup expiry sweep | `backend/app/services/conversations/live_test_expiry.py` |
| `extract_tools_call_names` / `preview_entries` | functions | Literal `tools.call` extraction and bounded preview | `backend/app/services/agents/script_tool_names.py` |
| `request-live-test` handler / `_CH_ALLOWLIST` entry | endpoint / constant | Ledger creation + approval intervention; CH allowlist | `backend/app/api/v1/internal/system_tools.py`, `backend/app/api/deps.py` |
| `LangChainRequestLiveTestTool` | class | Model-facing live-test request + interrupt | `backend/app/services/agents/langchain_system_tools.py` |
| `forward_live_test` | method | CC → CH approved-script run dispatch | `backend/app/services/control_center/comm_hub_client.py` |
| `POST /internal/live-test/run` (AR) | endpoint | One approved-script sandbox run with grant pre-check and per-call recording | `backend/app/agent_runtime/api/live_test.py` |
| `POST /internal/live-test/run` (CH) | endpoint | CC → AR relay | `backend/app/communication_hub/api/internal/live_test_forwarding.py` |
| optimizer model endpoints / gate extension | endpoints / schema | `GET`/`PUT /agents/model-configs/optimizer-model`; `OptimizationGateRead` additions | `backend/app/api/v1/agents.py`, `backend/app/schemas/agents.py` |
| `OptimizationConversationCreate` / `OptimizationConversationRead` / `OptimizationConversationDetailRead` / `OptimizationSubjectRead` / `OptimizationAvailabilityRead` / `OptimizationAuditRead` / `OptimizerModelStateRead` / `OptimizerModelOptionRead` / `OptimizerModelConfigRead` / `OptimizerModelConfigUpdate` / `LiveTestRequestRead` / `LiveTestOperationRead` / `LiveTestDecisionRead` | schemas | Optimizer wire contracts | `backend/app/schemas/optimizer.py` |
| `InterveneRequestRead.live_test` / `LiveTestApprovalSummary` | schema additions | Reconnect re-surfacing of a pending live-test approval | `backend/app/schemas/intervene.py` |
| `create_optimization_conversation` / `get_optimization_conversation` / `list_live_test_requests` | endpoints | Optimization-channel public routes | `backend/app/api/v1/conversations.py` |

### Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentOptimizedPlanTab` | component | Entry, status/feedback, requires-fix/re-optimize, needs-feedback, retire; mounts the optimizer dialog once | `frontend/src/components/agents/AgentOptimizedPlanTab.tsx` |
| `AgentOptimizeAction` | component | One-shot Optimize trigger with localized gate reason | `frontend/src/components/agents/AgentOptimizeAction.tsx` |
| `OptimizationHelpDialog` / `PlanStepTree` | components | Interaction help; shared step tree | `frontend/src/components/agents/OptimizationHelpDialog.tsx`, `PlanStepTree.tsx` |
| `AgentPlanContent` / `AgentTypeDetailsDialog` / `AgentJobLaunchDialog` | components | Plan tab/actions, explicit Generate plan, execution-only launch | `frontend/src/components/agents/AgentPlanContent.tsx`, `AgentTypeDetailsDialog.tsx`, `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| `ConversationDialog` (optimization mode) | component | Mode chip, model alert, ask/approval cards, activity, ledger invalidation | `frontend/src/components/agents/ConversationDialog.tsx` |
| `OptimizationSessionBar` / `LiveTestApprovalCard` / `OptimizerAskCard` / `OptimizerActivityBlock` / `OptimizerAuditBlock` / `OptimizerModelAlert` | components | Optimizer chat chrome | `frontend/src/components/optimizer/` |
| `useOptimizationConversation` / `useOptimizerModelConfig` / `useOptimizationGate` / `useChatSession` | hooks | Session/ledger, model config, gate, live-test parsing | `frontend/src/hooks/useOptimizationConversation.ts`, `useOptimizerModelConfig.ts`, `useOptimizationGate.ts`, `useChatSession.ts` |
| `SystemConfigPage` | page | Authoring + optimizer model sections | `frontend/src/pages/system/SystemConfigPage.tsx` |
| `errorUtils` | functions | `extractOptimizeGateFailure`, `extractPlanGenerationReason`, `extractOptimizerRefusal`, reason/chat-error predicates | `frontend/src/utils/errorUtils.ts` |
| `OptimizationConversation(Detail)` / `OptimizationAvailability` / `OptimizationAudit` / `OptimizerModelConfig` / `LiveTestRequest` / `ScriptRunRecord` / `LiveTestApprovalSummary` / `LiveTestCardState` | types | Optimizer frontend contracts | `frontend/src/types/index.ts` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_plan_generation_service` | unit test | Authoring-model resolution, no fallback, not-configured writes nothing, failure preserves last plan, step typing/parent order | `backend/tests/unit/services/test_plan_generation_service.py` |
| `test_workflow_generation_settings` | unit test | Authoring state derivation, tenant scoping, reason codes | `backend/tests/unit/services/test_workflow_generation_settings.py` |
| `test_agent_types_plan` | integration test | Regenerate-plan gating, success path, no implicit generation | `backend/tests/integration/api/test_agent_types_plan.py` |
| `test_optimization_gate` | test | Extended gate payload, precedence, trigger `412` per reason code | `backend/tests/test_optimization_gate.py` |
| `test_internal_agent_context_authoring_model` | test | Command-run context returns the authoring model; normal run returns the agent model; fail closed | `backend/tests/test_internal_agent_context_authoring_model.py` |
| `test_optimized_plan` | test | Reference transcript, replay-only `execute_script`, requires-fix, feedback tagging, payload | `backend/tests/test_optimized_plan.py` |
| `test_optimized_plan_requires_fix_migration` / `test_optimization_live_test_migration` | tests | Enum/ledger migrations (single additive head, reversible) | `backend/tests/test_optimized_plan_requires_fix_migration.py`, `backend/tests/test_optimization_live_test_migration.py` |
| `test_optimization_mode_context` / `test_optimization_mode_routing` / `test_optimization_subject_guard` / `test_optimization_conversation_api` | tests | Mode context, routing, subject guard, conversation API | `backend/tests/` |
| `test_optimizer_model_settings` / `test_optimizer_model_config_api` | tests | Explicit/authoring/stale derivation and API | `backend/tests/unit/services/test_optimizer_model_settings.py`, `backend/tests/test_optimizer_model_config_api.py` |
| `test_optimization_live_test_ledger` / `test_optimization_live_test_runner` / `test_live_test_execute` / `test_live_test_forwarding` / `test_turn_resolution_live_test` | tests | Ledger validations, run dispatch, AR execution, CH forwarding, approve→execute→resume ordering | `backend/tests/` |
| `test_tenant_resume_ttl_setting` | test | Tenant resume window (activity/pause) | `backend/tests/unit/test_tenant_resume_ttl_setting.py` |
| `AgentOptimizedPlanTab.test` / `AgentOptimizedPlanTab.optimizerEntry.test` / `AgentTypeDetailsDialog.test` / `AgentSessionLaunchDialog.test` | frontend tests | Plan tab states, optimizer entry, generate-plan states, execution-only Run | `frontend/src/__tests__/` |
| `OptimizerChatDialog.test` / `OptimizerPanels.test` / `LiveTestApprovalCard.test` / `OptimizerAskCard.test` / `SystemConfigPage.optimizer-model.test` / `useOptimizationConversation.test` / `useOptimizerModelConfig.test` / `errorUtils.optimizer.test` / `optimizerI18n.test` | frontend tests | Optimizer surface and hooks | `frontend/src/__tests__/` |
| `agent-optimize-gate.spec.ts` / `agent-optimize-requires-fix.spec.ts` / `agent-plan-mode.spec.ts` / `agent-optimizer-conversation.spec.ts` / `agent-optimizer-live-test-approval.spec.ts` / `agent-optimizer-model-config.spec.ts` / `agent-optimizer.real-backend.spec.ts` | E2E tests | Gate, self-healing, explicit plan mode, optimizer conversation/approval/model config | `e2e/tests/` |
