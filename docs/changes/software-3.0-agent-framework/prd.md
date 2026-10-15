# PRD: Software 3.0 Agent Framework — Workflow Compilation

## Problem Statement

Parthenon today operates as a strong "Software 2.0" platform: every agent execution routes through an LLM observe-reason-act loop. This is powerful but carries structural costs that grow with usage:

- **Cost**: every run of the same workflow re-pays full LLM token costs, even when the actual work is deterministic data collection and transformation between tools.
- **Non-determinism**: identical inputs can yield different outputs across runs, undermining repeatability, auditability, and trust in enterprise settings.
- **Latency**: each reasoning step adds model round-trips to every execution.
- **Verification debt**: there is no mechanism by which a previously-proven correct execution can be replayed with confidence.

At the same time, a class of judgment — fuzzy, knowledge-intensive decisions such as "how likely is rain given this environment description?" — is precisely where deterministic code struggles and LLM/System One models excel. The framework needs *both*: deterministic execution where work is scriptable, and model-driven judgment where it is not.

**Software 3.0 thesis**: Software 1.0 is hand-written code; Software 2.0 is LLM-driven agents (powerful but costly, non-deterministic, hard to repeat); Software 3.0 is agents whose work is *compiled into verified deterministic scripts*. The agent is used to **create** the software; the software then runs **without an LLM**, with LLM fallback only when needed.

## Vision & Goals

Parthenon is positioned and extended as a Software 3.0 agent framework. When an agent produces an implementation plan for a workflow, it also attempts to generate a deterministic bridge script between the tools involved. Once that script is generated **and verified** against an LLM execution, subsequent executions run the script purely — no LLM required. The agent becomes real software rather than a per-run LLM agent.

Goals:

1. **Compile, don't re-reason**: recurring workflows execute as verified deterministic scripts by default.
2. **Repeatable, low-cost, deterministic** execution for the scriptable majority of workflow steps.
3. **Preserve LLM strength** for what LLMs are uniquely good at: semantic bridging (unstructured → structured) and System One-style judgment — invoked as first-class steps inside otherwise deterministic workflows.
4. **Safe degradation**: any script failure falls back to the LLM-driven agent path, records the reason, and enables script repair.
5. **Governance and observability**: full registry, versioning, audit, and cost tracking of compiled vs LLM executions.
6. **Zero security regression**: scripts run inside the existing segregated security architecture and can never exceed agent tool permissions.

## Non-Goals

- Replacing the LLM agent loop entirely — LLM execution remains available, and remains the default for un-compiled workflows.
- Requiring every workflow to compile — compilation is opportunistic; workflows that are inherently non-deterministic stay in `llm` mode.
- General-purpose programming: scripts are bridge scripts between permitted tools, not arbitrary user-authored applications.
- Automatic self-healing without governance — script repair produces new candidate versions that must pass verification before promotion.
- Any change to the existing security model, identity topology, or tool permission semantics.
- Vendor-specific model optimization; the framework is model-agnostic.

## Personas

- **Platform Administrator** — governs the script registry: versions, promotion/retirement of compiled scripts, audit of compiled vs LLM runs, and cost dashboards.
- **Agent Operator** — sets the execution mode per agent/workflow (`llm`, `compiled-with-fallback`, `compiled-only`), monitors fallback events and script health.
- **Enterprise Consumer / Business Owner** — benefits silently: repeated workflows become faster, cheaper, and produce identical results; sees execution provenance (compiled script vX vs LLM run).
- **Compliance / Audit** — inspects script versions, verification evidence, run history, and the reason log for every fallback.

## Architecture Context (Existing Foundations)

The Software 3.0 capability composes entirely on Parthenon's existing structure, without weakening it:

- **Security layers** (existing): Control Center, Agent Runtime, and Communication Hub remain fully segregated services; agents never hold credentials, tokens, or database access.
- **Tool access path** (existing): integrations → MCP tool hub → permitted tools; permissions are granted at tool/skill level and resolved by Control Center.
- **Identity** (existing): OIDC dual identities — human users in the user realm, agents as first-class OIDC principals in the agent realm.
- **The Brain**, divided into two parts:
  1. **Semantic Bridge** — sub-agents that convert unstructured data into structured data (e.g., parsing free-text descriptions into typed fields from the Agent Data Type Registry).
  2. **Decision Making** — a decision tool based on the "System One" model: fast, intuitive structured judgment backed by rich knowledge and semantic understanding (e.g., predicting rain likelihood from an environment description). This fills exactly the gap where deterministic code struggles.
- **Script compilation** (NEW — the heart of this change): agents generate, verify, and promote deterministic bridge scripts between tools; verified scripts execute without an LLM.

Conceptually, a compiled workflow step looks like:

```
[plan] ──▶ MCP tool A (query) ──▶ transform/filter ──▶ MCP tool B (act)
                     │                                        │
                     └──▶ Semantic Bridge sub-agent ──────────┴──▶ Decision tool (System One)
```

## Requirements

### Workflow Compilation

- **C1 (Must)** — When an agent generates an implementation plan for a workflow, the system also attempts to generate a candidate deterministic bridge script covering the tool-call sequence (e.g., call MCP tool A to query, transform/filter results, feed MCP tool B, delegate a summary step to a semantic-bridge sub-agent).
- **C2 (Must)** — Candidate scripts are derived from the implementation plan and/or the observed tool-call sequence of a successful LLM execution.
- **C3 (Should)** — Operators can view, compare, and manually promote, demote, or retire script versions from the registry UI.
- **C4 (Could)** — Suggest compilation opportunities proactively: workflows whose recent LLM runs show a stable, repeated tool-call pattern are flagged as good compilation candidates.

### Script Verification & Promotion

- **V1 (Must)** — A candidate script must be verified before use: it is shadow-run (or compared run-for-run) against the LLM execution's output, and only matching executions are promoted to **compiled** status.
- **V2 (Must)** — Verification evidence (inputs, expected vs actual outputs, comparison outcome) is retained and auditable.
- **V3 (Should)** — Mismatching candidates remain in draft status with a recorded diff so the agent (or operator) can repair them.
- **V4 (Should)** — Promoted scripts are versioned; re-verification is required after any repair or tool-schema change.

### Execution Modes

- **E1 (Must)** — Execution mode is configurable per agent and per workflow with three values: `llm` (always LLM), `compiled-with-fallback` (default), and `compiled-only` (never falls back).
- **E2 (Must)** — `compiled-with-fallback` is the platform default for eligible workflows.
- **E3 (Should)** — When no verified script exists, all modes degrade gracefully to LLM execution without error.

### Fallback & Repair

- **F1 (Must)** — Fallback triggers on: script execution error, tool schema mismatch, or output validation failure.
- **F2 (Must)** — Every fallback records the reason and context needed for script repair, and links the fallback event to the script version involved.
- **F3 (Must)** — On fallback under `compiled-with-fallback`, the LLM-driven agent path completes the run and may produce a repaired script candidate that must re-verify (V1) before promotion.
- **F4 (Should)** — Repeated fallbacks on the same script version degrade the script's health status and can notify operators.

### Semantic Bridge & Decision Steps

- **S1 (Must)** — Semantic Bridge sub-agents (unstructured → structured conversion) can be invoked as steps within a workflow, including inside a compiled script's step sequence.
- **S2 (Must)** — The System One decision tool is invocable as a workflow step for judgment-type decisions, with its structured answer and confidence carried into downstream steps.
- **S3 (Should)** — Steps that involve semantic bridging or decision tools are marked as model-backed steps within compiled workflows, so operators can see which parts of a "compiled" run still consume model capacity.

### Governance, Audit & Cost

- **G1 (Must)** — A script registry holds all scripts with versioning, status (draft / verified / compiled / retired), owning workflow, and lineage back to the plan or run that produced them.
- **G2 (Must)** — Audit distinguishes script runs from LLM runs per execution, including mode, script version, and fallback events.
- **G3 (Must)** — Cost tracking reports LLM tokens saved by compiled execution (tokens not consumed versus the equivalent LLM run), per workflow and aggregate.
- **G4 (Should)** — Dashboard surfacing: compilation rate, script hit rate, fallback rate, and cumulative cost savings.

### Security Integration

- **SEC1 (Must)** — Scripts execute within the Agent Runtime under the same identity and permission model as agents; a script can never invoke a tool the corresponding agent identity/role is not permitted to use.
- **SEC2 (Must)** — Scripts can never bypass tool permissions, hold credentials, or access the database directly; tool access flows only through the existing integrations → MCP tool hub → permitted-tools path.
- **SEC3 (Must)** — Script content and verification artifacts never contain sensitive data (identity tokens, database credentials, integration secrets).
- **SEC4 (Must)** — All three backend services remain fully segregated; compilation artifacts are managed by Control Center, execution by Agent Runtime, in line with top-priority rules.

## Success Metrics

- **Compilation rate**: ≥ 40% of eligible recurring workflows have a verified compiled script within 90 days of adoption.
- **Compiled execution share**: ≥ 60% of runs of compiled workflows execute via script (not fallback).
- **Cost reduction**: ≥ 70% reduction in LLM token spend for compiled-workflow executions versus pre-compilation baseline.
- **Determinism**: 100% output parity between verified script runs and their verification reference on identical inputs.
- **Latency**: measurable reduction in end-to-end execution time for compiled workflows (target ≥ 50%).
- **Safety**: zero security-policy violations attributable to scripts; 100% of fallback events carry a recorded reason.
- **Trust**: fallback-triggered repair cycles converge — the same script version does not fall back repeatedly without repair.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scripts overfit to one observed run and break on legitimate input variation | Silent wrong results or high fallback rate | Verification with comparison tolerance; output validation on every run; fallback with reason capture (F1–F3) |
| Tool schema drift invalidates compiled scripts at scale | Waves of fallbacks, cost spike | Schema-mismatch detection as explicit trigger (F1); re-verification requirement (V4); script health alerts (F4) |
| "Compiled" runs still consume model capacity via semantic/decision steps, diluting savings expectations | Misleading cost metrics | Model-backed steps explicitly marked (S3); cost reporting distinguishes residual model usage (G3) |
| `compiled-only` mode used recklessly, causing failed business operations when scripts break | Operational outages | Mode is an explicit, operator-set choice (E1); degrades loudly rather than silently; health status visibility (F4) |
| Verification cost (shadow runs) offsets savings for rarely-used workflows | Net-negative ROI on compilation | Opportunistic compilation targeting stable, repeated patterns (C2, C4) |
| Governance debt: orphaned or stale scripts accumulate | Audit confusion, security surface | Registry lifecycle with retirement status (G1); lineage tracking (G1) |
| Security erosion — scripts perceived as a way "around" the agent sandbox | Trust, compliance | Hard requirement that scripts inherit the agent permission model and never bypass tool permissions (SEC1–SEC4) |

## Dependencies & Constraints

- Builds on existing Parthenon capabilities: MCP tool hub and permissions, skills/SOPs, Agent Data Type Registry, System One decision tools, and OTEL observability.
- Must comply with `docs/config.yaml` top-priority rules: fully segregated backend services; agents only in Agent Runtime; only Control Center touches the database; agents never hold sensitive data.
- Script execution is behavior, not a new permission pathway: no parallel permission system is introduced.
- Related prior change: System One decision skills (`docs/changes/system-one-decision-skills/`) provides the decision-making foundation referenced by S2.
