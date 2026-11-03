# Test Plan: Control Center Assistant (Chatbot)

> Change: `control-center-chatbot` — `has_db_changes: true` (single `AgentType.is_system` boolean). Scope flags: `has_ui_changes`, `has_architecture_changes`, `has_operations_changes`.

## Pre-Test Checklist (Database Change — REQUIRED)

Run before any backend/E2E execution:

- [ ] Confirm migration applied: `cd backend && python -m alembic current` shows the `is_system` migration revision (latest in `backend/alembic/versions/`).
- [ ] If not applied: `python -m alembic upgrade head`.
- [ ] Backend DB fixture uses a schema matching production (SQLite `Base.metadata.create_all` for unit; real PostgreSQL `parthenon_test` for schema/`information_schema` probes — see `backend/tests/conftest.py`).
- [ ] DB-dependent tests registered in `backend/tests/conftest.py` (`_DB_DEPENDENT_FILES` / `_DB_DEPENDENT_TESTS`) so the `is_system` schema probe runs only against real PostgreSQL.
- [ ] Restart backend after migration (ORM models cached at startup): `./scripts/restart-backend.sh`.
- [ ] Confirm `is_system` column is `boolean NOT NULL DEFAULT false` on `agent_types` before running the negative protection tests.

---

## 1. Test Strategy

| Layer | Approach | Scope |
|---|---|---|
| **Unit (backend)** | MCP tool-catalog filtering, `tools/call` authorization parity, management-tool registration, permission-parity map, `is_system` edit/delete protection rules — no I/O beyond in-memory fixtures | `backend/tests/unit/` |
| **Integration (backend)** | ASGI test client + SQLite for OAuth Bearer-token auth and `tools/list`/`tools/call` flows; real PostgreSQL probes for schema verification (`information_schema`) | `backend/tests/integration/`, `backend/tests/db/` |
| **Integration (backend, DB)** | Verify `is_system` schema change took effect + negative protection (attempt edit/delete of a system agent type) | `backend/tests/db/` |
| **E2E** | Playwright with `page.route()` mocks for speed; **at least one real-backend (no-mock) variant** for the migration + live OAuth→MCP→CC path; one external-MCP-client variant proving UI/MCP parity | `e2e/tests/` |
| **Manual** | Conversational UX sanity, i18n text, thinking/working indicators, sensitive-data non-disclosure spot-checks | checklist only |

**Key risk addressed by layering:** management operations now live behind OAuth/OIDC-authenticated MCP tools on the CH `/mcp` protocol server. The OAuth→`tools/list`→`tools/call`→CC path and the `is_system` migration can pass with mocked backends while the real auth/migration is broken — hence the mandatory real-backend E2E variant, the external-MCP-client parity variant, and the `information_schema` probes.

---

## 2. Coverage Areas

### OAuth/OIDC authentication on the MCP server (`/mcp`)
- Management tools are reachable only behind the CH MCP protocol server (`/mcp`), authenticated by the *user's* OAuth/OIDC Bearer token.
- Valid token → session established with the user's resolved identity + permission set; invalid/expired token → 401; missing token → 401.
- The session binds to the authenticated user's subject — no separate service/elevated identity, no agent-realm identity.

### Permission-filtered `tools/list`
- The catalog returned to a client contains only tools the authenticated user is permitted to use (no elevation, no leakage of unavailable tools).
- Each management tool appears only when the user holds the mapped `(resource_type, action)` permission.

### `tools/call` authorization parity
- A permitted action (create/update/read within the user's grant) succeeds and is attributed to the user.
- A non-permitted action is denied with a clear error and no write occurs.
- Delete is always declined (no delete tools registered; delete-shaped calls fail closed).
- Parity is exact between each management MCP tool and its REST `require_permission` counterpart.

### Management toolset (create/update/read, nine families)
- Skills, SOPs, Agent Types, Agent Roles, Agent Identities, Model Configs, Schedules, Data Types, MCP Hub connections.
- Each: create → appears in list with correct values; update → visible immediately without page reload; read/query → accurate vs UI.
- Duplicate identifiers rejected; missing/invalid required fields produce a clear validation message and no write.

### Same security layer for UI and MCP (parity guarantee)
- The in-app chatbot (seeded `AgentType`, `is_system=true`) and an external MCP client using the user's OAuth credentials resolve to the **same** permission engine and the **same** management tools — identical allow/deny outcomes for identical inputs.

### Schema (`AgentType.is_system`)
- Column exists, `boolean`, `NOT NULL`, default `false` (query `information_schema`).
- Migrations apply cleanly (`upgrade head`); downgrade reversible.
- System agent types are protected from user edit/delete (backend + UI).
- Non-system agent types remain editable/deletable (regression).

### Sensitive-data boundary (top-priority rules)
- Identity tokens, DB credentials, decrypted MCP/provider credentials never cross the service boundary and never echo into MCP `tools/call` results or conversation responses.

### Conversational UX / attribution
- Assistant entry point resolves the seeded system `AgentType` and opens `ConversationDialog`.
- Actions are attributed to the authenticated user (whose OAuth token established the session) in audit/tool-call records.
- Multi-turn context; thinking/working indicators reused.
- `is_system` agent types marked specially in the Agent Types list; edit/delete controls disabled.

---

## 3. Critical Scenarios (WHEN/THEN)

**OAuth authentication (MCP server)**
- WHEN a client calls `POST /mcp` with a valid user OAuth Bearer token — THEN the request is accepted and a session is established with the user's resolved identity and permission set.
- WHEN a client calls `/mcp` with no token — THEN the request is rejected (401) with no session and no tool catalog exposed.
- WHEN a client calls `/mcp` with an invalid or expired token — THEN the request is rejected (401) and no tools are callable.
- WHEN a client calls `/mcp` with a token for an identity that is not a platform user — THEN the request is rejected (401) and the session never binds a subject.

**Permission-filtered `tools/list`**
- WHEN a user with only `agent::skills` create/update/read permissions calls `tools/list` — THEN the catalog includes the skill management tools and excludes SOPs, schedules, data types, and MCP Hub tools.
- WHEN a user with no `agent`/`agent::*`/`integration::mcp_hub` grants calls `tools/list` — THEN the management tools are absent from the catalog (only the shared meta tool, e.g. `load_skills`, remains).
- WHEN an admin with wildcard grants (`agent::*`, `integration::*`) calls `tools/list` — THEN all permitted management tools are present.

**`tools/call` authorization parity**
- WHEN a user with `agent::skills` create calls the create-skill tool — THEN the action succeeds and the skill is created (parity with the REST `agent::skills` create endpoint).
- WHEN a user *without* `agent::skills` create calls the create-skill tool — THEN the call is denied with a clear permission error and no skill is created.
- WHEN a user calls the update-agent-type tool — THEN authorization is evaluated against bare `agent` update, exactly as the REST endpoint.
- WHEN a user calls the manage-schedule tool — THEN authorization is evaluated against `agent::schedules`, not `agent`.
- WHEN a user calls the manage-MCP-Hub tool — THEN authorization is evaluated against `integration::mcp_hub`, not `agent`.
- WHEN a user calls the manage-data-type tool — THEN authorization is evaluated against `agent::data_types`.
- WHEN an admin with wildcard grants performs any permitted action — THEN it succeeds but remains attributed to that user (never a privileged/service identity).

**Deletion & out-of-scope (defense-in-depth)**
- WHEN a client calls `tools/list` — THEN no delete-shaped management tool appears in the catalog.
- WHEN a client attempts a delete-shaped `tools/call` (delete skill/SOP/agent type/role/identity/model config/schedule/data type/MCP connection) — THEN the call is declined with a "not supported" result and nothing is deleted.
- WHEN a client invokes a tool outside the Agents management scope (e.g. system or other integration modules) — THEN it is absent from the catalog and, if invoked directly, is denied with a clear message and no action taken.

**Schema protection**
- WHEN a system agent type (`is_system=true`) is targeted for edit or delete via the REST API — THEN the request is rejected (403).
- WHEN the same system agent type is listed in the Agent Types UI — THEN it is marked as system and its edit/delete controls are disabled.

**Sensitive data**
- WHEN a read tool returns an agent identity or model config — THEN identity tokens / decrypted credentials are excluded from the result.
- WHEN any management tool result is serialized — THEN no secret material crosses the CH↔CC boundary or appears in the MCP result or chat.

**Tool context on the conversational delegation path (FIX-20261031-035145)**
- WHEN a conversational agent type WITHOUT a role (the assistant) requests its execution context (`GET /internal/data/agent-types/{id}/context`) — THEN `allowed_tools` contains the bound skill's canonical management tools (e.g. `system____create_skill`) and `tool_definitions` carries their function schemas; the toolset is NEVER empty.
- WHEN a tenant's management skill starts with zero `McpTool` rows — THEN `AssistantSeeder` self-seeds the per-tenant rows (deterministic uuid5 ids, `system____<bare>` names) plus the per-tenant `system` server mirror and binds all 36 tools; re-running is idempotent (no duplicates).
- WHEN the assistant is asked to create a resource and the management tool is unavailable or errors — THEN the assistant reports the failure plainly (system-instruction rule 6) and NEVER claims success without a successful tool result.

**Attribution**
- WHEN the chatbot performs an action — THEN the resulting audit/tool-call record attributes the action to the authenticated user (the OAuth token subject), not a service identity.
- WHEN an external MCP client performs the same action with the user's OAuth credentials — THEN the audit record attributes it to the same user.

---

## 4. Edge Cases & Risks

- **Permission parity drift** — a management MCP tool enforced against a different `(resource_type, action)` than its REST twin. Risk: elevation/under-permission. Mitigate: parity-map unit test asserting equality per tool.
- **Delete smuggling** — a create/update payload that attempts to delete referenced sub-resources. Risk: unintended destructive writes. Mitigate: no delete tools + guard rejects delete intent.
- **Token-to-subject mismatch** — the MCP session binding a token to the wrong user (or a service/agent identity). Risk: elevation. Mitigate: auth tests asserting subject resolution + no elevated path.
- **Catalog leakage** — `tools/list` returning tools the user cannot invoke. Risk: information disclosure of unavailable management surface. Mitigate: permission-filtered catalog tests.
- **Cross-tenant leakage** — management tool dispatch resolving in the wrong tenant (signed `X-Internal-Tenant-*` not forwarded). Mitigate: fail-closed header tests.
- **`is_system` default regression** — column added nullable in migration but model expects `NOT NULL`. Risk: existing rows NULL. Mitigate: `information_schema` nullable probe + backfill check.
- **Sensitive echo via `tools/call` result** — a read handler accidentally serializing encrypted fields into the MCP result/audit. Mitigate: sensitive-field exclusion tests.
- **Seeding idempotency** — `AssistantSeeder` running twice must not duplicate the assistant `AgentType`/skills.
- **Tool-name collision** — management tool names colliding with existing `save_data`/`get_data`/proxied namespaces. Mitigate: registry name-validation test.
- **Conversational context resolution** — follow-up reference ("change that one's schedule") resolving to the wrong resource across turns.

---

## 5. Acceptance Criteria Checklist (maps to PRD)

**Assistant Availability & Scope**
- [ ] Assistant available to logged-in users in the Control Center UI.
- [ ] Scope limited to `agent::*` + `integration::mcp_hub`; other module groups declined with clear message.
- [ ] Deletion requests declined with clear "not supported" message.

**Create**
- [ ] Create Skill / SOP / Agent Type / Role / Identity / Model Config / Schedule / MCP Hub / Data Type → appears in respective list with correct field values.
- [ ] Missing/invalid required fields → clear validation message, no resource created.
- [ ] Duplicate identifiers rejected with clear error surfaced in conversation.

**Update / Configure**
- [ ] Update/reconfigure existing resource → changes saved and visible in UI without manual reload.
- [ ] Related counts/badges update after a change.

**Read / Query**
- [ ] Query current configuration → accurate and consistent with the UI.

**OAuth + Permission Inheritance & No Elevation (critical)**
- [ ] `POST /mcp` accepts a valid user OAuth Bearer token; rejects missing/invalid/expired tokens with 401.
- [ ] `tools/list` returns only tools the authenticated user may use.
- [ ] `tools/call` enforces exact `(resource_type, action)` parity with REST; permitted action succeeds, non-permitted denied.
- [ ] Actions attributed to the authenticated user (audit/history), never a privileged/service identity.
- [ ] External MCP client using the user's OAuth credentials is bound to the same security layer as the in-app chatbot.
- [ ] Assistant never exposes sensitive data (identity tokens, DB credentials, decrypted MCP credentials) beyond the user's entitlement.

**Conversational Behavior**
- [ ] Maintains context across multiple turns (follow-up references resolve correctly).
- [ ] Behavior aligns with existing conversational experience (thinking/working indicators, per-turn visibility).

**Database Change (additional)**
- [ ] `agent_types.is_system` column exists, `boolean NOT NULL DEFAULT false`.
- [ ] System agent types protected from user edit/delete (API rejects; UI disables controls).

---

## 6. Test File References

Paths relative to workspace root under the `source.tests` dirs. **N** = new file; **E** = extended existing file. This is the as-implemented list (Phase 7).

### Backend — unit (`backend/tests/unit/`)
- **N** `backend/tests/unit/test_management_mcp_tools.py` — 36 management tools (9 families × create/update/list/get), stable reserved UUIDs (019–054), no delete verb, every tool carries a `parity` tuple; OpenAI-function schemas; name validation.
- **N** `backend/tests/unit/test_management_tool_permission_parity.py` — `get_parity_map()` equals the authoritative REST `require_permission` pairs (skills→`agent::skills`, SOPs→`agent::sops`, agent types/roles/identities/model configs→bare `agent`, schedules→`agent::schedules`, data types→`agent::data_types`, MCP Hub→`integration::mcp_hub`); deny-by-default; every parity type/action declared in the manifest.
- **N** `backend/tests/unit/test_oauth_bearer_auth.py` — `OAuthBearerAuthMiddleware` fail-closed gate: `_extract_bearer`/`_looks_like_jwt` classification; missing/non-JWT/API-key fall-through; invalid/expired/subject-less/unresolvable → 401; valid token seeds `auth_method`/`user_sub`/`platform_user_id`/`permissions`/`tenant_id` and never surfaces the identity token.
- **N** `backend/tests/unit/test_assistant_seeder.py` — `AssistantSeeder` idempotency (one assistant `AgentType` + one management `Skill`, `is_system=true` conversational, upgrade-in-place of a mutated row).
- **E** `backend/tests/unit/test_tool_registry_bridge.py` — OAuth permission-filtered catalog (management tools only, no `load_skills`), in-band `permission_denied`/`deletion_not_supported`/`out_of_scope` denials, management-tool routing forwards `user_sub` (never `identity_token`).

### Backend — integration (`backend/tests/integration/`)
- **N** `backend/tests/integration/test_mcp_oauth_bearer_auth.py` — real `OAuthBearerAuthMiddleware` + `handle_streamable_http` on a minimal ASGI app: valid token → session + management-only catalog; missing/expired → 401; deny-by-default empty catalog.
- **N** `backend/tests/integration/test_management_toolset_end_to_end.py` — CC management-tool handlers (`POST /internal/management-tools/{tool}`): skill create→list→get→update lifecycle, duplicate 409, missing-name 400, delete-shaped/unknown 404, permission-denied 403 with no write, agent-type & MCP-server & data-type create validation.
- **E** `backend/tests/integration/test_mcp_protocol_server.py` — OAuth session flow through the real protocol server: management-only `tools/list`, permitted `tools/call` routed with `user_sub`, delete-shaped call declined in-band.
- **E** `backend/tests/integration/test_system_tool_endpoints.py` — `_CH_ALLOWLIST` completeness now accounts for management tools routing through the single parameterized `management-tools/{tool_name}` entry.
- **E** `backend/tests/integration/test_internal_tenant_header_failclosed.py` — added `app.api.v1.internal.management_tools` to the fail-closed data-plane router structural check.

### Backend — schema / migration (`backend/tests/db/`, `backend/tests/conftest.py`)
- **N** `backend/tests/db/test_agent_type_is_system_migration.py` — **schema-change verification** against real PostgreSQL:
  - `information_schema.columns`: `agent_types.is_system` exists, `boolean`, `is_nullable = NO`, `column_default` includes `false`; no `NULL` rows.
  - Negative protection: `PUT`/`DELETE` of a seeded `is_system=true` agent type → 403; non-system type delete → 204, update not system-protected.
- **E** `backend/tests/conftest.py` — registered `tests/db/test_agent_type_is_system_migration.py` in `_DB_DEPENDENT_FILES`.

### Frontend (`frontend/src/__tests__/`)
- **N** `frontend/src/__tests__/ControlCenterAssistantEntry.test.tsx` — assistant launcher: resolves the seeded `is_system` agent type, renders the FAB, opens `ConversationDialog` with the resolved `agentTypeId`; i18n keys (`assistant.launch`, `agents.types.systemBadge`, `agents.types.systemProtected`).
- **N** `frontend/src/__tests__/AssistantModelConfigGuidance.test.tsx` — model-unconfigured guidance: assistant-model GET returning `selected_model_id: null` renders the guidance Alert with the "Configure model" action and disables input/send; a configured model renders no banner and keeps input enabled; `useChatSession` maps the structured `assistant_model_not_configured` chat-error payload to `chatError` state (mid-session mapping).
- **E** `frontend/src/__tests__/AgentManagementPage.test.tsx` — `is_system` agent type marked with the System badge; edit/delete controls disabled; non-system types unaffected.

### Backend — bounded turns, WS liveness, end-session cleanup (FIX-20261031-091657)
- **N** `backend/tests/agent_runtime/test_fix_20261031_091657_llm_timeout.py` — hung LangGraph agent invocation bounded by `conversation_llm_timeout_seconds` → returns a clear "timed out" reply + `timeout_or_failed` status event; fast turns unaffected.
- **N** `backend/tests/agent_runtime/test_fix_20261031_091657_terminate_conversation_task.py` — AR `/terminate/{id}` cancels in-flight CONVERSATION turn tasks; still 404 with nothing in flight.
- **N** `backend/tests/communication_hub/test_fix_20261031_091657_turn_watchdog.py` — whole-turn watchdog (bounded even on the streaming path), exact-once error-turn persistence (success path never persists a watchdog error), `thinking_heartbeat` keepalive during long turns, WS close code+reason logging.
- **N** `backend/tests/api/test_conversations_end_termination.py` — `/end` best-effort termination via `AgentRuntimeClient.terminate_session`; termination failure never fails the end call.
- **N** `backend/tests/test_llm_mock_hang_hook.py` — `LLM_MOCK_DELAY_SECONDS` delay and `LLM_MOCK_HANG=1` hang hooks in the mock provider (simulate a slow/hanging model through the real stack).
- **Live verification (REAL turns through the Vite-proxied WS, LLM mock mode)** — Scenario A (100s delayed model): reply delivered live at ~133s, 8 × `thinking_heartbeat` every 15s, socket survived > 90s mid-turn, turn persisted. Scenario B (hanging model, 10s AR bound): `timeout_or_failed` + persisted clear error reply within the bound. Scenario B2 (end-session): `/end` at ~5s cancels the CH pending turn → WS gets `timeout_or_failed` + error message promptly, session `closed`, full CC → CH → AR forwarding chain confirmed in logs. Scripts: `scripts/fix-20261031-091657-live-a.cjs`, `scripts/fix-20261031-091657-live-b.cjs`.
Frontend:
- **N** `frontend/src/__tests__/useChatSession.heartbeat.test.ts` — `thinking_heartbeat` refreshes the thinking timestamp (no state/kind change, no message injected); `timeout_or_failed` surfaces as the terminal status (rendered as the error Alert by `ConversationDialog`).
- **N** `frontend/src/__tests__/AppShell.forceNewAfterEnd.test.tsx` — after explicit END (flag set) the next open skips the resume list fetch and starts a NEW session; without the flag resume-latest-active is unchanged.

### Backend — model-unconfigured guard (`backend/tests/communication_hub/`)
- **N** `backend/tests/communication_hub/test_ws_chat_model_not_configured.py` — an AR 400 "Agent model is not configured" (pre-model guard) surfaces the structured `assistant_model_not_configured` code from `_call_llm` (REST and streaming paths); unrelated 400s stay generic; correctly-configured agents still return their reply unchanged.
- **N** `backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py` — **tool-context-on-conversational-path** (FIX-20261031-035145): the CC `get_agent_context` payload consumed by AR's `execute_conversation_turn_from_context` includes the assistant's management tools (`system____create_skill` in `allowed_tools`, `create_skill` function schema in `tool_definitions`); `AssistantSeeder` self-seeds per-tenant management `McpTool` rows + full 36 bindings for a fresh tenant; double-seed idempotency.

### Backend — agent-type skill/SOP association (`backend/tests/integration/`, FIX-20261031-071721 defect 2)
- **N** `backend/tests/integration/test_fix_20261031_071721_agent_type_bindings.py` (9 tests) — **agent-type skill/SOP bindings via the management toolset**: `create_agent_type` with `skill_ids`/`sop_ids` (id or name, tenant-scoped) creates `AgentTypeSkillBinding`/`AgentTypeSopBinding` rows (`order=0` conventions); `update_agent_type` ADDS bindings (additive merge — never removes existing ones) and re-binding an existing pair is an idempotent no-op; unknown skill/SOP id or name → structured 404 with zero partial writes; permission parity unchanged (`agent:create` / `agent:update`, wrapper 403 verified); served `get_management_tool_schema` exposes `skill_ids`/`sop_ids` with additive-merge description; `search_assistant_knowledge("associate skill with agent type")` returns the association workflow rule.

### Backend — CWD-independent cert paths + role grants (`backend/tests/`, FIX-20261031-131030)
- **N** `backend/tests/unit/test_fix_20261031_131030_cert_paths.py` (12 tests) — **cert-path resolution is CWD-independent** (resolution exercised under `os.chdir(tmp_path)`), absolute/explicit config wins, CH/AR managers + CC renewal default + CC outbound clients all anchor to the backend root; `ensure_cert_files_exist` fails fast with an actionable message when a resolved cert file is missing; CH `_load_certificate` raises a fail-fast `RuntimeError` instead of warn-and-continue.
- **N** `backend/tests/integration/test_fix_20261031_131030_role_grants.py` (10 tests) — **role skill/SOP grants via the management toolset**: `create_agent_role` with `skill_ids`/`sop_ids` (id or name, tenant-scoped) writes `AgentRoleSkill`/`AgentRoleSOP` rows; `update_agent_role` ADDS grants (additive merge, never removes) and re-granting is an idempotent no-op; unknown skill → structured 404 with "create_skill" guidance and zero partial writes; parity unchanged (roles on bare `agent` create/update; wrapper 403 verified); served schemas expose `skill_ids`/`sop_ids`; `search_assistant_knowledge("assign skill to agent role")` returns the grant-to-role workflow (create skill → grant to role → agent type with that role; ungranted skills are inaccessible at runtime).

### E2E (`e2e/tests/`)
- **N** `e2e/tests/control-center-chatbot.spec.ts` — mocked flows: assistant FAB only when a system agent type resolves; FAB opens the conversational surface; `is_system` badge + disabled edit/delete on the Agent Types list; non-system types remain editable/deletable.
- **N** `e2e/tests/control-center-chatbot.real-backend.spec.ts` — **`Real Backend Integration - Control Center Assistant`** (no mocks): unauthenticated/invalid OAuth token on `/mcp` → 401; valid OAuth token → session + permission-filtered management catalog (skips when the OAuth→MCP resolve is blocked by the multi-tenancy signed-header gap).
- **N** `e2e/tests/control-center-chatbot-mcp.spec.ts` — **external MCP client parity**: drives `/mcp` with the user's OAuth credentials; `tools/list` never exposes a delete tool; delete-shaped / out-of-scope `tools/call` declined in-band (skips under the same multi-tenancy gap).

### mcp-demo-app (`mcp-demo-app/tests/`)
- No changes required (assistant is a Control Center internal capability; demo app unaffected).

### Backend — confirmation-before-write + conversational HITL (`backend/tests/`, FIX-20261031-133253)
- **N** `backend/tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py` (10 tests) — `human_intervene` is the 5th assistant meta tool (registry set, no parity leak, schema carries approval/choice/text + prompt); the role-less assistant `agent_context` loads exactly the 5 meta definitions incl. `human_intervene` and binds it to the management skill; knowledge retrieval: "do I need to confirm before creating?" → `confirm-before-write` (human_intervene + approval + table + reject contract), "what does an agent need to work?" → `agent-creation-completeness` (list tools, update_agent_role grants, non-functional rule), general creation completeness; seeder instruction carries the rules AND a pre-fix (stale-digest) skill row refreshes on the next seeder run; AR→CH routing of `system____human_intervene` reaches the CC `/internal/system-tools/human-intervene` endpoint with the signed tenant header set.
- **N** `backend/tests/agent_runtime/test_fix_20261031_133253_conversational_hitl.py` (8 tests) — `conversation_resume` registry semantics (resolve delivers the response value, timeout returns None cleanly, garbage ids safe, per-conversation scoping); AR `/internal/resume` resolves a pending conversational intervention FIRST (never relaunches a job execution) and preserves the existing job-relaunch fallback for non-conversation sessions; `LangChainHumanInterveneTool` on conversational turns returns the operator's response (`status:"approved"`) and, on operator-less timeout, the explicit `status:"timeout"` "NOT executed" result.
- **N** `backend/tests/agent_runtime/test_fix_20261031_133253_intervention_wait_bound.py` (2 tests) — co-existence with FIX-20261031-091657: without a pending intervention the strict `conversation_llm_timeout_seconds` bound still fires (hanging provider → timeout_or_failed); with a pending intervention the wait is re-armed (turn survives past the strict bound and completes with the operator's approval), and an unanswered confirmation ends the turn bounded.
- **N** `frontend/src/__tests__/InlineInterventionDialog.test.tsx` (+2) — an approval `reason` carrying a markdown TABLE renders as a real `<table>` via `ContentRenderer` (header + body rows, values visible); Approve still fires the existing `intervene_response` flow for a table preview.
- **Live verification (REAL turn through the Vite-proxied WS, LLM mock `scripted` mode, real CC/CH/AR stack)** — `scripts/fix-20261031-133253-live.cjs` + `tmp/fix-133253-scripted.json`: (1) real `invoke_management_tool(list_model_configs)` read (no confirmation needed); (2) real `human_intervene` approval with the markdown TABLE preview delivered live as `intervene_request` (asserted `| Field |` table present); (3) approve via the REAL `intervene_response` WS message → `intervene_status: responded`; (4) on approval the real `create_agent_type` management dispatch ran — the agent type **actually created** with `model_id=deepseek-v4-flash` (verified via REST). `LIVE-VERIFICATION-PASSED`.

### Backend — `cc____` namespace, Control Center MCP entity, skill↔tool bindings (`backend/tests/`, FIX-20261101-000319)
- **N** `backend/tests/unit/test_cc_naming.py` (18) — `cc` reserved slug; category-aware canonical names (`cc____create_skill`, `cc____invoke_management_tool`; `system____save_data` etc. untouched); `is_cc_tool`; `is_system_tool` accepts both namespaces for routing; management excluded from `get_mcp_hub_entries`; `get_cc_mcp_hub_entries` covers management+meta; parity map unchanged; meta mechanics unchanged (`human_intervene` stays general); CC server UUID distinct/deterministic.
- **N** `backend/tests/unit/test_cc_seeder_migration.py` (4) — old-style `system____<mgmt>` rows + bindings → CC entity exists (slug `cc`), `cc____` rows present, skill rebound to new rows, legacy rows retired, general rows intact; idempotent across restarts; fresh-tenant path clean.
- **N** `backend/tests/unit/test_cc_tool_registry_bridge.py` (10) — cc tools listed ONLY when granted; general system tools excluded from the OAuth catalog even if present in the permitted set; granted dispatch → management handler with `user_sub` forwarding; ungranted → structured in-band denial (OAuth) / `PermissionError` (API key); `cc____delete_skill` declined; `cc____list_management_tools` routes to its meta endpoint.
- **N** `backend/tests/unit/test_skill_tool_bindings_management.py` (8) — `create_skill` binds via `tool_names` and `tool_ids`; `update_skill` additive merge + idempotent re-bind; unknown tool → 404 with NO partial write; tenant-scoped resolution (foreign-tenant tool 404); `cc____` tools bindable; `get_mcp_server` returns its `tools`; `search_assistant_knowledge` returns the `skill-tool-binding` rule.
- **U** prior suites updated to the new canonical names: `test_tool_registry_bridge.py`, `test_oauth_bearer_auth.py`, `test_management_tool_permission_parity.py`, `test_mcp_oauth_bearer_auth.py`, `test_mcp_protocol_server.py` (`system____create_skill` → `cc____create_skill`), `test_fix_20261031_133253` / `test_fix_20261031_035145` (meta definitions now `cc__…`/`system__…` sanitised canonical; per-tenant rows are `cc____`).
- **Live verification** — `scripts/fix-20261101-000319-live.cjs` + `tmp/fix-000319-scripted-rules.json` (real Vite-proxied WS, LLM mock `scripted`): real `cc____invoke_management_tool(create_skill, data.tool_names=["cc____list_skills"])` dispatch → **LIVE-VERIFICATION-PASSED**: cc entity present (41 tools: management + meta, zero general tools), the skill created WITH its `SkillToolBinding` (verified via `GET /mcp/tools/{id}/skills`), and a role with no cc grants (`decision-role`) resolves no `cc____` tools.

### Backend — `integration::control_center` entity-view permission (`backend/tests/`, FIX-20261101-014511)
- **N** `backend/tests/unit/test_cc_integration_permission.py` (16) — manifest registration (`integration::control_center` = read+manage) + integration-module group membership (wildcard coverage); MCP Hub REST: list filters `cc` without read / includes with read, detail 404-without-leak without read / 200 with read, update+delete on `cc` → structured 403 (`required_permission.resource_type = integration::control_center`) without manage and 200 without it, non-cc server mutations unaffected for a plain `integration::mcp_hub` user; tool grants on cc tools → structured 403 without manage / 201 with manage; cc tool listing 404 without read; management toolset: `list_mcp_servers` omits cc and `get_mcp_server(cc)` 404s without the triggering user's read, returns the record with it.
- **U** `backend/tests/unit/test_resource_type_manifest.py` (28→29 entries; integration group 2→3) and `backend/tests/integration/test_namespace_permission_evaluation.py` (manifest-count fixtures refreshed — stale on HEAD, verified via clean worktree).
- **N/U** `frontend/src/__tests__/McpHubPage.test.tsx` (+3) — cc row renders with the protected chip when the (permission-filtered) API returns it; no cc row when the list omits it; structured 403 from cc deletion surfaces via `PermissionDeniedAlert`. `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` updated to 28 types / 3 integration submodules.

### Backend + Frontend — cc entity system-managed & sessionless (FIX-20261101-090438)
- **N/U** `backend/tests/unit/test_cc_integration_permission.py` (29 total) — new
  `TestCcSystemManagedImmutable`: update/delete/sync/OAuth-authorize on `cc` → structured 403
  (`code=system_managed_integration`) even WITH `integration::control_center:manage` (wildcards
  included); session create/update/delete on `cc` → 403 "not supported"; cc session list stays
  200 (harmless); non-cc session create unaffected (201 passthrough). Updated FIX-014511
  expectations: cc update with manage now 403 (immutable); cc update without manage is the
  system-managed 403 (guard precedes the permission gate). New `TestSystemManagedFlag`:
  `McpServerRead.is_system_managed` True for cc/system/decision, False for ordinary slugs;
  seeder refreshes drifted cc-server fields idempotently (no row created).
- **Regression (not regressed):** role↔tool grant on a cc tool with manage still 201; non-cc
  server mutations under plain `integration::mcp_hub` unchanged; FIX-014511 read-visibility
  suite green; manifest/namespace/tenant-isolation suites green (117 passed combined).
- **N/U** `frontend/src/__tests__/McpHubPage.test.tsx` — cc row renders the
  `mcp.controlCenter.systemManaged` chip with edit/delete/sessions hidden and sync disabled
  (both via slug fallback and via the API `is_system_managed` flag); non-cc rows keep their
  actions; the structured-403 `PermissionDeniedAlert` path is exercised via the regular server
  row (the cc row no longer offers delete).

### Backend + Frontend — iteration budget, guardrail error clarity, action bar (FIX-20261101-111439)
- **N/U** `backend/tests/unit/test_assistant_seeder.py` (+2, failing first) — seeded assistant
  carries `guardrail_max_iterations = ASSISTANT_GUARDRAIL_MAX_ITERATIONS` (24, ≥ the observed
  11-step exhaustion); an existing seeded row downgraded to 10 is refreshed back to 24 by the
  seeder's update branch.
- **N/U** `backend/tests/communication_hub/test_fix_20261101_111439_iteration_limit.py` (new) —
  AR streaming error chunk carries `error_type=iteration_limit` + `error_details` when the
  executor raises `GuardrailStop`; CH maps `iteration_limit` (with/without details) and other
  guardrail reasons to structured `ConversationTurnError`s; `run_conversation_turn` delivers the
  clear message (never the generic "An error occurred"), emits a `chat_error` payload AND
  persists the error turn exactly once with an `iteration_limit` status event; the
  `GuardrailCallback` still raises `iteration_limit` with details at 11/10.
- **N/U** `frontend/src/__tests__/ConversationDialog.actionBar.test.tsx` (new, failing first) —
  4-option action bar renders (View All Sessions / New Session / End Session / Exit); New
  Session POSTs `/conversations`, never calls end/archive, does NOT set the force-new flag, and
  clears the message state; View All Sessions lists sessions (query reuse) and switching resumes
  the chosen one without ending/archiving the previous; End Session still calls the end mutation
  and sets the force-new flag; Exit closes with zero API calls; New Session is disabled while a
  turn is streaming.
- **Regression (not regressed):** `ConversationDialog.test.tsx`,
  `ConversationDialog.assistantChat.test.tsx`, `ConversationDialog.resumeLiveDelivery.test.tsx`,
  `ConversationDialog.intervention.test.tsx`, `AppShell.assistantSession.test.tsx`,
  `AppShell.forceNewAfterEnd.test.tsx`, `AppShell.test.tsx` (66 passed); backend
  `tests/communication_hub` (150 passed; 2 pre-existing HEAD failures in
  `test_tenant_header_verification.py`, verified on a clean worktree); guardrail/executor/HITL/
  confirm suites (181 passed, 6 skipped); full vitest 1798 passed / 0 failed / 18 skipped;
  `tsc --noEmit` clean.

## FIX-20261101-120618 Work Item 1 — sessions view + sessions list API

File: `backend/tests/integration/test_conversations_sessions_query.py` (new, 13 tests,
failing-first — `ConversationStore.list_sessions_page` and the endpoint did not exist).

| Test | Verifies |
|---|---|
| `test_list_sessions_page_orders_by_updated_at_desc` | Time-desc ordering |
| `test_list_sessions_page_default_window_excludes_sessions_older_than_7_days` | Default query window = now − 7 days |
| `test_list_sessions_page_explicit_date_from_overrides_default_window` | Explicit range wins over the window |
| `test_list_sessions_page_all_time_includes_old_sessions` | `all_time=true` escape hatch |
| `test_list_sessions_page_status_active_only_by_default_flag` / `..._ended_includes_closed_and_archived` / `..._all_includes_everything` | Status semantics: `active` / `ended` (= closed+archived+error) / `all` |
| `test_list_sessions_page_pagination_and_total` | `page`/`page_size` slicing + full filtered `total` |
| `test_list_sessions_page_tenant_isolated` | Other tenants' sessions never returned |
| `test_legacy_list_sessions_still_works_backward_compat` | Legacy `GET /conversations` path unchanged |
| `test_sessions_endpoint_default_window_applied` / `..._accepts_new_filter_params` | New endpoint contract + param validation |
| `test_config_exposes_default_window_days_setting` | `conversation_sessions_default_window_days` = 7 |

Frontend: `frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx` (new, 6 tests,
failing-first): default active-only + 7-day window; ended rows marked and NOT resumable;
toggle refetches with `status=all`; pagination requests page 2; date-range refetch
(from `T00:00:00.000Z` / to `T23:59:59.999Z`); switching resumes in place with no
end/archive of the previous session (FIX-111439 preserved); new controls via i18n keys.

Regression: `test_conversations.py`, `test_conversations_end_termination.py`,
`test_intervention_api_integration.py` (32 passed); ConversationDialog ×5 suites +
AppShell ×2 + ConversationSessionsTab + AgentDetailBubble (all green after adding the
`useConversationSessionsPage` export to their hook mocks); full vitest **1804 passed /
0 failed (18 skipped)**; `tsc --noEmit` clean; backend `tests/unit` + `tests/api`
1279 passed with only environment-dependent failures (see fix-log for the clean-worktree
comparison).

## FIX-20261101-120618 Work Item 2 — built-in inherent skills (`backend/tests/communication_hub/`)

File: `test_fix_20261101_120618_inherent_skills.py` (failing-first: import failed before
`builtin_skills.py` existed).

| Test | Verifies |
|---|---|
| `test_inherent_set_contents` | The inherent set is exactly the documented 9 optimization/self-context tools; all registered; none are management tools (stay `system____`) |
| `test_inherent_definitions_have_descriptions` | Both skills carry discovery descriptions + tool lists |
| `test_roled_agent_context_includes_inherent_tools` | Role'd agent: role-resolved MCP tool still present + all 9 inherent tools as canonical `system____` names + registry schemas under sanitised def names + skills summary contains both inherent skills |
| `test_no_binding_rows_created` | `get_agent_context` creates ZERO `AgentTypeSkillBinding` rows (no N×M seeding) |
| `test_roleless_assistant_gets_inherent_tools` | Assistant (role-less) context = cc meta tools + inherent set |

Deliberately updated contracts: `test_fix_20261031_035145_assistant_tool_context.py::test_t1`
and `test_fix_20261031_133253_confirm_before_write.py::test_assistant_context_definitions_include_human_intervene`
now expect meta tools + inherent definitions (exactly); `test_tool_naming_refactor.py`
`TestNoAutoInjection` now allows ONLY the inherent set as auto-injected system tools.

Optional live check note: the AR→CH→CC routing of `system____*` calls is unchanged plumbing
already covered by the tool-routing suites (`test_conversation_agent_tool_routing.py`,
`test_tool_routing_architecture.py`, `test_data_clients.py`) — inherent tools use the same
dispatch path as bound-skill system tools, so coverage is in-process.

---

## FIX-20261101-223511 — binding visibility + zero-binding guard + canonical preview + expand card

File: `backend/tests/unit/test_fix_20261101_223511_skill_bindings_visibility.py` (failing-first:
`warnings` absent, `tool_bindings` absent from toolset reads and `SkillRead`,
`confirmation-preview-format` knowledge entry missing).

1. create_skill without tools → result carries `warnings: ["This skill has no tools bound …"]`,
   record still returned (non-fatal).
2. create_skill WITH `tool_names` → no warning.
3. update_skill touching tools with zero bindings after → warning.
4. update_skill adding tools → no warning.
5. get_skill record exposes `tool_bindings` (name/original_name/server_slug/server_name).
6. list_skills records expose `tool_bindings` per skill.
7. `SkillRead.model_validate` populates `tool_bindings` (incl. server slug/name).
8. Knowledge retrieval: "confirmation preview format" / "how to format the approval table" →
   `confirmation-preview-format` entry containing `| Field | Value |` + `human_intervene`.

Frontend:
- `SkillsToolBindingsVisibility.test.tsx` — bound-tool chips render original names; chip
  tooltip carries server name + canonical name; zero-binding skill shows muted
  "No tools bound".
- `InlineInterventionDialog.expand.test.tsx` — expand control renders; expanded dialog shows
  the full-width table (role="dialog", 5 rows, content assertions); approve/deny from the
  expanded dialog invoke the same handlers; collapse returns to a working inline card; inline
  approve round-trip untouched.
- Prior `InlineInterventionDialog.test.tsx` (incl. FIX-133253 table-rendering tests) unchanged
  and green.

Live (scripted mock, real WS): `scripts/fix-20261101-223511-live.cjs` asserts the canonical
bold-title + Field/Value table in the intervene_request, the approve→resume create, the
zero-binding warning in the final reply, and `tool_bindings` on `/skills`. Result:
LIVE-VERIFICATION-PASSED.

---

## FIX-20261102-062047 — single tool surface + complete, permission-correct listing

### Backend — `backend/tests/unit/test_fix_20261102_062047_mcp_tool_listing.py` (11)

Handlers are invoked directly with a real SQLite session and a bare ASGI
`Request`; `_cc_visible` is patched to model the caller permission.
`_declared_default` reads FastAPI's declared `limit` default.

| # | Case | Asserts |
|---|---|---|
| 1 | default window not truncated at 50 | declared default ≥ 200; > 50 tools returned; seeded `supabase`/`mapdemo` servers present; `X-Total-Count == len(page)` |
| 2 | pagination no loss/duplication | paged ids unique; page union == one big page; total header == union size; order `(server_slug, name, id)`; two walks identical |
| 3 | stable ordering across requests | same key list on repeated calls |
| 4 | cc hidden without cc read | no `server_slug == "cc"`; total accurate |
| 5 | cc listed with cc read | exactly the seeded cc tools appear |
| 6 | referenced cc tool resolvable | `GET /mcp/tools/{id}` returns 200 when a skill binding references it |
| 7 | unreferenced cc tool | 404-without-leak |
| 8 | non-cc tool resolvable | 200 |
| 9 | decision tools in complete listing | virtual `decision____<name>` present |
| 10 | server pagination filters cc before slicing | no cc; no duplicates; every seeded server present; total == collected |
| 11 | server pagination with cc read | cc exactly once; no duplicates |

Failing-first evidence: reverting the handler behavior (default 50, no cc
filter, no full-set sort, no referenced-cc resolution) → 4 failed; fixed → 11
passed.

### Frontend — `frontend/src/__tests__/SkillEditor.singleSurface.test.tsx` (6)

| # | Case | Asserts |
|---|---|---|
| 1 | pre-selects existing bindings | `run_sql` + `create_skill` + canonical names render from `tool_bindings`; exactly ONE "Bound tools" surface |
| 2 | referenced cc read-only | permission note rendered; no remove control for the cc entry |
| 3 | picker toggles same list | checking `github____create_issue` then Confirm adds it to the single list |
| 4 | save keeps the union | removing `run_sql` still sends the locked cc id; removed id absent |
| 5 | view mode one list | names + servers, one surface, no remove controls |
| 6 | zero bindings | "No tools bound" |

Failing-first evidence: 2 passed / 4 failed before the component change → 6/6.

### Frontend — `frontend/src/__tests__/useMcpServers.pagination.test.tsx` (3)

Complete paging past the 200 cap for tools and servers; explicit
`(limit, offset)` callers still issue one request.

### Regression

- `SkillEditor.boundTools|fixes|test|minimal|generatedToolReference|workflow-
  generation-preview`, `SkillsToolBindingsVisibility` — 54/54.
- Backend new suite + FIX-223511 bindings + skill-binding management +
  `test_tenant_isolation_sweep.py` — 93 passed.
- `test_cc_integration_permission.py` — 28 passed, 1 pre-existing failure
  (`test_grant_on_cc_tool_with_manage_allowed`, mock ordering drift; confirmed
  with the fix reverted).
- `tests/api/v1/test_mcp_hub_api.py` — 20 passed / 9 pre-existing
  session-mock-ordering failures (confirmed with the fix reverted).
- `tests/api/v1/test_skills_api.py` — 8 pre-existing failures from stale
  MagicMock bindings (confirmed with the new schema field removed).
- `tsc --noEmit` clean; full vitest run recorded in the fix log.

### Live probe

`scripts/fix-20261102-062047-probe.cjs` → `LIVE-PROBE-PASSED`:
default `/mcp/tools` now returns all 90 root-tenant tools with `X-Total-Count:
90`; ordering deterministic; 50-item paging lossless; supabase + map-demo
present; cc hidden for a no-cc-read user (49 tools) with full server pages; the
referenced cc tool resolves 200 read-only.

## FIX-20261102-100704 Work Item 1 — generic assistant knowledge/instruction

### `backend/tests/unit/test_fix_20261102_100704_generic_principles.py` (new, 40)

| # | Group | Asserts |
|---|---|---|
| 1 | principle entries exist | `resource-completeness`, `prerequisite-ordering` (+ `reuse-first`) present; corpus ≥ 20 entries |
| 2 | principle retrieval (6) | "how do I make an agent work" / "why is my agent not working" → `resource-completeness`; "what must exist before creating a skill"/"…an agent type" → `prerequisite-ordering`; "what does an agent need to work" → `agent-creation-completeness`; "why can't my agent access this tool" → `role-grant-workflow` |
| 3 | new entries are principles | completeness = "every resource type" + complete/functional + principle topic, no `create skill first`; prerequisite = derive + dependency, no `sequence:` |
| 4 | corpus has no scripted sequence (23 params, one per entry) | no `sequence: (1)`, `first create the skill`, `create skill first, then`, `step 1` |
| 5 | instruction generic principles | completeness principle / prerequisite ordering / grant at the right level / reuse-first / derive markers present |
| 6 | discovery pointers | `list_management_tools`, `get_mcp_server`, `search_assistant_knowledge`, `get_management_tool_schema` |
| 7 | no fixed sequence (4) | `create the skill first`, `first discover the tool`, `sequence: (1)`, `step 1` absent |
| 8 | facts kept | never raw MCP tools, model config, enabled models, conversational, unique per tenant, cc____/system____, non-functional, human_intervene, `\| Field \| Value \|` |
| 9 | skill digest | "principle" present, facts kept, no `create skill first`/`composition chain:` |

Failing-first evidence: 12 failed / 37 collected before the rewrite (missing
entries, missing retrieval, fixed-sequence phrasing in corpus + both
instruction surfaces) → 40/40 pass (23 corpus entries).

### Modified backend tests

- `tests/unit/test_assistant_knowledge.py` — retrieval matrix gains the three
  generic queries ("how do I make an agent work" → complete, "what must exist
  before creating a skill" → prerequisite, "why can't my agent access this
  tool" → grant); required-id set extended; new
  `test_corpus_entries_are_principles_or_facts`.
- `tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py` —
  completeness knowledge test now asserts the reference-fact framing (discovery
  tools, non-functional, enabled, role grants) instead of the retired
  `update_agent_role` script token; new completeness/prerequisite principle
  retrieval tests; instruction test additionally asserts the generic principles
  and the absence of the fixed sequence.
- `tests/unit/test_assistant_seeder.py` — new
  `test_seeder_refreshes_stale_instruction_and_digest`: stale seeded
  `system_instruction` + stale skill `instructions` converge to the current
  constants for every tenant on the next seeder run.

### Regression (unaffected)

`test_assistant_seeder` 10/10; cc naming / cc seeder migration /
management tools / permission parity / skill-tool bindings / FIX-223511
bindings / assistant meta tools / role grants / agent-type bindings /
assistant context / inherent skills / assistant model API / tenant-isolation
sweep = **182 passed**. Full `tests/unit` (minus the pre-existing
`test_setup_tenant_demo` collection error) = **1150 passed / 6 failed**, all 6
pre-existing/environmental (4 order-dependent mcp-listing tests that pass in
isolation, the documented cc-tool-grant 403 mock drift, one stale cert-path
expectation).

### Seed refresh (live dev DB)

`scripts/fix-20261102-100704-seed-refresh-check.py` →
`tmp/fix-20261102-100704-seed-refresh.txt`: 27 tenants (root + 26
e2e/demo/probe tenants) — 0/27 rows current before, 27/27 assistant
instructions and 27/27 skill digests current after the idempotent seeder
refresh (`SEED-REFRESH: PASSED`). Stack restart deferred to the Work Item 2
owner; the new corpus module text takes effect on the next CC process start.

## FIX-20261102-100704 Work Item 2 — topology pending-load states (frontend)

### Scope

Every topology entity whose referenced data is still loading renders a
spinner + i18n "Loading…" instead of a raw id or a misleading placeholder; a
resolved-but-missing reference keeps its raw-id fallback and deliberately
empty/set slots keep their existing dashed/solid semantics.

### Coverage matrix

| Entity | Pending source | Test |
|---|---|---|
| identity / role / model | identities / roles / model-configs list in flight | canvas: pending node label = loading key, no raw id; resolved → real labels |
| input/output data type | data-types list in flight | canvas + composer pending cases |
| skills (direct + SOP-composed) | skills list in flight | composer: skill node pending, no raw skill id |
| SOPs | SOPs list in flight | composer pending cases |
| SOP composition chain | bound-SOP detail requests in flight | composer + canvas: `sop_pending_<id>` child under the SOP; tools zone pending |
| MCP tools | skills/tools/servers in flight (when tool ids bind) | composer: `tool_pending` instead of `tool_empty`; no dashed skill→tool edges yet |
| none / conversation / auto / locked output / unfilled typed slots | n/a — deliberate states | canvas: `None`/`Auto` labels, `usage: 'empty'` placeholders unchanged, `pending` undefined |

### `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` (+9)

Composer (`buildPanelTopology`): loading placeholders for every bound entity
while flags are on + no raw ids; resolved-but-missing keeps raw-id fallbacks
and no pending flags; cached names never pending; deliberate contract states
and unfilled placeholders never pending; tools zone pending while SOP details
load then the genuine "no tools" state.

Canvas (component): stalled `apiClient.get` requests → pending nodes for
identity/role/model/input/output/skill/SOP + `sop_pending_sop-1` +
`tool_pending` with no raw ids; resolving all lists/details →
resolved labels, all tool nodes, pending flags gone; None/Auto semantics and
unbound-draft dashed placeholders stay pending-free while data is in flight.

### `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` (+4)

Pending node renders an accessible spinner (`role="progressbar"`, localized
`aria-label` + `<title>`, SMIL `animateTransform`) in place of the entity icon,
viewBox-unit geometry (radius ≤ 6 at zoom 2 / font cap 1.6), resolved node
renders the normal icon (no spinner), and clicking a pending node does not
invoke `onNodeClick`.

### Failing-first evidence

Before the change: **7 failed / 95 collected** across the two suites (4 new
canvas + composer assertions, 3 renderer spinner assertions — no spinner
node, no pending flags, raw ids leaking). After: **102/102** in the three
touched suites (incl. `PanelTopologyTokenHealth` label-fixture update).

### Regression

`tsc --noEmit` clean. Targeted: PanelTopologyCanvas + PanelTopologyTokenHealth
+ AgentTypeDetailsDialog + TopologyDiagramRenderer + AgentManagementPanelPage
= **142/142**. Full frontend `vitest run` = **1837 passed / 0 failed** (1855
collected, 18 skipped) — no new flakiness observed; the previously documented
order-dependent suites were green in this run.

### Manual / later

Vite HMR carries the change; no backend restart required. i18n string
`agents.panel.topologyLoading` is en-only in this change (single locale file
today).
