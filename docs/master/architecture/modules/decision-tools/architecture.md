# Decision Tools Architecture

## Overview

Decision tools are user-definable decision-making modules that behave exactly like Parthenon's built-in system tools. They are the second decision-making pathway alongside LLM skills — a skill, an agent, or an external MCP client invokes a decision tool instead of routing the judgment to an LLM. Decision tools resolve through the same system-tool registry, naming convention (`decision____<name>`, four-underscore separator shared with `system____`), permission model, and grants as system tools. Skills themselves are unchanged. All decision-tool records, lookups, grants, and invocations are tenant-contained: names are unique per tenant, and `decision` is a reserved MCP server slug alongside `system`. Provider configuration and execution live in Control Center; for the provider/model side, see [Decision Models Architecture](../decision-models/architecture.md).

## Component Architecture

```mermaid
flowchart LR
    FE[Frontend Authoring UI]
    ADMIN[Platform Admin]
    CH[Communication Hub<br/>MCP registry bridge]
    AR[Agent Runtime]
    MCP[External MCP Clients]
    subgraph CC["Control Center"]
        DTR[Decision Tool Registry<br/>AgentDataType refs, tenant-scoped names]
        AI[AI Authoring Assistant<br/>reuses skill draft generation]
        PCS[Provider Config + Test Connection]
        DEE[Decision Execution Engine<br/>confidence gate]
        DRS[Decision Result Store]
    end
    DB[(PostgreSQL)]
    TS[TypeSafe API]

    ADMIN -->|provider key write-only| PCS
    FE -->|author tools, draft questions| DTR
    AI --> DTR
    FE -->|tool picker for skills<br/>decision____ alongside system____| CH
    AR -->|call decision____tool| CH
    MCP -->|tools/list + tools/call| CH
    CH -->|forward via system-tools path| DTR
    DTR --> DEE
    PCS --> DEE
    DEE --> TS
    DRS --> DB
    DTR --> DB
```

## Key Properties

- **Tool registry** — CRUD for decision tools: question sets (Choice / Score / Noul), state preset, and input/output references to existing Agent Data Type records (no ad-hoc schemas). Definitions are validated, and the tool description is auto-generated. Authoring is gated on a configured decision provider.
- **Tenant containment** — tool names are unique per tenant; identical names in different tenants never collide. The `decision` MCP server slug is reserved so no external MCP server can shadow the namespace.
- **Authoring assistance** — the authoring form detects backtick-quoted state placeholders in question instructions and suggests state mappings; an AI-assisted endpoint (the same generation mechanism behind the skill editor) drafts questions and state mapping from the tool description and chosen data types.
- **Execution engine** — resolve tool → apply state preset → dispatch all questions in one parallel evaluation → normalize typed answers → confidence gate (high = auto, medium = confirm, low = escalate).
- **Result storage** — every execution is persisted (tool, state snapshot, answers, probabilities, confidence, gate outcome) and auditable like existing tool executions.
- **Segregation respected** — Control Center is the only component that decrypts the provider key (call time only, never returned by any API) and calls the external vendor; Communication Hub brokers only; agents receive structured answers, never credentials.

## Invocation Flow

```mermaid
sequenceDiagram
    participant A as Agent / MCP Client
    participant CH as Communication Hub
    participant CC as Control Center
    participant V as Decision Vendor

    A->>CH: tools/call decision____<name>
    CH->>CC: forward via system-tools path (tenant-scoped)
    CC->>CC: resolve tool definition + provider config, decrypt key
    CC->>V: evaluate (state + all questions, parallel)
    V-->>CC: typed answers, probabilities, confidence
    CC->>CC: confidence gate
    CC->>CC: persist execution result
    CC-->>CH: structured result
    CH-->>A: structured result (no credentials)
```

## Data Model (business entities)

```mermaid
erDiagram
    TENANT ||--o{ DECISION_TOOL : "owns (name unique per tenant)"
    DECISION_TOOL }o--|| AGENT_DATA_TYPE : "input schema"
    DECISION_TOOL }o--|| AGENT_DATA_TYPE : "output schema"
    DECISION_TOOL ||--o{ DECISION_QUESTION : "question set"
    DECISION_TOOL }o--o{ DECISION_MODEL : "targets one enabled model"
    DECISION_TOOL ||--o{ DECISION_EXECUTION_RESULT : "executions"
```

- **Decision Tool** — tenant-scoped tool module with auto-generated description; grantable like any system tool.
- **Decision Question** — Choice / Score / Noul question with instructions, criteria, and state placeholders.
- **Decision Execution Result** — auditable record of one invocation (answers, probabilities, confidence, gate outcome).
- **Skills are unchanged** — skill definitions reference decision tools through the existing tool binding, listed as `decision____<name>` in the skill-editor tool picker.
