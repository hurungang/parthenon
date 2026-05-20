# Architecture — Conversation Agent Sessions

## Changed Components

| Component | Change |
|---|---|
| **Agent Session Queue** | Extended to store `conversation_title` and `conversation_status` (active / ended / archived) on session records for conversational agent types |
| **Communication Hub** | Receives `session_id` on WebSocket connect to associate messages with persistent sessions; triggers Session Auto-Namer after first user message lands |
| **Agent Instance Dashboard** | Sessions tab added per Agent Type view; columns updated to include session title and last-active timestamp for conversational agents; status filter extended to include `active` and `archived` states |
| **Platform API** | New session management endpoints wired to the Conversation Session Manager (create, list, resume, end, archive) |

## New Components

| Component | Responsibility |
|---|---|
| **Conversation Session Manager** | Creates and owns conversation session records; validates session ownership against the authenticated user; enforces session lifecycle transitions (active → ended → archived) |
| **Session Auto-Namer** | Invoked asynchronously after the first user message in a new session; constructs a concise title-generation prompt from the user's opening message; calls the configured LLM and writes the result back to the session record; pushes the title to the active WebSocket client |

## Integration Points

| Integration | Protocol | Direction | Purpose |
|---|---|---|---|
| Web UI → Platform API | REST | Frontend → Backend | Create, list, resume, end, archive sessions |
| Web UI ↔ Communication Hub | WebSocket | Bidirectional | Carry `session_id` on connection open; receive title-update push after auto-naming |
| Communication Hub → Session Auto-Namer | Internal | Async trigger | First-message signal initiates title generation |
| Session Auto-Namer → LLM Provider | LLM API | Outbound | Title-generation prompt resolved via Model Config Service (reuses agent type's model config) |
| Conversation Session Manager → Data Store | SQL | Read / Write | Persist session records and conversation history; query sessions by user and agent type |
| Session Query Endpoints → Data Store | SQL | Read | List and filter sessions for the Sessions tab |

## Component Architecture

```mermaid
flowchart TB
    subgraph WebUI[Web UI]
        SessionList[Sessions Tab]
        ChatView[Conversation View]
    end

    subgraph PlatformAPI[Platform API]
        CSM[Conversation Session Manager]
        SAN[Session Auto-Namer]
        SQE[Session Query Endpoints]
    end

    subgraph Core[Core Services]
        CH[Communication Hub]
        AR[Agent Runtime]
        AJQ[Agent Session Queue]
    end

    LLM[LLM Provider]
    DS[(Data Store)]

    SessionList -->|list/archive/end| SQE
    ChatView -->|start/resume session| CSM
    ChatView <-->|WebSocket| CH
    SQE --> DS
    CSM --> DS
    CSM -->|on first message| SAN
    SAN -->|title prompt| LLM
    LLM -->|generated title| SAN
    SAN --> DS
    CH --> AR
    AR --> AJQ
    AJQ --> DS
```

## Data Flow Changes

### Start Conversation Session

```mermaid
sequenceDiagram
    participant UI as Web UI
    participant CSM as Conv. Session Manager
    participant CH as Communication Hub
    participant AR as Agent Runtime
    participant SAN as Session Auto-Namer
    participant LLM as LLM Provider
    participant DS as Data Store

    UI->>CSM: Create conversation session (agent type)
    CSM->>DS: Persist session (status: active, title: null)
    CSM-->>UI: session_id
    UI->>CH: Open WebSocket (session_id)
    UI->>CH: Send first message
    CH->>AR: Dispatch to agent (session context)
    AR-->>CH: Agent response
    CH-->>UI: Display response
    CH->>SAN: Trigger auto-name (first user message)
    SAN->>LLM: Generate title from prompt
    LLM-->>SAN: Generated title
    SAN->>DS: Update session title
    SAN-->>UI: Push title update
```

### Discover and Resume Session

```mermaid
sequenceDiagram
    participant UI as Web UI
    participant SQE as Session Query Endpoints
    participant CSM as Conv. Session Manager
    participant CH as Communication Hub
    participant AR as Agent Runtime
    participant DS as Data Store

    UI->>SQE: List sessions (agent type, user)
    SQE->>DS: Query conversation sessions
    DS-->>SQE: Session records (id, title, status, updated_at)
    SQE-->>UI: Session list
    UI->>CSM: Resume session (session_id)
    CSM->>DS: Fetch conversation history
    DS-->>CSM: Message history
    CSM-->>UI: Session context (history + metadata)
    UI->>CH: Open WebSocket (session_id)
    UI->>CH: Send message
    CH->>AR: Dispatch with full conversation context
    AR-->>CH: Agent response
    CH-->>UI: Display response
```

## Master Arch Update Instructions

Update the following files in `docs/master/architecture/`:

| File | Update |
|---|---|
| `system-overview.md` | Add **Conversation Session Manager** and **Session Auto-Namer** to the Core Services subgraph in the main flowchart; add both to the Component Responsibilities table; add session management REST and WebSocket entries to the Integration Points table |
| `modules/communication.md` | Add "Conversation Session Persistence" section: describe how the hub accepts `session_id` on WebSocket connect, associates messages with the session record, and fires the async auto-name trigger after the first user message |
| `modules/agent-instance-dashboard.md` | Document the Sessions tab added to the Agent Type detail view; update the Dashboard Features section to include session title column, last-active timestamp, and the active / archived status filter values |
| `modules/agent-lifecycle.md` | Add a "Conversational Session Lifecycle" section describing the extended lifecycle (active → ended → archived) and the Conversation Session Manager's role in managing it alongside the Agent Session Queue |
