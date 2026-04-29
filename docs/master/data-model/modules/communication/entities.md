# Communication & Conversations — Entities

```mermaid
erDiagram
    ConversationSession {
        uuid id
        uuid agent_instance_id
        string initiator_subject
        string channel
        enum status
        int turn_count
    }
    ConversationTurn {
        uuid id
        uuid session_id
        enum role
        string content
        int token_count
    }
    ToolCallRecord {
        uuid id
        uuid turn_id
        string tool_name
        json tool_input
        json tool_output
        int duration_ms
    }

    ConversationSession ||--o{ ConversationTurn : "has"
    ConversationTurn ||--o{ ToolCallRecord : "references"
```

**Source**: `backend/app/db/models/conversations.py`

| Entity | Description |
|--------|-------------|
| **ConversationSession** | A bounded interaction context between an initiating party (user or scheduler) and an agent; tracks channel, participants, and status. |
| **ConversationTurn** | A single message within a session; carries a role label (user, agent, tool, or system) and is ordered chronologically. |
| **ToolCallRecord** | A record of a specific tool invocation made during a conversation turn — what was called, with what arguments, and what was returned. |
