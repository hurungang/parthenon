# PRD: strict-tenant-isolation

## Epic Overview

Parthenon is a multi-tenant SaaS platform in which each tenant is fully independent. The product rule confirmed by the owner is strict: no cross-tenant fallback, sharing, or visibility of business data — ever. The root tenant exists for platform-management users (and acts as the single tenant when multi-tenancy is disabled). An audit of the data plane found multiple paths that violate this rule: MCP server slugs are platform-wide so two tenants cannot both register a server with the same name; internal service endpoints fail open when tenant headers are missing; notification dispatch always targets a global "shared" group; and several legacy designs deliberately share NULL-tenant rows across all tenants. This change makes tenant isolation strict and uniform across the MCP hub, internal data-plane APIs, notifications, skills, and scheduling, so that every tenant operates in a fully sealed workspace.

## Business Goals

- Guarantee zero cross-tenant visibility of business data (outputs, saved data, MCP tools, skills, notifications) — verified by test.
- Enable true SaaS tenancy: any two tenants can configure identically named MCP servers, skills, and tools without conflict.
- Eliminate fail-open security paths on internal service endpoints — missing tenant binding means deny, never default.
- Retire the legacy NULL-tenant "shared slot" concept on the data plane, reducing long-term complexity and audit risk.
- Preserve existing single-tenant behavior: with multi-tenancy disabled, everything resolves to the root tenant transparently.

## Users & Personas

- **Tenant Administrator**: configures MCP servers, skills, roles, and recipient groups for their tenant; needs assurance their configuration and data are invisible to other tenants, and freedom to use common names like "supabase".
- **Tenant End User / Agent Operator**: runs agents and views outputs; should only ever see their own tenant's results and data.
- **Agent (non-human principal)**: executes skills and invokes tools; must resolve tools and delegation targets only within its own tenant.
- **Platform Administrator (root tenant)**: manages the platform; may see all data as part of platform operations, but ordinary tenant users never see platform modules or other tenants' data.
- **Security / Compliance Auditor**: needs observable, testable isolation guarantees and no fail-open code paths.

## User Stories

- As a tenant administrator, I want to register an MCP server with a slug that another tenant also uses, so that my tenant is not blocked by global naming.
- As a tenant administrator, I want my skills and skill bindings to reference my own tenant's MCP servers, so that agent tool invocation never reaches another tenant's server.
- As an agent, I want tool names and A2A delegation names resolved within my own tenant, so that I can never invoke or hijack another tenant's server or agent.
- As a tenant administrator, I want recipient groups and notification dispatch scoped to my tenant, so that notifications for my agents go to my group, not a global one.
- As a tenant end user, I want query results, saved data, and outputs visible only from my tenant, so that no other tenant's business data can leak to me.
- As a platform operator, I want internal service endpoints to reject requests lacking a valid signed tenant binding, so that no component can accidentally operate tenant-less.
- As a platform operator, I want legacy NULL-tenant records adopted into the root tenant once, so that strict tenant matching works everywhere without special cases.
- As a scheduler operator, I want scheduled jobs bound to a tenant at creation and dispatch, so that a job always executes in its owning tenant's context.

## Acceptance Criteria

- Two tenants can each register an MCP server with the same slug (e.g., "supabase"); each tenant's skills referencing that slug resolve to their own tenant's server, and each agent invokes tools from its own tenant's server only.
- MCP tool names, tool-name parsing, and A2A delegation names (including `agent____<slug>` style names) are tenant-scoped: an agent from tenant A cannot list or invoke a tool registered by tenant B, and A2A delegation by name resolves only within the calling tenant.
- Permission grants on tools and skills are enforced within the granting tenant only; a grant in tenant A never authorizes access in tenant B.
- Internal endpoints under `/api/v1/internal/*` reject (fail closed) requests without valid signed `X-Internal-Tenant-*` tenant headers; no data-plane path resolves records across tenants.
- The `query_result` system tool resolves the data type and queries outputs only within the calling tenant; a tenant A agent querying a data type name that exists in both tenants gets only tenant A results.
- `save_data` and `get_data` records are always written with the calling tenant's binding and retrieval filters strictly by that tenant; a record saved by tenant A is not retrievable by tenant B even with identical names, agent type, or session filters.
- Internal outputs and agent-data listing endpoints return only the bound tenant's records.
- A2A delegation resolves the target agent type strictly by (tenant, name); a name collision across tenants never routes to the wrong tenant's agent.
- `get-recipient-group` returns only groups in the bound tenant.
- Notification dispatch resolves the calling tenant's own recipient group; each tenant's notifications go to that tenant's group, and the global/shared slot is no longer used on the data plane.
- Data types (AgentDataType), seeded skills, and scheduled jobs no longer use a NULL-tenant shared slot: after migration, all legacy NULL-tenant rows belong to the root tenant, and lookups match the exact session tenant only — a tenant user cannot see or reference another tenant's (or the root tenant's) data types, skills, or jobs.
- Scheduler dispatch executes each job under its owning tenant's context; a job created in tenant A never runs with access to tenant B resources.
- With multi-tenancy disabled, all of the above behave identically with everything bound to the root tenant (single-tenant behavior preserved).
- Existing per-tenant unique-name behavior for entity name/slug and per-identity-tenant OAuth token refresh continue to work (regression check).

## Out of Scope

- Per-tenant uniqueness of entity name/slug constraints — already completed in a prior change (regression coverage only).
- Login-context OIDC provider candidate chain (own → shared → root at token validation) — identity-plane behavior, intentionally unchanged.
- Cross-tenant collaboration features, shared marketplaces, or any opt-in data sharing — prohibited by product rule.
- Platform-module (control-plane) authorization redesign — platform routes already resolve root-tenant binding.
- Changes to license tiers/quotas mechanics beyond tenant-scoped enforcement already in place.
- UI redesign of the MCP hub, skills, or notifications pages beyond what tenant scoping requires.
- Retrofitting tenant isolation into the identity plane (agent identities, OIDC provisioning) — already strict.

## Dependencies & Constraints

- Requires a one-time data migration adopting existing NULL-tenant legacy rows (data types, seeded skills, scheduled jobs, shared recipient groups) into the root tenant; must be idempotent and applied before strict matching goes live.
- Requires coordinated changes across Control Center, Agent Runtime, and Communication Hub — internal service contracts must carry the signed tenant binding on every call (per `X-Internal-Tenant-*` HMAC convention).
- Schema changes must follow the Alembic migration workflow; migrations must be applied before backend testing.
- Must comply with `docs/config.yaml` top priority rules (service segregation, agents only in Agent Runtime, only Control Center touches the database, no sensitive data to agents).
- Backward compatibility is not required for cross-tenant paths (they are being removed by design); single-tenant (root-default) deployments must keep working without operator action beyond running migrations.
