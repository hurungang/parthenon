# Architecture — Passthrough Sessions

## Changed Components

Two existing components change behaviour; no new top-level services are introduced.

| Component | What Changes |
|---|---|
| **MCP Hub — Session Manager** | Adds `passthrough` as a valid session type on `McpSession`; role configuration UI allows associating an MCP server with passthrough (no credential selection required) |
| **MCP Hub — MCP Proxy Engine** | Detects passthrough session type at call time; extracts the executing agent's JWT from the request context and forwards it as the `Authorization: Bearer` header instead of decrypting stored credentials |
| **MCP Hub — Tool Registry UI** | Tool test flow branches on server session type: passthrough servers show an agent identity picker; session-based servers show the existing session picker |

---

## System Architecture — Changed Component View

The diagram shows only components involved in this change. Unchanged platform components are omitted.

```mermaid
flowchart TB
    subgraph Clients
        WebUI[Web UI]
    end

    API[Platform API]

    subgraph MCPDomain["MCP Hub (Changed)"]
        SM[Session Manager]
        Proxy[MCP Proxy Engine]
        TR[Tool Registry]
    end

    subgraph CommHub["Communication Hub (Changed)"]
        WS[WebSocket Server]
        AR[Agent Runtime]
    end

    subgraph IdP["Identity Provider (Keycloak)"]
        AgentRealm[Agent Realm]
    end

    ExtMCP[MCP Server]
    CredStore[(Credential Store)]

    WebUI --> API
    API --> SM
    API --> TR
    WS --> AR
    AR --> Proxy
    Proxy -->|standard: decrypt + inject creds| CredStore
    Proxy -->|passthrough: forward agent JWT| AgentRealm
    Proxy --> ExtMCP
    AR -.->|agent JWT in context| Proxy
```

---

## Integration Points

| Integration | Before | After |
|---|---|---|
| **MCP Proxy Engine → Credential Store** | Always decrypts stored credentials at call time | Skipped for passthrough sessions; agent JWT used directly |
| **MCP Proxy Engine → Keycloak Agent Realm** | Not present | New: validates and retrieves agent JWT for passthrough forwarding |
| **MCP Server ← Authorization header** | Stored credential (API key, OAuth token, bearer) | Agent JWT for passthrough servers; unchanged for all other session types |
| **Role Config UI → Session Manager** | Session selection required to associate server with role | Passthrough servers require no session selection — server association alone is sufficient |
| **Tool Registry Test UI → Session Manager** | Session picker shown for all MCP servers | Agent identity picker shown for passthrough servers; session picker shown for all others |

---

## Data Flow Changes

```mermaid
sequenceDiagram
    participant AR as Agent Runtime
    participant Proxy as MCP Proxy Engine
    participant IdP as Keycloak Agent Realm
    participant MCP as MCP Server

    Note over AR,MCP: Standard session flow (unchanged)
    AR->>Proxy: invoke tool (session_id)
    Proxy->>Proxy: resolve session, decrypt creds
    Proxy->>MCP: POST /mcp (Authorization: stored creds)
    MCP-->>Proxy: tool result
    Proxy-->>AR: result

    Note over AR,MCP: Passthrough session flow (new)
    AR->>Proxy: invoke tool (passthrough server)
    Proxy->>Proxy: detect passthrough session type
    Proxy->>IdP: validate / retrieve agent JWT
    IdP-->>Proxy: agent JWT
    Proxy->>MCP: POST /mcp (Authorization: Bearer agent JWT)
    MCP->>IdP: introspect JWT
    IdP-->>MCP: identity confirmed
    MCP-->>Proxy: tool result
    Proxy-->>AR: result
```

**Key differences from the standard flow:**
- No credential decryption step — the Credential Store is not accessed for passthrough calls
- Agent JWT travels end-to-end; the MCP server performs its own identity validation against Keycloak
- Existing session-based flows are entirely unchanged

---

## Master Arch Update Instructions

| Document | Required Update |
|---|---|
| `docs/master/architecture/modules/tool-execution.md` | Add passthrough session type to MCP Proxy Engine description; document the new integration with Keycloak Agent Realm for JWT forwarding at call time |
| `docs/master/architecture/system-overview.md` | Update MCP Hub component responsibility row to note passthrough session support and direct agent JWT propagation to compatible MCP servers |
