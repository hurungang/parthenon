# MCP Hub Architecture

## Overview

The MCP Hub (inside Control Center) is the registry, credential store, and proxy for all registered MCP tool servers. Every registered server has a **slug that is unique per tenant** — the business identity is `(tenant_id, slug)`, not a platform-wide slug. All tools synced from a server are stamped with the server's tenant (`McpTool.tenant_id`), so a tool exists only inside its owning tenant's namespace.

```mermaid
flowchart TB
    TEN[Tenant A / Tenant B]
    REG[(MCP Server Registry<br/>slug unique per tenant)]
    TS[Tool Sync Service<br/>tenant-bound upserts]
    TN[(MCP Tools<br/>tenant-stamped)]
    RES[Tool Name Resolver<br/>tenant-qualified at resolution time]
    SK[Skill Bindings + Permission Grants<br/>same-tenant containment]
    SCH[Scheduler<br/>tenant bound at creation + dispatch]
    EXT[External MCP Servers]
    CS[Credential Store<br/>AES-256, decrypt at call time]

    TEN --> REG
    REG --> TS --> TN
    TN --> RES
    RES --> SK
    SK --> SCH
    RES --> EXT
    EXT --> CS
```

## Per-Tenant Slug & Tool Namespace

- A slug collision across tenants is normal: tenant A and tenant B may each register an MCP server with slug `supabase`. Lookups are always `(tenant, slug)`; the other tenant's row is invisible to resolution.
- Tool sync (`ToolSyncService`) upserts tools under the owning tenant's namespace with a denormalized tenant binding on each tool row.
- The **wire format is unchanged**: `server____tool` and `agent____<slug>` are the names agents and MCP clients see. Tenant qualification happens **at resolution time only** — the slug component is matched against the calling tenant's own registry. Existing permission grants and skill bindings that reference old global tool names keep working.
- Skill → MCP tool bindings and `ToolPermission` grants resolve only against tools of the **same tenant**; a grant in tenant A never authorizes tenant B's same-named tool.

## Reserved Namespaces

The `system`, `decision`, and `cc` server names are reserved namespaces (`RESERVED_SERVER_NAMES`) and are tenant-neutral in the wire format but resolved within the caller's tenant:

- **`system____*`** — platform system tools (`save_data`, `get_data`, `get_output`, `query_result`, `send_notification`, `get_recipient_group`, …), routed to CC internal endpoints.
- **`decision____*`** — decision tools. These are **virtual bindings with no `mcp_tools` rows**: they are registered via skill bindings against the tenant's configured decision provider. In AR, the tool-routing layer classifies `decision____` names before MCP proxying and dispatches them to the decision-tool service, which resolves data types and execution strictly within the calling tenant (exact `tenant_id` match; the old `IS NULL OR own` shared-slot pattern is removed). Decision-provider vendor differences are abstracted behind the Control Center multi-provider client factory, so provider backends are selected per resolved tenant, not hard-wired. Decision tools appear in `tools/list` and the skill-editor tool picker alongside system tools as `decision____<name>`; skills themselves are unchanged by this pathway. See [Decision Tools Architecture](../decision-tools/architecture.md).
- **`cc____*`** — Control Center management and meta tools (`create_*` / `update_*` / `list_*` / `get_*`), hosted on a dedicated **per-tenant Control Center entity** rather than the System entity, so management capability is granted independently of general system tools. The entity is system-managed (seeder-only writer, immutable, sessionless) and its visibility is gated by `integration::control_center`; invocation is gated by tool grants plus per-tool permission parity. See [Control Center Architecture](../control-center/architecture.md).

## A2A Delegation Naming

`agent____<slug>` delegation targets are resolved strictly by `(tenant, name)` at CC (`prepare_a2a_request`) and CH `/internal/a2a` forwarding. Name collisions across tenants never route cross-tenant.

## Scheduler Tenant Binding

Scheduled jobs carry a mandatory `tenant_id` at creation (NULL is a hard error). Dispatch resolves a single owning tenant — no `agent_type.tenant_id` fallback — and the job runs fully within that tenant's context: tenant scoping, quotas (consulted at dispatch time in CC), and signed tenant headers on the downstream execution chain. See [Scheduling Architecture](../scheduling/architecture.md).

## MCP Session Token Health

MCP sessions expose session-level token health (credential/identity bindings and their expiry state) so Control Center can classify each session alongside agent identity tokens. Classification feeds the same Token Health Service — expired sessions block executions that would use them (via the CH preflight gate), expiring-soon sessions warn. How tokens are injected per tool call is unchanged, and tokens still never cross to agents.

```mermaid
flowchart LR
    MS[MCP Sessions<br/>session token health]
    CC[Control Center<br/>Token Health Service]
    CH[Communication Hub<br/>preflight gate]
    FE[Dashboard token health cards]

    MS -->|session health metadata| CC
    CH -->|preflight check| CC
    FE -->|health per category| CC
```

## Tool Execution Chain

Tool invocation follows the existing Skill Engine → MCP Hub → External MCP Server chain, with the calling tenant's context carried end to end on signed internal headers. Session types (named encrypted-credential sessions vs. passthrough agent-JWT) are unchanged; identity tokens are resolved by Control Center within the tenant's scope only. See [Tool Execution](../tool-execution.md) for the call sequences.
