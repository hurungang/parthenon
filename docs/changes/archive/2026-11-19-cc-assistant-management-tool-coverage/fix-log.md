# Fix Log: cc-assistant-management-tool-coverage

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261108-121000

**Created:** 2026-11-08T12:20:00Z
**Status:** Resolved
**Issue:** A2A delegation times out after 120s and the sub-agent execution log is unreachable; fixes from earlier today were not live.

### Observed Behavior
- Assistant delegation to a sub-agent (e.g. `airline-booking-agent`) hangs; AR polls `GET /internal/a2a/wait/<id>` every 90s with no reply, then the parent conversation turn dies with "Conversation turn timed out after 120s".
- The sub-agent execution log cannot be fetched (sub-session never progressed under the stale services).
- Earlier same-day fixes (activity watchdog, thinking indicator, revocation transport) appeared ineffective.

### Expected Behavior
Delegation stays alive (with a visible chat indicator) for as long as the sub-agent legitimately works; services restart cleanly with current code.

### Analysis
- **Affected components:** `backend/app/services/agents/langchain_tool_wrapper.py` (A2A poll loop), `scripts/restart-backend.sh` (stale-process cleanup), service lifecycle.
- **Root cause hypothesis:** (1) The A2A poll loop emits no status events, so the conversation watchdog sees no activity and cancels a healthy parent turn at the 120s bound. (2) Restart script `pkill -f "uvicorn …"` kills uvicorn parents but NOT their orphaned `multiprocessing.spawn` worker forks, which keep ports 8000/8001/8002 bound — new instances fail with `[Errno 48] address already in use` (confirmed in both AR and CH logs) and the stale pre-fix processes kept serving.
- **Documentation impact:** none beyond this log (operational + code fix).

### Fix Tasks
- [x] **Reproduce** — Log evidence: 90s-spaced A2A wait calls (12:06:14 → 12:07:45) followed by the 120s watchdog kill (12:08:08); `[Errno 48]` bind failures; orphaned `spawn_main` processes confirmed via `ps`.
- [x] **Fix** — (a) `langchain_tool_wrapper.py` A2A poll loop now re-emits `{"status": "waiting", agent_type, receiver_session_id}` on every still-running poll — resets the conversational watchdog's activity marker (turn extends while the sub-agent works) and keeps a visible chat indicator; (b) `scripts/restart-backend.sh` now kills any listener on ports 8000/8001/8002 directly, so orphaned workers can never hold the ports.
- [x] **Verify** — `pytest backend/tests/agent_runtime -k "deleg or hitl or timeout"`: 14 passed. Full restart: all three services fresh PIDs (12:15:08/12:15:21/12:15:25), health 200 on 8000/8001/8002, zero bind errors.
- [x] **Document** — This entry; parity/docs unaffected.

### Code Changes
- `backend/app/services/agents/langchain_tool_wrapper.py` — A2A poll loop emits waiting status per poll (activity + UI indicator).
- `scripts/restart-backend.sh` — port-listener kill for 8000/8001/8002 added.

### Verification Results
- Backend targeted suites: 14 passed.
- Live stack: fresh processes, all health probes 200, no bind errors in restart output.

---
# Fix Round — Permission-Resolution Model Correction (role=permission, agent type=visibility)

**Date:** 2026-11-09
**Trigger:** Product-owner correction: the previous round removed the role's 3 direct skill grants and added a "delegation SOP + direct grants" warning based on a wrong model. Correct model: **role controls PERMISSION only; agent TYPE controls VISIBILITY** (own SOP/skill bindings, a subset of the role's grants).

### What was reverted
- `scripts/remove_role_direct_skill_grants.py` — added `--restore` mode (idempotent re-insert of find-booking-by-pnr / check-in-passenger / create-booking grants on role `airline-agents`); **restored and verified** (role resolves 5 tools again).
- Removed `_role_delegation_grant_warning` and its create/update wiring from `backend/app/api/v1/internal/management_tools.py`.
- Replaced the `sop-only-router-roles` knowledge entry + seeder rule 2i with ROLE-PERMISSION vs AGENT-VISIBILITY semantics ("if an agent can't see an expected tool, associate the SOP/skill to the AGENT TYPE, not just the role").

### The new resolution algorithm
`AgentPermissionManager.calculate_agent_allowed_tools(agent_type_id, db)`:
1. **Visibility** from the agent type's own associations: `AgentTypeSkillBinding` skill ids + `AgentTypeSopBinding` SOPs' `skill_invocation` steps' skills → tools.
2. **Permission filter**: result = visibility tools ∩ `calculate_allowed_tools(role_id)` (role grants still gate).
`calculate_agent_allowed_agent_types(agent_type_id, db)`: `agent_delegation` step targets of the agent type's own SOPs, intersected with role-derived delegation targets (fallback to SOP targets when the role derives none). Inherent `system____` tools unchanged at the hub layer.
Consumers switched: `permission_resolution.resolve_permissions` (CH certificate authorize — the leak point), `runtime_executor` (conversation turn + task `_execute_job`), `lifecycle_handler.get_role_tools_for_agent`, `agent_data` / `optimization_tools` internal helpers.

### Cache invalidation
New per-agent-type caches (`_agent_visibility_cache`, `_agent_visibility_agent_types_cache`) keyed by agent_type_id. `invalidate(role_id)` clears all agent-visibility caches (role gates every agent); `invalidate_agent_type()` is called from `AgentTypeService.set_bindings` (covers agent create/update binding writes) and from the agent-type update endpoint when `role_id` changes. Chosen over embedding binding state in the key — simpler and still correct.

### Empty-visibility edge (backward compat)
Strict model: agent types with NO bindings see nothing from the role. Live-DB audit: **every active agent type has bindings** (only `control-center-assistant` has no role and is exempt). No seeded agent relies on role-only inheritance — nothing flagged for the conductor.

### Verification
- `pytest backend/tests -k "permission or resolution or allowed_tools or parity or knowledge or delegation or runtime_executor or conversation_agent_tool or support_role"`: **422 passed**, 16 skipped, 1 failed = pre-existing baseline failure (`test_service_auth::test_user_permissions_api`, 401 signed-tenant-header env issue, fails on unmodified HEAD too).
- New unit tests: chatbot case (delegation-only SOP → 0 tools, 3 delegation targets, role's extra skills NOT visible), bound-skill ∩ role-grant (visible only when role-granted), strict no-inheritance, cache invalidation both directions.
- Live DB: `airline-service-chatbot` → visible tools `[]`, delegation targets = the 3 airline sub-agents; role still grants 5 tools (permission only).

---

---
# Fix Round — execute_script description, conversation execution-log skip, guardrail panel regression

**Date:** 2026-11-09
**Trigger:** Three live defects in the conversational assistant path.

### A. `execute_script` description rewritten (tool stays INHERENT)
`backend/app/services/agents/system_tool_registry.py` — the description now teaches the iteration-saving pattern: combine MULTIPLE associated MCP tool calls plus intermediate computation into ONE sandboxed script (only when script-feasible and the request warrants it); the sandbox `tools` facade exposes exactly the agent's associated tools (convention only, no specific tool names); `run(context, tools)` must return a dict; do NOT use for a single tool call or a conversational answer. Verification primitive (inline `python_source` / `script_version_id`) kept as a secondary note. `python_source` param description updated. Schema stays bounded (<2000 chars, test-guarded).

### B. Conversational sessions skip execution-log shipping
Root cause (live log): the Control Center Assistant ran `system____execute_script` inside a conversation turn; AR's `script_tools.py` bound its execution-log shipper to the CONVERSATION session id, and every ship hit CC FK violation (`execution_log_entries.session_id` → AgentJob sessions only) — 164 500s in control-center.log.
- `backend/app/agent_runtime/api/script_tools.py` — conversation turns (`conv_session_id` set) build NO log shipper; agent-job turns unchanged.
- `backend/app/services/agents/runtime_executor.py` — `execute_conversation_turn_from_context` now sets `_suppress_execution_log_shipping` (restored in `finally`); `_log_execution_event` early-returns when set (single choke point).
- `backend/app/api/v1/internal/session_data.py` — defense in depth: on `IntegrityError` for a session that is a `ConversationSession`, log DEBUG and return 200 no-op (never 500 the caller); unknown sessions still 500.
- Verified nothing reads conversation-session execution_log_entries (DelegationMiniLog reads AgentJob sessions via `/agents/sessions/{id}/logs`; optimization tools join AgentJob).

### C. Guardrail panel regression — root cause & fix
Root cause (backend, not frontend/model): `guardrail_update` was only sent AFTER `_process_message` fully succeeded — including the `append_conversation_turn` persistence call. Communication-hub.log shows live `append-turn` `httpx.ReadTimeout` failures raising past the reply delivery (`on_reply` had already fired), so the persistence tail exception skipped the `guardrail_update` send entirely — the panel went dark whenever persistence hung/failed after a delivered reply.
Fix (`backend/app/api/ws/chat.py`): `_process_message` accepts `on_guardrail_usage`, invoked with the usage the moment the LLM delegation returns — BEFORE persistence; `run_conversation_turn` sends `guardrail_update` via the idempotent `deliver_guardrail_usage` helper (post-hoc send kept, deduped).

### Tests
- New: `backend/tests/agent_runtime/test_fix_20261109_conversation_log_guardrail.py` — 14 tests (description content/bound, suppression flag set/restore, script-tool shipper skip/keep, CC endpoint FK→200 / unknown→500, guardrail callback before persistence).


### Follow-up: script tool-name validation scope (caught by test_optimized_plan)
`backend/app/api/v1/internal/optimization_tools.py::_allowed_tool_names_for_agent` — under the strict visibility model, a legacy role-only agent type (no own bindings) resolves an empty tool set, silently disabling `execute_script`/`generate_script` tool-name validation (`status: draft` instead of `validation_error`). Added fallback: when visibility-derived scope is empty, validate against the ROLE's granted tools. `test_optimized_plan.py`: 39 passed.

### Final verification
- `-k "script or guardrail or execution_log or session_data or registry"`: 614+ passed; 6 failures investigated → 2 fixed via the fallback above, 4 pre-existing on unmodified HEAD (tenant-isolation sweep `AgentClient`/`AgentClientUsageLog` registration, skills-api MagicMock fixture).
- `-k "permission or resolution or allowed_tools or parity or knowledge or delegation or runtime_executor or conversation_agent_tool or support_role"`: **422 passed**, 16 skipped, 1 pre-existing baseline failure (`test_service_auth::test_user_permissions_api`).

---

# Fix Round — workflow-optimization gating + SOP no-raw-tool-mentions rule

**Date:** 2026-11-10

### A. Gate the `workflow-optimization` inherent skill on user-confirmed optimization runs
Product owner requirement: the workflow-optimization skill (injected summary + authoring tools) must load ONLY when the user confirmed optimization via the launch-dialog opt-in (run converted to the `optimize-and-verify` command via the `__command` input_data marker). Conversational/chat sessions have no dialog → default = no optimization.

- Gating mechanism: **option (a)** — `GET /internal/data/agent-types/{id}/context` accepts an optional `session_id` query param and inspects the stored `AgentJob.input_data` for `__command == OPTIMIZE_AND_VERIFY_SLUG` (imported from `command_prompts`). AR's executor passes its session id; conversational prepare (`agent_runtime/api/conversation.py`) and auto-compile omit it → gated default.
- `backend/app/services/agents/builtin_skills.py` — added `WORKFLOW_OPTIMIZATION_AUTHORING_TOOLS` (`generate_optimized_plan`, `generate_script`, `list_scripts`, `get_script`), `WORKFLOW_OPTIMIZATION_SKILL_NAME`, and gated variants `get_inherent_tool_names_for` / `get_inherent_skill_summaries_for` / `get_inherent_canonical_tool_names_for`. `execute_script` + self-context tools stay ALWAYS available (inherent iteration-saver, by design).
- `backend/app/api/v1/internal/agent_data.py` — injection now uses the gated set/summaries unless the session is an optimize-and-verify run (behavior unchanged for opt-in runs).
- `backend/app/agent_runtime/data_client.py` + `backend/app/services/agents/runtime_executor.py` — `get_agent_context(agent_type_id, session_id=...)`; executor forwards the session id.

### B. Assistant knowledge: SOPs must never mention raw MCP tools
Root cause: a SOP authored via the assistant instructed an agent to "call `mcp-demo____searchFlights` yourself" — SOP text/steps must never instruct direct MCP-tool calls; tool visibility flows ONLY through SOP associations.
- `backend/app/services/agents/assistant_knowledge.py` — new entry `sop-no-raw-tool-mentions` (HARD RULE: capability expressed only as `agent_delegation` / `skill_invocation` steps; bind raw tools into a SKILL first) with retrieval keywords ("sop tool mention", "mcp tool in sop", "sop step rule", "mention", "raw", "mcp", "tool"); `sop-composition` extended with the hard rule.
- `backend/app/services/agents/assistant_seeder.py` — always-on system instruction extended with the same HARD RULE.

### Tests
- `backend/tests/communication_hub/test_fix_20261101_120618_inherent_skills.py` — role'd default run → gated set (authoring tools/summary absent, `execute_script` + self-context present); NEW `test_optimize_and_verify_run_gets_full_inherent_set` (opt-in session → full set + both summaries); role-less assistant + NEW `test_conversational_prepare_gates_workflow_optimization` → gated.
- Updated default-set expectations in `test_fix_20261031_035145_assistant_tool_context.py`, `test_fix_20261031_133253_confirm_before_write.py`, `test_tool_naming_refactor.py` (gated set).
- `backend/tests/unit/test_assistant_knowledge.py` — new corpus-entry + seeder-instruction + retrieval tests.

### Final verification
- `pytest -k "agent_data or inherent or context or knowledge or seeder or sop"` + `test_management_mcp_tools.py`: target tests green (81 passed incl. management sanity); remaining failures verified pre-existing on unmodified HEAD via `git stash` baseline (tool-naming uuid seeding, tenant-header, session-lifecycle, decision-tools, service-auth, skills-api MagicMock fixture, tenant-adoption migration errors).
