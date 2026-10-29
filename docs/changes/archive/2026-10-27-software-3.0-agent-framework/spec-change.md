# Spec Change: Software 3.0 Agent Framework — Workflow Compilation

**Related PRD:** [prd.md](prd.md)
**Change type:** Capability extension (one new capability; existing capabilities preserved)
**Positioning change:** Parthenon is positioned as a **"Software 3.0" agent framework** — agents whose work is compiled into verified deterministic scripts that run without an LLM whenever a verified script exists, with unconditional LLM fallback on any automation failure. Compilation eligibility is agent-driven at plan time; script execution is session-bound and MCP-only; agents self-improve by repairing defective scripts within existing guardrails.

## Paradigm Framing

| Generation | Model | Characteristics |
|---|---|---|
| Software 1.0 | Hand-written code | Deterministic, repeatable, but costly to author and rigid |
| Software 2.0 | LLM-driven agents | Powerful and flexible, but costly, non-deterministic, hard to repeat |
| Software 3.0 | Agents that **compile** into verified scripts | Agent creates the software; software runs without an LLM; LLM fallback only when needed |

The real "work" an agent does in many workflows is data collection and transformation between tools — which is scriptable. Software 3.0 captures that work once, verifies it, and replays it deterministically.

## NEW Capabilities

### N1. Workflow Compilation
When an agent generates an implementation plan for a workflow — or completes a run with a stable observed tool-call sequence — the system also generates a candidate **deterministic bridge script** between the tools involved. Example shape of a compiled workflow: call MCP tool A to query, transform/filter the results, feed MCP tool B, and hand over to a semantic-bridge sub-agent for a summary. Scripts cover the scriptable steps; judgment-type steps remain model-backed.

### N2. Script Verification & Promotion
Candidate scripts are verified before use: shadow-run, or compared against the LLM execution's output on identical inputs. Verified scripts are promoted to **compiled** status. Verification evidence is retained; mismatches stay as repairable drafts.

### N3. Plan-Time Compilability Analysis
At implementation-plan generation time, the agent analyzes which workflow steps are scriptable (deterministic tool calls plus local data transformation) and which are model-backed (semantic bridging, judgment, interactive input). A workflow is compilation-eligible only if the agent determines its steps are scriptable. Not all agents qualify: conversational and interactive agents are **never** compiled.

### N4. Automatic Economical Execution
There is no execution-mode configuration. Execution automatically runs the compiled script path whenever a verified script exists, and **always** falls back to the LLM-driven agent path on any automation failure — unconditional, built-in, nothing to configure. With no verified script, execution uses the LLM path by default.

### N5. Session-Bound Script Execution with Strict Boundary
Script execution is bound to the agent session: script MCP tool calls use the same dual identities (user-realm human + agent-realm OIDC agent principal) as the agent itself. Scripts are strictly limited to MCP tool calls plus local data processing/transformation between steps — **MCP tools are the only way scripts interact with the outside world**.

### N6. Agent Self-Improvement (Defect-Driven Script Repair)
When execution fails due to a script defect, the agent repairs the script and retries within existing execution guardrails (permissions, no credentials, no external access), until success or guardrail-bounded exhaustion. Repair attempts are recorded and auditable; exhaustion triggers unconditional LLM fallback.

### N7. Script Registry, Audit & Cost Tracking
Governance foundation for Software 3.0: a script registry with versioning and lifecycle status (draft / verified / compiled / retired) and lineage to the plan or run that produced it (including `repaired_from` lineage for repaired versions); audit distinguishing script runs from LLM runs; cost tracking of LLM tokens saved by compiled execution. The registry is persisted and served by Control Center REST APIs; there is **no standalone admin module** for scripts — governance visibility lives in the agent type detail dialog (see C1 below).

### N8. Agent-Owned Scripts (Scripts Tab)
Scripts are functions owned by the agent type that produced them. The Agent Type detail dialog gains a **Scripts tab** listing all scripts the agent will use, each with its version history and self-improvement lineage (`repaired_from` parent, lifecycle draft → verified → compiled → retired), its health, and a human-readable description of what the script does.

### N9. Standardized Script Invocation Contract
A script is invoked like a function owned by the agent itself: identity context is **always** passed to script execution — the agent's dual identities and its resolved permissions. Scripts execute with the agent's identities and permissions, never their own; they hold no independent identity, credentials, or grants.

## CHANGED Capabilities

### C1. Agent Type Detail Dialog
- **Before:** the agent type detail dialog shows the agent type's configuration (identity, role, model, instructions, I/O types).
- **After:** the dialog gains a **Scripts tab** — the governance surface for the agent's owned scripts: all scripts the agent type will use, each with version history and self-improvement lineage (`repaired_from`, lifecycle draft → verified → compiled → retired), health, and a human-readable description. There is no standalone script admin page or navigation entry; Control Center REST APIs persist the registry and serve this dialog.

### C2. Workflow Execution Semantics
- **Before:** every execution traverses the LLM observe-reason-act loop.
- **After:** executions of workflows with a verified script run the compiled script automatically (script-first always); the LLM loop is used for the first run, for verification, as the **unconditional** fallback on any automation failure, for bounded repair retries' eventual degradation, and for workflows without a verified script. Execution records now indicate script version, fallback reasons, and repair attempts — never a configured mode.

### C3. Agent Implementation Plans
- **Before:** a plan describes the steps the agent will take in this run only.
- **After:** plans additionally include **compilability analysis** (each step marked scriptable vs model-backed; conversational/interactive agents marked ineligible) and yield a reusable artifact — a candidate bridge script — turning one agent run into durable software. Plan steps backed by a script display a **link to that script**, so reviewers can open and review it (in the agent type's Scripts tab) during plan review.

### C4. Observability & Cost Reporting
- **Before:** cost and traces reflect LLM usage only.
- **After:** execution telemetry distinguishes script runs from LLM runs; model-backed steps inside compiled workflows (semantic bridge, decision tool) remain visible; dashboards report compilation rate, fallback rate, and token savings.

### C5. Operational Surface
- **Before:** operators manage agents, identities, tools, skills, SOPs, and schedules.
- **After:** operators additionally review script versions, lineage, health, and agent-driven repair activity — in the Scripts tab of the agent type detail dialog (scripts are agent-owned; no standalone admin module). There are no execution modes to configure — script-first execution with unconditional LLM fallback is built-in behavior.

## UNCHANGED Capabilities

### U1. Security Architecture (fully preserved)
The three backend services remain fully segregated. Scripts execute **within Agent Runtime** under the same identity/permission model as agents; a script can never invoke a tool the agent identity is not permitted to use, never bypass tool permissions, never hold credentials, and never touch the database. Tool access still flows integrations → MCP tool hub → permitted tools. Only Control Center connects to the database. Agents never receive sensitive data.

### U2. Identity Model
OIDC dual identities are unchanged: human users in the user realm, agents as first-class OIDC principals in the agent realm. Scripts inherit the executing agent's identity through the standardized invocation contract (N9 — identity context always passed; a script executes with the agent's identities and permissions, never its own; identity parity is an explicit binding requirement); no new identity class is introduced.

### U3. The Brain — Semantic Bridge & Decision Making
Both components keep their roles and are reused as **steps inside compiled workflows**:
1. **Semantic Bridge** — sub-agents converting unstructured data to structured data (unchanged behavior; now invocable as a step within a deterministic script's sequence).
2. **Decision Making** — the "System One" decision tool for fast, intuitive, knowledge-backed judgment (e.g., predicting rain likelihood from an environment description). Unchanged behavior; fills precisely the gap where deterministic scripts struggle, so these steps intentionally remain model-backed.

### U4. Tool & Permission Model
MCP tool hub, tool-level permissions, skills, SOPs, and role-based resolution are untouched. Scripts are consumers of the existing permission model, not a new pathway around it.

### U5. LLM Agent Loop & Non-Compiled Workflows
The LangChain deep-agent loop remains the default for workflows without a verified script, the unconditional fallback for all automation failures, and the engine for agent-driven script repair. Nothing that cannot be scripted is forced into a script; conversational and interactive agents are never compiled.

### U6. Execution Guardrails
The existing execution guardrail set (tool permissions, no credentials, no external access beyond MCP) is unchanged and is the boundary within which agent self-improvement operates: script repair and retry (N6) never extends beyond these guardrails, no matter how many bounded attempts occur.

## Compliance Note

This change complies with `docs/config.yaml` `top_priority_rules`: services stay fully segregated; agents run only in Agent Runtime; only Control Center touches the database; scripts and agents never hold sensitive data. No database-direct paths, no credential exposure, no new permission bypass are introduced.
