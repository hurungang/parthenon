# Multi-Tenancy (SaaS)

## Epic Overview

Parthenon runs as a single-tenant platform by default: one deployment serves one organization. Multi-tenancy is an **opt-in, platform-level switch (disabled by default)** that turns the platform into a self-serve SaaS: a visitor signs up with a personal email and password, instantly receives their own tenant workspace, and becomes its **tenant root user** — the permanent super-admin of that tenant. Growth is governed by license tiers (free / team / enterprise) with quotas on users, agent types, and monthly agent executions; tenants without an assigned license run on a free tier by default.

The platform itself operates as the **root tenant** (workspace address `root`): platform staff are simply members of the root tenant holding platform roles. Every permission grant — including wildcards — stays strictly inside the session's tenant, and everyone signs in through one unified workspace-address flow. With the switch off, the deployment behaves exactly like the root tenant's workspace and all existing single-tenant behavior is preserved.

## Business Goals

- Enable a hosted offering: serve many customer organizations on one shared deployment with no new infrastructure per customer.
- Self-serve acquisition: signup to a working tenant workspace in minutes, with zero platform-admin involvement.
- Isolation by design: no user, agent, or API key can read or write another tenant's data through any interface.
- Monetization-ready tiers: every quota-exceeded action is blocked with clear tier, limit, usage, and upgrade feedback.
- Zero regression: with multi-tenancy disabled, existing behavior and tests are unchanged.

## Users & Personas

- **Prospective Owner (Visitor)** — signs up with a personal email and password and instantly owns a tenant workspace.
- **Tenant Root User** — the person who registered the tenant; its permanent super-admin with ALL permissions inside the tenant. Root status cannot be changed, demoted, or removed by anyone. Limited to owning one tenant (the limit may be raised later).
- **Platform Admin** — a member of the root tenant holding a platform role. Creates, suspends, resumes, and deletes tenants; controls the tenancy switch; assigns licenses and monitors quota usage. Does not browse tenant business data and cannot alter a tenant root.
- **Tenant Admin (delegated)** — administrator appointed within a tenant; fully self-sufficient inside their tenant, except they can never modify or remove the tenant root.
- **Tenant User** — works only with their organization's data, using only tenant modules.
- **Tenant Agent** — AI agent principal executing strictly within one tenant's skills, tools, and permissions.

## Key Capabilities

### Tenancy Mode Switch (default off)
Multi-tenancy is enabled or disabled at platform level and is disabled by default. When disabled, everything defaults to the root tenant: the deployment behaves exactly like the root tenant's workspace — same unified sign-in, same tenant modules — with no visible tenant concept. Enabling multi-tenancy on an existing deployment adopts it as the root tenant with no manual reconfiguration; disabling returns to single-tenant behavior without data loss.

### Root Tenant Platform Model
The platform's own internal workspace is the root tenant (address `root`). Platform staff are simply root-tenant members holding platform roles. Root-tenant members use the same common modules as every tenant (permissions, identity-provider configuration, member management) plus the platform modules their platform role grants. The break-glass super-admin account remains available at the root workspace sign-in for first-run bootstrap and disaster recovery.

### Permission Containment
Every permission grant — including wildcard grants covering "all resources, all actions" — applies only within the session's tenant. No global or cross-tenant roles exist: a platform role unlocks platform modules and nothing in any customer tenant; a tenant admin role unlocks its own workspace and no platform modules. Isolation is enforced centrally on every read and write, regardless of which feature performs it.

### Unified Workspace-Address Sign-In
Everyone signs in the same way: enter a workspace address (e.g. `test-com` or `root`), then sign in via that tenant's OIDC provider or a platform-issued email + password. There is no separate platform login page. Signing into `root` with a platform role opens the platform console. One session is bound to exactly one tenant; switching tenants requires a fresh sign-in. Signing in to a tenant succeeds only with an active membership and role there; anyone else receives a clear "no access to this workspace" message — never a redirect loop.

### Self-Serve Registration & Tenant Root
A visitor registers with a personal email + password; their tenant workspace is created instantly and they land in guided onboarding as the tenant root. A user who already owns a tenant is blocked from registering again with a clear "one tenant per user" message. Platform-admin tenant creation remains available as a secondary administrative path (the designated contact becomes that tenant's root). The root can edit the tenant's display alias; the unique tenant address stays fixed.

### Tenant Admin Module
Every tenant workspace includes a tenant admin module covering the tenant display name/alias, identity-provider configuration, and member management — alongside the standard workspace modules. Tenant users (including tenant root and admins) see only tenant modules; platform modules are visible only to root-tenant members with platform roles after signing into the root workspace.

### Strict Per-Tenant Identity Providers & JIT Default Role
Each tenant uses **only its own identity provider** — there is no shared provider and no fallback chain. A sign-in to a workspace validates exclusively against that workspace's own configured provider. Each provider configuration carries an optional **default tenant role** (from the seeded presets: Tenant System Admin / Agent Manager / Agent Executor / Agent Viewer). A first-time OIDC sign-in to a tenant with a default role configured is automatically onboarded with that role; if unset, the tenant stays invitation-only. Existing memberships are never changed by sign-in.

### No Workspace Switching
One session is bound to exactly one tenant, and the root tenant is the default workspace. There is no in-session workspace switching: reaching another workspace always requires a fresh sign-in with an active membership there. With multi-tenancy disabled, only the root tenant's identity providers are used and sign-in to any non-root tenant workspace is rejected.

### License Tiers & Quotas
Platform admins assign each tenant a license defining a tier — free / team / enterprise — with limits on maximum users, maximum agent types, and monthly agent executions (counted per calendar month, reset monthly). A tenant without a license automatically runs on the free tier. Reaching a quota blocks the corresponding action (inviting users, creating agent types, submitting executions) with feedback naming the tier, limit, current usage, and upgrade path; one exhausted quota does not block unrelated actions. Tenants and platform admins see tier, limits, and current usage at a glance.

### Tenant Lifecycle
Tenants have a unique name and unique web address. Platform admins can create, edit, suspend (blocks sign-in and ends active sessions, no data loss), resume, and delete tenants (explicit confirmation; full data removal; the address becomes reusable). All lifecycle actions are auditable.

## Isolation Guarantees

Isolation is **strict**: every tenant is fully independent — no cross-tenant fallback, sharing, or visibility of business data, ever (see [Strict Tenant Isolation](strict-tenant-isolation.md)).

- **Everything is tenant-owned**: roles, agents, agent identities, MCP hubs and sessions, skills, SOPs, schedules, model configurations, conversations, execution logs, outputs, saved data, notifications, and API keys each belong to exactly one tenant and are filtered automatically in every list, search, and action. Lookups match the exact session tenant only — never shared or tenant-less rows.
- **Strict permission containment**: any grant, including wildcards, applies only within the session's tenant — verified by automated containment tests.
- **Tenant-bound sessions**: a session created at one tenant's address is invalid everywhere outside that tenant.
- **Agent isolation**: agents execute only with their tenant's skills, tools, credentials, and identities; agent-to-agent messages cannot cross tenants.
- **API keys are tenant-bound**: a tenant's API key cannot access another tenant's resources.
- **Operator limits**: platform admins manage tenant metadata and licenses but cannot browse tenant business data or alter a tenant root.
- **Auditable boundaries**: cross-tenant access attempts, root-protection violations, and quota events are recorded with tenant attribution and visible to the platform admin.
- **Fail-closed internal services**: internal endpoints between Control Center, Communication Hub, and Agent Runtime require a valid signed tenant context on every call; requests without one are rejected, never defaulted.
- **Per-tenant naming**: entity names and slugs — including MCP server slugs — are unique per tenant, not platform-wide.
- **No tenant-less data**: a one-time, idempotent migration adopted all legacy tenant-less (NULL-tenant) shared rows (data types, seeded skills, scheduled jobs, shared recipient groups) into the root tenant; re-running it makes no further changes, and the shared slot no longer exists as a concept.

## Acceptance Criteria

- With the switch off (default), all sign-in, UI, and feature behavior matches the single-tenant product exactly; all existing tests pass unchanged.
- With the switch on, an existing deployment is adopted as the root tenant with configuration and data intact and no identity-provider reconfiguration.
- A visitor can self-register and land in a working tenant workspace as its root user, with no platform-admin action; duplicate registrations are blocked with a clear message.
- Tenant root membership cannot be changed, demoted, or removed by anyone; attempts are rejected and audited.
- Inviting users, creating agent types, or submitting executions beyond the tenant's tier quota is blocked with tier, limit, usage, and upgrade-path feedback; monthly executions reset at the start of each calendar month.
- No user, agent, or API key — through UI, API, agent execution, scheduling, notifications, or MCP tools — can read or write another tenant's data; attempts return "not found / permission denied" and are recorded as security-relevant audit events.
- Everyone signs in via the unified workspace-address flow; non-members are rejected cleanly with "no access to this workspace".
- First OIDC sign-in with a default role configured auto-creates membership with that role; with no default role, first-time visitors are rejected without a membership being created.
- License changes take effect immediately; removing a license falls the tenant back to free-tier defaults.
- Suspended tenants are blocked at sign-in with active sessions ended; deletion removes all data and frees the address for reuse.

## Out of Scope

- Billing, payments, and self-service plan purchase (license assignment is manual; enforcement is in scope).
- Owning multiple tenants per user (limit fixed at one for now).
- Rate limiting beyond tier quotas; data residency customization; per-tenant dedicated infrastructure.
- Cross-tenant sharing, collaboration, or marketplaces; white-label branding beyond address and alias.
- Group-claim-to-role mapping, SCIM provisioning, and any separate platform login page or flow.
