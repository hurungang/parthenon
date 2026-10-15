# Test Plan: Software 3.0 Agent Framework — Workflow Compilation

**Related:** [prd.md](prd.md) · [tech-spec.md](tech-spec.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md)

This plan covers verification of the workflow-compilation capability (C1–C4, V1–V4, E1–E3, F1–F4, S1–S3, G1–G4, SEC1–SEC4) while preserving the `docs/config.yaml` `top_priority_rules`: fully segregated services, agents/scripts only in Agent Runtime, only Control Center touches the database, and no sensitive data in agent/script hands.

---

## 1. Test Strategy

- **Unit-first on the AR compilation package.** The Script Compiler, Script Runner, Verification Engine, Fallback Controller, and mode resolver are deterministic components with typed failure modes — ideal for isolated unit tests with mocked CH client and CC clients.
- **Service-contract testing for CC.** The Script Registry / Mode Config / Audit & Cost services and the REST + internal APIs are tested via API-level tests, with emphasis on permission gating (`require_permission()`), lifecycle state-machine validation, and certificate rules (agent-instance certs rejected from `/internal/*`).
- **Invariant testing for security segregation.** Dedicated tests assert that compiled scripts traverse the same integrations → CH → CC permission path as agent tool calls, hold no credentials, and never open DB connections. These run at unit, API, and e2e levels.
- **Behavioral parity via shadow verification.** Verification is tested with recorded LLM reference executions and `comparison_tolerance`; determinism (100% parity, PRD success metric) is asserted on identical inputs.
- **End-to-end happy path + fallback paths in Playwright.** One e2e spec drives the full lifecycle: LLM run → candidate generation → verification → promotion → compiled run → forced fallback → repair cycle → audit/cost visibility.
- **Frontend component tests with i18next test wrapper** for the optional admin pages (registry page, execution-mode selector), asserting `t()` usage and permission-based rendering.
- **Test pyramid / tooling:** backend pytest (async), frontend Vitest, Playwright e2e; migration verified per AGENTS.md (`alembic upgrade head` before backend tests, since new tables/ENUMs ship in this change).

---

## 2. Coverage Areas

| Area | PRD refs | Level |
|---|---|---|
| StepGraph schema validation (step kinds, `model_backed`, `comparison_tolerance`, tool refs by name only) | C1, S3 | Unit |
| Script Compiler: plan + recorded tool-call sequence → candidate graph; compiler never promotes/executes | C1, C2 | Unit |
| Compilation-opportunity suggestion from repeated stable tool-call patterns | C4 | Unit |
| Script Runner: step execution, typed failures (`ExecutionError`, `SchemaMismatch`, `OutputValidationFailure`), per-step output validation | E1, F1 | Unit |
| Verification Engine: shadow-run comparison, tolerance handling, verdict + diff evidence | V1, V2, V3 | Unit |
| Lifecycle transitions draft → verified → compiled → retired; re-verification after repair/schema change | G1, V4, C3 | Unit + API |
| Execution-mode resolution per agent type/workflow; graceful degradation when no verified script | E1–E3 | Unit + API |
| Fallback triggers (script error, schema mismatch, output validation failure), reason capture, repair loop, health degradation | F1–F4 | Unit + API |
| Semantic Bridge and System One decision steps inside compiled graphs; confidence propagation; model-backed marking | S1–S3 | Unit |
| Script registry REST API (CRUD, diff, promote/demote/retire, verifications, fallbacks, health, mode config, reports) | C3, G1–G4 | API |
| Internal CC↔AR endpoints; service-cert-only access; agent-instance cert rejection | SEC4 | API |
| Provenance tagging in CH (`script` vs `llm`, `script_version`) in audit records | G2 | Unit + API |
| Audit records distinguishing script vs LLM runs; cost/token-savings computation vs LLM baseline | G2, G3 | Unit + API |
| Permission enforcement on script tool calls (no bypass, no credentials, no direct DB) | SEC1–SEC3 | Unit + API + e2e |
| Service segregation (AR executes, CC owns DB writes, CH provenance only) | SEC4, top-priority rules | API + e2e |
| Admin UI: script registry page, execution-mode selector; i18next; permission-denied rendering | C3, E1 | Frontend |
| Full lifecycle e2e: compile → verify → promote → compiled run → fallback → repair → reports | all | E2E |
| Alembic migration up/down, ENUM `create_type=False`, reversible downgrade | data-model | Migration |

---

## 3. Critical Scenarios

### Compilation & Script Correctness

- **WHEN** an agent produces an implementation plan containing a repeated tool-call sequence (tool A query → transform → tool B act) **THEN** the compiler produces a candidate StepGraph covering the sequence, with tool references by name only and no credentials/URLs-with-secrets embedded.
- **WHEN** a candidate is compiled from a recorded successful LLM execution's tool-call sequence **THEN** the graph's step order, tool names, and data flow match the recorded run.
- **WHEN** the compiler encounters a plan with a non-deterministic, un-bridgeable step **THEN** no candidate is produced (or candidate is rejected) and the workflow remains `llm` mode — compilation is opportunistic, never forced.
- **WHEN** a StepGraph is submitted with an invalid step kind, a missing output reference, or a tool reference containing a secret-like value **THEN** Pydantic validation rejects it with a typed error.

### Verification & Promotion (shadow-run comparison)

- **WHEN** a draft candidate is shadow-run against the recorded LLM reference on identical inputs and outputs match within `comparison_tolerance` **THEN** the verdict is `match`, evidence (inputs, expected vs actual, outcome) is stored via CC, and the version may be promoted to `verified`.
- **WHEN** shadow-run outputs differ beyond tolerance **THEN** the candidate remains `draft`, a structured diff is recorded (V3), and no compiled version is activated.
- **WHEN** an operator promotes a version that has no passing verification evidence **THEN** the server rejects the promotion with a validation error (V4 / server-side lifecycle validation).
- **WHEN** a tool schema changes after promotion **THEN** the compiled version is flagged for re-verification and is not used until re-verified (schema-mismatch detection leads to fallback in the interim).
- **WHEN** a repaired candidate is submitted **THEN** it becomes a *new* version in `draft`, lineage links back to the prior version and the fallback event, and it must pass verification (V1) before promotion.

### Execution Modes

- **WHEN** mode is `llm` and a verified compiled script exists **THEN** execution still uses the LLM path; no script runs.
- **WHEN** mode is `compiled-with-fallback` (default) and a compiled script exists **THEN** the run executes the script with no LLM calls except model-backed steps; the execution record reports script provenance.
- **WHEN** mode is `compiled-only` and the script fails **THEN** the run fails loudly with the recorded reason — there is **no** silent LLM fallback (F1/E1; PRD risk "degrades loudly").
- **WHEN** any mode is set but no verified script exists **THEN** execution degrades gracefully to LLM without error (E3).
- **WHEN** the mode resolver's CC call fails or its cache TTL expires **THEN** resolution retries/degrades to LLM execution; AR never reads the DB directly.

### Fallback Triggers & Repair Loop

- **WHEN** a script step raises an execution error **THEN** the Fallback Controller classifies it as `ExecutionError`, records reason + context + script version via the CC internal API, and routes to the LLM path (unless `compiled-only`).
- **WHEN** a tool's schema no longer matches the step's expectation **THEN** the typed `SchemaMismatch` triggers fallback, the reason identifies the mismatching tool/field, and re-verification is required for the script.
- **WHEN** a step's output fails validation **THEN** `OutputValidationFailure` triggers fallback with the validation diff recorded.
- **WHEN** the LLM path completes a run after fallback **THEN** a repaired candidate may be produced, enters `draft`, and re-verifies per V1 before promotion — the same version is never silently reused.
- **WHEN** the same script version falls back repeatedly (threshold crossed) **THEN** its health status degrades and an operator notification path is exercised (F4).

### Script Lifecycle

- **WHEN** a script version transitions draft → verified → compiled **THEN** each transition is validated server-side, is auditable, and only the CC registry service writes the tables.
- **WHEN** an operator demotes or retires a compiled version **THEN** subsequent runs fall back (or use LLM per mode), the retired version is excluded from mode resolution, and lineage/history is preserved.
- **WHEN** a retired script's workflow runs again under `compiled-with-fallback` **THEN** behavior is identical to "no verified script exists" (graceful LLM degradation).

### Permission Enforcement & Security Invariants

- **WHEN** a compiled script step invokes a tool **THEN** the call traverses CH with per-call token injection and CC permission resolution exactly like an agent call; a script can never invoke a tool the agent identity/role is not permitted to use (SEC1).
- **WHEN** a script (or its execution context) is inspected **THEN** it contains no credentials, identity tokens, or DB connection material (SEC2, SEC3) — including in verification artifacts and diffs.
- **WHEN** AR reports/receives registry state **THEN** it uses only CC internal APIs with its service certificate; **WHEN** an agent-instance certificate calls `/internal/scripts/*` **THEN** it is rejected (SEC4, existing middleware).
- **WHEN** fallback occurs **THEN** permissions are never widened — the LLM path uses the same agent identity/permissions (Fallback Controller boundary).

### Semantic Bridge & System One Steps in Compiled Workflows

- **WHEN** a compiled graph contains a `semantic_bridge` step **THEN** the existing Semantic Bridge sub-agent is invoked, unstructured input converts to typed registry fields, and the structured result feeds downstream steps.
- **WHEN** a compiled graph contains a `decision` step **THEN** the System One decision tool is invoked, and its structured answer **and confidence** are carried into downstream step inputs (S2).
- **WHEN** a compiled run includes model-backed steps **THEN** those steps are marked `model_backed` in the execution record, and cost reporting shows residual model usage separately (S3, G3).

### Governance, Audit & Cost

- **WHEN** a script run and an LLM run complete for the same workflow **THEN** audit records distinguish mode, script version, and fallback events per execution (G2), with CH-tagged provenance (`script` vs `llm`).
- **WHEN** compiled executions accumulate **THEN** cost-savings reports compute tokens saved vs the LLM baseline per workflow and aggregate, excluding residual model-backed usage from savings (G3).
- **WHEN** the compilation report endpoint is queried **THEN** compilation rate, script hit rate, and fallback rate are returned (G4).

### Service Segregation Invariants

- **WHEN** any script execution occurs **THEN** it runs only inside Agent Runtime; no compiler/runner/verification code paths exist in CC or CH.
- **WHEN** any script-related table is written **THEN** the writer is a CC service only; AR and CH hold no DB sessions (assert via connection/diagnostic checks).
- **WHEN** CH handles a script-provenance tool call **THEN** protocol, permission delegation, and token injection are unchanged — only provenance metadata is added.

### UI (optional admin pages, i18next)

- **WHEN** a permitted operator opens the script registry page **THEN** versions, lifecycle status, health, verification evidence, and fallback reasons render; diff view compares two versions.
- **WHEN** an operator promotes/demotes/retires from the UI **THEN** the lifecycle action is sent, errors surface via the dialog error-handling pattern (`dialogError` + `PermissionDeniedAlert`, per AGENTS.md convention).
- **WHEN** a user without `agent::scripts` (or equivalent) permission opens the page or actions **THEN** permission-denied placeholders render instead of 403 crashes.
- **WHEN** the execution-mode selector is changed on the Agent Type form **THEN** the mode persists and is reflected in subsequent mode resolution.
- **WHEN** any new UI text renders **THEN** it resolves through i18next `t()` in all supported locales (no hardcoded strings); locale keys exist in both locale files.

---

## 4. Edge Cases

- Script overfit to one observed run: legitimate input variation at runtime → output validation catches it and falls back with reason (never silently wrong results).
- Shadow-run comparison exactly at the `comparison_tolerance` boundary (inclusive vs exclusive semantics).
- Concurrent runs of the same workflow while a version is promoted/retired mid-flight (in-flight run completes on the old version; next session resolves the new one).
- Two candidates for the same workflow submitted concurrently — registry enforces one active compiled version.
- Empty/zero-step graph, single-step graph, graph with only model-backed steps (savings ≈ 0 — must be reported honestly).
- Circular or self-referencing step dependencies rejected at schema validation.
- Mode set to `compiled-only` before any verification exists → run fails loudly with a clear reason, not a crash.
- Fallback occurs and the LLM path *also* fails — both failures recorded; repair candidate not produced from a failed reference.
- Fallback Controller's CC-report call fails (CC down): fallback still proceeds on the LLM path; report is retried/queued without blocking the user run.
- Tool renamed or removed from the MCP hub → schema-mismatch fallback, health degradation, no crash loop.
- Schema drift wave: many scripts invalidated by one MCP server update — each degrades independently; no cascading CC overload (batching/rate of fallback reports).
- `llm-reference/{session_id}` lookup for a session with no recorded execution → verification cannot proceed; candidate stays `draft` with an explanatory verdict.
- Model-backed step returns low/zero confidence from System One → confidence still propagates downstream; downstream steps handle it per tolerance.
- Retired script version requested via mode resolution cache before TTL expiry → stale cache must not resurrect a retired version (cache invalidated on lifecycle change or short TTL proven).
- Unicode/large payloads through transform steps; output validation on size limits.
- Lifecycle API abuse: promote a `retired` version, retire a `draft` version → 4xx with state-machine error.
- Verification artifacts containing redacted content — assert no tokens/secrets even when the source run contained sensitive-looking strings.
- Migration edge: ENUM created via model import (`create_type=False`), downgrade path clean; `alembic downgrade -1` then `upgrade head` round-trips.
- i18next: missing translation key falls back to default locale rather than rendering the raw key on the new admin pages.

---

## 5. Acceptance Criteria Checklist

### Compilation (C1–C4)
- [ ] Candidate bridge script generated from implementation plan (C1)
- [ ] Candidate derivable from recorded tool-call sequence of a successful LLM run (C2)
- [ ] Operators can view, compare, promote, demote, retire versions in the registry UI (C3)
- [ ] Stable repeated tool-call patterns flagged as compilation candidates (C4)

### Verification & Promotion (V1–V4)
- [ ] Shadow-run comparison against LLM reference on identical inputs; only matches promote (V1)
- [ ] Verification evidence (inputs, expected/actual, outcome) retained and auditable (V2)
- [ ] Mismatched candidates stay `draft` with recorded diff (V3)
- [ ] Versions re-verify after repair or tool-schema change (V4)

### Execution Modes (E1–E3)
- [ ] Mode configurable per agent/workflow: `llm` / `compiled-with-fallback` / `compiled-only` (E1)
- [ ] `compiled-with-fallback` is the default for eligible workflows (E2)
- [ ] No verified script → graceful degradation to LLM in all modes (E3)

### Fallback & Repair (F1–F4)
- [ ] Fallback triggers on script error, schema mismatch, and output validation failure (F1)
- [ ] Every fallback records reason, context, and script version (F2)
- [ ] Fallback under `compiled-with-fallback` completes via LLM and can produce a repair candidate requiring re-verification (F3)
- [ ] Repeated fallbacks degrade health status and can notify operators (F4)

### Semantic Bridge & Decision (S1–S3)
- [ ] Semantic Bridge invocable inside compiled step sequences (S1)
- [ ] System One decision tool invocable with answer + confidence carried downstream (S2)
- [ ] Model-backed steps marked and visible in run records (S3)

### Governance, Audit & Cost (G1–G4)
- [ ] Registry with versioning, lifecycle statuses, owning workflow, lineage (G1)
- [ ] Audit distinguishes script vs LLM runs with mode, version, fallback events (G2)
- [ ] Token-savings reporting per workflow and aggregate, with residual model usage (G3)
- [ ] Dashboard surfaces compilation rate, hit rate, fallback rate, cumulative savings (G4)

### Security (SEC1–SEC4)
- [ ] Scripts run under agent identity; cannot invoke unpermitted tools (SEC1)
- [ ] Scripts cannot bypass tool permissions, hold credentials, or touch the DB directly (SEC2)
- [ ] Script content and verification artifacts contain no sensitive data (SEC3)
- [ ] Services remain segregated: execution in AR, registry/DB in CC, provenance in CH (SEC4)

### Success Metrics (measurable)
- [ ] 100% output parity between verified script runs and verification reference on identical inputs
- [ ] Compiled execution share ≥ 60% on compiled workflows; fallback rate trend visible
- [ ] ≥ 70% LLM token-spend reduction vs pre-compilation baseline on compiled workflows (measurable in cost report)
- [ ] Latency reduction ≥ 50% measurable for compiled runs
- [ ] Zero security-policy violations attributable to scripts; 100% of fallback events carry a reason
- [ ] Repair cycles converge (no version falls back repeatedly without repair)

### Quality / Conventions
- [ ] Alembic migration applied and reversible; backend restarted before API tests
- [ ] New resource type registered in BOTH `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` (no wildcard-permission 403s)
- [ ] All new UI text via i18next `t()`; dialog error-handling standard followed
- [ ] Pydantic v2 / SQLAlchemy 2 async / Python Enums strong typing throughout
- [ ] OTEL spans/metrics emitted from compiler, runner, verification, fallback, and provenance tagging

---

## 6. Test File References

All paths follow `docs/config.yaml` `source.tests`. No test code here — planned files only.

### Backend unit tests — `backend/tests/`
- `backend/tests/test_script_compiler.py` — plan/tool-call-sequence → StepGraph compilation; validation rejections; C4 candidate suggestion
- `backend/tests/test_script_runner.py` — step execution, per-step output validation, typed failures, model-backed step invocation (Semantic Bridge + System One), tool calls via CH client
- `backend/tests/test_verification_engine.py` — shadow-run comparison, tolerance boundaries, verdicts + diffs, evidence payloads
- `backend/tests/test_fallback_controller.py` — the three trigger types, reason capture, `compiled-only` no-fallback, repair-candidate triggering, health degradation, permission invariance during fallback
- `backend/tests/test_mode_resolver.py` — E1–E3 resolution, TTL cache, graceful degradation, no-DB-access assertion
- `backend/tests/test_script_registry_service.py` — lifecycle state machine, versioning/lineage, health aggregation, evidence storage, cost/token-savings computation (G3)

### Backend API tests — `backend/tests/`
- `backend/tests/test_scripts_api.py` — REST `/api/v1/scripts/*` CRUD, promote/demote/retire validation, diff, verifications/fallbacks/health, mode config, reports; JWT + `require_permission()` gating; new resource type authorization (incl. wildcard permission sanity)
- `backend/tests/test_internal_scripts_api.py` — CC↔AR internal endpoints; service-cert accepted, **agent-instance cert rejected** on `/internal/*`; candidate/evidence/fallback/execution reporting; LLM-reference fetch

### Security / segregation tests — `backend/tests/`
- `backend/tests/test_script_security_invariants.py` — SEC1–SEC4: no credential leakage in scripts/artifacts, permission-path parity with agent calls, AR/CH never open DB connections, permission never widened on fallback

### Migration test — `backend/tests/`
- `backend/tests/test_script_registry_migration.py` (or covered by CI alembic round-trip) — upgrade/downgrade of the script registry & execution migration; ENUM `create_type=False`

### Frontend tests — `frontend/src/__tests__/`
- `frontend/src/__tests__/script-registry-page.test.tsx` — registry list, version diff view, lifecycle actions, permission-denied rendering, dialog error handling, i18next keys
- `frontend/src/__tests__/execution-mode-selector.test.tsx` — mode selector on Agent Type form, persistence, i18n coverage

### E2E tests — `e2e/tests/`
- `e2e/tests/workflow-compilation.spec.ts` — full lifecycle: LLM run → candidate → verification → promotion → compiled run provenance → forced fallback (schema mismatch) → repair → re-verify → reports/audit visible in UI; compiled-only loud-failure path; admin page permission gating

### MCP demo app tests — `mcp-demo-app/tests/`
- `mcp-demo-app/tests/script-provenance.spec.ts` (if the demo harness exercises MCP tool calls) — provenance metadata (`script`/`llm`, `script_version`) visible on externally-invoked tool calls without protocol change

---

*End of test plan. Traceability: each Critical Scenario maps to ≥1 acceptance-criteria item and ≥1 referenced test file.*
