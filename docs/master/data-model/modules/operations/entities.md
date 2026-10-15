# Results, Scheduling & Notifications — Entities

All entities below carry a **mandatory tenant binding**: every row belongs to exactly one tenant (when multi-tenancy is disabled, everything binds to the root tenant — never tenant-less). Retrieval, dispatch, and query paths match the exact calling tenant only; there is no shared/global slot and no fallback.

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
    DecisionExecutionResult {
        uuid id
        uuid tenant_id "mandatory; append-only history, always tenant-filtered"
        uuid decision_tool_id
        uuid conversation_session_id "nullable"
        json input_state_snapshot
        json answers "per question: typed value, probabilities, confidence"
        enum outcome "act | confirm | escalate"
        enum status "completed | failed"
        string error_message
        string provider_model
        datetime created_at
    }
    ScheduledJob {
        uuid id
        uuid tenant_id "mandatory at creation; unique name per tenant"
        string name
        string cron_expression
        enum target_type
        uuid target_id "same tenant"
        uuid scheduled_by_user_id "nullable; FK -> Identity (schedule creator)"
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
    Identity {
        uuid id
        string subject
        string display_name
    }
    NotificationChannel {
        uuid id
        uuid tenant_id "mandatory; name unique per tenant"
        string name
        enum channel_type
        boolean is_active
    }
    ChannelProperty {
        uuid id
        uuid channel_id
        string key
        string encrypted_value
        boolean is_secret
    }
    RecipientGroup {
        uuid id
        uuid tenant_id "mandatory; name and slug unique per tenant"
        string name
        string slug
        boolean is_active
    }
    GroupChannelMapping {
        uuid id
        uuid group_id
        uuid channel_id "same tenant"
    }
    NotificationLog {
        uuid id
        uuid tenant_id "mandatory"
        uuid group_id
        uuid channel_id
        enum source_type "SOP, AGENT, MANUAL"
        enum status "PENDING, DELIVERED, FAILED"
    }

    DecisionTool ||--o{ DecisionExecutionResult : "produces"
    ConversationSession |o--o{ DecisionExecutionResult : "records"
    ScheduledJob ||--o{ JobExecution : "triggers"
    Identity ||--o{ ScheduledJob : "scheduled by"
    NotificationChannel ||--o{ ChannelProperty : "configured via"
    NotificationChannel ||--o{ GroupChannelMapping : "assigned to"
    RecipientGroup ||--o{ GroupChannelMapping : "delivered via"
    RecipientGroup ||--o{ NotificationLog : "notified in"
    NotificationChannel ||--o{ NotificationLog : "sent through"
```

**Sources**: `backend/app/db/models/results.py`, `backend/app/db/models/scheduling.py`, `backend/app/db/models/notifications.py`, `backend/app/db/models/decision_tools.py`, `backend/app/db/models/identity.py`

| Entity | Description |
|--------|-------------|
| **ResultRecord** | A structured output saved by an agent or SOP via the `save_data` tool; accessible through the result repository. |
| **DecisionExecutionResult** | Append-only audit record of each decision-tool execution: input state snapshot, per-question typed answers with probabilities and confidence, and the computed gate outcome (`act` / `confirm` / `escalate`). Scoped to the owning tenant of the decision tool. |
| **ScheduledJob** | A cron-based schedule that triggers an agent execution; **tenant-bound at creation**, and dispatch never falls back through `job → agent type` chains across tenants — each job executes under its owning tenant's context. |
| **JobExecution** | A record of a single run of a ScheduledJob; inherits tenant scope via its parent job. |
| **NotificationChannel** | A configured outbound destination for notifications; type is one of: email, Slack, Teams, or webhook. Name unique per tenant. |
| **RecipientGroup** | A named, tenant-bound audience; agents and SOPs target a group by `slug`, resolved within the calling tenant only (name and slug unique per tenant). |
| **GroupChannelMapping** | Many-to-many association between recipient groups and channels; both sides share the same tenant. |
| **NotificationLog** | Immutable, tenant-attributed delivery record per channel attempt, including delivery outcome and error detail. |

**Dispatch tenant binding:** notification dispatch resolves the recipient group and its channel mappings within the calling tenant only. The global NULL-tenant "shared slot" is no longer a dispatch target, and channel lookup by id also verifies tenant containment.
