# Skills & SOPs — Entities

```mermaid
erDiagram
    Skill {
        uuid id
        string name
        string description
        string instructions
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    SkillToolBinding {
        uuid id
        uuid skill_id
        uuid tool_id
        int order
    }
    Sop {
        uuid id
        string name
        string description
        string instructions
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    SopStep {
        uuid id
        uuid sop_id
        int order
        string name
        string description
        enum step_type
        uuid skill_id
        uuid target_agent_type_id
        json step_config
        datetime created_at
    }
    SopA2APermission {
        uuid id
        uuid sop_id
        uuid sop_step_id
        uuid target_agent_type_id
        enum derivation_source
        boolean is_enabled
        datetime created_at
    }

    Skill ||--o{ SkillToolBinding : "invokes via"
    SkillToolBinding }o--|| McpTool : "calls"
    Sop ||--o{ SopStep : "composed of"
    SopStep }o--o| Skill : "executes"
    SopStep }o--o| AgentType : "delegates to"
    SopStep ||--o{ SopA2APermission : "derives"
    Sop ||--o{ SopA2APermission : "grants"
    AgentType ||--o{ SopA2APermission : "target_is"
```

**Source**: `backend/app/db/models/skills.py`

| Entity | Description |
|--------|-------------|
| **Skill** | A named, permission-assignable capability that wraps one or more MCP tool invocations into a single executable unit; carries agent-facing instructions for how to use the skill. |
| **SkillToolBinding** | Ordered link between a Skill and an MCP tool it invokes; supports multi-tool skills. |
| **Sop** | A Standard Operating Procedure that composes multiple Skills into an ordered, multi-step workflow; carries human-readable workflow guidance in its instructions field. |
| **SopStep** | An ordered step within a SOP; represents either a skill invocation (`skill_invocation`) or a delegation request to another agent type (`agent_delegation`); carries step-specific runtime config and a typed reference to the target agent type. |
| **SopA2APermission** | Derived allow-list entry generated from delegation steps. Captures which target agent type can be invoked from a SOP step and whether the delegation rule is currently enabled. |
