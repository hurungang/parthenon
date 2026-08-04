# Communication Hub Architecture

## Message Routing and UI Connections

```mermaid
flowchart LR
    UI[Workflow Authoring UI]
    CHAT[Conversation UI]
    LOG[Execution Log Viewer]
    CFG[System Configuration]
    CH[Communication Hub]
    AR[Agent Runtime]
    CC[Control Center]
    CTX[Governed Context Package]
    STAT[Workflow status channel]
    CSTAT[Chat status channel]
    MCP[MCP and channel integrations]

    UI <-->|Workflow generation and preview| CH
    CHAT <-->|Conversation turn exchange| CH
    CFG -->|Selected generation model| CH
    CH -->|Route workflow request| AR
    CH -->|Route terminate request| AR
    CH -->|Route resume signal| AR
    AR -->|Tool and delegation routing| CH
    AR -->|Thinking and delegation status events| CH
    AR -->|Request governed context| CH
    CH --> CC
    CC --> CTX
    CTX --> CH
    CH --> AR
    CH --> MCP
    AR -->|Policy and stop outcomes| CH
    AR -->|Terminate acknowledgement| CH
    CH --> STAT
    CH --> CSTAT
    STAT --> UI
    CSTAT --> CHAT
```

## Intervention Routing and External Agents

```mermaid
flowchart LR
    AR[Agent Runtime]
    CH[Communication Hub]
    CC[Control Center]
    CHAT[Conversation UI]
    LOG[Execution Log Viewer]
    IR[Intervention Router]
    IQ[Intervention Queue]
    TDER[Task Delegation Event Router]
    EA[External AI Agent]
    AKV[API Key Validator]

    AR -->|Intervene signal with conv_session_id| IR
    AR -->|Non-conversational delegation events and intervene| TDER
    TDER -->|Delegation status push| LOG
    LOG -->|Intervene response| TDER
    IR -->|Enqueue pending per session| IQ
    IQ -->|Deliver next when resolved| IR
    IR -->|intervene_request WS message| CHAT
    CHAT -->|intervene_response WS message| IR
    IR -->|Persist intervene turn| CC
    EA -->|API Key| AKV
    AKV -->|mTLS: validate key| CC
    AKV -->|Authenticated request| CH
```

```mermaid
flowchart TB
    P0[Policy and context fetch from Agent Runtime]
    CH[Communication Hub]
    CC[Control Center]
    P1[Effective policy and governed context]
    S0[Guardrail stop outcome from Agent Runtime]
    S1[Workflow channel update]
    UI[Client view]

    P0 --> CH
    CH --> CC
    CC --> CH
    CH --> P1
    S0 --> CH
    CH --> S1
    S1 --> UI
```

## Dual Authentication Paths

Communication Hub accepts agents through two parallel authentication paths, converging at the same MCP proxy layer:

| Auth Path | Credential | Agent Type | Token Handling |
|-----------|-----------|------------|----------------|
| **mTLS Certificate** | X.509 client cert issued by CC CA | Internal Agent Runtime | AR receives decrypted identity token |
| **API Key** | Bearer token or query parameter | External third-party agents | CH holds identity token internally; never exposed |

```mermaid
flowchart LR
    EA[External Agent]
    AKV[API Key Validator]
    CC_VAL[CC Key Validation API]
    CC_DB[(CC Database)]
    CH_PROXY[MCP Proxy Layer]
    MCP[MCP Servers]

    EA -->|API Key| AKV
    AKV -->|mTLS: validate key| CC_VAL
    CC_VAL -->|lookup hash| CC_DB
    CC_VAL -->|identity token + permissions| AKV
    AKV -->|authenticated request| CH_PROXY
    CH_PROXY -->|proxy with token| MCP
```

External agents do not receive identity tokens. The API Key Validator calls Control Center's internal validation endpoint over mTLS, receives a resolved identity token, and holds it internally. CH injects the token only when proxying MCP tool requests to downstream servers.

## Responsibilities

- **Message Broker**: Routes agent execution, tool calls, and delegation requests between Web UI, Agent Runtime, and Control Center. Detects intervention requests originating from delegated sub-agents within a conversation session and routes them to the parent conversation's UI via the Intervention Router.
- **Conversation Session Manager**: Manages conversation WebSocket connections, session state transitions, and intervention-pending flags that block new user messages until outstanding interventions are resolved.
- **API Key Validator**: New middleware that intercepts requests bearing an API key (via `Authorization: Bearer` header or `?apiKey=` query parameter). Calls Control Center's internal validation endpoint over mTLS, receives the resolved identity/role/permission set, and caches the outcome for the request lifetime. External agents never receive the identity token — CH holds it exclusively for MCP request proxying.
- **Intervention Router**: Inspects `human_intervene` suspend signals for a `conversation_session_id`. When present, routes the intervention request to the connected WebSocket client of the parent conversation. When absent, falls through to the existing dashboard-based intervention flow.
- **Intervention Queue**: Per-conversation-session FIFO queue for intervention requests. When multiple delegated sub-agents request intervention concurrently, requests are delivered sequentially.
- **Task Delegation Event Router**: In-memory router that manages delivery of non-conversational delegation status events and intervention requests to execution log viewer clients. Maintains a mapping of active log viewer connections to parent task agent sessions. Pushes delegation status events (`delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`) and intervention requests to the correct log viewer. Falls back to poll-based delivery when no live viewer is connected.
- **System Tool Router**: Maps bare tool names (`save_data`, `get_data`, `get_output`, `query_result`, `load_skills`) to Control Center internal system-tool endpoints. No new structural components are needed; existing permission-check and certificate-forwarding infrastructure handles these tool calls automatically.

## WebSocket Messages

The Communication Hub supports structured WebSocket messages for intervention and chat flows. Intervention messages include request delivery, response submission, cancellation, and status updates between server and client. Chat messages from clients are rejected when the session has a pending intervention, ensuring orderly resolution of HITL requests.
