# Spec Change: Software 3.0 Agent Framework — Workflow Compilation

**Related PRD:** [prd.md](prd.md)
**Change type:** Capability extension (one new capability; existing capabilities preserved)
**Positioning change:** Parthenon is positioned as a **"Software 3.0" agent framework** — agents whose work is compiled into verified deterministic scripts that run without an LLM, with LLM fallback only when needed.

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

### N3. Per-Workflow Execution Modes
Execution mode is configurable per agent and per workflow:
- `llm` — always execute via LLM agent loop (today's behavior).
- `compiled-with-fallback` — run the verified script; fall back to LLM on failure. **Platform default.**
- `compiled-only` — run the script, never fall back (operator's explicit choice).

### N4. LLM Fallback with Repair Loop
If a script fails — tool schema changed, unexpected data shape, output validation failure — execution falls back to the LLM-driven agent path. The fallback records its reason and links to the script version; the LLM path may repair the script, and repaired candidates must re-verify before promotion.

### N5. Script Registry, Audit & Cost Tracking
Governance surface for Software 3.0: a script registry with versioning and lifecycle status (draft / verified / compiled / retired) and lineage to the plan or run that produced it; audit distinguishing script runs from LLM runs; cost tracking of LLM tokens saved by compiled execution.

## CHANGED Capabilities

### C1. Workflow Execution Semantics
- **Before:** every execution traverses the LLM observe-reason-act loop.
- **After:** executions of compiled workflows run the verified script directly through Agent Runtime; the LLM loop is used on first run, for verification, on fallback, and for workflows in `llm` mode. Execution records now indicate mode, script version, and fallback reasons.

### C2. Agent Implementation Plans
- **Before:** a plan describes the steps the agent will take in this run only.
- **After:** plans additionally yield a reusable artifact — a candidate bridge script — turning one agent run into durable software. Plan review now includes reviewing the candidate script.

### C3. Observability & Cost Reporting
- **Before:** cost and traces reflect LLM usage only.
- **After:** execution telemetry distinguishes script runs from LLM runs; model-backed steps inside compiled workflows (semantic bridge, decision tool) remain visible; dashboards report compilation rate, fallback rate, and token savings.

### C4. Operational Surface
- **Before:** operators manage agents, identities, tools, skills, SOPs, and schedules.
- **After:** operators additionally manage script versions and execution modes per workflow, and monitor script health (repeated fallbacks degrade health status and can notify).

## UNCHANGED Capabilities

### U1. Security Architecture (fully preserved)
The three backend services remain fully segregated. Scripts execute **within Agent Runtime** under the same identity/permission model as agents; a script can never invoke a tool the agent identity is not permitted to use, never bypass tool permissions, never hold credentials, and never touch the database. Tool access still flows integrations → MCP tool hub → permitted tools. Only Control Center connects to the database. Agents never receive sensitive data.

### U2. Identity Model
OIDC dual identities are unchanged: human users in the user realm, agents as first-class OIDC principals in the agent realm. Scripts inherit the executing agent's identity — no new identity class is introduced.

### U3. The Brain — Semantic Bridge & Decision Making
Both components keep their roles and are reused as **steps inside compiled workflows**:
1. **Semantic Bridge** — sub-agents converting unstructured data to structured data (unchanged behavior; now invocable as a step within a deterministic script's sequence).
2. **Decision Making** — the "System One" decision tool for fast, intuitive, knowledge-backed judgment (e.g., predicting rain likelihood from an environment description). Unchanged behavior; fills precisely the gap where deterministic scripts struggle, so these steps intentionally remain model-backed.

### U4. Tool & Permission Model
MCP tool hub, tool-level permissions, skills, SOPs, and role-based resolution are untouched. Scripts are consumers of the existing permission model, not a new pathway around it.

### U5. LLM Agent Loop & Non-Compiled Workflows
The LangChain deep-agent loop remains the default for un-compiled and `llm`-mode workflows. Nothing that cannot be scripted is forced into a script.

## Compliance Note

This change complies with `docs/config.yaml` `top_priority_rules`: services stay fully segregated; agents run only in Agent Runtime; only Control Center touches the database; scripts and agents never hold sensitive data. No database-direct paths, no credential exposure, no new permission bypass are introduced.
