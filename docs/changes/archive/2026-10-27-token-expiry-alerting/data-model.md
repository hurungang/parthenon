# Data Model — Token Expiry Alerting

Technology-agnostic view of the business entities affected by token expiry health tracking. Schema code lives in `backend/app/db/models/`; this document shows entities and relationships only.

Related docs: [PRD](./prd.md)

---

## 1. New Entities

### TokenHealthCheck (preflight outcome record — auditability)

One row per pre-execution token health evaluation performed by Control Center before an agent execution (including subagent token checks).

```mermaid
erDiagram
    TokenHealthCheck {
        uuid id
        uuid tenant_id "mandatory; tenant-scoped (strict isolation)"
        uuid agent_type_id "execution being preflighted"
        uuid session_id "agent execution session, nullable if blocked pre-submission"
        enum target_kind "agent_identity | mcp_session"
        uuid target_id "FK to checked identity or session (polymorphic reference)"
        enum health_state "healthy | expiring | expired | unknown"
        enum check_outcome "passed | blocked"
        string message "user-facing message naming the identity/session to refresh"
        datetime checked_at
    }
```

- Purpose: audit trail of preflight checks so "every expired token surfaced before a run" is provable, and blocked executions are traceable.
- `health_state` is computed at check time from token/refresh expiry timestamps; not a stored invariant.

---

## 2. Modified Entities

### AgentIdentity — add token health fields

Existing entity (`backend/app/db/models/agents.py`). Already stores encrypted tokens, `token_expires_at`, `token_status`, `last_token_refresh_at`. Modified to carry the full computed health state:

| Change | Field | Type | Purpose |
|---|---|---|---|
| New | `refresh_token_expires_at` | datetime (nullable) | Expiry of the refresh token; drives "expiring within 7 days" vs "expired" when access token can be renewed |
| New | `last_token_refresh_outcome` | enum (nullable): `success \| failure` | Outcome of the most recent automatic refresh by Control Center |
| New | `token_health_state` | enum (nullable): `healthy \| expiring \| expired \| unknown` | Computed health state surfaced on dashboard and topology; refreshed on token refresh and dashboard read |

### McpSession — add token health fields

Existing entity (`backend/app/db/models/mcp_hub.py`). Already stores `oauth_expires_at` and `oauth_refresh_expires_at`. Modified:

| Change | Field | Type | Purpose |
|---|---|---|---|
| New | `last_token_refresh_at` | datetime (nullable) | When Control Center last refreshed this session's OAuth token |
| New | `last_token_refresh_outcome` | enum (nullable): `success \| failure` | Outcome of that refresh |
| New | `token_health_state` | enum (nullable): `healthy \| expiring \| expired \| unknown` | Computed health state surfaced on dashboard and topology |

No changes to existing credential/encryption fields; token payloads remain encrypted and agent-inaccessible.

### TokenRefreshLog — no structural change

Existing audit log (`backend/app/db/models/agent_security.py`, `token_refresh_logs`) already records per-attempt outcomes for agent identities. If MCP session refreshes are routed through the same mechanism, a nullable `mcp_session_id` reference is added alongside `agent_identity_id` (exactly one set per row); otherwise the entity is unchanged.

---

## 3. Removed Entities / Fields

None. No entities or fields are dropped by this change.

---

## 4. Schema Files to Update

Per `docs/config.yaml` (`source.schema` = `backend/app/db/models/`):

| File | Change |
|---|---|
| `backend/app/db/models/agents.py` | Add `refresh_token_expires_at`, `last_token_refresh_outcome`, `token_health_state` to `AgentIdentity`; extend `AgentTokenStatus` enum values if the health state reuses it (prefer a new `TokenHealthState` enum) |
| `backend/app/db/models/mcp_hub.py` | Add `last_token_refresh_at`, `last_token_refresh_outcome`, `token_health_state` to `McpSession` |
| `backend/app/db/models/agent_security.py` | Optionally add nullable `mcp_session_id` FK on `TokenRefreshLog`; define `TokenRefreshOutcome` reuse for sessions |
| New file `backend/app/db/models/token_health.py` | `TokenHealthCheck` entity + `TokenHealthState` / `TokenCheckOutcome` enums |
| `backend/app/db/models/__init__.py` | Export the new model so autogenerate detects it |

---

## 5. Updates to `docs/master/data-model/`

| File | Update |
|---|---|
| `docs/master/data-model/modules/identity/entities.md` | Add the three new `AgentIdentity` token-health attributes to the Identity/agent-identity erDiagram block; add `TokenHealthCheck` entity and its relationship to AgentIdentity |
| `docs/master/data-model/modules/mcp-hub/entities.md` | Add the three new `McpSession` token-health attributes to the McpSession erDiagram block |
| `docs/master/data-model/modules/security/entities.md` | Add `TokenHealthCheck` (preflight audit) alongside existing `TokenRefreshLog` / certificate audit entities |
| `docs/master/data-model/overview.md` | One-line note under the relevant domain summary: token expiry health tracking exists for agent identities and MCP sessions (healthy / expiring ≤7 days / expired) |

Keep module docs reference-based — entity lists + source file pointers, no schema code.

---

## Relationship Summary (full view)

```mermaid
erDiagram
    Tenant ||--o{ AgentIdentity : "owns"
    Tenant ||--o{ McpServer : "owns"
    Tenant ||--o{ TokenHealthCheck : "scopes"
    AgentIdentity ||--o{ TokenRefreshLog : "refresh attempts logged for"
    AgentIdentity ||--o{ TokenHealthCheck : "preflighted as"
    McpServer ||--o{ McpSession : "has"
    McpSession ||--o{ TokenHealthCheck : "preflighted as"
    McpSession }o--o| AgentIdentity : "bound to via identity_binding"
    AgentType ||--o{ TokenHealthCheck : "preflight before execution"
    McpSession {
        uuid id
        uuid server_id
        string name
        enum auth_type
        string encrypted_credentials
        datetime oauth_expires_at
        datetime oauth_refresh_expires_at
        datetime last_token_refresh_at "NEW"
        enum last_token_refresh_outcome "NEW: success|failure"
        enum token_health_state "NEW: healthy|expiring|expired|unknown"
        boolean is_active
        boolean is_default
    }
    AgentIdentity {
        uuid id
        uuid tenant_id
        string name
        enum identity_type
        enum status
        datetime token_expires_at
        datetime refresh_token_expires_at "NEW"
        datetime last_token_refresh_at
        enum last_token_refresh_outcome "NEW: success|failure"
        enum token_health_state "NEW: healthy|expiring|expired|unknown"
        boolean is_active "via status"
    }
    TokenHealthCheck {
        uuid id
        uuid tenant_id
        uuid agent_type_id
        uuid session_id
        enum target_kind "agent_identity|mcp_session"
        uuid target_id
        enum health_state
        enum check_outcome "passed|blocked"
        string message
        datetime checked_at
    }
    TokenRefreshLog {
        uuid id
        uuid agent_identity_id
        uuid mcp_session_id "NEW, nullable"
        datetime attempted_at
        enum outcome
        int retry_attempt
        datetime next_retry_at
    }
```

**Source files**: `backend/app/db/models/agents.py`, `backend/app/db/models/mcp_hub.py`, `backend/app/db/models/agent_security.py`
