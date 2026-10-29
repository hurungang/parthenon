# Implementation Plan: Software 3.0 Agent Framework — Workflow Compilation

**Related:** [prd.md](prd.md) · [spec-change.md](spec-change.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md) · [tech-spec.md](tech-spec.md)

## Overview

This plan implements the Software 3.0 workflow-compilation capability: agents' recurring workflows are compiled into verified deterministic bridge scripts that execute in Agent Runtime without an LLM. **There are no execution modes**: script-first execution is automatic whenever a verified serving script exists, with unconditional LLM fallback on any automation failure, session-bound script identity, an MCP-only script boundary, and a bounded self-improvement repair loop. **Adjustment (agent-owned scripts):** scripts are functions owned by their agent type — the standalone Scripts admin module is deleted and governance lives in the Scripts tab of the Agent Type detail dialog (A1–A4); the standardized invocation contract always passes session identity context to script execution (A5/N9); and implementation-plan steps expose links to their backing script versions (E4a). Work is sequenced so that the Control Center–owned registry foundation lands first, Agent Runtime compilation/execution components follow, and governance, cost tracking, and the dialog-based frontend complete the capability — all within the top-priority rules (3 segregated services; scripts/agents run only in Agent Runtime; only Control Center touches the DB; scripts never hold credentials/tokens).

## Task Checklist

### Phase 1 — Schema & Registry Foundation (Control Center)
- [x] 1.1 — New DB models: script_registry.py (ScriptDefinition, ScriptVersion, VerificationRun, FallbackEvent)
- [x] 1.2 — New DB models: script_execution.py (ScriptExecutionRecord; ExecutionModeConfiguration dropped per data-model.md §1.7/§3)
- [x] 1.3 — Extend agents.py relationships & model exports
- [x] 1.4 — Alembic migration (autogenerate + review + apply), including the follow-up drop migration
- [x] 1.5 — Script Registry service in Control Center (CRUD, lifecycle, lineage, health; mode CRUD stripped)
- [x] 1.6 — Add RepairAttempt model + `repaired_from` lineage on ScriptVersion (script_registry.py) + exports
- [x] 1.7 — Follow-up Alembic migration dropping ExecutionModeConfiguration (and mode columns), applied per AGENTS.md

### Phase 2 — Script Compiler & Runner (Agent Runtime)
- [x] 2.1 — Declarative step-graph schema (Pydantic v2)
- [x] 2.2 — Script Compiler
- [x] 2.3 — Script Runner
- [x] 2.4 — Model-backed step invocation (Semantic Bridge / System One decision)
- [x] 2.5 — Execution-mode resolver — resolver removed; mode_resolver.py and its tests deleted
- [x] 2.6 — Delete mode_resolver.py + its tests; strip mode routing from dispatch (script-first becomes automatic)
- [x] 2.7 — Plan-time compilability analysis in compiler + plan integration (scriptable vs model-backed marks; conversational/interactive never compiled)
- [x] 2.8 — Session-binding enforcement in runner (identity parity via the same mTLS/CH path as agent tool calls)
- [x] 2.9 — Verify standardized invocation contract (A5/N9): runner requires session identity context — verified: `runner.py` raises a typed `ExecutionError` when `session_id`/`agent_type_id` are missing; `backend/tests/test_script_runner.py` covers the anonymous-context rejection — no gaps found
- [x] 2.10 — Plan-step script links (E4a): `link_plan_steps_to_version` in the CC registry service stamps `script_definition_id`/`script_version_id` onto plan steps when a version is compiled from a plan; `PlanStepRead` exposes the reference
- [x] 2.11 — Execution logs for script runs: the runner ships best-effort execution log entries via an injected log shipper (backed by the CC data client `log_execution_event` in `dispatch.py`) for run start (version, step count), each step completion (name/kind, truncated outcome brief — no full payloads), model-backed steps (script↔LLM segment visibility), completion, and failure; dispatch adds a fallback entry on script→LLM handoff — DONE: `runner.py` (`log_shipper` param, `_ship_log`, `_brief` truncation), `dispatch.py` (`_script_log_shipper`, `_ship_fallback_log`); covered by `test_script_runner.py` log-shipping tests
- [x] 2.12 — Computed-data transform ops: `count`, `pluck`, `merge`, `sum`, `first`, `last` added to `TransformOp` (`schemas.py`) + `_run_transform_step` (`runner.py`) so scripts derive data for subsequent steps without a model — covered by `test_script_runner.py` transform tests

### Phase 3 — Verification & Promotion
- [x] 3.1 — Verification Engine (shadow-run + comparison)
- [x] 3.2 — Verification evidence persistence via CC registry APIs
- [x] 3.3 — Promotion / rejection lifecycle transitions

### Phase 4 — Fallback & Repair Loop
- [x] 4.1 — Fallback Controller — mode branching removed; fallback is unconditional
- [x] 4.2 — Fallback event recording & script health degradation
- [x] 4.3 — Repair loop (LLM-produced candidate re-verification)
- [x] 4.4 — Self-improvement repair loop: defect diagnosis → repaired candidate (`repaired_from` lineage + RepairAttempt records) → re-verify → bounded retry within guardrails
- [x] 4.5 — Script-First Dispatcher simplification: unconditional fallback + repair-retry orchestration in dispatch.py/fallback.py

### Phase 5 — APIs, Governance & Cost Tracking (Control Center)
- [x] 5.1 — Registry REST API (CRUD, versioning, lifecycle transitions)
- [x] 5.2 — Internal CC↔AR endpoints (serving-version lookup, candidate/evidence submission; mode endpoints removed)
- [x] 5.3 — Script provenance tagging in Communication Hub
- [x] 5.4 — Audit & cost reporting endpoints (mode stripped from audit payloads; repair-attempt data included)
- [x] 5.5 — Permission resource types & manifest registration
- [x] 5.6 — Strip mode APIs from scripts.py + internal scripts API; add RepairAttempt listings (`GET /scripts/{id}/repairs`, `GET /internal/scripts/repairs`)

### Phase 6 — Frontend (agent-owned scripts)
- [x] 6.1 — Execution-mode selector on Agent Type UI — selector removed entirely
- [x] 6.2 — Delete standalone Scripts module — DONE: `frontend/src/pages/scripts/` deleted, `/admin/scripts` route and `nav.scripts` entry removed, `script-registry-page.test.tsx` deleted, `admin.scripts.*` keys migrated to the `agents.scripts.*` namespace in `en.json`
- [x] 6.3 — Add Scripts tab to the Agent Type detail dialog — DONE: new `frontend/src/components/agents/AgentScriptsTab.tsx` mounted at tab index 4 of `AgentTypeDetailsDialog.tsx`; version history with `repaired_from` lineage badges, lifecycle/health chips, description, promote (target select) / retire actions, verifications/fallbacks/repairs; `useScripts.ts` reused; i18n under `agents.scripts.*`; `t()` everywhere
- [ ] 6.4 — Script health & cost dashboard cards
- [x] 6.5 — Wire plan UI script links (E4a) — DONE: `AgentPlanContent.tsx` renders a script link on steps carrying `script_version_id`; the link switches the Agent Type detail dialog to the Scripts tab (new optional `onOpenScript` prop)
- [x] 6.6 — Markdown rendering for session results: shared `MarkdownRenderer.tsx` (react-markdown + remark-gfm; strings render as markdown, JSON pretty-printed) used by `ResultRepositoryPage`, `OutputTypeResultTab`, and `ContentRenderer`; script-path string results flow to the session output as raw text (the CC result endpoint extracts `output_data["result"]` as `result_content`) — covered by `MarkdownRenderer.test.tsx`

### Phase 7 — Tests & Observability
- [x] 7.1 — Backend unit tests (compiler, runner, verification, fallback; mode-dependent cases removed)
- [x] 7.2 — API tests (registry CRUD, internal endpoints, cert access rules; mode-endpoint tests removed)
- [x] 7.3 — OTEL instrumentation (mode_resolver spans dropped; repair-loop/compilability spans added)
- [x] 7.4 — E2E happy-path test (compile → verify → compiled run → fallback)
- [ ] 7.5 — Master docs update
- [x] 7.6 — MCP-only boundary enforcement test (scripts limited to MCP tool calls + local data processing)

## Phase 1 — Schema & Registry Foundation (Control Center)

### 1.1 — New DB models: `backend/app/db/models/script_registry.py`
Create SQLAlchemy 2 (async, declarative, typed) models `ScriptDefinition`, `ScriptVersion`, `VerificationRun`, `FallbackEvent` exactly as specified in data-model.md §1.1–1.3, §1.5: lifecycle status enums (`draft/verified/compiled/retired`), Python Enums (strong typing), lineage FKs to AgentType/AgentPlan, health status, parent-version link, immutable versions.

**Done when:** models import cleanly; `ScriptDefinition` ↔ `ScriptVersion` ↔ `VerificationRun`/`FallbackEvent` relationships resolve; no credential/token-shaped fields exist (SEC3); file follows the one-domain-per-file pattern.

### 1.2 — New DB models: `backend/app/db/models/script_execution.py` ⚠️ NEEDS REWORK
Create `ScriptExecutionRecord` (outcome, duration, tools invoked, model-backed steps, session reference, identity-parity evidence, tokens-saved estimate) per data-model.md §1.4. The `ExecutionModeConfiguration` model (`llm` / `compiled-with-fallback` / `compiled-only` per agent-type/workflow pair) **must be removed** — there is no execution-mode configuration (data-model.md §1.7/§3).

**Done when (revised):** `ScriptExecutionRecord` resolves relationships to `ConversationSession`/`AgentJob` without altering those classes; enums are typed; **`ExecutionModeConfiguration` is dropped via task 1.7.**

### 1.3 — Extend `backend/app/db/models/agents.py` and exports
Add one-to-many relationships on `AgentType` → ScriptDefinitions and `AgentPlan` → script lineage (backward references only, no structural change). Export all new models from `backend/app/db/models/__init__.py`.

**Done when:** existing agents.py classes otherwise unchanged; imports in `__init__.py` succeed; no circular imports.

### 1.4 — Alembic migration ⚠️ NEEDS REWORK
Run `python -m alembic revision --autogenerate -m "script registry and execution tables"`, review the generated file in `backend/alembic/versions/` (down_revision chain, `postgresql.ENUM(..., create_type=False)`, no parameterized DDL, reversible downgrade), then `python -m alembic upgrade head` and verify with `python -m alembic current`. Restart backend. **The initial migration includes `ExecutionModeConfiguration`; a follow-up drop migration (task 1.7) is required before testing.**

**Done when:** `alembic current` shows the new head (including the 1.7 drop migration); backend restarts without errors; downgrade is reversible.

### 1.5 — Script Registry service (Control Center) ⚠️ NEEDS REWORK
New service module under `backend/app/services/` (e.g. `script_registry/`) providing versioning, lifecycle transitions (`draft → verified → compiled → retired`, re-verification required after repair/tool-schema change per V4), lineage lookup, and health aggregation from fallback events. This is the only code path that reads/writes script tables. **Strip the `ExecutionModeConfiguration` CRUD; add `RepairAttempt` record management (task 1.6).**

**Done when (revised):** all lifecycle transitions enforced server-side (invalid transitions rejected); health degrades on repeated fallbacks (F4); unit tests cover transitions; no mode CRUD remains.

### 1.6 — Add `RepairAttempt` model + repair lineage *(new)*
In `backend/app/db/models/script_registry.py`: add the `RepairAttempt` entity per data-model.md §1.6 (defect diagnosis, diff applied, retry outcome, repaired candidate version) linked to `FallbackEvent`, and add the `repaired_from` lineage column on `ScriptVersion` (§1.2). Export from `__init__.py`.

**Done when:** repair relationships resolve (`FallbackEvent` → `RepairAttempt` → repaired `ScriptVersion`); migration 1.7 (or a chained revision) covers the new table/column; no credential-shaped fields.

### 1.7 — Follow-up Alembic migration dropping `ExecutionModeConfiguration` *(new)*
Generate a follow-up revision that drops the `ExecutionModeConfiguration` table and any mode-related columns/enum values, with a reversible downgrade. Review the generated file per AGENTS.md migration rules, then `python -m alembic upgrade head`, verify with `python -m alembic current`, and restart the backend.

**Done when:** `ExecutionModeConfiguration` no longer exists in the DB or models; `alembic current` shows the new head; downgrade restores the prior schema; backend restarts cleanly.

## Phase 2 — Script Compiler & Runner (Agent Runtime)

### 2.1 — Declarative step-graph schema
Pydantic v2 models (in Agent Runtime, e.g. `backend/app/agent_runtime/scripts/`) describing the bridge script: typed step nodes (tool call, transform/filter, semantic-bridge, decision, output), typed inputs/outputs, comparison tolerance, model-backed step markers (S3). No credentials/tokens anywhere in the schema (SEC3).

**Done when:** schema round-trips JSON; tool-call steps reference tools by name only (permission resolution stays delegated); validation rejects unknown step types.

### 2.2 — Script Compiler
Component in Agent Runtime that converts an implementation plan and/or recorded tool-call sequence of a successful LLM run into a candidate step graph (C1, C2). Produces candidates only — never promotes, never executes.

**Done when:** given a recorded tool-call sequence, it emits a valid step graph; output contains no secrets; candidates are submitted to CC registry via internal API (not DB).

### 2.3 — Script Runner
Executes compiled step graphs step-by-step. Every tool call goes through Communication Hub exactly like an agent tool call (same mTLS path, permission resolution via CC, per-call token injection by CH — SEC1/SEC2). Validates outputs; on failure, raises a typed failure to the Script-First Dispatcher.

**Done when:** a compiled script run completes a tool sequence through CH with zero LLM tokens for scriptable steps; runner cannot invoke a tool the agent identity is not permitted for (verify via permission rejection path).

### 2.4 — Model-backed step invocation
Wire semantic-bridge sub-agent and System One decision tool as invocable step types with structured results/confidence carried downstream; mark steps as model-backed in execution telemetry (S1–S3).

**Done when:** a step graph containing a semantic-bridge and a decision step executes; telemetry/execution record lists the model-backed steps used.

### 2.5 — Execution-mode resolver ⚠️ NEEDS REWORK
On session start, resolve mode + current compiled script version per workflow via CC internal API; route to LLM loop, Script Runner, or fallback path (E1–E3 as originally specified). **This component is removed: there are no execution modes; script-first dispatch is automatic and fallback is unconditional.**

**Done when (revised):** `mode_resolver.py` and its tests are deleted (task 2.6); no mode-resolution calls remain in dispatch wiring.

### 2.6 — Delete mode resolver + strip mode routing *(new)*
Delete `backend/app/agent_runtime/scripts/mode_resolver.py` and its tests; remove mode resolution calls/wiring from `dispatch.py` and the session-start path; remove the internal mode endpoint usage from the AR CC client.

**Done when:** no references to execution modes or `mode_resolver` remain in the Agent Runtime codebase; `llm`-path behavior is byte-equivalent with today's behavior when no verified script exists; full test suite passes.

### 2.7 — Plan-time compilability analysis *(new)*
Extend the compiler/plan integration: at implementation-plan generation time the agent marks each plan step **scriptable** (deterministic MCP tool calls + local data processing) or **model-backed** (semantic bridging, System One judgment, interactive input) — E4. A workflow is compilation-eligible only if the agent determines its steps are scriptable (E5); conversational/interactive agent types are marked never-compiled (E6). Persist the marks with the plan and feed them to the compiler as eligibility input.

**Done when:** plans embed compilability marks; conversational/interactive agents are never compiled (verified by test); model-backed marks align with step-graph `model_backed` flags; telemetry records eligibility decisions.

### 2.8 — Session-binding enforcement in runner *(new)*
Bind script execution to the agent session: the Script Runner's MCP tool calls use the **same dual OIDC identities** (user-realm human + agent-realm agent principal) as the agent's own tool calls, via the identical mTLS/Communication Hub path (identity parity, E7/SEC1). Scripts never introduce a separate or anonymous identity; execution records capture the session reference and identity-parity evidence.

**Done when:** a script run's CH tool calls are indistinguishable from agent tool calls at the identity/permission layer (same certs, same token injection); session reference + identity-parity confirmation recorded on the `ScriptExecutionRecord`; test asserts no anonymous/separate identity path exists.

### 2.9 — Standardized invocation contract verification *(new)* ✅ VERIFIED
Formalize/enforce the invocation contract (A5/N9): the Script Runner **requires** session identity context (session id + agent type) on every invocation and refuses unbound execution — no anonymous identity path. Current code already enforces this (`runner.py` raises a typed error when `session_id`/`agent_type_id` are missing) — **verify only; rework only if gaps are found** in enforcement or test coverage (anonymous-context rejection, identity-parity evidence on execution records).

**Done when:** a test asserts execution without identity context is refused; identity-parity evidence is recorded on execution records; no rework needed if coverage already exists.

### 2.10 — Plan-step script links (E4a) *(new)* ✅ DONE
When the compiler produces a script from an implementation plan, embed a per-step `script_version_id`/link into the plan: the compiler records the reference on the plan step; the plan API/response (Pydantic plan schemas) exposes it; the plan UI (wherever plans render) shows a link to the script — opening the owning agent type's Scripts tab (6.3) — so reviewers can inspect content, description, and lineage during plan review.

**Done when:** a plan generated with compilation exposes script links on script-backed steps; plans without compilation are unchanged; the API response includes the reference; the UI renders the link.

### 2.11 — Post-run tool-call capture *(new)*
- [x] Add a bounded per-session in-memory capture (`backend/app/agent_runtime/scripts/capture.py`, last ~50 calls: tool name, arguments, result) recorded in `CommHubToolClient.call_tool` on successful LLM-path tool calls. Best-effort: capture failure never affects execution. Security: memory-only for the session lifetime, never persisted raw; script executions (provenance/script_version-tagged) are never captured; compiled graphs pass the compiler's secret-shaped-field guard (SEC3).

**Done when:** LLM-run tool sequences are captured per session with no effect on tool execution when capture fails; script-path calls are excluded; memory is bounded.

### 2.12 — Post-run auto-compilation hook *(new)*
- [x] Add `backend/app/agent_runtime/scripts/autocompile.py` (`schedule_autocompile` → `_run_autocompile`, fire-and-forget asyncio task, all errors logged and swallowed) hooked into `dispatch.py`'s LLM-completion paths (no-serving-script branch and post-fallback branch). Flow: skip when a serving version already exists (duplicate protection); skip when the tool sequence is empty; run `analyze_compilability` against the fetched plan + agent-type traits (conversational / model-backed → skip, E4–E6); `ScriptCompiler.compile_from_tool_sequence` → `cc_client.submit_candidate` (draft definition+version with a plan-goal description); `VerificationEngine` shadow-run against `cc_client.get_llm_reference(session_id)` + `cc_client.submit_verification`; on match → `cc_client.promote_version` (verified → compiled serving); on mismatch → leave the draft with recorded evidence for the repair loop. OTEL span `script.autocompile` with eligible/compiled/verified/promoted attributes.
- [x] Focused unit tests `backend/tests/test_autocompile.py` (eligible→promoted; ineligible skip; already-serving skip; mismatch leaves draft; failure containment).

**Done when:** an eligible LLM run auto-produces a serving script version without operator action; ineligible/already-serving runs are skipped with a logged reason; verification-mismatch candidates stay draft; no auto-compile error can break a completed run.

## Phase 3 — Verification & Promotion

### 3.1 — Verification Engine
Shadow-runs candidate scripts against recorded LLM executions on identical inputs; compares outputs using the declared comparison tolerance; produces match/mismatch verdicts (V1).

**Done when:** identical inputs yield a match verdict on a correct candidate and a mismatch with a usable diff on a broken one; comparison is deterministic.

### 3.2 — Verification evidence persistence
Evidence (inputs, expected vs actual, outcome, verdict reason) is stored via the CC registry APIs — never locally in Agent Runtime (V2).

**Done when:** every verification run produces a persisted `VerificationRun` row retrievable through the CC API; Agent Runtime writes no DB rows.

### 3.3 — Promotion / rejection lifecycle transitions
On match: promote version to verified and set as `current_compiled_version` (compiled). On mismatch: keep draft with recorded diff for repair (V3). Promotion requests originate in Agent Runtime but are executed by CC's registry service.

**Done when:** only verified versions can become the compiled version; mismatched candidates remain draft; operator-triggered demote/retire also works (C3).

### 3.4 — Auto-promotion endpoint *(new)*
- [x] Add `POST /api/v1/internal/scripts/promote` (`PromoteVersionRequest`) to `backend/app/api/v1/internal/scripts.py` calling the registry service `transition_version` (draft → verified → compiled with the V4 passing-verification guard); add `promote_version` to the AR `ScriptRegistryClient` and allowlist the endpoint in `_AR_ALLOWLIST` (`backend/app/api/deps.py`). Rationale: script-first dispatch with unconditional LLM fallback makes auto-promotion on a verified shadow-run match safe and operator-free.

**Done when:** the AR auto-compiler promotes a verified candidate to the serving version through the mTLS internal API; non-verified promotion attempts are rejected (409).

## Phase 4 — Fallback & Repair Loop

### 4.1 — Fallback Controller ⚠️ NEEDS REWORK
Detects script failure (execution error, tool schema mismatch, output validation failure — F1) and switches the run to the LLM agent path except in `compiled-only` mode. **Rework: remove all mode branching — fallback is unconditional on any automation failure (E2); a run never fails solely because a script failed.**

**Done when (revised):** all trigger types cause unconditional fallback to the LLM path; the LLM path completes the run (F3); no `compiled-only` structured-failure path remains; permissions never widen during fallback.

### 4.2 — Fallback event recording & health degradation
Record trigger reason, failure detail, resulting action, script version, and health impact via CC; aggregate into script health status; surface operator notification on degradation (F2, F4).

**Done when:** every fallback produces a linked `FallbackEvent`; repeated fallbacks degrade health status and an operator-visible signal exists.

### 4.3 — Repair loop
On fallback, the LLM path may produce a repaired candidate (new ScriptVersion with parent link) that must pass verification before promotion (F3, V4).

**Done when:** repaired candidates re-enter Phase 3 verification; a repaired version can only serve compiled runs after a successful verification run.

### 4.4 — Self-improvement repair loop *(new)*
On script-defect failures the agent runs the full self-improvement cycle (E9/E10): diagnose the defect → produce a repaired candidate as a **new ScriptVersion with `repaired_from` lineage** and a **`RepairAttempt` record** (diagnosis, diff, retry outcome) → re-verify via the Verification Engine → retry the repaired script within execution guardrails (permissions, no credentials, no external access, bounded attempt budget). Exhaustion of the bounded budget triggers unconditional fallback with reason capture.

**Done when:** each repair attempt is recorded and auditable (diagnosis, diff, outcome); repair lineage (`repaired_from`) is queryable; attempts are bounded by a guardrail budget with exhaustion falling back unconditionally; unit tests cover diagnose → repair → re-verify → retry success and exhaustion paths.

### 4.5 — Script-First Dispatcher simplification *(new)*
Rework `dispatch.py` (absorbing `fallback.py` responsibilities): when a verified serving script exists, dispatch automatically to the Script Runner (no configuration); when none exists, use the LLM path without error; on **any** automation failure — including repair exhaustion — fall back **unconditionally** to the LLM path and orchestrate the 4.4 repair-retry loop within guardrails.

**Done when:** dispatcher contains no mode logic; verified-script runs dispatch automatically; every forced failure completes via the LLM path with a recorded reason; repair-retry orchestration is bounded and observable.

## Phase 5 — APIs, Governance & Cost Tracking (Control Center)

### 5.1 — Registry REST API
JWT-authenticated endpoints under `backend/app/api/v1/` (e.g. `scripts.py`): list/get scripts and versions, lifecycle transitions (promote/demote/retire), version diff, health status. Pydantic v2 request/response schemas; `require_permission()` on every route.

**Done when:** all routes require permission; lifecycle rules enforced; OpenAPI docs generated.

### 5.2 — Internal CC↔AR endpoints ⚠️ NEEDS REWORK
Endpoints under `backend/app/api/v1/internal/` for: resolve execution mode + current compiled script version; submit candidates/verification evidence; report fallback events and execution records. Agent-instance certificates must be blocked from `/internal/*` (only service certs, as with CH); existing certificate middleware enforced. **Rework: remove the mode-resolution endpoint; replace with a serving-version lookup plus repair-attempt endpoints (task 5.6).**

**Done when (revised):** AR can complete all registry interactions without DB access using only the revised endpoints; a request presenting an agent-instance cert to `/internal/*` is rejected with 403; no mode endpoints remain.

### 5.3 — Script provenance tagging (Communication Hub)
Extend CH tool-call bookkeeping: each call carries `script` vs `llm` provenance and script version, recorded in audit trails. Protocol, permission delegation, and per-call token injection unchanged.

**Done when:** CH audit records for script-initiated calls show provenance + version; token/permission behavior identical to agent calls.

### 5.4 — Audit & cost reporting endpoints ⚠️ NEEDS REWORK
Endpoints for per-execution audit (mode, script version, fallback events — G2) and cost reports (tokens saved vs LLM baseline, per workflow and aggregate, with residual model-backed step usage called out — G3, G4). **Rework: strip `mode` from audit payloads/records; include fallback events and repair attempts (G2) instead.**

**Done when (revised):** reports distinguish script vs LLM runs (no mode attribute); repair attempts appear in audit; token-saved estimates aggregate correctly; dashboard consumers can fetch summary metrics.

### 5.5 — Permission resource types & manifest registration
If new resource types are introduced (e.g. `agent::scripts`), register in **BOTH** `backend/app/core/resource_types.py` (ResourceTypeManifest + MODULE_GROUPS) **and** `frontend/src/constants/resourceTypes.ts` (RESOURCE_TYPE_MANIFEST + MODULE_GROUPS submodules).

**Done when:** wildcard `agent::*` holders can access new endpoints without 403; both manifests mirrored; covered by a permission test.

### 5.6 — Strip mode APIs; add repair-attempt listings *(new)*
Remove `GET/PUT /scripts/execution-modes`, `GET /scripts/execution-modes/resolve`, and `GET /internal/scripts/mode` from `backend/app/api/v1/scripts.py` and `backend/app/api/v1/internal/scripts.py`. Replace the internal mode endpoint with a serving-version lookup; add `GET /scripts/{id}/repairs` and `GET /internal/scripts/repairs` for RepairAttempt listings (E10, G2).

**Done when:** no mode endpoints exist in OpenAPI; repair listings return RepairAttempt records with lineage; permission checks cover the new routes; API tests updated.

## Phase 6 — Frontend (agent-owned scripts)

### 6.1 — Execution-mode selector on Agent Type UI ✅ DONE (removed)
There is nothing to configure: no mode UI or `/scripts/execution-modes` persistence exists in `AgentTypeForm.tsx` / `AgentManagementPage.tsx`; leftover mode i18n strings were removed.

### 6.2 — Delete standalone Scripts module ✅ DONE
Deleted from the tree:
- `frontend/src/pages/scripts/ScriptsPage.tsx` and `frontend/src/pages/scripts/ScriptDetailDrawer.tsx`
- the `/admin/scripts` route + `ScriptsPage` import in `frontend/src/app/AppRouter.tsx`
- the `nav.scripts` entry in `frontend/src/app/AppShell.tsx` (label key `nav.scripts` purged from locales) and any AppShell test assertions on it
- `frontend/src/__tests__/script-registry-page.test.tsx` (old registry page test)
- the `admin.scripts.*` i18n keys in locale files — **after** the key migration in 6.3 (keys move to the agent-detail scripts namespace)

**Done when:** no standalone scripts page, route, nav entry, or page test remains; no orphaned `admin.scripts.*` keys; frontend build + tests pass.

### 6.3 — Scripts tab in the Agent Type detail dialog ✅ DONE *(replaces former standalone page — PRD A1–A4 / spec N8, C1)*
Add a **Scripts** tab to `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` (alongside Details/Agent Preview/Execution Logs/Sessions). For each script owned by the agent type, show:
- **version history** with `repaired_from` self-improvement lineage (parent + repaired versions)
- **lifecycle chips** (draft / verified / compiled / retired) and **health** status
- **human-readable description** of what the script does
- **promote/retire actions** (operator lifecycle control) and **verifications / fallbacks / repairs** views (defect diagnosis, diff, retry outcome)

Repurpose `frontend/src/hooks/useScripts.ts` (no mode queries; keep `useScriptRepairs`) and `frontend/src/types/scripts.ts`. **Move i18n keys from `admin.scripts.*` to an agent-detail scripts namespace** (e.g. `agents.types.scripts.*`) in `en.json`; all strings via `t()`; dialogs follow the standard dialog error-handling pattern; permission-denied states render the PermissionDeniedAlert pattern.

**Done when:** the standalone module (6.2) is gone; operator can complete the full lifecycle from the dialog tab; fallback/repair history is visible; no orphaned i18n keys; tests cover the tab.

### 6.4 — Script health & cost dashboard cards *(optional)*
Dashboard cards for compilation rate, fallback rate, script hit rate, cumulative token savings (G4).

**Done when:** cards render with permission checks and show data from 5.4 endpoints; strings via `t()`.

### 6.5 — Plan UI script links (E4a) *(new)* ✅ DONE
Wherever implementation plans are rendered in the frontend, show a per-step link to the backing script version (delivered by the plan API per task 2.10); the link opens the owning agent type's Scripts tab (6.3) for review during plan review. Steps without a script render unchanged.

**Done when:** script-backed plan steps render a working link; strings via `t()`; tests cover link rendering.

## Phase 7 — Tests & Observability

### 7.1 — Backend unit tests ⚠️ NEEDS REWORK
Under `backend/tests/`: compiler (plan/sequence → step graph), runner (step execution, typed failures), verification (match/mismatch/tolerance), fallback (all trigger types), registry service (lifecycle transitions, health). **Rework: remove mode-dependent cases (`compiled-only`, mode routing, mode resolver); add dispatcher (automatic dispatch, unconditional fallback) and repair-loop (4.4) cases.**

**Done when (revised):** all components have unit tests with no mode dependencies; suite passes via the backend runner used in CI.

### 7.2 — API tests ⚠️ NEEDS REWORK
Registry CRUD permissions, internal endpoints (including agent-instance cert rejection on `/internal/*`), cost/audit endpoints. **Rework: delete mode-endpoint tests; add serving-version and repair-listing endpoint tests.**

**Done when (revised):** permission matrix and certificate access rules covered by tests with no mode endpoints; all pass.

### 7.3 — OTEL instrumentation ⚠️ NEEDS REWORK
New span attributes on the AR script components (`compiler.py` `script.name`/`script.steps`, `runner.py` `script.version_label`/`script.failure`/`script.model_backed_steps`, `mode_resolver.py` `script.execution_mode`/`script.resolved_version`, `fallback.py` `script.fallback_reason`, `verification.py` `script.verification_outcome`) and the CC registry service (`script.lifecycle_transition`, `script.verification_outcome`), plus a `script.*` span on the CH provenance-tagged tool path. Aggregate rates (compilation/hit/fallback/savings) are served by the 5.4 report endpoints rather than exported metrics. **Rework: drop mode_resolver spans; add repair-loop spans (`script.repair_attempt`, `script.repair_outcome`) and compilability spans (`script.compilability_verdict`).**

**Done when (revised):** traces from a compiled run with a repair cycle carry the new attributes across AR, CC, and CH; no mode attributes remain.

### 7.4 — E2E happy path
Under `e2e/tests/`: LLM run → candidate compiled → verified → subsequent run executes via script with zero scriptable-step LLM spend → forced failure falls back with recorded reason → repaired candidate re-verifies.

**Done when:** e2e scenario passes against a running stack.

### 7.5 — Master docs update
Apply the updates listed in architecture.md §5 and data-model.md §5 (`docs/master/`).

**Done when:** all listed master doc files updated, including the new `modules/workflow-compilation.md`.

### 7.6 — MCP-only boundary enforcement test *(new)*
Static + behavioral test asserting scripts are strictly limited to MCP tool calls plus local data processing (E8): no direct network, filesystem-outside-sandbox, database, or other I/O in script execution; all external access flows through the CH tool-call path.

**Done when:** static source assertions reject imports/constructs for network/DB/external I/O in the script runtime modules; a behavioral test shows a script attempting non-MCP I/O is blocked and triggers unconditional fallback with a recorded reason.

## Completion Checklist

- [x] All Alembic migrations generated, reviewed, applied, and reversible
- [x] Only Control Center connects to PostgreSQL — verified by test
- [x] Agent-instance certificates rejected from `/internal/*` — verified by test
- [x] Scripts never hold credentials/tokens; CH injects tokens per tool call — verified by code review + tests
- [x] Script tool calls use the identical permission path as agent tool calls (SEC1/SEC2)
- [x] Fixed script-first strategy with unconditional fallback behaves per revised E1–E3 (no modes)
- [x] ExecutionModeConfiguration removed (model + migration + APIs + UI) — verified by tests
- [x] Plan-time compilability analysis gates compilation; conversational/interactive agents never compiled (E4–E6) — verified by test
- [x] Script execution bound to the agent session with identity parity (E7) — verified by test
- [x] MCP-only script boundary enforced (E8) — verified by test
- [x] Self-improvement repair loop bounded and auditable (E9–E10) — verified by test
- [x] Verification evidence retained and auditable (V2)
- [x] Every fallback carries a recorded reason and script version (F2)
- [x] New resource types registered in BOTH backend and frontend manifests (if added)
- [x] All new UI strings go through i18next `t()`
- [x] OTEL spans/metrics implemented for compilation, fallback, and savings
- [x] Backend unit, API, and e2e tests pass
- [ ] `docs/master/` documentation updated
