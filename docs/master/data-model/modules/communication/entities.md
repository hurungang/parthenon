# Communication & Conversations — Entities

```mermaid
erDiagram
    ConversationSession {
        uuid id
        uuid agent_type_id
        uuid triggered_by_user_id
        uuid agent_job_id
        string title
        string channel
        enum status
        int turn_count
        datetime created_at
        datetime updated_at
        datetime closed_at
    }
    ConversationTurn {
        uuid id
        uuid session_id
        enum role
        enum turn_type
        string content
        int token_count
        uuid intervene_request_id
        datetime created_at
    }
    ToolCallRecord {
        uuid id
        uuid turn_id
        string tool_name
        json tool_input
        json tool_output
        string error
        int duration_ms
        datetime created_at
    }
    InterveneRequest {
        uuid id
        uuid agent_session_id
        uuid agent_type_id
        uuid conversation_session_id
        enum intervention_type
        string reason
        json choices
        enum status
        int delegation_depth
        datetime created_at
        datetime responded_at
        datetime expires_at
    }
    InterveneResponse {
        uuid id
        uuid request_id
        uuid operator_user_id
        boolean approval_value
        string selected_choice
        string text_value
        datetime responded_at
    }
    AgentA2ASessionLink {
        uuid id
        string requester_instance_id
        string receiver_instance_id
        string session_link_id
        enum status
        datetime created_at
        datetime disconnected_at
    }
    AgentType {
        uuid id
        string name
        enum input_type
        boolean is_active
    }
    AgentSession {
        uuid id
        uuid agent_type_id
        uuid triggered_by_user_id
        enum status
        json conversation_history
        datetime created_at
    }
    AgentJob {
        uuid id
        uuid agent_type_id
        int delegation_depth
        enum status
    }
    Identity {
        uuid id
        string subject
        string display_name
    }

    AgentType ||--o{ ConversationSession : "has sessions"
    Identity ||--o{ ConversationSession : "owns"
    ConversationSession }o--o| AgentSession : "backed by"
    ConversationSession }o--o| AgentJob : "backed by"
    ConversationSession ||--o{ ConversationTurn : "has"
    ConversationTurn ||--o{ ToolCallRecord : "invokes"
    ConversationTurn }o--o| InterveneRequest : "references"
    InterveneRequest }o--|| ConversationSession : "surfaced in"
    InterveneRequest }o--|| AgentJob : "originates from"
    InterveneRequest ||--o| InterveneResponse : "resolved by"
    InterveneResponse }o--|| Identity : "responded by"
    AgentA2ASessionLink ||--o| ConversationSession : "links delegated context"
```

**ConversationStatus enum values:**

| Value | Meaning |
|---|---|
| `active` | Session is open and accepting new messages |
| `closed` | User explicitly ended the session; no longer accepting messages |
| `archived` | Hidden from the active sessions list; retained for audit and history |
| `error` | Session encountered an unrecoverable error |

**Source**: `backend/app/db/models/conversations.py`, `backend/app/db/models/intervene.py`, `backend/app/db/models/agents.py`

| Entity | Description |
|--------|-------------|
| **ConversationSession** | Primary user-facing session entity for conversational agent interactions; tracks session title (auto-generated), user ownership, agent type, and lifecycle status (active / closed / archived / error). Promoted from an internal execution record to a persistent, bounded conversation with full turn history. |
| **ConversationTurn** | A single message within a session; carries a role label (user, agent, tool, or system) and a `turn_type` distinguishing regular `message` turns from `intervene_request` and `intervene_response` intervention events. Ordered chronologically. |
| **ToolCallRecord** | A record of a specific tool invocation made during a conversation turn — what was called, with what arguments, what was returned, and any error encountered. |
| **InterveneRequest** | An agent-initiated request for human intervention surfaced in a conversation session. Links to the originating `AgentJob` and parent `ConversationSession`. Tracks intervention type (approval, choice, text), lifecycle status, and delegation depth. |
| **InterveneResponse** | The operator's response to an `InterveneRequest`. Carries the type-specific response value (approval boolean, selected choice, or free-form text) and the responding operator identity. |
| **AgentA2ASessionLink** | Tracks requester/receiver linkage when one agent delegates to another in a shared session context. Supports lifecycle visibility and disconnection handling for delegated conversations. |
