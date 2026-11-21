# Module: agents — Tech Spec

> Part of the [technology documentation](../../README.md).

## Overview

The agents module is the central execution layer for AI agents: agent type definitions, a role-governed permission model, first-class OIDC agent identities, model configuration and binding, the asynchronous session queue, the LangChain deep-agent runtime executor, structured outputs, the seeded Control Center Assistant, and the plan/optimization lifecycle.

**Permission model (current).** A role controls **permission**; an agent type controls **visibility**. `AgentPermissionManager.calculate_agent_allowed_tools` resolves the tools visible from the agent type's own bindings (its skills and its SOPs' `skill_invocation` steps) and intersects that set with `calculate_allowed_tools(role_id)` — the role still gates every call, but an agent type cannot reach anything it was not bound to. Agents with no bindings see nothing from the role; only the role-less Control Center Assistant is exempt. `calculate_agent_allowed_agent_types` does the same for delegation targets (`agent_delegation` SOP steps ∩ role-derived targets). Both are cached per agent type and invalidated on role writes and on agent-type binding changes.

**Execution model.** A session (`AgentJob`) is enqueued by `AgentSessionService`, dispatched by `SessionDispatcher`, and executed by `AgentRuntimeExecutor` using the LangChain deep-agent observe-reason-act loop with guardrail and execution-logging callbacks. Agent identities are OIDC principals in a dedicated realm; tokens are AES-256 encrypted and refreshed. `ModelBindingLayer` resolves `AgentType.model_id` to a provider client; plan authoring uses the tenant's **authoring model**, not the agent's runtime model.

**Plan and optimization model.** The base implementation plan is authored with the tenant authoring model on an explicit `regenerate-plan` request only (never as a save side effect) and is high-level. Optimization is a separate action: a one-shot `optimize-and-verify` command execution, plus an optimization-mode **conversation** on the agent type itself. Verification is replay-only; a later execution that falls back to the LLM because of an optimized-artifact script marks the source plan `requires_fix`.

**Admin surface.** The Agent Management Panel (`/agents/panel`) is the single editing surface for agent composition; a single Save maps a client-side draft onto one agent-type PUT.

**Dependency**: `langchain` and `langchain-community`.

---

## Where the detail lives

| Page | Covers |
|------|--------|
| [core.md](core.md) | Agent roles, identities, types, bindings, model configurations, permission/visibility resolution, agent CRUD pages, Agent Management Panel, topology, skill tool-binding editor |
| [execution.md](execution.md) | Session queue and dispatcher, runtime executor, guardrails and model-usage hierarchy, structured outputs and data types, intervene/A2A delegation, runtime monitor |
| [assistant.md](assistant.md) | Seeded Control Center Assistant: `cc____` management toolset at UI parity, payload validator, knowledge corpus, inherent skills, confirm-before-write, assistant model selection, assistant UI |
| [plans-optimization.md](plans-optimization.md) | Authoring model, base-plan generation, Optimize action and gate, `optimize-and-verify`, optimized plan lifecycle (`ready` / `needs_feedback` / `requires_fix`), optimization conversation, live-test approval |

Related modules: [conversations](../conversations/tech-spec.md) (session/turn substrate, activity, resume), [sandboxed-scripting](../sandboxed-scripting/tech-spec.md) (sandbox, script registry, replay), [control-center](../control-center/tech-spec.md) (internal data plane), [identity](../identity/tech-spec.md) (RBAC primitives), [data-types](../data-types/tech-spec.md) (registry UI/API detail).

---

## Component summary

| Area | Responsibility | Page |
|------|----------------|------|
| Roles & identities | Role CRUD, SOP/skill grants, MCP session assignment, identity OAuth lifecycle, role↔identity assignment | [core.md](core.md) |
| Agent types | Base properties, input/output contract, union of own bindings, guardrails, model id | [core.md](core.md) |
| Permission & visibility | Role permission ∩ agent-type visibility; A2A target resolution; per-agent-type caches | [core.md](core.md) |
| Models | Provider catalogue (12 providers, 2 dispatch families), encrypted credentials, model listing, authoring/assistant/optimizer selections | [core.md](core.md) |
| Sessions | Enqueue, dispatch, state transitions, results, execution logs | [execution.md](execution.md) |
| Runtime | LangChain loops, tool wrappers, MCP session context, delegation, guardrails | [execution.md](execution.md) |
| Structured output | Data type validation, typed outputs, `save_data`/`get_data`/`get_output`/`query_result` | [execution.md](execution.md) |
| Assistant | Seeder, management tools, meta tools, knowledge, HITL | [assistant.md](assistant.md) |
| Plans & optimization | Plan authoring, gate, command, optimized plan, optimizer conversation, live test | [plans-optimization.md](plans-optimization.md) |

---

## API route map

| Group | Routes | Page |
|-------|--------|------|
| Roles | `/agents/roles`, `/agents/roles/{id}/{mcp-tools,mcp-sessions,identities,available-mcp-sessions}` | core |
| Identities | `/agents/identities`, `.../roles`, `.../refresh-token`, `.../reauth-url`, `/agents/oauth/callback` | core |
| Types | `/agents/types`, `/agents/types/{id}`, `.../instances`, `/agents/instances/{id}` | core |
| Models | `/agents/model-configs` (+ `/models`), `.../workflow-generation`, `.../assistant-model`, `.../optimizer-model` | core / assistant / plans |
| Sessions | `POST/GET /agents/sessions`, `.../{id}/{result,execution-logs,logs,logs/stream}`, `POST /agents/sessions/optimize` | execution / plans |
| Plans | `/agents/types/{id}/regenerate-plan`, `.../optimization-gate`, `.../optimized-plan`, `.../optimize-plan/feedback`, `.../optimized-plan/retire` | plans |
| Runtime | `/agents/runtime/topology`, `.../topology/stream`, `.../termination`, model-usage/availability endpoints | execution |
| Intervene | `/intervene/requests`, `.../{id}/{respond,cancel}`, `/intervene/metrics` | execution |

All public routes are JWT-authenticated, tenant-scoped, and guarded by `agent::*` resource permissions.

---

## Code Reference Map — cross-cutting

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `parse_tool_name` / `build_tool_name` | functions | Canonical `server____tool` parse/build (reserved `system`, `decision`, `cc`) | `backend/app/services/agents/tool_naming.py` |
| `is_system_tool` / `is_cc_tool` / `RESERVED_SERVER_NAMES` | functions / constants | Namespace predicates and reserved slugs | `backend/app/services/agents/tool_naming.py` |
| `SYSTEM_TOOL_NAMES` / `SYSTEM_TOOL_DISPLAY_NAMES` | constants | Canonical bare system tool names and canonical display names | `backend/app/services/system_tools.py` |
| `SystemTool` | class | Descriptor: name, description, OpenAI schema, category, server slug, canonical name, CC endpoint path, `mcp_hub_id`, parity pair | `backend/app/services/agents/system_tool_registry.py` |
| `SystemToolRegistry` | class | Single source of truth for schemas, endpoint map, parity map, seeded UUIDs, inherent/management sets | `backend/app/services/agents/system_tool_registry.py` |
| `SystemToolRegistry.get_all_schemas` / `get_cc_endpoint_map` / `get_parity_map` | methods | Consumer-facing catalog, routing map and permission parity map | `backend/app/services/agents/system_tool_registry.py` |
| `_next_management_uuid` | function | Sequential UUID allocator for management tools (deployed ids never change) | `backend/app/services/agents/system_tool_registry.py` |
| `app.state.session_tasks` / `app.state.conversation_tasks` | in-flight registries | AR task registries used by termination | `backend/app/agent_runtime/api/execute.py`, `backend/app/agent_runtime/api/conversation.py` |
| `agent_plans` migration | migration | Creates `agent_plans` (unique per agent type, CASCADE) | `backend/alembic/versions/fcbe5b250e08_add_agent_plans.py` |
| `optimized_plan_status_enum` migration | migration | Adds `requires_fix` (additive, no-op downgrade) | `backend/alembic/versions/a7b8c9d0e1f2_optimized_plan_requires_fix_status.py` |
| `conversation_scoped_intervene` migration | migration | Nullable `agent_session_id` + `conversation_session_id` on intervene requests | `backend/alembic/versions/a1c3e5d70427_conversation_scoped_intervene_requests.py` |
| `optimization_live_tests` migration | migration | Ledger table + enum + nullable `runtime_tool_calls.optimization_live_test_request_id` | `backend/alembic/versions/3d7c2a5940bc_optimization_live_test_requests.py` |
| `optimization_live_tests.script_version_id` migration | migration | Nullable FK to `script_versions` (`SET NULL`) | `backend/alembic/versions/7b1e4c2d9f03_optimization_live_test_script_version.py` |
| `AgentPermissionManager` | class | Role permission and agent-type visibility resolution with per-agent-type caches | `backend/app/services/agents/permission_manager.py` |
| `test_permission_manager` | test | Permission/visibility, A2A target and cache-invalidation tests | `backend/tests/unit/test_permission_manager.py` |
