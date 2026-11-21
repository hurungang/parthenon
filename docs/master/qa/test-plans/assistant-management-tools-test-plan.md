# Assistant Management Tools Test Plan

Sibling page of [Control Center Assistant](control-center-assistant-test-plan.md) (hub). This page
covers the assistant's **management-tool surface**; chat entry, session lifecycle, approval
transport, limits and knowledge live on the hub page.

Index: [QA documentation](../../qa/README.md)

## Scope

Covers the management half of the Control Center Assistant (`control-center-chatbot`): the
management actions exposed as MCP tools on the Communication Hub `/mcp` protocol server and
authenticated with the **user's** OAuth/OIDC Bearer token. The same tool surface and permission
resolution serve the in-app chatbot and any external MCP client using the user's credentials.

In scope: management MCP toolset (`cc____` namespace) with exact REST permission parity; role,
agent-type and skill ↔ tool bindings with the zero-binding guard and additive-merge semantics;
typed per-family parameter schemas and structured self-correctable validation; per-resource-family
UI field parity; permission-denial parity for both transports; the no-delete invariant; the Control
Center MCP entity invariants (system-managed, sessionless, permission-gated); OAuth bearer
authentication on `/mcp`; inherent self-context/optimization tool surface; credential-non-echo
reads; tenant-scoped id-or-name resolution.

Out of scope: chat entry, session lifecycle, confirmation-before-write transport, turn supervision
and knowledge corpus ([hub page](control-center-assistant-test-plan.md)), resource deletion (no
delete tool is registered), non-`agent::*` / non-`integration::mcp_hub` modules, and manual form
workflows (unchanged).

---

## Coverage Areas

### 1. Management MCP Toolset (`cc____` namespace)
- Nine resource families × create/update/list/get = 36 management tools with stable reserved ids; every tool declares a stable OpenAI-function schema.
- Canonical names carry the reserved `cc____` slug (`cc____create_skill`, `cc____invoke_management_tool`, …); general system tools stay in `system____` (`system____save_data`, `system____human_intervene`).
- No delete verb is registered anywhere in the catalog; delete-shaped calls are declined in-band without writing.
- Request/response validation: name validation, duplicate identifiers rejected, required-field violations produce structured errors and zero partial writes.
- Meta tools: `list_management_tools`, `get_management_tool_schema`, `invoke_management_tool`, `search_assistant_knowledge`, `human_intervene` are bound to the assistant's management skill (5 meta definitions total on the role-less assistant context).

**Test files:**
- [backend/tests/unit/test_management_mcp_tools.py](../../../../backend/tests/unit/test_management_mcp_tools.py)
- [backend/tests/unit/test_cc_naming.py](../../../../backend/tests/unit/test_cc_naming.py)
- [backend/tests/unit/test_cc_seeder_migration.py](../../../../backend/tests/unit/test_cc_seeder_migration.py)
- [backend/tests/unit/test_cc_tool_registry_bridge.py](../../../../backend/tests/unit/test_cc_tool_registry_bridge.py)
- [backend/tests/integration/test_management_toolset_end_to_end.py](../../../../backend/tests/integration/test_management_toolset_end_to_end.py)

### 2. Permission Parity & Grants
- `get_parity_map()` equals the authoritative REST `require_permission` pairs: skills → `agent::skills`, SOPs → `agent::sops`, schedules → `agent::schedules`, data types → `agent::data_types`, MCP Hub → `integration::mcp_hub`, agent types/roles/identities/model configs → bare `agent`; every type/action is declared in the manifest and the map is deny-by-default.
- `tools/list` is permission-filtered: only tools the authenticated user may invoke are catalogued; no `agent`/`agent::*`/`integration::mcp_hub` grants → management tools absent.
- `tools/call` authorizes against the exact parity pair before dispatch; permitted calls forward `user_sub` (never the identity token); non-permitted calls are denied in-band (OAuth) or raise (`PermissionError` on the API-key path) with no write.
- Role grants: `create_agent_role`/`update_agent_role` write `AgentRoleSkill` / `AgentRoleSOP` rows from ids or tenant-scoped names; update is an additive merge and re-granting is an idempotent no-op; unknown skill returns a structured 404 with `create_skill` guidance and zero partial writes.
- Agent-type grants: `create_agent_type`/`update_agent_type` write `AgentTypeSkillBinding` / `AgentTypeSopBinding` with the same additive-merge semantics and no partial writes on unknown references.
- Skill ↔ tool bindings: `create_skill`/`update_skill` bind by tool names or ids; unknown or foreign-tenant tool → 404 with no partial write; `cc____` tools are bindable; `get_mcp_server` returns its tool list.
- Zero-binding guard: creating/updating a skill with no bound tools succeeds but returns a non-fatal warning; read payloads expose `tool_bindings` (original name, canonical name, server slug/name).
- Single tool surface: the skill editor shows one bound-tool list (picker toggles that list), referenced `cc` tools are read-only locked entries, and table rows show a count with a tooltip.

**Test files:**
- [backend/tests/unit/test_management_tool_permission_parity.py](../../../../backend/tests/unit/test_management_tool_permission_parity.py)
- [backend/tests/unit/test_tool_registry_bridge.py](../../../../backend/tests/unit/test_tool_registry_bridge.py)
- [backend/tests/unit/test_skill_tool_bindings_management.py](../../../../backend/tests/unit/test_skill_tool_bindings_management.py)
- [backend/tests/integration/test_fix_20261031_131030_role_grants.py](../../../../backend/tests/integration/test_fix_20261031_131030_role_grants.py)
- [backend/tests/integration/test_fix_20261031_071721_agent_type_bindings.py](../../../../backend/tests/integration/test_fix_20261031_071721_agent_type_bindings.py)
- [backend/tests/unit/test_fix_20261101_223511_skill_bindings_visibility.py](../../../../backend/tests/unit/test_fix_20261101_223511_skill_bindings_visibility.py)
- [frontend/src/__tests__/SkillEditor.singleSurface.test.tsx](../../../../frontend/src/__tests__/SkillEditor.singleSurface.test.tsx)
- [frontend/src/__tests__/SkillEditor.boundTools.test.tsx](../../../../frontend/src/__tests__/SkillEditor.boundTools.test.tsx)
- [frontend/src/__tests__/SkillsToolBindingsVisibility.test.tsx](../../../../frontend/src/__tests__/SkillsToolBindingsVisibility.test.tsx)

### 3. OAuth-Authenticated MCP Clients (`/mcp`)
- A valid user OAuth/OIDC Bearer token establishes an MCP session bound to that user's resolved identity, permissions and tenant; the identity token is held server-side and never surfaced.
- Missing, non-JWT, invalid, expired, subject-less or unresolvable tokens fail closed with 401 before any catalog is exposed.
- The catalog is the same permission-filtered management catalog the in-app assistant sees — no elevation, no service/agent-realm identity.
- External MCP client parity: an external client using the user's credentials gets identical allow/deny outcomes, no delete tool, and in-band `permission_denied` / `deletion_not_supported` / `out_of_scope` declines.
- Internal dispatch to Control Center carries the signed `X-Internal-Tenant-*` header set (fail-closed without it).

**Test files:**
- [backend/tests/unit/test_oauth_bearer_auth.py](../../../../backend/tests/unit/test_oauth_bearer_auth.py)
- [backend/tests/integration/test_mcp_oauth_bearer_auth.py](../../../../backend/tests/integration/test_mcp_oauth_bearer_auth.py)
- [backend/tests/integration/test_mcp_protocol_server.py](../../../../backend/tests/integration/test_mcp_protocol_server.py)
- [backend/tests/integration/test_internal_tenant_header_failclosed.py](../../../../backend/tests/integration/test_internal_tenant_header_failclosed.py)
- [backend/tests/integration/test_system_tool_endpoints.py](../../../../backend/tests/integration/test_system_tool_endpoints.py)
- [e2e/tests/control-center-chatbot.real-backend.spec.ts](../../../../e2e/tests/control-center-chatbot.real-backend.spec.ts)
- [e2e/tests/control-center-chatbot-mcp.spec.ts](../../../../e2e/tests/control-center-chatbot-mcp.spec.ts)

### 4. Control Center MCP Entity Invariants
- A dedicated per-tenant "Control Center" MCP server row (slug `cc`, deterministic id) holds the management tools and meta tools (41 entries: 36 management + 5 meta) and zero general system tools; `system` and `decision` entities are separate.
- The `cc` entity is **system-managed**: update / delete / sync / OAuth-authorize return a structured 403 (`code=system_managed_integration`) even with `integration::control_center:manage` or wildcard grants; the seeder refreshes drifted fields idempotently without creating rows.
- The `cc` entity is **sessionless**: session create/update/delete return 403 "not supported"; existing-session listing stays 200; non-`cc` session creation is unaffected.
- The entity is **permission-gated** by `integration::control_center` (read + manage): list omits `cc` without read and includes it with read; detail returns 404-without-leak; tool grants on `cc` tools require manage; management-tool reads (`list_mcp_servers` / `get_mcp_server`) respect the same trigger-user permission.
- The MCP Hub UI renders the `cc` row with the system-managed chip, hides edit/delete/sessions and disables sync, while non-`cc` rows keep their actions.
- Tool listing completeness: the default window is not truncated (declared default ≥ 200), paging is lossless and deterministically ordered by `(server_slug, name, id)`, `decision____*` virtual tools are included, and a referenced `cc` tool is resolvable read-only while an unreferenced one 404s.

**Test files:**
- [backend/tests/unit/test_cc_integration_permission.py](../../../../backend/tests/unit/test_cc_integration_permission.py)
- [backend/tests/unit/test_fix_20261102_062047_mcp_tool_listing.py](../../../../backend/tests/unit/test_fix_20261102_062047_mcp_tool_listing.py)
- [backend/tests/unit/test_resource_type_manifest.py](../../../../backend/tests/unit/test_resource_type_manifest.py)
- [backend/tests/integration/test_namespace_permission_evaluation.py](../../../../backend/tests/integration/test_namespace_permission_evaluation.py)
- [frontend/src/__tests__/McpHubPage.test.tsx](../../../../frontend/src/__tests__/McpHubPage.test.tsx)
- [frontend/src/__tests__/ResourceTypeManifestMirror.test.ts](../../../../frontend/src/__tests__/ResourceTypeManifestMirror.test.ts)
- [frontend/src/__tests__/useMcpServers.pagination.test.tsx](../../../../frontend/src/__tests__/useMcpServers.pagination.test.tsx)

### 5. Inherent Self-Context & Optimization Skills
- A fixed built-in set of two inherent skills (`self-context`, `workflow-optimization`) exposes exactly nine optimization/self-context tools; all are registered and remain `system____` (never management tools).
- Both skills carry discovery descriptions and their tool lists.
- Context assembly injects the inherent tools for role-holding agents (alongside role-resolved tools) and for the role-less assistant (alongside the `cc` meta tools), with canonical `system____` names and sanitized definition names.
- Injection creates **zero** `AgentTypeSkillBinding` rows (no N×M seeding) — the set is inherent, not bound.
- The assistant never injects general agent system tools into the OAuth catalog; only explicitly granted `cc` tools are listed.

**Test files:**
- [backend/tests/communication_hub/test_fix_20261101_120618_inherent_skills.py](../../../../backend/tests/communication_hub/test_fix_20261101_120618_inherent_skills.py)
- [backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py](../../../../backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py)
- [backend/tests/unit/test_conversation_agent_tool_routing.py](../../../../backend/tests/unit/test_conversation_agent_tool_routing.py)
- [backend/tests/integration/test_tool_routing_architecture.py](../../../../backend/tests/integration/test_tool_routing_architecture.py)

### 6. Security & Sensitive-Data Boundary
- Identity tokens, DB credentials and decrypted MCP/provider credentials never appear in management tool results, MCP payloads, conversation responses or logs.
- Read handlers omit encrypted fields; write handlers never echo sender-supplied secrets.
- Every action is attributed to the OAuth-authenticated user in `ToolCallRecord` / `RuntimeToolCall`.
- Internal CC dispatch carries signed tenant headers and fails closed without them.

**Test files:**
- [backend/tests/unit/test_oauth_bearer_auth.py](../../../../backend/tests/unit/test_oauth_bearer_auth.py)
- [backend/tests/integration/test_management_toolset_end_to_end.py](../../../../backend/tests/integration/test_management_toolset_end_to_end.py)
- [backend/tests/integration/test_internal_tenant_header_failclosed.py](../../../../backend/tests/integration/test_internal_tenant_header_failclosed.py)

### 7. Management Tool Field Parity & Self-Correction (cc-assistant-management-tool-coverage)
- **UI parity per resource family**: for each of the nine families (`agent_type`, `agent_identity`, `agent_role`, `model_config`, `schedule`, `data_type`, `mcp_server`, `skill`, `sop`) every field editable in the corresponding web UI create/update form is accepted through the tool path and persisted — notably agent-type `identity_id`/`role_id`/`input_type`/`input_schema`/`output_type`/`output_schema`/`output_data_type_id`/guardrail fields, identity `status` + `role_ids`, role `description` + `skill_ids`/`sop_ids`, model-config `provider_type`/`api_key`/`enabled_models`/`api_base_url`/`is_disabled`, schedule update-time `cron_expression`/`payload`/`target_type`/`target_id` (with scheduler re-registration), data-type `description`/`fields`.
- **Typed per-family parameter schemas** in the registry (free-form `data` payloads gone), stable tool UUIDs, frozen parity map, enum mirroring, and a bounded schema size.
- **Structured, self-correctable validation errors**: missing/invalid/unknown fields and unresolvable id-or-name FK values return a payload (error code, field, problem, remedy with valid enum values or resolution guidance) rather than a bare 400 — the assistant retries with corrected input and completes without human troubleshooting; resolve-before-write means no partial writes.
- **Permission parity incl. negatives**: each tool enforces the same `(resource_type, action)` pair as its REST twin; a user without `manage` gets a clear denial and nothing is persisted; without `integration::control_center` the `cc` tools are absent from `/resolve`.
- **Additive-merge bindings**: `skill_ids`/`sop_ids` merges are additive and idempotent — re-approving the same set never removes or duplicates rows; an unknown reference fails the whole call with zero writes.
- **No-delete invariant**: no delete verb exists in the toolset, registry or seeder entries.
- **Conversational agent-type conflicts**: `output_data_type_id` + `input_type=conversation` is rejected with a structured error, identically to REST.
- **Read parity & credential hygiene**: list/get serializers return UI-detail-level data (guardrails, role assignments, grant lists, field definitions, output-data-type name) and never echo `api_key`, tokens or decrypted credentials — including inside validation errors.
- **Invariant preservation**: tenant-scoped id-or-name resolution (an identically named resource in another tenant never resolves), stable `mcp_hub_id`s, seeder-owned `cc` entity, CC-only DB writes.
- Regression: previously supported families and the REST surface behave unchanged.

**Test files:**
- [backend/tests/unit/test_management_payload_validator.py](../../../../backend/tests/unit/test_management_payload_validator.py)
- [backend/tests/integration/test_management_tool_full_field_parity.py](../../../../backend/tests/integration/test_management_tool_full_field_parity.py)
- [backend/tests/unit/test_management_mcp_tools.py](../../../../backend/tests/unit/test_management_mcp_tools.py)
- [backend/tests/e2e/test_assistant_agent_type_update_e2e.py](../../../../backend/tests/e2e/test_assistant_agent_type_update_e2e.py)
- [backend/tests/unit/test_management_tool_permission_parity.py](../../../../backend/tests/unit/test_management_tool_permission_parity.py)
- [backend/tests/unit/test_assistant_seeder.py](../../../../backend/tests/unit/test_assistant_seeder.py)
- [e2e/tests/control-center-chatbot-agent-type-update.spec.ts](../../../../e2e/tests/control-center-chatbot-agent-type-update.spec.ts)

---

## Critical Scenarios

### Catalog & authorization
- WHEN a valid user OAuth token calls `/mcp` THEN a session binds that user's identity, permissions and tenant and returns the permission-filtered catalog.
- WHEN the token is missing/invalid/expired/unresolvable THEN 401 is returned with no catalog and no session.
- WHEN a user lacks the mapped grant for a tool THEN that tool is absent from `tools/list` and a direct `tools/call` is denied with no write.
- WHEN a permitted action is called THEN it succeeds with exact REST parity and is attributed to the user.
- WHEN any delete-shaped action is requested THEN it is declined in-band and nothing is deleted.
- WHEN any action outside `agent::*` / `integration::mcp_hub` is requested THEN it is absent from the catalog and refused if invoked directly.

### Control Center entity
- WHEN a manager (including a wildcard holder) attempts to update/delete/sync/authorize the `cc` server THEN 403 `system_managed_integration` is returned and no row changes.
- WHEN a session is created/updated/deleted on `cc` THEN 403 "not supported"; non-`cc` sessions are unaffected.
- WHEN a user without `integration::control_center:read` lists MCP servers or tools THEN the `cc` entity/tools are omitted; with read they are included read-only.

### Management field parity & self-correction
- WHEN the assistant updates an agent type with `role_id` (id or name), `input_type`, `output_type`, `output_data_type_id` and guardrail fields, and the preview is approved THEN every changed field is persisted exactly as approved and the serialized post-write result reflects the new values (no "finish in the UI" fallback).
- WHEN the assistant sets `output_data_type_id` on an agent type whose `input_type` is `conversation` THEN a structured conflict error names the field and the remedy, and nothing is written.
- WHEN any create/update omits a required field, supplies an unknown field, or supplies an unresolvable id-or-name THEN the response is a structured error (code/field/problem/remedy) and no partial write occurs; a retry with corrected values succeeds without user involvement.
- WHEN an assistant updates `skill_ids` including already-bound skills THEN the merge is additive and idempotent — existing bindings are never removed.
- WHEN an assistant creates a model config with `api_key` THEN the credential is stored encrypted and never appears in the tool result, any serializer or a validation error.
- WHEN an assistant creates an MCP server without a slug, or with a duplicate slug THEN the known "slug is required" failure mode is self-correctable (structured error with guidance) and a duplicate returns a structured 409.
- WHEN a user lacks `manage` on a family or `integration::control_center` visibility THEN the tool call is denied with a clear structured 403 / the tools are absent at `/resolve`, and nothing is persisted.
- WHEN the registry, seeder entries and routing map are inspected THEN no delete verb exists for any family.

Entry, session, approval and liveness scenarios are on the
[hub page](control-center-assistant-test-plan.md#critical-scenarios).

---

## Edge Cases & Risks

| Risk | Mitigation / coverage |
|---|---|
| Permission-parity drift between a management MCP tool and its REST twin (elevation or under-permission) | Parity-map unit test asserting equality per tool with the REST `require_permission` pairs |
| Elevated identity through the MCP session (service/agent realm instead of the user) | Token→subject resolution tests; no elevated path; identity token never surfaced |
| Catalog leakage of tools the user cannot invoke | Permission-filtered `tools/list` tests per grant shape |
| Delete smuggling through create/update payloads | No delete tool registered + guard declining delete intent |
| Cross-tenant leakage on internal dispatch | Signed `X-Internal-Tenant-*` fail-closed structural tests |
| Legacy `system____<mgmt>` tool names surviving the `cc____` migration | Registry bridge naming tests + legacy→canonical migration test in `test_cc_seeder_migration.py` |
| Empty toolset on a fresh or non-root tenant (binding self-seed gap) | Seeder self-seed + double-seed idempotency tests; role-less assistant context always non-empty |
| Zero-binding skill produced silently by the assistant | Non-fatal warning in the write result + "No tools bound" UI state |
| Typed schema drift between the tool registry and the REST validators | Frozen parity map + registry schema-size and enum-mirroring assertions |
| Credential echo through a validation error or read serializer | Credential-non-echo assertions in field-parity and end-to-end management tests |

Conversation-side risks (approval durability, watchdog, topology) are on the
[hub page](control-center-assistant-test-plan.md#edge-cases--risks).

---

## Acceptance Criteria

- Assistant is scoped to `agent::*` + `integration::mcp_hub`; other scopes and deletion are declined with clear messages.
- Create/update/read through the assistant produce the same resources and validation results as the manual UI, visible without a page reload, across all nine management families.
- `POST /mcp` accepts only valid user OAuth tokens; `tools/list` is permission-filtered; `tools/call` enforces exact REST parity; actions are attributed to the authenticated user.
- An external MCP client using the user's credentials is bound to the same security layer as the in-app assistant.
- The Control Center MCP entity is system-managed, sessionless and permission-gated.
- No sensitive data (identity tokens, DB credentials, decrypted credentials) crosses any boundary or appears in results/logs.

Conversation-side acceptance criteria are on the
[hub page](control-center-assistant-test-plan.md#acceptance-criteria).

---

## Execution Results (as shipped)

| Layer | Suites | Result |
|---|---|---|
| Backend (pytest) | management tools/parity/cc naming/seeder, OAuth bearer + MCP protocol, inherent skills, bindings visibility, tool listing, management field parity + payload validator | Green per fix log; full `tests/unit` 1150 passed with only documented pre-existing/environmental failures |
| Frontend (Vitest) | skill binding surfaces, MCP Hub `cc` row, resource-type manifest mirror | Full run 1837 passed / 0 failed (1855 collected, 18 skipped) |
| E2E (Playwright) | `control-center-chatbot-mcp.spec.ts` (1), `control-center-chatbot-agent-type-update.spec.ts` (mocked agent-type-update journey) | Passing; MCP variant skips honestly under the multi-tenancy signed-header gap |
| Live verification | `scripts/fix-20261101-000319-live.cjs`, `fix-20261101-223511-live.cjs`, `fix-20261102-062047-probe.cjs` | LIVE-VERIFICATION-PASSED / LIVE-PROBE-PASSED |

Conversation-surface suites are reported on the
[hub page](control-center-assistant-test-plan.md#execution-results-as-shipped).

---

## Related Test Plans

- [Control Center Assistant (hub)](control-center-assistant-test-plan.md) — sibling page: chat entry, sessions, approvals, limits, knowledge.
- [MCP Hub](mcp-hub-test-plan.md) — server/session/tool-repository baseline plus the `cc` entity invariants.
- [Skill & SOP Engine](skills-sop-test-plan.md) — skill bindings, zero-binding guard, single tool surface.
- [Identity & Auth](identity-test-plan.md) — permission engine and resource-type manifest mirroring.
- [Communication Hub](communication-hub-test-plan.md) — `/mcp` protocol server and OAuth middleware.
- [Namespaced Resource Types](namespace-resource-types-test-plan.md) — `module::submodule` registry and wildcard evaluation.
- [Scheduling](scheduling-test-plan.md) — schedule family baseline reused by the management tools.

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| control-center-chatbot | OAuth-authenticated management MCP toolset (`cc____`), exact REST permission parity, skill/role/agent-type bindings, `cc` MCP entity invariants (system-managed, sessionless, permission-gated), inherent skills, sensitive-data boundary | 2026-11-02 |
| cc-assistant-management-tool-coverage | Full UI field parity across all nine management families, typed per-family tool schemas, structured self-correctable validation errors, positive/negative permission parity, additive-merge bindings, no-delete invariant, credential-non-echo read parity, and the mocked assistant agent-type-update journey (`control-center-chatbot-agent-type-update.spec.ts`) | 2026-11 |
