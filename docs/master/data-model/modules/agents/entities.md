# Agent Management — Entities

```mermaid
erDiagram
    ModelConfig {
        uuid id
        string name
        enum provider_type
        string api_endpoint
        string api_key_encrypted
        json enabled_models
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    AgentRole {
        uuid id
        string name
        string description
        datetime created_at
        datetime updated_at
    }
    AgentRoleIdentity {
        uuid role_id
        uuid identity_id
        datetime assigned_at
        uuid assigned_by
        datetime created_at
    }
    AgentRoleSOP {
        uuid role_id
        uuid sop_id
    }
    AgentRoleSkill {
        uuid role_id
        uuid skill_id
    }
    AgentRoleMcpSession {
        uuid role_id
        uuid mcp_session_id
        uuid server_id
        datetime assigned_at
        uuid assigned_by
    }
    AgentIdentity {
        uuid id
        string name
        enum identity_type
        string auth_provider
        string realm_name
        string access_token_encrypted
        string refresh_token_encrypted
        datetime token_expiry
        enum status
        datetime created_at
        datetime updated_at
    }
    AgentType {
        uuid id
        string name
        string description
        uuid identity_id
        uuid role_id
        string model_id
        string system_instruction
        enum input_type
        json input_schema
        enum output_type
        json output_schema
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    AgentSession {
        uuid id
        uuid agent_type_id
        uuid triggered_by_user_id
        json input_data
        enum status
        datetime started_at
        datetime completed_at
        json output_data
        json conversation_history
        string error_message
        datetime created_at
    }
    McpServer {
        uuid id
        string name
        string slug
    }
    McpSession {
        uuid id
        uuid server_id
        string name
        json identity_binding
    }
    Sop {
        uuid id
        string name
    }
    Skill {
        uuid id
        string name
    }
    Identity {
        uuid id
        string subject
    }

    AgentRole ||--o{ AgentRoleSOP : "grants access to"
    AgentRole ||--o{ AgentRoleSkill : "grants access to"
    AgentRole ||--o{ AgentRoleIdentity : "can be assumed by"
    AgentRole ||--o{ AgentRoleMcpSession : "provides MCP context via"
    AgentIdentity ||--o{ AgentRoleIdentity : "can assume"
    AgentRoleIdentity }o--|| Identity : "assigned by"
    AgentRoleSOP }o--|| Sop : "references"
    AgentRoleSkill }o--|| Skill : "references"
    AgentRoleMcpSession }o--|| McpSession : "references"
    AgentRoleMcpSession }o--|| McpServer : "constrained by"
    McpSession }o--|| McpServer : "belongs to"
    AgentPlan {
        uuid id
        uuid agent_type_id
        json plan_steps
        json topology
        enum generation_status
        string generation_error
        string agent_config_hash
        datetime generated_at
        datetime created_at
        datetime updated_at
    }

    AgentType }o--|| AgentRole : "governed by"
    AgentType }o--|| AgentIdentity : "authenticates as"
    AgentSession }o--|| AgentType : "executes"
    AgentSession }o--o| Identity : "triggered by"
    AgentType ||--o| AgentPlan : "has current plan"
```

**Source**: `backend/app/db/models/agents.py`

| Entity | Description |
|--------|-------------|
| **ModelConfig** | A named, reusable LLM provider backend configuration. Stores provider type, API endpoint, encrypted credentials, and the explicit list of enabled model IDs. The runtime resolves which config to use by matching a model ID against `enabled_models` on active configs. |
| **AgentRole** | A named permission set granting an agent access to specific SOPs and/or Skills. Controls which MCP tools are available at runtime and which identities may assume the role. |
| **AgentRoleIdentity** | Many-to-many join table explicitly assigning an AgentIdentity to an AgentRole. An identity can only be used for a role if a record exists here. Tracks when and by whom the assignment was made. |
| **AgentRoleSOP** | Join table linking an AgentRole to a Sop. Granting an SOP implicitly includes all Skills it depends on and all MCP tools those Skills require. |
| **AgentRoleSkill** | Join table linking an AgentRole to a Skill directly (outside of any SOP). Contributes the Skill's required MCP tools to the role's allowed tool set. |
| **AgentRoleMcpSession** | Join table associating an MCP Session with an AgentRole, providing credential and resource context for MCP tool calls. At most one session per MCP server per role (unique constraint on `role_id + server_id`). |
| **AgentIdentity** | Represents an agent's user account in a dedicated identity provider realm (e.g., `ai_agents`). Stores encrypted OAuth tokens used at runtime; tokens are refreshed automatically as needed. |
| **AgentType** | The definition of an agent class: its identity, permission role, model selection, system instruction, and input/output schema. The `model_id` is resolved at runtime against active `ModelConfig.enabled_models`; there is no direct FK to ModelConfig. |
| **AgentSession** | A single agent execution instance from submission through completion. Serves as the agent instance record for the dashboard. Stores input, output, status, timing, and (for conversational agents) the full `conversation_history`. |
| **AgentPlan** | Stores the most recent LLM-generated implementation plan for an agent type. One record per `AgentType` (unique on `agent_type_id`). `plan_steps` is a structured, ordered plan payload that is both human-readable (for UI preview) and machine-parseable (for runtime execution guidance). `topology` is an opaque node-edge JSON payload produced by the Topology Builder service for frontend rendering. `generation_status` tracks `pending` \| `success` \| `failed` state; `generation_error` captures the failure reason without discarding the last successful plan. `agent_config_hash` is a hash of the inputs at generation time (role, SOPs, skills, system instruction) used to detect plan staleness. The Agent Runtime loads the saved plan during session initialization to guide execution. |
