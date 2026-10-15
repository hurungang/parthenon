# Strict Tenant Isolation

## Epic Overview

Parthenon is a multi-tenant SaaS platform in which each tenant is fully independent. The product rule is strict: no cross-tenant fallback, sharing, or visibility of business data — ever. Every tenant operates in a fully sealed workspace: its own identity provider, its own MCP servers, skills, tools, data types, saved data, outputs, notifications, schedules, and agents. The root tenant exists for platform-management users and acts as the single tenant when multi-tenancy is disabled.

## Business Goals

- Guarantee zero cross-tenant visibility of business data (outputs, saved data, MCP tools, skills, notifications) — verified by automated test.
- Enable true SaaS tenancy: any two tenants can configure identically named MCP servers, skills, and tools without conflict.
- Eliminate fail-open security paths: a missing tenant binding means deny, never default.
- Retire the legacy NULL-tenant "shared slot" concept on the data plane.
- Preserve single-tenant behavior: with multi-tenancy disabled, everything resolves to the root tenant transparently.

## Users & Personas

- **Tenant Administrator** — configures MCP servers, skills, roles, and recipient groups for their tenant; their configuration and data are invisible to other tenants, and they are free to use common names like "supabase".
- **Tenant End User / Agent Operator** — runs agents and views outputs; only ever sees their own tenant's results and data.
- **Agent (non-human principal)** — executes skills and invokes tools; resolves tools and delegation targets only within its own tenant.
- **Platform Administrator (root tenant)** — manages the platform; ordinary tenant users never see platform modules or other tenants' data.
- **Security / Compliance Auditor** — relies on observable, testable isolation guarantees with no fail-open paths.

## Strict Isolation Rules

### Strict Identity-Plane Rule

Every tenant uses **only its own identity provider**. There is no shared provider and no provider fallback chain:

- Each tenant's sign-in validates exclusively against that tenant's own configured identity provider.
- With multi-tenancy disabled, only the root tenant's identity providers are used, and sign-in to any non-root tenant workspace is rejected.
- There is no workspace switching after sign-in: one session is bound to exactly one tenant, and the root tenant is the default workspace. Moving to another workspace always requires a fresh sign-in — and is only possible with an active membership there.

### Sealed Data Plane

- **Everything is tenant-owned**: roles, agents, agent identities, MCP servers and sessions, skills, SOPs, schedules, data types, saved data, outputs, conversations, execution logs, notifications, and API keys each belong to exactly one tenant and are filtered strictly by the session's tenant in every list, search, query, and action. Lookups match the exact tenant only — never "shared" or tenant-less rows.
- **Per-tenant naming everywhere**: entity names and slugs — including MCP server slugs and agent-type slugs — are unique per tenant, not platform-wide. Two tenants can both register a server named "supabase"; each tenant's references resolve to its own server.
- **Per-tenant tool namespaces**: tool names are resolved within the calling tenant's context. Identical tool names can coexist across tenants; an agent from tenant A can never list or invoke a tool registered by tenant B. Permission grants on tools and skills are enforced within the granting tenant only.
- **Tenant-bound agents and chat**: agent sessions (including WebSocket chat) are bound to their tenant at creation. Users of one workspace can never reach another workspace's data, MCP servers (identical slugs are fine — each resolves per tenant), or decision tools.
- **A2A delegation is tenant-qualified**: delegation targets (including `agent____<slug>`-style names) resolve by tenant and name; a name collision across tenants never routes to the wrong tenant's agent.
- **Tenant-scoped notifications**: recipient groups and notification dispatch resolve within the calling tenant; the legacy global "shared" recipient-group slot no longer exists on the data plane.
- **Tenant-bound scheduling**: scheduled jobs are bound to a tenant at creation and always dispatched under their owning tenant's context; a job created in tenant A never runs with access to tenant B resources.

### Fail-Closed Internal Service Endpoints

Internal endpoints between Control Center, Communication Hub, and Agent Runtime require a valid signed tenant context on every call. A request without a valid signed tenant binding is rejected — it never falls back to an unscoped or default tenant. All internal queries filter strictly by the bound tenant.

### System Tools Are Tenant-Scoped

- `save_data` and `get_data` records always carry the calling tenant's binding and are retrieved only by that tenant — a record saved by tenant A is not retrievable by tenant B even with identical names.
- `query_result` resolves the data type within the calling tenant only and filters outputs by tenant.
- Internal listing APIs for outputs and agent data return only the bound tenant's records.

### Decision Tools

Decision tools are per-tenant by definition — a tenant's decision tools are visible and usable only within that tenant:

- **Readiness validation**: a decision tool can only be enabled once both its input and output data types are defined (both are required).
- **Questions are auto-derived** from the tool's output data type — no manual question authoring.
- **State is auto-mapped** from the input data type by default; advanced mapping remains optional for special cases.

## One-Time Legacy Adoption Migration

Existing tenant-less (NULL-tenant) shared rows — data types, seeded skills, scheduled jobs, shared recipient groups, and any other tenant-less business rows — were adopted into the root tenant by a single, idempotent migration. After adoption, all lookups match the exact session tenant only; the NULL-tenant "shared slot" no longer exists as a concept. Re-running the migration is safe and makes no further changes.

## Acceptance Criteria

- Two tenants can each register an MCP server with the same slug; each tenant's skills referencing that slug resolve to their own server, and each agent invokes tools from its own tenant's server only.
- Tool names, tool-name parsing, and A2A delegation names are tenant-scoped: a tenant A agent cannot list or invoke a tenant B tool, and delegation resolves only within the calling tenant.
- Permission grants on tools and skills authorize only within the granting tenant.
- Internal endpoints reject (fail closed) requests without a valid signed tenant binding; no data-plane path resolves records across tenants.
- `query_result`, `save_data`, and `get_data` operate strictly within the calling tenant; identical names across tenants never leak records.
- Each tenant's notifications go to that tenant's own recipient group; no global/shared slot exists.
- A tenant user cannot see or reference another tenant's (or the root tenant's) data types, skills, or jobs; scheduled jobs always execute in their owning tenant's context.
- Agent and chat sessions are tenant-bound; one workspace's users can never reach another workspace's data, MCP servers, or decision tools.
- Every tenant authenticates solely through its own identity provider; with multi-tenancy disabled only root-tenant providers work and non-root sign-ins are rejected; there is no workspace switching.
- With multi-tenancy disabled, all of the above behaves identically with everything bound to the root tenant.
- Existing per-tenant unique-name behavior and per-identity-tenant OAuth token refresh continue to work (regression check).

## Out of Scope

- Cross-tenant collaboration features, shared marketplaces, or any opt-in data sharing — prohibited by product rule.
- Platform-module (control-plane) authorization redesign — platform routes already resolve root-tenant binding.
- Retrofitting tenant isolation into agent identities or OIDC provisioning — already strict.

## Spec Deltas

> Note: `openspec/specs/` does not exist in this repository, so the spec deltas from the change document are recorded here.

### New Capabilities

- **Tenant-scoped MCP hub**: each tenant registers its own MCP servers with arbitrary slugs; slugs are unique per tenant, not platform-wide.
- **Per-tenant tool namespaces**: tool names resolve within the calling tenant's context; identical names coexist across tenants.
- **Virtual tenant awareness in Agent Runtime**: agents run under a resolved tenant binding; every tool invocation, data access, and delegation resolves against the calling tenant only.
- **One-time legacy adoption migration**: NULL-tenant shared rows adopted into the root tenant, idempotently.

### Modified Capabilities

- **MCP server slug uniqueness** — from platform-wide to per-tenant; tool sync, name building/parsing, and permission grants operate per tenant.
- **Internal service endpoints** — from fail-open (tenant-scoped only if signed headers present) to fail-closed: signed tenant binding required, all queries filter by the bound tenant.
- **query_result** — data type resolved within the calling tenant only; outputs filtered by tenant.
- **save_data / get_data** — records always written with the calling tenant binding; retrieval filtered strictly by tenant.
- **Internal outputs / agent-data listing APIs** — return only the signed tenant's records.
- **A2A delegation** — target resolved by (tenant, name); delegation names tenant-qualified.
- **get-recipient-group** — returns only the bound tenant's groups.
- **Notification dispatch** — resolves the calling tenant's own recipient group; the shared slot is retired.
- **Agent data type lookup** — from "shared slot OR own tenant" to strict exact tenant match.
- **Skill seeding** — seeds into a target tenant (root tenant for platform defaults), not a global slot.
- **Scheduler** — every job tenant-bound at creation and dispatched under its owning tenant's context.

### Removed Capabilities

- **NULL-tenant "shared slot" on the data plane**: no business-data lookup uses tenant-less matching; shared recipient-group slot, shared data types, globally seeded skills, and tenant-less scheduled jobs are removed as concepts.
- **Platform-wide MCP slug uniqueness**: replaced by per-tenant uniqueness (a conflict removal, not a capability loss).

## Multi-Tenancy Note

This feature defines the strict end-state of [Multi-Tenancy](multi-tenancy.md). With multi-tenancy disabled (the default), the deployment operates as the root tenant's workspace — the root tenant's identity providers only, and identical strict isolation behavior.
