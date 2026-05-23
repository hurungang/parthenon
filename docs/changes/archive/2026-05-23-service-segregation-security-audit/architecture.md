# Architecture: Service Segregation Security Audit

This target state enforces strict segregation across the three backend services. Control Center is the only database-connected service, Agent Runtime is the only place where agents execute, and caller-specific allowlists apply deny-by-default access control.

## 1) Changed Components

```mermaid
flowchart LR
    UI[Web UI]
    CH[Communication Hub]
    AR[Agent Runtime]

    subgraph CC[Control Center]
        CCA[Control Center API]
        PE[Policy Enforcement]
        CHAL[CH Allowlist]
        ARAL[AR Allowlist]
        AUD[Security Audit Log]
    end

    DB[(Platform DB)]

    UI -->|User API calls| CCA
    UI <-->|Realtime messaging| CH
    CCA -->|Execution trigger| AR
    AR -->|Runtime data APIs| CCA
    CH -->|Hub-essential APIs| CCA
    PE --> CHAL
    PE --> ARAL
    CCA --> PE
    PE --> AUD
    CCA --> DB
```

This model separates responsibilities by service boundary and keeps all privileged data access behind Control Center.

## 2) Caller-Based Access Control Model

```mermaid
erDiagram
    CALLER_TYPE ||--o{ API_ALLOWLIST_POLICY : has
    API_ALLOWLIST_POLICY ||--o{ ALLOWLIST_RULE : defines
    CC_API_ENDPOINT ||--o{ ALLOWLIST_RULE : constrained_by
    ALLOWLIST_RULE ||--o{ DENY_EVENT : emits_when_blocked
    DENY_EVENT }o--|| SECURITY_AUDIT_EVIDENCE : captured_in
```

```mermaid
flowchart TB
    ARP[Caller: Agent Runtime]
    CHP[Caller: Communication Hub]
    PEP[CC Policy Enforcement]
    ARW[Allowlist: Runtime-essential only]
    CHW[Allowlist: Hub-essential only]
    DENY[Deny by default for all non-allowlisted endpoints]

    ARP --> PEP
    CHP --> PEP
    PEP --> ARW
    PEP --> CHW
    ARW --> DENY
    CHW --> DENY
```

This control model ensures Communication Hub and Agent Runtime are granted only the minimal Control Center API access required for their distinct responsibilities, with blocked attempts recorded as audit evidence.

## 3) Integration Boundaries

```mermaid
flowchart LR
    UI2[Web UI]
    CH2[Communication Hub]
    AR2[Agent Runtime]
    CC2[Control Center]
    DB2[(Platform DB)]

    UI2 -->|No direct DB or runtime-control APIs| CC2
    UI2 <-->|Conversation and events| CH2
    CH2 -->|Caller=CH; CH allowlist required| CC2
    AR2 -->|Caller=AR; AR allowlist required| CC2
    CC2 -->|Only component with DB connectivity| DB2
    CH2 -.->|Blocked: no DB path| DB2
    AR2 -.->|Blocked: no DB path| DB2
```

These boundaries enforce the top-priority rules: no direct database path outside Control Center and no privilege overlap by default between Communication Hub and Agent Runtime.

## 4) Primary Data Flow

```mermaid
flowchart TB
    UI3[Web UI]
    CH3[Communication Hub]
    AR3[Agent Runtime]
    CC3[Control Center]
    DB3[(Platform DB)]

    UI3 <-->|1. User conversation traffic| CH3
    CH3 -->|2. Hub-essential API requests| CC3
    CC3 -->|3. Dispatch execution intent| AR3
    AR3 -->|4. Runtime context and result APIs| CC3
    AR3 -->|5. Tool call forwarding| CH3
    CC3 -->|6. Read and write platform state| DB3
    CH3 -.->|Denied: any non-allowlisted CC endpoint| CC3
    AR3 -.->|Denied: any non-allowlisted CC endpoint| CC3
```

This flow keeps user interaction, runtime execution, policy enforcement, and persistence concerns clearly separated while preserving full auditability of denied access attempts.

## 5) Master Documentation Alignment

```mermaid
flowchart TB
    SO[system-overview.md]
    CCM[modules/control-center.md]
    CHM[modules/communication-hub.md]
    ARM[modules/agent-runtime.md]
    SEC[security/certificate-management.md]

    U1[Add caller-specific CC API allowlists and deny-by-default control]
    U2[Add explicit allowed and blocked interaction matrix for UI CH AR CC DB]
    U3[State separation of CH and AR privileges with no overlap by default]
    U4[Add audit evidence expectations for blocked access attempts]
    U5[Reinforce that only CC accesses DB and agents never receive sensitive identity data]

    SO --> U1
    SO --> U2
    CCM --> U1
    CCM --> U4
    CHM --> U3
    ARM --> U3
    SEC --> U4
    SO --> U5
    ARM --> U5
```

Update [docs/master/architecture/system-overview.md](docs/master/architecture/system-overview.md), [docs/master/architecture/modules/control-center/architecture.md](docs/master/architecture/modules/control-center/architecture.md), [docs/master/architecture/modules/communication-hub/architecture.md](docs/master/architecture/modules/communication-hub/architecture.md), [docs/master/architecture/modules/agent-runtime/architecture.md](docs/master/architecture/modules/agent-runtime/architecture.md), and [docs/master/architecture/security/certificate-management.md](docs/master/architecture/security/certificate-management.md) to reflect these boundaries and controls at the same high level.