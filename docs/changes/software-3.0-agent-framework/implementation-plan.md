# Implementation Plan: Software 3.0 Agent Framework — Workflow Compilation

**Related:** [prd.md](prd.md) · [spec-change.md](spec-change.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md) · [tech-spec.md](tech-spec.md)

## Overview

This plan implements the Software 3.0 workflow-compilation capability: agents' recurring workflows are compiled into verified deterministic bridge scripts that execute in Agent Runtime without an LLM, with LLM fallback and repair when scripts fail. Work is sequenced so that the Control Center–owned registry foundation lands first, Agent Runtime compilation/execution components follow, and governance, cost tracking, and optional frontend admin complete the capability — all within the top-priority rules (3 segregated services; scripts/agents run only in Agent Runtime; only Control Center touches the DB; scripts never hold credentials/tokens).

## Task Checklist

### Phase 1 — Schema & Registry Foundation (Control Center)
- [ ] 1.1 — New DB models: script_registry.py (ScriptDefinition, ScriptVersion, VerificationRun, FallbackEvent)
- [ ] 1.2 — New DB models: script_execution.py (ScriptExecutionRecord, ExecutionModeConfiguration)
- [ ] 1.3 — Extend agents.py relationships & model exports
- [ ] 1.4 — Alembic migration (autogenerate + review + apply)
- [ ] 1.5 — Script Registry service in Control Center (CRUD, lifecycle, lineage, health)

### Phase 2 — Script Compiler & Runner (Agent Runtime)
- [ ] 2.1 — Declarative step-graph schema (Pydantic v2)
- [ ] 2.2 — Script Compiler
- [ ] 2.3 — Script Runner
- [ ] 2.4 — Model-backed step invocation (Semantic Bridge / System One decision)
- [ ] 2.5 — Execution-mode resolver

### Phase 3 — Verification & Promotion
- [ ] 3.1 — Verification Engine (shadow-run + comparison)
- [ ] 3.2 — Verification evidence persistence via CC registry APIs
- [ ] 3.3 — Promotion / rejection lifecycle transitions

### Phase 4 — Fallback & Repair Loop
- [ ] 4.1 — Fallback Controller
- [ ] 4.2 — Fallback event recording & script health degradation
- [ ] 4.3 — Repair loop (LLM-produced candidate re-verification)

### Phase 5 — APIs, Governance & Cost Tracking (Control Center)
- [ ] 5.1 — Registry REST API (CRUD, versioning, lifecycle transitions)
- [ ] 5.2 — Internal CC↔AR endpoints (mode resolution, candidate/evidence submission)
- [ ] 5.3 — Script provenance tagging in Communication Hub
- [ ] 5.4 — Audit & cost reporting endpoints
- [ ] 5.5 — Permission resource types & manifest registration

### Phase 6 — Frontend Admin (optional / minimal)
- [ ] 6.1 — Execution-mode selector on Agent Type UI
- [ ] 6.2 — Script registry admin page
- [ ] 6.3 — Script health & cost dashboard cards

### Phase 7 — Tests & Observability
- [ ] 7.1 — Backend unit tests (compiler, runner, verification, fallback)
- [ ] 7.2 — API tests (registry CRUD, internal endpoints, cert access rules)
- [ ] 7.3 — OTEL instrumentation (spans, metrics)
- [ ] 7.4 — E2E happy-path test (compile → verify → compiled run → fallback)
- [ ] 7.5 — Master docs update

## Phase 1 — Schema & Registry Foundation (Control Center)

### 1.1 — New DB models: `backend/app/db/models/script_registry.py`
Create SQLAlchemy 2 (async, declarative, typed) models `ScriptDefinition`, `ScriptVersion`, `VerificationRun`, `FallbackEvent` exactly as specified in data-model.md §1.1–1.3, §1.5: lifecycle status enums (`draft/verified/compiled/retired`), Python Enums (strong typing), lineage FKs to AgentType/AgentPlan, health status, parent-version link, immutable versions.

**Done when:** models import cleanly; `ScriptDefinition` ↔ `ScriptVersion` ↔ `VerificationRun`/`FallbackEvent` relationships resolve; no credential/token-shaped fields exist (SEC3); file follows the one-domain-per-file pattern.

### 1.2 — New DB models: `backend/app/db/models/script_execution.py`
Create `ScriptExecutionRecord` (mode, outcome, duration, tools invoked, model-backed steps, session reference, tokens-saved estimate) and `ExecutionModeConfiguration` (`llm` / `compiled-with-fallback` / `compiled-only` per agent-type/workflow pair) per data-model.md §1.4, §1.6.

**Done when:** both models resolve relationships to `ConversationSession`/`AgentJob` without altering those classes; enums are typed.

### 1.3 — Extend `backend/app/db/models/agents.py` and exports
Add one-to-many relationships on `AgentType` → ScriptDefinitions and `AgentPlan` → script lineage (backward references only, no structural change). Export all new models from `backend/app/db/models/__init__.py`.

**Done when:** existing agents.py classes otherwise unchanged; imports in `__init__.py` succeed; no circular imports.

### 1.4 — Alembic migration
Run `python -m alembic revision --autogenerate -m "script registry and execution tables"`, review the generated file in `backend/alembic/versions/` (down_revision chain, `postgresql.ENUM(..., create_type=False)`, no parameterized DDL, reversible downgrade), then `python -m alembic upgrade head` and verify with `python -m alembic current`. Restart backend.

**Done when:** `alembic current` shows the new head; backend restarts without errors; downgrade is reversible.

### 1.5 — Script Registry service (Control Center)
New service module under `backend/app/services/` (e.g. `script_registry/`) providing versioning, lifecycle transitions (`draft → verified → compiled → retired`, re-verification required after repair/tool-schema change per V4), lineage lookup, health aggregation from fallback events, and CRUD for `ExecutionModeConfiguration`. This is the only code path that reads/writes script tables.

**Done when:** all lifecycle transitions enforced server-side (invalid transitions rejected); health degrades on repeated fallbacks (F4); unit tests cover transitions.

## Phase 2 — Script Compiler & Runner (Agent Runtime)

### 2.1 — Declarative step-graph schema
Pydantic v2 models (in Agent Runtime, e.g. `backend/app/agent_runtime/scripts/`) describing the bridge script: typed step nodes (tool call, transform/filter, semantic-bridge, decision, output), typed inputs/outputs, comparison tolerance, model-backed step markers (S3). No credentials/tokens anywhere in the schema (SEC3).

**Done when:** schema round-trips JSON; tool-call steps reference tools by name only (permission resolution stays delegated); validation rejects unknown step types.

### 2.2 — Script Compiler
Component in Agent Runtime that converts an implementation plan and/or recorded tool-call sequence of a successful LLM run into a candidate step graph (C1, C2). Produces candidates only — never promotes, never executes.

**Done when:** given a recorded tool-call sequence, it emits a valid step graph; output contains no secrets; candidates are submitted to CC registry via internal API (not DB).

### 2.3 — Script Runner
Executes compiled step graphs step-by-step. Every tool call goes through Communication Hub exactly like an agent tool call (same mTLS path, permission resolution via CC, per-call token injection by CH — SEC1/SEC2). Validates outputs; on failure, raises a typed failure to the Fallback Controller.

**Done when:** a compiled script run completes a tool sequence through CH with zero LLM tokens for scriptable steps; runner cannot invoke a tool the agent identity is not permitted for (verify via permission rejection path).

### 2.4 — Model-backed step invocation
Wire semantic-bridge sub-agent and System One decision tool as invocable step types with structured results/confidence carried downstream; mark steps as model-backed in execution telemetry (S1–S3).

**Done when:** a step graph containing a semantic-bridge and a decision step executes; telemetry/execution record lists the model-backed steps used.

### 2.5 — Execution-mode resolver
On session start, resolve mode + current compiled script version per workflow via CC internal API; route to LLM loop, Script Runner, or fallback path; degrade gracefully to LLM when no verified script exists (E1–E3).

**Done when:** all three modes behave per spec; `compiled-only` fails loudly instead of silently falling back; `llm` mode is byte-equivalent with today's behavior.

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

## Phase 4 — Fallback & Repair Loop

### 4.1 — Fallback Controller
Detects script failure (execution error, tool schema mismatch, output validation failure — F1) and switches the run to the LLM agent path except in `compiled-only` mode. Never widens permissions during fallback.

**Done when:** all three trigger types cause fallback under `compiled-with-fallback`; `compiled-only` returns a structured failure; LLM fallback completes the run (F3).

### 4.2 — Fallback event recording & health degradation
Record trigger reason, failure detail, resulting action, script version, and health impact via CC; aggregate into script health status; surface operator notification on degradation (F2, F4).

**Done when:** every fallback produces a linked `FallbackEvent`; repeated fallbacks degrade health status and an operator-visible signal exists.

### 4.3 — Repair loop
On fallback, the LLM path may produce a repaired candidate (new ScriptVersion with parent link) that must pass verification before promotion (F3, V4).

**Done when:** repaired candidates re-enter Phase 3 verification; a repaired version can only serve compiled runs after a successful verification run.

## Phase 5 — APIs, Governance & Cost Tracking (Control Center)

### 5.1 — Registry REST API
JWT-authenticated endpoints under `backend/app/api/v1/` (e.g. `scripts.py`): list/get scripts and versions, lifecycle transitions (promote/demote/retire), version diff, health status. Pydantic v2 request/response schemas; `require_permission()` on every route.

**Done when:** all routes require permission; lifecycle rules enforced; OpenAPI docs generated.

### 5.2 — Internal CC↔AR endpoints
Endpoints under `backend/app/api/v1/internal/` for: resolve execution mode + current compiled script version; submit candidates/verification evidence; report fallback events and execution records. Agent-instance certificates must be blocked from `/internal/*` (only service certs, as with CH); existing certificate middleware enforced.

**Done when:** AR can complete all registry interactions without DB access; a request presenting an agent-instance cert to `/internal/*` is rejected with 403.

### 5.3 — Script provenance tagging (Communication Hub)
Extend CH tool-call bookkeeping: each call carries `script` vs `llm` provenance and script version, recorded in audit trails. Protocol, permission delegation, and per-call token injection unchanged.

**Done when:** CH audit records for script-initiated calls show provenance + version; token/permission behavior identical to agent calls.

### 5.4 — Audit & cost reporting endpoints
Endpoints for per-execution audit (mode, script version, fallback events — G2) and cost reports (tokens saved vs LLM baseline, per workflow and aggregate, with residual model-backed step usage called out — G3, G4).

**Done when:** reports distinguish script vs LLM runs; token-saved estimates aggregate correctly; dashboard consumers can fetch summary metrics.

### 5.5 — Permission resource types & manifest registration
If new resource types are introduced (e.g. `agent::scripts`), register in **BOTH** `backend/app/core/resource_types.py` (ResourceTypeManifest + MODULE_GROUPS) **and** `frontend/src/constants/resourceTypes.ts` (RESOURCE_TYPE_MANIFEST + MODULE_GROUPS submodules).

**Done when:** wildcard `agent::*` holders can access new endpoints without 403; both manifests mirrored; covered by a permission test.

## Phase 6 — Frontend Admin (optional / minimal)

### 6.1 — Execution-mode selector on Agent Type UI *(optional)*
Add mode selection (`llm` / `compiled-with-fallback` / `compiled-only`) to the Agent Type form. All UI strings via i18next `t()`; follow the Dialog Error Handling Standard for the dialog.

**Done when:** mode persists via CC API; no hardcoded strings; error handling follows the standard pattern.

### 6.2 — Script registry admin page *(optional)*
Page listing scripts/versions with lifecycle actions (promote/demote/retire), version diff view, verification evidence, health status. All strings via `t()`.

**Done when:** operator can complete the full lifecycle from the UI; permission-denied states render the PermissionDeniedAlert pattern.

### 6.3 — Script health & cost dashboard cards *(optional)*
Dashboard cards for compilation rate, fallback rate, script hit rate, cumulative token savings (G4).

**Done when:** cards render with permission checks and show data from 5.4 endpoints; strings via `t()`.

## Phase 7 — Tests & Observability

### 7.1 — Backend unit tests
Under `backend/tests/`: compiler (plan/sequence → step graph), runner (step execution, typed failures), verification (match/mismatch/tolerance), fallback (all trigger types), registry service (lifecycle transitions, health).

**Done when:** all new components have unit tests; suite passes via the Vitest-equivalent backend runner used in CI.

### 7.2 — API tests
Registry CRUD permissions, internal endpoints (including agent-instance cert rejection on `/internal/*`), cost/audit endpoints.

**Done when:** permission matrix and certificate access rules covered by tests; all pass.

### 7.3 — OTEL instrumentation
New span attributes (execution mode, script version, fallback reason, model-backed-step usage) and metrics (compilation rate, script hit rate, fallback rate, tokens saved) per architecture.md §3.

**Done when:** traces from a compiled run carry the new attributes; metrics emitted and visible via the OTEL collector config.

### 7.4 — E2E happy path
Under `e2e/tests/`: LLM run → candidate compiled → verified → subsequent run executes via script with zero scriptable-step LLM spend → forced failure falls back with recorded reason → repaired candidate re-verifies.

**Done when:** e2e scenario passes against a running stack.

### 7.5 — Master docs update
Apply the updates listed in architecture.md §5 and data-model.md §5 (`docs/master/`).

**Done when:** all listed master doc files updated, including the new `modules/workflow-compilation.md`.

## Completion Checklist

- [ ] All Alembic migrations generated, reviewed, applied, and reversible
- [ ] Only Control Center connects to PostgreSQL — verified by test
- [ ] Agent-instance certificates rejected from `/internal/*` — verified by test
- [ ] Scripts never hold credentials/tokens; CH injects tokens per tool call — verified by code review + tests
- [ ] Script tool calls use the identical permission path as agent tool calls (SEC1/SEC2)
- [ ] All three execution modes behave per E1–E3
- [ ] Verification evidence retained and auditable (V2)
- [ ] Every fallback carries a recorded reason and script version (F2)
- [ ] New resource types registered in BOTH backend and frontend manifests (if added)
- [ ] All new UI strings go through i18next `t()`
- [ ] OTEL spans/metrics implemented for compilation, fallback, and savings
- [ ] Backend unit, API, and e2e tests pass
- [ ] `docs/master/` documentation updated
