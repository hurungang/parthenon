# Data Model: Sandboxed Scripting Follow-ups

Technology-agnostic; all schema changes are Control-Center-owned (sole database gateway). Migration via Alembic autogenerate; enum/column changes follow project conventions (`postgresql.ENUM(..., create_type=False)`, reversible downgrades).

## 1. McpSession — new fields

Location: `backend/app/db/models/mcp_hub.py` (verified: `McpSession` lives here).

```mermaid
erDiagram
    MCP_SESSION {
        uuid id PK
        uuid server_id FK
        string name
        string auth_type
        bool "requires_reauth (NEW)"
        text "last_refresh_error (NEW)"
    }
```

- `requires_reauth` (boolean, default false) — set when a token refresh fails unrecoverably (e.g. the identity provider reports the refresh token no longer exists); cleared when the user completes in-place re-auth on the SAME session.
- `last_refresh_error` (text, nullable) — the failure reason at the time the flag was set; cleared together with the flag.
- Transient refresh failures (network, temporary provider errors) must NOT set the flag.

## 2. OptimizedImplementationPlan — `error` must be populated (no schema change)

Location: `backend/app/db/models/optimized_plan.py` (verified: `error: Text, nullable` already exists).

```mermaid
erDiagram
    OPTIMIZED_IMPLEMENTATION_PLAN {
        int id PK
        uuid agent_type_id FK
        string status
        text "error (EXISTS - must be populated on needs_feedback)"
        text steps_json
    }
    MCP_SESSION }o--|| MCP_SERVER : "belongs to"
    OPTIMIZED_IMPLEMENTATION_PLAN }o--|| AGENT_TYPE : "targets"
```

No migration required for this entity. The requirement is behavioural: whenever optimize-and-verify ends in `needs_feedback`, the service or the authoring agent (via `generate_optimized_plan(error=...)`) must persist the failure reason; the Optimized Plan tab renders it.

## 3. Script Execution Record — outcome semantics (no schema change unless an outcome enum lacks the value)

Execution records must be able to express a partial failure (tool call returned a semantic error report). If the existing outcome representation cannot express it, extend the outcome enumeration (Alembic `ALTER TYPE ... ADD VALUE` via string-formatted DDL); otherwise no change.

## 4. Everything Else

All other predecessor entities (ScriptVersion, ScriptExecutionRecord accounting fields, LLMMockRecording, plan status enums incl. `retired`) are unchanged.
