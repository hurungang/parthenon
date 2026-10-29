# Tech Spec: Software 3.0 Agent Framework — Workflow Compilation

**Related:** [prd.md](prd.md) · [spec-change.md](spec-change.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md) · [implementation-plan.md](implementation-plan.md)

## Compliance Header (top_priority_rules)

- **3 services fully segregated** — new components live strictly inside their service: compiler/runner/verification/dispatcher/repair in Agent Runtime; registry/audit/cost in Control Center; provenance tagging in Communication Hub.
- **Agents/scripts run only in Agent Runtime** — the Script Runner executes inside AR under the executing agent's identity; no execution logic anywhere else.
- **Only Control Center touches the database** — all new tables are CC-owned; AR reads/writes registry state exclusively via CC internal APIs.
- **Scripts never hold credentials/tokens** — step graphs reference tools by name only; every tool call traverses CH with per-call token injection and CC permission resolution, identical to agent tool calls (SEC1–SEC3).

---

## Component Breakdown

All modules follow existing conventions: Pydantic v2 schemas, SQLAlchemy 2 async models, strong typing (Python Enums), OTEL instrumentation.

### Agent Runtime (execution plane) — `backend/app/agent_runtime/`

New package `scripts/` (or `compilation/`) containing:

| Component | Responsibility | Boundaries |
|---|---|---|
| **StepGraph schema** (`schemas.py`) | Pydantic v2 models for the declarative bridge script: step nodes (`tool_call`, `transform`, `semantic_bridge`, `decision`, `output`), typed inputs/outputs, `comparison_tolerance`, `model_backed` markers | Tool references by name only — no credentials, no URLs with secrets |
| **Script Compiler** (`compiler.py`) | **Plan-time compilability analysis** — the agent marks each plan step **scriptable** (deterministic MCP tool calls + local data processing) or **model-backed** (semantic bridging, System One judgment, interactive input); conversational/interactive agents are never compiled (E4–E6). Then: plan + recorded tool-call sequence → candidate step graph (C1, C2) | Produces candidates only; never promotes or executes; compilability marks are advisory input to eligibility, not execution config |
| **Script Runner** (`runner.py`) | Executes compiled step graphs **bound to the agent session** under the **standardized invocation contract (A5/N9)**: the runner *requires* identity context (session id + agent type) on every invocation and refuses unbound execution — there is no anonymous identity path. MCP tool calls carry the same dual OIDC identities as the agent via the existing CH client path (`comm_hub_client.py`, same mTLS/CH path as agent tool calls; E7/SEC1); output validation per step; between steps only local data processing — MCP is the only external access (E8). Transform ops between steps: structural (`passthrough`, `select_keys`, `json_path_get`, `template`, `constant`) and computed-data (`count`, `pluck`, `merge`, `sum`, `first`, `last`). Ships best-effort execution log entries (run start/step completion/model-backed step/completion/failure) via an injected log shipper backed by the CC data client — logging failures never break the run | Runs under agent identity; fails typed (`ExecutionError`, `SchemaMismatch`, `OutputValidationFailure`) to the Script-First Dispatcher; no network/DB/other I/O |
| **Verification Engine** (`verification.py`) | Shadow-runs candidates against recorded LLM executions on identical inputs; compares with tolerance; produces verdicts + diffs (V1, V3) | Evidence persisted via CC APIs, never locally |
| **Script-First Dispatcher** (`dispatch.py`, absorbing `fallback.py`) | Fixed platform strategy — **no execution modes exist**. Verified script exists → run the script automatically; no verified script → LLM path without error. On **any** automation failure it **unconditionally falls back** to the LLM path (a run never fails solely because a script failed; E2), records the fallback reason + script version, and orchestrates the **self-improvement repair loop**: defect diagnosis → LLM produces a repaired candidate (new draft version with `repaired_from` lineage + `RepairAttempt` record) → re-verification → bounded retry of the repaired script, within execution guardrails (E9–E10, F1–F4) | Never widens permissions during fallback or repair; bounded repair attempt budget; degrades script health via CC on repeated fallbacks |

Model-backed step invocation reuses existing Semantic Bridge sub-agents and the System One decision tool (`backend/app/services/system_one/`, decision_tools models) — they are called as steps, with structured result + confidence carried downstream (S1–S3).

### Control Center (governance plane) — `backend/app/services/` + `backend/app/api/`

| Component | Location (suggested) | Responsibility |
|---|---|---|
| **Script Registry Service** | `backend/app/services/script_registry/` | Versioning, lifecycle transitions (`draft → verified → compiled → retired`), lineage (including `repaired_from` repair lineage), health aggregation, **RepairAttempt records**, evidence storage — the only writer of script tables |
| **Script Audit & Cost Service** | within the same package | Per-execution provenance audit (G2, incl. repair attempts); token-saved computation vs LLM baseline, per workflow and aggregate (G3) |
| **REST API** | `backend/app/api/v1/scripts.py` | Registry CRUD, lifecycle transitions, version diff, health, cost/audit reports (JWT + `require_permission()`) |
| **Internal API** | `backend/app/api/v1/internal/scripts.py` | CC↔AR: serving-version lookup, candidate/evidence submission, fallback/execution-record/repair reporting — service certs only |

### Communication Hub — `backend/app/communication_hub/`

Provenance tagging only: extend tool-call handling in the MCP/services layer so each call carries `provenance: "script" | "llm"` and optional `script_version` into audit records. Protocol, permission delegation to CC, and per-call token injection are **unchanged**.

---

## API Changes

### Control Center REST (JWT-authenticated, permission-gated)

Base: `/api/v1/scripts` (new router registered alongside `agents.py`, `conversations.py`).

| Method & path | Purpose |
|---|---|
| `GET /scripts` | List script definitions (filter by agent type, lifecycle, health) |
| `POST /scripts` | Create definition (normally via compiler submission, but operator-visible) |
| `GET /scripts/{id}` / `GET /scripts/{id}/versions` | Definition + version history with lineage |
| `POST /scripts/{id}/versions` | Create a new draft version (candidate/repair submission from AR, or operator) |
| `GET /scripts/{id}/versions/{vid}/diff?against={vid2}` | Version diff view |
| `POST /scripts/{id}/versions/{vid}/promote` | Lifecycle transition to a target status (promote/demote; validated server-side, V4 re-verification rules) |
| `POST /scripts/{id}/versions/{vid}/retire` | Operator lifecycle control (C3) |
| `GET /scripts/{id}/verifications` | Verification evidence (V2) |
| `GET /scripts/{id}/fallbacks` | Fallback events with reasons (F2) |
| `GET /scripts/{id}/repairs` | Repair attempts for a script (defect diagnosis, diff, retry outcome, repaired candidate — E10, G2) |
| `GET /scripts/{id}/health` | Health status + recent fallback trend (F4) |
| `GET /scripts/executions` | Execution records (script vs LLM runs, for audit) |
| `GET /reports/compilation` | Compilation rate, script hit rate, fallback rate (G4) |
| `GET /reports/cost-savings` | Tokens saved vs LLM baseline, per workflow + aggregate, residual model usage (G3) |

All request/response bodies are Pydantic v2 models; all routes wrapped with `require_permission()` against the new resource type (see below). **No execution-mode endpoints exist**: the previously specified `GET/PUT /scripts/execution-modes` and `GET /scripts/execution-modes/resolve` were removed — script-first execution with unconditional fallback is fixed platform behavior, not configuration (E1–E3).

The REST surface is **unchanged by the agent-owned-scripts adjustment** (A4): these endpoints now serve the **Scripts tab of the Agent Type detail dialog** instead of a standalone admin page — no new or removed REST routes.

**Plan API exposes script links (E4a)**: when the compiler produces a script from a plan, the implementation-plan response (`AgentPlan` schemas in `backend/app/schemas/agents.py` or plan schemas) embeds a per-step `script_version_id`/link for steps backed by a script version, so plan reviewers can open the script (in the agent type's Scripts tab). The plan UI renders the link wherever plans are shown.

### Internal CC↔AR endpoints (`/api/v1/internal/scripts/...`)

Certificate rules (existing middleware, unchanged): **agent-instance certs are blocked from `/internal/*`**; AR calls these endpoints with its **service certificate** (same pattern as Communication Hub today).

| Endpoint | Direction | Purpose |
|---|---|---|
| `GET /internal/scripts/serving-version?agent_type_id=&workflow=` | AR ← CC | Fetch the current verified/compiled script version for a workflow (dispatcher check — no mode resolution; absent → LLM path) |
| `POST /internal/scripts/candidates` | AR → CC | Submit candidate step graph (draft version) |
| `POST /internal/scripts/verifications` | AR → CC | Submit verification evidence + verdict request |
| `POST /internal/scripts/fallbacks` | AR → CC | Report fallback event (reason, version, detail) |
| `POST /internal/scripts/executions` | AR → CC | Report script execution record (outcome, duration, tools, model-backed steps, session reference, tokens saved) |
| `POST /internal/scripts/repairs` | AR → CC | Report a repair attempt (defect diagnosis, diff, `RepairAttempt` record) and submit the repaired candidate (new draft version with `repaired_from` lineage, F3/E9) |
| `GET /internal/scripts/repairs?script_id=` | AR ← CC | List repair attempts for a script (bounded-retry bookkeeping within an episode) |
| `GET /internal/scripts/versions/{version_id}` | AR ← CC | Fetch a compiled version's step graph for execution |
| `GET /internal/scripts/llm-reference/{session_id}` | AR ← CC | Fetch recorded LLM execution inputs/outputs for shadow comparison |

Permission resolution for script tool calls reuses the existing CC permission API unchanged.

---

## Data Access Patterns

Per data-model.md entities. **All access is through Control Center** (sole DB gateway); AR and CH never open a DB connection.

| Entity | Written by | Read by | Path |
|---|---|---|---|
| `ScriptDefinition` | CC registry service (on AR candidate submission or operator action) | CC REST (UI/audit), AR (via internal serving-version API) | AR → CC internal API → CC service → DB |
| `ScriptVersion` | CC registry service | CC REST (diff, evidence), AR (compiled content via internal API) | same |
| `VerificationRun` | CC registry service (evidence submitted by AR Verification Engine) | CC REST (audit), repair loop in AR via internal read | same |
| `FallbackEvent` | CC registry service (reported by AR Script-First Dispatcher) | CC REST (health, audit, notifications) | same |
| `RepairAttempt` | CC registry service (reported by AR repair loop) | CC REST (audit, repair listings), AR repair loop via internal read | same |
| `ScriptExecutionRecord` | CC registry service (reported by AR after each compiled/fallback run) | CC REST (audit, cost reports, dashboard) | same |
| Existing `AgentType`, `AgentPlan` | unchanged | CC registry service (ownership/lineage joins) | same |
| Existing `ConversationSession`, `ExecutionLogEntry`, `ToolCallRecord` | unchanged writers | CC audit joins execution records to sessions/tool calls | CC only |

Provenance metadata on tool calls (`script` vs `llm`, script version) flows AR → CH on each call and is persisted by CH into its audit trail via its existing CC delegation — no new permission checks.

---

## Code Reference Map

| New component / file | Location | Touches (existing files) |
|---|---|---|
| ScriptDefinition, ScriptVersion (+ `repaired_from` lineage), VerificationRun, FallbackEvent, RepairAttempt models | `backend/app/db/models/script_registry.py` *(implemented)* | `backend/app/db/models/__init__.py` (exports), `agents.py` (`AgentType`, `AgentPlan` FK relationships) |
| ScriptExecutionRecord model; **`ExecutionModeConfiguration` dropped** | `backend/app/db/models/script_execution.py` *(implemented — mode entity and `execution_mode` column removed; `identity_parity_confirmed` added)* | `backend/app/db/models/__init__.py`, `conversations.py` (`ConversationSession`), `agents.py` (`AgentJob`) |
| Alembic migration | `backend/alembic/versions/a1b2c3d4f5e6_add_script_registry_and_execution_tables.py` *(implemented)* | Migration chain; follows AGENTS.md migration rules (ENUM `create_type=False`, reversible downgrade) |
| Follow-up Alembic migration (mode removal + repairs) | `backend/alembic/versions/b2c3d4e5f6a7_drop_execution_mode_configuration.py` *(implemented, applied — head `b2c3d4e5f6a7`)* | Drops `execution_mode_configurations` + `script_execution_records.execution_mode`; adds `repair_attempts`, `script_versions.repaired_from_id`, `identity_parity_confirmed`; reversible downgrade |
| Runtime dispatch wiring | `backend/app/agent_runtime/scripts/dispatch.py` *(implemented — Script-First Dispatcher: `run_session_script_first`, automatic script-first dispatch, unconditional LLM fallback, bounded repair-retry orchestration; no modes)* | `backend/app/agent_runtime/api/execute.py` (`_execute_session` calls `run_session_script_first` before the LLM executor) |
| StepGraph schemas, Compiler, Runner, Verification Engine, Repair loop, CC client | `backend/app/agent_runtime/scripts/` *(package: `schemas.py`, `compiler.py` *(plan-time compilability analysis via `analyze_compilability`, E4–E6)*, `runner.py` *(session-binding + MCP-only boundary enforcement)*, `verification.py`, `repair.py` *(implemented — bounded self-improvement loop, `MAX_REPAIR_ATTEMPTS=2`)*, `fallback.py` *(implemented — unconditional fallback, no mode branching)*, `capture.py` *(implemented — bounded per-session in-memory tool-call capture, memory-only/never persisted raw, best-effort, script-path calls excluded)*, `autocompile.py` *(implemented — post-run auto-compilation hook: `schedule_autocompile` fire-and-forget task launched from `dispatch.py` LLM completion; duplicate-protected serving-version check, `analyze_compilability` eligibility, candidate submission, shadow verification against the recorded LLM reference, auto-promotion on match / draft-with-evidence on mismatch; OTEL span `script.autocompile`)*, `cc_client.py` — the CC registry client (`get_serving_version`, `submit_candidate`, `submit_verification`, `get_llm_reference`, `promote_version`, `report_repair`, `list_repairs`); **`mode_resolver.py` deleted**; metadata/data clients unchanged)* | `backend/app/agent_runtime/comm_hub_client.py` (tool calls — `provenance`/`script_version` + best-effort capture hook on LLM-path calls), LangChain agent loop in `backend/app/services/agents/` (plan + compilability marks + recorded tool-call capture) |
| Semantic Bridge / System One step invocation | within `backend/app/agent_runtime/scripts/runner.py` | `backend/app/services/system_one/`, `backend/app/db/models/decision_tools.py`, `system_one_provider_config.py` |
| Script Registry / Audit & Cost services | `backend/app/services/script_registry/service.py` *(implemented — mode CRUD/resolution removed; `record_repair_attempt`, `list_repairs`, `get_serving_version` added)* | `backend/app/db/models/script_registry.py`, `script_execution.py`, `backend/app/services/agents/`, `permission_resolution.py` (pattern reference) |
| CC REST API | `backend/app/api/v1/scripts.py` *(implemented — mode endpoints removed; `GET /scripts/{id}/repairs` added)* | `backend/app/api/v1/__init__.py` (router registration), `backend/app/api/deps.py` (auth deps), `backend/app/schemas/scripts.py` *(implemented — mode types removed, repair/serving-version types added)* |
| CC internal API | `backend/app/api/v1/internal/scripts.py` *(implemented — `GET /serving-version`, `GET/POST /internal/scripts/repairs`, and `POST /promote` *(implemented — `PromoteVersionRequest` → registry `transition_version` to compiled/serving, V4 passing-verification guard, 409 on illegal transitions)*; `/mode` removed)* | existing `backend/app/api/v1/internal/` package; `backend/app/api/deps.py` `_AR_ALLOWLIST` (serving-version, candidates, verifications, promote, fallbacks, executions, repairs, llm-reference entries); certificate middleware in `backend/app/middleware/` (agent-instance certs blocked from `/internal/*`) |
| CH provenance tagging | `backend/app/communication_hub/api/internal/tool_routing.py` *(modify: `ToolCallRequest.provenance`/`script_version` + audit log record)* | protocol, permission delegation, per-call token injection unchanged |
| Permission resource types (if added, e.g. `agent::scripts`) | `backend/app/core/resource_types.py` **AND** `frontend/src/constants/resourceTypes.ts` *(modify both — required by manifest rule)* | `MODULE_GROUPS` in both files |
| Execution-mode selector on Agent Type form | **removed** — `frontend/src/pages/agents/AgentTypeForm.tsx` + `frontend/src/pages/agents/AgentManagementPage.tsx` contain no mode UI or `/scripts/execution-modes` persistence; `frontend/src/__tests__/execution-mode-selector.test.tsx` deleted; `agents.executionMode` i18n keys removed | i18next locale files; `useDialogErrorHandler.ts` pattern |
| Agent Type detail dialog — **Scripts tab** *(implemented — replaces the former standalone scripts page; PRD A1–A4 / spec N8, C1)* | `frontend/src/components/agents/AgentScriptsTab.tsx` *(new — per script: version history with `repaired_from` lineage badges, lifecycle/health chips, description, promote (target select) / retire actions, verifications/fallbacks/repairs lists)* mounted at tab index 4 of `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` *(Details=0, Preview=1, Logs=2, Sessions=3 conversation-only, Scripts=4 always; errors surface via the parent dialog's `dialogError` + `PermissionDeniedAlert` pattern)*; hooks in `frontend/src/hooks/useScripts.ts` *(unchanged — no mode queries; `useScriptRepairs` kept)*; types in `frontend/src/types/scripts.ts`; i18n keys **moved from `admin.scripts.*` to `agents.scripts.*`** in `frontend/src/i18n/locales/en.json` *(plus `agents.types.scriptsTab`)*. **No standalone `/admin/scripts` route or nav entry** — governance surface is the dialog per PRD A3 / spec C1 | `frontend/src/constants/resourceTypes.ts`, i18n resources; consumes existing CC REST APIs (`/api/v1/scripts`) — REST surface unchanged (A4) |
| **DELETE — standalone Scripts module** *(deleted)* | `frontend/src/pages/scripts/ScriptsPage.tsx` and `ScriptDetailDrawer.tsx` removed; `/admin/scripts` route + import removed from `frontend/src/app/AppRouter.tsx`; `nav.scripts` entry + `CodeIcon` import removed from `frontend/src/app/AppShell.tsx`; `frontend/src/__tests__/script-registry-page.test.tsx` deleted; `admin.scripts.*` + `nav.scripts` keys purged from `frontend/src/i18n/locales/en.json` after key migration | i18next locale files |
| Plan-step script links (E4a) *(implemented)* | `backend/app/services/script_registry/service.py` *(new `link_plan_steps_to_version` — stamps `script_definition_id`/`script_version_id` onto matching `AgentPlan.plan_steps` entries when a version is compiled from the definition's source plan; called from `backend/app/api/v1/internal/scripts.py` `submit_candidate` and `backend/app/api/v1/scripts.py` `create_script_version`)*; plan response schema `backend/app/schemas/agents.py` `PlanStepRead` *(new optional `script_definition_id`/`script_version_id`)*; frontend `frontend/src/types/index.ts` `PlanStep` + `frontend/src/components/agents/AgentPlanContent.tsx` *(script link per script-backed step; optional `onOpenScript` prop — `AgentTypeDetailsDialog` switches to the Scripts tab)* | `agents.py` models/schemas, frontend plan views |
| Backend unit tests | `backend/tests/` — `test_script_compiler.py` *(add compilability-analysis cases)*, `test_script_runner.py` *(add session-binding/identity-parity cases)*, `test_verification_engine.py`, `test_fallback_controller.py` → `test_script_first_dispatcher.py` *(unconditional fallback + bounded repair-retry)*, `test_script_registry_service.py` *(add `RepairAttempt`)*, `test_repair_loop.py` *(new — defect diagnosis → repaired candidate → re-verify → bounded retry)*, `test_script_mcp_only_boundary.py` *(new — scripts limited to MCP tool calls + local processing)* *(new)* | fixtures for `AgentType`, `ConversationSession` |
| Backend API tests | `backend/tests/` — `test_scripts_api.py` *(mode endpoints removed; repair-attempt listings)*, `test_internal_scripts_api.py` *(mode endpoint removed; serving-version + repairs endpoints)* *(new)* | certificate-auth test utilities (agent-instance cert rejection on `/internal/*`) |
| Security / segregation tests | `backend/tests/test_script_security_invariants.py` *(new)* | static source assertions (no DB access in AR script modules), permission-path parity |
| Migration test | `backend/tests/test_script_registry_migration.py` *(new)* | structural assertions on the migration source (tables, `create_type=False`, reversible downgrade) |
| Frontend tests | `frontend/src/__tests__/` — agent-type Scripts tab tests *(new — moved from the standalone page; to be (re)written against `AgentScriptsTab.tsx`)*; `frontend/src/__tests__/script-registry-page.test.tsx` — **deleted** with the standalone page; `frontend/src/__tests__/execution-mode-selector.test.tsx` — **deleted** alongside the selector | Vitest setup, i18n test wrapper |
| E2E test | `e2e/tests/` — `workflow-compilation.spec.ts` *(new)* | existing e2e harness |
| OTEL instrumentation | `backend/app/agent_runtime/scripts/` + CC/CH middleware telemetry *(modify)* | existing OTEL setup (`config/telemetry.yaml` consumers) |
| Master docs | `docs/master/architecture/` + `docs/master/data-model/` per architecture.md §5 / data-model.md §5 *(modify + new `modules/workflow-compilation.md`)* | — |

---

## Interface Sketches (illustrative only)

```python
# Step graph (Pydantic v2, Agent Runtime)
class StepKind(str, Enum):
    TOOL_CALL = "tool_call"
    TRANSFORM = "transform"
    SEMANTIC_BRIDGE = "semantic_bridge"   # model-backed
    DECISION = "decision"                 # model-backed (System One)
    OUTPUT = "output"

class ScriptStep(BaseModel):
    kind: StepKind
    model_backed: bool = False
    # tool_call: tool name reference only — permission + token stay delegated
    # decision: confidence carried into downstream inputs

class StepGraph(BaseModel):
    steps: list[ScriptStep]
    comparison_tolerance: ComparisonTolerance
```

```python
# Lifecycle (Control Center registry service)
class ScriptLifecycle(str, Enum):
    DRAFT = "draft"; VERIFIED = "verified"; COMPILED = "compiled"; RETIRED = "retired"

# Execution modes removed: script-first with unconditional LLM fallback is fixed behavior.

class RepairAttempt(BaseModel):
    fallback_event_id: str
    defect_diagnosis: str
    diff_applied: str
    repaired_candidate_version: str | None  # must re-verify (V1) before promotion
    retry_outcome: str
```

No large implementations are included here by design; see implementation-plan.md tasks for build order and done conditions.
