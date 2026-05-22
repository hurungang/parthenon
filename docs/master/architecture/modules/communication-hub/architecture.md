# Communication Hub

## Service Segregation Contract

Communication Hub uses service certificate-authenticated internal calls to Control Center and is restricted to its caller-specific allowlist.

Allowed Control Center internal groups:
- Certificate validation and tool-call authorization
- Session/conversation/A2A data endpoints
- System-tools endpoints (`save-result`, `send-notification`, `get-recipient-group`)
- MCP proxy endpoint

Denied by policy:
- Agent Runtime-only Control Center endpoints (for example `POST /api/v1/internal/data/sessions/claim-queued`)
- Any unknown or non-allowlisted internal endpoint

Communication Hub does not access the database directly; all persistence flows route through Control Center.

```mermaid
flowchart LR
    Req[Requester Agent]
    Hub[Communication Hub]
    NameVal[Shared Naming Validation]
    Perm[Permission Resolver]
    SOP[SOP A2A Policy]
    Registry[Agent Registry]
    Runtime[Agent Runtime]
    Lifecycle[Receiver Lifecycle Controller]
    Rec[Receiver Agent]
    Link[A2A Session Link]

    Req -->|target agent type slug| Hub
    Hub --> NameVal
    Hub --> Perm
    Perm --> SOP
    Hub --> Registry
    Registry --> Runtime
    Runtime --> Lifecycle
    Lifecycle -->|activate or attach| Rec
    Hub --> Link
    Req --> Link
    Rec --> Link
    Link -->|disconnect intent| Lifecycle
```

```mermaid
sequenceDiagram
    participant Req as Requester Agent
    participant Hub as Communication Hub
    participant NV as Shared Naming Validation
    participant Perm as Permission Resolver
    participant SOP as SOP A2A Policy
    participant Run as Agent Runtime
    participant Rec as Receiver Agent

    Req->>Hub: A2A request(target slug, payload)
    Hub->>NV: Validate slug format and reservation rules
    Hub->>Perm: Authorize delegation path
    Perm->>SOP: Evaluate SOP-step A2A allow rule
    SOP-->>Perm: Allow or deny
    Perm-->>Hub: Authorization decision
    Hub->>Run: Resolve receiver availability
    Run-->>Hub: Active receiver or activation result
    Hub->>Rec: Deliver message on shared session link
    Rec-->>Hub: Response or event
    Hub-->>Req: Response or event
    Req->>Hub: Disconnect
    Hub->>Run: Trigger receiver cleanup
```
