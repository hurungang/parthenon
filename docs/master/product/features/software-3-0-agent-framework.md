# Software 3.0 Agent Framework (Workflow Compilation)

## 1. Epic Overview

Parthenon is positioned as a **Software 3.0 agent framework**: when an agent produces an implementation plan for a workflow, it also attempts to generate a deterministic bridge script between the tools involved. Once that script is generated **and verified** against a real model-driven execution, subsequent executions run the script purely — no model required. The agent is used to create the software; the software then runs without a model whenever a verified script exists, and always degrades to the model-driven path when automation fails — with nothing to configure. This turns recurring agent work from costly, non-deterministic, per-run reasoning into repeatable, low-cost, deterministic execution, while preserving model-driven judgment exactly where deterministic code struggles: semantic bridging (unstructured → structured data) and fast, knowledge-backed decisions (the "System One" decision tools), which remain first-class model-backed steps inside otherwise deterministic workflows. Scripts are owned by the agent type that produced them, governed in the Scripts tab of the Agent Type detail dialog, and always execute under the agent's identities and permissions — never their own.

## 2. Business Goals

- Compile, don't re-reason: recurring workflows execute as verified deterministic scripts by default.
- Reduce cost: target ≥ 70% reduction in model token spend for compiled-workflow executions versus the pre-compilation baseline.
- Deliver repeatability: 100% output parity between verified script runs and their verification reference on identical inputs.
- Reduce latency: measurable end-to-end speed-up (target ≥ 50%) for compiled workflows.
- Preserve trust and safety: zero security-policy violations attributable to scripts, and 100% of fallback events carry a recorded reason.

## 3. Users & Personas

- **Platform Administrator** — governs scripts where they live: the Scripts tab of each agent type's detail dialog, reviewing versions, promotion/retirement, verification evidence, lineage, and human-readable descriptions of what each script does.
- **Agent Operator** — monitors automatic economical execution: fallback events, script health, and agent-driven repair activity.
- **Enterprise Consumer / Business Owner** — benefits silently: repeated workflows become faster, cheaper, and produce identical results; sees execution provenance (compiled script vs model-driven run).
- **Compliance / Audit** — inspects script versions, verification evidence, run history, and the reason log for every fallback.

## 4. User Stories

- As a business owner, I want recurring agent workflows to run as verified deterministic scripts so that results are faster, cheaper, and identical across runs.
- As a platform administrator, I want each script owned by its agent type and listed in that agent type's Scripts tab, so that governance lives with the agent rather than in a separate admin module.
- As a platform administrator, I want each script's version history, self-improvement lineage, health, and a plain-language description, so that I can judge what a script does and how trustworthy it is.
- As a compliance officer, I want verification evidence retained for every promoted script, so that I can audit why automation was trusted.
- As an agent operator, I want any script failure to fall back unconditionally to the model-driven path, so that a run never fails solely because a script failed.
- As an agent operator, I want the agent to repair defective scripts within existing guardrails, so that script defects resolve themselves without my intervention in the majority of cases.
- As a plan reviewer, I want plan steps that are backed by scripts to link to those scripts, so that I can review their content and lineage during plan review.
- As a plan reviewer, I want each plan step marked as scriptable or model-backed, so that I can see which parts of a workflow will run deterministically.
- As a business owner, I want execution records to show provenance (script run vs model run, with version and fallback reasons), so that cost and behaviour reporting is credible.

## 5. Acceptance Criteria

### Workflow Compilation & Eligibility

- When an agent generates an implementation plan for a workflow, the system also attempts to generate a candidate deterministic bridge script covering the tool-call sequence (query a tool, transform/filter results, feed the next tool, delegate judgment or summarization to model-backed steps).
- Candidate scripts are derived from the implementation plan and/or the observed tool-call sequence of a successful model-driven execution.
- At plan time, each step is marked as scriptable (deterministic tool calls plus local data transformation) or model-backed (semantic bridging, decision judgment, or interactive input).
- A workflow is compilation-eligible only if the agent determines its steps are scriptable; conversational and interactive agents are never compiled.
- Plan steps backed by a script display a link to that script, opening it in the agent type's Scripts tab for review.
- Workflows whose recent model-driven runs show a stable, repeated tool-call pattern are flagged as good compilation candidates.

### Verification & Promotion

- A candidate script is verified before use: it is compared run-for-run against the model-driven execution's output on identical inputs; only matching executions are promoted to compiled status.
- Verification evidence (inputs, expected vs actual outputs, comparison outcome) is retained and auditable.
- Mismatching candidates remain in draft status with a recorded diff so the agent or an operator can repair them.
- Promoted scripts are versioned; re-verification is required after any repair.

### Agent-Owned Scripts (Scripts Tab)

- The Agent Type detail dialog includes a Scripts tab listing all scripts the agent type will use, each with version history and self-improvement lineage, lifecycle state (draft → verified → compiled → retired), health status, and a human-readable description.
- There is no standalone script administration page or navigation entry; script governance lives entirely in the agent type detail dialog.
- After closing any script management dialog, the parent view automatically refreshes to show updated lifecycle state, health, and counts without a manual page reload.

### Automatic Economical Execution

- When a verified script exists for a workflow, execution automatically runs the compiled script path — no configuration, no operator selection.
- Fallback to the model-driven agent path is unconditional: any automation failure (script error, tool mismatch, output validation failure, or repair exhaustion) always falls back and the run completes via the model-driven path.
- When no verified script exists, execution uses the model-driven path by default without error.

### Self-Improvement (Defect-Driven Script Repair)

- When execution fails due to a script defect, the agent repairs the script and retries within existing execution guardrails (permissions, no credentials, no external access) until success or guardrail-bounded exhaustion.
- Each repair attempt records the defect diagnosis, the change applied, and the retry outcome; exhaustion triggers unconditional fallback.
- Repeated fallbacks on the same script version degrade its health status.

### Semantic Bridge & Decision Steps

- Semantic bridge sub-agents (unstructured → structured conversion) can be invoked as steps within a workflow, including inside a compiled script's step sequence.
- System One decision tools are invocable as workflow steps for judgment-type decisions, with their structured answer and confidence carried into downstream steps.
- Steps involving semantic bridging or decision tools are marked as model-backed, so operators can see which parts of a compiled run still consume model capacity.

### Security & Identity

- Scripts execute under the agent's identities and permissions, never their own: identity context is always passed at invocation — the agent's dual identities (user-realm human + agent-realm agent principal) and its resolved permissions. Scripts hold no independent identity, credentials, or permission grants.
- Scripts are strictly limited to permitted tool calls plus local data processing between steps; permitted tools are the only way scripts interact with the outside world — no direct network, file, or database access.
- A script can never invoke a tool the corresponding agent identity is not permitted to use, and can never bypass tool permissions or touch the database.
- Script content and verification artifacts never contain sensitive data (identity tokens, credentials, integration secrets).
- All three backend services remain fully segregated; script artifacts are managed by Control Center and executed in Agent Runtime.

## 6. Out of Scope

- Replacing the model-driven agent loop — it remains always available as the unconditional fallback and the default for un-compiled workflows.
- Requiring every workflow or agent to compile — compilation is agent-driven and opportunistic; conversational/interactive agents are never compiled.
- General-purpose programming — scripts are bridge glue between permitted tools, not user-authored applications.
- Automatic self-healing without governance — script repair produces new candidate versions that must pass verification before promotion.
- Any change to the existing security model, identity topology, or tool permission semantics.
- Standalone script administration surfaces — governance remains in the agent type detail dialog.

## 7. Dependencies & Constraints

- Builds on existing platform capabilities: the MCP tool hub and permissions, skills and SOPs, the Agent Data Type Registry, System One decision tools, and existing observability.
- Must comply with platform top-priority rules: fully segregated backend services; agents and their scripts run only in Agent Runtime; only Control Center touches the database; agents and scripts never hold sensitive data.
- Script execution is behaviour, not a new permission pathway: no parallel permission system is introduced.
- The model is always invoked for verification comparisons; compilation targets stable, repeated workflows so verification cost stays proportionate.
- Related feature: [Sandboxed Scripting & Model-Authored Composition](sandboxed-scripting.md) builds on this framework's script registry, lifecycle, Scripts tab, and invocation contract.
