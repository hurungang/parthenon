# Results, Scheduling & Notifications — Entities

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

| Entity | Description |
|--------|-------------|
| **ResultRecord** | A structured output saved by an agent or SOP via the `save_result` tool; accessible through the result repository. |
| **ScheduledJob** | A cron-based schedule that triggers a prompt or SOP execution; carries active or paused status. |
| **JobExecution** | A record of a single run of a ScheduledJob, capturing when it fired and whether it succeeded or failed. |
| **NotificationChannel** | A configured outbound destination for notifications; type is one of: email, Slack, Teams, or webhook. |
| **NotificationEvent** | A record of a notification dispatched by an agent or workflow to a NotificationChannel, including delivery outcome. |
