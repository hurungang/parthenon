# Agent Management — Entities

```mermaid
erDiagram
    AgentType {
        uuid id
        string name
        enum mode
        string llm_provider
        string llm_model
        uuid sop_id
        int max_instances
        boolean is_active
        string identity_subject
    }
    AgentInstance {
        uuid id
        uuid agent_type_id
        enum status
        string session_handle
        string initiator_subject
    }
    AgentSkillAssignment {
        uuid id
        uuid agent_type_id
        uuid skill_id
    }

    AgentType ||--o{ AgentInstance : "spawns"
    AgentType ||--o{ AgentSkillAssignment : "has"
    AgentType }o--o| Sop : "bound to"
    AgentSkillAssignment }o--|| Skill : "assigns"
```

**Source**: `backend/app/db/models/agents.py`

| Entity | Description |
|--------|-------------|
| **AgentType** | The definition of an agent class, including its operating mode (sop-agent or skillful-agent), OIDC identity, model binding, and maximum concurrent instance count. |
| **AgentInstance** | A single active runtime execution of an AgentType, carrying its own lifecycle status (created → active → closed). |
| **AgentSkillAssignment** | Links a Skill to a skillful-agent AgentType, making that skill available during the agent's reasoning loop. |
