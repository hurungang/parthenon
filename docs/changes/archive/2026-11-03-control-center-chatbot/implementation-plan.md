# Implementation Plan: Control Center Assistant (Chatbot)

## Overview

Add a conversational "Control Center Assistant" embedded in the Control Center web UI that performs Agents-menu management tasks (create / update / read of skills, SOPs, agent types, roles, identities, model configs, schedules, MCP Hub connections, data types) through natural language. The assistant is a seeded conversational `AgentType` running in Agent Runtime; its management operations are exposed as **MCP tools** on the existing Communication Hub MCP protocol server (`/mcp`), authenticated via **OAuth/OIDC** (the *user's* Bearer token) — one tool surface for both the in-app chatbot and external MCP clients. OAuth is the identity plane: the MCP session authenticates as the user, so every call is authorized by the permission engine against the user's own scope via a tool-to-`(resource_type, action)` parity map. There is no elevated path, and deletion is not a registered tool.

## Task Checklist

### Phase 1 — Schema & Migration
- [x] 1.1 — Add `is_system` boolean flag to `AgentType` model
- [x] 1.2 — Generate and apply the Alembic migration for `is_system`
- [x] 1.3 — Surface `is_system` in AgentType schemas and protect system agent types from user edit/delete

### Phase 2 — OAuth MCP Auth
- [x] 2.1 — Add OIDC Bearer-token validation to the MCP server (parallel to API-key middleware)
- [x] 2.2 — Resolve the user's identity, permissions, and tenant into the MCP session
- [x] 2.3 — Hold the identity token server-side and preserve fail-closed semantics

### Phase 3 — Management MCP Tools
- [x] 3.1 — Define the management-tool → `(resource_type, action)` parity map
- [x] 3.2 — Register create/update/read tools for the nine resource families in `SystemToolRegistry`
- [x] 3.3 — Implement CC write-path handlers for the management tools (no delete)

### Phase 4 — Permission Enforcement
- [x] 4.1 — Filter `tools/list` by the user's permitted parity permissions
- [x] 4.2 — Authorize `tools/call` via the permission engine before dispatch
- [x] 4.3 — Decline delete and out-of-scope requests (no delete tool registered)

### Phase 5 — Seed the Control Center Assistant
- [x] 5.1 — Implement `AssistantSeeder` (system `AgentType` + management tool bindings)
- [x] 5.2 — Author the assistant `system_instruction` and no-delete / scope policy

### Phase 6 — Frontend Entry Point & System-Type Surfacing
- [x] 6.1 — Add the assistant launch entry point in the Control Center UI
- [x] 6.2 — Add i18n strings for the assistant UI
- [x] 6.3 — Surface `is_system` agent types specially in the Agent Types list

### Phase 7 — Tests
- [x] 7.1 — Backend tests (OAuth auth + tool registration + permission parity + schema)
- [x] 7.2 — Frontend tests (entry point + system-type surfacing)
- [x] 7.3 — End-to-end tests (full chatbot journey + external MCP client journey)

### Session persistence & chat rendering
- [x] 8.1 — Assistant entry point resolves the user's most recent ACTIVE conversation session (per tenant + user, scoped server-side) and opens `ConversationDialog` with that `sessionId` to resume; falls back to a new session when none exists or the lookup fails; dialog mounts only after resolution (no empty-conversation flash)
- [x] 8.2 — Verify/keep exit (dialog close) semantics: closing only disconnects the WebSocket client-side; the session stays `active` (no end/archive call) — only the explicit "End session" action ends it
- [x] 8.3 — Render assistant messages via `ContentRenderer` in `auto` mode (markdown/HTML auto-detection, sanitized); user messages remain plain-text bubbles; intervention/chat_blocked/guidance-banner flows untouched
- [x] 8.4 — Vitest coverage: session resolution (latest active / fallback / loading / API failure), resume renders full history, close does not call end/archive, explicit end does, markdown/HTML rendering and plain user bubble
- [x] 8.5 — Update tech-spec (component notes + Code Reference Map) for the frontend changes

### Bounded turns, WS liveness & end-session cleanup (FIX-20261031-091657)
- [x] 8.6 — Bounded LLM calls (AR): `conversation_llm_timeout_seconds` (default 120s) as an asyncio bound around the conversational agent invocation + LangChain client request timeouts; timeout → `timeout_or_failed` + persisted clear error turn
- [x] 8.7 — Bounded whole-turn watchdog (CH): `run_conversation_turn` bounds the entire turn with `agent_question_timeout_seconds` even on the streaming path; watchdog/cancel paths dedupe (no duplicate persistence, no duplicate error after a delivered reply); live reply delivered BEFORE persistence
- [x] 8.8 — WS liveness + diagnostics: `thinking_heartbeat` keepalive (15s) while a turn is in flight; `WebSocketDisconnect` close code+reason logged
- [x] 8.9 — End-session cleanup: `POST /conversations/{id}/end` best-effort terminates in-flight execution via the existing CC → CH → AR termination chain (AR `/terminate` now also cancels conversation turn tasks); never fails the end call
- [x] 8.10 — Force-new after explicit END: per-agent-type flag set by the dialog's end action and consumed (cleared) by `AppShell.openAssistant` on next open; plain exit keeps resume-latest-active (resolver still filters `status === 'active'`)

### Progressive context & knowledge
- [x] 9.1 — Register the assistant meta tools (`invoke_management_tool`, `get_management_tool_schema`, `list_management_tools`, `search_assistant_knowledge`) in `SystemToolRegistry` (no parity; stable UUIDs 055–058; CC endpoint paths under `/internal/management-tools/`)
- [x] 9.2 — CC meta-tool handlers in `management_tools.py` (`meta_router`): wrapper dispatch re-enforcing `_authorize` parity per invocation (no delete path; unknown tool → structured 404), schema-on-demand, cheap catalog, knowledge search
- [x] 9.3 — Author `assistant_knowledge.py`: deterministic keyword-scored corpus of platform domain rules (composition chain, skills-first prerequisite, role/identity assignment, model availability, I/O types, MCP hub, naming uniqueness, no-delete, permission parity); tenant-agnostic, read-only
- [x] 9.4 — `get_agent_context` role-less branch: assistant context carries ONLY the meta tools in `tool_definitions` (execution schemas dropped; meta tools forced into `allowed_tools`)
- [x] 9.5 — `AssistantSeeder`: bind meta tools per tenant alongside the execution tools; concise rule digest in the management skill `instructions` + assistant `system_instruction`; CH user_sub forwarding for meta tools + allowlist entries
- [x] 9.6 — Tests: meta-only context contract (updated FIX-20261031-035145 T1/T2), wrapper dispatch (permitted/denied/delete-shaped/unknown), knowledge search relevance, registry no-parity contract

---

## Phase 1 — Schema & Migration

### Task 1.1 — Add `is_system` boolean flag to `AgentType` model

Add a non-null boolean `is_system` column (default `false`) to the `AgentType` ORM model, mirroring the existing `Skill.is_system` / `Role.is_system` convention. `true` marks a system-provided agent type (the Control Center Assistant) that the UI surfaces specially and that users cannot arbitrarily modify or delete.

**Done when** the `AgentType` model defines `is_system` with default `false`, and the model imports cleanly (no syntax/import errors).

### Task 1.2 — Generate and apply the Alembic migration for `is_system`

Generate the Alembic migration with `alembic revision --autogenerate`, review it (correct `down_revision` chain, reversible `downgrade()`, `server_default` for the new non-null column), apply it with `alembic upgrade head`, and restart backend services.

**Done when** `alembic current` reports the new revision, and a manual query shows `agent_types.is_system` exists with default `false`.

**Additional migration (workflow-generation per-tenant storage):** `6fba31147599` (revising `1a0ed55b8cf1`) creates the `tenant_settings` table — the tenant-scoped key/value store holding the per-workspace workflow-generation model selection (replacing the former global `config/app.yaml` value; a best-effort startup step adopts the legacy yaml value into the ROOT tenant's row).

### Task 1.3 — Surface `is_system` in AgentType schemas and protect system agent types from user edit/delete

Include `is_system` in the `AgentType` read/create/update Pydantic schemas. In the AgentType CRUD endpoints, reject user-driven `update` and `delete` when the target `AgentType.is_system` is `true` (clear 403/422 with an i18n-aware message surfaced via the existing dialog error standard).

**Done when** the Agent Types REST list/detail responses expose `is_system`; update/delete of a `is_system=true` agent type is rejected; non-system agent types are unaffected.

---

## Phase 2 — OAuth MCP Auth

### Task 2.1 — Add OIDC Bearer-token validation to the MCP server (parallel to API-key middleware)

Add an OAuth/OIDC Bearer-token auth path on the MCP protocol server, parallel to the existing `ApiKeyAuthMiddleware`: detect the user's `Authorization: Bearer` token on `/mcp*` paths, validate it against the OIDC provider (reusing the same validation used by the WebSocket chat path), and mark the request as OAuth-authenticated. Keep the API-key path unchanged and additive; the two paths coexist.

**Done when** a valid user Bearer token on `/mcp` is accepted, an invalid/expired token is rejected (401) with a clear message, and the API-key path still works unchanged.

### Task 2.2 — Resolve the user's identity, permissions, and tenant into the MCP session

Resolve the validated token's `sub` to the user's `PlatformUser`, resolve the user's tenant binding, and resolve the user's permission scope (the `agent::*` and `integration::mcp_hub` grants) into the MCP session — the same permission-plane resolution used by `authorize_identity` / `require_permission`. Seed the `McpSession` with this context so `tools/list` and `tools/call` filter and authorize against the user's scope, never an elevated identity.

**Done when** an OAuth-authenticated MCP session carries the user's resolved identity, tenant, and permission scope, and a user with no resolvable `PlatformUser` is denied cleanly (no re-auth bounce).

### Task 2.3 — Hold the identity token server-side and preserve fail-closed semantics

Ensure the user's identity token and any permission/credential material are held server-side only (never serialized into client-visible responses or session objects), and that every MCP transport (Streamable HTTP and SSE) fails closed (401) when no valid OAuth or API-key context is present.

**Done when** no identity token or credential material appears in any client-visible MCP response, and unauthenticated MCP requests are rejected across both transports.

---

## Phase 3 — Management MCP Tools

### Task 3.1 — Define the management-tool → `(resource_type, action)` parity map

Encode, for each management tool, the exact `(resource_type, action)` its corresponding REST endpoint enforces via `require_permission`, so the assistant and external MCP clients can never perform an action the REST API would deny. Reference mapping: skills → `agent::skills`; SOPs → `agent::sops`; agent types, roles, identities, model configs → bare `agent` (`RT_AGENT`, matching `agents.py`); schedules → `agent::schedules`; data types → `agent::data_types`; MCP Hub → `integration::mcp_hub`. Create maps to the endpoint's `create` (or `manage` where the type only declares `manage`); update maps to `update`/`manage`; read maps to `read`. No delete action exists in the map.

**Done when** the map is a single source of truth keyed by tool name, and a review confirms every mapping equals the matching REST endpoint's `require_permission` arguments (verified against `skills.py`, `sops.py`, `agents.py`, `scheduling.py`, `data_types.py`, `mcp_hub.py`).

### Task 3.2 — Register create/update/read tools for the nine resource families in `SystemToolRegistry`

Register each management tool (create/update/list/get across all nine resources, canonical `system____<verb>_<resource>` naming) in `SystemToolRegistry` with a stable unique `mcp_hub_id` (continuing the reserved UUID block), an OpenAI function schema, and its CC endpoint path. Attach each tool's parity `(resource_type, action)`. Do not register any delete tool. Reuse `get_cc_endpoint_map`, `get_all_schemas`, and `get_mcp_hub_entries` for routing/schema/seeding derivation.

**Done when** every management tool is registered and discoverable via `SystemToolRegistry`; no delete tool exists; UUIDs are unique and stable; each tool carries its parity permission.

### Task 3.3 — Implement CC write-path handlers for the management tools (no delete)

Implement the CC-side handlers for each management tool (create/update/read), executed on Control Center (sole DB owner) via the tools' CC endpoint paths, following the existing `SystemToolRequest`/`SystemToolResponse` contract. Validate required fields, reject duplicates (tenant-scoped name uniqueness), reuse the existing write paths, and exclude sensitive material (identity tokens, decrypted MCP/provider credentials) from all results. No delete handler.

**Done when** a permitted create/update persists and reads reflect UI-consistent state; missing fields, duplicates, and permission denials return clear errors with no write; no credential material is echoed.

---

## Phase 4 — Permission Enforcement

### Task 4.1 — Filter `tools/list` by the user's permitted parity permissions

In the permission-filtered catalog, list only the management tools whose parity `(resource_type, action)` the authenticated user can satisfy, evaluated by the permission engine (deny-by-default, wildcards such as `agent::*` respected). Out-of-scope tools are omitted from the catalog entirely.

**Done when** a `tools/list` for a permission-restricted user returns only the management tools that user may invoke, and a fully-permitted user sees the full management toolset.

### Task 4.2 — Authorize `tools/call` via the permission engine before dispatch

Before dispatching a management `tools/call`, re-check the tool's parity `(resource_type, action)` against the user's permission scope via the permission engine. When `authorize` returns `allowed=false`, return a structured permission-denied result (no action, no partial write) that the caller can relay.

**Done when** a permission-denied `tools/call` produces a structured, non-mutating denial carrying the reason, and a permitted call dispatches to CC.

### Task 4.3 — Decline delete and out-of-scope requests (no delete tool registered)

Ensure no delete tool is registered and that any delete verb or request for a resource outside the mapped management scope is declined in-band before any write (a defense-in-depth backstop on top of the absent registration). The denial carries a fixed "deletion not supported" / "out of scope" reason.

**Done when** a delete verb and an out-of-scope resource each produce a structured, non-mutating denial result with a reason the assistant can relay to the user.

---

## Phase 5 — Seed the Control Center Assistant

### Task 5.1 — Implement `AssistantSeeder` (system `AgentType` + management tool bindings)

Create an idempotent seeder that provisions the Control Center Assistant `AgentType` (conversational input, `is_system=true`, bound identity/role/model) and binds the management tools to it, following the `SkillSeeder` / `SystemToolRegistry` pattern (system skills marked `is_system`). The assistant is tenant-bound: the seeder provisions every tenant and never binds a model (per-tenant model selection is configured through the assistant-model endpoints).

**Done when** the assistant agent type and its management tool bindings are seeded idempotently for every tenant (root-tenant behaviour preserved when multi-tenancy is off) and are marked system-protected.

### Task 5.2 — Author the assistant `system_instruction` and no-delete / scope policy

Author the assistant's `system_instruction` constraining it to the Agents-menu management scope, instructing it to decline deletion and out-of-scope requests, and to act strictly on behalf of the authenticated user within that user's permission scope.

**Done when** the seeded instruction text encodes the scope, no-delete, and delegated-action rules, and a review confirms the assistant surface reflects them.

---

## Phase 6 — Frontend Entry Point & System-Type Surfacing

### Task 6.1 — Add the assistant launch entry point in the Control Center UI

Add an assistant entry point (floating action / menu item in the Control Center shell) that resolves the seeded assistant `AgentType` (by `is_system=true`) and opens the existing `ConversationDialog` with that `agentTypeId`. Reuse the existing WebSocket chat path and session lifecycle; no new forms/dialogs. When the assistant's model is not configured for the tenant (`GET /agents/model-configs/assistant-model` returns `selected_model_id: null`, or the backend surfaces the structured `assistant_model_not_configured` chat error), the chat surface shows setup guidance (MUI Alert + "Configure model" action navigating to `/system-config`) and disables the input instead of failing at runtime. Backend guard: `ws/chat.py` maps AR's pre-model "Agent model is not configured" rejection onto the typed `assistant_model_not_configured` chat-error payload.

**Done when** a logged-in user can open the assistant from the Control Center UI and converse; the assistant resolves to the seeded system agent type; an unconfigured model yields actionable guidance (banner + navigation + disabled input) rather than a runtime error.

### Task 6.2 — Add i18n strings for the assistant UI

Add all assistant-specific UI text (launcher label, empty-state, scope/delete-declined messages, model-unconfigured guidance strings under `assistant.*`) through the i18n `t()` function — no hardcoded strings — following the existing dialog/alert error-handling standard.

**Done when** all new UI strings route through i18n keys, and permission-denied/not-supported responses surface via the existing `PermissionDeniedAlert` pattern.

### Task 6.3 — Surface `is_system` agent types specially in the Agent Types list

Update the Agent Types list/table to visibly mark system agent types (`is_system=true`) and disable user edit/delete controls for them, matching the backend protection added in Task 1.3.

**Done when** the Control Center Assistant is visibly marked as system-provided and its edit/delete controls are disabled.

---

## Phase 7 — Tests

### Task 7.1 — Backend tests (OAuth auth + tool registration + permission parity + schema)

Backend unit and integration tests covering: OAuth/OIDC Bearer-token validation on `/mcp` (accept/deny, server-side token holding), management tool registration in `SystemToolRegistry` (no delete, stable UUIDs, parity attached), permission parity (each tool maps to its REST-equivalent `(resource_type, action)`; a permitted action succeeds; a denied action is declined; delete/out-of-scope is always declined), and the `is_system` schema change (column present, system agent types protected from edit/delete).

**Done when** backend tests pass against a real migrated database, including the OAuth-auth, tool-registration, permission-parity, and schema assertions.

### Task 7.2 — Frontend tests (entry point + system-type surfacing)

Frontend tests for the assistant entry point (renders, opens `ConversationDialog`), the `is_system` special marking, and the i18n / permission-denied surfacing.

**Done when** frontend tests pass (Vitest) covering the new entry point and system-type surfacing.

### Task 7.3 — End-to-end tests (full chatbot journey + external MCP client journey)

End-to-end tests covering the full in-app chatbot journey (open assistant → natural-language create/update/read → resource reflects in the UI) and the external MCP client journey (authenticate with the user's OAuth credentials → `tools/list` is permission-filtered → `tools/call` enforces parity). Include at least one real-backend variant (no mocks) so the OAuth/MCP path is exercised against live services.

**Done when** e2e tests pass for both consumer journeys, including a real-backend variant, and both surfaces enforce the same permission scope.

---

## Phase 9 — Progressive Context & Knowledge

### Task 9.1–9.6 — O(1) tool context + knowledge base (done)

Per-turn LLM context for the assistant carries ONLY the four constant meta tools instead of all ~36 management execution schemas. `invoke_management_tool` dispatches in-process through the existing `management_tools._dispatch` with per-invocation `_authorize` parity (delete-shaped and unknown targets declined); `get_management_tool_schema` / `list_management_tools` provide on-demand schema/catalog; `search_assistant_knowledge` serves platform domain rules from `assistant_knowledge.py` (deterministic keyword scoring, tenant-agnostic). The seeder binds meta tools per tenant and seeds a concise rule digest into the management skill instructions + assistant system instruction. Tests: `tests/integration/test_assistant_meta_tools.py`, `tests/unit/test_assistant_knowledge.py`, updated `tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py`.

**Done when** context assertion (meta-only `tool_definitions`), wrapper dispatch (permitted end-to-end / 403 parity denial / delete declined / unknown 404), and knowledge-relevance tests pass; tenant isolation sweep green.

---

## Phase 10 — Confirmation-before-write + agent-creation completeness (FIX-20261031-133253)

### Task 10.1 — Expose `human_intervene` to the assistant (done)

`human_intervene` added to `_META_MANAGEMENT_TOOL_NAMES` (5th always-loaded meta definition; no parity). Per-tenant seeding, binding, and CH routing (user-sub forwarding) verified.

### Task 10.2 — Conversational HITL round-trip (done)

`conversation_resume` registry (AR, in-process, per conversation session); CC `human_intervene` accepts conversation-only sessions (nullable `agent_session_id`, migration `a1c3e5d70427`); AR `/internal/resume` resolves the pending future before the job-relaunch fallback; `LangChainHumanInterveneTool` awaits the operator on conversational turns (no LangGraph `interrupt()` — its Command-resume replay re-registered duplicates) and returns the operator response or an explicit `status:"timeout"` not-executed result. Task-agent interrupt flow unchanged. CC replay idempotency: same conversation+reason → pending dedupe / responded returns the operator response. `InterveneRequest` prompt folded into `reason` so markdown previews reach the WS UI.

### Task 10.3 — Turn-bound co-existence (done)

Strict FIX-091657 `conversation_llm_timeout_seconds` preserved; the executor re-arms the wait ONLY while an intervention is pending, up to the new `conversation_intervention_timeout_seconds` (default 240s, below the CH turn watchdog). Legacy GraphInterrupt fallbacks converted to wait-and-resume instead of swallowing.

### Task 10.4 — Knowledge + instruction hard rules (done)

`confirm-before-write` (markdown table preview + `human_intervene` approval before ANY create/update; reads unaffected; rejection → do not execute), `agent-creation-completeness` (discover → reuse/create identity+role → grant skills via `update_agent_role` → enabled model only → preview MUST show model/identity/role/skills/grants → never create a non-functional shell), `creation-payload-completeness` (all required fields in every preview). Assistant instruction rules 2d/2e; shared `MANAGEMENT_SKILL_INSTRUCTIONS` so pre-fix seeded rows refresh.

### Task 10.5 — Frontend preview rendering (done)

`InlineInterventionDialog` renders `reason` via `ContentRenderer` (GFM tables); Approve/Deny unchanged (`intervene_response` flow).

### Task 10.6 — Tests + live verification (done)

20 new backend tests + 2 frontend tests (see `test-plan.md`); live WS verification `scripts/fix-20261031-133253-live.cjs` (LIVE-VERIFICATION-PASSED: preview table → approve → real `create_agent_type` executed).

---

## Completion Checklist

- [x] `AgentType.is_system` added and migrated; system agent types protected from user edit/delete
- [x] OAuth/OIDC Bearer-token auth added to the MCP server (parallel to API keys), resolving the user's identity, permission scope, and tenant into the session; token held server-side
- [x] Management MCP tools registered for the nine resource families, each carrying its parity `(resource_type, action)`
- [x] Permission parity enforced at `tools/list` and `tools/call` via the permission engine; no delete tool exists and out-of-scope is declined
- [x] Control Center Assistant seeded as a system `AgentType` with management tool bindings and a constrained `system_instruction`
- [x] Assistant entry point present in the Control Center UI with i18n text and system-type surfacing
- [x] Backend, frontend, and end-to-end tests pass (both chatbot and external MCP client journeys)
- [x] `agent::*` resource-type manifest and frontend mirror remain consistent (no new resource types required)
- [x] Top-priority rules honored: services segregated, agents run only in AR, only CC touches the DB, no sensitive data crosses service boundaries
- [x] FIX-20261031-133253: mandatory confirmation with markdown table preview before create/update (human_intervene exposed, conversational HITL round-trip, replay idempotency) + agent-creation completeness workflow in knowledge/instruction; live WS verification passed

---

## Phase 11 — `cc____` namespace, Control Center MCP entity, Skill↔tool bindings (FIX-20261101-000319)

### Task 11.1 — `cc____` namespace + category-aware registry (done)

`SystemTool.category` (`"general"` | `"management"`); the 36 management execution tools + 4 meta tools are `category="management"` with canonical `cc____<bare>`; general tools untouched (`system____save_data` etc.). `cc` added to `RESERVED_SERVER_NAMES`; `is_cc_tool()` added; legacy bare names parse category-aware. `get_mcp_hub_entries()` → general only (management no longer auto-seeds into the generic System entity); `get_cc_mcp_hub_entries()` added; `get_cc_endpoint_map` / parity map mechanics unchanged.

### Task 11.2 — Control Center MCP entity + migration (done)

Per-tenant "Control Center" `McpServer` (slug `cc`, new reserved uuid5 identity `parthenon:cc-server:<tenant>`) + per-tenant `cc____<bare>` `McpTool` rows, provisioned idempotently by `AssistantSeeder`. Migration: `_retire_legacy_management_rows` deletes legacy `system____<mgmt>` rows and their bindings, the management skill rebinds to the new rows, general `system____` rows untouched; `seed_system_tools` retires the global System entity's legacy rows (pure SQL, idempotent). No schema migration required (rows are data). `cc` rejected as a registerable server slug.

### Task 11.3 — First-class grantability + routing (done)

OAuth resolve returns `cc____` canonical names; the bridge lists `cc____` tools exactly when granted and dispatches them through the management handler with per-call parity re-enforcement (ungranted → not listed / structured denial / `PermissionError`; `cc____delete_*` declined). `system____` routing unchanged; CH internal routing treats `cc____` as the built-in system path. Assistant context uses category-aware canonical names (sanitised definitions + populated `tool_name_map`); the `human_intervene` HITL special-case matches the sanitised name (confirmation/HITL flow unchanged).

### Task 11.4 — Skill ↔ tool association (done)

`create_skill` / `update_skill` accept `tool_ids` / `tool_names` (canonical `server____tool` names or UUIDs, tenant-scoped): create = bind all; update = ADDITIVE MERGE (never removes, idempotent re-bind); resolve-before-write (unknown tool → structured 404, no partial write). `get_mcp_server` returns its synced `tools` for discovery. Schemas enriched; assistant instruction rule 2f + `MANAGEMENT_SKILL_INSTRUCTIONS` + new knowledge entry `skill-tool-binding` pin the workflow (discover → bind at creation; skills without bindings cannot do anything; `cc____` tools are Control Center capabilities granted deliberately).

### Task 11.5 — Tests + live verification (done)

40 new tests (naming/registry, seeder migration, bridge grantability/parity, skill bindings + discovery + knowledge; TDD failing-first); prior-fix suites updated to the new canonical names; confirmation/HITL, timeouts/watchdog, role-grant, agent-type-binding and cert-path suites green; tenant isolation verified. Live WS verification `scripts/fix-20261101-000319-live.cjs` (LIVE-VERIFICATION-PASSED: skill created WITH its `SkillToolBinding` via a real turn; cc entity present with management tools and no general tools; a non-granted role sees no `cc____` tools).

## Phase 12 — `integration::control_center` entity-view permission (FIX-20261101-014511)

### Task 12.1 — RT registration (done)
`RT_INTEGRATION_CONTROL_CENTER = "integration::control_center"` (read, manage) in the backend manifest + `MODULE_GROUPS["integration"]`, mirrored in `frontend/src/constants/resourceTypes.ts` (manifest + integrations submodules). Mirror-consistency tests updated.

### Task 12.2 — MCP Hub REST enforcement (done)
`_gate_cc_server`/`_require_cc_permission`/`_cc_tool_gate` via the new `identity_has_permission` probe: list filtering, 404-without-leak detail/tool reads, structured 403s for cc mutations and tool grants; non-cc servers untouched.

### Task 12.3 — Management toolset filtering (done)
`list_mcp_servers` omits `cc` and `get_mcp_server(cc)` 404s when the triggering user lacks `integration::control_center:read`.

### Task 12.4 — Frontend gating (done)
`McpHubPage` protected chip + `PermissionDeniedAlert` surfacing for row-level 403s; i18n strings; cc hidden by the API-filtered list without the grant.

### Task 12.5 — Tests + verification (done)
New `test_cc_integration_permission.py` (TDD red→green), McpHubPage gating tests, full targeted backend + frontend runs + `tsc --noEmit` green (pre-existing failures verified on a clean HEAD worktree, not regressed).

## Phase 13 — Iteration budget, guardrail error clarity, chat action bar (FIX-20261101-111439)

### Task 13.1 — Assistant iteration budget (done)
`ASSISTANT_GUARDRAIL_MAX_ITERATIONS = 24` in `assistant_seeder.py`; set on create and refreshed
in the update branch (stale rows carrying the default 10 are upgraded at seed time). 24 ≈ 2×
headroom over the documented agent-creation workflow's 11+ tool iterations; per-agent-type
resolution via the agent-context `guardrail_policy` (both `GuardrailCallback` and the inline
executor checks read it).

### Task 13.2 — Guardrail stop → clear persisted error turn (done)
AR conversation endpoint forwards `{error_type, error_details}` on the streaming error chunk;
CH maps `iteration_limit` to a structured `ConversationTurnError` ("This task needed more steps
than allowed (limit N). …") and persists the error turn (status event + agent message) following
the `timeout_or_failed` pattern; other guardrail reasons map generically.

### Task 13.3 — Chat action bar (done)
`ConversationDialog.tsx` footer → 4-option action bar for ALL conversational agents: View All
Sessions (`SessionSwitcherList`, in-place resume switch), New Session (fresh session without
end/archive, current stays `active`, no force-new flag), End Session (unchanged), Exit
(unchanged). Streaming-blocked states via `turnStreaming`. i18n keys added.

### Task 13.4 — Tests + verification (done)
Failing-first: `test_assistant_seeder.py` budget tests, new
`test_fix_20261101_111439_iteration_limit.py` (AR reason forwarding + CH mapping + persisted
error turn), `ConversationDialog.actionBar.test.tsx` (6 tests). Regressions green: backend
communication-hub + guardrail/executor/HITL/confirm suites (181 passed, 6 skipped; the 2
tenant-header failures pre-exist at HEAD, verified on a clean worktree), frontend
ConversationDialog/AppShell suites (66 passed), full vitest 1798 passed / 0 failed / 18 skipped,
`tsc --noEmit` clean.

## Phase 14 — Built-in inherent skills (FIX-20261101-120618 Work Item 2)

### Task 14.1 — Inherent skill registry module (done)
`backend/app/services/agents/builtin_skills.py` (new): `self-context` +
`workflow-optimization` definitions over the 9 optimization system tools, derived from
`SystemToolRegistry` (fail-closed on drift), deterministic uuid5 skill ids, canonical
`system____` names.

### Task 14.2 — Dynamic context injection (done)
`get_agent_context` (`backend/app/api/v1/internal/agent_data.py`) injects the inherent set
AFTER both role'd / role-less branches: `allowed_tools` gains the canonical names (existing
system-schema loop emits the definitions), skills summary gains both inherent skills. Zero
per-agent rows, zero configuration; guardrails/sandboxing/confirmation semantics unchanged.

### Task 14.3 — Tests + verification (done)
Failing-first `test_fix_20261101_120618_inherent_skills.py` (5 tests). Deliberate contract
updates: FIX-035145 T1, FIX-133253 human_intervene context test, tool-naming no-auto-injection
tests. Regressions: communication_hub, meta-tools, seeder, cc-naming/bridge, role service,
cc permission, tenant isolation, unit/integration/agent_runtime/security suites.

## Phase 15 — View All Sessions upgrades + sessions list API (FIX-20261101-120618 Work Item 1)

### Task 15.1 — Configurable default query window (done)
`backend/app/core/config.py`: `conversation_sessions_default_window_days: int = 7`
(env `CONVERSATION_SESSIONS_DEFAULT_WINDOW_DAYS`), following the existing Settings
conventions.

### Task 15.2 — Paginated sessions endpoint (done)
`ConversationStore.list_sessions_page` (`backend/app/services/conversations/store.py`):
status filter (`active` / `ended` = closed+archived+error / `all`), `date_from`/`date_to`,
default lower bound = now − configured window when no explicit range and not `all_time`,
`updated_at` DESC, `page`/`page_size`, full filtered `total`. New
`GET /conversations/sessions` (`backend/app/api/v1/conversations.py`) +
`ConversationSessionPageRead` (`{items, total, page, page_size, default_window_days}`);
legacy `GET /conversations` unchanged (backward compat). Tenant-scoped as today.

### Task 15.3 — View All Sessions upgrades (done)
`useConversationSessionsPage` hook (`frontend/src/hooks/useConversationSessions.ts`);
`SessionSwitcherList` in `frontend/src/components/agents/ConversationDialog.tsx` upgraded to
the sessions-tab experience: active/ended Switch (default active-only → `status=active`;
on → `status=all`), From/To date inputs defaulting to the last-7-days window
(`DEFAULT_SESSIONS_WINDOW_DAYS` mirrors the backend setting), pagination (page size 10,
`total`-driven), time-desc rows with title/status/updated time; ended sessions carry an
"Ended" chip and are not resumable; active sessions keep the FIX-111439 in-place resume
switch (never end/archive). New i18n keys: `conversations.sessions.showEnded`, `dateFrom`,
`dateTo`, `endedTag` (`frontend/src/i18n/locales/en.json`).

### Task 15.4 — Tests + verification (done)
Failing-first: `backend/tests/integration/test_conversations_sessions_query.py` (13 tests),
`frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx` (6 tests). Regressions:
conversations/session-lifecycle suites, ConversationDialog suites (actionBar /
assistantChat / resumeLiveDelivery / intervention), AppShell session tests, ConversationSessionsTab.
Full vitest 1804 passed / 0 failed; `tsc --noEmit` clean. See fix-log for numbers.

---

## Phase 16 — FIX-20261101-223511 (binding visibility + zero-binding guard + canonical preview + expand card)

16.1 Management toolset: `_attach_skill_tool_bindings` (+ `_count_skill_bindings`) wired into
list/get/create/update for skills; `ZERO_BINDING_WARNING` on zero-binding create/update.
16.2 REST schema: `SkillRead.tool_bindings` via detached snapshot validator;
`selectinload(McpTool.server)` load option.
16.3 Knowledge: `confirmation-preview-format` entry; extended `skill-tool-binding` (guard rule)
and `confirm-before-write` (canonical layout); seeder instructions 2e/2f +
`MANAGEMENT_SKILL_INSTRUCTIONS`.
16.4 Frontend: SkillListPage tool chips / "No tools bound" chip; `SkillToolBindingInfo` type;
InlineInterventionDialog expand/collapse dialog; i18n keys.
16.5 Tests: failing-first `test_fix_20261101_223511_skill_bindings_visibility.py` (8),
`SkillsToolBindingsVisibility.test.tsx` (3), `InlineInterventionDialog.expand.test.tsx` (6);
regression suites + full vitest + tsc clean; live scripted verification PASSED
(`scripts/fix-20261101-223511-live.cjs`).

---

## Phase 17 — FIX-20261102-062047 (single tool surface + complete, permission-correct listing)

17.1 Backend listing contract (`mcp_hub.py`): `/mcp/tools` default `limit`
200, permission-filter → dedupe → full-set sort `(server_slug, name, id)` →
slice, `X-Total-Count`; `/mcp/servers` filters system/decision + cc IN the
query before `offset/limit`, deterministic `(name, id)`, virtual servers in the
full ordering, `X-Total-Count`; new `GET /mcp/tools/{tool_id}` individual
resolution with the referenced-cc read-only rule (`_tool_referenced_by_skill`).
17.2 Schema: `SkillToolBindingRead.tool_id`; CORS exposes `X-Total-Count`.
17.3 Frontend hooks: `useAllTools`/`useMcpServers` page the complete set (200
per page); explicit paging unchanged.
17.4 `SkillEditor`: single selection state + grouped list (display & editor),
detail-authoritative init with dirty guard, binding-derived pinned read-only
entries, picker "Referenced (read-only)" group, duplicate Bound Tools card
removed; view mode = same list; i18n keys.
17.5 Tests: failing-first `test_fix_20261102_062047_mcp_tool_listing.py` (11),
`SkillEditor.singleSurface.test.tsx` (6), `useMcpServers.pagination.test.tsx`
(3); regression suites + `tsc --noEmit`; live probe script
`scripts/fix-20261102-062047-probe.cjs` → LIVE-PROBE-PASSED; stack restarted
healthy.
