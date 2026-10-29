# Test Plan: Software 3.0 Agent Framework — Workflow Compilation & Agent-Owned Scripts

**Change:** `software-3.0-agent-framework` · **Source plan:** `docs/changes/software-3.0-agent-framework/test-plan.md`

Module scope: workflow compilation into executable StepGraphs (Script Compiler), script-first dispatch with unconditional LLM fallback, plan-time compilability analysis, session-bound identity parity, MCP-only script boundary, the bounded self-improvement repair loop, verification/promotion lifecycle, and governance UI (Agent Type dialog Scripts tab). Execution-mode configuration is fully removed — no mode endpoints, no mode resolution anywhere.

## Coverage Areas

### 1. Compilation & Compilability Analysis
- Plan / recorded tool-call sequence → candidate StepGraph; tool references by name only, no credentials embedded; compiler never promotes or executes.
- Plan-time compilability: every plan step marked `scriptable` or `model-backed`; eligible only when steps are scriptable; conversational/interactive agents never produce a script; repeated stable tool-call patterns flagged as compilation opportunities.

### 2. Script Runner & Invocation Contract
- Step execution with typed failures (`ExecutionError`, `SchemaMismatch`, `OutputValidationFailure`), per-step output validation, computed-data transform ops (`count`, `pluck`, `merge`, `sum`, `first`, `last`) with type-shape validation.
- Invocation contract (N9/A5): execution always carries session identity context; the runner refuses identity-less execution before any step runs; scripts execute as the agent — SEC1 parity on every Communication Hub call, no script-owned identity or credentials.
- Execution-log shipping is best-effort: start/per-step/model-backed/failure entries; a broken shipper never breaks the run.

### 3. Script-First Dispatch & Unconditional Fallback (fixed strategy — no modes)
- Verified script exists → script path runs automatically; none/retired → LLM path without error; ANY script failure → unconditional LLM fallback, run always completes; no `compiled-only` loud-failure path exists (asserted absent).
- Fallback reasons, context, and script version recorded; repeated fallbacks degrade health status.

### 4. Self-Improvement Repair Loop
- Defect diagnosis → `RepairAttempt` record (diagnosis, diff, retry outcome) → repaired candidate as a NEW version with `repaired_from` lineage → re-verification gate → bounded retry budget → exhaustion triggers unconditional fallback and health degradation. CC failures never block the user run.

### 5. Verification & Lifecycle
- Shadow-run comparison against the recorded LLM reference with `comparison_tolerance` (inclusive boundary); mismatch keeps the candidate `draft` with a structured diff; promotion without passing verification is rejected server-side; re-verification after repair or tool-schema change; lifecycle state machine draft → verified → compiled → retired enforced server-side; one active compiled version per workflow.

### 6. Security & Service Segregation Invariants
- MCP-only boundary: static source analysis proves no direct network/filesystem-outside-sandbox/DB/subprocess I/O in AR script execution modules; runtime attempts blocked with typed boundary violations.
- Permission parity: scripts can never invoke tools the agent identity is not permitted to use; no privilege resurrection after permission-set changes.
- Segregation: execution only in Agent Runtime; only Control Center writes script tables; internal endpoints are service-cert-only (agent-instance certs rejected 403); no sensitive data in scripts, verification artifacts, or repair diffs.
- Audit distinguishes script vs LLM provenance (CH-tagged, no mode attribute); cost/token-savings reporting per workflow and aggregate; compilation report (rate, hit rate, fallback rate).

### 7. Governance UI — Agent Type Dialog Scripts Tab
- Scripts tab lists agent-owned scripts with description, lifecycle, health, version lineage (incl. `repaired_from`), verifications/fallbacks/repairs views; promote/retire actions via the unchanged CC registry API; dialog error-handling standard; i18next coverage.
- Negative assertion: no standalone `/admin/scripts` route or nav entry exists.
- Plan review shows script links on script-backed steps, opening into the Scripts tab (E4a).
- `MarkdownRenderer`: GFM table rendering via remark-gfm; session results render as markdown.
- Migration: drop-`ExecutionModeConfiguration` revision (`b2c3d4e5f6a7`) with clean up/down round-trip.

## Test File References (verified in workspace 2026-10-27)

### Backend (`backend/tests/`) — all files verified present
| File | Coverage |
|---|---|
| `test_script_compiler.py` | Compilation, validation rejections, compilability analysis (C1, C2, E4–E6, SEC3) |
| `test_script_runner.py` | Step execution, transform ops, log shipping, invocation contract / identity parity (E1, E7, F1, SEC1) |
| `test_verification_engine.py` | Shadow-run comparison, tolerance, verdicts/diffs (V1–V3) |
| `test_script_first_dispatcher.py` | Fixed strategy, unconditional fallback, no-mode assertions (E1–E3, F1–F2, F4) |
| `test_repair_loop.py` | Bounded repair cycle, exhaustion fallback (E9, E10, F3) |
| `test_script_mcp_only_boundary.py` | Static + runtime MCP-only boundary (E8, SEC2) |
| `test_script_registry_service.py` | Lifecycle state machine, repair persistence, plan-step linking, cost reports (C3, E4a, E10, G1–G4) |
| `test_scripts_api.py` | REST CRUD, promote/retire 409s, repair listings, permission gating, no mode endpoints (C3, G1–G4) |
| `test_internal_scripts_api.py` | CC↔AR internal endpoints incl. repairs, serving-version lookup, cert gating (SEC4) |
| `test_script_security_invariants.py` | SEC1–SEC4 invariants, identity parity across repair loop |
| `test_script_registry_migration.py`, `test_drop_execution_mode_migration.py` | Base + drop-mode migration structure and round-trip |
| `tests/unit/test_resource_type_manifest.py` | Manifest count incl. `agent::scripts` resource type |

### Frontend (`frontend/src/__tests__/`)
| File | Coverage |
|---|---|
| `AgentTypeDetailsDialog.test.tsx` | Dialog tab structure incl. Scripts tab targeting, plan step-type locale keys |
| `MarkdownRenderer.test.tsx` | GFM tables, markdown rendering contract |
| ~~`agent-type-scripts-tab.test.tsx`~~ | **Referenced by the change plan but NOT present in the workspace** — the dedicated Scripts-tab component test file is missing; its scenario coverage is partially carried by `AgentTypeDetailsDialog.test.tsx` and the E2E spec below. Flagged stale. |

### E2E (`e2e/tests/`)
- `agent-type-scripts-tab.spec.ts` — full script-governance journey from the Scripts tab: list/lineage/verification/fallback/repairs visibility, promote/retire with asserted payloads, plan-step script link navigation, permission-gated promote, and the negative `/admin/scripts` route assertion. **Caveat:** the current `AgentTypeDetailsDialog` implementation and its Vitest suite assert the Scripts tab is *removed* (superseded by the sandboxed-scripting Optimized-Plan / `ScriptViewDialog` journey); this spec should be re-validated against the current UI before being treated as authoritative.

## Notes
- `mcp-demo-app/tests/script-provenance.spec.ts` — intentionally not created (no demo harness for MCP tool calls).
- Overall testing strategy unchanged; this module follows the existing unit-first (deterministic AR components) + API-contract + mocked-Playwright E2E conventions in `testing-strategy.md`.
