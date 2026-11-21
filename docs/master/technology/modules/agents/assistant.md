# Module: agents — Control Center Assistant

> Part of the [agents hub](tech-spec.md) · [technology documentation](../../README.md).

## Overview

A seeded, system-provided **conversational** `AgentType` (`is_system = true`) that lets a Control Center user perform Agents-menu management work in natural language. The agent runs in Agent Runtime; every management action is a `cc____`-namespaced MCP tool executed by Control Center through Communication Hub. The identity plane is the **user's own OAuth scope** — no elevated service credential — and deletion is never registered.

Two consumers share one tool surface: the in-app assistant (AR acting on the user's cached JWT) and external MCP clients presenting the user's Bearer token.

**Namespace and entity.** `SystemTool.category` (`general` | `management`) drives the namespace: management execution tools and management meta tools are `cc____<bare>`; everything else stays `system____<bare>` (`save_data`, `get_data`, `get_output`, `query_result`, notifications, `human_intervene`, optimization/script tools). Each tenant owns a reserved Control Center `McpServer` (slug `cc`, deterministic uuid5) hosting its `cc____` tool rows; the generic System entity seeds general tools only. The `cc` entity is seeder-managed, immutable, and sessionless.

**Progressive disclosure.** The conversational context loads only a small constant meta-tool set; execution schemas are fetched on demand, keeping the per-turn payload flat. Execution tools remain registered, bound and parity-mapped — the wrapper dispatches to them, `/resolve` evaluates them, and external MCP clients may call them directly.

---

## UI parity (as built)

The assistant's create/update tools accept the same field sets as the web forms, and validation returns structured, actionable errors instead of bare strings.

| Family | Fields accepted by the management tools |
|--------|----------------------------------------|
| Agent types | `identity_id`, `role_id`, `model_id`, `system_instruction`, `input_type` + `input_schema`, `output_type` + `output_schema`, `output_data_type_id`, all guardrail fields, additive `skill_ids` / `sop_ids` |
| Agent identities | `status`, plus additive `role_ids` on update; tokens are never touched or echoed |
| Agent roles | `description`, additive `skill_ids` / `sop_ids`; optional `mcp_session_mappings` |
| Model configs | `name`/`display_name`, `provider_type`, `api_base_url`, `enabled_models`, `is_disabled`, write-only `api_key` |
| Schedules | create requires cron + target; update may change `cron_expression`, `payload`, `target_type`, `target_id` with scheduler re-registration |
| Data types | `description` on update; typed `fields`; slug immutable |
| MCP servers | unchanged field set, typed patterns and required-field errors; per-tenant slug uniqueness (409) |
| Skills / SOPs | full field sets incl. tool bindings and typed SOP `steps` (ordered, `skill_invocation` / `agent_delegation`, full-list replace) |

Every update is validated by a shared payload validator/normalizer: enum coercion (with valid values in the error), tenant-scoped id-or-name foreign-key resolution **before any write**, required/unknown-field rules, and a structured failure contract (`error` + per-field `{field, problem, remedy}`). 403/404/409 semantics are preserved with the structured shape. Read serializers render UI-detail parity (guardrails, role assignments, grant id lists, data-type fields, `output_data_type_name`) and never echo credentials or tokens.

A tool call routed from CH passes the **full** validated field set through to the handler; nothing is silently dropped between the registry schema and the write.

### Hardening shipped with the coverage work

- **Permission model** — role = permission, agent type = visibility (see [core.md](core.md)); consumers (`permission_resolution`, `runtime_executor`, `lifecycle_handler`, agent-data/optimization helpers) all use `calculate_agent_allowed_tools`. The assistant's own knowledge entry now teaches "if the agent can't see a tool, bind the SOP/skill to the AGENT TYPE".
- **`execute_script` description** — teaches combining multiple tool calls into one sandboxed script; the tool stays inherent and its schema is bounded.
- **Conversation execution-log shipping** — conversation turns do not ship execution-log entries (the log table references agent jobs only); the CC endpoint tolerates a conversation-session integrity error, and the executor suppresses shipping for conversation turns.
- **Guardrail usage delivery** — usage is sent the moment the LLM delegation returns, before conversation persistence, so a persistence hang no longer blanks the guardrail panel.
- **A2A polling** — the delegation poll loop re-emits a `waiting` status per poll so the conversation watchdog sees activity and the UI keeps an indicator while a sub-agent legitimately works.
- **Workflow-optimization gating** — the authoring skill and tools are injected only for an `optimize-and-verify` run or an optimization conversation, not for ordinary chat (see [plans-optimization.md](plans-optimization.md)).

---

## Seeding and knowledge

| Component | Description |
|-----------|-------------|
| `AssistantSeeder` | Idempotent, tenant-bound seeding (one commit per tenant): management skill, `cc` entity + tool rows, skill→tool bindings, assistant `AgentType` with its iteration budget. No model is bound — selection is per-tenant configuration |
| Instruction digests | `ASSISTANT_SYSTEM_INSTRUCTION` and `MANAGEMENT_SKILL_INSTRUCTIONS` are diffed on every run so drifted rows refresh |
| Knowledge corpus | Deterministic, no-LLM entries (`{id, topic, keywords, rule_text}`) — generic principles and reference facts only. Additions include `structured-error-self-correction`, `sop-steps-replace-semantics`, `role-mcp-session-mappings` (session kinds, default rules, warnings, preview rows) and `sop-no-raw-tool-mentions` (SOPs must never instruct raw MCP tool calls) |
| Inherent skills | `self-context` and `workflow-optimization`, injected at context-build time with zero binding rows; `execute_script` and self-context tools always available |

---

## Confirm-before-write

Before any create/update the assistant presents the canonical preview — `**<Operation> <Resource>: <Name>**` plus a `| Field | Value |` markdown table (updates show old → new) — and waits for `human_intervene` approval. Rejection or timeout writes nothing. Conversation turns use the durable pause/resume machinery (see [conversations](../conversations/tech-spec.md)); task agents use LangGraph interrupt. The preview format now also covers enum values, assignments and additive list rows ("(add)").

---

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/internal/management-tools/resolve` | Resolve the OAuth user's identity, tenant and permitted `cc____` catalogue |
| `POST` | `/internal/management-tools/{tool_name}` | Per-tool execution (parity re-check then dispatch) |
| `POST` | `/internal/management-tools/invoke_management_tool` | Progressive-disclosure wrapper (per-invocation parity) |
| `POST` | `/internal/management-tools/get_management_tool_schema` | One tool's OpenAI schema on demand |
| `POST` | `/internal/management-tools/list_management_tools` | Cheap catalog (name, description, required permission) |
| `POST` | `/internal/management-tools/search_assistant_knowledge` | Keyword corpus search |
| `GET` / `PUT` | `/agents/model-configs/assistant-model` | Per-tenant assistant model selection (stored on the assistant agent type) |

All internal routes are mTLS + signed tenant headers, reached only through CH. Public routes are JWT-authenticated and tenant-scoped.

---

## Data Access Patterns

- Control Center is the only writer; handlers resolve the triggering user's identity/tenant, run parity authorisation against the user's scope, then read/write through the session-scoped ORM.
- Resolve-before-write: every referenced entity is resolved (tenant-scoped, id or name) before the first mutation, so a bad reference produces no partial write.
- Additive binding/grant semantics: skill/SOP bindings, role grants and skill tool bindings merge; existing rows are never removed (no delete verb exists anywhere in the toolset).
- The assistant (AR) holds no tokens or credentials; it receives serialized, credential-free records.
- `cc` MCP visibility is gated by `integration::control_center`: reads omit the entity, direct reads return 404-without-leak, and tool grants need `manage`.

---

## Code Reference Map

### Seeding and registry

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AssistantSeeder` / `AssistantSeeder.run` | class / method | Per-tenant idempotent seeding and refresh | `backend/app/services/agents/assistant_seeder.py` |
| `ASSISTANT_AGENT_TYPE_NAME` / `MANAGEMENT_SKILL_NAME` / `ASSISTANT_GUARDRAIL_MAX_ITERATIONS` | constants | Stable slugs and iteration budget (24) | `backend/app/services/agents/assistant_seeder.py` |
| `ASSISTANT_SYSTEM_INSTRUCTION` / `MANAGEMENT_SKILL_INSTRUCTIONS` | constants | Instruction digests (principles, discovery, structured-error retry, preview rows) | `backend/app/services/agents/assistant_seeder.py` |
| `_tenant_cc_server_id` / `_tenant_system_server_id` / `_tenant_management_tool_id` | functions | Deterministic uuid5 identities for entities/tools | `backend/app/services/agents/assistant_seeder.py` |
| `_retire_legacy_management_rows` / `_ensure_management_tool_rows` / `_ensure_skill_bindings` / `_seed_skill` / `_seed_agent_type` | methods / functions | Legacy-row retirement and provisioning | `backend/app/services/agents/assistant_seeder.py` |
| `SystemTool` (`category`, `server_slug`, `canonical_name`, `parity`, `is_management_tool`) | class fields/properties | Category-aware namespace and management marker | `backend/app/services/agents/system_tool_registry.py` |
| `get_parity_map` / `get_management_tool_names` / `get_meta_tool_names` / `_META_MANAGEMENT_TOOL_NAMES` / `get_cc_mcp_hub_entries` / `get_mcp_hub_entries` | classmethods / constant | Parity map, tool name sets, meta set, CC entity entries, general-only System entries | `backend/app/services/agents/system_tool_registry.py` |
| `_MANAGEMENT_RESOURCES` | constant | The nine managed families with resource types and actions | `backend/app/services/agents/system_tool_registry.py` |
| `_MANAGEMENT_DATA_FIELDS` / `_SOP_STEP_TYPES` / `_SOP_STEP_ITEMS` | constants | Typed per-family `data` declarations and typed SOP steps | `backend/app/services/agents/system_tool_registry.py` |
| `_apply_typed_management_schemas` | function | Mutates every registered create/update tool in place: typed `data`, no `additionalProperties`, field set/required/additive semantics in the description | `backend/app/services/agents/system_tool_registry.py` |
| `_enum_field` / `_s` / `_slist` / `_objlist` / `_bool_field` / `_obj_field` | functions | Typed property builders (enum values embedded from models) | `backend/app/services/agents/system_tool_registry.py` |
| `_register_management_tools` | function | Registers create/update/list/get per family with stable UUIDs | `backend/app/services/agents/system_tool_registry.py` |
| `invoke_management_tool` / `get_management_tool_schema` / `list_management_tools` / `search_assistant_knowledge` / `human_intervene` | system tools | Always-loaded meta set (execution schemas on demand) | `backend/app/services/agents/system_tool_registry.py` |
| `CC_SERVER_SLUG` / `RESERVED_SERVER_NAMES` / `is_cc_tool` | constants / function | Reserved namespaces including `cc` | `backend/app/services/agents/system_tool_registry.py`, `backend/app/services/agents/tool_naming.py` |

### Validation and handlers

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PayloadValidator` (`PayloadValidatorFull`) | class | Enum/bool/int coercion with valid values, slug patterns, required/unknown-field rejection, tenant-scoped `resolve_fk` / `resolve_fk_list` | `backend/app/services/agents/management_payload.py` |
| `ManagementValidationError` / `Problem` / `ReferenceNotFoundError` | exception / dataclass / exception | Structured failure contract (`error` + per-field problems with remedies) | `backend/app/services/agents/management_payload.py` |
| `parse_uuid` / `is_uuid_shaped` | functions | Id-or-name discrimination | `backend/app/services/agents/management_payload.py` |
| `router` / `resolve_router` / `meta_router` | routers | Data-plane, resolve and meta-tool routers | `backend/app/api/v1/internal/management_tools.py` |
| `execute_management_tool` / `_dispatch` | endpoint / function | Parity re-check then verb/resource dispatch; delete-shaped names declined in-band | `backend/app/api/v1/internal/management_tools.py` |
| `invoke_management_tool_meta` / `get_management_tool_schema_meta` / `list_management_tools_meta` / `search_assistant_knowledge_meta` / `resolve_management_session` | endpoints | Meta surface and session resolution | `backend/app/api/v1/internal/management_tools.py` |
| `_build_create` / `_apply_update` / `_list_resource` / `_get_resource` | functions | Per-family handlers using the validator | `backend/app/api/v1/internal/management_tools.py` |
| `_SERIALIZERS` / `_serialize_agent_type` / `_serialize_agent_identity` / `_serialize_agent_role` / `_serialize_model_config` / `_serialize_schedule` / `_serialize_data_type` / `_serialize_mcp_server` / `_serialize_skill` / `_serialize_sop` | functions / constant | UI-detail serializers (credential-free) | `backend/app/api/v1/internal/management_tools.py` |
| `_authorize` / `_cc_permitted` / `_check_duplicate_name` / `_parse_uuid` / `_coerce` | functions | Permission gate, cc visibility, uniqueness, helpers | `backend/app/api/v1/internal/management_tools.py` |
| `_validation_error` / `_reference_error` | functions | Convert validator exceptions to structured 400/404 | `backend/app/api/v1/internal/management_tools.py` |
| `_ALLOWED_CREATE_FIELDS` / `_ALLOWED_UPDATE_FIELDS` | constants | Per-family allowed keys | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_guardrails_structured` / `_validate_conversational_output_conflict` / `_validate_data_type_fields` / `_coerce_guardrail_fields` | functions | Structured contract mirrors of the REST layer | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_sop_steps` / `_write_sop_steps` | functions | Typed SOP step validation/resolution and full-list replace (+ permission cache invalidation) | `backend/app/api/v1/internal/management_tools.py` |
| `_resolve_capability_ids` / `_bind_agent_type_capabilities` / `_bind_agent_role_capabilities` / `_resolve_skill_tool_ids` / `_bind_skill_tools` / `_attach_skill_tool_bindings` / `_count_skill_bindings` | functions | Additive binding/grant paths and read-side attachment | `backend/app/api/v1/internal/management_tools.py` |
| `_bind_agent_role_mcp_sessions` / `_resolve_mcp_session_for_server` | functions | `mcp_session_mappings` (session belongs to server; passthrough preferred; multi-session warning) | `backend/app/api/v1/internal/management_tools.py` |
| `_eager_load_options` / `_post_create_side_effects` / `_post_update_side_effects` / `ZERO_BINDING_WARNING` | functions / constant | Eager loading, scheduler registration, zero-binding warning | `backend/app/api/v1/internal/management_tools.py` |
| `_route_to_system_tool` (cc acceptance) | function | CH routing treats `cc____` like a system-path call | `backend/app/communication_hub/api/internal/tool_routing.py` |

### Knowledge and runtime context

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `_KNOWLEDGE_ENTRIES` / `search_knowledge` / `get_entry_count` | constant / functions | Corpus and deterministic keyword retrieval | `backend/app/services/agents/assistant_knowledge.py` |
| `InherentSkillDefinition` / `INHERENT_SKILL_DEFINITIONS` / `INHERENT_SKILL_NAMES` | dataclass / constants | Inherent skill set | `backend/app/services/agents/builtin_skills.py` |
| `get_inherent_skill_definitions` / `get_inherent_tool_names` / `get_inherent_skill_summaries` / `get_inherent_canonical_tool_names` | functions | Validated inherent tool/skill accessors | `backend/app/services/agents/builtin_skills.py` |
| `get_inherent_tool_names_for` / `get_inherent_skill_summaries_for` / `get_inherent_canonical_tool_names_for` / `WORKFLOW_OPTIMIZATION_AUTHORING_TOOLS` / `WORKFLOW_OPTIMIZATION_SKILL_NAME` / `REQUEST_LIVE_TEST_TOOL` | functions / constants | Gated inherent set for optimization runs/conversations | `backend/app/services/agents/builtin_skills.py` |
| `get_agent_context` | endpoint | Runtime context: role-less direct-binding branch, meta + inherent tools, `tool_name_map`, guardrail snapshot, model identifiers, optimization mode | `backend/app/api/v1/internal/agent_data.py` |
| `run_conversation_turn` / `_send_to_live_socket` / `cancel_pending_conversation_turn` / `ActiveSessionTracker.unregister` | functions / method | Whole-turn watchdog, send-time live-socket resolution, cancellation | `backend/app/api/ws/chat.py` |
| `ConversationTurnError` / `_conversation_turn_error_from_http_status` / `_conversation_turn_error_from_guardrail_stop` / `_persist_and_surface_turn_error` | class / functions | Structured `chat_error` surfacing and error-turn persistence | `backend/app/api/ws/chat.py` |
| `conversation_llm_timeout_seconds` / `conversation_intervention_timeout_seconds` / `conversation_sessions_default_window_days` | settings | Conversational bounds and listing window | `backend/app/core/config.py` |

### Assistant model and UI

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `get_assistant_model_config` / `set_assistant_model_config` | endpoints | Assistant model selector (options from the tenant catalogue; persisted on the assistant agent type) | `backend/app/api/v1/agents.py` |
| `AssistantModelConfigRead` | schema | `{selected_model_id, options}` | `backend/app/schemas/agents.py` |
| `openAssistant` | handler | Launcher: resolve assistant, force-new or latest active session | `frontend/src/app/AppShell.tsx` |
| Assistant launcher (FAB) | component usage | Floating entry with resolving spinner | `frontend/src/app/AppShell.tsx` |
| `assistantSessionState` | utility module | Force-new-session and ended marking | `frontend/src/utils/assistantSessionState.ts` |
| `useAssistantModelConfig` | hook | Assistant model query | `frontend/src/hooks/useAssistantModelConfig.ts` |
| `ConversationDialog` (assistant) | component | Model guidance alert, disabled input, action bar, sessions view, reconnect | `frontend/src/components/agents/ConversationDialog.tsx` |
| `InlineInterventionDialog` (approval preview) | component | Markdown preview via `ContentRenderer` with expand | `frontend/src/components/conversations/InlineInterventionDialog.tsx` |
| `SystemConfigPage` (assistant section) | page | Assistant and authoring model selectors | `frontend/src/pages/system/SystemConfigPage.tsx` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_assistant_seeder` / `test_assistant_knowledge` | tests | Seeding/refresh, corpus integrity and retrieval | `backend/tests/unit/test_assistant_seeder.py`, `backend/tests/unit/test_assistant_knowledge.py` |
| `test_management_mcp_tools` / `test_management_tool_permission_parity` | tests | Handler contracts, per-family field parity, parity equivalence, registry invariants | `backend/tests/unit/test_management_mcp_tools.py`, `backend/tests/unit/test_management_tool_permission_parity.py` |
| `test_skill_tool_bindings_management` / `test_cc_naming` / `test_cc_seeder_migration` / `test_cc_tool_registry_bridge` | tests | Tool bindings, `cc____` naming, legacy retirement, bridge listing/dispatch | `backend/tests/unit/` |
| `test_oauth_bearer_auth` | test | OAuth plane on `/mcp*` | `backend/tests/unit/test_oauth_bearer_auth.py` |
| `test_inherent_skills` / `test_assistant_tool_context` / `test_confirm_before_write` | tests | Gated inherent set, assistant context, HITL no-write-on-rejection/timeout | `backend/tests/communication_hub/`, `backend/tests/agent_runtime/` |
| `AssistantModelConfigGuidance` / `ControlCenterAssistantEntry` / `AppShell.assistantSession` / `SystemConfigPage.assistant-model` | frontend tests | Model guidance, launcher, session resume, per-tenant selectors | `frontend/src/__tests__/` |
| `control-center-chatbot*.spec.ts` (+ `.real-backend`) | E2E tests | Assistant conversation flows and external MCP parity | `e2e/tests/` |
