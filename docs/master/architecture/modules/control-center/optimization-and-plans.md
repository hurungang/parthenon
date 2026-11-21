# Control Center — Optimization, Authoring Models & Plans

[← Control Center Architecture](architecture.md) · [System Overview](../../system-overview.md)

Optimization is one gated action plus an optional human-gated conversation, both on the agent type itself — never a separate agent, identity, or role.

## Optimize Gate, Authoring Models & Optimization Mode

```mermaid
flowchart LR
    OP[Operator] --> GATE{Successful execution<br/>and usable model?}
    GATE -->|no| STOP[Disabled with explanation]
    GATE -->|yes| CMD[Optimization command run<br/>dispatched through the hub]
    OP --> CONV[Optimization-mode conversation<br/>channel on the agent type]
    CONV --> SCOPE[Scope guard<br/>this agent type only]
    CONV --> LEDGER[Live-test approval ledger<br/>script version · preview · single use]
    LEDGER -->|approved once| LIVE[One approved live script run<br/>in Agent Runtime · agent identity]
    CMD --> PLAN[(Optimized plan)]
    LIVE --> PLAN
    MODEL[Authoring model resolver<br/>optimizer model → authoring model] --> CMD
    MODEL --> GEN[Base plan and optimized<br/>plan authoring]
    GEN --> PLAN
    FALLBACK[Fallback attributed<br/>to an optimized artifact] --> MARK[Mark requires_fix<br/>+ recorded feedback]
    MARK --> OP
```

- **Separated actions** — Run never optimizes. Optimize is its own trigger with a dual precondition (at least one successful execution and a usable model); generation of a plan is explicit-only and unavailable for conversational agent types.
- **Authoring model resolver** — one tenant-scoped setting serves Skill/SOP workflow generation, implementation plans, and optimized plans. Unset, disabled, or removed is a hard stop with a clear message and no fallback model; the agent type's runtime model never authors plans.
- **Optimizer model resolution** — a tenant-scoped optimizer setting that falls back to the authoring model when unset. It is never the agent's runtime model, and a disabled selection is a "not configured" state rather than a substitution.
- **Optimization mode** — a conversation channel on the agent type. The executor routes it to the conversational loop whatever the agent type's input type, the optimization mission replaces the business instruction and skills only for those turns, and the scope guard limits work to that agent type's plan, scripts, and execution history. Normal business runs are unaffected.
- **Live-test approval ledger** — records the script version under test, a server-derived tool-call preview, the operator decision, and the single script run record, tied to tenant, agent type, and conversation. Approval is single-use and audited; deny, silence, timeout, or expiry leaves the session replay-only. The ledger grants no new authority — an approved live script cannot exceed the agent type's existing grants.
- **Requires-fix flagging** — when a fallback is attributed to an optimized artifact, Control Center marks the plan `requires_fix`, appends feedback, and the plan surface alerts the operator. A requires-fix plan is never re-served as if healthy, and no unattended re-optimization runs.

### Which Model Authors a Plan

```mermaid
flowchart LR
    SET[Tenant optimizer setting] -->|set| OM[Optimizer model]
    SET -->|"unset · disabled · removed"| AM[Authoring model]
    OM --> RES[Resolved authoring model]
    AM --> RES
    AM -->|"unset · disabled · removed"| HALT[Hard stop<br/>clear message · no fallback]
    RES --> ART[(Base and optimized plans)]
    RT[Agent type runtime model] -.->|never authors plans| ART
```

### Live-Test Approval (Single Use)

```mermaid
sequenceDiagram
    participant Op as Operator
    participant Conv as Optimization conversation
    participant CC as Control Center
    participant AR as Agent Runtime

    Conv->>CC: request a live test · script version under test
    CC->>CC: derive the tool-call preview
    CC-->>Op: approval request · preview · single use
    Op->>CC: approve
    CC->>CC: consume the approval · record the decision
    CC-->>AR: one live script run · agent identity
    AR-->>CC: run record tied to the ledger
    Note over CC,Op: deny · silence · timeout · expiry leaves the session replay-only
```

## Script Registry, Optimized Plans & LLM Mock Recordings

Control Center persists the Software 3.0 script framework — the script registry (draft → verified → compiled → retired lifecycle, sandbox validation), the `OptimizedImplementationPlan` compositions authored by the separated Optimize action and its optimization-mode conversations, `CommandPrompt` mission storage, per-execution records, and `LLMMockRecording` test data (written only in test/recording modes). Re-optimization never reopens a plan — a new one is authored and the prior one is retired. Its REST APIs serve the registry to Agent Runtime exclusively over mTLS; its internal recording endpoint stores mock LLM interactions (prompt + response + usage only). The semantic-bridge endpoint is served by the mock layer in test modes, so model-backed script steps run zero-LLM in tests. See [Sandboxed Scripting](../sandboxed-scripting.md).

### Plan Status

| Status | Meaning |
|---|---|
| `generating` | Authoring in progress |
| `ready` | Plan authored and usable |
| `needs_feedback` | Authored but awaiting operator feedback |
| `failed` | No usable plan was produced |
| `requires_fix` | A fallback was attributed to the plan: feedback recorded and the operator alerted; never re-served as healthy |
| `retired` | Superseded by a newly authored plan; kept for history, never reopened |

The optimizer persists the first three outcomes; `requires_fix` is set by Control Center when a fallback is attributed to the plan; `retired` records supersession.
