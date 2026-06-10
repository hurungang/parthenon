# Agent Instance Dashboard

## Overview

The Agent Instance Dashboard is a Web UI component that gives platform admins and business users visibility into all running and historical agent executions. Each row in the dashboard corresponds to one `AgentSession` record. Users can filter by session status and time range, then drill into an individual instance to see its structured input, output, and full conversation turn history.

The dashboard now also hosts the **Runtime Control Dashboard** — a read-only operator view that surfaces currently running agents, their delegation topology, configured model-usage guardrails, current usage posture, and operator-controlled termination actions.

## Component Architecture

```mermaid
flowchart LR
    User[Business User or Admin]

    subgraph WebUI[Web UI]
        AID[Agent Instance Dashboard]
        RCD[Runtime Control Dashboard]
        subgraph Detail[Instance Detail View]
            LogViewer[Log Viewer]
        end
    end

    subgraph API[Platform API]
        SQ[Session Query Endpoints]
        Topo[Runtime Topology & Terminate]
    end

    subgraph Data[Data Store]
        AS[AgentSession & Conversation History]
        EL[Execution Logs]
        GRD[Guardrails & Usage Posture]
    end

    User --> AID
    User --> RCD
    AID -->|filter by status and time| SQ
    AID --> Detail
    Detail -->|fetch input, output, steps| SQ
    SQ --> AS
    SQ --> EL
    EL -->|raw log| LogViewer

    RCD -->|topology query| Topo
    RCD -->|terminate selected node| Topo
    Topo --> AS
    Topo --> GRD
```

## Dashboard Features

### Session List

- Lists all agent instances (one row per `AgentSession`)
- **Status filter:** `running` / `completed` / `failed` / `cancelled` / `terminated`
- **Time-range picker:** scopes results to a selected window
- Columns: agent type, status, start time, duration, session title (for conversation-type agents)
- **Session column:** For conversation-type agent executions, displays the linked conversation session title; empty for non-conversational agents

### Sessions Tab (Conversation Agents Only)

For conversation-type agents, the Agent Type detail dialog includes a dedicated **Sessions** tab that lists all of the user's conversation sessions for that agent type:

- **Session list columns:** Title (auto-generated), Status (active / closed / archived), Last Active timestamp
- **Actions per session:** Resume (opens chat interface with full history), End (closes session), Archive (hides from active list)
- **"Start New Conversation" entry point** — creates a new session and opens the chat interface
- **User-scoped listing** — each user sees only their own sessions
- **Automatic refresh** — session list updates after create, end, and archive operations without page reload

The Sessions tab is visible **only** for agent types with `input_type = 'conversation'`. All other agent types (single-shot, workflow, etc.) do not display this tab.

### Runtime Control Dashboard

The dashboard hosts the [Runtime Control Dashboard](runtime-control-dashboard.md), which provides a read-only operator view of currently running agents, their delegation topology, configured model-usage guardrails, and current usage posture. It supports operator-controlled termination actions for authorized users, with cascade termination of delegated children.

Key behaviors:

- **Topology view** shows active agents, their delegated children, conversation sessions, and agent instances
- **Filter legend** lets operators toggle visibility of any combination of status + node kind
- **Cascade termination** — terminating a parent execution stops all active delegated child executions

For full architecture details, see the [Runtime Control Dashboard](runtime-control-dashboard.md) document.

### Instance Detail View

Selecting a session opens the Instance Detail View, which surfaces:

| Section | Content |
|---|---|
| **Input** | Structured input submitted to the session |
| **Output** | Structured or markdown output produced by the agent |
| **Conversation** | Full turn history (for conversational agent types) |
| **Log Viewer** | Three-panel view of session execution: **Summary Panel** (identity, role, SOP/skills, plan, model, result summary — shown by default), **Working Steps Panel** (LLM iterations and tool calls grouped per reasoning step — collapsed by default), **Raw Log Toggle** (switches to unprocessed raw log text; copyable). See [Execution Logs](execution-logs.md). |

## Backend Query Endpoints

The Platform API exposes session query endpoints that accept `status` and `time_range` parameters. No additional persistence schema is required beyond what the Agent Session Queue already tracks — the `AgentSession` record, conversation history table, and Execution Log Store are queried directly. See [Agent Runtime](agent-runtime/architecture.md) for session state management.

The Runtime Control Dashboard reads the **runtime topology** from a Control Center endpoint that merges three sources — `AgentJob` (live agent runs), `ConversationSession` (conversation sessions with synthetic active/sleep status derived from backing job state), and `AgentInstance` (agent instance dashboard entries). Operator-initiated termination is routed through the Communication Hub to Agent Runtime to preserve service segregation and certificate-based authentication boundaries.

## Related Modules
- [Runtime Control Dashboard](runtime-control-dashboard.md) — operator surface for live execution state and termination
- [Execution Logs](execution-logs.md) — execution log view, status colors, and terminated/failed distinction
- [Model Config](model-config.md) — vendor → model → guardrail hierarchy
- [Agent Runtime](agent-runtime/architecture.md) — agent execution and termination
- [Communication Hub](communication-hub/architecture.md) — control-plane routing for termination
