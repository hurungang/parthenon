## Changed Components

### Control Center (CC)

- **New sub-component: Scheduling Engine** — runs inside the Control Center process, managing APScheduler-based cron job registration, execution dispatch, and lifecycle
- **Config** — New `scheduler_check_interval_seconds` field in `backend/app/core/config.py` Settings class alongside existing `scheduler_enabled`

### Agent Runtime (AR)

- **No changes** — agent execution remains triggered via the existing `AgentInstanceManager.spawn()`/`activate()` flow. The scheduler is a client of the agent runtime, not a modifier.

### Communication Hub (CH)

- **No changes** — scheduling is a Control Center internal concern. CH already handles agent execution requests.

## New Components

```mermaid
flowchart TD
    CC[Control Center] --> SE[Scheduling Engine]
    SE --> APS[APScheduler]
    SE --> DB[(PostgreSQL\nscheduled_jobs)]
    SE --> AMM[AgentInstanceManager]
    SE --> SO[SopOrchestrator]

    subgraph "Scheduling Engine"
        APS --> |cron trigger| EJ[Execute Job]
        EJ --> DC{Check Status}
        DC --> |active| DI[Dispatch]
        DI --> |agent| AMM
        DI --> |sop| SO
        EJ --> JR[JobExecution Record]
        JR --> DB
    end

    subgraph "Startup Recovery"
        CC --> |on startup| SR[Schedule Recovery]
        SR --> |load active| DB
        SR --> |register triggers| APS
    end
```

## Integration Points

| Integration | Direction | Protocol | Description |
|-------------|-----------|----------|-------------|
| SchedulingEngine → DB | read/write | SQLAlchemy async | Load active schedules, record job executions |
| SchedulingEngine → AgentInstanceManager | internal call | Python async | Spawn/activate/close agent instances for agent-type targets |
| SchedulingEngine → SopOrchestrator | internal call | Python async | Execute SOP targets with prompt and context |
| Config → SchedulingEngine | read | Pydantic Settings | Read `scheduler_enabled`, `scheduler_check_interval_seconds` |

## Data Flow Changes

```mermaid
sequenceDiagram
    participant Admin as Administrator
    participant UI as Frontend UI
    participant API as CC API
    participant SE as Scheduling Engine
    participant DB as PostgreSQL
    participant AR as Agent Runtime

    Admin->>UI: Create schedule (cron + payload)
    UI->>API: POST /api/v1/schedules
    API->>DB: Insert scheduled_job
    API->>SE: add_job()
    SE->>APS: register cron trigger
    API-->>UI: 201 Created

    Note over SE,AR: Cron fires

    SE->>SE: _execute_job()
    SE->>DB: Query job status
    SE->>DB: Insert JobExecution (running)
    SE->>SE: _dispatch()
    alt Target is agent
        SE->>AR: manager.spawn() + activate()
        AR-->>SE: session_handle
        SE->>AR: handler.request(prompt, payload)
        AR-->>SE: result
        SE->>AR: manager.close()
    else Target is SOP
        SE->>SE: sop_orchestrator.execute()
    end
    SE->>DB: Update JobExecution (success/failure)

    Note over SE,DB: Service restart

    CC->>SE: on startup - recover_schedules()
    SE->>DB: SELECT * FROM scheduled_jobs WHERE status = 'active'
    SE->>APS: register_cron_trigger() for each
```

## Master Arch Update Instructions

- Add Scheduling Engine as a sub-component of Control Center in `docs/master/architecture/system-overview.md`
- Add the Mermaid flowchart from this document to show Scheduling Engine internals
- Add the integration points table to the Control Center module docs
