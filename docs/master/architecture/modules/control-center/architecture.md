# Control Center Architecture

```mermaid
flowchart LR
    UI[Web UI]
    CH[Communication Hub]
    AR[Agent Runtime]
    API[Control Center APIs]
    POL[Policy Resolution Service]
    CTX[Governed Context Assembler]
    CFG[Generation Model Resolver]
    SOP[Default SOP Resolver]
    GOV[Governance and Audit Service]
    DB[(Platform DB)]
    OBS[Observability]

    UI --> API
    CH -->|Caller: communication_hub| API
    AR -->|Caller: agent_runtime| API
    API --> POL
    API --> CTX
    API --> IRS[Intervene Request Store]
    API --> CIT[Conversation Intervention Turns]
    API --> TOPO[Runtime Topology Controller]
    API --> TERM[Termination Orchestrator]
    CTX --> CFG
    CTX --> SOP
    CFG --> DB
    SOP --> DB
    API --> GOV
    POL --> DB
    GOV --> DB
    TOPO --> DB
    TERM --> CH
    CTX --> CH
    POL --> OBS
    GOV --> OBS
    TERM --> OBS
```

```mermaid
flowchart TB
    CALL[Inbound caller request]
    AUTH[Caller scope check]
    POLICY[Resolve effective guardrail policy]
    CONTEXT[Assemble governed context]
    DECIDE[Allow or deny decision]
    LOG[Governance event recording]
    REPLY[Policy and context response]
    DB[(Platform DB)]

    CALL --> AUTH
    AUTH --> POLICY
    POLICY --> CONTEXT
    CONTEXT --> DECIDE
    DECIDE --> LOG
    LOG --> DB
    DECIDE --> REPLY
    AUTH -->|Scope mismatch| LOG
```

## Conversation Intervention Persistence

- **Conversation Intervention Turns**: Extension of `ConversationTurn` persistence to support `intervene_request` and `intervene_response` turn types. Stores intervention type (approval/choice/text), prompt text, available options, operator identity, response value, and timestamp. Turns are persisted in chronological order within the conversation stream for audit traceability.
- **Intervene Request Store**: Extended to accept and persist conversation context fields (`conversation_session_id`, `delegation_depth`) on `InterveneRequest`. Automatically creates paired `intervene_response` conversation turns when responses are submitted to conversation-scoped requests. Non-conversational flow (no `conversation_session_id`) is unchanged.
