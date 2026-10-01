# PRD: Multi-Tenant Support (SaaS)

## Epic Overview

Parthenon today runs as a single-tenant platform: one deployment serves exactly one organization, with one identity provider configuration, one set of roles, agents, and integrations. Every new organization must run its own deployment, which blocks a hosted (SaaS) offering and raises cost and friction. This epic adds opt-in multi-tenancy and turns the platform into a true self-serve SaaS: a visitor signs up with a personal email and password, instantly receives their own tenant workspace, and becomes its **tenant root user** — the permanent super-admin of that tenant. Growth is governed by license-based tiers (free / team / enterprise) with quotas on users, agent types, and monthly agent executions; tenants without an assigned license run on a free tier by default, giving every signup a usable starting point and a clear upgrade path. Each tenant connects its own corporate sign-in (OIDC) and configures everything Parthenon offers today with no visibility into, or exposure risk from, any other tenant. A platform-level switch enables multi-tenancy and is **disabled by default**, so local development, demos, and existing self-hosted installations behave exactly as they do today.

## Business Goals

- Enable a hosted offering: serve multiple customer organizations on one shared deployment with no new infrastructure per customer (target: ≥ 10 concurrent tenants with no degradation beyond agreed performance thresholds).
- Self-serve acquisition: a visitor goes from signup to a working tenant workspace in under 5 minutes with zero platform-admin involvement.
- Guarantee isolation by design: 100% of cross-tenant security tests pass; zero cross-tenant data exposure in security review.
- Monetization-ready tiers: 100% of quota-exceeded actions are blocked with clear feedback showing tier, limit, current usage, and upgrade path; per-tenant usage reporting is accurate within the calendar month.
- Zero regression and clear governance: with multi-tenancy disabled, 100% of existing functionality and tests pass unchanged; platform-admin and tenant responsibilities fully separated, with every cross-tenant or root-protection violation recorded in an audit trail.

## Users & Personas

- **Prospective Owner (Visitor)** — wants to try or adopt Parthenon. Signs up with a personal email and password; expects an instant workspace without contacting sales or an operator.
- **Tenant Root User** — the person who registered the tenant; its permanent super-admin with ALL permissions inside the tenant. Manages the tenant alias (display name). Root status cannot be changed, demoted, or removed by anyone. Limited to owning one tenant (like one cloud account per person; the limit may be raised later).
- **Platform Admin** — operator of the hosted deployment (evolution of today's super admin). Creates (secondary path), suspends, resumes, and deletes tenants; controls the tenancy switch; **assigns licenses/tiers** and monitors tenant quota consumption. Does **not** browse tenant business data and cannot alter a tenant root.
- **Tenant Admin (delegated)** — administrator appointed within a tenant. Fully self-sufficient inside their tenant (OIDC sign-in, roles, agents, MCP hubs, skills, SOPs, schedules, model configurations, API keys, users) — except they can never modify or remove the tenant root.
- **Tenant User** — employee of a tenant organization. Signs in via their organization's sign-in page and works only with their organization's data.
- **Tenant Agent** — AI agent principal executing strictly within one tenant's scope, using only that tenant's skills, tools, and permissions.
- **Security Auditor** — needs demonstrable, testable evidence that cross-tenant access is impossible by design before approving a hosted deployment.

## User Stories

**Prospective Owner / Tenant Root**
- As a visitor, I want to sign up with my personal email and password, so that I get my own tenant workspace instantly without talking to anyone.
- As a tenant root user, I want permanent super-admin rights inside my tenant, so that I always retain full control of my organization's workspace.
- As a tenant root user, I want my root status to be immutable, so that no other tenant admin or platform operator can ever lock me out of my own tenant.
- As a tenant root user, I want to update my tenant's alias (display name), so that my workspace stays named correctly as my organization evolves.
- As a visitor who already owns a tenant, I want a clear explanation when I try to register again, so that I understand I can own only one tenant today.

**Platform Admin**
- As a platform admin, I want to enable or disable multi-tenancy with a platform-level switch, so that local dev, demos, and existing single-tenant installations behave exactly as today.
- As a platform admin, I want to create a tenant with a name, a unique tenant address, and a primary admin contact (who becomes its tenant root), so that I can onboard an organization manually when needed.
- As a platform admin, I want to assign each tenant a license defining its tier (free / team / enterprise) with its limits, so that tenant entitlements match their agreement.
- As a platform admin, I want to see each tenant's tier, limits, and current usage in the tenant overview, so that I can manage capacity and advise upgrades.
- As a platform admin, I want to suspend, resume, and delete tenants, so that I can operate the hosted service responsibly.
- As a platform admin, I want tenant administration to never expose tenant business data, so that operator access stays minimal and auditable.

**Tenant Admin / Tenant User**
- As a tenant admin, I want a guided onboarding after my tenant is created, so that my organization is ready for users without specialist help.
- As a tenant admin, I want to connect my organization's own OIDC identity provider, so that my users sign in with corporate credentials.
- As a tenant admin, I want to set a default tenant role on my tenant's OIDC provider configuration, so that first-time corporate sign-ins are automatically onboarded with the right level of access — without me inviting each user manually.
- As a tenant admin, I want to be able to leave the default role unset, so that only people I explicitly invite can enter my tenant.
- As a first-time visitor arriving via my organization's corporate sign-in, I want to be onboarded automatically with the default role my administrators chose, so that I can start working immediately without waiting for an invitation.
- As a first-time visitor whose organization has not configured a default role, I want a clear "no access to this workspace" message, so that I know to request access instead of being stuck.
- As a tenant admin, I want to invite users and assign tenant roles, so that colleagues can start working quickly — within my tenant's user quota.
- As a tenant admin, I want to see my tenant's tier, limits, and current usage at a glance, so that I can plan before hitting a limit.
- As a tenant admin, when a quota is reached I want the blocked action to tell me which limit, my current usage, and how to get more, so that I know exactly what to do next.
- As a tenant user, I want to see only my organization's agents, tools, history, and results, so that I never encounter another organization's data.

**Tenant Agent & Security Auditor**
- As a tenant agent, I want to run only with my tenant's skills, tools, and permissions, so that execution can never reach another tenant.
- As a security auditor, I want documented and testable isolation guarantees, so that I can approve the hosted deployment.

## Tenant Resolution & Isolation Model (proposed, business terms)

- **Dedicated tenant address**: every tenant gets a unique web address chosen at creation (organization-named hosted address). The address alone determines which tenant workspace a visitor lands in — no ambiguity, and tenant selection only appears for users who belong to several organizations.
- **One session = one tenant**: each sign-in is bound to exactly one tenant for the whole session. Switching tenants requires a fresh sign-in for that tenant.
- **Owner accounts are email + password**: the registering owner uses a personal email + password account bound to their tenant; tenant members typically sign in via the tenant's OIDC provider once configured. An owner credential unlocks only its own tenant.
- **One account, one tenant**: a user can own at most one tenant today (the limit can be raised later); duplicate registrations are blocked with a clear message.
- **Everything is tenant-owned**: every record — roles, agents, agent identities, MCP hubs and sessions, skills, SOPs, schedules, model configurations, conversations, execution logs, outputs, saved data, notifications, API keys — belongs to exactly one tenant and is automatically filtered to the signed-in tenant in every list, search, and action.
- **Centrally enforced isolation**: tenant boundaries apply automatically and consistently to every read and write, regardless of which feature performs it; no user, agent, or integration can bypass or widen its tenant scope.
- **Identity model**: every person is represented by an identity that is either self-managed (platform-issued email + password, e.g. the registering owner) or linked to an external identity provider identity (corporate OIDC sign-in).
- **Contextual sign-in**: a person signs in either at the platform level (requires a platform role) or at a tenant's workspace address (requires a role in that tenant); the sign-in context alone decides what the session can reach.
- **Provider sharing**: one identity-provider configuration can serve the platform and multiple tenants simultaneously; the sign-in context (platform vs a given workspace address) decides the tenant the session is bound to — no duplicate provider registrations per tenant are required.
- **Tenant admission rule**: signing in to a tenant succeeds if and only if the person has an active membership with a role in that tenant — otherwise the sign-in is rejected cleanly with a clear "no access to this workspace" message; users are never trapped in a redirect loop.
- **First-sign-in auto-onboarding (JIT default role)**: each identity-provider configuration has a configurable default tenant role (one of the seeded presets: Tenant System Admin / Agent Manager / Agent Executor / Agent Viewer). When a user signs in to a tenant via OIDC for the first time — no existing membership — the configured default role is automatically assigned (membership created on the spot). If no default role is configured, the user is rejected with "no access to this workspace" semantics. Existing memberships are never modified by sign-in.
- **Shared platform, hard logical walls**: all tenants share one deployment (no dedicated infrastructure per tenant); isolation comes from strict tenant ownership plus centralized enforcement, not separate systems.
- **Role split**: Platform Admin governs tenants, licenses, and platform settings; the Tenant Root and delegated admins govern everything inside one tenant; neither can act in the other's domain — and no one can alter the root.

## Acceptance Criteria

**Tenancy Mode Switch**
- With the switch off (default): UI, sign-in, and all features behave exactly as the current single-tenant product; no tenant concept is visible anywhere; all existing tests pass unchanged.
- With the switch on: tenant features become available. Disabling the switch again returns the deployment to single-tenant behavior without data loss.
- When enabling multi-tenancy on an existing deployment, the current organization's configuration and data remain intact and continue to work under the tenancy model (adopted as its first tenant), with no manual reconfiguration of its identity provider.

**Self-Serve Registration & Tenant Root**
- A visitor can register with a personal email and password; on success their tenant workspace is created and they land in guided onboarding as the tenant root user — no platform-admin action involved.
- The root user has ALL permissions inside their tenant and can perform every tenant-admin action without additional grants.
- Root role/membership cannot be changed, demoted, or removed by anyone: attempts by other tenant admins or by the platform admin are rejected with a clear message and recorded in the audit trail.
- A user who already owns a tenant and attempts to register again is blocked with a clear "one tenant per user" message; no second tenant is created and no partial data remains.
- Duplicate email registration and missing/invalid fields are rejected with clear validation errors.
- The root user can edit the tenant alias (display name); the new alias appears immediately across the tenant workspace without a page reload; the unique tenant address remains fixed and uniqueness rules stay enforced.

**License & Tier Management**
- Platform admin can assign a license to any tenant; the license defines a tier (free / team / enterprise) with limits for: maximum users, maximum agent types, and monthly agent executions.
- Platform admin can change a tenant's license; removing the license falls the tenant back to free-tier defaults immediately.
- A tenant without an assigned license automatically runs on the free tier with lower default limits — visible to both platform admin and tenant users.
- After assigning/changing/removing a license, the tenant overview and the tenant's own usage view update immediately without a manual page reload.
- Invalid license input (unknown tier, non-positive limits) is rejected with clear errors; permission errors are shown gracefully.

**Quota Enforcement & Usage UX**
- Inviting or creating users beyond the tenant's max-user limit is blocked; the blocker names the tenant's tier, the limit, current usage, and the upgrade path (contact the platform admin to change tier).
- Creating agent types beyond the max-agent-types limit is blocked with the same tier/limit/usage/upgrade feedback.
- Submitting agent executions beyond the monthly execution limit is blocked with the same feedback; executions are counted per calendar month per tenant and reset at the start of each calendar month.
- Reaching one quota does not block unrelated actions (e.g., an exhausted user quota still allows agent executions until their own limit is reached).
- Usage shown in the tenant UI (users, agent types, executions this month) matches the tenant's actual records; in-flight executions already counted are not double-counted.

**Tenant Lifecycle (create / read / update / suspend / delete)**
- Platform admin can create a tenant with name, unique tenant address, and primary admin contact (who becomes the tenant root); the new tenant appears immediately in the tenant overview table with all values correctly displayed.
- Tenant name and address are unique; duplicates are rejected with a clear error message; required fields are enforced.
- Editing a tenant updates the overview table immediately without a manual page reload; related counts (users, agents) refresh after changes.
- Suspend: users of a suspended tenant are blocked at sign-in and active sessions are ended with a clear "tenant suspended" message; no data is lost; resume restores full access immediately.
- Delete: requires explicit confirmation; removes the tenant and all of its data; the tenant disappears from the overview table immediately; creating a new tenant with the same address afterwards succeeds (proves true deletion).
- Invalid inputs (missing fields, malformed address) show validation errors; permission errors are shown gracefully, not silently.

**Per-Tenant Identity Provider**
- Each tenant admin can configure their own OIDC provider independently; changing one tenant's sign-in configuration never affects another tenant.
- A single provider configuration may be shared: it can serve the platform sign-in and multiple tenants' workspace sign-ins; the sign-in context alone decides which tenant the resulting session is bound to, and a session created at tenant A's address can never access tenant B.
- A session created at tenant A's workspace address is tenant-bound: it cannot access tenant B — any attempt to use it outside tenant A is rejected.
- Tenant admins cannot view or modify another tenant's sign-in configuration.

**Sign-In Admission & First-Sign-Onboarding (JIT Default Role)**
- Every identity is either self-managed (platform-issued email + password) or linked to an external IdP identity (OIDC); the platform sign-in page accepts only users holding a platform role, and a tenant workspace address only accepts users with a role in that tenant.
- Signing in to a tenant succeeds exactly when the person has an active membership with a role there; anyone else receives a clear "no access to this workspace" message immediately — never a redirect loop or silent failure.
- Each OIDC provider configuration offers a default tenant role selection limited to the seeded presets (Tenant System Admin / Agent Manager / Agent Executor / Agent Viewer); the tenant admin can set it or leave it unset.
- First OIDC sign-in to a tenant with a default role configured: membership is created automatically with exactly that role, and the user lands in the workspace with that role's permissions — no invitation, no admin approval step.
- Second and subsequent sign-ins never change the user's role or permissions, even if the provider's default role is later changed.
- Changing the default role on a provider configuration affects only future first-time sign-ins; existing members keep their current roles.
- With no default role configured, a first-time OIDC visitor to the tenant is rejected with the same clean "no access to this workspace" message as any non-member; no membership record is created.
- The provider configuration form enforces the default-role field validation (only seeded presets selectable) and reflects saved changes immediately without a page reload.

**Isolation & Security (must be testable)**
- A tenant A user attempting to open, list, search, edit, or delete any tenant B record (agents, roles, MCP hubs, skills, SOPs, schedules, model configs, conversations, outputs, API keys) — including by guessing or forging references — receives "not found / permission denied" and sees no tenant B data.
- Directly addressed requests for another tenant's identifiers return no data and are recorded as security-relevant audit events visible to the platform admin.
- Agents executing for tenant A can only use tenant A's skills, tools, credentials, and identities; agent-to-agent messages cannot cross tenants.
- API keys belong to a tenant; a tenant A API key cannot read or call any tenant B resource.
- Platform admin can manage tenant metadata and licenses but cannot browse tenant business data or alter a tenant root; tenant admins cannot see platform configuration or other tenants.
- A security review confirms: through any interface (UI, API, agent execution, scheduling, notifications, MCP tools), no user, agent, or API key action can read or write another tenant's data.

**Single-Tenant Compatibility**
- An upgraded existing installation with the switch off behaves identically to before (sign-in, roles, agents, integrations, dashboard, scheduling).
- All existing backend, frontend, and E2E tests pass with the switch off, without modification.

## Out of Scope

- Billing, payment collection, subscriptions, invoicing, and self-service plan purchase — **license/tier assignment is manual by the platform admin in this epic**; tier/quota *enforcement* is explicitly in scope, but charging for it is not.
- Owning multiple tenants per user (limit fixed at 1 for now; raising the limit is future work).
- Rate-limiting policies beyond the tier quotas (e.g., per-user or per-API-key throttling).
- Data residency customization or per-tenant region selection.
- Per-tenant dedicated infrastructure (dedicated databases, dedicated compute, single-tenant pods).
- Cross-tenant sharing, collaboration, marketplaces, or template exchange.
- White-label branding customization per tenant (beyond the tenant address and alias).
- Automated export/import migration of tenants between deployments.
- Group-based role mapping from OIDC claims (e.g., mapping corporate groups to tenant roles) — sign-in onboarding uses only the per-provider default role in this epic.
- SCIM or any other automated user-provisioning/de-provisioning protocol; membership changes outside first sign-in remain manual (invitations by tenant admins).

## Dependencies & Constraints

- **Identity providers**: tenants bring their own OIDC provider (Keycloak, Azure EntraID, or any OIDC-compliant provider); each tenant requires its own sign-in registration in its provider. The owner's email + password account is issued by the platform itself and does not depend on any OIDC provider.
- **License catalog**: tier names (free / team / enterprise) and the default limits per tier (max users, max agent types, monthly executions) must be agreed before enforcement ships; the free tier is the automatic fallback for every unlicensed tenant.
- **Usage metering accuracy**: monthly execution counts depend on complete tenant attribution of every execution record; quota reporting is only as accurate as that attribution.
- **Hosted environment**: wildcard DNS and certificates are required to support per-tenant web addresses.
- **Architecture rules (non-negotiable)**: three segregated backend services; agents run only in Agent Runtime; only Control Center accesses the database; agents never hold identity tokens or secrets. Tenant enforcement and quota counting must respect and reinforce these boundaries.
- **Permission model**: the existing fine-grained resource-type manifest (with wildcards) continues to apply within each tenant; new tenant-management and license-management resource types must be registered consistently in both backend and frontend manifests to avoid access breakage.
- **Default-off constraint**: the tenancy switch defaults to disabled; single-tenant behavior must be preserved exactly for all existing deployments.
- **Audit & observability**: audit trails and telemetry must gain tenant attribution so cross-tenant attempts, root-protection violations, and quota events are traceable end to end.
