# Spec Delta: strict-tenant-isolation

## Affected Spec Areas

- `docs/master/product/features/multi-tenancy.md` — strict tenant isolation rule on the data plane
- `docs/master/product/features/mcp-hub.md` — tenant-scoped MCP server slugs, tool namespaces, and permission grants
- `docs/master/product/features/agent-gateway.md` — tenant-scoped tool resolution and internal endpoint tenant enforcement
- `docs/master/product/features/communication-hub.md` — tenant-aware tool namespacing and MCP protocol server resolution
- `docs/master/product/features/skill-management.md` — tenant-scoped skills, skill bindings, and SkillSeeder
- `docs/master/product/features/agent-a2a-communication-and-slug-enforcement.md` — tenant-scoped A2A delegation name resolution
- `docs/master/product/features/agent-data-types.md` — retirement of NULL-tenant shared slot for data types
- `docs/master/product/features/agent-data.md` — tenant scoping of save_data/get_data
- `docs/master/product/features/agent-outputs.md` — tenant scoping of outputs and query_result
- `docs/master/product/features/notification-integration.md` — tenant-scoped recipient groups and dispatch
- `docs/master/product/features/schedule-management.md` — tenant-bound scheduled jobs
- `docs/master/product/features/agent-runtime-security.md` — virtual tenant awareness in Agent Runtime
- `docs/master/product/features/agent-runtime-monitor.md` — runtime visibility per tenant

## New Capabilities

- **Tenant-scoped MCP hub**: each tenant can register its own MCP servers with arbitrary slugs, independent of any other tenant; slugs are unique per tenant, not platform-wide.
- **Per-tenant tool namespaces**: tool names are namespaced and resolved within the calling tenant's context; identical tool names can coexist across tenants.
- **Virtual tenant awareness in Agent Runtime**: agents run under a resolved tenant binding; every tool invocation, data access, and delegation resolves against the calling tenant only.
- **One-time legacy adoption migration**: existing NULL-tenant shared rows (data types, seeded skills, scheduled jobs, shared recipient groups, any other NULL-tenant business rows) are adopted into the root tenant in a single idempotent migration.

## Modified Capabilities

- **MCP server slug uniqueness** — before: slug unique platform-wide; after: slug unique per tenant; tool sync, name building/parsing, and permission grants all operate per tenant.
- **Internal service endpoints (`/api/v1/internal/*`)** — before: tenant-scoped only if signed `X-Internal-Tenant-*` headers present (fail-open); after: signed tenant headers required; requests without a valid binding are rejected (fail closed), and all queries filter strictly by the bound tenant.
- **query_result system tool** — before: resolves AgentDataType by slug/name across all tenants and queries AgentOutput unfiltered; after: resolves the data type within the calling tenant only and filters outputs by tenant.
- **save_data / get_data (AgentDataService)** — before: records written without tenant binding and retrieved unfiltered; after: records always written with the calling tenant binding and retrieval filtered strictly by tenant.
- **Internal outputs / agent-data listing APIs** — before: unfiltered; after: return only the signed tenant's records.
- **A2A delegation** — before: target agent type resolved by name only (cross-tenant hijack possible); after: resolved by (tenant, name); delegation names including `agent____<slug>` style names are tenant-qualified.
- **get-recipient-group** — before: unfiltered; after: returns only the bound tenant's groups.
- **Notification dispatch** — before: always resolves the NULL-tenant "shared" recipient-group slot; after: resolves the calling tenant's own recipient group; tenant-scoped groups are reachable and the shared slot is retired on the data plane.
- **AgentDataType lookup** — before: `tenant_id IS NULL OR own tenant` pattern allowing all tenants to reference a shared slot; after: strict exact tenant match only.
- **SkillSeeder** — before: seeds global NULL-tenant skills visible to all tenants; after: seeds skills into the target tenant (root tenant for platform defaults).
- **Scheduler** — before: dispatches NULL-tenant jobs with no tenant binding; after: every job is tenant-bound at creation and dispatched under its owning tenant's context.

## Removed Capabilities

- **NULL-tenant "shared slot" on the data plane**: no business-data lookup may use `tenant_id IS NULL OR own` matching; the shared recipient-group slot, shared NULL-tenant data types, globally seeded NULL-tenant skills, and NULL-tenant scheduled jobs are removed as concepts.
- **Platform-wide MCP slug uniqueness**: replaced by per-tenant uniqueness (not a user-facing capability loss — it is a conflict removal).

## Spec Update Instructions

- `docs/master/product/features/multi-tenancy.md`: state the strict data-plane rule explicitly — every tenant fully independent; root tenant for platform users and as the single tenant when multi-tenancy is disabled; no cross-tenant fallback/sharing/visibility; fail-closed internal tenant binding.
- `docs/master/product/features/mcp-hub.md`: change slug uniqueness from platform-wide to per-tenant; describe per-tenant tool namespaces and tenant-scoped permission grants.
- `docs/master/product/features/communication-hub.md` and `agent-gateway.md`: document tenant-aware tool name building/parsing and MCP protocol tool resolution per calling tenant; document that internal endpoints require signed tenant headers and fail closed.
- `docs/master/product/features/skill-management.md`: skills, skill bindings, and seeding are tenant-scoped; SkillSeeder seeds into a target tenant, not a global slot.
- `docs/master/product/features/agent-a2a-communication-and-slug-enforcement.md`: delegation targets resolve by (tenant, name); delegation names are tenant-qualified.
- `docs/master/product/features/agent-data-types.md`: remove the NULL-tenant shared-slot language; data types are strictly tenant-owned (root tenant owns legacy adopted rows); lookup is exact tenant match.
- `docs/master/product/features/agent-data.md` and `agent-outputs.md`: all records carry the owning tenant; all system tools (save_data, get_data, get_output, query_result) and internal listing APIs filter strictly by tenant.
- `docs/master/product/features/notification-integration.md`: recipient groups and dispatch are tenant-scoped; remove the shared/global slot behavior.
- `docs/master/product/features/schedule-management.md`: scheduled jobs are tenant-bound at creation and dispatched in the owning tenant's context; remove NULL-tenant job dispatch.
- `docs/master/product/features/agent-runtime-security.md` and `agent-runtime-monitor.md`: describe virtual tenant awareness — agents run under a resolved tenant and can only reach that tenant's resources.
- Add a reference note (in the multi-tenancy feature or `docs/master/reference/`) describing the one-time NULL-tenant → root-tenant adoption migration and its idempotency guarantee.
