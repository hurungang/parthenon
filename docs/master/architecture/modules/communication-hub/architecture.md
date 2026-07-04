# Communication Hub Architecture

```mermaid
flowchart LR
    UI[Workflow Authoring UI]
    CHAT[Conversation UI]
    LOG[Execution Log Viewer]
    CFG[System Configuration]
    CH[Communication Hub]
    AR[Agent Runtime]
    CC[Control Center]
    MCP[MCP and channel integrations]
    IR[Intervention Router]
    IQ[Intervention Queue]
    TDER[Task Delegation Event Router\nNEW]
    STAT[Workflow status channel]
    CSTAT[Chat status channel]
    CTX[Governed Context Package]

    UI <-->|Workflow generation and preview| CH
    CHAT <-->|Conversation turn exchange| CH
    CFG -->|Selected generation model| CH
    CH -->|Route workflow request| AR
    CH -->|Route terminate request| AR
    CH -->|Route resume signal| AR
    AR -->|Tool and delegation routing| CH
    AR -->|Thinking and delegation status events| CH
    AR -->|Intervene tool call and suspend| CH
    CH -->|Intervene response relay| CC
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
    AR -->|Intervene signal with conv_session_id| IR
    AR -->|Non-conversational delegation\nevents and intervene| TDER
    TDER -->|Delegation status push| LOG
    LOG -->|Intervene response| TDER
    IR -->|Enqueue pending per session| IQ
    IQ -->|Deliver next when resolved| IR
    IR -->|intervene_request WS message| CHAT
    CHAT -->|intervene_response WS message| IR
    IR -->|Persist intervene turn| CC
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

## Responsibilities

- **Message Broker**: Routes agent execution, tool calls, and delegation requests between Web UI, Agent Runtime, and Control Center. Detects intervention requests originating from delegated sub-agents within a conversation session and routes them to the parent conversation's UI via the Intervention Router.
- **Conversation Session Manager**: Manages conversation WebSocket connections, session state transitions, and intervention-pending flags that block new user messages until outstanding interventions are resolved.
- **Intervention Router**: Inspects `human_intervene` suspend signals for a `conversation_session_id`. When present, routes the intervention request to the connected WebSocket client of the parent conversation. When absent, falls through to the existing dashboard-based intervention flow.
- **Intervention Queue**: Per-conversation-session FIFO queue for intervention requests. When multiple delegated sub-agents request intervention concurrently, requests are delivered sequentially.
- **Task Delegation Event Router**: In-memory router that manages delivery of non-conversational delegation status events and intervention requests to execution log viewer clients. Maintains a mapping of active log viewer connections to parent task agent sessions. Pushes delegation status events (`delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`) and intervention requests to the correct log viewer. Falls back to poll-based delivery when no live viewer is connected.
- **System Tool Router**: The `endpoint_map` dict in `_route_to_system_tool()` maps bare tool names to Control Center system-tool endpoint URLs. Routing entries include `save_data`, `get_data`, `get_output`, and `query_result` — each pointing to the corresponding `POST /api/v1/internal/system-tools/<tool>` URL on Control Center. No new structural components are needed; existing permission-check and certificate-forwarding infrastructure handles these tool calls automatically.

## WebSocket Message Types

### Intervention messages (new)
- `intervene_request` (server → client): Intervention prompt with type, reason, options, delegation context
- `intervene_response` (client → server): User's response with request_id and response value
- `intervene_cancel` (client → server): User's dismissal with request_id
- `intervene_status` (server → client): Lifecycle updates with request_id and status

### Chat message changes
- `chat` messages from client are rejected when session has pending intervention
