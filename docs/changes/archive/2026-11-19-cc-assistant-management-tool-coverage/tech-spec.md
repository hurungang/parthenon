# Tech Spec: CC Assistant Management Tool Coverage

## Technical Overview

The Control Center Assistant manages nine resource families through `cc____<verb>_<resource>` management tools routed Communication Hub → Control Center. Today the CC internal handlers accept only a subset of the fields the web UI forms accept (most visibly: `update_agent_type` cannot set `role_id`, `identity_id`, `input_type`, `output_type`, `output_data_type_id`, I/O schemas, or guardrails; `update_agent_identity` cannot manage role assignments), and validation failures surface as bare 400 strings the assistant cannot self-correct from.

This change closes the gap without altering any flow boundaries:

1. **CC internal handlers** (`backend/app/api/v1/internal/management_tools.py`) accept the full UI-parity field set per family, running every payload through a new shared validator/normalizer that performs typed coercion (enums, tenant-scoped id-or-name FK resolution, required/unknown-field rules) and returns structured actionable error payloads.
2. **The system tool registry** (`backend/app/services/agents/system_tool_registry.py`) replaces the free-form `data` pass-through with typed per-family parameter schemas — generalizing the existing enrichment-function pattern — while preserving every stable `mcp_hub_id`, every parity `(resource_type, action)` pair, and the no-delete-verb invariant.
3. **Confirm-before-write is unchanged**: the assistant still presents the canonical preview (`**<Operation> <Resource>: <Name>**` + `| Field | Value |` table, old → new for updates) and writes only after `human_intervene` approval; rejection or timeout writes nothing.

Hard boundaries respected: only CC touches the database; CH stays forward-only (never signs tenant headers); the `cc` MCP entity remains seeder-managed and immutable; sensitive material (identity tokens, API keys, decrypted credentials) is never echoed in any tool result; no delete verb exists anywhere in the toolset.

## Component Breakdown

| Component | Responsibility | Change |
|---|---|---|
| Management-tools internal handlers | Per-family create/update/list/get execution behind `POST /api/v1/internal/management-tools/{tool_name}`; parity re-authorization per call; sole DB writer | Accept full UI field sets per family; call the new validator before any write; return structured validation errors |
| Payload validator / normalizer (new CC module) | Enum coercion with valid values listed on failure; tenant-scoped id-or-name resolution (resolve-before-write, no partial writes); required-field enforcement; unknown-field rejection; structured error construction (field, problem, remedy) | New; used by every create/update handler |
| Read serializers (`_SERIALIZERS`) | UI-detail-level record rendering; never echo credentials/tokens | Extend to UI-detail parity (guardrails, role assignments, grant lists, output data type name) |
| System tool registry | Single source of truth for tool names, UUIDs, CC endpoint paths, LLM parameter schemas, parity map, skill seeding | Typed per-family create/update schemas replace free-form `data`; richer descriptions; stable UUIDs/parity untouched |
| Schema enrichment helpers | Post-registration in-place schema mutation (agent-type bindings, role grants, skill tool bindings) | Subsumed by the generalized per-family typed schema declaration |
| Assistant meta tools (`invoke_management_tool`, `get_management_tool_schema`, `list_management_tools`) | Progressive tool disclosure; O(1) assistant context; parity re-enforced per wrapped invocation | Unchanged logic; schemas they serve now reflect the typed per-family definitions |
| CH tool routing | Maps bare tool names to CC internal endpoints via the registry endpoint map; forward-only | No change — payload shapes only |
| Confirm-before-write flow | Canonical preview + `human_intervene` approval + timeout/rejection → no write | No change — previews now express the new fields |
| Assistant knowledge corpus + seeder | Platform rules and self-correction guidance for the assistant | Updated guidance: full field sets, structured-error retry strategy |
| Permission engine / parity map | `(resource_type, action)` enforcement per tool invocation against the user's scope | No change — parity pairs preserved exactly |

## API Changes

All changes are to the CC internal management-tools data-plane endpoints (mTLS + signed tenant headers, reached only via CH forwarding). Route paths are unchanged; request payloads and error behavior change.

**Route structure (unchanged):**
- `POST /internal/management-tools/resolve` — establishes tenant context from the OAuth identity; permitted-tool set derivation unchanged.
- `POST /internal/management-tools/{tool_name}` — per-tool execution (`create_*` / `update_*` / `list_*` / `get_*`).
- `POST /internal/management-tools/invoke_management_tool`, `get_management_tool_schema`, `list_management_tools`, `search_assistant_knowledge` — meta tools; dispatch and parity re-enforcement logic unchanged.

**Payload/behavior changes:**

- `create_agent_type` / `update_agent_type` — `data` gains: `identity_id`, `role_id` (id-or-name, tenant-scoped), `input_type`, `input_schema`, `output_type`, `output_schema`, `output_data_type_id` (id-or-name; rejected with a structured error when `input_type` is `conversation`), and the eight guardrail fields (`guardrail_max_iterations`, `guardrail_max_delegation_depth`, `guardrail_max_delegated_steps`, `guardrail_execution_timeout_seconds`, `guardrail_token_budget`, `guardrail_token_enforcement_mode`, `guardrail_token_fallback_mode`, `guardrail_conversational_token_visibility_mode`, `guardrail_conversational_continuation_policy`) with the same contract validation the REST layer enforces; `skill_ids` / `sop_ids` keep additive-merge semantics.
- `create_agent_identity` / `update_agent_identity` — `data` gains `status` (enum-coerced) on both, and `role_ids` on update (id-or-name, additive merge, resolve-before-write, no partial write). Tokens/credentials remain untouched and unexposed.
- `update_agent_role` — `description` plus existing additive `skill_ids` / `sop_ids` grants confirmed and typed in schema.
- `create_model_config` / `update_model_config` — `data` gains `display_name` (via `name`), `provider_type` (enum-coerced, required at create), and optionally `api_key` (write-accepted, encrypted at storage, never echoed); `enabled_models`, `api_base_url`, `is_disabled` already supported and now typed.
- `create_schedule` / `update_schedule` — update gains `cron_expression`, `payload`, `target_type`, `target_id` (id-or-name) with scheduler re-registration on change; create behavior preserved (cron + target required).
- `create_data_type` / `update_data_type` — update gains `description`; `fields` typed as the field-definition list; slug immutable after create (mirrors REST).
- `create_mcp_server` / `update_mcp_server` — unchanged field set, now typed with pattern and required-field errors as structured payloads; slug uniqueness per tenant preserved (409).
- `create_skill` / `update_skill`, `create_sop` / `update_sop` — full field sets already accepted (`name`, `description`, `instructions`, `is_active`, tool/binding enrichment); schemas typed, zero-binding warning behavior preserved.
- All create/update endpoints — validation failures now return a structured error payload (error code, per-field problems, remedy hint including valid enum values or resolution guidance) instead of bare 400 strings; 403/404/409 semantics preserved with the structured shape; existing non-validation error behavior unchanged.
- All list/get endpoints — serializers extended to UI-detail parity (agent types include guardrails and `output_data_type_name`; identities include role assignments; roles include grant id lists; data types include field definitions; MCP servers include non-sensitive posture fields). No credential, token, or secret is ever serialized.

## State Management

**No frontend changes.** The web UI is the parity baseline, not a target of change: no new components, no state stores, no API client updates, no schema files. The assistant's conversational state (session registry, websocket reply delivery, heartbeats/watchdogs) is likewise untouched — only tool payload shapes and handler behavior change.

## Data Access Patterns

- **All database access stays in Control Center** (top-priority rule). Handlers write via SQLAlchemy async session (`get_db` dependency) exactly as today: resolve-before-write lookups (tenant-scoped `SELECT` by id or name), ORM instance mutation/insert, flush/commit, re-read for the serialized result. No raw SQL; no new tables; no migrations (`has_db_changes: false`).
- **CH ↔ CC transport** — CH forwards tool calls to the registry-derived CC endpoint using the internal HTTP client with signed `X-Internal-Tenant-*` headers after `/resolve`; CH never touches the database and never signs from its own state.
- **Assistant-side access** — the assistant (Agent Runtime) reaches data only through CH-routed tools; it holds no identity tokens or credentials and receives serialized, credential-free records.
- **Binding/grant writes** — additive merge via existing binding models (`AgentTypeSkillBinding`, `AgentTypeSopBinding`, `AgentRoleSkill`, `AgentRoleSOP`, `SkillToolBinding`): whole-set resolution before any insert; idempotent re-binding; existing rows never removed (no delete verb).

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SystemTool` | class | Tool descriptor: name, description, parameter schema, CC endpoint path, `mcp_hub_id`, parity pair, category | `backend/app/services/agents/system_tool_registry.py` |
| `SystemToolRegistry` | class | Single source of truth for all system tools: schemas, endpoint map, parity map, UUID set | `backend/app/services/agents/system_tool_registry.py` |
| `SystemToolRegistry.get_parity_map` | method | Management-tool → `(resource_type, action)` parity map (unchanged by this change) | `backend/app/services/agents/system_tool_registry.py` |
| `SystemToolRegistry.get_cc_mcp_hub_entries` | method | CC-entity tool seeding entries (seeder-owned; consumes typed schemas) | `backend/app/services/agents/system_tool_registry.py` |
| `_MANAGEMENT_RESOURCES` | constant | The 9 managed families with per-family resource types and create/update actions | `backend/app/services/agents/system_tool_registry.py` |
| `_MANAGEMENT_DATA_FIELDS` | constant | Per-family typed `data` field declaration (typed/described properties, required-on-create, create-only/update-only splits, additive-merge list fields + merge notes) consumed by the schema applier | `backend/app/services/agents/system_tool_registry.py` |
| `_apply_typed_management_schemas` | function | Generalized replacement for the former `_enrich_agent_type_binding_schemas` / `_enrich_agent_role_grant_schemas` / `_enrich_skill_tool_binding_schemas`: mutates every registered create/update tool in place (stable `mcp_hub_id`s and parity pairs), replaces free-form `data` with the typed declaration (no `additionalProperties` pass-through), and states field set / required-vs-optional / additive-merge semantics in the tool description | `backend/app/services/agents/system_tool_registry.py` |
| `_enum_field` (+ schema builder helpers `_s` / `_slist` / `_objlist` / `_bool_field` / `_obj_field`) | functions | Typed property builders; enum properties embed the exact model value lists (AgentInputType, AgentOutputType, AgentIdentityType/Status, ModelProvider, guardrail modes, JobTargetType) | `backend/app/services/agents/system_tool_registry.py` |
| `_next_management_uuid` | function | Sequential UUID allocator for management tools (never reuse/change deployed ids) | `backend/app/services/agents/system_tool_registry.py` |
| `_register_management_tools` | function | Registers create/update/list/get per family; gains typed per-family parameter schemas | `backend/app/services/agents/system_tool_registry.py` |
| `_enrich_agent_type_binding_schemas` | function | REMOVED in Phase 3.1 — subsumed by `_MANAGEMENT_DATA_FIELDS` + `_apply_typed_management_schemas` | `backend/app/services/agents/system_tool_registry.py` (removed) |
| `_enrich_agent_role_grant_schemas` | function | REMOVED in Phase 3.1 — subsumed (see above) | `backend/app/services/agents/system_tool_registry.py` (removed) |
| `_enrich_skill_tool_binding_schemas` | function | REMOVED in Phase 3.1 — subsumed (see above) | `backend/app/services/agents/system_tool_registry.py` (removed) |
| `_META_MANAGEMENT_TOOL_NAMES` | constant | Progressive-disclosure meta tool names | `backend/app/services/agents/system_tool_registry.py` |
| `router` (management-tools) | router | Data-plane router: mTLS + signed tenant headers, `/{tool_name}` execution | `backend/app/api/v1/internal/management_tools.py` |
| `resolve_router` | router | Control-plane `/resolve` router (mTLS only; establishes tenant context) | `backend/app/api/v1/internal/management_tools.py` |
| `meta_router` | router | Assistant meta-tool endpoints | `backend/app/api/v1/internal/management_tools.py` |
| `execute_management_tool` | function | Per-tool execution entry; parity re-authorization then dispatch | `backend/app/api/v1/internal/management_tools.py` |
| `invoke_management_tool_meta` | function | Wrapper dispatch with per-invocation parity re-enforcement | `backend/app/api/v1/internal/management_tools.py` |
| `get_management_tool_schema_meta` | function | Serves one tool's OpenAI schema on demand | `backend/app/api/v1/internal/management_tools.py` |
| `list_management_tools_meta` | function | Cheap catalog: name + description + required permission | `backend/app/api/v1/internal/management_tools.py` |
| `resolve_management_session` | function | Resolves OAuth user → tenant + permitted tools | `backend/app/api/v1/internal/management_tools.py` |
| `_dispatch` | function | Routes tool name to verb/resource handler | `backend/app/api/v1/internal/management_tools.py` |
| `_build_create` | function | Per-family create constructor; extended to full UI field sets via validator | `backend/app/api/v1/internal/management_tools.py` |
| `_apply_update` | function | Per-family update application; extended to full UI field sets via validator | `backend/app/api/v1/internal/management_tools.py` |
| `_list_resource` / `_get_resource` | functions | Read handlers (cc-entity visibility, tool discovery, binding attachment) | `backend/app/api/v1/internal/management_tools.py` |
| `_bind_agent_role_mcp_sessions` | function | Task 2.8/3.6: applies `mcp_session_mappings` (additive, resolve-before-write, session-belongs-to-server, 409 on re-map) then the default rules over the role's effective MCP server set (passthrough preferred, single-session auto-used, multi-session → structured warning) | `backend/app/api/v1/internal/management_tools.py` |
| `_resolve_mcp_session_for_server` | function | Resolves an MCP session id-or-name scoped to a known server (names are unique per server only) | `backend/app/api/v1/internal/management_tools.py` |
| `_SERIALIZERS` / `_serialize_agent_type` / `_serialize_agent_identity` / `_serialize_agent_role` / `_serialize_model_config` / `_serialize_schedule` / `_serialize_data_type` / `_serialize_mcp_server` / `_serialize_skill` / `_serialize_sop` | functions/constants | Record serializers; extended to UI-detail parity; never echo credentials | `backend/app/api/v1/internal/management_tools.py` |
| `_authorize` | function | Parity authorization against the user's scope (raises 403) | `backend/app/api/v1/internal/management_tools.py` |
| `_cc_permitted` | function | `integration::control_center` entity-view check for cc-entity visibility | `backend/app/api/v1/internal/management_tools.py` |
| `_check_duplicate_name` | function | Tenant-scoped uniqueness probe (409) | `backend/app/api/v1/internal/management_tools.py` |
| `_coerce` | function | Existing enum coercion helper (subsumed by validator, structured errors) | `backend/app/api/v1/internal/management_tools.py` |
| `_parse_uuid` | function | UUID parsing helper | `backend/app/api/v1/internal/management_tools.py` |
| `_resolve_capability_ids` | function | Id-or-name → tenant-scoped UUID resolution for skills/SOPs (resolve-before-write) | `backend/app/api/v1/internal/management_tools.py` |
| `_bind_agent_type_capabilities` | function | Additive-merge skill/SOP binding for agent types | `backend/app/api/v1/internal/management_tools.py` |
| `_bind_agent_role_capabilities` | function | Additive-merge skill/SOP grants for roles | `backend/app/api/v1/internal/management_tools.py` |
| `_bind_skill_tools` / `_resolve_skill_tool_ids` | functions | Skill ↔ MCP tool binding (additive merge, 404 on unknown) | `backend/app/api/v1/internal/management_tools.py` |
| `_attach_skill_tool_bindings` / `_count_skill_bindings` | functions | Skill binding read-side attachment + zero-binding warning support | `backend/app/api/v1/internal/management_tools.py` |
| `ZERO_BINDING_WARNING` | constant | Non-fatal tool-less-skill warning text | `backend/app/api/v1/internal/management_tools.py` |
| `_post_create_side_effects` | function | Schedule → APScheduler registration after create | `backend/app/api/v1/internal/management_tools.py` |
| Management payload validator / normalizer (new) | module | Typed coercion, id-or-name resolution, required/unknown-field rules, structured error builder | `backend/app/services/agents/management_payload.py` (new) |
| `ManagementValidationError` | exception | Structured validation failure (payload: `error` + per-field `problems` [{field, problem, remedy}]) | `backend/app/services/agents/management_payload.py` |
| `Problem` | dataclass | One field-level problem with remedy hint | `backend/app/services/agents/management_payload.py` |
| `ReferenceNotFoundError` | exception | Unknown tenant-scoped FK reference (rendered as structured 404) | `backend/app/services/agents/management_payload.py` |
| `PayloadValidator` (alias of `PayloadValidatorFull`) | class | Enum/bool/int coercion with valid values in errors, slug patterns, required fields, unknown-field rejection, `resolve_fk` / `resolve_fk_list` (tenant-scoped id-or-name) | `backend/app/services/agents/management_payload.py` |
| `parse_uuid` / `is_uuid_shaped` | functions | UUID-shape detection for id-or-name resolution | `backend/app/services/agents/management_payload.py` |
| `_validation_error` / `_reference_error` | functions | Handler-side conversion of validator exceptions to structured HTTP 400 / 404 | `backend/app/api/v1/internal/management_tools.py` |
| `_ALLOWED_CREATE_FIELDS` / `_ALLOWED_UPDATE_FIELDS` | constants | Per-family allowed `data` keys (unknown-field rejection) | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_guardrails_structured` | function | Guardrail contract mirror (bounds + conversational/no-enforce rule) with structured errors | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_conversational_output_conflict` | function | conversation input_type vs output_data_type_id structured error (create + update) | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_data_type_fields` | function | Data type field-set contract (≥1 field, no duplicate names), structured | `backend/app/api/v1/internal/management_tools.py` |
| `_validate_sop_steps` | function | Typed SOP `steps` array validation + resolution (task 2.7): order int, step_type enum, per-type REQUIRED skill_id / target_agent_type_id (id-or-name, tenant-scoped, resolve-before-write), skill_id-XOR-target invariant, unknown per-step fields — structured errors | `backend/app/api/v1/internal/management_tools.py` |
| `_write_sop_steps` | function | SOP steps full-list replace (delete + recreate in order, mirrors REST `replace_sop_steps`) + permission-manager cache invalidation for every `AgentRoleSOP`-bound role | `backend/app/api/v1/internal/management_tools.py` |
| `_coerce_guardrail_fields` | function | Eight guardrail fields coercion from tool data | `backend/app/api/v1/internal/management_tools.py` |
| `_eager_load_options` | function | selectinload options for UI-detail serializers (output_data_type, role grants, identity role assignments, SOP steps) | `backend/app/api/v1/internal/management_tools.py` |
| `_post_update_side_effects` | function | Schedule APScheduler re-registration after cron change | `backend/app/api/v1/internal/management_tools.py` |
| `_route_to_system_tool` | function | CH-side routing of system/cc tools to CC internal endpoints (unchanged) | `backend/app/communication_hub/api/internal/tool_routing.py` |
| `AgentTypeCreate` / `AgentTypeUpdate` | schema classes | UI parity baseline for agent types (field sets + guardrail contract + conversational/typed-output conflict rule) | `backend/app/schemas/agents.py` |
| `AgentIdentityCreate` / `AgentIdentityUpdate` | schema classes | UI parity baseline for agent identities (incl. name pattern, status enum) | `backend/app/schemas/agents.py` |
| `AgentRoleCreate` / `AgentRoleUpdate` / `AgentRoleRead` | schema classes | UI parity baseline for roles incl. grant id lists | `backend/app/schemas/agents.py` |
| `ModelConfigCreate` / `ModelConfigUpdate` | schema classes | UI parity baseline for model configs (api_key write-only, never echoed) | `backend/app/schemas/agents.py` |
| `ScheduledJobCreate` / `ScheduledJobUpdate` | schema classes | UI parity baseline for schedules | `backend/app/schemas/scheduling.py` |
| `DataTypeCreate` / `DataTypeUpdate` | schema classes | UI parity baseline for data types (typed fields) | `backend/app/schemas/data_types.py` |
| `McpServerCreate` / `McpServerUpdate` | schema classes | UI parity baseline for MCP servers (slug patterns) | `backend/app/schemas/mcp_hub.py` |
| `create_agent_type` / `update_agent_type` | endpoints | REST counterparts the handlers mirror for field sets and validation rules | `backend/app/api/v1/agents.py` |
| `update_agent_identity` / `assign_roles_to_identity` | endpoints | REST counterparts for identity updates and identity→role assignment | `backend/app/api/v1/agents.py` |
| `assign_identities_to_role` | endpoint | REST counterpart for role↔identity assignment semantics | `backend/app/api/v1/agents.py` |
| `_validate_guardrail_contract` | function | Guardrail field contract validation the handlers must mirror | `backend/app/schemas/agents.py` |
| `search_knowledge` | function | Assistant knowledge corpus search (meta tool backend); Phase 4 adds `structured-error-self-correction` entry + preview-format coverage for enums/assignments/additive lists; task 4.4 adds `sop-steps-replace-semantics` entry + SOP ordered-step preview rows; task 4.5 adds `role-mcp-session-mappings` entry (session kinds, default rules, warnings, mapping preview rows) | `backend/app/services/agents/assistant_knowledge.py` |
| `_SOP_STEP_TYPES` / `_SOP_STEP_ITEMS` / `_MANAGEMENT_DATA_FIELDS["sop"]["steps"]` | constants/schema | Typed `steps` array schema on create_sop / update_sop (task 3.5): enum step_type, per-type required id-or-name refs, full-list replace semantics in descriptions | `backend/app/services/agents/system_tool_registry.py` |
| Assistant seeder | module | Seeds the per-tenant `cc` MCP entity + assistant agent type; consumes registry entries; Phase 4 extends `ASSISTANT_SYSTEM_INSTRUCTION` (rule 2g structured-error retry; rule 2e preview rows for enums/assignments/'(add)' list rows) and `MANAGEMENT_SKILL_INSTRUCTIONS` | `backend/app/services/agents/assistant_seeder.py` |
| Runtime executor confirmation handling | module | `human_intervene`-based confirm-before-write wait, timeout/rejection → no write (unchanged) | `backend/app/services/agents/runtime_executor.py` |
| `authorize_identity` | dependency/helper | Identity-based authorization used by handler parity checks | `backend/app/api/deps.py` |
| `require_internal_tenant_context` / `require_service_certificate` | dependencies | Internal request guards (signed tenant headers / mTLS) | `backend/app/api/deps.py` |
| Parity/validation/invariant tests (new) | tests | Per-family field parity, structured validation errors, permission parity, registry UUID/parity invariants + typed-schema/enum/additive-merge/scale invariants (`test_management_mcp_tools.py`) + HITL no-write-on-rejection/timeout tests (`test_fix_20261031_133253_conversational_hitl.py`) | `backend/tests/unit/`, `backend/tests/agent_runtime/`, `backend/tests/integration/` |
| Assistant-conversation E2E (new) | test | Full agent-type update via conversation: preview → approval → CH routing → persisted record; rejection → no write | `backend/tests/e2e/` |
