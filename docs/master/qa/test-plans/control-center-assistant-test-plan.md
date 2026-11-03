# Control Center Assistant Test Plan

## Scope

Covers the Control Center Assistant (`control-center-chatbot`): a seeded, system-owned
conversational `AgentType` embedded in the Control Center UI whose management actions are
exposed as MCP tools on the Communication Hub `/mcp` protocol server and authenticated with the
**user's** OAuth/OIDC Bearer token. The same tool surface and permission resolution serve the
in-app chatbot and any external MCP client using the user's credentials.

In scope: assistant entry point; conversation session lifecycle (persistence, resume, View All
Sessions, New/End/Exit, end-session termination); confirmation-before-write (approval preview,
expand); management MCP toolset (`cc____` namespace) with exact REST permission parity; role and
agent-type grants; skill ↔ tool bindings with the zero-binding guard; per-tenant assistant model
configuration; inherent self-context/optimization skills; guardrail iteration limits; turn
timeouts, watchdog and heartbeats; the Control Center MCP entity invariants (system-managed,
sessionless, permission-gated); and the `agent_types.is_system` / `tenant_settings` schema.

Out of scope: resource deletion (no delete tool is registered), non-`agent::*` /
non-`integration::mcp_hub` modules, and manual form workflows (unchanged).

---

## Coverage Areas

### 1. Assistant Availability & Entry Point
- The launcher renders only when a seeded `is_system` conversational agent type resolves; none resolved → no FAB.
- Clicking the launcher opens the reused `ConversationDialog` with the resolved agent type id.
- Assistant/agent messages render through `ContentRenderer` (sanitized HTML / markdown); user turns stay plain text.
- i18n keys exist for the launcher and the system-type badges (no hardcoded strings).
- `is_system` agent types are marked in the Agent Types list with Edit/Delete disabled; non-system types are unaffected.

**Test files:**
- [frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx](../../../../frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx)
- [frontend/src/__tests__/ConversationDialog.assistantChat.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.assistantChat.test.tsx)
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx)
- [e2e/tests/control-center-chatbot.spec.ts](../../../../e2e/tests/control-center-chatbot.spec.ts)

### 2. Session Lifecycle — Persistence, Resume, View All Sessions, New/End/Exit
- Closing the dialog only disconnects the WebSocket; the session stays `active` and the next open resumes the most recent active session for the assistant (prior turns reloaded).
- An explicit End closes the session (best-effort in-flight termination) and sets a per-agent-type force-new flag so the next open starts a NEW session; plain Exit keeps resume semantics.
- Four-option action bar: View All Sessions / New Session / End Session / Exit. New Session creates a fresh session without ending or archiving the current one and clears message state; Exit closes with zero API calls; all actions are disabled while a turn is streaming.
- View All Sessions: active-only by default with a 7-day default window; an "ended" toggle includes closed/archived/error sessions; ended rows are marked and not resumable; switching to an active session resumes in place without ending/archiving the previous one.
- Sessions list API contract: `updated_at DESC` ordering, configurable default window (7 days) with explicit `date_from`/`date_to` override and an `all_time` escape hatch, `status` semantics (`active` / `ended` = closed+archived+error / `all`), `page`/`page_size` slicing with full filtered `total`, tenant isolation, and legacy `GET /conversations` backward compatibility.
- Mid-turn WebSocket reconnect: the resume endpoint re-merges persisted turns generated during the outage (no duplicates, reply renders live).
- End-session termination: `/conversations/{id}/end` best-effort cancels in-flight execution via the CC → CH → AR chain; a termination failure never fails the end call.

**Test files:**
- [backend/tests/integration/test_conversations_sessions_query.py](../../../../backend/tests/integration/test_conversations_sessions_query.py)
- [backend/tests/api/test_conversations_end_termination.py](../../../../backend/tests/api/test_conversations_end_termination.py)
- [frontend/src/__tests__/ConversationDialog.actionBar.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.actionBar.test.tsx)
- [frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx)
- [frontend/src/__tests__/AppShell.forceNewAfterEnd.test.tsx](../../../../frontend/src/__tests__/AppShell.forceNewAfterEnd.test.tsx)
- [frontend/src/__tests__/AppShell.assistantSession.test.tsx](../../../../frontend/src/__tests__/AppShell.assistantSession.test.tsx)
- [frontend/src/__tests__/ConversationDialog.resumeLiveDelivery.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.resumeLiveDelivery.test.tsx)

### 3. Confirmation-Before-Write (Conversational HITL)
- `human_intervene` is exposed to the assistant as a meta tool (registry set and schema), with no permission-parity leakage and no management duplicate.
- Every write is preceded by a confirmation preview in the canonical markdown table form (`| Field | Value |` with a bold title), so the user can reject or correct before anything is written.
- Approval resumes the same conversation turn and then performs the real management dispatch; the created resource is verified through the REST API.
- The inline approval card supports an expand action that renders the full-width preview table with the same approve/deny handlers; collapse restores the working inline card.
- An operator-less timeout returns an explicit "not executed" result and ends the turn bounded — it never silently proceeds with the write.
- The turn timeout stays armed while a confirmation is pending (re-armed on the pending intervention) and still fires for unanswered confirmations.

**Test files:**
- [backend/tests/integration/test_assistant_meta_tools.py](../../../../backend/tests/integration/test_assistant_meta_tools.py)
- [backend/tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py](../../../../backend/tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py)
- [backend/tests/agent_runtime/test_fix_20261031_133253_conversational_hitl.py](../../../../backend/tests/agent_runtime/test_fix_20261031_133253_conversational_hitl.py)
- [backend/tests/agent_runtime/test_fix_20261031_133253_intervention_wait_bound.py](../../../../backend/tests/agent_runtime/test_fix_20261031_133253_intervention_wait_bound.py)
- [frontend/src/__tests__/InlineInterventionDialog.test.tsx](../../../../frontend/src/__tests__/InlineInterventionDialog.test.tsx)
- [frontend/src/__tests__/InlineInterventionDialog.expand.test.tsx](../../../../frontend/src/__tests__/InlineInterventionDialog.expand.test.tsx)
- [frontend/src/__tests__/ConversationDialog.intervention.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.intervention.test.tsx)
- [frontend/src/__tests__/useChatSession.intervention.test.ts](../../../../frontend/src/__tests__/useChatSession.intervention.test.ts)

### 4. Management MCP Toolset (`cc____` namespace)
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

### 5. Permission Parity & Grants
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

### 6. OAuth-Authenticated MCP Clients (`/mcp`)
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

### 7. Control Center MCP Entity Invariants
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

### 8. Per-Tenant Assistant Model Configuration
- The assistant model is operator-configured per tenant through the dedicated endpoints (options from the tenant's Model Configurations, selection persisted onto the tenant's assistant agent type `model_id`) with `agent` read/update permission.
- With no assistant row or no selection, the GET returns a null `selected_model_id` and an empty-safe options list; cross-tenant selections never leak.
- A model that is not enabled for the tenant is rejected; selecting a valid model persists and renders immediately in System Config.
- In the chat surface, `selected_model_id: null` shows the guidance banner with a "Configure model" action and disables input/send; a configured model shows no banner. Mid-session, an AR pre-model 400 maps to the structured `assistant_model_not_configured` chat error instead of a generic failure.
- Workflow-generation model selection is DB-backed per tenant (`tenant_settings`, unique `(tenant_id, key)`), with idempotent adoption of the legacy global YAML value into the root tenant and no cross-tenant bleed.

**Test files:**
- [backend/tests/api/test_assistant_model_api.py](../../../../backend/tests/api/test_assistant_model_api.py)
- [backend/tests/test_tenant_settings_workflow_generation.py](../../../../backend/tests/test_tenant_settings_workflow_generation.py)
- [backend/tests/communication_hub/test_ws_chat_model_not_configured.py](../../../../backend/tests/communication_hub/test_ws_chat_model_not_configured.py)
- [frontend/src/__tests__/AssistantModelConfigGuidance.test.tsx](../../../../frontend/src/__tests__/AssistantModelConfigGuidance.test.tsx)
- [frontend/src/__tests__/SystemConfigPage.assistant-model.test.tsx](../../../../frontend/src/__tests__/SystemConfigPage.assistant-model.test.tsx)

### 9. Inherent Self-Context & Optimization Skills
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

### 10. Guardrails & Iteration Limits
- The seeded assistant carries `guardrail_max_iterations` = 24 (≥ the observed 11-step exhaustion); a previously downgraded seeded row is refreshed back to 24 by the idempotent seeder.
- A `GuardrailStop` during a conversation turn surfaces a structured `iteration_limit` error (with details) through AR streaming chunks and CH mapping, and the user sees a clear message — never the generic "An error occurred".
- The error turn is persisted exactly once with an `iteration_limit` status event, and a `chat_error` payload is emitted.

**Test files:**
- [backend/tests/unit/test_assistant_seeder.py](../../../../backend/tests/unit/test_assistant_seeder.py)
- [backend/tests/communication_hub/test_fix_20261101_111439_iteration_limit.py](../../../../backend/tests/communication_hub/test_fix_20261101_111439_iteration_limit.py)

### 11. Turn Timeouts, Watchdog & Heartbeats
- A hung model invocation is bounded by `conversation_llm_timeout_seconds`, returning a clear "timed out" reply and a `timeout_or_failed` status event; fast turns are unaffected.
- The whole-turn watchdog bounds the turn even on the streaming path; a watchdog error turn is persisted exactly once and never on the success path.
- `thinking_heartbeat` keepalives are emitted during long turns and refresh the client's thinking timestamp without injecting messages or changing status; the socket survives beyond the legacy idle boundary.
- AR `/terminate/{id}` cancels in-flight conversation turn tasks (404 when nothing is in flight); WebSocket close code/reason is logged.

**Test files:**
- [backend/tests/agent_runtime/test_fix_20261031_091657_llm_timeout.py](../../../../backend/tests/agent_runtime/test_fix_20261031_091657_llm_timeout.py)
- [backend/tests/agent_runtime/test_fix_20261031_091657_terminate_conversation_task.py](../../../../backend/tests/agent_runtime/test_fix_20261031_091657_terminate_conversation_task.py)
- [backend/tests/communication_hub/test_fix_20261031_091657_turn_watchdog.py](../../../../backend/tests/communication_hub/test_fix_20261031_091657_turn_watchdog.py)
- [frontend/src/__tests__/useChatSession.heartbeat.test.ts](../../../../frontend/src/__tests__/useChatSession.heartbeat.test.ts)

### 12. Assistant Knowledge, Instruction & Self-Correction
- The seeded instruction encodes generic principles (completeness, prerequisite ordering, grant at the right level, reuse-first, derive-not-script) plus the hard facts (never raw MCP tools, model config, enabled models, conversational, unique per tenant, `cc____`/`system____`, non-functional detection, `human_intervene`, preview table format).
- No fixed step-by-step sequence is encoded in the corpus or either instruction surface.
- Knowledge retrieval returns the right rule for intent: confirmation-before-write, agent-creation completeness, role-grant workflow, skill ↔ tool binding, confirmation preview format.
- The idempotent seeder refreshes stale instruction text and stale skill digests on the next run for every tenant.
- Tool-context completeness on the conversational path: the role-less assistant always receives a non-empty toolset (management + meta + inherent) with function schemas.

**Test files:**
- [backend/tests/unit/test_assistant_knowledge.py](../../../../backend/tests/unit/test_assistant_knowledge.py)
- [backend/tests/unit/test_fix_20261102_100704_generic_principles.py](../../../../backend/tests/unit/test_fix_20261102_100704_generic_principles.py)
- [backend/tests/unit/test_assistant_seeder.py](../../../../backend/tests/unit/test_assistant_seeder.py)
- [backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py](../../../../backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py)

### 13. Topology Pending-Load States (shipped with this change)
- Every topology entity whose data is still loading renders a spinner + localized "Loading…" instead of a raw id or a misleading placeholder.
- Resolved entities render their real labels; resolved-but-missing references keep the raw-id fallback; deliberately empty/`None`/`Auto`/conversation slots keep their existing dashed/solid semantics and never flip to pending.
- Pending nodes are non-interactive (no node-click), accessible (`role="progressbar"` + localized label/title), and drawn in viewBox units.

**Test files:**
- [frontend/src/__tests__/PanelTopologyCanvas.test.tsx](../../../../frontend/src/__tests__/PanelTopologyCanvas.test.tsx)
- [frontend/src/__tests__/TopologyDiagramRenderer.test.tsx](../../../../frontend/src/__tests__/TopologyDiagramRenderer.test.tsx)

### 14. Schema & Migration
- `agent_types.is_system` exists on the live database: `boolean`, `NOT NULL`, default `false`, and no NULL rows.
- `tenant_settings` exists with unique `(tenant_id, key)` and cascade on tenant delete.
- System agent types are rejected by the REST API on update/delete (403); non-system types remain editable/deletable.
- Migrations apply cleanly and are reversible.

**Test files:**
- [backend/tests/db/test_agent_type_is_system_migration.py](../../../../backend/tests/db/test_agent_type_is_system_migration.py)
- [backend/tests/test_tenant_settings_workflow_generation.py](../../../../backend/tests/test_tenant_settings_workflow_generation.py)
- [backend/tests/conftest.py](../../../../backend/tests/conftest.py)

### 15. Security & Sensitive-Data Boundary
- Identity tokens, DB credentials and decrypted MCP/provider credentials never appear in management tool results, MCP payloads, conversation responses or logs.
- Read handlers omit encrypted fields; write handlers never echo sender-supplied secrets.
- Every action is attributed to the OAuth-authenticated user in `ToolCallRecord` / `RuntimeToolCall`.
- Internal CC dispatch carries signed tenant headers and fails closed without them.

**Test files:**
- [backend/tests/unit/test_oauth_bearer_auth.py](../../../../backend/tests/unit/test_oauth_bearer_auth.py)
- [backend/tests/integration/test_management_toolset_end_to_end.py](../../../../backend/tests/integration/test_management_toolset_end_to_end.py)
- [backend/tests/integration/test_internal_tenant_header_failclosed.py](../../../../backend/tests/integration/test_internal_tenant_header_failclosed.py)

---

## Critical Scenarios

### Entry & availability
- WHEN no seeded `is_system` agent type resolves THEN no assistant launcher is rendered.
- WHEN the launcher is clicked THEN `ConversationDialog` opens bound to the resolved assistant agent type.
- WHEN a system agent type is listed in Agent Types THEN it shows the System badge with Edit/Delete disabled; non-system rows stay editable/deletable.

### Session lifecycle
- WHEN the user closes and reopens the assistant THEN the most recent active session resumes with its prior turns (no new session).
- WHEN the user ends the session THEN it becomes closed, in-flight work is best-effort terminated, and the next open starts a NEW session.
- WHEN the user chooses Exit THEN the dialog closes with zero API mutation and resume semantics are preserved.
- WHEN View All Sessions opens THEN only active sessions from the last 7 days are listed, ordered by `updated_at` desc.
- WHEN the "show ended" toggle is used THEN closed/archived/error sessions appear and are marked non-resumable.
- WHEN a later page or an explicit date range is requested THEN the list refetches with the correct `page`/`page_size` and inclusive day boundaries and reports the full filtered total.
- WHEN an active session is selected from the list THEN it resumes in place; the previously open session is neither ended nor archived.

### Confirmation-before-write
- WHEN a write is requested THEN the assistant emits an approval request whose preview is the canonical bold-title + `| Field | Value |` table.
- WHEN the user approves THEN the same turn resumes and the real management tool executes (resource verifiable via REST).
- WHEN the user rejects, or no operator responds in time THEN nothing is written and the turn ends bounded with an explicit not-executed outcome.
- WHEN the approval card is expanded THEN the full table renders at full width and approve/deny still work; collapsing returns to the inline card.

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

### Model configuration
- WHEN the tenant has no assistant model selected THEN the chat shows the configure-model guidance and disables input, and mid-session the structured `assistant_model_not_configured` error maps to the same guidance.
- WHEN an operator selects an enabled model THEN it persists for that tenant only and the chat input is enabled.

### Limits & liveness
- WHEN the model hangs THEN the turn is bounded by the conversation timeout, the user gets a clear timeout reply, and a `timeout_or_failed` event is recorded.
- WHEN a turn runs long THEN heartbeats keep the socket alive and the turn completes without a mid-turn disconnect.
- WHEN the assistant exhausts its iteration budget THEN a clear iteration-limit error is shown and persisted once.

---

## Edge Cases & Risks

| Risk | Mitigation / coverage |
|---|---|
| Permission-parity drift between a management MCP tool and its REST twin (elevation or under-permission) | Parity-map unit test asserting equality per tool with the REST `require_permission` pairs |
| Elevated identity through the MCP session (service/agent realm instead of the user) | Token→subject resolution tests; no elevated path; identity token never surfaced |
| Catalog leakage of tools the user cannot invoke | Permission-filtered `tools/list` tests per grant shape |
| Delete smuggling through create/update payloads | No delete tool registered + guard declining delete intent |
| Cross-tenant leakage on internal dispatch | Signed `X-Internal-Tenant-*` fail-closed structural tests |
| Seeding idempotency drift (duplicate assistant/skills; stale instruction or binding set) | Seeder idempotency + stale-refresh tests; legacy `system____<mgmt>` → `cc____` migration test |
| Empty toolset on a fresh or non-root tenant (binding self-seed gap) | Seeder self-seed + double-seed idempotency tests; role-less assistant context always non-empty |
| Zero-binding skill produced silently by the assistant | Non-fatal warning in the write result + "No tools bound" UI state |
| End-session leaving orphaned in-flight execution | `/end` best-effort termination chain test; termination failure never fails end |
| Watchdog double-persisting an error turn | Exact-once persistence assertions on both success and watchdog paths |
| `is_system` nullable/missing default in a hand-written migration | `information_schema` probes (type, NOT NULL, default) + no-NULL-rows check |
| `tenant_settings` adoption overwriting an existing selection | Idempotent adoption test (legacy YAML value only seeds an empty root row) |
| Topology showing raw ids while data loads | Pending-state matrix tests for every entity type + resolved/deliberate-state regressions |

---

## Acceptance Criteria

- Assistant is available to logged-in users and scoped to `agent::*` + `integration::mcp_hub`; other scopes and deletion are declined with clear messages.
- Create/update/read through the assistant produce the same resources and validation results as the manual UI, visible without a page reload.
- `POST /mcp` accepts only valid user OAuth tokens; `tools/list` is permission-filtered; `tools/call` enforces exact REST parity; actions are attributed to the authenticated user.
- An external MCP client using the user's credentials is bound to the same security layer as the in-app assistant.
- Every write requires an explicit approval whose preview carries the canonical field/value table.
- Conversation context persists across turns; sessions resume, list (active/ended, paged, date-windowed), and can be created/ended/exited with the documented semantics.
- Per-tenant assistant model configuration gates the chat surface with actionable guidance when unset.
- Inherent self-context/optimization skills are always available without creating binding rows.
- Turn timeouts, watchdogs, heartbeats and iteration limits terminate cleanly with clear user-facing errors.
- The Control Center MCP entity is system-managed, sessionless and permission-gated.
- `agent_types.is_system` is `boolean NOT NULL DEFAULT false`; `tenant_settings` is tenant-unique; system agent types are protected in API and UI.
- No sensitive data (identity tokens, DB credentials, decrypted credentials) crosses any boundary or appears in results/logs.

---

## Execution Results (as shipped)

| Layer | Suites | Result |
|---|---|---|
| Backend (pytest) | management tools/parity/cc naming/seeder, OAuth bearer + MCP protocol, assistant model API, tenant settings, HITL/confirm, timeouts/watchdog, iteration limit, inherent skills, bindings visibility, tool listing, topology-free knowledge corpus | Green per fix log; full `tests/unit` 1150 passed with only documented pre-existing/environmental failures |
| Frontend (Vitest) | assistant entry, model guidance, session action bar, sessions view, heartbeat, intervention/expand, skill binding surfaces, MCP Hub `cc` row, topology pending states | Full run 1837 passed / 0 failed (1855 collected, 18 skipped) |
| E2E (Playwright) | `control-center-chatbot.spec.ts` (mocked 4), `control-center-chatbot.real-backend.spec.ts` (3), `control-center-chatbot-mcp.spec.ts` (1) | Passing; real-backend/MCP variants skip honestly under the multi-tenancy signed-header gap |
| Live verification | `scripts/fix-20261031-091657-live-a.cjs`, `-live-b.cjs`, `fix-20261031-133253-live.cjs`, `fix-20261101-000319-live.cjs`, `fix-20261101-223511-live.cjs`, `fix-20261102-062047-probe.cjs`, `fix-20261102-100704-seed-refresh-check.py` | LIVE-VERIFICATION-PASSED / LIVE-PROBE-PASSED / SEED-REFRESH: PASSED |

---

## Related Test Plans

- [Conversation Sessions](conversation-sessions-test-plan.md) — session lifecycle baseline extended by View All Sessions and New/End/Exit.
- [Human Intervene](human-intervene-test-plan.md) — conversational approval transport reused for confirmation-before-write.
- [MCP Hub](mcp-hub-test-plan.md) — server/session/tool-repository baseline plus the `cc` entity invariants.
- [Skill & SOP Engine](skills-sop-test-plan.md) — skill bindings, zero-binding guard, single tool surface.
- [Identity & Auth](identity-test-plan.md) — permission engine and resource-type manifest mirroring.
- [Agents UI](agents-ui-test-plan.md) — Agent Types list `is_system` badge and topology pending states.
- [Communication Hub](communication-hub-test-plan.md) — `/mcp` protocol server and OAuth middleware.

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| control-center-chatbot | Seeded system assistant agent type; OAuth-authenticated management MCP toolset (`cc____`); confirmation-before-write; session lifecycle (resume/View All/New/End/Exit + end termination); per-tenant assistant model config; inherent skills; guardrail/timeout/heartbeat handling; `cc` MCP entity invariants; `is_system` + `tenant_settings` schema; topology pending states | 2026-11-02 |
