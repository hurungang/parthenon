# Data Model Overview

Parthenon's data model is organised into six domains. Each section below contains the entity-relationship diagram for that domain with key business attributes. Cross-domain links are summarised in the last section.

For entity descriptions, see the module docs in `docs/master/data-model/modules/`.
Schema source files live in `backend/app/db/models/`.

---

## Identity & Access

```mermaid
erDiagram
    Identity {
        uuid id
        string subject
        string idp_subject
        string email
        string display_name
        enum identity_type
        uuid role_id
        boolean is_active
    }
    Role {
        uuid id
        string name
        enum role_type
        boolean is_active
    }
    Permission {
        uuid id
        string name
        string resource
        string action
    }
    RolePermission {
        uuid id
        uuid role_id
        uuid permission_id
    }
    IdentityProviderConfig {
        uuid id
        string provider_type
        string oidc_provider_url
        string client_id
        string client_secret
        string realm_name
        string audience
        boolean is_setup_complete
        datetime setup_completed_at
        uuid setup_completed_by
    }
    IdentityProviderSetupState {
        uuid id
        boolean is_setup_complete
        datetime completed_at
        uuid completed_by
    }

    Identity }o--|| Role : "assigned to"
    Role ||--o{ RolePermission : "grants"
    Permission ||--o{ RolePermission : "is granted via"
    IdentityProviderConfig ||--o| Identity : "setup_completed_by"
    IdentityProviderSetupState ||--o| Identity : "completed_by"
```

**Sources**: `backend/app/db/models/identity.py`, `backend/app/db/models/identity_provider_config.py`, `backend/app/db/models/identity_provider_setup_state.py`

---

## User Permissions

```mermaid
erDiagram
    TagDefinition ||--o{ TagValue : "has"
    Role ||--o{ PolicyStatement : "contains"
    PolicyStatement ||--o{ PolicyAction : "includes"
    PolicyStatement ||--o{ PolicyResource : "scopes"
    PolicyStatement ||--o{ PolicyTagCondition : "conditions"
    PlatformUser }o--o{ Role : "assigned via UserRole"
    PlatformUser }o--o{ Group : "member via UserGroup"
    Group }o--o{ Role : "assigned via GroupRole"
    Group }o--|| PlatformUser : "owned by"
    AccessRequestBatch }o--|| PlatformUser : "submitted by"
    AccessRequest }o--|| AccessRequestBatch : "part of"
    AccessRequest }o--o| Group : "assigned to"
    AccessRequest }o--|| PlatformUser : "requested by"

    TagDefinition {
        uuid id
        string key
        string scope
        string resource_type
        string description
        datetime created_at
    }
    TagValue {
        uuid id
        uuid tag_definition_id
        string value
        datetime created_at
    }
    Role {
        uuid id
        string name
        string description
        enum role_type
        datetime created_at
        datetime updated_at
    }
    PolicyStatement {
        uuid id
        uuid role_id
        string effect
        string module
        datetime created_at
    }
    PolicyAction {
        uuid id
        uuid policy_statement_id
        string action
    }
    PolicyResource {
        uuid id
        uuid policy_statement_id
        string resource_type
        string resource_id
    }
    PolicyTagCondition {
        uuid id
        uuid policy_statement_id
        string tag_key
        string tag_value
    }
    PlatformUser {
        uuid id
        string oidc_sub
        string email
        string display_name
        datetime first_seen_at
        datetime last_seen_at
    }
    UserRole {
        uuid user_id
        uuid role_id
        datetime assigned_at
        string assigned_by
    }
    Group {
        uuid id
        string name
        string description
        uuid owner
        string idp_claim_value
        datetime created_at
    }
    GroupRole {
        uuid group_id
        uuid role_id
        datetime assigned_at
    }
    UserGroup {
        uuid user_id
        uuid group_id
        datetime joined_at
        string join_reason
    }
    AccessRequestBatch {
        uuid id
        uuid submitted_by
        string justification
        datetime submitted_at
    }
    AccessRequest {
        uuid id
        uuid batch_id
        uuid group_id "optional"
        uuid requested_by
        string status
        datetime requested_at
        datetime reviewed_at
        string reviewed_by
        string reviewer_reason
    }
```

**Sources**: `backend/app/db/models/tag_definition.py`, `backend/app/db/models/tag_value.py`, `backend/app/db/models/role.py`, `backend/app/db/models/policy_statement.py`, `backend/app/db/models/policy_action.py`, `backend/app/db/models/policy_resource.py`, `backend/app/db/models/policy_tag_condition.py`, `backend/app/db/models/platform_user.py`, `backend/app/db/models/user_role.py`, `backend/app/db/models/group.py`, `backend/app/db/models/group_role.py`, `backend/app/db/models/user_group.py`, `backend/app/db/models/access_request_batch.py`, `backend/app/db/models/access_request.py`

---

## MCP Hub

```mermaid
erDiagram
    McpServer {
        uuid id
        string name
        string slug
        string base_url
        enum status
        datetime last_synced_at
        datetime created_at
        datetime updated_at
    }
    McpSession {
        uuid id
        uuid server_id
        string name
        string description
        enum auth_type
        string encrypted_credentials
        string identity_subject
        json identity_binding
        json credential_config
        boolean is_active
        datetime created_at
        datetime updated_at
    }
    McpTool {
        uuid id
        uuid server_id
        string name
        string original_name
        boolean is_active
    }
    ToolPermission {
        uuid id
        uuid tool_id
        uuid role_id
    }

    McpServer ||--o{ McpSession : "has"
    McpServer ||--o{ McpTool : "provides"
    McpTool ||--o{ ToolPermission : "governed by"
```

**Source**: `backend/app/db/models/mcp_hub.py`

---

## Skills & SOPs

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

    Skill ||--o{ SkillToolBinding : "invokes via"
    SkillToolBinding }o--|| McpTool : "calls"
    Sop ||--o{ SopStep : "composed of"
    SopStep }o--o| Skill : "executes"
    SopStep }o--o| AgentType : "delegates to"
```

**Source**: `backend/app/db/models/skills.py`

---

## Agent Management

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

---

## Communication & Conversations

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

---

## Results, Scheduling & Notifications

```mermaid
erDiagram
    ResultRecord {
        uuid id
        uuid agent_type_id
        uuid agent_instance_id
        string title
        string content_type
        json payload
    }
    ScheduledJob {
        uuid id
        string name
        string cron_expression
        enum target_type
        uuid target_id
        enum status
    }
    JobExecution {
        uuid id
        uuid job_id
        enum status
        string error
        datetime started_at
        datetime finished_at
    }
    NotificationChannel {
        uuid id
        string name
        enum channel_type
        boolean is_active
    }
    NotificationEvent {
        uuid id
        uuid channel_id
        string subject
        string body
        string recipient
        enum status
    }

    ScheduledJob ||--o{ JobExecution : "triggers"
    NotificationChannel ||--o{ NotificationEvent : "sends"
```

**Sources**: `backend/app/db/models/results.py`, `backend/app/db/models/scheduling.py`, `backend/app/db/models/notifications.py`

---

## Cross-Domain Relationship Map

```mermaid
erDiagram
    Identity }o--|| Role : "assigned to"
    Role ||--o{ ToolPermission : "grants access to"
    McpTool ||--o{ ToolPermission : "governed by"
    McpTool ||--o{ SkillToolBinding : "bound via"
    Skill ||--o{ SkillToolBinding : "invokes via"
    Sop ||--o{ SopStep : "composed of"
    SopStep }o--o| Skill : "executes"
    SopStep }o--o| AgentType : "delegates to"
    AgentType }o--o| Sop : "bound to"
    AgentType ||--o{ AgentSkillAssignment : "has"
    AgentSkillAssignment }o--|| Skill : "assigns"
    AgentType ||--o{ AgentInstance : "spawns"
    AgentInstance ||--o{ ConversationSession : "handles"
    AgentType ||--o{ ResultRecord : "produces"
    AgentInstance ||--o{ ResultRecord : "produces"
    ScheduledJob ||--o{ JobExecution : "triggers"
    Role ||--o{ PolicyStatement : "contains"
    PlatformUser }o--o{ Role : "assigned via"
    PlatformUser }o--o{ Group : "member of"
    Group }o--o{ Role : "assigned via"
```
