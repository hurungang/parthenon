# Control Center Architecture

## API Layer and Authentication

```mermaid
flowchart LR
    UI[Web UI]
    CH[Communication Hub]
    AR[Agent Runtime]
    API[Control Center APIs]
    AM[Auth Middleware]
    SAR[Super Admin Auth Service]
    OPR[OIDC Provider Registry]
    SCAPI[System Config API]
    OCR[OIDC Config Service]
    DB[(Platform DB)]

    UI --> API
    CH -->|Caller: communication_hub| API
    AR -->|Caller: agent_runtime| API
    API --> AM
    AM -->|1. super admin| SAR
    AM -->|2. OIDC JWT| OPR
    API --> SCAPI
    SCAPI --> OCR
    SAR --> DB
    OCR --> DB
    OPR --> DB
```

## Core Platform Services

```mermaid
flowchart LR
    API[Control Center APIs]
    AKM[API Key Management Service]
    POL[Policy Resolution Service]
    CTX[Governed Context Assembler]
    CFG[Generation Model Resolver]
    SOP[Default SOP Resolver]
    GOV[Governance and Audit Service]
    ELS[Execution Log Store]
    IRS[Intervene Request Store]
    CIT[Conversation Intervention Turns]
    TOPO[Runtime Topology Controller]
    TERM[Termination Orchestrator]
    CH[Communication Hub]
    DB[(Platform DB)]

    API --> AKM
    API --> POL
    API --> CTX
    API --> ELS
    API --> IRS
    API --> CIT
    API --> TOPO
    API --> TERM
    API --> GOV
    AKM --> DB
    CTX --> CFG
    CTX --> SOP
    CFG --> DB
    SOP --> DB
    POL --> DB
    GOV --> DB
    TOPO --> DB
    TERM --> CH
    CTX --> CH
```

## Data Management and Observability

```mermaid
flowchart LR
    API[Control Center APIs]
    DTR[Data Type Registry]
    OS[Output Store]
    SV[Schema Validation Service]
    DB[(Platform DB)]
    OBS[Observability]
    POL[Policy Resolution Service]
    GOV[Governance and Audit Service]
    TERM[Termination Orchestrator]

    API --> DTR
    API --> OS
    API --> SV
    DTR --> DB
    OS --> DB
    SV --> DTR
    POL --> OBS
    GOV --> OBS
    TERM --> OBS
```

```mermaid
flowchart TB
    CALL[Inbound caller request]
    AUTH[Caller scope check]
    POLICY[Resolve effective guardrail policy]
    CONTEXT[Assemble governed context]
    DECIDE[Allow or deny decision]
    LOG[Governance event recording]
    REPLY[Policy and context response]
    DB[(Platform DB)]

    CALL --> AUTH
    AUTH --> POLICY
    POLICY --> CONTEXT
    CONTEXT --> DECIDE
    DECIDE --> LOG
    LOG --> DB
    DECIDE --> REPLY
    AUTH -->|Scope mismatch| LOG
```

## Auth Middleware & OIDC Provider Registry

Control Center authentication is a three-tier pipeline shared across all inbound API calls:

```mermaid
flowchart TD
    REQ[Inbound Request] --> AM[Auth Middleware]

    AM --> SA{Super Admin<br/>enabled & token?}
    SA -->|yes| SAR[Super Admin Auth Service]
    SAR -->|bcrypt verify| SAC[(super_admin_credentials)]
    SAR -->|short-lived JWT| ID[Identity + Permissions]

    SA -->|no| OIDC{OIDC Bearer<br/>token?}
    OIDC -->|yes| OPR[OIDC Provider Registry]
    OPR -->|hot-reload| IPC[(identity_provider_configs)]
    OPR -->|JWKS validate| ID

    OIDC -->|no| PUB{Public Path?}
    PUB -->|yes| ANON[Anonymous]
    PUB -->|no| DENY[403]
```

### Super Admin Auth Service

- Stores bcrypt-hashed credentials in the `super_admin_credentials` table
- Issues short-lived internal JWTs (default 15-minute expiry, configurable)
- Seeded on first launch from environment variables (`SUPER_ADMIN_ENABLED`, `SUPER_ADMIN_USERNAME`, `SUPER_ADMIN_PASSWORD_HASH`)
- Enable/disable toggle: when disabled, all super admin login attempts are refused regardless of credentials
- Bypasses OIDC entirely — no external IdP dependency for super admin access

### OIDC Provider Registry

- In-memory cache of active provider configurations loaded from `identity_provider_configs` at startup
- Hot-reload: invalidated and refreshed when OIDC Config Service updates a provider, no restart required
- Caches JWKS keys per provider with TTL-based refresh
- Resolves provider type (`user` vs `agent`) from token claims or request context
- Supports concurrent multi-provider operation — separate issuers for users and agents

## OIDC Config Service

- Full CRUD for identity provider configurations in the `identity_provider_configs` table
- Validates OIDC Discovery endpoints (issuer reachability, `.well-known/openid-configuration` fetch)
- Encrypts client secrets at rest
- Supports provider type enumeration: `user` and `agent`
- Each provider entry: issuer URL, client ID, encrypted client secret, scopes, claims mapping
- Replaces the legacy static `config/identity.yaml` approach; DB is the source of truth

## System Config API — Identity Provider Endpoints

JWT-protected endpoints for managing identity provider configurations, super admin settings, and OIDC connectivity testing. All provider configuration is stored in the database and loaded at startup by the OIDC Provider Registry. Client secrets are encrypted at rest via AES-256-GCM.

## API Key Management Service

A new set of CC API endpoints and service logic for CRUD operations on API keys. Platform administrators provision API keys for external agent identities through JWT-protected REST endpoints.

- **Create**: Admin selects an existing agent identity and agent role; CC generates a cryptographically random key, stores its SHA-256 hash, and returns the clear-text key once
- **List**: Returns all keys with bound identity, role, status, creation date, and last-used date
- **Revoke**: Sets key status to `revoked`; immediately invalidates it for future authentication
- **Internal Validation**: mTLS-protected endpoint called exclusively by Communication Hub. CH sends the hashed key value; CC looks up the hash, checks status, resolves the bound identity/role/permission set, and returns the identity token. External agents never receive this token — CH holds it internally for MCP proxying.

### API Key Store (`agent_api_keys` table)

New table in the Platform DB storing SHA-256 hashed key values with metadata including identity binding, role assignment, status, and timestamp tracking. Managed through CC's standard model and Alembic migration toolchain.

### Permission Resolution Chain (API Key Path)

API keys reuse the existing permission engine without modification. The resolution chain is:

`API Key → bound agent identity → bound agent role → policy evaluation → allowed tools/skills/SOPs`

This is the same model used by internal agents — the API key provides an alternative entry point into the identity → role → permission resolution chain.

## Conversation Intervention Persistence

- **Conversation Intervention Turns**: Extension of `ConversationTurn` persistence to support `intervene_request` and `intervene_response` turn types. Stores intervention type (approval/choice/text), prompt text, available options, operator identity, response value, and timestamp. Turns are persisted in chronological order within the conversation stream for audit traceability.
- **Intervene Request Store**: Extended to accept and persist conversation context fields (`conversation_session_id`, `delegation_depth`) on `InterveneRequest`. Automatically creates paired `intervene_response` conversation turns when responses are submitted to conversation-scoped requests. Non-conversational flow (no `conversation_session_id`) is unchanged.

## Task Delegation Event Persistence

- **Execution Log Store**: Accepts new delegation-related execution log event types: `delegation_started`, `delegation_waiting`, `delegation_resumed`, `delegation_depth_blocked`, `delegation_timeout`, `delegation_failed`. These are persisted to the `ExecutionLogEntry` table via the internal log append endpoint and delivered to log viewers via the existing NDJSON stream.
- **Parent-Child Resolution**: Non-conversational intervention requests use the existing `AgentJob.parent_job_id` FK chain to resolve parent context — `InterveneRequest.agent_session_id` identifies the sub-agent session, and the parent is reached via FK traversal. No new schema columns were added.
- **Pending Intervention Query**: Returns outstanding intervention requests for a task agent session, used by the execution log viewer on reconnect to re-surface dialogs.
- **Delegation Status Query**: Returns current delegation state (active sub-agent types, depths, exit conditions) by querying recent delegation-related `ExecutionLogEntry` entries.

## Agent Data Type Registry

- **Data Type Registry**: Centralized catalogue of reusable typed schemas (`AgentDataType` model) stored in the `agent_data_types` table. Each data type defines a name, slug (canonical runtime identifier), description, and an ordered array of field definitions with types: `string`, `number`, `boolean`, `date`, `enum`. Administrators manage data types via CRUD REST endpoints. The registry enforces uniqueness on name and slug, blocks deletion when referenced by agent types (409 Conflict with referencing type list), and requires at least one field per data type.
- **API**: JWT-protected CRUD endpoints for data types. A `?usage=true` query returns referencing agent type counts for delete-guard UI.

## Output Store

- **Output Store** (`AgentOutput` model): Immutable typed output records in the `agent_outputs` table. Each record links to a data type, agent type, execution session, stores field values matching the data type schema, validation status (valid or validation_error), and raw output fallback. Queried by data type, agent type, date range, and session.
- **Agent Outputs Page**: Paginated JWT-protected query and CSV export endpoints.
- **Internal API**: mTLS-protected endpoints for Agent Runtime output persistence and `query_result` tool queries.
- **System Tool Endpoints** (mTLS-protected): Persists `AgentData` intermediate records, queries `AgentData` with filter guard, queries `AgentOutput` by filters, and resolves data type names to return matching typed outputs.

## Schema Validation Service

- **Schema Validation Service**: Lightweight payload validator invoked by Agent Runtime via mTLS. Accepts a data type ID and a payload, fetches the schema from the Data Type Registry, validates field types (string, number, boolean, ISO 8601 date, enum membership), required field presence, and default values. Returns validation result with field-level error details. Validation failure does not block execution — results are persisted with `validation_error` status and the raw output as fallback.
