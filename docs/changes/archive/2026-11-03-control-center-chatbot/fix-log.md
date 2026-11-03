# Fix Log: control-center-chatbot

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261102-100704

**Created:** 2026-11-02T10:07:04Z
**Status:** Resolved
**Issue:** (1) Assistant workflow knowledge may be over-fitted to the create-skill→grant→create-agent example — instructions must be GENERIC principles so the LLM decides correctly in any scenario; (2) agent topology diagram shows raw ids/empty placeholders while entities resolve on slow networks — needs pending-load spinners

### Observed Behavior
1. The agent-creation workflow works, but its knowledge/instruction wording risks being case-specific rather than generalizable.
2. On slow networks the topology diagram (`PanelTopologyCanvas` / `TopologyDiagramRenderer`) renders unresolved ids/empty labels before dependent data arrives, with no feedback that loading is in progress.

### Expected Behavior
1. Instructions encode GENERAL principles (understand the platform model from knowledge; every created resource must be complete and functional in its context; create prerequisites before referencing; grant capabilities at the right level; confirm before writes) plus accurate, generic facts — no case-scripted sequences.
2. Pending entities in the topology show a loading spinner/skeleton (instead of raw ids/blank) until resolved; resolved entities render normally.

### Analysis
- **Affected components:** `assistant_knowledge.py` + `assistant_seeder.py` (knowledge/instruction genericization), `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx`, `frontend/src/components/agents/TopologyDiagramRenderer.tsx` (+ `AgentTypeDetailsDialog` preview via the same canvas)
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: unresolved-topology spinner; knowledge wording checks
- [x] **Fix** — Generic knowledge/instruction + topology pending spinners
  - [x] Work Item 1 (backend knowledge + instruction genericization) — implemented & verified
  - [x] Work Item 2 (frontend topology pending-load spinners) — implemented & verified (frontend-only)
- [x] **Verify** — All layers
- [x] **Document** — Update affected documentation

### Work Item 1 — generic principles (backend knowledge + instruction)

**Requirement (user verbatim):** *"Hopefully the fix is generic, not specific
for this use case where we need to create skill first, then assign access then
create agent. The instruction should be generic so the LLM can make right
decisions."*

**Root cause.** The knowledge corpus and both instruction surfaces encoded one
observed scenario as mandated prose: an ordered "skills-first" script
(`create the skill first → grant it to the role → create the agent type`), a
`Sequence: (1)(2)(3)` entry, and an `ASSOCIATION WORKFLOW` block. Those read as
*a procedure to follow*, not *facts to reason from*, so any request that does
not match the example (e.g. binding a capability directly on a role-less agent,
composing an SOP, or wiring a schedule target) invited a wrong or
over-constrained plan.

**Before → after (samples).**

| Surface | Before | After (generic) |
|---|---|---|
| `skills-first-prerequisite` | "If a required skill or SOP does not exist yet, it must be CREATED FIRST … **Sequence: (1)** create the skill wrapping the MCP tool(s), (2) optionally compose skills into an SOP, (3) grant the skill/SOP to a role, and/or bind it directly to the agent type." | "SKILL/SOP PREREQUISITE (an instance of the **prerequisite-ordering** principle): a role grant or an agent-type binding references EXISTING rows only, so a missing skill/SOP must be created first — before anything can reference it. There is **NO fixed global sequence beyond that dependency**: whether you then grant it to a role, bind it directly to an agent type, or compose it into an SOP depends on the configuration at hand. **Derive the order from the dependency graph** of the request…" |
| instruction 2c | "ROLE GRANTS (critical): role-based agents get their runtime tool access from the ROLE's skill/SOP grants — **after creating an agent that uses a role, ALWAYS ensure** every skill/SOP the agent needs is granted to that role … Role-less agents use direct skill bindings." | "2c. PREREQUISITE AND GRANT PRINCIPLES (generic — **derive, never script**): (a) Prerequisite ordering: a reference can only point at something that already exists … **Derive the order from the dependencies you discovered (X references Y ⇒ Y must exist before X is written) — there is no universal fixed sequence** … (b) Grant at the right level: … must be granted at the level the configuration actually consumes it — role-based agent types get runtime access from their ROLE's grants, role-less agent types from their DIRECT bindings … (c) Reuse-first …" |

**Generic principles now taught (both surfaces).** understand-before-acting
(`search_assistant_knowledge` + discovery tools), **completeness** (a created
resource must be complete/functional in its own context — derive "complete"
from the resource type's reference facts, never placeholders), **prerequisite
ordering** (create what you reference; derive order from dependencies),
**grant-at-the-right-level** (permission model; role grants vs direct
bindings), **reuse-first** (prefer compatible existing entities; ask when
ambiguous), plus the unchanged **confirm-before-write** and **no-delete**.

**Facts kept as REFERENCE FACTS (accuracy unchanged).** agent types bind
skills/SOPs and never raw MCP tools; skills wrap tools via tool bindings (zero
bindings ⇒ inert); roles grant skills/SOPs and identities are assigned to
roles (many-to-many, validated per execution); per-tenant Model Config
enabled-models; conversational vs typed output; cc____ vs system____ tool
categories; per-tenant name/slug uniqueness; `confirmation-preview-format`
kept verbatim (a format standard, not a workflow); discovery pointer set
(`list_*`, `get_mcp_server`, `search_assistant_knowledge`,
`get_management_tool_schema`).

### Test Cases Added/Modified (Work Item 1)
- `backend/tests/unit/test_fix_20261102_100704_generic_principles.py` (NEW, 40
  collected: 12 red before the change → all green after): principle entries
  exist (`resource-completeness`, `prerequisite-ordering`, `reuse-first`);
  retrieval for "how do I make an agent work", "why is my agent not working",
  "what must exist before creating a skill/agent type", "what does an agent
  need to work", "why can't my agent access this tool"; both new entries are
  principles (no `create skill first`/`sequence:`); every corpus entry is free
  of fixed-sequence phrasing; instruction carries the generic principle markers
  and the discovery pointer set; instruction no longer contains
  `create the skill first` / `first discover the tool` / `sequence: (1)` /
  `step 1`; key facts still asserted (never raw MCP tools, model config,
  enabled models, conversational, unique per tenant, cc____/system____,
  non-functional, human_intervene, `| Field | Value |`); management-skill
  digest generic + facts retained.
- `backend/tests/unit/test_assistant_knowledge.py` — new principle queries in
  the retrieval matrix; required-id set extended with the three new entries;
  new `test_corpus_entries_are_principles_or_facts`.
- `backend/tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py`
  — `test_knowledge_agent_completeness_rule_retrievable` now asserts the
  reference-fact framing (discovery tools + non-functional + enabled + role
  grants) instead of the retired `update_agent_role` script token; new
  `test_knowledge_completeness_principle_is_generic` /
  `test_knowledge_prerequisite_principle_is_generic`; instruction test also
  asserts the generic principles and the absence of the fixed sequence.
- `backend/tests/unit/test_assistant_seeder.py` — new
  `test_seeder_refreshes_stale_instruction_and_digest` (stale assistant
  `system_instruction` + stale skill digest converge to the current constants
  on the next seeder run for EVERY tenant).

### Code Changes (Work Item 1)
- `backend/app/services/agents/assistant_knowledge.py` — module docstring now
  states "principles + reference facts". New entries
  `resource-completeness`, `prerequisite-ordering`, `reuse-first`. Rewritten as
  principles/facts: `agent-creation-completeness` (was "AGENT-CREATION
  COMPLETENESS WORKFLOW"), `creation-payload-completeness`,
  `agent-type-composition` (dropped `ASSOCIATION WORKFLOW`),
  `skills-first-prerequisite` (dropped `Sequence: (1)(2)(3)`),
  `role-identity-chain` (dropped the imperative chain),
  `role-grant-workflow` (now the grant-at-the-right-level principle),
  `sop-composition`, `progressive-context` (explicit discovery pointer set).
  `confirmation-preview-format` unchanged.
- `backend/app/services/agents/assistant_seeder.py` — `ASSISTANT_SYSTEM_INSTRUCTION`:
  new rules 2a (understand before acting), 2b (completeness principle), 2c
  (prerequisite ordering + grant-at-the-right-level + reuse-first), rule 8
  rewritten as "reference FACTS (consult — not a script) + PRINCIPLES"; rules
  1/2/2d/2e/2f/3-7 and the canonical preview contract unchanged.
  `MANAGEMENT_SKILL_INSTRUCTIONS` rewritten likewise (the "Composition chain"
  script replaced by PRINCIPLES + REFERENCE FACTS). Both branches (create and
  digest-compare refresh) use the constants, so existing seeded rows converge
  on the next seeder run/restart.

### Verification Results (Work Item 1)
- TDD: new suite **12 failed / 37 collected** before the change (missing
  principle entries, retrievability, fixed-sequence phrasing in
  `agent-type-composition`/`skills-first-prerequisite` and in both instruction
  surfaces) → **40/40 passed** after (23 corpus entries → 40 params).
- Targeted backend regression: `test_assistant_knowledge` +
  `test_fix_20261102_100704_generic_principles` +
  `test_fix_20261031_133253_confirm_before_write` = **71 passed**;
  seeder/knowledge/cc-naming/cc-migration/management-tool/parity/bindings/
  meta-tools/role-grants/agent-type-bindings/assistant-context/inherent-skills/
  assistant-model/tenant-isolation sweep = **182 passed**; `test_assistant_seeder`
  **10/10**.
- Full `tests/unit` (excluding the pre-existing `test_setup_tenant_demo`
  collection error): **1150 passed / 6 failed**, all 6 unrelated and
  pre-existing/environmental — 4 `test_fix_20261102_062047_mcp_tool_listing`
  order-dependent (all 11 pass in isolation), `test_cc_integration_permission::
  test_grant_on_cc_tool_with_manage_allowed` (403 mock drift, already documented
  as pre-existing in FIX-20261102-062047), and
  `test_control_center_comm_hub_client::test_init_uses_default_cc_cert_paths_when_env_missing`
  (stale expectation vs FIX-20261031-131030 absolute cert-path resolution).
- Seed refresh evidence (live dev DB, `scripts/fix-20261102-100704-seed-refresh-check.py`
  → `tmp/fix-20261102-100704-seed-refresh.txt`): **27 tenants** = root + 26
  e2e/demo/probe tenants (the 26 non-root tenants named in the work item, plus
  the `probe-062047-…` probe tenant) — before: `0/27` assistant rows and `0/27`
  skill digests carried the new text; after running the same idempotent refresh
  the startup hook runs: **27/27 assistant rows** and **27/27 skill digests**
  current (`SEED-REFRESH: PASSED`). The running CC serves the refreshed rows
  immediately; the new corpus module text needs the next process restart.
- `compileall` clean on both changed modules. Stack NOT restarted — Work Item 2
  (frontend topology) owned the restart window and was still running its suite;
  restart-on-deploy will pick up the corpus + constants. Live services healthy
  at the time of handoff (CC 8000 / AR 8001 / CH 8002 → `200`).

### Documentation Updates
- `tech-spec.md` — §15 (assistant knowledge/instruction genericization: principle
  entries, wording policy, digest refresh contract, Code Reference Map rows).
- `test-plan.md` — FIX-20261102-100704 section.
- `fix-log.md` — this entry.

### Work Item 2 — topology pending-load states (frontend)

**Requirement (user verbatim):** *"When we load the agent topology, when
network is slow, some of the entities are not resolved on time and showing some
id or empty before it's loaded. Can you add a spinner for things that are
pending load in the diagram so user knows to wait."*

**Root cause.** `PanelTopologyCanvas` composes labels from independent
react-query lists/details but ignored their loading states: each bound entity
fell back to `names[id] ?? id` (or a generic label), so on a slow network the
diagram showed raw ids/blank placeholders with no "wait" signal — and the
MCP-tools zone asserted "No tools" before the tool catalogue arrived. The same
canvas drives the Agent Type Details preview, so one fix covers both surfaces.

**Fix (single canonical canvas — no preview-specific diagram).**

- `PanelTopologyPending` (typed, all-false `NO_PENDING` default) is built in
  the canvas from each query's `isLoading` and passed to
  `buildPanelTopology(..., pending)`; the composer stays pure.
- Bound entity with a cached name → resolved (never flickers). Bound entity
  whose request is in flight → `pending: true` + i18n `loading` label — never
  the raw id. Request completed but row absent → historical raw-id fallback
  (genuinely missing, no spinner).
- Pending coverage: identity, role, model, typed input slot (registry data-type
  lookup), output data type, skills (direct + SOP-composed), SOPs, the SOP
  composition chain (`sop_pending_<sopId>` indented child while the bound-SOP
  detail loads), and the tools zone (`tool_pending` while skill/tool/server
  data is in flight, instead of the "No tools" placeholder).
- Deliberate states untouched: solid `None` / `Conversation` / `Auto` /
  locked-output nodes and dashed unfilled placeholders keep their semantics
  and never carry `pending`.
- `TopologyDiagramRenderer`: `TopologyNode.pending` swaps the entity icon for
  an SVG `PendingSpinner` in the SAME viewBox slot (same diameter as the icon,
  viewBox units → scales with responsive width, `fillHeight`, viewBox zoom and
  the font-scale cap; no layout jump). Accessible `role="progressbar"` +
  localized `aria-label`/`<title>`; SMIL rotation inside the SVG. Pending nodes
  are click-inert (no detail navigation) and marked `data-pending="true"`.

### Test Cases Added/Modified (Work Item 2)
- `frontend/src/__tests__/PanelTopologyCanvas.test.tsx` (+9): composer pending
  placeholders for every bound entity (no raw ids), resolved-but-missing keeps
  raw-id fallbacks with no pending flags, cached names never pending,
  deliberate None/Auto/unfilled states never pending, tools zone pending while
  SOP details load then genuine "no tools"; canvas tests with stalled
  `apiClient.get` requests (pending nodes for identity/role/model/input/
  output/skill/SOP + `sop_pending_sop-1` + `tool_pending`, then resolution →
  real labels/tool nodes, no pending), and None/Auto + unbound-draft dashed
  placeholders staying pending-free mid-load.
- `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` (+4): accessible
  spinner (`role=progressbar`, aria-label/title, `animateTransform`) replaces
  the entity icon, viewBox-unit geometry under zoom/font cap, resolved node has
  no spinner, pending node click does not call `onNodeClick`.
- `frontend/src/__tests__/PanelTopologyTokenHealth.test.tsx` — labels fixture
  gains `loading` (typing only).

### Code Changes (Work Item 2)
- `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` —
  `PanelTopologyPending` + `NO_PENDING`; `PanelTopologyLabels.loading`;
  `resolveRef`/`refLabel` (resolved → loading → raw id); pending-aware node
  labels/flags; pending SOP-composition child; `tool_pending` vs `tool_empty`
  rule; canvas reads `isLoading` from roles/identities/skills/SOPs/SOP
  details/data types/available models/MCP tools/MCP servers and passes the
  flags (memo deps updated).
- `frontend/src/components/agents/TopologyDiagramRenderer.tsx` —
  `PendingSpinner` component; pending icon swap; click-inert pending nodes;
  `data-pending` marker; localized loading text.
- `frontend/src/types/index.ts` — `TopologyNode.pending?: boolean`.
- `frontend/src/i18n/locales/en.json` — `agents.panel.topologyLoading`
  ("Loading…").

### Verification Results (Work Item 2)
- TDD: **7 failed / 95 collected** before the change (no spinner/pending
  flags, raw ids leaking in the composer, no pending tools placeholder) →
  **102/102** across PanelTopologyCanvas + TopologyDiagramRenderer +
  PanelTopologyTokenHealth after.
- `npx tsc --noEmit` clean.
- Targeted regression: PanelTopologyCanvas, PanelTopologyTokenHealth,
  AgentTypeDetailsDialog (preview via the same canvas), TopologyDiagramRenderer,
  AgentManagementPanelPage = **142 passed / 0 failed**.
- Full frontend `vitest run` = **1837 passed / 0 failed** (1855 collected, 18
  skipped) — no new flakiness; the previously documented order-dependent
  suites were green in this run.
- Frontend-only: Vite HMR picks the change up; no backend service restart
  needed. No backend files touched by this work item.

### Documentation Updates (Work Item 2)
- `tech-spec.md` — §16 (canvas pending-load contract: pending vs missing vs
  deliberate-empty matrix, per-entity flags, tools placeholder rule, renderer
  spinner contract, Code Reference Map rows).
- `test-plan.md` — FIX-20261102-100704 Work Item 2 section (coverage matrix,
  files, failing-first evidence, regression).
- `fix-log.md` — this entry.

---

## FIX-20261102-062047

**Created:** 2026-11-02T06:20:47Z
**Status:** Resolved
**Issue:** (1) SkillEditor duplicates the bound-tools display: the tool-picker (select tools → chips) and the read-only Bound Tools card disagree; existing bindings are not pre-selected. (2) MCP servers `supabase` / `decision` are missing from the tool picker — only 2 MCP groups show.

### Observed Behavior
1. The editor shows both a tool picker (with chips under the button) and a separate read-only Bound Tools card; previously saved bindings are not pre-selected in the picker; the two sections can disagree.
2. `useAllTools()` → `GET /mcp/tools` defaults to `limit=50` with post-fetch dedupe and no stable ordering; the tenant now has ~41 cc tools + system + supabase (30 tools) + decision, so the 50-item window can exclude `supabase`/`decision` tools entirely — the picker groups by server, so those MCPs appear missing.

### Expected Behavior
1. ONE source of truth in the editor: opening it pre-selects all existing bindings in the picker; newly toggled tools update the same selection; view mode shows the same single list read-only.
2. All tenant MCP servers and their tools are visible to `integration::mcp_hub:read` users regardless of the tool-volume (no truncation); cc stays gated on `integration::control_center:read` (read-only there). If a role lacks the cc permission but the skill/agent already uses cc tools, those tools remain VISIBLE read-only (never editable) — visibility of what you depend on must not be blocked by the admin gate.

### Analysis
- **Affected components:** `frontend/src/components/agents/SkillEditor.tsx` (picker vs bound-tools duplication), `frontend/src/hooks/useMcpServers.ts` (`useAllTools`), `backend/app/api/v1/mcp_hub.py` (`list_all_tools` limit/order/dedupe)
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: existing bindings not pre-selected; tool list truncates at 50
- [x] **Fix** — Picker integration + complete/stable tool listing + read-only visibility for already-bound cc tools
- [x] **Verify** — All layers incl. live picker check
- [x] **Document** — Update affected documentation

### Live Probe (root cause evidence)

Script `scripts/fix-20261102-062047-probe.cjs` → `tmp/fix-20261102-062047-probe-output.txt`
(authenticated root-tenant user; the no-cc-read principal is a real Agent Viewer
PlatformUser signed with the CC secret — the dev/E2E token pattern).

**Pre-fix baseline (recorded on the running stack):**

| Call | Result |
|---|---|
| `GET /mcp/tools` (default) | `200`, **exactly 50 tools** — `{system:16, cc:34}`, **`supabase`, `map-demo`, `decision` absent** |
| `GET /mcp/tools?limit=200` | `200`, 90 tools — `{system:17, cc:41, map-demo:3, supabase:29}` |
| `GET /mcp/tools?limit=50&offset=50` | `200`, 40 rows — the window resumed mid-cc; the frontend never requested this page |
| `GET /mcp/servers?limit=100` (no cc read) | `200`, `[system, decision, map-demo, supabase]` (cc correctly hidden) |
| `GET /mcp/tools?limit=200` (no cc read) | `200`, 90 tools including **41 `cc` tools** (LEAK — the tools endpoint had no cc filter at all) |

Root cause confirmed: `useAllTools()` → `GET /mcp/tools` used `limit=50`; the
endpoint assembled `system + decision + db` in implementation order, deduped,
then sliced `[offset:offset+limit]`. The tenant's 90 tools pushed `supabase`
(29) and `map-demo` (3) entirely past the window, so the picker (grouped by
server) rendered only system + cc. Secondary defect: `list_mcp_servers` applied
the cc filter AFTER `offset/limit`, so filtered pages could be short/shifted,
and `list_all_tools` never applied the cc permission filter — cc tools leaked
to users without `integration::control_center:read`. `SkillEditor` also had two
disagreeing surfaces: picker chips (only for tools present in the truncated
catalogue) and the separate read-only Bound Tools card.

**Post-fix probe (same script, stack restarted):** default window = 90 tools
(`{system:17, cc:41, map-demo:3, supabase:29}`, `X-Total-Count: 90`), ordering
exactly `(server_slug, name)`, limit=50 paging covers the identical set with no
loss/duplication; no-cc-read user sees 49 tools with zero `cc`, `GET
/mcp/servers` keeps `cc` hidden with full pages (`limit=3` walk:
`system, decision, map-demo, supabase`, no duplicates), and the cc tool already
referenced by `control-center-management` resolves individually (`GET
/mcp/tools/5371efa1-…` → `200 cc____create_agent_identity`). `LIVE-PROBE-PASSED`.

### Design — ONE editor surface
- `SkillEditor` has a SINGLE selection state (`selectedToolIds`), initialised
  from the skill's `tool_ids` / `tool_bindings` (detail payload authoritative,
  applied once per skill and never clobbering a user change).
- The picker (Select Tools dialog) and the grouped list are the same state: the
  list under the button IS the display + editor. Each entry renders
  `original_name || name` (`<code>`), owning-server chip, canonical name, and a
  remove affordance in edit mode (explicit unbind — the REST PUT replaces
  bindings). View mode renders the identical grouped list read-only.
- The duplicate read-only "Bound Tools" card was removed. List-page count
  column (FIX-015138) untouched.
- Control Center tools absent from the browsable catalogue are reconstructed
  from `tool_bindings` (now carrying `tool_id`) and pinned read-only, so saving
  can never silently drop a dependency the caller cannot see. Other unbrowsable
  ids (stale/deleted tools) stay visible from the binding payload and remain
  removable.

### Visibility rule — referenced cc tools
- General browsing: `list_all_tools` hides all cc tools without
  `integration::control_center:read`; `list_mcp_servers` continues to hide the
  cc server (now with correct pre-slice filtering).
- Dependency visibility: `GET /mcp/tools/{tool_id}` resolves a cc tool ONLY
  when a skill binding of the caller's tenant references it
  (404-without-leak otherwise). The editor pre-selects those tools from the
  binding payload, renders them checked/disabled in the picker and locked in
  the list, with the i18n note "Access to this tool requires the Control Center
  integration permission — shown read-only because this skill uses it." The
  rest of the cc catalogue is never exposed.

### API contract changes
- `GET /mcp/tools`: default `limit` 50 → **200** (cap unchanged, ≤200); full set
  is deduped + sorted `(server_slug, name, id)` BEFORE slicing; cc filtered
  by permission; `X-Total-Count` header states the true total.
- `GET /mcp/servers`: system/decision exclusion + cc permission filter moved
  INTO the query (before `offset/limit`); deterministic `ORDER BY (name, id)`;
  pagination runs over the full logical ordering where the two virtual servers
  occupy slots 0–1; `X-Total-Count` = db total + 2.
- `GET /mcp/tools/{tool_id}` (NEW): individual resolution with the
  referenced-cc read-only rule; resolves virtual system/decision ids too.
- `SkillToolBindingRead.tool_id` added (REST parity with the management
  toolset's `tool_bindings`).
- CORS `expose_headers=["X-Total-Count"]`.
- `useAllTools()` / `useMcpServers()` with no arguments page until a short page
  (200-item pages); explicit `(limit, offset)` callers keep single-page
  semantics (McpToolBrowser pagination unchanged).

### Test Cases Added/Modified
- `backend/tests/unit/test_fix_20261102_062047_mcp_tool_listing.py` (NEW, 11):
  default window not truncated at 50; no loss/duplication across pages; stable
  ordering; `X-Total-Count` accurate; cc tools hidden without read / listed
  with read; referenced cc tool resolvable; unreferenced cc tool 404; non-cc
  tool resolvable; virtual decision tools in the complete listing; server
  pagination filters cc before slicing / includes cc once with read.
- `frontend/src/__tests__/SkillEditor.singleSurface.test.tsx` (NEW, 6):
  bindings pre-selected from `tool_bindings`; referenced cc tool read-only +
  note and not removable; picker toggling updates the SAME list; save keeps the
  union (removing `run_sql` still persists the locked cc id); view mode renders
  one read-only list; zero-binding indicator.
- `frontend/src/__tests__/useMcpServers.pagination.test.tsx` (NEW, 3): hook
  pages past 200; explicit paging callers unchanged; server catalogue pages.

### Code Changes
- `frontend/src/components/agents/SkillEditor.tsx` — single-surface selection
  list (`buildSkillToolEntries`, `groupToolEntries`), detail-authoritative
  initialisation (dirty-ref guard), read-only referenced group in the picker,
  locked entries preserved in save payload, Bound Tools card removed.
- `frontend/src/hooks/useMcpServers.ts` — paged `useAllTools`/`useMcpServers`.
- `frontend/src/types/index.ts` — `SkillToolBindingInfo.tool_id`.
- `frontend/src/i18n/locales/en.json` — `skills.editor.referencedTools`,
  `referencedToolReadOnlyNote`, `removeTool`.
- `backend/app/api/v1/mcp_hub.py` — `list_all_tools` (default/order/cc/total),
  `list_mcp_servers` (pre-slice filter + total), `get_mcp_tool` +
  `_tool_referenced_by_skill`.
- `backend/app/schemas/skills.py` — `SkillToolBindingRead.tool_id`.
- `backend/app/main.py` — CORS exposes `X-Total-Count`.

### Documentation Updates
- `fix-log.md` — this entry (probe evidence, design, contract, results).
- `tech-spec.md` — section 14 (single-surface editor + listing contract + cc
  read-only dependency rule).
- `test-plan.md` — FIX-20261102-062047 section.
- `implementation-plan.md` — Phase 17.

### Verification Results
- TDD (backend): legacy mutation of the new handler behavior → **4 failed / 6
  passed**; after fix **11/11 passed**.
- TDD (frontend): new editor suite **2 passed / 4 failed** before the change →
  **6/6 passed**; hook suite 3/3; existing SkillEditor/table suites **54/54**.
- Backend targeted: new suite 11/11; FIX-223511 bindings 8/8; skill-bindings
  management + tenant-isolation sweep + new suite **93 passed**.
- cc permission suite: **28 passed, 1 failed** — `test_grant_on_cc_tool_
  with_manage_allowed` (mock ordering drift; confirmed failing with this fix
  reverted). `tests/api/v1/test_mcp_hub_api.py`: 20 passed / 9 pre-existing
  failures (confirmed with the fix reverted). `tests/api/v1/test_skills_api.py`:
  8 pre-existing failures from stale MagicMock bindings (confirmed with the
  new schema field removed).
- `npx tsc --noEmit`: clean.
- Live probe: `LIVE-PROBE-PASSED` (see evidence above); stack restarted, all
  services healthy.
- Full vitest: **452 files passed / 0 failed; 1825 tests passed / 0 failed / 18
  skipped** (1843 total). Final-code focused re-run of the five touched suites:
  38/38 passed; `tsc --noEmit` clean.
- Stack restarted via `scripts/restart-backend.sh`: CC/CH/AR/Frontend ready,
  "All services healthy."

### Follow-ups
- `decision` has zero configured tools in the root tenant (the virtual server is
  listed and the order/listing path is covered by unit tests with a seeded
  decision tool); the picker will show the decision group as soon as the tenant
  defines one.

---

## FIX-20261102-015138

**Created:** 2026-11-02T01:51:38Z
**Status:** Resolved
**Issue:** Skill tool-binding UX refinement — the table should show a COUNT (as before), while the skill VIEWER and EDITOR should show the full bound-tools list

### Expected Behavior
- Skills table: "N tools" count (keep the explicit "No tools bound" indicator for zero)
- Skill viewer + editor (`SkillEditor.tsx`): full bound-tools list (tool name + server)

### Analysis
- User feedback on FIX-20261101-223511: per-tool chips in the table are too noisy; the table only needs a count, while the full list belongs in the detail surfaces.
- `SkillEditor.tsx` doubles as BOTH viewer (`mode="view"`) and editor — one shared component covers both modes.
- `tool_bindings` (`[{name, original_name, server_slug, server_name}]`) already arrives from the API since FIX-223511; this fix is frontend display only.

### Fix Tasks
- [x] **Reproduce** — Failing tests: table shows per-tool chips instead of count; viewer/editor lack the full list
- [x] **Fix** — Table count + viewer/editor full list
- [x] **Verify** — All layers
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- `frontend/src/__tests__/SkillsToolBindingsVisibility.test.tsx` — rewritten: table renders "2 tools" count (no per-tool chips), count carries a native `title` tooltip listing tool names, zero-binding skill still shows muted "No tools bound".
- `frontend/src/__tests__/SkillEditor.boundTools.test.tsx` — NEW: view mode renders the full bound-tools list (original tool name + server chip + canonical name) from the `tool_bindings` payload; edit mode renders the same read-only list; zero-binding skill shows "No tools bound" inside the Bound Tools section.

### Code Changes
- `frontend/src/pages/skills/SkillListPage.tsx` — tool column: replaced per-tool `Chip` list with a "N tools" count (`t('skills.toolCountValue', {count})`) wrapped in a native `title` tooltip listing the bound tool names; kept the muted italic "No tools bound" chip for zero bindings.
- `frontend/src/components/agents/SkillEditor.tsx` — new read-only **Bound Tools** card (shown whenever a skill is loaded, i.e. both view and edit modes; also visible for system skills). Renders each binding as `original_name || name` in `<code>` + owning-server `Chip` (`server_name || server_slug`) + canonical `name` as muted caption; shows "No tools bound" when the list is empty. Data source: `skillDetail?.tool_bindings ?? skill?.tool_bindings` (list payload + detail fetch). Binding editing behavior unchanged.
- `frontend/src/i18n/locales/en.json` — added `skills.toolCountValue` ("{{count}} tools") and `skills.editor.boundTools` ("Bound Tools").

### Documentation Updates
- `fix-log.md` — this entry.
- `tech-spec.md` — SkillEditor component contract updated (Bound Tools section; table shows count).

### Verification Results
- TDD evidence: `SkillsToolBindingsVisibility.test.tsx` failed pre-fix (expected "2 tools", got chips; tooltip test failed) → 3/3 pass post-fix. `SkillEditor.boundTools.test.tsx` new, 3/3 pass.
- `npx tsc --noEmit` — clean (exit 0).
- Full vitest run: **169 files passed / 1 skipped, 1816 tests passed / 18 skipped, 0 failed** (22 min; the known DecisionToolForm/AppShell full-run flakiness did NOT recur in this run).
- Frontend build confirmed via `tsc --noEmit` + full test-suite transform; no backend changes, no stack restart needed (Vite HMR).

### Test Environment Note
- A "hung" vitest run during development was traced to (a) overlapping background vitest instances saturating CPU, and (b) inline hook mocks returning a NEW object per call (`useSkillRoles: () => ({ data: [] })`) feeding `SkillEditor`'s `useEffect([currentRoleIds])` state loop. Mocks in `SkillEditor.boundTools.test.tsx` return a stable module-level `EMPTY_ARRAY`.

---

## FIX-20261101-223511

**Created:** 2026-11-01T22:35:11Z
**Status:** Resolved
**Issue:** (1) Skill↔tool association invisible — Skills UI never displays bound tools, so correctly-associated skills look unassociated; (2) approval card too narrow for tables, no standard preview format, no expand/maximize

### Observed Behavior
- `list-supabase-projects` (2026-11-01 22:26) IS bound to `supabase____list_projects` in the DB, but the Skills UI shows no binding information — users conclude the association is missing.
- The confirmation card renders markdown tables in a narrow surface; no way to expand; no standard preview format the assistant reliably follows.

### Expected Behavior
- Skills list/detail show the bound tools (tool name + owning server).
- `create_skill` with zero tool bindings returns a structured warning the assistant relays and self-corrects.
- A STANDARD confirmation preview format (defined markdown table contract) is taught and used; the approval card can be expanded/maximized to full width for large tables.

### Analysis
- **Affected components:** `frontend/src/pages/skills/SkillListPage.tsx` (+ detail view), `management_tools.py` (create_skill zero-binding warning), `assistant_knowledge.py` + `assistant_seeder.py` (preview-format contract), `InlineInterventionDialog.tsx` / confirmation card surface (expand/maximize)
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: UI shows no bindings; no expand affordance; create_skill silent on zero bindings
- [x] **Fix** — UI binding display + zero-binding warning + preview-format contract + expandable approval card
- [x] **Verify** — All layers incl. live confirmation turn with a wide table
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
<!-- Will be updated -->

### Code Changes
<!-- Will be updated by developer -->

### Documentation Updates
<!-- Will be updated as docs are revised -->

### Verification Results
<!-- Will be updated after verification -->

---

## FIX-20261101-120618

**Created:** 2026-11-01T12:06:18Z
**Status:** In Progress
**Issue:** Enhancement set: (1) View All Sessions upgrades to the full sessions-tab experience — ended-sessions toggle (default active-only), pagination ordered time desc, time-range search, default query window last 7 days (configurable); (2) built-in inherent skills giving EVERY agent self-context + workflow-optimization system tools without user configuration

### Work Item 1 — Sessions view + API
Sessions list API gains pagination + status filter + date-range params + configurable default window (Settings, default 7 days); the chat "View All Sessions" dialog presents the sessions-tab experience (toggle/pagination/date-range), ordered time desc.

### Work Item 2 — Inherent optimization skills
The optimization toolset (get_implementation_plan, get_optimized_implementation_plan, generate_optimized_plan, generate_script, execute_script, list_scripts, get_script, get_scripts, get_execution_log) becomes inherently available to every agent via built-in system skills (self-context + workflow optimization) — no user configuration, no per-agent binding rows.

#### Work Item 2 — Inherent optimization skills (backend)

- **Inherent set definition** (`backend/app/services/agents/builtin_skills.py`, new):
  `self-context` (get_implementation_plan, get_optimized_implementation_plan, get_scripts,
  get_execution_log) + `workflow-optimization` (generate_optimized_plan, generate_script,
  execute_script, list_scripts, get_script + the read tools for the Optimize & Verify loop).
  Definitions derive from `SystemToolRegistry` at request time and fail closed on registry
  drift; all tools are `general`-category ⇒ canonical `system____<name>` (FIX-000319 scope).
- **Injection mechanism**: dynamic merge in `get_agent_context`
  (`backend/app/api/v1/internal/agent_data.py`) AFTER both role'd and role-less branches —
  `allowed_tools` gains the canonical names (the existing system-tool schema loop emits the
  OpenAI definitions / `tool_name_map` entries) and the skills summary gains both inherent
  skills (deterministic uuid5 ids, not DB rows). Idempotent, cheap, zero
  `AgentTypeSkillBinding` rows, no confirmation/HITL (system tools, not management wrappers),
  sandboxing unchanged (`execute_script` stays AR-sandboxed), guardrail iteration budget
  still applies.
- **Deliberate test-contract updates**: assistant context is now exactly meta tools +
  inherent set (`test_fix_20261031_035145_assistant_tool_context.py::test_t1`,
  `test_fix_20261031_133253_confirm_before_write.py::test_assistant_context_definitions_include_human_intervene`);
  "empty role ⇒ zero system tools" updated to "only the inherent set auto-injects"
  (`tests/integration/test_tool_naming_refactor.py`).
- **Verification**: `tests/communication_hub/test_fix_20261101_120618_inherent_skills.py`
  5/5 (failing-first: collection ImportError before `builtin_skills.py` existed). Targeted
  regression (inherent-skills, 035145, 133253, seeder, meta-tools, cc-naming, bridge,
  role-service, tenant-isolation): **127 passed**; communication_hub suite (earlier run):
  280 passed / 2 failed (`test_tenant_header_verification.py` — pre-existing at HEAD,
  verified on a clean HEAD worktree). Full `tests/unit + integration + agent_runtime +
  security` run: 1808 passed / 150 skipped / 30 failed — **none caused by this change**:
  with the injection block temporarily disabled (baseline), 24 of the 30 fail identically
  (order-dependent shared-DB pollution: service-auth/cert-chain/decision-binding/
  tool-naming-seed suites, including the SQLite `seed_system_tools` UUID-affinity bug), and
  the remaining 6 all PASS in isolation WITH the change enabled (re-run:
  cc-permission grant, cert-paths, 3× decision bindings, 2× cross-service cert flows).
  `tests/unit/test_setup_tenant_demo.py` has a pre-existing `ModuleNotFoundError: setup`
  collection error unrelated to this fix. Imports compile clean (`compileall` + full
  collection); stack NOT restarted (coordinated — the other work item owns the restart).

### Fix Tasks
- [x] **Reproduce** — Failing tests: sessions API filters/pagination (Work Item 1; Work Item 2 owned by the concurrent inherent-skills developer)
- [x] **Fix** — Both work items
- [x] **Verify** — All layers
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

Work Item 1 (this section — sessions view + API):
- `backend/tests/integration/test_conversations_sessions_query.py` (new, 13 tests, failing first —
  `list_sessions_page` did not exist): time-desc ordering; default 7-day window excludes older
  sessions; explicit `date_from` overrides the window; `all_time` escape hatch; status semantics
  (`active` only / `ended` = closed+archived / `all`); pagination + total; tenant isolation;
  legacy `list_sessions` backward compat; endpoint default window + new params accepted;
  `conversation_sessions_default_window_days` Settings default = 7.
- `frontend/src/__tests__/ConversationDialog.sessionsView.test.tsx` (new, 6 tests, failing first —
  no toggle/pagination/date inputs): default active-only + last-7-days window; ended sessions
  marked (chip) and not resumable; toggling refetches with `status=all`; pagination requests
  page 2; date-range changes refetch with from/to; switching resumes in place (no end/archive);
  i18n keys for all new controls.
- Updated: mocks in 7 existing suites gained the `useConversationSessionsPage` export
  (`ConversationDialog.actionBar` also feeds its two sessions through the new page hook);
  `ConversationDialog.actionBar` "View All Sessions / switching resumes" now exercised via the
  upgraded list.

### Code Changes

1. **Backend**
   - `backend/app/core/config.py` — `conversation_sessions_default_window_days: int = 7`
     (env `CONVERSATION_SESSIONS_DEFAULT_WINDOW_DAYS`).
   - `backend/app/services/conversations/store.py` — `list_sessions_page()`:
     status semantics (`active` → status==active; `ended` → closed/archived/error; `all`/None →
     everything), `date_from`/`date_to` filters, default lower bound
     `now − conversation_sessions_default_window_days` when no explicit range and not
     `all_time`, `updated_at` DESC, `page`/`page_size` (min-1 clamped), full filtered
     `total` via count subquery. Legacy `list_sessions` untouched.
   - `backend/app/schemas/conversations.py` — `ConversationSessionPageRead`
     (`items/total/page/page_size/default_window_days`).
   - `backend/app/api/v1/conversations.py` — new `GET /conversations/sessions`
     (declared before `/{session_id}`), 422 on invalid `status`/page params; response carries
     `default_window_days` so the UI mirrors the configured window. Tenant-scoped as today.
2. **Frontend**
   - `frontend/src/hooks/useConversationSessions.ts` — `useConversationSessionsPage` +
     `ConversationSessionsPageParams`/`ConversationSessionsPage` types (query to
     `/conversations/sessions`).
   - `frontend/src/components/agents/ConversationDialog.tsx` — `SessionSwitcherList` upgraded:
     active/ended Switch (default off → `status=active`; on → `status=all`), From/To date
     TextFields defaulting to the 7-day window (`DEFAULT_SESSIONS_WINDOW_DAYS`), MUI
     `Pagination` (page size 10, `total`-driven, resets on filter change), time-desc rows with
     title/status/updated time, "Ended" chip on non-active rows (no resume button), Resume on
     active non-current rows (FIX-111439 in-place switch preserved).
   - `frontend/src/i18n/locales/en.json` — new keys `conversations.sessions.showEnded`,
     `dateFrom`, `dateTo`, `endedTag`.

### Documentation Updates

- `tech-spec.md` §11b (endpoint contract + Code Reference Map), `test-plan.md`,
  `implementation-plan.md`, this log.

### Verification Results (Work Item 1)

- Backend: new suite failed first (ImportError/AttributeError on `list_sessions_page`,
  missing endpoint) → **13/13 pass** after implementation.
- Backend regression: `test_conversations.py` + sessions-query + end-termination +
  intervention-API suites = **32 passed**; `tests/unit` + `tests/api` = **1279 passed**;
  the extra failures vs a clean-HEAD worktree run are environmental (cert-file presence and
  dev-database state in this working repo — verified: the clean HEAD worktree shows exactly the
  10 pre-existing failures already documented in FIX-000319's log, and none of the extras touch
  conversations code).
- Frontend: new suite failed first (no toggle/pagination/date controls rendered) → **6/6 pass**;
  full `npx vitest run` = **1804 passed / 0 failed (18 skipped)** across 166 files;
  `tsc --noEmit` clean.

---

## FIX-20261101-111439

**Created:** 2026-11-01T11:14:39Z
**Status:** Fixed
**Issue:** (1) Post-approval execution failed with `GuardrailStop('iteration_limit')` at 11/10 — the full agent-creation workflow needs more tool-step iterations than the seeded default (10); surfaced as a generic error; (2) chat window needs an action bar: View All Sessions / New Session (keeps old) / End Session / Exit — for the chatbot and all conversational agents

### Analysis
- **Affected components:** `assistant_seeder.py` (assistant `guardrail_max_iterations`), guardrail error surfacing (CH `ws/chat.py` / AR conversation API), `ConversationDialog.tsx` action bar (frontend)
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: iteration-limit on the multi-step workflow; action-bar options
- [x] **Fix** — Assistant iteration budget + clear guardrail error + action bar (4 options)
- [x] **Verify** — All layers
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

Backend:
- `tests/unit/test_assistant_seeder.py` — `test_seeder_sets_workflow_iteration_budget`,
  `test_seeder_refreshes_stale_iteration_budget` (failing first: budget was default 10).
- `tests/communication_hub/test_fix_20261101_111439_iteration_limit.py` (new) — AR forwards
  guardrail reason on the streaming error chunk; CC maps `iteration_limit` → structured
  `ConversationTurnError` and persists a clear error turn; other guardrail stops map generically;
  GuardrailCallback still raises with details.

Frontend:
- `src/__tests__/ConversationDialog.actionBar.test.tsx` (new, failing first) — 4-option action
  bar renders; New Session creates a fresh session WITHOUT end/archive and does NOT set the
  force-new flag, and clears messages; View All Sessions lists sessions and switching resumes the
  chosen one (no end/archive of the previous); End Session still calls end + sets force-new flag;
  Exit closes with zero API calls; New Session disabled while a turn is streaming.

### Code Changes

1. **Defect 1 — iteration budget (raised to 24).** The documented agent-creation workflow needs
   11+ tool iterations (list_agent_identities + list_agent_roles + list_model_configs +
   get_mcp_server tool discovery → create_skill → create_agent_identity → create_agent_role →
   update_agent_role grant → create_agent_type; each tool call costs one guardrail iteration).
   24 ≈ 2× headroom over the observed 11-step exhaustion while still bounding runaway loops.
   - `assistant_seeder.py`: `ASSISTANT_GUARDRAIL_MAX_ITERATIONS = 24`, set on create and
     refreshed in the update branch (stale seeded rows carrying 10 are upgraded).
   - The per-agent-type budget flows through `GET /internal/data/agent-context`
     (`guardrail_policy.max_iterations` = `AgentType.guardrail_max_iterations`) into
     `_build_guardrail_state` in `runtime_executor.py`; `GuardrailCallback` and the inline
     executor checks both read this state — no other change needed.
2. **Defect 1 — clear error surfacing.**
   - AR `agent_runtime/api/conversation.py`: a `GuardrailStop` on the streaming path now emits
     `{"type": "error", "error_type": <reason>, "error_details": {...}}` instead of a bare
     `{"type": "error"}`.
   - CH `api/ws/chat.py`: `_conversation_turn_error_from_guardrail_stop()` maps
     `iteration_limit` → `ConversationTurnError("iteration_limit", "This task needed more steps
     than allowed (limit N). Try breaking it into smaller requests or ask an administrator to
     raise the step limit.")`; other guardrail reasons map to
     `guardrail_<reason>` with a generic "safety limit" message. `run_conversation_turn`
     persists the clear error turn (status event + agent message + `append_conversation_turn`)
     following the `timeout_or_failed` structured-error pattern.
3. **Defect 2 — action bar (all conversational agents).** `ConversationDialog.tsx` footer
   replaced with a 4-option action bar (all strings via `t()`): View All Sessions (opens a
   switcher dialog reusing the `useConversationSessions` query; resuming calls
   `POST /conversations/{id}/resume` in-place), New Session (resets message state + creates a
   fresh session via `POST /conversations`; current session stays `active`; never calls
   end/archive; no force-new flag), End Session (unchanged semantics: end mutation +
   `markAssistantSessionEnded` + close), Exit (unchanged `onClose`). Switch/end actions are
   disabled while a turn is streaming (`turnStreaming`). Heartbeat/timeout/reconnect/
   confirmation flows untouched. New i18n keys: `conversations.sessions.viewAllSessions`,
   `viewAllSessionsTitle`, `newSession`, `currentSession` (en.json).

### Verification Results

- Backend failing→passing: new seeder tests failed at default 10 → pass after fix.
  `tests/communication_hub/test_fix_20261101_111439_iteration_limit.py` + `test_assistant_seeder.py`
  = **15 passed**.
- Backend regression: `tests/communication_hub` (150 passed; the 2
  `test_tenant_header_verification.py` failures are pre-existing at HEAD, verified in a clean
  worktree), guardrail/executor/ws-chat/HITL/confirm suites = **181 passed, 6 skipped** total
  across the targeted run.
- Frontend: new action-bar suite 6/6 (failed-first before implementation); regression
  ConversationDialog ×4 + AppShell ×3 suites = **66 passed**; full vitest **1798 passed /
  0 failed (18 skipped)**; `tsc --noEmit` clean.

### Documentation Updates

- `tech-spec.md` Code Reference Map, `test-plan.md`, `implementation-plan.md`, this log.

---

## FIX-20261101-090438

**Created:** 2026-11-01T09:04:38Z
**Status:** In Progress
**Issue:** The `cc` MCP entity must be system-managed: immutable (no edit/delete/sync/OAuth-config by anyone — seeding is the only writer) and sessionless (no MCP sessions; access flows through role/skill grants only)

### Analysis
- **Affected components:** `assistant_seeder.py` (cc entity `is_system` marking), `mcp_hub.py` (mutation/session rejection for cc), `McpHubPage.tsx` (system-managed chip, actions hidden, sessions section hidden)
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [ ] **Reproduce** — Failing tests: cc mutations/sessions currently allowed for manage-permission holders
- [ ] **Fix** — System-managed marking + immutable + sessionless (backend + frontend)
- [ ] **Verify** — All layers
- [ ] **Document** — Update affected documentation

### Test Cases Added/Modified
<!-- Will be updated -->

### Code Changes
<!-- Will be updated by developer -->

### Documentation Updates
<!-- Will be updated as docs are revised -->

### Verification Results
<!-- Will be updated after verification -->

---

## FIX-20261101-014511

**Created:** 2026-11-01T01:45:11Z
**Status:** Implemented — verified (backend + frontend, TDD red→green)
**Issue:** The Control Center MCP integration (`cc` entity) and its tools are visible to anyone with generic MCP Hub access — permission system needs explicit control over who can VIEW it and define anything around it (grants/configuration)

### Expected Behavior
Only roles granted the new `integration::control_center` resource type can see the CC entity and its tools (MCP Hub UI/API, management toolset reads); configuring/granting around it requires `manage`. Deny-by-default; wildcards (integration::* / *::*) cover admins. Registered in BOTH the backend manifest and the frontend mirror (critical convention).

### Analysis
- **Affected components:** `backend/app/core/resource_types.py` + `frontend/src/constants/resourceTypes.ts` (new RT + MODULE_GROUPS), `backend/app/api/v1/mcp_hub.py` (entity-scoped enforcement), `management_tools.py` (`list_mcp_servers`/`get_mcp_server` filtering), `McpHubPage.tsx` (visibility), permission presets
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: cc entity visible without the new permission
- [x] **Fix** — RT registration (backend+frontend mirror) + enforcement at API, toolset reads, and UI
- [x] **Verify** — All layers
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- **New** `backend/tests/unit/test_cc_integration_permission.py` (16 tests): manifest registration + integration-group membership; list filters `cc` without read / includes it with read; detail 404-without-leak without read / 200 with read; update+delete on cc → structured 403 (`required_permission.resource_type == integration::control_center`) without manage, allowed with manage; non-cc server mutation unaffected for a plain `integration::mcp_hub` user; grant on a cc tool → structured 403 without manage / 201 with manage; cc tool list → 404 without read; management toolset `_list_resource` omits cc and `_get_resource` 404s without read, returns the record with read.
- **Updated** `backend/tests/unit/test_resource_type_manifest.py` (28→29 entries, integration group 2→3); `backend/tests/integration/test_namespace_permission_evaluation.py` (manifest-count fixtures refreshed — were stale on HEAD, verified pre-existing failures in a clean worktree); `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` (27→28 types, 3 integration submodules, new key asserted).
- **New frontend tests** in `frontend/src/__tests__/McpHubPage.test.tsx`: cc row renders with the protected-integration chip when the (permission-filtered) API returns it; no cc row when the list omits it; a structured 403 from cc deletion surfaces via `PermissionDeniedAlert` (never a silent failure).

### Code Changes
- `backend/app/core/resource_types.py` — `RT_INTEGRATION_CONTROL_CENTER = "integration::control_center"` (actions `read`, `manage`) registered in `ResourceTypeManifest` AND `MODULE_GROUPS["integration"]` (so `integration::*` / `*::*` wildcards cover admins; deny-by-default otherwise).
- `frontend/src/constants/resourceTypes.ts` — exact mirror entry + `integrations` group submodule list.
- `backend/app/api/deps.py` — new non-raising `identity_has_permission(request, db, module, action)` probe (super-admin bypass, identity-plane PlatformUser lookup, tenant-context-aware PermissionEngine evaluation).
- `backend/app/api/v1/mcp_hub.py` — `_gate_cc_server` / `_require_cc_permission` / `_cc_tool_gate` enforcement: server list filters `cc` without read; get/list-tools 404-without-leak; update/delete/sync/OAuth-config and all session mutations on cc → structured 403 without manage; tool-permission list/grant/revoke on cc tools gated (read / manage). Non-cc servers behave exactly as before. External MCP `tools/list` / `tools/call` remain governed by role tool-grants + parity — the entity-view permission governs the MCP Hub ADMIN surface only.
- `backend/app/api/v1/internal/management_tools.py` — `_cc_permitted` helper; `list_mcp_servers` omits the cc entity and `get_mcp_server(cc)` 404s when the TRIGGERING USER lacks `integration::control_center:read` (the assistant acts with the user's scope).
- `frontend/src/pages/mcp/McpHubPage.tsx` — cc row carries a "Control Center" protected chip with explanatory tooltip; row-level action errors (delete 403, sync onError) surface via the standard `PermissionDeniedAlert`.
- `frontend/src/utils/toolNaming.ts` — `CONTROL_CENTER_SERVER_SLUG` / `isControlCenterServer`.
- `frontend/src/i18n/locales/en.json` — `mcp.controlCenter.chip` / `mcp.controlCenter.tooltip`.

### Documentation Updates
- `tech-spec.md` — permission model §: new RT + enforcement points + dual registration note.
- `test-plan.md` / `implementation-plan.md` — new coverage + task group (Phase 12).

### Verification Results
- New backend suite: 16/16 passed (initially failing — TDD red→green: ImportError on the missing RT, then cc visible in list/detail before enforcement was added).
- Manifest suites: `test_resource_type_manifest.py` + `test_namespace_permission_evaluation.py` green; frontend `ResourceTypeManifestMirror` green (40/40 in file set with McpHubPage).
- Regression (targeted): `test_management_mcp_tools.py`, `test_management_tool_permission_parity.py`, `test_cc_naming.py`, `test_cc_seeder_migration.py`, `test_skill_tool_bindings_management.py`, `test_reserved_slugs.py`, `test_mcp_hub_tenant_slug_isolation.py`, `test_assistant_meta_tools.py`, `test_assistant_seeder.py`, `test_tenant_isolation_sweep.py`, `test_platform_permission_gating.py`, `test_permission_engine.py`, `test_fix_20261031_131030_role_grants.py`, `test_default_tenant_roles.py` — all green except three failures **verified pre-existing on HEAD in a clean git worktree** (`test_default_tenant_roles.py::test_agent_manager_covers_full_agent_domain`, and the previously stale manifest-count fixtures in `test_namespace_permission_evaluation.py`, now repaired).
- Frontend: full Vitest run **1790 passed / 0 failed**; `tsc --noEmit` clean.
- `test_mcp_hub_api.py` session-mock failures (6) verified identical on HEAD — pre-existing mock-ordering drift, untouched by this fix.

---

## FIX-20261101-000319

**Created:** 2026-11-01T00:03:19Z
**Status:** Implemented — verified (unit + integration + live WS round-trip)
**Issue:** (1) Skill creation does not associate the tool(s) the skill wraps — a skill can only invoke tools bound to it (`SkillToolBinding`), so skills created by the assistant are non-functional; (2) security: Control Center management tools are exposed as generic `system____*` tools in the shared System MCP entity, with no independent permission control

### Expected Behavior
1. `create_skill` / `update_skill` accept tool associations (MCP tools and/or Control Center tools, by id or name) creating `SkillToolBinding` rows; the assistant's workflow binds the wrapped tool at skill creation.
2. Management tools move to a `cc____` namespace and a dedicated per-tenant "Control Center" MCP entity, split from the System entity — independently grantable; original general-agent system tools (save_data, send_notification, human_intervene, etc.) remain `system____` untouched.

### Analysis
- **Affected components:** `tool_naming.py` (new `cc` reserved server slug), `system_tool_registry.py` (management category + cc naming), `management_tools.py` (skill bindings), seeder (CC entity + row migration), `tool_registry_bridge.py` (cc routing/grantability), knowledge + instructions
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: skill tool-binding absent; cc naming/routing/separation absent
- [x] **Fix** — Skill↔tool bindings + cc____ namespace + CC MCP entity split + migration
- [x] **Verify** — All layers incl. live create-skill-with-binding turn
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
New (TDD, failing first → passing):
- `tests/unit/test_cc_naming.py` (18 tests) — `cc` reserved slug, category-aware canonical names, `is_cc_tool`, general tools unchanged (`system____save_data` etc.), management entries excluded from the generic System entity, CC-server UUID distinctness.
- `tests/unit/test_cc_seeder_migration.py` (4 tests) — old-style `system____` rows + bindings → CC entity + `cc____` rows, skill rebound, legacy rows retired, general rows intact, idempotent across restarts, fresh-tenant path.
- `tests/unit/test_cc_tool_registry_bridge.py` (10 tests) — cc tools listed only when granted; granted dispatch → management handler with parity; ungranted → structured denial (OAuth) / `PermissionError` (API key); `cc____delete_*` declined; meta cc dispatch.
- `tests/unit/test_skill_tool_bindings_management.py` (8 tests) — create_skill with `tool_names`/`tool_ids` binds; update additive + idempotent; unknown tool → structured 404 with NO partial write; tenant-scoped resolution; `cc____` tools bindable; `get_mcp_server` returns its `tools`; knowledge rule retrievable.
Updated to the new cc names (expected, required): `test_tool_registry_bridge.py`, `test_oauth_bearer_auth.py`, `test_management_tool_permission_parity.py`, `test_mcp_oauth_bearer_auth.py`, `test_mcp_protocol_server.py`, `test_fix_20261031_133253_confirm_before_write.py`, `test_fix_20261031_035145_assistant_tool_context.py` (meta definitions now carry sanitised canonical names `cc__…`/`system__…`).

### Code Changes
- `app/services/agents/system_tool_registry.py` — `SystemTool.category` ("general" | "management"); category-aware `canonical_name`/`parse_name`/`canonicalize_name`; `is_cc_tool`; `get_mcp_hub_entries()` → general only; new `get_cc_mcp_hub_entries()`; skill-binding schema enrichment for `create_skill`/`update_skill` (`tool_ids`/`tool_names`); management (36 execution + 4 meta) tools registered `category="management"`.
- `app/services/agents/tool_naming.py` — `"cc"` in `RESERVED_SERVER_NAMES`; `CC_SERVER_SLUG`; `is_cc_tool()`; category-aware legacy bare-name parsing.
- `app/services/agents/assistant_seeder.py` — per-tenant "Control Center" McpServer (slug `cc`, deterministic uuid5 `_tenant_cc_server_id`) + per-tenant `cc____<bare>` McpTool rows; `_retire_legacy_management_rows` deletes legacy `system____<mgmt>` rows + their bindings (general rows untouched); binding rule added to assistant instruction + skill instructions.
- `app/api/v1/internal/management_tools.py` — `_resolve_skill_tool_ids`/`_bind_skill_tools` (create = bind all; update = additive merge, idempotent re-bind no-op; unknown → structured 404, resolve-before-write); `get_mcp_server` returns its synced `tools` (discovery).
- `app/communication_hub/mcp/tool_registry_bridge.py` — `_management_scope_denial` handles `cc____`; cc tools are first-class grantable tools routed to the management handler with parity re-enforcement.
- `app/api/v1/internal/agent_data.py` — role-less assistant context uses category-aware canonical names (`cc____` meta), emits sanitised canonical definitions + populated `tool_name_map`; `cc` accepted alongside `system` for schema emission.
- `app/services/agents/langchain_tool_wrapper.py` — `human_intervene` HITL special-case matches the sanitised canonical name (no regression to the confirmation/HITL flow).
- `app/api/v1/mcp_hub.py` — `cc` reserved slug rejection; `seed_system_tools` retires legacy `system____` management rows from the global System entity (pure-SQL, idempotent).
- `app/api/v1/skills.py`, `app/api/v1/agents.py` — system-tool record lookup / canonicalization cover the cc entries.
- `app/services/agents/assistant_knowledge.py` — new `skill-tool-binding` rule (bind at creation; skills without bindings cannot do anything; `cc____` = Control Center management capabilities, grant deliberately).
- No DB schema migration required (rows are data; verified — no alembic revision needed).

### Documentation Updates
- `tech-spec.md` — naming/permission design + Code Reference Map.
- `test-plan.md`, `implementation-plan.md` — new task group + test cases.

### Verification Results
- **TDD evidence:** new tests failed first (`ImportError: is_cc_tool`, seeder/migration/bridge/binding assertions), then all passed after implementation.
- **Suite:** unit + communication_hub + api: **1407 passed** (10 pre-existing failures verified identical on a clean git worktree of HEAD — SQLite UUID-affinity seeder tests + mock-based session tests, unrelated to this fix); targeted fix suites 117/117 green; confirmation/HITL (133253) and context (035145) suites green; tenant-isolation sweep green.
- **Live verification** (LLM mock scripted mode, real Vite-proxied WS): `scripts/fix-20261101-000319-live.cjs` → **LIVE-VERIFICATION-PASSED** — cc entity present (41 tools incl. management+meta, no general tools), live turn created `live-bound-skill-000319` WITH its `SkillToolBinding` to `cc____list_skills` (verified via REST `GET /mcp/tools/{id}/skills`), and a role without cc grants (`decision-role`) sees NO `cc____` tools in its resolved tool set.

---

## FIX-20261031-133253

**Created:** 2026-10-31T13:32:53Z
**Status:** Implemented — verified (unit + live WS round-trip)
**Issue:** (1) Agent creation produces incomplete shells — assistant created `list-supabase-projects-agent` with model=None, identity=None, role=None (working agents use deepseek + identity + role); (2) assistant must ALWAYS ask for confirmation with a table preview before create/update, and execute only on approval

### Observed Behavior
Assistant created the skill (bound ✓) and the agent type, but with no model/identity/role — a non-functional shell. Older working agents show the correct pattern (deepseek-v4-flash + identity 49bb6057 + role 3ce31663). Tool-call records show the writes happened but no discovery/assembly of the full configuration, and no user confirmation was requested.

### Expected Behavior
1. Creating an agent assembles the FULL working configuration: discover existing identity/role/model (list tools), grant the skill to the role, create the agent type with model_id + identity_id + role_id (+ skill_ids) — never leave a non-functional shell.
2. Before EVERY create/update management action: present a markdown TABLE preview of the exact payload (operation, resource, fields→values) and request approval via the platform's human-intervention mechanism; execute only on approval.

### Analysis
- **Affected components:** `assistant_knowledge.py` + `assistant_seeder.py` (workflow), `system_tool_registry.py` meta set (human_intervene not exposed to the assistant), `agent_data.py` context filter, `management_tools.py` wrapper dispatch (human_intervene reachable), frontend intervention rendering in `ConversationDialog.tsx` (no markdown)
- **Additional root causes found during implementation:**
  - `human_intervene` was not in the assistant's meta tool set (`_META_MANAGEMENT_TOOL_NAMES`).
  - The conversational turn path swallowed `GraphInterrupt` ("HITL not supported for conversational turns") — approval could never resume the assistant's turn.
  - CC `human_intervene` endpoint required an `AgentJob` row (404 for conversation-only sessions; `intervene_requests.agent_session_id` was NOT NULL).
  - LangGraph `interrupt()`/`Command(resume)` REPLAYED the interrupted tool task, re-registering duplicate intervene requests on every resume.
  - `InlineInterventionDialog` rendered `reason` as plain text — markdown table previews showed as raw text.

### Fix Tasks
- [x] **Reproduce** — Failing tests: human_intervene available to assistant context; confirmation workflow knowledge present
- [x] **Fix** — Meta exposure + knowledge/instruction + markdown intervention preview
- [x] **Verify** — All layers incl. live confirmation-flow turn
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
- `tests/communication_hub/test_fix_20261031_133253_confirm_before_write.py` (10 tests): meta-tool exposure (registry, context, seeding, binding), knowledge retrievability (confirmation rule, agent-creation completeness, general payload completeness), seeder instruction + stale-row refresh, AR→CH→CC routing of `system____human_intervene` with signed tenant forwarding.
- `tests/agent_runtime/test_fix_20261031_133253_conversational_hitl.py` (8 tests): `conversation_resume` registry semantics; AR `/internal/resume` resolves conversational interventions before the job-relaunch fallback (and preserves the fallback); conversational tool returns the operator response / explicit `status:"timeout"`; per-conversation scoping.
- `tests/agent_runtime/test_fix_20261031_133253_intervention_wait_bound.py` (2 tests): the strict FIX-091657 LLM-timeout bound is preserved when nothing is pending; the wait is re-armed while an intervention is pending; operator-less timeout ends the turn.
- `frontend/src/__tests__/InlineInterventionDialog.test.tsx` (+2): markdown table reason renders as a real `<table>` (ContentRenderer) and Approve still emits the intervene_response flow.
- Modified: seeder/context tests now expect 5 meta tools; existing suites (035145 context, meta tools, seeder, knowledge, bridge, role grants, bindings, 091657 watchdog/timeouts) all green.

### Code Changes
- `backend/app/services/agents/system_tool_registry.py` — `human_intervene` added to `_META_MANAGEMENT_TOOL_NAMES` (5th always-loaded meta definition; carries no parity).
- `backend/app/services/agents/assistant_knowledge.py` — 3 new corpus entries: `confirm-before-write` (hard CONFIRMATION RULE: markdown table preview + human_intervene approval before ANY create/update; reads unaffected; rejection → do not execute), `agent-creation-completeness` (discover via list_agent_identities/roles/model_configs; reuse or create identity/role; grant skill to role via update_agent_role; model_id only from ENABLED models; preview MUST show model/identity/role/skills/grants; agent without working model AND (identity or role) is non-functional — never create), `creation-payload-completeness` (all required fields in every preview; user fills gaps).
- `backend/app/services/agents/assistant_seeder.py` — instruction rules 2d (completeness) + 2e (confirmation rule); shared `MANAGEMENT_SKILL_INSTRUCTIONS` constant used by BOTH the create and digest branches so pre-fix rows refresh on next startup.
- `backend/app/agent_runtime/conversation_resume.py` (new) — in-process registry keyed by conversation session: `register/resolve/is_pending/wait_for_resume`.
- `backend/app/agent_runtime/api/intervene.py` — AR `/internal/resume` resolves a pending conversational intervention FIRST (delivers the response to the paused tool); job-relaunch fallback unchanged for non-conversation sessions.
- `backend/app/services/agents/langchain_system_tools.py` — `LangChainHumanInterveneTool`: conversational turns (conv_session_id set) now AWAIT the operator response via `conversation_resume.wait_for_resume` (bounded by `conversation_intervention_timeout_seconds`) and return the operator's response — or `status:"timeout"` with an explicit "NOT executed" error — as the tool result; LangGraph `interrupt()` is retained only for task-agent (job) sessions, whose resume path already works. Also returns the `Command(resume)` value for the task path.
- `backend/app/services/agents/runtime_executor.py` — conversational turn bound co-existence: strict `conversation_llm_timeout_seconds` (FIX-091657) preserved, re-armed ONLY while `conversation_resume.is_pending` up to `conversation_intervention_timeout_seconds`; legacy GraphInterrupt/return-based-interrupt fallbacks now wait-and-resume instead of swallowing.
- `backend/app/core/config.py` — new `conversation_intervention_timeout_seconds` (default 240, below the CH turn watchdog bound).
- `backend/app/db/models/intervene.py` + `alembic/versions/a1c3e5d70427_*.py` — `intervene_requests.agent_session_id` now nullable (conversation-scoped requests carry NULL + `conversation_session_id`).
- `backend/app/api/v1/internal/system_tools.py` — CC `human_intervene` accepts conversation-only sessions (no AgentJob); folds the markdown-table `prompt` into `reason` (the request has no prompt column) so previews reach the WS UI; REPLAY IDEMPOTENCY: same conversation+reason → pending request returned deduped; responded request returns the stored operator response as the tool result (LangGraph task-path replays complete without re-interrupting).
- `backend/app/services/agents/intervene_service.py` + `backend/app/api/v1/intervene.py` + `backend/app/api/v1/internal/session_data.py` — respond/resume paths fall back to `conversation_session_id` when `agent_session_id` is NULL; tolerant of None in lazy loads.
- `frontend/src/components/conversations/InlineInterventionDialog.tsx` — question text rendered via `ContentRenderer` (GFM markdown → real table previews); Approve/Deny unchanged (existing `intervene_response` flow).
- `scripts/fix-20261031-133253-live.cjs` + `tmp/fix-133253-scripted.json` — live verification fixture.

### Documentation Updates
- `fix-log.md` (this section), `tech-spec.md`, `test-plan.md`, `implementation-plan.md`.

### Verification Results
- Backend: **112+ related tests green** (133253 suites: 10 + 8 + 2 = 20; regression: 035145 context, assistant meta tools, seeder, knowledge, tool-registry bridge, role grants 131030, bindings 071721, watchdog/llm-timeout 091657, a2a HITL timeout, task delegation router — 55 passed in agent_runtime + 133253 run; `tests/agent_runtime tests/communication_hub`: 169 passed, 3 pre-existing failures unrelated to this fix — verified failing on clean HEAD via worktree: `test_tenant_header_verification` (2, cert-middleware env dependency) and one 091657 timeout test fixed by this change's conditional extension).
- Frontend: InlineInterventionDialog (21) + useChatSession.intervention (9) = 30 passed; `tsc --noEmit` clean.
- **Live verification (REAL turn, Vite-proxied WS `ws://localhost:5173/ws/…`, LLM mock `scripted` mode, real CH/CC/AR stack):** scripted flow → (1) real `invoke_management_tool(list_model_configs)` read (no confirmation needed); (2) real `human_intervene` (approval) dispatched as `intervene_request` WS message with the markdown TABLE preview in `reason` (asserted `/| Field |/` present); (3) script approved via the REAL `intervene_response` WS message → `intervene_status: responded`; (4) on approval the assistant executed the real `create_agent_type` management dispatch — the agent type **actually created** (`fraud-detection-agent-133253`, `model_id=deepseek-v4-flash`, `input_type=conversation`, verified via REST). Final assistant reply: "Live verification complete: agent fraud-detection-agent-133253 was created with model deepseek-v4-flash, identity, role and the skill granted to the role." → `LIVE-VERIFICATION-PASSED`. (Test artifact removed afterwards; stack restarted clean without mock env.)

---

## FIX-20261031-131030

**Created:** 2026-10-31T13:10:30Z
**Status:** Resolved
**Issue:** (1) Every chat errors out — services running with wrong CWD broke relative cert paths (`FileNotFoundError: 'certs/communication-hub-cert.pem'` at LLM-call time); (2) knowledge gap: when the agent uses a ROLE, the created skill must be GRANTED TO THAT ROLE (`AgentRoleSkill`) — the management toolset has no role skill-grant support

### Observed Behavior
1. Chat returns "An error occurred while processing your message" immediately. CH log: `LLM call error ... FileNotFoundError: certs/communication-hub-cert.pem` + `Cannot read CA certificate from certs/ca-cert.pem` — the stack had been restarted with a CWD other than `backend/`, so relative cert paths broke. Health probes passed because cert loading is lazy.
2. Creating an agent does not produce a working authorization chain: agent types bind skills directly, but for role-based agents the skill must be granted to the role (role→skill assignments drive runtime tool access).

### Expected Behavior
1. Chat works regardless of service CWD; misconfigured cert paths fail fast at startup, not mid-conversation.
2. The assistant follows the full authorization workflow: create skill → grant skill to the agent's role (role-based agents) / bind directly (role-less) → create agent type; role create/update tools support skill/SOP grants.

### Analysis
- **Affected components:** CH/AR/CC cert path resolution (relative `certs/…`), `management_tools.py` role handlers (no `AgentRoleSkill`/`AgentRoleSOP` support), `assistant_knowledge.py` + instructions
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: role grant tooling absent; cert-path CWD dependence
- [x] **Fix** — Role skill/SOP grant support + knowledge workflow; CWD-independent cert paths + startup fail-fast
- [x] **Verify** — All layers
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified

**Defect 1 / cert paths:** `backend/tests/unit/test_fix_20261031_131030_cert_paths.py` (12 tests):
- `test_relative_path_anchors_to_backend_root_regardless_of_cwd` — FAILING-FIRST pre-fix (resolution was CWD-relative); runs `resolve_cert_path("certs/communication-hub-cert.pem")` under `monkeypatch.chdir(tmp_path)` and asserts the result is `BACKEND_ROOT/certs/…`.
- `test_resolution_matches_real_cert_layout` — all four deployed relative paths anchor identically from a foreign CWD.
- `test_absolute_path_passes_through` / `test_none_resolves_to_none` / `test_backend_root_is_backend_directory` — explicit absolute config wins; helper invariants.
- `test_ch_certificate_manager_resolves_relative_env_paths` — `CommHubCertificateManager` stores backend-root-anchored `cert_path`/`key_path` even started from a foreign CWD.
- `test_cc_renewal_default_cert_dir_is_anchored` — `cc_service_cert_renewal.DEFAULT_CERT_DIR` is anchored; relative explicit dirs anchor too.
- `test_cc_outbound_clients_resolve_relative_cert_paths` — `CommunicationHubClient` resolves `CC_CERT_PATH`/`CC_KEY_PATH` CWD-independently.
- `test_ensure_cert_files_exist_fails_fast_when_missing` / `..._passes_when_present` / `..._resolves_relative_under_foreign_cwd` — startup validation raises `CertValidationError` listing missing files with actionable guidance.
- `test_startup_fail_fast_ch_main_raises_when_cert_unloadable` — CH `_load_certificate` now RAISES a fail-fast `RuntimeError` ("startup FAILED", resolved path, required env vars) instead of the old warn-and-continue.

**Defect 2 / role grants:** `backend/tests/integration/test_fix_20261031_131030_role_grants.py` (10 tests, TDD — **8 failed before the fix, 10 pass after**):
- `test_update_agent_role_grants_skills` — FAILING-FIRST: `update_agent_role` with `skill_ids` previously ignored them; asserts `AgentRoleSkill` rows exist.
- `test_create_agent_role_grants_skills_and_sops` — create-with-grants writes `AgentRoleSkill` + `AgentRoleSOP` rows.
- `test_grants_resolve_by_name` — id-or-name resolution, tenant-scoped.
- `test_update_agent_role_additive_merge_and_idempotent` — grants ADD (never remove); re-grant is an idempotent no-op (no duplicates).
- `test_update_agent_role_unknown_skill_is_404_no_partial_write` — unknown id → 404 with actionable message ("create_skill"), zero grant rows written.
- `test_create_agent_role_unknown_sop_name_is_404` — unknown SOP name → 404.
- `test_parity_map_roles_and_agent_types_use_bare_agent` — parity unchanged: roles + agent types + identities + model configs all on bare `agent` create/update.
- `test_update_agent_role_denied_without_permission` — wrapper still enforces parity (403).
- `test_get_management_tool_schema_role_includes_grant_fields` — served schemas expose `skill_ids`/`sop_ids` in `data.properties`.
- `test_search_knowledge_returns_role_grant_workflow` — "assign skill to agent role" returns the grant workflow rule.

### Code Changes

**Defect 1 / cert paths (CWD-independent resolution + startup fail-fast):**
- New `backend/app/core/cert_paths.py` — `BACKEND_ROOT` (the `backend/` repo root, derived from `__file__`), `resolve_cert_path()` (absolute paths pass through — explicit `*_CERT_PATH`-style config wins; relative paths anchor to `BACKEND_ROOT`), `ensure_cert_files_exist()` + `CertValidationError` (fail-fast startup validation with actionable message).
- `backend/app/communication_hub/certificate_manager.py` / `backend/app/agent_runtime/certificate_manager.py` — `COMM_HUB_CERT_PATH`/`AGENT_CERT_PATH`/key/CA paths resolved via `resolve_cert_path` in `load_certificate` (bootstrap writes go to the anchored paths too). `.env` `CC_CERT_PATH`/`CC_KEY_PATH` keep working (relative values anchor; absolute win).
- `backend/app/core/cc_service_cert_renewal.py` — `DEFAULT_CERT_DIR` anchored at import; relative explicit `cert_dir` args anchored as well.
- `backend/app/services/control_center/comm_hub_client.py` / `agent_runtime_client.py` — CC outbound cert/key/CA paths resolved CWD-independently.
- `backend/app/communication_hub/main.py` / `backend/app/agent_runtime/main.py` — `_load_certificate` now FAILS FAST: any load/bootstrap failure raises a `RuntimeError` ("… startup FAILED", resolved cert path, required env vars, root error) instead of the previous silent warn-and-continue (`certificate_manager = None`) that produced lazy `FileNotFoundError`s at LLM-call time while health probes stayed green. (AR's CC-reachability fail-fast precedent mirrored.)

**Defect 2 / role grants:**
- `backend/app/api/v1/internal/management_tools.py` — new `_bind_agent_role_capabilities` (mirrors `_bind_agent_type_capabilities`): `create_agent_role` / `update_agent_role` `data` may include `skill_ids` / `sop_ids` (id or name, tenant-scoped, resolved via the existing `_resolve_capability_ids`). Semantics: **ADDITIVE MERGE** — provided entries ADDED to the role's grant set, existing grants never removed (no delete verb in this toolset), re-grant an idempotent no-op; the WHOLE set is resolved BEFORE any write, so an unknown id/name → structured 404 with an actionable message ("Create the skill first (create_skill)…") and no partial write. Hooked into `_create_resource` (before commit) and `_update_resource` for `agent_roles`. Parity already correct (roles enforce bare `agent` create/update — verified via `test_parity_map_roles_and_agent_types_use_bare_agent`).
- `backend/app/services/agents/system_tool_registry.py` — `_enrich_agent_role_grant_schemas()` mutates the registered `create_agent_role`/`update_agent_role` tools in place (stable mcp_hub_ids and parity untouched): adds `skill_ids`/`sop_ids` array properties to `data` and documents the grant semantics + "role-based agents get runtime access from the role's grants — every skill/SOP the agent needs MUST be granted to its role".
- `backend/app/services/agents/assistant_knowledge.py` — new `role-grant-workflow` entry: full authorization workflow for role-based agents (create skill → **grant to the role** via `update_agent_role skill_ids` → create agent type with that role; role-less agents use direct bindings) with the rule "after creating an agent that uses a role, ALWAYS ensure every skill/SOP the agent needs is granted to that role — an ungranted skill is inaccessible at runtime".
- `backend/app/services/agents/assistant_seeder.py` — new `ASSISTANT_SYSTEM_INSTRUCTION` rule 2c (role grants) and the management-skill `instructions` digest extended with the same workflow (seeder diffs instructions → seeded rows refresh on restart). No DB schema changes (existing `agent_role_skills` / `agent_role_sops` join tables reused).

### Documentation Updates
- `tech-spec.md` — Code Reference Map: cert-path resolution module + role-grant helpers; component notes updated.
- `test-plan.md` — new coverage rows for both defects.
- This fix log.

### Verification Results
- **Failing→passing:** Defect 2 `test_fix_20261031_131030_role_grants.py` — pre-fix **8 failed, 2 passed** (parity tests already green); post-fix **10 passed**. Defect 1 `test_fix_20261031_131030_cert_paths.py` — written against the new module (12 passed; the two CWD-dependence tests fail against the pre-fix CWD-relative behavior by construction).
- Regression (all pass): `test_fix_20261031_071721_agent_type_bindings.py` + `test_assistant_seeder.py` (16), `test_assistant_knowledge.py` + `test_tenant_isolation_sweep.py` + `test_assistant_meta_tools.py` (29), `test_fix_20261031_035145_assistant_tool_context.py` + `test_cc_service_cert_renewal.py` + `test_certificate_renewal.py` (29). Prior fixes (timeouts/watchdog/heartbeats/end-termination/force-new, meta tools, bindings) untouched.
- `import app.main` / `app.communication_hub.main` / `app.agent_runtime.main` — clean.
- Live restart via `./scripts/restart-backend.sh` — CC (8000), CH (8002), AR (8001), frontend all healthy; AR log shows "certificate loaded successfully" post-restart. CWD-independent certs make restarts from any working directory safe.
- Live registry check: `get_management_tool_schema('update_agent_role')` (and `create_agent_role`) serve `skill_ids`/`sop_ids` in `data.properties`; parity `("agent","create"/"update")`.

---

## FIX-20261031-091657

**Created:** 2026-10-31T09:16:57Z
**Status:** Resolved
**Issue:** (1) "Thinking" appears then disappears; response never arrives — turn HANGS (AR hung >1h on post-tool LLM call, no timeout); (2) ending a session must clean up and force a NEW session on next open

### Observed Behavior
1. User sends a message (resumed or fresh): "thinking" indicator shows, then disappears; no response, no error. Evidence for session `e329cba6` (2026-10-31 20:09 local): 14 tool calls completed successfully (AR/CH logs), then **AR went completely silent** — zero log lines after 20:09:35 while the process stayed alive (verified: port 8001 responds, log tail frozen mid-turn for 1h+). The turn never completed, never persisted, no error surfaced. The AR deep agent hung on the post-tool LLM call — the conversational model call has no effective timeout. Earlier occurrences (52s/38s turns that DID persist) were the same upstream being slow instead of hung.
2. The WS close code/reason is not logged (diagnostic gap), and there is no keepalive/heartbeat during long turns, so "thinking" silently disappears on idle close.
3. Ending a session marks it closed (works), but the entry resolver then auto-resumes ANOTHER stale active session instead of starting a new one; an in-flight turn is not terminated on end.

### Expected Behavior
1. Long turns stay visibly "thinking" (keepalive), and when the LLM call hangs/fails, a bounded timeout surfaces `timeout_or_failed` to the UI with a clear error; the turn is not left hung forever.
2. Explicit end-session: terminates any in-flight execution, marks the session closed, and the NEXT open starts a NEW session (never silently resumes another stale active one). Plain exit keeps resume semantics.

### Analysis
- **Affected components:** AR conversational executor + model binding (LLM call timeout), CH `ws/chat.py` (`_run_turn_and_reply` watchdog not effective — HTTP timeout disabled for streaming; WS close-code logging; keepalive), `AppShell.tsx` session resolver + end-session flow, CC `/conversations/{id}/end` (in-flight termination)
- **Root cause:** no effective timeout anywhere on the conversational LLM call chain (LangChain client default = unbounded); WS close diagnostics missing; end-session lacks cleanup + "force new" semantics.
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: hung-LLM turn surfaces bounded timeout; end-session forces new session
- [x] **Fix** — LLM/turn timeouts + WS keepalive & close-code logging + end-session cleanup/force-new
- [x] **Verify** — All layers incl. a real WS turn via the Vite proxy (LLM mock mode)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
Backend (all failing-first, now passing):
- `backend/tests/agent_runtime/test_fix_20261031_091657_llm_timeout.py` — hung LangGraph agent invocation is bounded by `conversation_llm_timeout_seconds` and returns `timeout_or_failed` + clear error text; fast turns unaffected.
- `backend/tests/agent_runtime/test_fix_20261031_091657_terminate_conversation_task.py` — AR `/terminate/{id}` cancels in-flight CONVERSATION turn tasks; still 404 with nothing in flight.
- `backend/tests/communication_hub/test_fix_20261031_091657_turn_watchdog.py` — whole-turn watchdog (bounded even on the streaming path), exact-once error-turn persistence, `thinking_heartbeat` keepalive, WS close code+reason logging.
- `backend/tests/api/test_conversations_end_termination.py` — `/end` best-effort termination via `AgentRuntimeClient.terminate_session`; failures never break the end call.
- `backend/tests/test_llm_mock_hang_hook.py` — `LLM_MOCK_DELAY_SECONDS` / `LLM_MOCK_HANG=1` test hooks in the mock provider (enable hanging-model simulation through the REAL stack).
Frontend:
- `frontend/src/__tests__/useChatSession.heartbeat.test.ts` — `thinking_heartbeat` refreshes the thinking indicator timestamp without changing state; `timeout_or_failed` surfaces as terminal status.
- `frontend/src/__tests__/AppShell.forceNewAfterEnd.test.tsx` — after explicit END the next open skips resume/list-pick (starts NEW); without the flag resume-latest-active is preserved.

### Code Changes
Backend:
- `app/core/config.py` — new `conversation_llm_timeout_seconds` (default 120).
- `app/services/agents/runtime_executor.py` — `execute_conversation_turn_from_context` wraps the agent invocation in `asyncio.wait_for`; on timeout emits `timeout_or_failed` (live, via the status-event stream) and returns a clear, persisted error message.
- `app/services/agents/langchain_model_factory.py` — bounded `request_timeout`/`timeout` on ChatOpenAI / AzureChatOpenAI / ChatAnthropic clients.
- `app/api/ws/chat.py` — new `run_conversation_turn` watchdog wrapper (whole turn bounded by `agent_question_timeout_seconds` even on the streaming path); `thinking_heartbeat` keepalive every 15s while a turn is in flight; `WebSocketDisconnect` code+reason logging; per-session pending-turn registry (`cancel_pending_conversation_turn`); the live reply is now delivered BEFORE persistence (`on_reply` hook) so a slow persistence tail can never delay/swallow it; watchdog/cancel paths dedupe (delivered reply is never followed by a duplicate error; error turn persisted at most once).
- `app/agent_runtime/api/conversation.py` — in-flight conversation turn tasks registered on `app.state.conversation_tasks` (keyed by conversation session id), cleaned up when the stream ends.
- `app/agent_runtime/api/terminate.py` — `/terminate/{id}` also cancels in-flight conversation turn tasks.
- `app/communication_hub/api/internal/agent_terminate.py` — terminate forwarding first cancels the CH-side pending turn task, then forwards to AR.
- `app/api/v1/conversations.py` + new `app/services/conversations/termination.py` — `POST /conversations/{id}/end` best-effort terminates in-flight execution via the existing CC → CH → AR machinery; never fails the end call.
- `app/services/agents/llm_mock_provider.py` — test-only `LLM_MOCK_DELAY_SECONDS` / `LLM_MOCK_HANG` hooks.
- `backend/.env` (local dev, gitignored) — added `CC_CERT_PATH`/`CC_KEY_PATH` (CC → CH control-plane calls were rejected "no client certificate", silently breaking all termination forwarding).
Frontend:
- `src/hooks/useChatSession.ts` — `thinking_heartbeat` handling (no-op timestamp refresh; keeps "thinking" alive).
- `src/utils/assistantSessionState.ts` (new) + `src/app/AppShell.tsx` + `src/components/agents/ConversationDialog.tsx` — per-agent-type "force NEW session after explicit END" flag (localStorage), consumed (cleared) on next open; plain exit unchanged; resume resolver still filters `status === 'active'`.

### Documentation Updates
- `tech-spec.md` — timeout/keepalive/termination wiring.
- `test-plan.md` — new test coverage + live-verification scenarios.
- `implementation-plan.md` — wording updated.

### Verification Results
In-process: 12/12 new FIX tests pass (first written as failing tests). Regression: backend ws/chat + communication_hub + agent_runtime + tenant sweeps + mock layer suites — 302 passed, 3 failed (all three verified pre-existing on the HEAD baseline via a clean git worktree: `test_tenant_header_verification.py` ×2, `test_default_tenant_roles.py` ×1). Frontend: 93 passed / 1 skipped across all chat + AppShell + ConversationDialog suites; `tsc --noEmit` clean.
REAL turn verification (mandatory) — executed against the ACTUAL stack (CC 8000 / CH 8002 / AR 8001 / Vite 5173) with the LLM mock layer in scripted mode:
- **Scenario A (slow-but-alive, `LLM_MOCK_DELAY_SECONDS=100`)** — real assistant turn driven through the Vite-proxied WS (`ws://localhost:5173/ws/sessions/…`): `thinking` at 1s, **8 × `thinking_heartbeat` every 15s**, socket survived well past 90s mid-turn, live reply delivered at 133s, agent turn persisted in `conversation_turns` and returned by resume. (`scripts/fix-20261031-091657-live-a.cjs`)
- **Scenario B (hanging model, `LLM_MOCK_HANG=1`, `CONVERSATION_LLM_TIMEOUT_SECONDS=10`)** — `timeout_or_failed` at 10.5s + persisted clear error reply ("Your request timed out…") — bounded, exactly as designed. (`scripts/fix-20261031-091657-live-b.cjs`)
- **Scenario B2 (end-session cleanup)** — turn started under a hanging model; `POST /conversations/{id}/end` at ~5s: session closed, CH log `Cancelled pending conversation turn … (session ended)`, WS received `timeout_or_failed` + error message at 5.5s (well before the 10s AR bound), CC log confirms the full CC → CH → AR forwarding chain; AR `/terminate` conversation-task cancellation is covered by the in-process test (AR had already unwound its stream-coupled task by the time the forward arrived). WS close logging now shows `code=1005 reason=''`.
Stack restarted clean (`scripts/restart-backend.sh`) after removing the mock env; the hung `e329cba6` turn is cleared by the restart.

---

## FIX-20261031-071721

**Created:** 2026-10-31T07:17:21Z
**Status:** Resolved
**Issue:** (1) Live assistant response not rendered after send in resumed sessions (visible only after exit/reopen); (2) assistant created skill + agent type but did not associate the skill to the agent type

### Observed Behavior
1. With session persistence working, sending a message in a resumed session persists the turn (visible after exit/reopen) but the response does NOT appear in the live UI.
2. Asked to create an agent: assistant created the skill and the agent type, but the skill was never associated with the agent type (no binding).

### Expected Behavior
1. Responses render live in resumed sessions, as in fresh sessions.
2. Creating an agent type must (optionally) include skill/SOP associations; at minimum a management tool must exist to bind them, and the assistant must know to use it.

### Analysis
- **Affected components (hypothesis):** `frontend/src/hooks/useChatSession.ts` / `ConversationDialog.tsx` resume-mode WS delivery; backend `app/api/v1/internal/management_tools.py` `create_agent_type`/`update_agent_type` (no skill/SOP binding support in `_build_create`/`_apply_update`), knowledge corpus (`assistant_knowledge.py`), seeder instructions
- **Root cause hypothesis:**
  1. In resume mode the reply event is not delivered/appended to the dialog's message state (WS handler not registered, or session-id mismatch between history-load and live channel).
  2. **Confirmed by code inspection:** the management toolset has NO tool to bind skills/SOPs to an agent type — `_build_create`/`_apply_update` for `agent_types` handle identity/role/model/instruction/IO only. The assistant literally cannot associate the skill.
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests for both defects
- [x] **Fix** — Resume-mode live delivery + agent-type skill/SOP association support
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Test Cases Added/Modified
<!-- Will be updated -->

**Defect 2 / backend (this developer):** `backend/tests/integration/test_fix_20261031_071721_agent_type_bindings.py` (9 tests, TDD — 7 failed before the fix, 9 pass after):
- `test_create_agent_type_creates_skill_bindings` — FAILING-FIRST: `create_agent_type` with `skill_ids`/`sop_ids` previously ignored them; asserts `AgentTypeSkillBinding`/`AgentTypeSopBinding` rows exist with `order=0` conventions.
- `test_create_agent_type_resolves_skills_by_name` — name-resolution parity with the rest of the toolset (tenant-scoped).
- `test_update_agent_type_adds_bindings_additively_and_idempotent` — update ADDS bindings; re-binding an existing pair is an idempotent no-op (no duplicates); existing bindings never removed.
- `test_update_agent_type_unknown_skill_id_is_404_no_partial_write` — unknown skill id → structured 404, zero binding rows written (no partial write).
- `test_update_agent_type_unknown_sop_name_is_404` — unknown SOP name → 404 with clear message.
- `test_parity_map_unchanged_for_agent_type_tools` — parity stays `("agent","create")` / `("agent","update")`.
- `test_create_agent_type_denied_without_permission` — parity gate still enforced through the wrapper (403).
- `test_get_management_tool_schema_includes_binding_fields` — served schemas expose `skill_ids`/`sop_ids` + additive-merge description.
- `test_search_knowledge_returns_association_workflow` — "associate skill with agent type" query returns the workflow rule (mentions `skill_ids`, `create_agent_type`/`update_agent_type`).

**Defect 1 / frontend (this developer):** new `frontend/src/__tests__/ConversationDialog.resumeLiveDelivery.test.tsx` exercising the **real `useChatSession` hook** (only collaborators mocked, mock `WebSocket`) inside `ConversationDialog`, wrapped in `React.StrictMode` to mirror the dev app:

1. `appends a live agent reply to the message list after sending in a resumed session` — resumed session (history renders), send a message, assert optimistic render + WS send, push an agent reply over the same socket, assert it renders live.
2. `keeps the assistant reply visible after a chat_status event was also received` — guards against status events swallowing message delivery.
3. `reconnects after an unexpected WS close mid-turn and recovers the persisted reply via history` — **the failing-first test**: sends in a resumed session, force-closes the socket mid-turn, asserts the client (a) reconnects **with the same session id** and (b) recovers the persisted reply via a history refresh so it renders live without exit/reopen, and the persisted user turn does not duplicate the optimistic message. Failed before the fix (no reconnect, no recovery); passes after.

Regression coverage re-run green: `ConversationDialog.assistantChat.test.tsx`, `ConversationDialog.test.tsx`, `ConversationDialog.intervention.test.tsx`, `useChatSession.test.ts`, `useChatSession.intervention.test.ts`, `AssistantModelConfigGuidance.test.tsx`, `AppShell.assistantSession.test.tsx`, `ConversationDelegationVisibility.test.tsx` (intervention flows, guidance banner, fresh-session live delivery, delegation cycles unchanged).

### Code Changes
<!-- Will be updated by developer -->

**Defect 2 / backend (this developer):**
- `backend/app/api/v1/internal/management_tools.py`:
  - New `_resolve_capability_ids` — resolves skill/SOP id-or-name lists, tenant-scoped; unknown value → structured 404 with actionable message; whole set resolved BEFORE any write (no partial write).
  - New `_bind_agent_type_capabilities` — **ADDITIVE MERGE** semantics: provided skills/SOPs are ADDED to the agent type's binding set; existing bindings are NEVER silently removed (no-delete, non-destructive philosophy); re-binding an existing pair is an idempotent no-op; new bindings use the `order` convention (0-based, appended after the current max).
  - Hooked into `_create_resource` (after flush, before commit) and `_update_resource` (after `_apply_update`) for `agent_types` only.
- `backend/app/services/agents/system_tool_registry.py`: `_enrich_agent_type_binding_schemas()` mutates the registered `create_agent_type`/`update_agent_type` tools in place (stable mcp_hub_ids and parity untouched) — adds `skill_ids`/`sop_ids` array properties to the `data` object and documents the additive/idempotent semantics + "agent without at least one skill/SOP (or role) cannot act" rule in the descriptions.
- `backend/app/services/agents/assistant_knowledge.py`: `agent-type-composition` entry extended with keywords (`associate`, `association`, `link`, `connect`) and the explicit ASSOCIATION WORKFLOW: create skill first → create agent type WITH `skill_ids`/`sop_ids` → or associate afterward via `update_agent_type`; additive/idempotent/404 semantics; un-associated agent types cannot act — always associate or explain why not.
- `backend/app/services/agents/assistant_seeder.py`: management-skill `instructions` digest and `ASSISTANT_SYSTEM_INSTRUCTION` rule 2b updated with the association workflow (seeder diffs instructions → existing seeded rows refreshed on restart, verified live: "updated management skill / updated assistant agent type" for all 26 tenants).

**Defect 1 / frontend (this developer):**

**Corrected root cause:** the conductor's hypotheses (a) "resume mode doesn't register the WS reply handler", (b) "session-id mismatch between history load and live channel", (c) "an effect replaces the message list after the response arrives" were all **disproven** — new tests prove the resumed live-delivery path (WS handler registration, same session id, message append + render) is correct in isolation, including under StrictMode. `POST /conversations/{id}/resume` returns the SAME session id (backend `ConversationSessionManager.resume` reactivates in place).

The real failure mode (from `backend/logs/communication-hub.log`, session `3f73072a-…`, 18:12–18:14): resumed-session turns are long agentic turns (~60–75s, many management-tool calls) and the chat WebSocket **closed mid-turn** on every failing attempt. The reply was generated, but `ws/chat.py` `_run_turn_and_reply` sends it via the captured `websocket` object, so delivery failed with `RuntimeError: Unexpected ASGI message 'websocket.send', after sending 'websocket.close'` — the turn still persisted, hence "only visible after exit/reopen". Fresh sessions rendered fine because their quick replies completed while the socket was still open.

Fixes (`frontend/src/hooks/useChatSession.ts`, `frontend/src/components/agents/ConversationDialog.tsx`):
1. **Auto-reconnect** — `ws.onclose` previously did nothing; now unexpected closes while the dialog is mounted schedule a reconnect with the SAME session id (1.5s delay, max 5 attempts, counter reset on successful open); intentional unmount closes are marked via `intentionalCloseRef` and never reconnect.
2. **In-flight reply recovery** — the hook tracks whether a turn was in flight at disconnect; after reconnecting it bumps `recoveryEpoch`. `ConversationDialog` watches it, re-fetches `POST /conversations/{id}/resume`, and merges persisted turns via `mergeUnseenMessages` (occurrence-counted per `role|content` against rendered + live messages) so the missed reply renders live and nothing is duplicated.
3. **Resume double-POST guard** — resume effect guarded by `resumeRequestedForRef` so StrictMode double-mount fires exactly one resume POST per session; previously the second response could race and re-render stale history over freshly arrived live messages.

**Note for the conductor (outside this defect's frontend scope):** (1) the backend reply send in `ws/chat.py` should route through `ActiveSessionTracker.get_ws(session_id)` instead of the captured connection so a reconnecting client can receive the in-flight reply directly; (2) mid-session the working tree lost uncommitted assistant-model-config code from `ConversationDialog.tsx`/`useChatSession.ts` (concurrent revert ~18:41); it was restored in this change and `npx tsc --noEmit` is clean again.

**Defect 1 / backend follow-up (this developer):** implemented the conductor's note (1) — route ALL reply/turn sends through the active-connection registry.

- `backend/app/api/ws/chat.py`:
  - New `_send_to_live_socket(session_id, fallback_ws, payload)` — resolves the CURRENT live socket from `ActiveSessionTracker.get_ws(session_id)` at send time (reused the existing intervention-routing registry; `get_ws` already existed), falling back to the captured socket when the tracker has no entry (preserves flows that never register); send failures are logged and swallowed — a send to a dead socket must never crash the turn pipeline.
  - `websocket_chat` / `_run_turn_and_reply` / `send_status_event`: ALL sends (`thinking` status, streamed `chat_status` events, agent reply, `title_update`, `guardrail_update`, `chat_error`, generic error fallback, `chat_blocked`) now go through `_send_to_live_socket` instead of the captured `websocket` object.
  - `_handle_intervention_response` / `_handle_intervention_cancel`: intervene_status sends routed through the helper too.
  - `ActiveSessionTracker.unregister(session_id, websocket)` — now identity-checked: the old connection's cleanup only evicts the entry when it still points at ITS OWN socket, so a reconnect's NEW registration for the same session id survives the old handler's teardown (tracker race).
  - Message persistence (`_process_message` → prepare/append turns) is UNCHANGED — only which socket receives the live send. Single-tenant and multi-tenant behaviour unchanged (no tenant-context changes).
- New test `backend/tests/communication_hub/test_fix_20261031_071721_ws_reconnect_reply_routing.py` (4 tests, TDD): reconnect mid-turn → reply delivered to the NEW socket (failed before the fix with the reply never reaching the new socket), no-reconnect unchanged, dead-socket send swallowed, tracker-empty fallback to the captured socket.

### Documentation Updates
<!-- Will be updated as docs are revised -->

### Verification Results

**Defect 1 / backend follow-up (this developer):**
- Failing→passing evidence: `tests/communication_hub/test_fix_20261031_071721_ws_reconnect_reply_routing.py` — pre-fix run: `test_reply_delivered_to_reconnected_socket` FAILED (reply sent to the stale captured socket; the reconnecting client never receives it → `TimeoutError` on the reply event); post-fix: **4 passed**.
- Regression (all pass): full `tests/communication_hub/` sweep **117 passed** (2 pre-existing failures in `test_tenant_header_verification.py` verified identical on the git-stashed baseline tree — unrelated); targeted ws/chat + intervention + tenant-signature + delegation suites (dispatch/delegate/tool-routing/script forwarding, signed-forwarding, oidc binding, assistant tool context, reconnect routing) **67 passed**; tenant sweeps (`test_tenant_isolation_sweep.py`, `test_tenant_signature.py`, `test_tenant_context.py`, `test_tenant_scoping.py`, `test_tenant_oidc_isolation.py`) **162 passed**.
- Syntax/import: `import app.main` clean; `py_compile`-equivalent via pytest collection OK.
- Live restart: `./scripts/restart-backend.sh` — CC (8000), AR (8001), CH (8002), frontend all healthy.

**Defect 2 / backend (this developer):**
- Failing→passing evidence: pre-fix run `7 failed, 2 passed`; post-fix `9 passed` (`tests/integration/test_fix_20261031_071721_agent_type_bindings.py`).
- Targeted suites (all pass): `test_assistant_seeder.py` (7), `test_fix_20261031_035145_assistant_tool_context.py`, `test_assistant_meta_tools.py` (12), `test_management_tool_permission_parity.py`, `test_tool_registry_bridge.py`, `test_tenant_isolation_sweep.py` + `test_system_tool_endpoints.py` + `test_system_tools_tenant_containment.py` (80) — combined runs of related suites: 58 and 103 passed. Pre-existing, unrelated order-dependence in broad `-k "assistant or seeder"` runs and `test_skills_api.py` confirmed identical on the unmodified baseline (git-stashed) tree.
- Syntax check (`py_compile`) on all 4 modified backend files: OK.
- Live restart: `./scripts/restart-backend.sh` all services healthy; seeder logs show "updated management skill 'control-center-management'" / "updated assistant agent type" and completed across 26 tenants (instruction diff refresh works).

**Defect 1 / frontend (this developer):**
- Failing→passing evidence: `ConversationDialog.resumeLiveDelivery.test.tsx` reconnect/recovery test failed pre-fix (`TestingLibraryElementError`/no reconnect: sockets never re-created, reply never rendered); post-fix **3/3 pass**.
- Targeted suites (all pass): `ConversationDialog.resumeLiveDelivery` (3), `AssistantModelConfigGuidance` (2), `ConversationDialog.assistantChat` (6), `ConversationDialog` (7), `ConversationDialog.intervention`, `useChatSession` (12 + 1 skipped), `useChatSession.intervention`, `AppShell.assistantSession` (4), `ConversationDelegationVisibility`, `AppShell.tenantAdmin` (4) — 56+ passed, 0 failed. `npx tsc --noEmit`: clean.
- Full frontend suite: **1781 passed / 1799 total (18 skipped), 0 failed**.
- Extra fix surfaced by verification: `AppShell.tsx` assistant-type resolution hardened against non-array `agentTypes` (`Array.isArray` guard) — `AppShell.tenantAdmin.test.tsx`'s apiClient mock returns `{ data: {} }` for `/agents/types` and previously crashed `(agentTypes ?? []).find is not a function`.
- Tool schema served: in-process registry check confirms `get_management_tool_schema('create_agent_type')`/`('update_agent_type')` expose `skill_ids`/`sop_ids` in `data.properties`, additive-merge description, parity `("agent","create"/"update")` unchanged, stable mcp_hub_ids (…0027/…0028).
- No DB schema changes (existing binding tables reused); no frontend files touched.

---

## FIX-20261031-035145

**Created:** 2026-10-31T03:51:45Z
**Status:** Fixed (live LLM E2E probe outstanding — see Verification Results)
**Issue:** Assistant claims "skill is created" but nothing is created and no error is shown (false-success hallucination — tools never invoked)

### Observed Behavior
User asked the assistant (root tenant) to create a skill. The assistant replied that the skill was created, but no skill was created in any tenant and no error was shown. Evidence for session `860643aa-02f6-41e2-91f5-6692b0af410b` ("Create skill to list Supabase projects", tenant=root, 2026-10-31 03:43): **4 conversation turns, 0 ToolCallRecords**, no `/internal/management-tools/*` hits in `control-center.log`, no entries in `agent-runtime.log` — the `create_skill` tool was never invoked.

### Expected Behavior
The assistant invokes the `create_skill` management tool; the skill actually appears in the tenant's Skills list; on failure the assistant reports the error.

### Analysis
- **Affected components:** CC WS delegation context builder (`app/api/ws/chat.py` `_delegate_conversation_turn_to_agent_runtime` + its tool-context assembly), AR executor tool-context consumption (`app/services/agents/runtime_executor.py` `execute_conversation_turn_from_context` reads `allowed_tools`/`tool_definitions`/`tool_name_map` from the CC-built `agent_context`), `AssistantSeeder` per-tenant tool bindings (`app/services/agents/assistant_seeder.py`)
- **Root cause hypothesis:**
  1. **Primary:** CC's conversational delegation builds an `agent_context` WITHOUT the assistant's management tools (skill→tool bindings not resolved on the WS chat path), so AR runs the deep agent with zero tools and the LLM fabricates success.
  2. **Secondary (confirmed in DB):** per-tenant seeding gap — root tenant's `control-center-management` skill has 36 tool bindings, but 23 other tenants' skills have **0 bindings**; every startup logs `AssistantSeeder: management tool 'create_skill' not seeded yet — binding skipped` because per-tenant `McpTool` rows don't exist when the seeder runs and it never retries/self-seeds.
  3. **Contributing:** the system instruction does not forbid claiming success without a successful tool call.
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Failing tests: delegation agent_context contains the management tools; per-tenant bindings seeded
- [x] **Fix** — Tool context on the conversational delegation path + per-tenant binding self-seed + instruction hardening
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Corrected Root Cause
The conductor's primary hypothesis pointed at the CH WS delegation (`ws/chat.py`), but the actual gap is one hop upstream in **Control Center**:

- CH `ws/chat.py` sends only `agent_type_id`; Agent Runtime's `/internal/conversation/turn` fetches the full `agent_context` from CC's `GET /internal/data/agent-types/{id}/context` (`app/api/v1/internal/agent_data.py::get_agent_context`).
- That context builder resolved tools **only inside `if agent_type.role_id:`**. The assistant `AgentType` is seeded WITHOUT a role (its permissions are its direct `AgentTypeSkillBinding` → management skill), so the assistant's context came back with **empty `allowed_tools` / `tool_definitions` / `tool_name_map`**. AR's `execute_conversation_turn_from_context` consumed that empty context, built zero LangChain tools, and the model — told by its instruction to "report what was created" — hallucinated success. Confirmed: AR executor and tool wrapper code are correct; the empty context was the whole story.
- Secondary gap confirmed as diagnosed: `AssistantSeeder._ensure_skill_bindings` depended on another component having seeded per-tenant `McpTool` rows; global system-tool seeding stamps rows to the ROOT tenant only, so 23 non-root tenants' management skills had 0 bindings (warning logged every startup, no retry).

### Test Cases Added/Modified
**New — `backend/tests/communication_hub/test_fix_20261031_035145_assistant_tool_context.py`** (TDD: written first, all 3 failed for the right reason, then made to pass):
- `test_t1_assistant_context_includes_management_tool_definitions` — builds the agent context exactly as the conversational delegation path does (CC `get_agent_context` for the role-less assistant) and asserts `allowed_tools` contains `system____create_skill` and `tool_definitions` carries the `create_skill` function schema.
- `test_t2_seeder_self_seeds_per_tenant_management_bindings` — fresh non-root tenant with zero management `McpTool` rows → after `AssistantSeeder.run`: per-tenant rows exist for ALL 36 management tools (`system____<name>`), each bound to the tenant's `control-center-management` skill (`create_skill` sampled explicitly).
- `test_t2_seeding_is_idempotent_across_restarts` — double seed → exactly 36 rows / 36 bindings, no duplicates.

### Code Changes
- `backend/app/api/v1/internal/agent_data.py` (`get_agent_context`): new `else:` branch for **role-less agent types** — resolves skills from the agent type's DIRECT `AgentTypeSkillBinding` → `SkillToolBinding` → `McpTool` (tenant-scoped, same canonical `system____<name>` resolution + SystemToolRegistry schema injection the role path uses); decision-tool virtual-binding resolution preserved unchanged for role'd agents. No behavioural change for any agent type WITH a role.
- `backend/app/services/agents/assistant_seeder.py`:
  - `_ensure_skill_bindings` now self-seeds: calls the new `_ensure_management_tool_rows`, which idempotently upserts the tenant's own `McpTool` rows (name `system____<bare>`, original_name, description, input_schema from `SystemToolRegistry.get_mcp_hub_entries()`) plus an on-demand per-tenant mirror of the reserved `system` MCP server. Row ids are deterministic uuid5 of (`mcp_hub_id`, tenant_id) — the raw `mcp_hub_id` stays reserved for the ROOT tenant's row (PK). The old "not seeded yet — binding skipped" warning is now an error path only.
  - `ASSISTANT_SYSTEM_INSTRUCTION`: new rule 6 — NEVER claim a resource was created/updated/listed/read unless the corresponding management tool call actually returned success (report the real id/name from the tool result); if the tool is unavailable or errors, say so plainly and stop. The existing update branch already refreshes `system_instruction` on restart — confirmed live (root assistant row contains the new rule).
- No DB schema changes (data-only rows; no migration required).

### Verification Results
- New tests: **3 passed**.
- Regression: `tests/unit/test_assistant_seeder.py` (7) + `test_fix_20261031_021855_delegate_tenant_headers` + `test_conversation_dispatch_tenant_forwarding` + `test_ws_chat_model_not_configured` — **31 passed**. `test_decision_tools_in_conversation`, `test_decision_tool_full_journey`, `test_agent_session_lifecycle`, `test_tenant_isolation_sweep`, `test_tenant_scoping`, `test_agent_runtime_executor`, `test_query_result_tool` — **203 passed**.
- **Pre-existing (NOT caused by this fix):** `tests/integration/test_tool_naming_refactor.py` 3 failures inside `seed_system_tools` under the SQLite test engine — `postgresql.UUID` DDL gets NUMERIC affinity on SQLite, so all-digit hex UUIDs (system tool ids `00000000-…-0000000000NN`) read back as INTEGER and crash the `Uuid` result processor. Verified failing identically before any change from this fix. Production PostgreSQL is unaffected; the new tests avoid the trap with uuid5 row ids.
- Live restart (`./scripts/restart-backend.sh`): all services healthy; current-startup log shows **zero** "not seeded yet" warnings and 828 `provisioned management tool` rows (23 non-root tenants × 36 + root extras).
- DB re-check after restart: **0 tenants with a 0-binding `control-center-management` skill**; all 24 tenants have exactly 36 bindings; root assistant `system_instruction` contains the new anti-hallucination rule.
- **Live LLM turn NOT performed:** the real-backend WS assistant turn needs (a) an authenticated root-tenant session — no password account owns/logs into the root tenant headlessly (super-admin tokens are rejected at WS tenant binding) — and (b) a per-tenant model binding unreachable from test accounts. The delegation contract (context builder → AR consumption) is covered end-to-end by T1, which exercises the exact `get_agent_context` payload AR consumes. An interactive browser E2E (Playwright chat flow against the configured root assistant) remains the outstanding verification.

### Documentation Updates
<!-- Will be updated as docs are revised -->

### Verification Results
<!-- Will be updated after verification -->

---

## FIX-20261031-021855

**Created:** 2026-10-31T02:18:55Z
**Status:** In Progress
**Issue:** Chatbot returns an error on the first message (conversation fails before the model is reached)

### Observed Behavior
Sending the first message to the Control Center Assistant returns an error. Agent Runtime logs show the conversation session failing on its callback into Control Center:

```
app.agent_runtime.data_client.ControlCenterDataError: CC data API PATCH
http://localhost:8000/api/v1/internal/data/sessions/a7e00148-4ce3-41a2-b640-a8ad73cf9fa9/status
returned 401: {"detail":"Signed tenant context headers are required on internal
data-plane endpoints"}
```

Additionally, every Control Center startup since 2026-10-30 logs a `NameError`:

```
NameError: name 'renew_cc_service_certificate_if_needed' is not defined
Failed to ensure Control Center service certificate; internal calls to
Communication Hub will fail.
```

### Expected Behavior
- A signed-in user can converse with the assistant; the first message processes end-to-end (WS → CC → AR deep agent → AR callback into CC → model → management tool calls → reply) under multi-tenancy.
- CC startup ensures/renews its service certificate without errors.

### Analysis
- **Affected components:** `backend/app/api/ws/chat.py` (CC→AR delegation), Agent Runtime data-client callback (`app/agent_runtime/data_client.py`), `backend/app/main.py` (cert renewal at startup, line ~718)
- **Root cause hypothesis:**
  1. The WS conversation delegation CC→AR does not carry the CC-signed `X-Internal-Tenant-*` header set, so AR has no signature to bind/forward on its callback into CC's internal data API (fail-closed 401 with multi-tenancy on). The WS path mints per-call signatures for its own loopback calls (`_signed_tenant_forwarding`) but evidently not for the delegation hop.
  2. `renew_cc_service_certificate_if_needed` is referenced in `app/main.py` but not defined/imported (regression introduced by this change's edits).
- **Documentation impact:** `tech-spec.md`, `test-plan.md`, this fix log

### Fix Tasks
- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Implementation Details
<!-- Will be filled in as fix progresses -->

### Test Cases Added/Modified

**2026-10-31 — Tester (FIX-20261031-021855)**

#### Test 2 — Startup cert renewal NameError (`Failing` — reproduces the defect)

- File: `backend/tests/core/test_fix_20261031_021855_startup_cert_renewal.py`
- `TestStartupCertRenewalNameResolves::test_renew_cc_service_certificate_if_needed_resolves_in_main`
- `TestStartupCertRenewalNameResolves::test_ensure_cc_service_certificate_actually_renews`

Status: **2 failed** — both fail for the right reason. The behavioral test surfaces the exact live traceback:

```
File "/Users/minglijiang/source/parthenon/backend/app/main.py", line 718, in _ensure_cc_service_certificate
    renewed = await renew_cc_service_certificate_if_needed()
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
NameError: name 'renew_cc_service_certificate_if_needed' is not defined
ERROR app.main:main.py:722 Failed to ensure Control Center service certificate;
internal calls to Communication Hub will fail.
```

The name is neither defined nor imported in `app.main` (only `start_daily_renewal_task` is imported at L715); the broad `except` at L721 swallows the NameError, so the renewal mock is never awaited.

#### Test 1 — Conversation callback 401 (`Created` — currently PASSING; defect NOT reproduced in the working tree)

- File: `backend/tests/communication_hub/test_fix_20261031_021855_delegate_tenant_headers.py`
- `TestDelegateHopCarriesSignedTenantContext::test_delegate_hop_to_ar_carries_signed_tenant_set` (CC→AR hop contract — the hypothesized failing reproduction)
- `TestDelegateHopCarriesSignedTenantContext::test_streaming_delegate_hop_carries_signed_tenant_set` (streaming variant used by the chat UI)
- `TestDelegateHopCarriesSignedTenantContext::test_delegate_hop_single_tenant_mode_stays_headerless`
- `TestARStatusPatchCallbackSucceeds::test_status_patch_succeeds_with_bound_forwarded_set` (AR-side PATCH `/internal/data/sessions/{id}/status` with the verified set)
- `TestARStatusPatchCallbackSucceeds::test_headerless_status_patch_fails_clear_with_live_401`

Status: **5 passed**. The delegate hop `_delegate_conversation_turn_to_agent_runtime` (`backend/app/api/ws/chat.py` L681-683) already reads `forward_tenant_headers()` and attaches the signed set on both the plain and streaming POST — this forwarding (plus the pre-existing suite `tests/communication_hub/test_conversation_dispatch_tenant_forwarding.py`, 25 passed) landed in commit `8b13a25` (2026-10-29), i.e. BEFORE this fix was reported (2026-10-31).

**Implication / follow-up for the developer:** the in-process CC→AR→CC contract is sound at HEAD, so the live 401 is NOT explained by the missing header set on the delegate hop. Most likely causes to investigate next: (a) stale running services predating `8b13a25`, or (b) the WS connect-time tenant binding (`websocket_chat` binds the context only when `claims.get("tenant")` is set — `OIDCClient.validate_token` returns decoded claims verbatim and does NOT inject a `tenant` claim, so OIDC-token connections bind no context and every hop goes out headerless). Do NOT close defect 1 on the strength of these passing tests alone; verify against the live two-service flow.

### Code Changes

**2026-10-31 — Developer (FIX-20261031-021855)**

#### Defect 1 — CC startup cert-renewal NameError (FIXED)

- `backend/app/main.py`
  - Added module-level `from app.core.cc_service_cert_renewal import renew_cc_service_certificate_if_needed` (the function exists in `app/core/cc_service_cert_renewal.py:104` — it was simply never imported, not renamed).
  - `_ensure_cc_service_certificate` now calls the renewal through the source module (`cc_service_cert_renewal.renew_cc_service_certificate_if_needed()` / `.start_daily_renewal_task()`), so call-time resolution honours patching and both names always resolve. The broad `except Exception` + `logger.exception` was retained deliberately (environmental CA/DB failures must not crash startup), but the programming error it was hiding is gone.

#### Defect 2 — first-message 401: OIDC WS connections bound NO tenant context (FIXED — tester's hypothesis (b) CONFIRMED, hypothesis (a) RULED OUT)

Root cause (corrected): the CC→AR delegate hop already carries the signed tenant header set (commit `8b13a25`; contract tests pass — hypothesis (a) ruled out). The real gap is one hop EARLIER: `websocket_chat` bound the tenant context only when `claims.get("tenant")` was truthy, and `OIDCClient.validate_token` returns claims VERBATIM — no `tenant` claim is injected on the direct WS validation path (REST's auth middleware injects it, but WS bypasses that middleware). So an OIDC user's connection ran context-less → `_signed_tenant_forwarding` yielded headerless → AR's `PATCH /internal/data/sessions/{id}/status` 401'd fail-closed. Platform-account JWTs (native `tenant` claim) were unaffected.

- `backend/app/api/ws/chat.py`
  - New `_resolve_oidc_tenant_slug(db, sub)`: mirrors the REST login-context resolution used by `/auth/tenant-memberships` — `PlatformUser` by verified `sub` (identity-plane, `execute_unscoped`) → ACTIVE membership in an ACTIVE tenant, default tenant first → slug. No new resolution mechanism invented.
  - New `_bind_connection_tenant_context(claims)`: platform-token `tenant` slug path unchanged; when claims carry no slug and multi-tenancy is ON, resolves via `_resolve_oidc_tenant_slug` and binds with `TenantResolutionService.resolve_slug` + `set_current_tenant_context` exactly like the old slug branch; multi-tenancy OFF → no binding (root tenant, headerless, unchanged); unresolvable → returns a fail-closed rejection reason, connection closed 4003 (no headerless pipeline).
  - `websocket_chat` now delegates to `_bind_connection_tenant_context` and closes 4003 with the clear reason on failure.

#### Test-driven evidence (defect 2)

- New file `backend/tests/communication_hub/test_fix_20261031_021855_oidc_ws_tenant_binding.py` (5 tests): OIDC claims without `tenant` → membership resolution binds context + delegation hop mints a VERIFIED signed set; no membership → fail-closed rejection; multi-tenancy off → unbound/headerless unchanged; platform token native-claim path unchanged (membership fallback must not run).
- Confirmed **5 failed at HEAD** (stash of the two source files), **5 passed after the fix**.

### Documentation Updates
<!-- Will be updated as docs are revised -->

### Verification Results

**2026-10-31 — Developer (FIX-20261031-021855)**

- Fix tests: `tests/core/test_fix_20261031_021855_startup_cert_renewal.py` 2 failed → **2 passed**; `tests/communication_hub/test_fix_20261031_021855_oidc_ws_tenant_binding.py` 5 failed at HEAD → **5 passed**; `tests/communication_hub/test_fix_20261031_021855_delegate_tenant_headers.py` **5 passed** (contract untouched).
- Regression sweep (tenant signature / WS / delegation / AR header verification / internal fail-closed / tenant-settings workflow): **231 passed**, 3 failed — the 3 (`test_tenant_header_verification.py::TestHeaderlessTraffic::test_no_tenant_headers_pass_through_unchanged`, `::TestValidSignedContext::test_valid_headers_bind_context`, `test_multitenant_auth_chain.py::TestInternalEndpoints::test_stale_timestamp_401`) were verified to **fail identically at HEAD** (pre-existing, unrelated to this fix).
- Import check: `import app.main; import app.communication_hub.main; import app.agent_runtime.main` → OK.
- Live restart (`./scripts/restart-backend.sh`): all services healthy; `backend/logs/control-center.log` at 13:39:14 shows the NameError GONE — "Control Center service certificate is present and valid" then the daily renewal check ran ("no renewal needed").
- Live WS probe NOT performed: the Keycloak realm client has direct-access grants disabled, so obtaining an OIDC user token headlessly (auth-code flow) was impractical; the OIDC resolution → context binding → signed delegation chain is covered end-to-end by the in-process contract tests above.

---

## FIX-20261101-090438 — Control Center (cc) MCP entity is system-managed and sessionless

**Date:** 2026-11-01 · **Area:** MCP Hub (backend + frontend) · **Status:** FIXED

### Summary / User Intent

The `cc` MCP entity must be system-managed like the generic System entity: it cannot be edited
(no update/delete/sync/OAuth-config by ANYONE — including `integration::control_center:manage`
holders; the seeder is the only writer, idempotent), and it needs NO sessions (MCP sessions don't
apply — access flows through role/skill grants only). Tool GRANTS onto cc tools remain allowed for
`manage` holders (FIX-014511 semantics preserved).

### Root Cause

FIX-014511 modelled cc-entity mutations as a *permission* question (manage gate), which implied
`manage` holders could rewrite the entity — but the cc entity is platform provisioned (per-tenant
seeder), so any runtime mutation would desync it from `SystemToolRegistry` and the skill bindings.
The frontend likewise exposed edit/delete/sync/session controls for the cc row.

### Semantics Chosen

- **System-managed marking (no new DB column):** the existing convention marks the System/Decision
  entities by reserved slug (`create_mcp_server` rejects `system`/`decision`/`cc`). New constant
  `SYSTEM_MANAGED_SERVER_SLUGS = {system, decision, cc}` in `app/db/models/mcp_hub.py`;
  `McpServerRead.is_system_managed` (bool, derived via model validator from the slug) is exposed in
  every read response — no migration needed.
- **Immutability:** `_reject_cc_mutation(server)` raises structured
  `403 {"code": "system_managed_integration", "detail": "The Control Center integration is
  system-managed and cannot be modified."}` and is checked BEFORE the FIX-014511 manage gate
  (immutability is unconditional, not a permission question) on: server update, delete, sync,
  OAuth authorize. Role↔tool grants on cc tools are NOT touched (still governed solely by the
  FIX-014511 read/manage gate).
- **Sessionless:** session create/update/delete/refresh-token on the cc entity raise the same
  structured 403 with "Sessions are not supported for the Control Center integration — access
  flows through role and skill grants." Session LIST remains allowed (harmless; returns existing
  rows — normally empty).
- **Seeder:** `_ensure_management_tool_rows` now refreshes drifted cc-server fields (name,
  description, base_url, status) on every run — idempotent; the slug (the flag carrier) can never
  drift because the router reserves it.

### Code Changes

- `backend/app/db/models/mcp_hub.py` — `SYSTEM_MANAGED_SERVER_SLUGS` constant (+ doc comment).
- `backend/app/schemas/mcp_hub.py` — `McpServerRead.is_system_managed` + slug-derived validator.
- `backend/app/api/v1/mcp_hub.py` — `_reject_cc_mutation` guard wired into update/delete/sync/
  oauth-authorize (entity) and session create/update/delete/refresh-token (sessions=True variant),
  always ahead of `_gate_cc_server(mutation=True)`.
- `backend/app/services/agents/assistant_seeder.py` — idempotent cc-server drift refresh
  (seeder = only writer).
- `frontend/src/types/index.ts` — `McpServer.is_system_managed?: boolean`.
- `frontend/src/pages/mcp/McpHubPage.tsx` — cc row (flag with slug fallback) shows a
  "System-managed" chip (i18n `mcp.controlCenter.systemManaged`); edit/delete/sessions hidden,
  sync disabled; grant-related controls for manage holders unchanged. Non-cc rows untouched.
- `frontend/src/i18n/locales/en.json` — `mcp.controlCenter.systemManaged`.
- Tests: `backend/tests/unit/test_cc_integration_permission.py` (updated 2 FIX-014511 expectations
  to the new immutable semantics + 12 new tests), `frontend/src/__tests__/McpHubPage.test.tsx`
  (cc gating block updated: system-managed assertions, slug-fallback and API-flag tests; the
  403-surfacing test now exercises the regular server row since the cc row has no delete action).

### Test-driven Evidence

Failing first (`TestCcMutations::test_update_cc_with_manage_rejected_system_managed` et al.):
10 failed / 7 passed at HEAD-minus-fix → after the fix **29 passed**
(`pytest tests/unit/test_cc_integration_permission.py`). Frontend `McpHubPage.test.tsx`:
19 passed after implementation (new cc tests failed before the page change).

### Verification Results

- `test_cc_integration_permission.py` **29 passed** (includes FIX-014511 suite, updated).
- Regression: `test_resource_type_manifest.py` + `test_namespace_permission_evaluation.py` +
  `test_tenant_isolation_sweep.py` + `test_cc_integration_permission.py` = **117 passed**.
- `test_mcp_hub.py`, `test_cc_naming.py`, `test_cc_seeder_migration.py`,
  `test_cc_tool_registry_bridge.py`, `test_management_mcp_tools.py`, `test_assistant_seeder.py`,
  `test_namespace_permission_evaluation.py` combined = 63 passed, 3 failed — the 3
  (`test_assistant_seeder.py::test_seeder_marks_assistant_as_system_conversational`,
  `::test_seeder_upgrades_existing_non_system_agent_type`, `::test_management_skill_is_system`)
  fail identically WITHOUT this fix when run after `test_cc_seeder_migration.py` in the same
  process (pre-existing shared-DB ordering pollution: multi-tenant `MANAGEMENT_SKILL_NAME` rows
  break `scalar_one`). Each passes in isolation (7 passed).
- Frontend: `npx tsc --noEmit` clean; full vitest 1784 passed / 8 failed — the 8
  (`AppShell.test.tsx` sidebar-entry, 7 × `DecisionToolForm.test.tsx`) are in files untouched by
  this fix and pass in isolation (AppShell 38/38 verified) — full-run parallel flakiness, not a
  regression.

### Documentation Updates

- `tech-spec.md` §10 — cc entity lifecycle (system-managed + sessionless).
- `test-plan.md` — new FIX-20261101-090438 test section.

---

---

## FIX-20261101-223511

**Created:** 2026-11-01T22:35:11Z
**Status:** Complete
**Issue:** Skill↔tool binding visibility + zero-binding guard + canonical confirmation preview format + expandable approval card

### Problem
1. The Skills UI showed only a numeric tool-count chip — no tool names, no owning server, and NO indication when a skill had zero bindings (invisible failure mode).
2. The management toolset allowed creating a skill with no tools bound with no signal to the assistant — a skill that cannot invoke anything was created silently.
3. The assistant improvised confirmation preview layouts (prose, bullets, varying tables) — no canonical contract.
4. The approval card (520px inline) had no way to view large preview tables comfortably.

### Feature 1 — Skill↔tool binding visibility
- **Management toolset** (`backend/app/api/v1/internal/management_tools.py`): new
  `_attach_skill_tool_bindings` attaches `tool_bindings` (`tool_id`, `name`, `original_name`,
  `server_slug`, `server_name`; virtual-tool bindings degrade to the tool id) to every skill
  record in `list_skills` / `get_skill` / `create_skill` / `update_skill` results (one joined
  query per batch, `SkillToolBinding ⟕ McpTool ⟕ McpServer`).
- **REST API**: `SkillRead.tool_bindings` (`backend/app/schemas/skills.py`) — the
  `populate_tool_ids` validator now builds a detached SimpleNamespace snapshot (setting dicts
  on the ORM's instrumented `tool_bindings` collection raises
  `AttributeError: 'dict' object has no attribute '_sa_instance_state'` — do NOT mutate the ORM
  object in a `mode="before"` validator) with `SkillToolBindingRead`
  (name/original_name/server_slug/server_name). `_SKILL_LOAD_OPTIONS` extended with
  `selectinload(McpTool.server)`.
- **Frontend** (`frontend/src/pages/skills/SkillListPage.tsx`): the Tools column now renders
  one chip per bound tool (original tool name, tooltip = `Server (slug) — canonical____name`);
  zero bindings render an explicit muted italic "No tools bound" chip
  (`skills.noToolsBound`). Types: `SkillToolBindingInfo` on `Skill.tool_bindings?`.

### Feature 2 — Zero-binding guard (assistant self-correction)
- `create_skill` returns `{"record": ..., "warnings": ["This skill has no tools bound — it
  cannot invoke anything. Bind tools via update_skill tool_ids/tool_names …"]}` when the
  created skill has zero bindings; `update_skill` warns when the update TOUCHED
  `tool_ids`/`tool_names` and bindings are still zero (additive semantics can't otherwise reach
  zero). Non-fatal warning, never an error (tool-less skills are technically allowed).
- Knowledge entry `skill-tool-binding` extended with the ZERO-BINDING GUARD rule (see the
  warning → discover the right tool via `get_mcp_server` → bind immediately → tell the user);
  seeder instructions 2f updated identically.

### Feature 3 — Canonical confirmation preview format
- New knowledge corpus entry `confirmation-preview-format`
  (`backend/app/services/agents/assistant_knowledge.py`): EVERY create/update confirmation
  uses EXACTLY `**<Operation> <Resource Type>: <Name>**` followed by ONE `| Field | Value |`
  markdown table (updates list only changed fields, old → new; agent-type creation MUST include
  model/identity/role/skills/grants rows). Never improvise other layouts.
- `confirm-before-write` entry references the canonical contract; seeder instructions 2e +
  `MANAGEMENT_SKILL_INSTRUCTIONS` updated (digest-compare re-seeds on next run).

### Feature 4 — Expandable/maximizable approval card
- `frontend/src/components/conversations/InlineInterventionDialog.tsx`: Expand toggle
  (OpenInFull icon, header) opens the SAME preview in a 90vw × 80vh MUI Dialog
  (`conversations.sessions.intervention.previewTitle`) with the table forced full-width
  (`min-width: 480px`) through the SAME `ContentRenderer`; Approve/Deny available in BOTH the
  inline card and the expanded dialog, wired to the SAME handlers (state stays in sync;
  approve→resume round-trip and streaming-blocked states untouched). Inline preview now wraps
  in `overflowX: auto` so unexpanded tables scroll horizontally. Collapse via title-bar icon,
  footer button, or backdrop. i18n: `expand` / `collapse` / `previewTitle`.

### Tests (failing-first → passing)
- `backend/tests/unit/test_fix_20261101_223511_skill_bindings_visibility.py` (8 tests): failed
  on first run (no `warnings` field, no `tool_bindings`, no `confirmation-preview-format`
  entry) → 8/8 after implementation. Covers: create without tools warns (record still
  returned); create with tools no warning; update touching tools at zero bindings warns;
  update adding tools no warning; get/list skill `tool_bindings` (name + server slug/name);
  `SkillRead.tool_bindings` schema; knowledge retrieval for "confirmation preview format" and
  "how to format the approval table".
- Frontend: `SkillsToolBindingsVisibility.test.tsx` (3 tests — chips for bound tools, tooltip
  carries server + canonical name, muted "No tools bound") and
  `InlineInterventionDialog.expand.test.tsx` (6 tests — expand control, expanded dialog shows
  full-width table, approve/deny from the expanded dialog hit the same handlers, collapse
  keeps inline card usable, inline round-trip untouched). Prior
  `InlineInterventionDialog.test.tsx` (20 tests) still green.
- Regression: management toolset/parity/cc-naming/000319/071721/131030/meta-tools suites
  **97 passed**; 133253 confirmation suite **10 passed**; skills regression + skill system
  tools + seeder migration + inherent skills **32 passed / 24 skipped**; communication_hub
  suite **171 passed / 2 failed** — the 2 (`test_tenant_header_verification.py`) fail
  identically on a clean HEAD worktree (pre-existing, unrelated). Full frontend vitest
  **1813 passed / 0 failed / 18 skipped**; `tsc --noEmit` **0 errors**.

### Live verification (LLM mock scripted mode, real Vite-proxied WS)
`scripts/fix-20261101-223511-live.cjs` + `tmp/fix-223511-scripted.json`
(AR restarted with `LLM_MOCK_MODE=scripted`). Result `LIVE-VERIFICATION-PASSED`:
intervene_request received with the EXACT canonical preview
(`**Create Skill: confirm-preview-live-223511**` + `| Field | Value |` table with
Operation/Resource Type/Name/Description/Tools rows); approve→resume executed the REAL
`create_skill`; the tool result carried the zero-binding warning and the assistant's final
reply acknowledges it; the REST `/skills` list exposes `tool_bindings` on every skill and the
created skill has `[]`. NOTE: scripted tool_calls must use the SANITIZED bound names the model
sees (`cc__invoke_management_tool`, 2 underscores) — the registry canonical `cc____` form is
rejected by the deep agent and loops to the iteration guard. Expanded-dialog rendering at full
width is DOM-verified by the Vitest expand tests (table present inside
`role="dialog"`, all rows rendered); headless visual screenshot not taken.

### Docs
- `tech-spec.md` §13 — binding visibility + zero-binding guard + canonical preview contract +
  expandable approval card.
- `test-plan.md` — FIX-20261101-223511 test section.
- `implementation-plan.md` — Phase 16.
