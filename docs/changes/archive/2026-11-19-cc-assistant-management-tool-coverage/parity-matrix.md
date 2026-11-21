# Parity Matrix: CC Assistant Management Tools vs Web UI

Baseline: Pydantic write schemas (`backend/app/schemas/agents.py`, `scheduling.py`, `data_types.py`, `mcp_hub.py`, `skills.py`) + REST endpoints in `backend/app/api/v1/` = **UI-supported**. Current state of `backend/app/api/v1/internal/management_tools.py` (`_build_create`, `_apply_update`, `_SERIALIZERS`) = **tool-accepted**. "Missing" = Phase 2 target.

Legend: ✅ supported · ⚠️ partial · ❌ missing · 🔒 excluded by design (never accepted / never echoed).

## 1. skill

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ | ✅ | ✅ | ✅ (top-level arg) | — |
| description | ✅ | ✅ | ✅ | ✅ | — |
| instructions | ✅ | ✅ | ✅ | ✅ | — |
| is_active | ✅ (via update schema) | ✅ | ✅ | ✅ | — |
| tool_ids / tool_names (bindings) | ✅ | ✅ | ✅ (additive) | ✅ (additive) | — |

Read parity: serializer covers id/name/description/instructions/is_active/is_system + `tool_bindings`. **Parity: complete.** Remaining work: structured errors only.

## 2. sop

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ | ✅ | ✅ | ✅ | — |
| description | ✅ | ✅ | ✅ | ✅ | — |
| instructions | ✅ | ✅ | ✅ | ✅ | — |
| is_active | ✅ | ✅ | ✅ (accepted in create data, default true) | ✅ | — |
| steps (ordered list) | ✅ (step editor) | ✅ (PUT /sops/{id}/steps, full replace) | ✅ (typed `steps` array, id-or-name refs) | ✅ (present = full replacement; absent = untouched) | — |

Nested-structure correction (task 2.7): the Phase-1 audit recorded "0 gaps" for the sop family but missed the nested `steps` structure (skill_invocation / agent_delegation steps). The tool surface now accepts a typed `steps` array on create_sop / update_sop: each step carries `order` (int), `step_type` (enum), per-type REQUIRED `skill_id` / `target_agent_type_id` (id-or-name, tenant-scoped, resolve-before-write), optional `name` / `description` / `step_config`; unknown per-step fields and the skill_id-XOR-target violation return structured errors. Replacement mirrors REST `replace_sop_steps` (delete + recreate in order) and invalidates the shared permission-manager cache for every role bound to the SOP (delegation steps gate role permissions). The serializer (`_serialize_sop`) returns the ordered steps so get_sop / list_sops reflect them.

Read parity: serializer has is_active AND the ordered `steps` list. **Gap: 0.**

## 3. agent_type

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ | ✅ | ✅ | ✅ | — |
| description | ✅ | ✅ | ✅ | ✅ (common) | — |
| identity_id | ✅ | ✅ | ✅ (uuid only) | ❌ | Update missing; create should accept id-or-name |
| role_id | ✅ | ✅ | ✅ (uuid only) | ❌ | Update missing; id-or-name on both |
| model_id | ✅ | ✅ | ✅ | ✅ | — |
| is_active | ✅ | ✅ | ✅ | ✅ | — |
| system_instruction | ✅ | ✅ | ✅ | ✅ | — |
| input_type | ✅ | ✅ | ✅ | ❌ | Update missing |
| input_schema | ✅ | ✅ | ❌ | ❌ | Both missing |
| output_type | ✅ | ✅ | ✅ | ❌ | Update missing |
| output_schema | ✅ | ✅ | ❌ | ❌ | Both missing |
| output_data_type_id | ✅ | ✅ | ❌ | ❌ | Both missing (id-or-name; conversational conflict rule) |
| guardrail_max_iterations | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_max_delegation_depth | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_max_delegated_steps | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_execution_timeout_seconds | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_token_budget | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_token_enforcement_mode | ✅ | ✅ | ❌ | ❌ | Both missing (+ conversational/enforce contract rule) |
| guardrail_token_fallback_mode | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_conversational_token_visibility_mode | ✅ | ✅ | ❌ | ❌ | Both missing |
| guardrail_conversational_continuation_policy | ✅ | ✅ | ❌ | ❌ | Both missing |
| skill_bindings / sop_bindings (as skill_ids/sop_ids) | ✅ | ✅ | ✅ (additive) | ✅ (additive) | — (additive semantics preserved; REST uses replace-on-save, tool uses additive merge — deliberate, no-delete invariant) |
| is_system | 🔒 write-ignored by REST | 🔒 | 🔒 | 🔒 | Excluded by design (system types immutable) |

**Special cases:** conversational `input_type=conversation` + `output_data_type_id` → structured error mirroring `AgentTypeCreate._validate_output_data_type`; guardrail contract (`_validate_guardrail_contract` bounds + conversational cannot use `enforce` token mode) must be mirrored on both create and update.

Read parity gaps vs `AgentTypeRead` / UI detail dialog: serializer **missing** `input_schema`, `output_schema`, `output_data_type_id`, `output_data_type_name`, and all 8 guardrail fields. **Gap: 13 write fields + 11 read fields.**

## 4. agent_role

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ | ✅ | ✅ | ✅ | — |
| description | ✅ | ✅ | ✅ | ✅ | — |
| skill_ids (grants) | ✅ | ✅ | ✅ (additive) | ✅ (additive) | — |
| sop_ids (grants) | ✅ | ✅ | ✅ (additive) | ✅ (additive) | — |
| mcp_session_mappings | ✅ (role editor) | ✅ (role editor) | ✅ (additive; nested `{server, session}` id-or-name pairs) | ✅ (additive) | — |

**Nested-mapping audit correction (tasks 2.8/3.6):** the role editor also maps one MCP session per server (`AgentRoleMcpSession`, unique per (role, server)); create/update_agent_role accept `mcp_session_mappings` (additive, resolve-before-write, session-must-belong-to-server, re-mapping a mapped server → structured 409). After explicit mappings, default rules run over the role's effective MCP server set (role skills → skill tool bindings → tools' servers): passthrough session preferred, single active session auto-used, multiple non-passthrough sessions → structured warning in the response (no guessing).

Read parity gap vs `AgentRoleRead` (UI role editor shows granted skills/SOPs + MCP session mappings): serializer **missing** `skill_ids` / `sop_ids` grant id lists and `mcp_session_mappings` (`{server_id, server_name, session_id, session_name, auth_type}` — never credentials). **Write parity complete; read gap: 3 fields.**

## 5. agent_identity

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ (`^[a-z0-9\-]+$`) | ✅ | ✅ (no pattern check) | ✅ (no pattern check) | Pattern validation → structured error |
| identity_type | ✅ | 🔒 (not in update schema) | ✅ | 🔒 | Match REST: not updatable |
| realm_name | ✅ | ✅ | ✅ | ❌ | Update missing |
| realm_username | ✅ | ✅ | ✅ | ❌ | Update missing |
| status | ✅ (enum) | ✅ (enum) | ❌ | ❌ | Both missing (enum-coerced) |
| role assignments | ✅ (separate REST endpoint `POST /identities/{id}/roles`) | ✅ | ❌ | ❌ | Mapped into update_agent_identity as `role_ids` (id-or-name, additive merge, resolve-before-write) |

**Never touched/echoed:** `access_token`, `refresh_token`, `encrypted_refresh_token` and all token-health fields. Read posture fields the UI shows and the serializer misses: `token_expires_at`, `has_refresh_token` (derived boolean — never the token itself). **Write gap: 4 fields (+ pattern validation); read gap: 2 non-sensitive posture fields.**

## 6. model_config

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| display_name | ✅ | ✅ | ✅ (via `name`) | ✅ (via `name` arg only) | Accept `display_name`/rename in update data |
| provider_type | ✅ (required) | ✅ | ✅ (required) | ❌ | Update missing (enum-coerced) |
| api_base_url | ✅ | ✅ | ✅ | ✅ | — |
| api_key | ✅ write-only | ✅ write-only (omit = unchanged) | ❌ | ❌ | Both missing — write-accepted, encrypted at storage (same vault shape as `ModelConfigService`), **never echoed** |
| enabled_models | ✅ | ✅ | ✅ | ✅ | — |
| is_disabled | ✅ (vendor toggle) | ✅ | ✅ | ✅ | — |

Read parity gap vs `ModelConfigRead`: serializer **missing** `has_credentials` (derived boolean from `encrypted_api_key` presence — non-sensitive). **Write gap: 2 fields; read gap: 1 non-sensitive posture field.**

## 7. schedule

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ | ✅ | ✅ | ✅ | — |
| description | ✅ | ✅ | ✅ | ✅ | — |
| cron_expression | ✅ (required) | ✅ | ✅ (required) | ❌ | Update missing + scheduler re-registration |
| payload | ✅ | ✅ | ✅ | ❌ | Update missing |
| target_type | ✅ (required) | 🔒 (not in update schema) | ✅ | 🔒 | Match REST: immutable after create |
| target_id | ✅ (required) | 🔒 | ✅ | 🔒 | Match REST: immutable after create |
| status / is_active | ⚠️ (status is lifecycle-managed, not a form field) | — | — | — | No change (no delete verb; status stays lifecycle-managed) |

Note: the REST `ScheduledJobUpdate` schema itself only supports name/description/cron_expression/payload — that is the UI parity baseline. Read parity: tool serializer missing `scheduler_job_id` (non-sensitive). **Write gap: 2 fields (+ re-registration).**

## 8. data_type

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ | ✅ | ✅ | ✅ | — |
| slug | ✅ (required) | ❌ immutable in REST despite schema field | ✅ (required) | 🔒 excluded | Keep immutable (mirrors REST update path semantics) |
| description | ✅ | ✅ | ✅ (common) | ❌ | Update missing (common `_apply_update` does apply description — confirm; explicitly typed) |
| fields | ✅ (≥1, no dup names) | ✅ (same contract) | ⚠️ (accepted, no ≥1 validation) | ✅ (no contract validation) | Enforce ≥1 field + no duplicate field names, structured error |

Read parity: serializer covers name/slug/description/fields. **Write gap: field-set contract validation (+ description made explicit); slug stays immutable.**

## 9. mcp_server

| Field | UI create | UI update | Tool create | Tool update | Gap |
|---|---|---|---|---|---|
| name | ✅ (`^[a-z0-9\-]+$`) | ✅ | ⚠️ (no pattern) | ✅ | Pattern → structured error |
| slug | ✅ (required, pattern, tenant-unique) | ❌ immutable | ✅ (required) | 🔒 excluded | Keep immutable; slug pattern → structured error |
| description | ✅ | ✅ | ✅ (common) | ✅ (common) | — |
| base_url | ✅ (required) | ✅ | ✅ (required) | ✅ | — |
| oauth_config / status | ⚠️ (in update schema; managed via sessions/sync in UI) | — | 🔒 excluded | 🔒 excluded | Out of scope for this change (credential-bearing / lifecycle-managed; sessions are Phase 3+ registry territory) |

Read parity: serializer returns name/slug/description/base_url/status — non-sensitive posture is correct; `oauth_config` deliberately **not** echoed (encrypted credential material). **Write gap: 0 new fields; pattern validation → structured errors.**

## Special cases (documented invariants)

1. **model_config `api_key`** — write-accepted (create + update), AES-encrypted via the credential vault before storage, **never echoed** in any serializer or error. `has_credentials` boolean is the only posture signal.
2. **agent_identity role assignment** — REST exposes it as a separate `POST /identities/{id}/roles` concern; the tool surface maps it into `update_agent_identity` as `role_ids` with additive-merge semantics (consistent with `IdentityService.assign_roles` which skips duplicates), resolved before write (unknown role id/name → 404, no partial write). Tokens/credentials are never accepted or returned.
3. **Conversational agent types cannot take `output_data_type_id`** — structured error mirroring the REST validator on create and update.
4. **Guardrail contract** — `update_agent_type` must validate the same bounds and the conversational-vs-`enforce` token-mode rule as `_validate_guardrail_contract`.
5. **Additive merge everywhere** — skill/SOP bindings, role grants, skill-tool bindings, and identity role assignments are add-only; existing rows are never silently removed (no delete verb). **Exception (task 2.7): SOP `steps` use FULL-LIST REPLACE on update, mirroring REST `PUT /sops/{id}/steps` — omitted steps are deleted; absent `steps` leaves them untouched.**
6. **Sensitive exclusion** — identity tokens (access/refresh/encrypted), model api keys, MCP oauth credentials never appear in any serializer output; only derived booleans (`has_refresh_token`, `has_credentials`).
7. **Slug immutability** — data_type and mcp_server slugs are create-only (mirrors REST update behavior for mcp_server; REST data_type update schema has a slug field the update path does not meaningfully rebind — tool surface keeps it immutable).
8. **Schedule target immutability** — `target_type`/`target_id` are create-only per the REST update schema; cron/payload updates re-register with the scheduler.

## Pre-Phase-2 missing-field counts (write paths)

| Family | Missing fields (create) | Missing fields (update) | Read gaps |
|---|---|---|---|
| skill | 0 | 0 | 0 |
| sop | 0 (is_active now accepted; nested `steps` found in task 2.7 correction) | 0 | 0 (serializer returns ordered steps) |
| agent_type | 11 (input/output schemas, output_data_type_id, 8 guardrails) | 12 (+identity_id, role_id, input_type, output_type) | 11 |
| agent_role | 0 | 0 | 2 (skill_ids, sop_ids) + mcp_session_mappings (task 2.8 nested-mapping audit correction) |
| agent_identity | 1 (status) | 4 (realm_name, realm_username, status, role_ids) | 2 (token_expires_at, has_refresh_token) |
| model_config | 1 (api_key) | 2 (display_name in data, provider_type, api_key) | 1 (has_credentials) |
| schedule | 0 | 2 (cron_expression, payload) | 1 (scheduler_job_id) |
| data_type | 0 (contract validation only) | 0 (description confirmed via common path) | 0 |
| mcp_server | 0 (pattern validation only) | 0 | 0 |
