# Tech Spec: Software 3.0 Agent Framework — Workflow Compilation

**Related:** [prd.md](prd.md) · [spec-change.md](spec-change.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md) · [implementation-plan.md](implementation-plan.md)

## Compliance Header (top_priority_rules)

- **3 services fully segregated** — new components live strictly inside their service: compiler/runner/verification/fallback in Agent Runtime; registry/modes/audit/cost in Control Center; provenance tagging in Communication Hub.
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
| **Script Compiler** (`compiler.py`) | Plan + recorded tool-call sequence → candidate step graph (C1, C2) | Produces candidates only; never promotes or executes |
| **Script Runner** (`runner.py`) | Executes compiled step graphs; tool calls via existing CH client path (`comm_hub_client.py`); output validation per step | Runs under agent identity; fails typed (`ExecutionError`, `SchemaMismatch`, `OutputValidationFailure`) to the Fallback Controller |
| **Verification Engine** (`verification.py`) | Shadow-runs candidates against recorded LLM executions on identical inputs; compares with tolerance; produces verdicts + diffs (V1, V3) | Evidence persisted via CC APIs, never locally |
| **Fallback Controller** (`fallback.py`) | Detects the three failure types, routes to LLM path (except `compiled-only`), records reasons, triggers repair, degrades health via CC (F1–F4) | Never widens permissions during fallback |
| **Execution-mode resolver** (`mode_resolver.py`) | Session-start resolution of mode + current compiled version via CC internal API; graceful degradation to LLM (E1–E3) | Caches per-workflow with short TTL; never reads DB |

Model-backed step invocation reuses existing Semantic Bridge sub-agents and the System One decision tool (`backend/app/services/system_one/`, decision_tools models) — they are called as steps, with structured result + confidence carried downstream (S1–S3).

### Control Center (governance plane) — `backend/app/services/` + `backend/app/api/`

| Component | Location (suggested) | Responsibility |
|---|---|---|
| **Script Registry Service** | `backend/app/services/script_registry/` | Versioning, lifecycle transitions (`draft → verified → compiled → retired`), lineage, health aggregation, evidence storage — the only writer of script tables |
| **Execution Mode Config Service** | within the same package | CRUD for per agent-type/workflow mode settings |
| **Script Audit & Cost Service** | within the same package | Per-execution provenance audit (G2); token-saved computation vs LLM baseline, per workflow and aggregate (G3) |
| **REST API** | `backend/app/api/v1/scripts.py` | Registry CRUD, lifecycle transitions, version diff, health, cost/audit reports (JWT + `require_permission()`) |
| **Internal API** | `backend/app/api/v1/internal/scripts.py` | CC↔AR: mode+version resolution, candidate/evidence submission, fallback/execution-record reporting — service certs only |

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
| `GET /scripts/{id}/versions/{vid}/diff?against={vid2}` | Version diff view |
| `POST /scripts/{id}/versions/{vid}/promote` | Lifecycle transition (validated server-side; V4 re-verification rules) |
| `POST /scripts/{id}/versions/{vid}/demote` / `/retire` | Operator lifecycle control (C3) |
| `GET /scripts/{id}/verifications` | Verification evidence (V2) |
| `GET /scripts/{id}/fallbacks` | Fallback events with reasons (F2) |
| `GET /scripts/{id}/health` | Health status + recent fallback trend (F4) |
| `PUT /agent-types/{id}/execution-mode` | Set mode per agent type/workflow (E1) |
| `GET /reports/compilation` | Compilation rate, script hit rate, fallback rate (G4) |
| `GET /reports/cost-savings` | Tokens saved vs LLM baseline, per workflow + aggregate, residual model usage (G3) |

All request/response bodies are Pydantic v2 models; all routes wrapped with `require_permission()` against the new resource type (see below).

### Internal CC↔AR endpoints (`/api/v1/internal/scripts/...`)

Certificate rules (existing middleware, unchanged): **agent-instance certs are blocked from `/internal/*`**; AR calls these endpoints with its **service certificate** (same pattern as Communication Hub today).

| Endpoint | Direction | Purpose |
|---|---|---|
| `GET /internal/scripts/mode?agent_type_id=&workflow=` | AR ← CC | Resolve execution mode + current compiled script version |
| `POST /internal/scripts/candidates` | AR → CC | Submit candidate step graph (draft version) |
| `POST /internal/scripts/verifications` | AR → CC | Submit verification evidence + verdict request |
| `POST /internal/scripts/fallbacks` | AR → CC | Report fallback event (reason, version, detail) |
| `POST /internal/scripts/executions` | AR → CC | Report script execution record (mode, outcome, duration, tools, model-backed steps, tokens saved) |
| `GET /internal/scripts/llm-reference/{session_id}` | AR ← CC | Fetch recorded LLM execution inputs/outputs for shadow comparison |

Permission resolution for script tool calls reuses the existing CC permission API unchanged.

---

## Data Access Patterns

Per data-model.md entities. **All access is through Control Center** (sole DB gateway); AR and CH never open a DB connection.

| Entity | Written by | Read by | Path |
|---|---|---|---|
| `ScriptDefinition` | CC registry service (on AR candidate submission or operator action) | CC REST (UI/audit), AR (via internal mode/resolve APIs) | AR → CC internal API → CC service → DB |
| `ScriptVersion` | CC registry service | CC REST (diff, evidence), AR (compiled content via internal API) | same |
| `VerificationRun` | CC registry service (evidence submitted by AR Verification Engine) | CC REST (audit), repair loop in AR via internal read | same |
| `FallbackEvent` | CC registry service (reported by AR Fallback Controller) | CC REST (health, audit, notifications) | same |
| `ScriptExecutionRecord` | CC registry service (reported by AR after each compiled/fallback run) | CC REST (audit, cost reports, dashboard) | same |
| `ExecutionModeConfiguration` | CC (operator via REST / Agent Type UI) | AR (via internal mode resolution), CC REST | same |
| Existing `AgentType`, `AgentPlan` | unchanged | CC registry service (ownership/lineage joins) | CC only |
| Existing `ConversationSession`, `ExecutionLogEntry`, `ToolCallRecord` | unchanged writers | CC audit joins execution records to sessions/tool calls | CC only |

Provenance metadata on tool calls (`script` vs `llm`, script version) flows AR → CH on each call and is persisted by CH into its audit trail via its existing CC delegation — no new permission checks.

---

## Code Reference Map

| New component / file | Location | Touches (existing files) |
|---|---|---|
| ScriptDefinition, ScriptVersion, VerificationRun, FallbackEvent models | `backend/app/db/models/script_registry.py` *(new)* | `backend/app/db/models/__init__.py` (exports), `agents.py` (`AgentType`, `AgentPlan` FK relationships) |
| ScriptExecutionRecord, ExecutionModeConfiguration models | `backend/app/db/models/script_execution.py` *(new)* | `backend/app/db/models/__init__.py`, `conversations.py` (`ConversationSession`), `agents.py` (`AgentJob`) |
| Alembic migration | `backend/alembic/versions/<rev>_script_registry_and_execution.py` *(new)* | Migration chain head; follows AGENTS.md migration rules (ENUM `create_type=False`, reversible downgrade) |
| StepGraph schemas, Compiler, Runner, Verification Engine, Fallback Controller, mode resolver | `backend/app/agent_runtime/scripts/` *(new package: `schemas.py`, `compiler.py`, `runner.py`, `verification.py`, `fallback.py`, `mode_resolver.py`)* | `backend/app/agent_runtime/comm_hub_client.py` (tool calls), `metadata_client.py` / `data_client.py` (CC clients — extend with script endpoints), `main.py` (wiring), LangChain agent loop in `backend/app/services/agents/` (plan + recorded tool-call capture) |
| Semantic Bridge / System One step invocation | within `backend/app/agent_runtime/scripts/runner.py` | `backend/app/services/system_one/`, `backend/app/db/models/decision_tools.py`, `system_one_provider_config.py` |
| Script Registry / Mode Config / Audit & Cost services | `backend/app/services/script_registry/` *(new package)* | `backend/app/db/models/script_registry.py`, `script_execution.py`, `backend/app/services/agents/`, `permission_resolution.py` (pattern reference) |
| CC REST API | `backend/app/api/v1/scripts.py` *(new)* | `backend/app/api/v1/__init__.py` (router registration), `backend/app/api/deps.py` (auth deps), `backend/app/schemas/` (new Pydantic v2 schemas, e.g. `schemas/scripts.py`) |
| CC internal API | `backend/app/api/v1/internal/scripts.py` *(new)* | existing `backend/app/api/v1/internal/` package; certificate middleware in `backend/app/middleware/` (agent-instance certs blocked from `/internal/*`) |
| CH provenance tagging | `backend/app/communication_hub/services/` + `backend/app/communication_hub/mcp/` *(modify)* | tool-call audit records; permission delegation path unchanged |
| Permission resource types (if added, e.g. `agent::scripts`) | `backend/app/core/resource_types.py` **AND** `frontend/src/constants/resourceTypes.ts` *(modify both — required by manifest rule)* | `MODULE_GROUPS` in both files |
| Execution-mode selector on Agent Type form *(optional)* | `frontend/src/` Agent Type admin component *(modify)* | i18next locale files; `useDialogErrorHandler.ts` pattern |
| Script registry admin page *(optional)* | `frontend/src/pages/` or `frontend/src/components/` (new, following Agent Outputs / Agent Data page pattern) | `frontend/src/constants/resourceTypes.ts`, i18n resources, React Router routes |
| Backend unit tests | `backend/tests/` — `test_script_compiler.py`, `test_script_runner.py`, `test_verification_engine.py`, `test_fallback_controller.py`, `test_script_registry_service.py` *(new)* | fixtures for `AgentType`, `ConversationSession` |
| Backend API tests | `backend/tests/` — `test_scripts_api.py`, `test_internal_scripts_api.py` *(new)* | certificate-auth test utilities (agent-instance cert rejection on `/internal/*`) |
| Frontend tests *(optional)* | `frontend/src/__tests__/` — script registry page / mode selector tests *(new)* | Vitest setup, i18n test wrapper |
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

class ExecutionMode(str, Enum):
    LLM = "llm"; COMPILED_WITH_FALLBACK = "compiled-with-fallback"; COMPILED_ONLY = "compiled-only"
```

No large implementations are included here by design; see implementation-plan.md tasks for build order and done conditions.
