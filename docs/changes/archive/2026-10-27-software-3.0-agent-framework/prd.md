# PRD: Software 3.0 Agent Framework — Workflow Compilation

## Problem Statement

Parthenon today operates as a strong "Software 2.0" platform: every agent execution routes through an LLM observe-reason-act loop. This is powerful but carries structural costs that grow with usage:

- **Cost**: every run of the same workflow re-pays full LLM token costs, even when the actual work is deterministic data collection and transformation between tools.
- **Non-determinism**: identical inputs can yield different outputs across runs, undermining repeatability, auditability, and trust in enterprise settings.
- **Latency**: each reasoning step adds model round-trips to every execution.
- **Verification debt**: there is no mechanism by which a previously-proven correct execution can be replayed with confidence.

At the same time, a class of judgment — fuzzy, knowledge-intensive decisions such as "how likely is rain given this environment description?" — is precisely where deterministic code struggles and LLM/System One models excel. The framework needs *both*: deterministic execution where work is scriptable, and model-driven judgment where it is not.

**Software 3.0 thesis**: Software 1.0 is hand-written code; Software 2.0 is LLM-driven agents (powerful but costly, non-deterministic, hard to repeat); Software 3.0 is agents whose work is *compiled into verified deterministic scripts*. The agent is used to **create** the software; the software then runs **without an LLM** whenever a verified script exists, and always degrades to the LLM path when automation fails — there is nothing to configure. Compilation itself is agent-driven and economical: at plan time the agent analyzes which workflow steps are scriptable and which are not, and only workflows whose steps are scriptable (never conversational or interactive agents) are eligible for compilation.

## Vision & Goals

Parthenon is positioned and extended as a Software 3.0 agent framework. When an agent produces an implementation plan for a workflow, it also attempts to generate a deterministic bridge script between the tools involved. Once that script is generated **and verified** against an LLM execution, subsequent executions run the script purely — no LLM required. The agent becomes real software rather than a per-run LLM agent.

Goals:

1. **Compile, don't re-reason**: recurring workflows execute as verified deterministic scripts by default.
2. **Repeatable, low-cost, deterministic** execution for the scriptable majority of workflow steps.
3. **Preserve LLM strength** for what LLMs are uniquely good at: semantic bridging (unstructured → structured) and System One-style judgment — invoked as first-class steps inside otherwise deterministic workflows.
4. **Safe degradation**: any script failure unconditionally falls back to the LLM-driven agent path, records the reason, and enables script self-repair with bounded retry.
5. **Governance and observability**: full registry, versioning, audit, and cost tracking of compiled vs LLM executions.
6. **Zero security regression**: scripts run inside the existing segregated security architecture and can never exceed agent tool permissions.

## Non-Goals

- Replacing the LLM agent loop entirely — LLM execution remains always available as the unconditional fallback and as the default for un-compiled workflows.
- Requiring every workflow or agent to compile — compilation is agent-driven and opportunistic; only agents whose steps are scriptable are eligible, and conversational/interactive agents are never compiled.
- General-purpose programming: scripts are bridge scripts between permitted tools, not arbitrary user-authored applications.
- Automatic self-healing without governance — script repair produces new candidate versions that must pass verification before promotion.
- Any change to the existing security model, identity topology, or tool permission semantics.
- Vendor-specific model optimization; the framework is model-agnostic.

## Personas

- **Platform Administrator** — governs scripts where they live: inside each agent type's detail dialog (Scripts tab), reviewing versions, promotion/retirement, verification evidence, and the human-readable description of what each script does; plus audit of compiled vs LLM runs and cost dashboards. Scripts are owned by the agent type, not administered through a standalone admin module.
- **Agent Operator** — monitors automatic economical execution: fallback events, script health, and agent-driven repair activity.
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
- **C3 (Should)** — Operators can view, compare, and manually promote, demote, or retire script versions from the **Scripts tab of the Agent Type detail dialog** (there is no standalone script admin page — the script registry persists in Control Center and is surfaced through this dialog).
- **C4 (Could)** — Suggest compilation opportunities proactively: workflows whose recent LLM runs show a stable, repeated tool-call pattern are flagged as good compilation candidates.

### Agent-Owned Scripts (Scripts Tab)

Scripts are functions owned by the agent type that produced them — not entries in an admin-managed registry surface.

- **A1 (Must)** — Each script is owned by its agent type. The Agent Type detail dialog gains a **Scripts tab** listing all scripts the agent type will use, across its workflows.
- **A2 (Must)** — Each script in the tab shows its **version history and self-improvement lineage** (each version recording its `repaired_from` parent where applicable, and its lifecycle state: draft → verified → compiled → retired), its **health** (fallback/degradation status), and a **human-readable description** of what the script does.
- **A3 (Must)** — There is **no standalone /admin/scripts module or navigation entry**; scripts are not administered through a dedicated admin page. Governance visibility lives entirely in the agent type detail dialog.
- **A4 (Must)** — Control Center REST APIs for the script registry remain unchanged (versioning, lifecycle promotion, lineage); they serve the Scripts tab dialog rather than a standalone admin surface.

### Standardized Script Invocation Contract

- **A5 (Must)** — Scripts are invoked like functions owned by the agent itself: the invocation contract **always passes identity context** to script execution — the agent's dual identities (user-realm human + agent-realm OIDC agent principal) and its resolved permissions. A script executes **with the agent's identities and permissions, never its own** — scripts hold no independent identity, credentials, or permission grants of any kind.

### Script Verification & Promotion

- **V1 (Must)** — A candidate script must be verified before use: it is shadow-run (or compared run-for-run) against the LLM execution's output, and only matching executions are promoted to **compiled** status.
- **V2 (Must)** — Verification evidence (inputs, expected vs actual outputs, comparison outcome) is retained and auditable.
- **V3 (Should)** — Mismatching candidates remain in draft status with a recorded diff so the agent (or operator) can repair them.
- **V4 (Should)** — Promoted scripts are versioned; re-verification is required after any repair or tool-schema change.

### Automatic Economical Execution

There is no execution-mode configuration. The platform applies a single fixed strategy: script-first with unconditional LLM fallback.

- **E1 (Must)** — When a verified script exists for a workflow, execution automatically runs the compiled script path — no configuration, no operator selection.
- **E2 (Must)** — Fallback to the LLM-driven agent path is unconditional: any automation failure (script error, tool schema mismatch, output validation failure, or repair exhaustion) always falls back and completes the run via the LLM path; a run never fails solely because a script failed.
- **E3 (Must)** — When no verified script exists, execution uses the LLM path by default without error.

### Plan-Time Compilability Analysis

- **E4 (Must)** — At implementation-plan generation time, the agent analyzes the plan and marks each step as **scriptable** (deterministic tool calls plus local data transformation) or **model-backed** (requires semantic bridging, System One judgment, or interactive input).
- **E4a (Must)** — **Plan-step script links**: when a plan step is backed by a script, the plan displays a link to that script so reviewers can open it (in the agent type's Scripts tab) and review its content, description, and lineage during plan review.
- **E5 (Must)** — A workflow is compilation-eligible only if the agent determines its steps are scriptable (model-backed steps may exist as embedded invocations). Not all agents qualify.
- **E6 (Must)** — Conversational and interactive agents are **never** compiled; compilation eligibility is restricted to non-conversational, non-interactive agent types and workflows.

### Session-Bound Script Execution

- **E7 (Must)** — Script execution is bound to the agent session: MCP tool calls made by the script use the **same dual identities** (user-realm human + agent-realm OIDC agent principal) as the agent itself, with identity parity guaranteed — scripts never introduce a separate or anonymous identity. This is realized through the standardized invocation contract (A5): identity context is always passed at invocation.

### Strict Script Boundary

- **E8 (Must)** — Scripts are strictly limited to **MCP tool calls** plus **local data processing/transformation** between steps. MCP tools are the ONLY way scripts interact with the outside world; no direct network, filesystem-outside-sandbox, database, or other I/O is permitted in scripts.

### Self-Improvement (Defect-Driven Script Repair)

- **E9 (Must)** — When execution fails due to a script defect, the agent repairs the script and retries within existing execution guardrails (permissions, no credentials, no external access), until success or guardrail-bounded exhaustion.
- **E10 (Should)** — Repair attempts are bounded and auditable: each attempt records the defect diagnosis, the diff applied, and the retry outcome; exhaustion of the bounded budget triggers unconditional fallback (E2).

### Fallback & Repair

- **F1 (Must)** — Fallback triggers on: script execution error, tool schema mismatch, or output validation failure.
- **F2 (Must)** — Every fallback records the reason and context needed for script repair, and links the fallback event to the script version involved.
- **F3 (Must)** — The LLM-driven agent path completes every fallback run and produces a repaired script candidate that must re-verify (V1) before promotion. The agent retries the repaired script within execution guardrails (E9).
- **F4 (Should)** — Repeated fallbacks on the same script version degrade the script's health status and can notify operators.

### Semantic Bridge & Decision Steps

- **S1 (Must)** — Semantic Bridge sub-agents (unstructured → structured conversion) can be invoked as steps within a workflow, including inside a compiled script's step sequence.
- **S2 (Must)** — The System One decision tool is invocable as a workflow step for judgment-type decisions, with its structured answer and confidence carried into downstream steps.
- **S3 (Should)** — Steps that involve semantic bridging or decision tools are marked as model-backed steps within compiled workflows, so operators can see which parts of a "compiled" run still consume model capacity.

### Governance, Audit & Cost

- **G1 (Must)** — A script registry holds all scripts with versioning, status (draft / verified / compiled / retired), owning agent type and workflow, and lineage back to the plan or run that produced them (including `repaired_from` lineage for repaired versions). The registry is persisted and managed by Control Center via REST APIs; its governance visibility is the Scripts tab in the agent type detail dialog (A1–A4), not a standalone admin page.
- **G2 (Must)** — Audit distinguishes script runs from LLM runs per execution, including script version, fallback events, and repair attempts.
- **G3 (Must)** — Cost tracking reports LLM tokens saved by compiled execution (tokens not consumed versus the equivalent LLM run), per workflow and aggregate.
- **G4 (Should)** — Dashboard surfacing: compilation rate, script hit rate, fallback rate, and cumulative cost savings.

### Security Integration

- **SEC1 (Must)** — Scripts execute within the Agent Runtime, bound to the agent session, invoked through the standardized contract (A5) with identity context always passed — a script is a function of the agent and executes only under the agent's identity and permission model; a script can never invoke a tool the corresponding agent identity/role is not permitted to use, and its MCP calls carry the same dual identities as the agent.
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
- **Trust**: fallback-triggered self-repair cycles converge — the same script version does not fall back repeatedly without repair, and bounded repair attempts (E9–E10) resolve script defects without operator intervention in the majority of cases.
- **Eligibility accuracy**: plan-time compilability analysis is reliable — workflows the agent marks as scriptable compile and verify at a high rate, while conversational/interactive agents are never compiled.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scripts overfit to one observed run and break on legitimate input variation | Silent wrong results or high fallback rate | Verification with comparison tolerance; output validation on every run; fallback with reason capture (F1–F3) |
| Tool schema drift invalidates compiled scripts at scale | Waves of fallbacks, cost spike | Schema-mismatch detection as explicit trigger (F1); re-verification requirement (V4); script health alerts (F4) |
| "Compiled" runs still consume model capacity via semantic/decision steps, diluting savings expectations | Misleading cost metrics | Model-backed steps explicitly marked (S3); cost reporting distinguishes residual model usage (G3) |
| Repair loops could mask broken scripts with endless retries | Wasted compute, hidden failures | Guardrail-bounded repair attempts (E9–E10); exhaustion triggers unconditional fallback with reason capture (E2, F1–F3); health status visibility (F4) |
| Session-bound script identity drifts from agent identity | Broken audit trail, identity confusion | Identity parity is a hard requirement — scripts reuse the executing agent session's dual identities (E7); no new identity class exists |
| Verification cost (shadow runs) offsets savings for rarely-used workflows | Net-negative ROI on compilation | Opportunistic compilation targeting stable, repeated patterns (C2, C4) |
| Governance debt: orphaned or stale scripts accumulate | Audit confusion, security surface | Registry lifecycle with retirement status (G1); lineage tracking (G1) |
| Security erosion — scripts perceived as a way "around" the agent sandbox | Trust, compliance | Hard requirement that scripts inherit the agent permission model and never bypass tool permissions (SEC1–SEC4) |

## Dependencies & Constraints

- Builds on existing Parthenon capabilities: MCP tool hub and permissions, skills/SOPs, Agent Data Type Registry, System One decision tools, and OTEL observability.
- Must comply with `docs/config.yaml` top-priority rules: fully segregated backend services; agents only in Agent Runtime; only Control Center touches the database; agents never hold sensitive data.
- Script execution is behavior, not a new permission pathway: no parallel permission system is introduced.
- Related prior change: System One decision skills (`docs/changes/system-one-decision-skills/`) provides the decision-making foundation referenced by S2.
