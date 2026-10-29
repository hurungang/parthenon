# Test Plan: Software 3.0 Agent Framework — Workflow Compilation

**Related:** [prd.md](prd.md) · [tech-spec.md](tech-spec.md) · [architecture.md](architecture.md) · [data-model.md](data-model.md)

This plan covers verification of the workflow-compilation capability (A1–A5, C1–C4, V1–V4, E1–E10 incl. E4a, F1–F4, S1–S3, G1–G4, SEC1–SEC4, N8/N9) while preserving the `docs/config.yaml` `top_priority_rules`: fully segregated services, agents/scripts only in Agent Runtime, only Control Center touches the database, and no sensitive data in agent/script hands.

**Refinement note (scripts UI + invocation contract):** scripts are **agent-owned functions** — the standalone `/admin/scripts` module is REMOVED. Governance visibility lives entirely in the **Scripts tab of the Agent Type detail dialog** (N8/A1–A4: version lineage incl. `repaired_from`, lifecycle, health, description, promote/retire, verifications/fallbacks/repairs). A **standardized invocation contract** (N9/A5) governs execution: identity context is **always** passed — the script executes as the agent, with the agent's dual identities and resolved permissions, never its own. Backend registry/execution APIs are unchanged; they serve the dialog. Plan-review additionally shows **script links on script-backed plan steps** (E4a/C3).

**Earlier refinement note:** execution modes are REMOVED — script-first dispatch is the single fixed platform strategy with unconditional LLM fallback; there is no mode configuration, no mode resolution, and no loud-failure (`compiled-only`) behavior anywhere in the system. Coverage previously mapped to modes is now mapped to E1–E3 (fixed strategy), plan-time compilability analysis (E4–E6), session-bound identity parity (E7), the MCP-only script boundary (E8), and the bounded self-improvement repair loop (E9–E10).

---

## 1. Test Strategy

- **Unit-first on the AR compilation package.** The Script Compiler, Script Runner, Script-First Dispatcher, Verification Engine, and Repair Loop are deterministic components with typed failure modes — ideal for isolated unit tests with mocked CH client and CC clients.
- **Service-contract testing for CC.** The Script Registry / Audit & Cost services (with `RepairAttempt` management) and the REST + internal APIs are tested via API-level tests, with emphasis on permission gating (`require_permission()`), lifecycle state-machine validation, and certificate rules (agent-instance certs rejected from `/internal/*`).
- **Invariant testing for security segregation and boundaries.** Dedicated tests assert that compiled scripts traverse the same integrations → CH → CC permission path as agent tool calls, hold no credentials, never open DB connections, and are **MCP-only** (static source analysis: no direct network, filesystem-outside-sandbox, DB, or other I/O in script execution contexts — E8). These run at unit, API, and e2e levels.
- **Identity-parity testing via the CH client path.** Because scripts execute MCP calls through the same `comm_hub_client.py` path as agents (E7), parity is assertable: every script-originated CH call is checked to carry the same dual identities (user-realm human + agent-realm OIDC agent principal) as the owning agent session, with no separate or anonymous identity.
- **Behavioral parity via shadow verification.** Verification is tested with recorded LLM reference executions and `comparison_tolerance`; determinism (100% parity, PRD success metric) is asserted on identical inputs.
- **Repair-loop testing as a first-class cycle.** The self-improvement loop (defect diagnosis → `RepairAttempt` record + `repaired_from` lineage → re-verification → bounded retry → exhaustion triggers unconditional fallback) is tested end-to-end at unit and API level with a bounded attempt budget.
- **End-to-end happy path + fallback visibility in Playwright.** One e2e spec drives the full lifecycle: LLM run → candidate generation → verification → promotion → script-first run → forced fallback with visible reason → repair cycle → audit/cost visibility. There is **no** mode-persistence journey.
- **Frontend component tests with i18next test wrapper** for the **Agent Type detail dialog's Scripts tab** (script list with description + lifecycle + lineage; promote/retire actions; verifications/fallbacks/repairs views; **negative assertion: no standalone `/admin/scripts` route or nav entry exists**), asserting `t()` usage and permission-based rendering.
- **Invocation-contract testing (N9/A5).** Script execution is tested as a contract: the runner **always** receives and validates identity context (dual identities + resolved permissions) at invocation and **refuses identity-less execution before any step runs** (covered and kept in `backend/tests/test_script_runner.py`); script MCP calls carry the agent's identities (SEC1 parity), never a script-specific identity.
- **Test pyramid / tooling:** backend pytest (async), frontend Vitest, Playwright e2e; migrations verified per AGENTS.md (`alembic upgrade head` before backend tests), including the follow-up migration that drops `ExecutionModeConfiguration` (data-model.md §1.7/§4).

---

## 2. Coverage Areas

| Area | PRD refs | Level |
|---|---|---|
| StepGraph schema validation (step kinds, `model_backed`, `comparison_tolerance`, tool refs by name only) | C1, S3 | Unit |
| Script Compiler: plan + recorded tool-call sequence → candidate graph; compiler never promotes/executes | C1, C2 | Unit |
| **Plan-time compilability analysis: each plan step marked `scriptable` vs `model-backed`; compilation-eligible only when steps are scriptable; conversational/interactive agents never compiled (no script produced)** | E4, E5, E6 | Unit |
| Compilation-opportunity suggestion from repeated stable tool-call patterns | C4 | Unit |
| **Invocation contract (A5/N9): script execution always carries session identity context; runner refuses identity-less execution before any step; script executes with the agent's permissions (SEC1 parity)** | A5, N9, E7, SEC1 | Unit |
| Script Runner: step execution, typed failures (`ExecutionError`, `SchemaMismatch`, `OutputValidationFailure`), per-step output validation, **session-bound execution with identity parity on every CH call** | E1, E7, F1 | Unit |
| **Computed-data transform ops: `count`, `pluck` (field column), `merge` (objects/arrays), `sum` (numeric field), `first`, `last` — plus type-validation failures on wrong input shapes** | E1 | Unit |
| **Script execution-log shipping: run start (version, step count), per-step completion (name/kind, truncated outcome brief), model-backed step events, completion, failure entries; a broken log shipper never breaks the run** | E1, F1 | Unit |
| **Markdown rendering of session results: GFM tables render via remark-gfm; strings render as markdown** | — | Frontend |
| **Script-First Dispatcher (fixed strategy): verified script exists → script runs automatically; none exists → LLM path without error; ANY script failure → unconditional LLM fallback, run always completes** | E1, E2, E3 | Unit |
| **Self-improvement repair loop: defect diagnosis → `RepairAttempt` recorded (diagnosis, diff, retry outcome) → repaired candidate (`repaired_from` lineage) re-verified → bounded retry → exhaustion falls back unconditionally** | E9, E10, F3 | Unit + API |
| Verification Engine: shadow-run comparison, tolerance handling, verdict + diff evidence | V1, V2, V3 | Unit |
| Lifecycle transitions draft → verified → compiled → retired; re-verification after repair/schema change | G1, V4, C3 | Unit + API |
| Fallback triggers (script error, schema mismatch, output validation failure), reason capture, health degradation | F1, F2, F4 | Unit + API |
| Semantic Bridge and System One decision steps inside compiled graphs; confidence propagation; model-backed marking | S1–S3 | Unit |
| Script registry REST API (CRUD, diff, promote/demote/retire, verifications, fallbacks, **repair listings**, health, reports — **no mode endpoints**) | C3, E10, G1–G4 | API |
| Internal CC↔AR endpoints (incl. `POST/GET /internal/scripts/repairs`); service-cert-only access; agent-instance cert rejection | SEC4 | API |
| Provenance tagging in CH (`script` vs `llm`, `script_version`) in audit records | G2 | Unit + API |
| Audit records distinguishing script vs LLM runs (no mode attribute); repair attempts in audit; cost/token-savings computation vs LLM baseline | E10, G2, G3 | Unit + API |
| **MCP-only boundary: scripts limited to MCP tool calls + local data processing; static analysis proves no direct network/filesystem/DB I/O; non-MCP external access attempts blocked/rejected** | E8, SEC2 | Unit (static) + e2e |
| Permission enforcement on script tool calls (no bypass, no credentials, no direct DB) | SEC1–SEC3 | Unit + API + e2e |
| Service segregation (AR executes, CC owns DB writes, CH provenance only) | SEC4, top-priority rules | API + e2e |
| **Agent-Type detail dialog — Scripts tab: scripts owned by the agent type render with description + lifecycle + version lineage (incl. `repaired_from`) + health; promote/retire actions from the tab; verifications/fallbacks/repairs views; i18next; permission-denied rendering; negative assertion: no standalone `/admin/scripts` route/nav** | A1–A4, C3, N8, E10, F2 | Frontend |
| **Plan review shows script links on script-backed plan steps, opening into the Scripts tab (E4a)** | E4a, C3 | Frontend + E2E |
| Full lifecycle e2e: compile → verify → promote → script-first run → fallback visibility → repair → reports, driven **from the Agent-Type dialog Scripts tab** (no registry-page journey, no `/admin/scripts` route) | all | E2E |
| Alembic migration up/down incl. **follow-up drop-`ExecutionModeConfiguration` migration**, ENUM `create_type=False`, reversible downgrade | data-model | Migration |

---

## 3. Critical Scenarios

### Compilation & Script Correctness

- **WHEN** an agent produces an implementation plan containing a repeated tool-call sequence (tool A query → transform → tool B act) **THEN** the compiler produces a candidate StepGraph covering the sequence, with tool references by name only and no credentials/URLs-with-secrets embedded.
- **WHEN** a candidate is compiled from a recorded successful LLM execution's tool-call sequence **THEN** the graph's step order, tool names, and data flow match the recorded run.
- **WHEN** the compiler encounters a plan with a non-deterministic, un-bridgeable step **THEN** no candidate is produced (or candidate is rejected) — compilation is opportunistic, never forced, and the LLM path simply continues to serve the workflow (E3).
- **WHEN** a StepGraph is submitted with an invalid step kind, a missing output reference, or a tool reference containing a secret-like value **THEN** Pydantic validation rejects it with a typed error.

### Plan-Time Compilability Analysis (E4–E6)

- **WHEN** an agent generates an implementation plan **THEN** every plan step is marked either `scriptable` (deterministic tool calls + local data transformation) or `model-backed` (semantic bridging, System One judgment, or interactive input) at plan time (E4).
- **WHEN** a plan contains at least one un-scriptable step and no model-backed invocation can cover it **THEN** the workflow is marked not compilation-eligible and no candidate script is generated (E5).
- **WHEN** a conversational or interactive agent produces a plan **THEN** the agent produces no script and the workflow is never compiled — regardless of how deterministic its steps appear (E6).
- **WHEN** a plan with model-backed steps that can be embedded as invocations (Semantic Bridge / decision tool) is analyzed **THEN** the workflow remains compilation-eligible with those steps marked `model_backed` in the graph (E5, S3).

### Script-First Dispatch & Unconditional Fallback (E1–E3)

- **WHEN** a verified compiled script exists for a workflow **THEN** execution automatically runs the script path with no configuration and no operator selection; the execution record reports script provenance and version (E1).
- **WHEN** no verified script exists (or the version is retired) **THEN** execution uses the LLM path by default without error (E3).
- **WHEN** the script fails for ANY reason (execution error, schema mismatch, output validation failure, repair exhaustion) **THEN** fallback to the LLM path is unconditional and the run completes via the LLM path — a run never fails solely because a script failed (E2, F1–F3).
- **WHEN** the dispatcher's CC lookup for the serving version fails **THEN** execution degrades to the LLM path; AR never reads the DB directly (SEC4).
- **WHEN** a script step raises an execution error **THEN** the Dispatcher classifies it as `ExecutionError`, records reason + context + script version via the CC internal API, and routes to the LLM path — there is no "loud failure" path for any mode, because no modes exist.

### Script Execution Logging & Derived Data (E1)

- **WHEN** a script run starts **THEN** an execution log entry is shipped with the script version and step count; each step completion ships an entry with step name/kind and a truncated outcome brief (never full payloads for large results); completion ships a duration summary (best-effort — logging failures never break the run).
- **WHEN** a model-backed step (semantic bridge / decision) executes **THEN** a dedicated execution log event makes the script↔LLM segment iteration visible in the session log stream, and the dispatcher ships a fallback entry on script→LLM handoff.
- **WHEN** a transform step uses a computed-data op (`count`, `pluck`, `merge`, `sum`, `first`, `last`) **THEN** the derived value is stored deterministically in the context for subsequent steps without a model; wrong input shapes raise typed `OutputValidationFailure` and trigger unconditional fallback.
- **WHEN** a script path produces a string result **THEN** the session output carries the raw rendered text (no JSON envelope at the result level), and the frontend renders it as markdown with GFM support (tables, task lists).

### Session Binding & Identity Parity (E7, SEC1)

- **WHEN** a compiled script executes an MCP tool call **THEN** the call is made via the same CH client path (`comm_hub_client.py`) as agent tool calls and carries the **same dual identities** (user-realm human + agent-realm OIDC agent principal) as the owning agent session (E7, SEC1).
- **WHEN** script-originated CH calls are inspected (test assertion on the CH client request) **THEN** identity claims are byte-identical in kind to the agent's own calls — no separate, anonymous, or script-specific identity is ever introduced (E7).
- **WHEN** a script runs as a post-repair retry **THEN** it binds to the same agent session; identity parity holds across the repair loop, keeping the audit trail unbroken (E7, G2).
- **WHEN** a script step attempts to invoke a tool the agent identity/role is not permitted to use **THEN** the call is rejected by the existing permission path exactly as an agent call would be (SEC1).

### MCP-Only Script Boundary (E8, SEC2)

- **WHEN** script execution code is statically analyzed (source-level assertion test) **THEN** it contains no direct network access, no filesystem access outside the sandbox, no database connections, and no subprocess/other I/O — MCP tool calls plus local data processing are the only capabilities (E8, SEC2).
- **WHEN** a script attempts a non-MCP external access (network socket, DB handle, file write outside sandbox) at runtime **THEN** the attempt is blocked/rejected with a typed boundary violation, the fallback records the reason, and the run still completes via the LLM path (E8, E2).

### Self-Improvement Repair Loop (E9, E10, F3)

- **WHEN** execution fails due to a script defect **THEN** the agent diagnoses the defect and records it — diagnosis, context, and the script version link into the repair cycle (E9, F2).
- **WHEN** a repair candidate is produced **THEN** it is a *new* `ScriptVersion` in `draft` with `repaired_from` lineage, and a `RepairAttempt` record (defect diagnosis, diff applied, retry outcome) is written via CC (E10, F3).
- **WHEN** a repaired candidate is submitted **THEN** it must pass verification (V1 shadow-run comparison) before promotion; the same version is never silently reused (V4, F3).
- **WHEN** the repaired candidate verifies successfully **THEN** it is promoted and the retry of the repaired script executes within execution guardrails (permissions, no credentials, no external access) (E9).
- **WHEN** the bounded repair-attempt budget is exhausted without success **THEN** retry stops, exhaustion triggers unconditional fallback to the LLM path with the reason recorded, and the script's health status degrades (E2, E10, F4).
- **WHEN** the same script version falls back repeatedly (threshold crossed) **THEN** its health status degrades and an operator notification path is exercised (F4).

### Verification & Promotion (shadow-run comparison)

- **WHEN** a draft candidate is shadow-run against the recorded LLM reference on identical inputs and outputs match within `comparison_tolerance` **THEN** the verdict is `match`, evidence (inputs, expected vs actual, outcome) is stored via CC, and the version may be promoted to `verified`.
- **WHEN** shadow-run outputs differ beyond tolerance **THEN** the candidate remains `draft`, a structured diff is recorded (V3), and no compiled version is activated.
- **WHEN** an operator promotes a version that has no passing verification evidence **THEN** the server rejects the promotion with a validation error (V4 / server-side lifecycle validation).
- **WHEN** a tool schema changes after promotion **THEN** the compiled version is flagged for re-verification and is not used until re-verified (schema-mismatch detection leads to fallback in the interim).
- **WHEN** a repaired candidate is submitted **THEN** it becomes a *new* version in `draft`, lineage links back to the prior version and the fallback event, and it must pass verification (V1) before promotion.

### Script Lifecycle

- **WHEN** a script version transitions draft → verified → compiled **THEN** each transition is validated server-side, is auditable, and only the CC registry service writes the tables.
- **WHEN** an operator demotes or retires a compiled version **THEN** subsequent runs fall back to the LLM path (identical to "no verified script exists"), the retired version is excluded from serving-version lookup, and lineage/history is preserved.

### Permission Enforcement & Security Invariants

- **WHEN** a compiled script step invokes a tool **THEN** the call traverses CH with per-call token injection and CC permission resolution exactly like an agent call; a script can never invoke a tool the agent identity/role is not permitted to use (SEC1).
- **WHEN** a script (or its execution context) is inspected **THEN** it contains no credentials, identity tokens, or DB connection material (SEC2, SEC3) — including in verification artifacts, repair diffs, and `RepairAttempt` records.
- **WHEN** AR reports/receives registry state **THEN** it uses only CC internal APIs with its service certificate; **WHEN** an agent-instance certificate calls `/internal/scripts/*` **THEN** it is rejected (SEC4, existing middleware).
- **WHEN** fallback or repair occurs **THEN** permissions are never widened — the LLM path and repair retries use the same agent identity/permissions (Dispatcher/repair-loop boundary).

### Semantic Bridge & System One Steps in Compiled Workflows

- **WHEN** a compiled graph contains a `semantic_bridge` step **THEN** the existing Semantic Bridge sub-agent is invoked, unstructured input converts to typed registry fields, and the structured result feeds downstream steps.
- **WHEN** a compiled graph contains a `decision` step **THEN** the System One decision tool is invoked, and its structured answer **and confidence** are carried into downstream step inputs (S2).
- **WHEN** a compiled run includes model-backed steps **THEN** those steps are marked `model_backed` in the execution record, and cost reporting shows residual model usage separately (S3, G3).

### Governance, Audit & Cost

- **WHEN** a script run and an LLM run complete for the same workflow **THEN** audit records distinguish script vs LLM provenance, script version, fallback events, and repair attempts per execution (G2), with CH-tagged provenance (`script` vs `llm`) and no mode attribute.
- **WHEN** compiled executions accumulate **THEN** cost-savings reports compute tokens saved vs the LLM baseline per workflow and aggregate, excluding residual model-backed usage from savings (G3).
- **WHEN** the compilation report endpoint is queried **THEN** compilation rate, script hit rate, and fallback rate are returned (G4).

### Service Segregation Invariants

- **WHEN** any script execution occurs **THEN** it runs only inside Agent Runtime; no compiler/runner/verification/repair-loop code paths exist in CC or CH.
- **WHEN** any script-related table is written **THEN** the writer is a CC service only; AR and CH hold no DB sessions (assert via connection/diagnostic checks).
- **WHEN** CH handles a script-provenance tool call **THEN** protocol, permission delegation, and token injection are unchanged — only provenance metadata is added.

### Invocation Contract — Identity Context Always Passed (A5/N9, SEC1)

- **WHEN** a script is invoked by the runner **THEN** the invocation always carries the session identity context — the agent's dual identities (user-realm human + agent-realm OIDC agent principal) and its resolved permissions; there is no invocation path that omits it (A5, N9).
- **WHEN** the runner is called without identity context (missing `session_id`, `agent_type_id`, or resolved permissions) **THEN** execution is refused before any step runs, with a typed error — an identity-less script execution is impossible (covered and kept in `backend/tests/test_script_runner.py`, referenced here as the contract test) (A5, E7).
- **WHEN** a script executes a tool call **THEN** it executes **as the agent**: it uses the agent's identities and permissions, and its MCP calls traverse the same permission path as agent calls — SEC1 parity; a script can never do anything its owning agent cannot (A5, SEC1).
- **WHEN** the script artifact or its execution context is inspected **THEN** it holds no independent identity, credentials, or permission grants of any kind (A5, SEC2/SEC3).

### UI (Agent-Type detail dialog — Scripts tab, i18next)

- **WHEN** a permitted operator opens the Agent Type detail dialog's Scripts tab **THEN** all scripts owned by that agent type render, each with its **human-readable description**, **lifecycle state** (draft → verified → compiled → retired), **health** (fallback/degradation status), and **version lineage** including `repaired_from` parent links; verification evidence, fallback reasons, and repair attempts are viewable per version; diff view compares two versions (A1, A2, N8, F2, E10).
- **WHEN** an operator promotes/demotes/retires a version from the Scripts tab **THEN** the lifecycle action is sent to the unchanged CC registry API and errors surface via the dialog error-handling pattern (`dialogError` + `PermissionDeniedAlert`) (C3, A4).
- **WHEN** a user without `agent::scripts` (or equivalent) permission opens the tab or its actions **THEN** permission-denied placeholders render instead of 403 crashes.
- **WHEN** the frontend route table and navigation are inspected **THEN** **no standalone `/admin/scripts` route or navigation entry exists** (negative assertion — A3/N8).
- **WHEN** a reviewer opens an implementation plan containing script-backed steps (E4a/C3) **THEN** each such step displays a link to its script that opens it in the agent type's Scripts tab for review of content, description, and lineage.
- **WHEN** any new UI text renders **THEN** it resolves through i18next `t()` in all supported locales (no hardcoded strings); locale keys exist in both locale files.

---

## 4. Edge Cases

- Script overfit to one observed run: legitimate input variation at runtime → output validation catches it and falls back with reason (never silently wrong results).
- Shadow-run comparison exactly at the `comparison_tolerance` boundary (inclusive vs exclusive semantics).
- Concurrent runs of the same workflow while a version is promoted/retired mid-flight (in-flight run completes on the old version; next run resolves the new one).
- Two candidates for the same workflow submitted concurrently — registry enforces one active compiled version.
- Empty/zero-step graph, single-step graph, graph with only model-backed steps (savings ≈ 0 — must be reported honestly); a plan whose steps are all model-backed → not compilation-eligible (E5).
- Conversational agent whose plan steps *look* deterministic → still never compiled (E6 boundary).
- Fallback occurs and the LLM path *also* fails — both failures recorded; repair candidate not produced from a failed reference.
- Repair attempt budget boundary: exactly at the last permitted attempt vs one-past — the one-past attempt must be refused and exhaustion fallback triggered (E10).
- Concurrent repair episodes on the same script — `RepairAttempt` records stay ordered and attributable; no double-promotion of two repaired candidates.
- Script-First Dispatcher's CC-report call fails (CC down): fallback still proceeds on the LLM path; report is retried/queued without blocking the user run.
- Tool renamed or removed from the MCP hub → schema-mismatch fallback, health degradation, no crash loop.
- Schema drift wave: many scripts invalidated by one MCP server update — each degrades independently; no cascading CC overload (batching/rate of fallback reports).
- `llm-reference/{session_id}` lookup for a session with no recorded execution → verification cannot proceed; candidate stays `draft` with an explanatory verdict.
- Model-backed step returns low/zero confidence from System One → confidence still propagates downstream; downstream steps handle it per tolerance.
- Script-originated CH call observed with missing/mutated identity claims → identity-parity assertion fails loudly in tests; runtime treats it as a boundary violation (E7).
- Script attempts MCP call for a tool removed from its permission set after compilation → permission rejection, fallback, no privilege resurrection.
- Unicode/large payloads through transform steps; output validation on size limits.
- Lifecycle API abuse: promote a `retired` version, retire a `draft` version → 4xx with state-machine error.
- Verification artifacts and repair diffs containing redacted content — assert no tokens/secrets even when the source run contained sensitive-looking strings.
- Migration edge: ENUM created via model import (`create_type=False`), downgrade path clean; `alembic downgrade -1` then `upgrade head` round-trips — including the drop-`ExecutionModeConfiguration` migration restoring the prior schema on downgrade.
- i18next: missing translation key falls back to default locale rather than rendering the raw key on the Scripts tab.
- Agent type with zero scripts → Scripts tab renders an empty state (no scripts yet), not an error.
- Script with deep repair lineage (multiple `repaired_from` hops) renders the full chain; cyclic lineage links are impossible (lineage is a DAG — assert server-side and in the tab).
- Invocation contract edge: runner invoked with identity context present but empty resolved-permissions set → executes, but every tool call is permission-rejected (agent with no grants → script with no grants).

---

## 5. Acceptance Criteria Checklist

### Compilation (C1–C4)
- [ ] Candidate bridge script generated from implementation plan (C1)
- [ ] Candidate derivable from recorded tool-call sequence of a successful LLM run (C2)
- [ ] Operators can view, compare, promote, demote, retire versions **in the Scripts tab of the Agent Type detail dialog** (C3)

### Agent-Owned Scripts & Invocation Contract (A1–A5)
- [ ] Scripts tab lists scripts owned by the agent type with description, lifecycle, health, and version lineage incl. `repaired_from` (A1, A2)
- [ ] No standalone `/admin/scripts` route or nav entry exists — negative assertion (A3)
- [ ] CC registry REST APIs unchanged; they serve the dialog (A4)
- [ ] Script invocation always carries identity context; runner refuses identity-less execution before any step (A5, N9)
- [ ] Script executes with the agent's identities and permissions — SEC1 parity; no script-owned identity/credentials/grants (A5, SEC1–SEC2)
- [ ] Stable repeated tool-call patterns flagged as compilation candidates (C4)

### Verification & Promotion (V1–V4)
- [ ] Shadow-run comparison against LLM reference on identical inputs; only matches promote (V1)
- [ ] Verification evidence (inputs, expected/actual, outcome) retained and auditable (V2)
- [ ] Mismatched candidates stay `draft` with recorded diff (V3)
- [ ] Versions re-verify after repair or tool-schema change (V4)

### Automatic Economical Execution (E1–E3)
- [ ] Verified script exists → script path runs automatically, no configuration (E1)
- [ ] Any automation failure → unconditional LLM fallback; run always completes; never fails solely because a script failed (E2)
- [ ] No verified script → LLM path by default without error (E3)

### Plan-Time Compilability Analysis (E4–E6)
- [ ] Each plan step marked `scriptable` or `model-backed` at plan-generation time (E4)
- [ ] Compilation-eligible only when steps are scriptable; model-backed steps only as embedded invocations (E5)
- [ ] Conversational/interactive agents never compiled; no script produced (E6)
- [ ] Plan review shows script links on script-backed steps, opening in the Scripts tab (E4a)

### Session-Bound Execution (E7)
- [ ] Script MCP calls use the same dual identities as the agent session, asserted via the CH client path (E7)
- [ ] No separate/anonymous script identity exists (E7, SEC1)

### MCP-Only Boundary (E8)
- [ ] Scripts limited to MCP tool calls + local processing; static analysis test passes (E8)
- [ ] Non-MCP external access attempts blocked/rejected with recorded reason (E8, E2)

### Self-Improvement Repair Loop (E9–E10)
- [ ] Script defect → agent repairs and retries within execution guardrails (E9)
- [ ] Each attempt records diagnosis, diff, and retry outcome; bounded budget; exhaustion triggers unconditional fallback (E10)

### Fallback & Repair (F1–F4)
- [ ] Fallback triggers on script error, schema mismatch, and output validation failure (F1)
- [ ] Every fallback records reason, context, and script version (F2)
- [ ] Fallback completes via LLM and produces a repair candidate requiring re-verification (F3)
- [ ] Repeated fallbacks degrade health status and can notify operators (F4)

### Semantic Bridge & Decision (S1–S3)
- [ ] Semantic Bridge invocable inside compiled step sequences (S1)
- [ ] System One decision tool invocable with answer + confidence carried downstream (S2)
- [ ] Model-backed steps marked and visible in run records (S3)

### Governance, Audit & Cost (G1–G4)
- [ ] Registry with versioning, lifecycle statuses, owning workflow, lineage (incl. `repaired_from`) (G1)
- [ ] Audit distinguishes script vs LLM runs with version, fallback events, repair attempts — no mode attribute (G2)
- [ ] Token-savings reporting per workflow and aggregate, with residual model usage (G3)
- [ ] Dashboard surfaces compilation rate, hit rate, fallback rate, cumulative savings (G4)

### Security (SEC1–SEC4)
- [ ] Scripts run under agent identity; cannot invoke unpermitted tools (SEC1)
- [ ] Scripts cannot bypass tool permissions, hold credentials, or touch the DB directly (SEC2)
- [ ] Script content, verification artifacts, and repair diffs contain no sensitive data (SEC3)
- [ ] Services remain segregated: execution in AR, registry/DB in CC, provenance in CH (SEC4)

### Success Metrics (measurable)
- [ ] 100% output parity between verified script runs and verification reference on identical inputs
- [ ] Compiled execution share ≥ 60% on compiled workflows; fallback rate trend visible
- [ ] ≥ 70% LLM token-spend reduction vs pre-compilation baseline on compiled workflows (measurable in cost report)
- [ ] Latency reduction ≥ 50% measurable for compiled runs
- [ ] Zero security-policy violations attributable to scripts; 100% of fallback events carry a reason
- [ ] Repair cycles converge (no version falls back repeatedly without repair); bounded repair (E9–E10) resolves defects without operator intervention in the majority of cases
- [ ] Eligibility accuracy: scriptable-marked workflows compile/verify at a high rate; conversational/interactive agents never compiled (E4–E6)

### Quality / Conventions
- [ ] All Alembic migrations applied and reversible — including the follow-up drop-`ExecutionModeConfiguration` migration; backend restarted before API tests
- [ ] `ExecutionModeConfiguration` removed (model + migration + APIs + UI) — verified by tests; no mode endpoints in OpenAPI
- [ ] New resource type registered in BOTH `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` (no wildcard-permission 403s)
- [ ] All new UI text via i18next `t()`; dialog error-handling standard followed
- [ ] Pydantic v2 / SQLAlchemy 2 async / Python Enums strong typing throughout
- [ ] OTEL spans/metrics emitted from compiler, runner, verification, dispatcher, and repair loop (incl. `script.repair_attempt`, `script.compilability_verdict`); no mode-resolver spans

---

## 6. Test File References

All paths follow `docs/config.yaml` `source.tests`. Status legend: **executed** = run locally and passing; **written-only** = created but not executed locally.

### Backend unit tests — `backend/tests/` *(all executed & passing)*
- `backend/tests/test_script_compiler.py` — **executed** (28 passed): plan/tool-call-sequence → StepGraph compilation; validation rejections; decision-tool detection; SEC3 secret rejection; compiler never promotes/executes; **plan-time compilability analysis (`analyze_compilability`): `scriptable` vs `model-backed` marks, eligibility verdicts, conversational/HITL agents produce no script (`never_compiled`)** (C1, C2, E4–E6, SEC3)
- `backend/tests/test_script_runner.py` — **executed** (34 passed): step execution, provenance tagging, per-step output validation, typed failures, **computed-data transform ops (`count` on arrays/objects + scalar rejection, `pluck` column extraction + non-array rejection, `merge` objects/arrays + mismatched-type rejection, `sum` numeric field + non-array rejection, `first`/`last` elements + empty/non-array rejections)**, model-backed telemetry; **execution-log shipping (best-effort CC log shipping): start entry (script version, step count), per-step completion entries (step name/kind, truncated outcome brief), dedicated `script_model_backed_step` entries for semantic-bridge/decision steps, `script_run_failed` on typed failure, broken shipper never breaks the run**; session-bound execution: missing `session_id`/`agent_type_id` refused before any step; identity parity asserted on every CH client call; no script-specific identity introduced — this is the canonical **invocation-contract** test (A5/N9): identity context always passed, identity-less execution refused, SEC1 permission parity (E1, E7, F1, S1–S3, SEC1/SEC2)
- `backend/tests/test_verification_engine.py` — shadow-run comparison, tolerance boundaries (inclusive), verdicts + diffs, evidence payloads, reference extraction (V1–V3) *(pre-existing, unchanged)*
- `backend/tests/test_script_first_dispatcher.py` *(replaced `test_fallback_controller.py`, deleted)* — **executed** (16 passed): fixed script-first strategy, serving-version lookup (absent → LLM without error; registry failure degrades to LLM; short-TTL cache), unconditional fallback on all three trigger types, reason capture, **no mode parameter / no `compiled-only` loud-failure path anywhere (asserted absent)**, repair handoff, permission invariance (E1–E3, F1–F2, F4)
- `backend/tests/test_repair_loop.py` *(new)* — **executed** (10 passed): deterministic defect diagnosis → `report_repair` (diagnosis, diff, attempt number) → re-verification gating (only verified/compiled candidates serve) → bounded retry (`MAX_REPAIR_ATTEMPTS = 2`) → exhaustion reports `exhausted` and stays on LLM; CC failures never block the user run (E9, E10, F3)
- `backend/tests/test_script_mcp_only_boundary.py` *(new)* — **executed** (88 passed): static source assertions (no sockets/requests/DB/subprocess/eval/open in all six AR script execution modules); runtime rejection of network-target tool references and credential-shaped fields with typed `ExecutionError` (E8, SEC2)
- `backend/tests/test_script_registry_service.py` — **executed** (31 passed): lifecycle state machine (V4), verification evidence (V1–V3), fallback + health thresholds (F2, F4), **`record_repair_attempt` persistence (RepairAttempt + `repaired_from` lineage + repaired draft candidate) and outcome updates (E10, F3)**, **`link_plan_steps_to_version` (E4a): matching plan steps stamped with `script_definition_id`/`script_version_id`, plans without compilation / without a source plan unchanged, already-linked steps never re-stamped**, cost report (G3, G4 — pollution-safe delta assertions); **no mode CRUD methods, no `ExecutionModeConfiguration` model, no `execution_mode` column**; in-memory SQLite

### Backend API tests — `backend/tests/`
- `backend/tests/test_scripts_api.py` — **executed** (25 passed): REST `/api/v1/scripts/*` CRUD, promote/retire 409s, diff, verifications/fallbacks/health, **repair listings (`GET /scripts/{id}/repairs` present + permission-gated 403)**, reports, `require_permission()` gating incl. 403; **mode endpoints asserted absent from routes and OpenAPI** (C3, E10, G1–G4). *Testing found a production bug — the REST `create_script_version` route referenced an undefined `definition` in the E4a plan-link call (`NameError` on every version create); fixed by fetching the definition before `link_plan_steps_to_version`. Re-test hardening: the `seeded` fixture now commits before the request runs, and `_bypass_auth` also passes through `TenantResolutionMiddleware` so unit tests stay in single-tenant mode instead of binding the dev database's root tenant.*
- `backend/tests/test_internal_scripts_api.py` — **executed** (21 passed): CC↔AR internal endpoints; candidates/verifications/fallbacks/executions; **repairs (`POST /internal/scripts/repairs` with new `script_version_id`/`defect_diagnosis`/`attempt_number` payload → RepairAttempt + repaired draft; `GET /internal/scripts/repairs` listing)**; **serving-version lookup (no mode attribute in response; empty for non-compiled workflows)**; LLM-reference fetch; no-cert 401 and **agent-instance cert 403** via the real CA (SEC4)

### Security / segregation tests — `backend/tests/`
- `backend/tests/test_script_security_invariants.py` — **executed** (19 passed): SEC1–SEC4: no credential leakage in candidates/artifacts/**repair reports**, permission-path parity (identity parity on every CH call — E7), **identity parity across the repair loop**, AR script modules contain no DB access (static source assertions), fallback/repair reports carry no secrets

### Migration tests — `backend/tests/`
- `backend/tests/test_script_registry_migration.py` — **executed**: base migration table list updated (`execution_mode_configurations` removed from `EXPECTED_TABLES`); **follow-up `b2c3d4e5f6a7` assertions: drop in `upgrade()`, restore in `downgrade()`, `repair_attempts` + `repaired_from_id` added**
- `backend/tests/test_drop_execution_mode_migration.py` *(new)* — **executed** (12 passed): structural assertions on revision `b2c3d4e5f6a7`: `upgrade()` drops `execution_mode_configurations` + `execution_mode` column, adds `repair_attempts`/`repaired_from_id`/`identity_parity_confirmed`; `downgrade()` fully restores; `create_type=False` enums; no parameterized DDL; full alembic up/down round-trip (`alembic upgrade head`) remains CI/PostgreSQL work per AGENTS.md

### Backend regression impact
- `backend/tests/unit/test_resource_type_manifest.py` — **updated & executed**: manifest-count assertions raised 27→28 entries / 14→15 agent submodules for the new `agent::scripts` resource type

### Frontend tests — `frontend/src/__tests__/` (Vitest) *(executed & passing)*
- `frontend/src/__tests__/MarkdownRenderer.test.tsx` — **executed** (3 passed): `MarkdownRenderer` component — GFM table rendering via `remark-gfm`, inline/block markdown (headings, code, lists), plain-text pass-through without markdown artifacts (output-as-rendered-text contract, A4)
- `frontend/src/__tests__/agent-type-scripts-tab.test.tsx` — **executed** (13 passed): Scripts tab of the Agent Type detail dialog — scripts owned by the agent type render with **description + lifecycle + version lineage incl. `repaired_from` + health**, verification/fallback/repair views (diagnosis, retry outcome, diff) + empty states, **promote/retire actions from the tab** (asserted request payloads), action errors surfaced through the dialog `onError` (`dialogError`) standard, i18next key usage + `en.json` locale coverage; **negative assertion: no standalone `/admin/scripts` route or nav entry exists**; **plan-review rendering shows script links on script-backed steps and opening one switches the dialog to the Scripts tab (E4a)** (A1–A4, C3, E4a, N8, E10, F2)
- `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` — **updated & executed** (24 passed): tab assertions raised 3→4 tabs; asserts the Scripts tab always targets panel index 4 (conversation agents get a Sessions tab at index 3). *Testing found a production bug — the Scripts `Tab` had no `value`, so MUI assigned it index 3 for typed agents while its `TabPanel` expects index 4 (clicking Scripts rendered nothing); fixed with an explicit `value={4}`.* Also added the missing `agents.plan.stepTypes.semantic_bridge`/`decision` locale keys surfaced by the plan-review tests.

### E2E tests — `e2e/tests/` (Playwright/Chromium against the built frontend preview, API traffic mocked via `page.route()`) *(executed & passing)*
- `e2e/tests/agent-type-scripts-tab.spec.ts` *(rewritten from `workflow-compilation.spec.ts` registry-list/drawer journeys; that spec is removed)* — **executed** (8 passed): full script-first visibility journey driven **from the Agent Type detail dialog's Scripts tab** — script list with description/lifecycle/health (G1, A1), version lineage with `repaired_from` + verification evidence + fallback reason (V2, F2, A2), repair-attempt history after fallback (E10, F3), promote with asserted request payload (C3, V4), retire; **plan review shows script links on script-backed steps and opening one lands in the Scripts tab (E4a)**; permission-gated promote via the dialog error pattern without crash (SEC); **absence of any `/admin/scripts` route or nav entry asserted end-to-end (A3)**

### MCP demo app tests — `mcp-demo-app/tests/`
- `mcp-demo-app/tests/script-provenance.spec.ts` — **not created** (demo harness does not exercise MCP tool calls; no harness present to test against)

---

*End of test plan. Traceability: each Critical Scenario maps to ≥1 acceptance-criteria item and ≥1 referenced test file.*
