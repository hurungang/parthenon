# Control Center Assistant Test Plan

Covers the Control Center Assistant's conversational surface (hub page). The assistant's
management-tool surface — tool catalog, permission parity, OAuth MCP clients and the `cc` entity —
lives on the sibling page.

| Page | Surface |
|---|---|
| **This page (hub)** | Chat entry/launcher, session lifecycle, confirmation-before-write approval flow, durable approvals across restarts, activity/status restoration, error surfacing, knowledge/i18n, seeded-assistant schema |
| [Assistant Management Tools](assistant-management-tools-test-plan.md) | Management MCP toolset (`cc____`), per-resource-family UI parity, typed parameter schemas, structured validation, permission-denial parity, bindings, no-delete, credential hygiene, tenant-scoped resolution |

Index: [QA documentation](../../qa/README.md)

## Scope

Covers the Control Center Assistant (`control-center-chatbot`): a seeded, system-owned
conversational `AgentType` embedded in the Control Center UI. Its management actions are exposed as
MCP tools on the Communication Hub `/mcp` protocol server and authenticated with the **user's**
OAuth/OIDC Bearer token; that tool surface is specified and tested on
[Assistant Management Tools](assistant-management-tools-test-plan.md).

In scope: assistant entry point; conversation session lifecycle (persistence, resume, View All
Sessions, New/End/Exit, end-session termination); confirmation-before-write (approval preview,
expand) and the durability of a pending approval across reconnects and service restarts (see
[Resumable Turns](resumable-turn-test-plan.md)); activity/status restoration on resume; per-tenant
assistant model configuration and its chat-surface error surfacing; guardrail iteration limits;
turn timeouts, watchdog and heartbeats; assistant knowledge/instruction and i18n; topology
pending-load states; and the `agent_types.is_system` / `tenant_settings` schema.

Out of scope: the management MCP toolset, permission parity, OAuth MCP client catalog and `cc`
entity invariants (sibling page), resource deletion (no delete tool is registered), and manual form
workflows (unchanged).

---

## Coverage Areas

### 1. Assistant Availability & Entry Point
- The launcher renders only when a seeded `is_system` conversational agent type resolves; none resolved → no FAB.
- Clicking the launcher opens the reused `ConversationDialog` with the resolved agent type id.
- Assistant/agent messages render through `ContentRenderer` (sanitized HTML / markdown); user turns stay plain text.
- i18n keys exist for the launcher and the system-type badges (no hardcoded strings).

**Test files:**
- [frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx](../../../../frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx)
- [frontend/src/__tests__/ConversationDialog.assistantChat.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.assistantChat.test.tsx)
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
- A pending approval survives a reconnect and a CC/CH/AR restart (durable resume index + checkpoint), applies its write exactly once, and ends with one reason-keyed terminal outcome when it truly cannot continue — see [Resumable Turns](resumable-turn-test-plan.md).

**Test files:**
- [backend/tests/integration/test_assistant_meta_tools.py](../../../../backend/tests/integration/test_assistant_meta_tools.py)
- [backend/tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py](../../../../backend/tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py)
- [backend/tests/agent_runtime/test_fix_20261031_133253_conversational_hitl.py](../../../../backend/tests/agent_runtime/test_fix_20261031_133253_conversational_hitl.py)
- [backend/tests/agent_runtime/test_fix_20261031_133253_intervention_wait_bound.py](../../../../backend/tests/agent_runtime/test_fix_20261031_133253_intervention_wait_bound.py)
- [frontend/src/__tests__/InlineInterventionDialog.test.tsx](../../../../frontend/src/__tests__/InlineInterventionDialog.test.tsx)
- [frontend/src/__tests__/InlineInterventionDialog.expand.test.tsx](../../../../frontend/src/__tests__/InlineInterventionDialog.expand.test.tsx)
- [frontend/src/__tests__/ConversationDialog.intervention.test.tsx](../../../../frontend/src/__tests__/ConversationDialog.intervention.test.tsx)
- [frontend/src/__tests__/useChatSession.intervention.test.ts](../../../../frontend/src/__tests__/useChatSession.intervention.test.ts)

### 4. Per-Tenant Assistant Model Configuration
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

### 5. Guardrails & Iteration Limits
- The seeded assistant carries `guardrail_max_iterations` = 24 (≥ the observed 11-step exhaustion); a previously downgraded seeded row is refreshed back to 24 by the idempotent seeder.
- A `GuardrailStop` during a conversation turn surfaces a structured `iteration_limit` error (with details) through AR streaming chunks and CH mapping, and the user sees a clear message — never the generic "An error occurred".
- The error turn is persisted exactly once with an `iteration_limit` status event, and a `chat_error` payload is emitted.

**Test files:**
- [backend/tests/unit/test_assistant_seeder.py](../../../../backend/tests/unit/test_assistant_seeder.py)
- [backend/tests/communication_hub/test_fix_20261101_111439_iteration_limit.py](../../../../backend/tests/communication_hub/test_fix_20261101_111439_iteration_limit.py)

### 6. Turn Timeouts, Watchdog & Heartbeats
- A hung model invocation is bounded by `conversation_llm_timeout_seconds`, returning a clear "timed out" reply and a `timeout_or_failed` status event; fast turns are unaffected.
- The whole-turn watchdog bounds the turn even on the streaming path; a watchdog error turn is persisted exactly once and never on the success path.
- `thinking_heartbeat` keepalives are emitted during long turns and refresh the client's thinking timestamp without injecting messages or changing status; the socket survives beyond the legacy idle boundary.
- AR `/terminate/{id}` cancels in-flight conversation turn tasks (404 when nothing is in flight); WebSocket close code/reason is logged.
- A2A delegation inside a conversational turn re-emits a `waiting` status on every still-running poll, so the whole-turn watchdog extends while the sub-agent works (no false 120 s cancellation) and the chat keeps a visible indicator.
- `guardrail_update` is delivered the moment the LLM delegation returns — before turn persistence — so a slow/failed `append-turn` can never leave the guardrail panel dark.
- `execute_script` inside a conversation turn ships no execution-log entries (conversation sessions have no `execution_log_entries` owner); the ship is suppressed at one choke point and the CC endpoint degrades a conversation-session FK violation to a 200 no-op.

**Test files:**
- [backend/tests/agent_runtime/test_fix_20261031_091657_llm_timeout.py](../../../../backend/tests/agent_runtime/test_fix_20261031_091657_llm_timeout.py)
- [backend/tests/agent_runtime/test_fix_20261031_091657_terminate_conversation_task.py](../../../../backend/tests/agent_runtime/test_fix_20261031_091657_terminate_conversation_task.py)
- [backend/tests/communication_hub/test_fix_20261031_091657_turn_watchdog.py](../../../../backend/tests/communication_hub/test_fix_20261031_091657_turn_watchdog.py)
- [backend/tests/agent_runtime/test_fix_20261109_conversation_log_guardrail.py](../../../../backend/tests/agent_runtime/test_fix_20261109_conversation_log_guardrail.py)
- [frontend/src/__tests__/useChatSession.heartbeat.test.ts](../../../../frontend/src/__tests__/useChatSession.heartbeat.test.ts)

### 7. Assistant Knowledge, Instruction & Self-Correction
- The seeded instruction encodes generic principles (completeness, prerequisite ordering, grant at the right level, reuse-first, derive-not-script) plus the hard facts (never raw MCP tools, model config, enabled models, conversational, unique per tenant, `cc____`/`system____`, non-functional detection, `human_intervene`, preview table format).
- No fixed step-by-step sequence is encoded in the corpus or either instruction surface.
- Knowledge retrieval returns the right rule for intent: confirmation-before-write, agent-creation completeness, role-grant workflow, skill ↔ tool binding, confirmation preview format.
- The idempotent seeder refreshes stale instruction text and stale skill digests on the next run for every tenant.
- Tool-context completeness on the conversational path: the role-less assistant always receives a non-empty toolset (management + meta + inherent) with function schemas.
- Knowledge/instruction encode the corrected permission model: a **role** grants permission only, an **agent type** controls visibility (its own SOP/skill bindings, intersected with the role's grants) — an agent that cannot see an expected tool is fixed by associating the SOP/skill with the agent type, not the role.
- SOP authoring never instructs raw MCP tool calls: capability is expressed only as `agent_delegation` / `skill_invocation` steps, and raw tools are bound into a skill first (`sop-no-raw-tool-mentions` entry + seeder rule + retrieval by "sop tool mention" / "raw" / "mcp" keywords).

**Test files:**
- [backend/tests/unit/test_assistant_knowledge.py](../../../../backend/tests/unit/test_assistant_knowledge.py)
- [backend/tests/unit/test_fix_20261102_100704_generic_principles.py](../../../../backend/tests/unit/test_fix_20261102_100704_generic_principles.py)
- [backend/tests/unit/test_assistant_seeder.py](../../../../backend/tests/unit/test_assistant_seeder.py)
- [backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py](../../../../backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py)

### 8. Topology Pending-Load States
- Every topology entity whose data is still loading renders a spinner + localized "Loading…" instead of a raw id or a misleading placeholder.
- Resolved entities render their real labels; resolved-but-missing references keep the raw-id fallback; deliberately empty/`None`/`Auto`/conversation slots keep their existing dashed/solid semantics and never flip to pending.
- Pending nodes are non-interactive (no node-click), accessible (`role="progressbar"` + localized label/title), and drawn in viewBox units.

**Test files:**
- [frontend/src/__tests__/PanelTopologyCanvas.test.tsx](../../../../frontend/src/__tests__/PanelTopologyCanvas.test.tsx)
- [frontend/src/__tests__/TopologyDiagramRenderer.test.tsx](../../../../frontend/src/__tests__/TopologyDiagramRenderer.test.tsx)

### 9. Schema & Migration
- `agent_types.is_system` exists on the live database: `boolean`, `NOT NULL`, default `false`, and no NULL rows.
- `tenant_settings` exists with unique `(tenant_id, key)` and cascade on tenant delete.
- System agent types are rejected by the REST API on update/delete (403); non-system types remain editable/deletable.
- `is_system` agent types are marked in the Agent Types list with Edit/Delete disabled; non-system types are unaffected.
- Migrations apply cleanly and are reversible.

**Test files:**
- [backend/tests/db/test_agent_type_is_system_migration.py](../../../../backend/tests/db/test_agent_type_is_system_migration.py)
- [frontend/src/__tests__/AgentManagementPage.test.tsx](../../../../frontend/src/__tests__/AgentManagementPage.test.tsx)
- [backend/tests/test_tenant_settings_workflow_generation.py](../../../../backend/tests/test_tenant_settings_workflow_generation.py)
- [backend/tests/conftest.py](../../../../backend/tests/conftest.py)

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
- WHEN the user reconnects — or CC/CH/AR restarts — while approval is pending THEN the pending approval is restored (durable resume index + checkpoint) and the confirmed write is applied exactly once.

### Model configuration
- WHEN the tenant has no assistant model selected THEN the chat shows the configure-model guidance and disables input, and mid-session the structured `assistant_model_not_configured` error maps to the same guidance.
- WHEN an operator selects an enabled model THEN it persists for that tenant only and the chat input is enabled.

### Limits & liveness
- WHEN the model hangs THEN the turn is bounded by the conversation timeout, the user gets a clear timeout reply, and a `timeout_or_failed` event is recorded.
- WHEN a turn runs long THEN heartbeats keep the socket alive and the turn completes without a mid-turn disconnect.
- WHEN the assistant exhausts its iteration budget THEN a clear iteration-limit error is shown and persisted once.
- WHEN a turn resumes after reconnect THEN status/activity indicators (waiting, thinking, guardrail panel) are restored from persisted state instead of appearing idle.

Tool-catalog, `cc` entity and management-field-parity scenarios are on
[Assistant Management Tools](assistant-management-tools-test-plan.md#critical-scenarios).

---

## Edge Cases & Risks

| Risk | Mitigation / coverage |
|---|---|
| Seeding idempotency drift (duplicate assistant/skills; stale instruction or binding set) | Seeder idempotency + stale-refresh tests; legacy `system____<mgmt>` → `cc____` migration test |
| End-session leaving orphaned in-flight execution | `/end` best-effort termination chain test; termination failure never fails end |
| Watchdog double-persisting an error turn | Exact-once persistence assertions on both success and watchdog paths |
| Pending approval lost on reconnect or service restart | Durable resume-index/checkpoint tests in [Resumable Turns](resumable-turn-test-plan.md); exactly-once application of the confirmed write |
| `is_system` nullable/missing default in a hand-written migration | `information_schema` probes (type, NOT NULL, default) + no-NULL-rows check |
| `tenant_settings` adoption overwriting an existing selection | Idempotent adoption test (legacy YAML value only seeds an empty root row) |
| Topology showing raw ids while data loads | Pending-state matrix tests for every entity type + resolved/deliberate-state regressions |

Tool-authorization, catalog-leakage and delete-smuggling risks are on
[Assistant Management Tools](assistant-management-tools-test-plan.md#edge-cases--risks).

---

## Acceptance Criteria

- Assistant is available to logged-in users; conversation context persists across turns; sessions resume, list (active/ended, paged, date-windowed), and can be created/ended/exited with the documented semantics.
- Every write requires an explicit approval whose preview carries the canonical field/value table; a pending approval survives reconnect and service restart and applies exactly once.
- Per-tenant assistant model configuration gates the chat surface with actionable guidance when unset.
- Turn timeouts, watchdogs, heartbeats and iteration limits terminate cleanly with clear user-facing errors.
- `agent_types.is_system` is `boolean NOT NULL DEFAULT false`; `tenant_settings` is tenant-unique; system agent types are protected in API and UI.

Security-boundary, permission-parity and tool-parity acceptance criteria are on
[Assistant Management Tools](assistant-management-tools-test-plan.md#acceptance-criteria).

---

## Execution Results (as shipped)

| Layer | Suites | Result |
|---|---|---|
| Backend (pytest) | assistant model API, tenant settings, HITL/confirm, timeouts/watchdog, iteration limit, topology-free knowledge corpus | Green per fix log; full `tests/unit` 1150 passed with only documented pre-existing/environmental failures |
| Frontend (Vitest) | assistant entry, model guidance, session action bar, sessions view, heartbeat, intervention/expand, topology pending states | Full run 1837 passed / 0 failed (1855 collected, 18 skipped) |
| E2E (Playwright) | `control-center-chatbot.spec.ts` (mocked 4), `control-center-chatbot.real-backend.spec.ts` (3) | Passing; real-backend variant skips honestly under the multi-tenancy signed-header gap |
| Live verification | `scripts/fix-20261031-091657-live-a.cjs`, `-live-b.cjs`, `fix-20261031-133253-live.cjs`, `fix-20261102-100704-seed-refresh-check.py` | LIVE-VERIFICATION-PASSED / SEED-REFRESH: PASSED |

Management-tool suites and live probes are reported on
[Assistant Management Tools](assistant-management-tools-test-plan.md#execution-results-as-shipped).

---

## Related Test Plans

- [Assistant Management Tools](assistant-management-tools-test-plan.md) — sibling page: management MCP toolset, parity, `cc` entity, field parity.
- [Conversation Sessions](conversation-sessions-test-plan.md) — session lifecycle baseline extended by View All Sessions and New/End/Exit.
- [Human Intervene](human-intervene-test-plan.md) — conversational approval transport reused for confirmation-before-write.
- [Conversational Intervention & Activity State](conversation-intervention-test-plan.md) — inline intervention surfacing and activity/status restoration.
- [Resumable Turns](resumable-turn-test-plan.md) — durable pause/approve-after-restart of a confirmation-pending turn.
- [Agents UI](agents-ui-test-plan.md) — Agent Types list `is_system` badge and topology pending states.
- [Communication Hub](communication-hub-test-plan.md) — `/mcp` protocol server and OAuth middleware.

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| control-center-chatbot | Seeded system assistant agent type; confirmation-before-write; session lifecycle (resume/View All/New/End/Exit + end termination); per-tenant assistant model config; guardrail/timeout/heartbeat handling; `is_system` + `tenant_settings` schema; topology pending states. Toolset/parity detail moved to [Assistant Management Tools](assistant-management-tools-test-plan.md) | 2026-11-02 |
