# Control Center Architecture

```mermaid
flowchart LR
    UI[Web UI]
    CH[Communication Hub]
    AR[Agent Runtime]
    API[Control Center APIs]
    POL[Policy Resolution Service]
    GOV[Governance and Audit Service]
    DB[(Platform DB)]
    OBS[Observability]

    UI --> API
    CH -->|Caller: communication_hub| API
    AR -->|Caller: agent_runtime| API
    API --> POL
    API --> GOV
    POL --> DB
    GOV --> DB
    POL --> OBS
    GOV --> OBS
```

```mermaid
flowchart TB
    CALL[Inbound caller request]
    AUTH[Caller scope check]
    POLICY[Resolve effective guardrail policy]
    DECIDE[Allow or deny decision]
    LOG[Governance event recording]
    REPLY[Response to caller]
    DB[(Platform DB)]

    CALL --> AUTH
    AUTH --> POLICY
    POLICY --> DECIDE
    DECIDE --> LOG
    LOG --> DB
    DECIDE --> REPLY
    AUTH -->|Scope mismatch| LOG
```
