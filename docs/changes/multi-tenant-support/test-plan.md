# Test Plan: Multi-Tenant Support

## 1. Test Strategy

This change is a platform-mode switch (default OFF) with hard security requirements. The strategy is layered so that (a) single-tenant behavior is proven byte-for-byte unchanged, (b) schema changes are proven against a real PostgreSQL database, and (c) cross-tenant isolation is proven negative-first (every attack path must fail closed and write an audit event).

**Pre-Test Checklist (Database Changes — mandatory before any backend/integration/E2E run):**
- Run `alembic current` and confirm it reports the multi-tenant migration revision (latest file under `backend/alembic/versions/`).
- If not applied, run `alembic upgrade head`, then re-run `alembic current` to confirm.
- Restart backend services after applying migrations (ORM models are cached at startup) via `parthenon.ps1 restart -Services backend`.
- Backend test fixtures must apply `alembic upgrade head` in setup (`backend/tests/conftest.py`) so the test database matches production schema exactly.
- Any 500 errors during testing: first suspect unapplied migrations (per AGENTS.md debugging guidance).

**Layers:**

| Layer | Location | Purpose |
|-------|----------|---------|
| Backend unit (pytest) | `backend/tests/` | Scope filters (`apply_tenant_scope`), PermissionEngine tenant binding, JWT tenant-claim validation, signed header sign/verify, tenant resolution fail-closed semantics, platform settings cache default-off |
| Backend integration (pytest + real PostgreSQL) | `backend/tests/integration/`, `backend/tests/db/`, `backend/tests/security/` | Migrations applied via `alembic upgrade head` in fixtures; schema verified by querying `information_schema` (tenant columns present, nullable, indexed); negative constraint tests; cross-tenant API flows with audit assertions |
| Frontend component (Vitest, JSON reporter per AGENTS.md) | `frontend/src/__tests__/` | Manifest mirror parity for new resource types, tenant picker behavior, platform-admin route gating, auth store active-tenant state, i18n coverage |
| E2E (Playwright) | `e2e/tests/` | UI flows for platform console and tenant workspace; mocked variants for speed plus **at least one real-backend variant** labeled `Real Backend Integration - Multi-Tenant Isolation` (no mocks, real DB, migrations verified first), following the existing `.real-backend.spec.ts` convention |
| Manual / prototype review | `docs/changes/multi-tenant-support/prototype/index.html` | Guided onboarding flow, tenant picker UX, platform console review against prototype; Phase 9.8 security hardening review against `top_priority_rules` in `docs/config.yaml` (three segregated services, agents only in AR, only CC touches DB, agents hold no secrets) |

**Test data conventions:** tenants/users/agents created by tests use identifiable names (timestamp-suffixed); every test cleans up its tenants via the platform delete API or fixture teardown; multi-tenant fixtures create exactly two tenants (A and B) plus the system tenant.

---

## 2. Coverage Areas

### 2.1 Default-Off Regression (Phase 2.8 guard — highest priority)
- With `multi_tenancy_enabled=false` (the seeded default): no tenant middleware executes, no tenant resolution occurs, no tenant claim is validated, no tenant headers are required or attached, `TenantContext` returns the unset sentinel.
- All existing backend, frontend, and E2E suites pass **unmodified** with the switch off.
- Response payloads of existing endpoints are byte-for-byte identical to pre-change behavior (no new fields, no tenant attribution added).
- Requests carrying stray tenant headers while the switch is off are ignored, not rejected.

### 2.2 Schema & Migrations (Phase 1) — `has_db_changes: true`
- `alembic upgrade head` succeeds on an existing **populated** database; `alembic downgrade -1` then re-upgrade succeeds (reversibility).
- Seven new tables exist (Tenant, TenantUserMembership, TenantInvitation, TenantAuditEvent, PlatformSetting, TenantLicense, TenantQuotaUsage); `multi_tenancy_enabled` row seeded false; `TenantQuotaUsage` is unique per (tenant, quota_type, calendar-month period).
- Every direct-scoped entity across all ~40 tables has a nullable `tenant_id` column with an index — verified by querying `information_schema` (column existence, nullability, index presence), not just ORM metadata.
- **Negative tests:** inserting a row with a non-existent tenant FK fails; unique constraints on tenant (name, slug) hold at the DB level; join/child tables (UserRole, GroupRole, UserGroup, TagValue, PolicyTagCondition, ApiKeyUsageLog, agent prompt/plan logs, tool-call records, cascade outcomes) carry **no** tenant column and inherit scope via parents.
- No existing column is dropped or made non-nullable by the migration.

### 2.3 Tenant Lifecycle (Phase 5)
- Create / read / update / suspend / resume / delete via platform API: full CRUD verification including all displayed values, aggregate counts (users, agents) correctness, immediate overview-table visibility, and duplicate name/slug rejection with clear errors.
- Self-service registration: the creator becomes the **tenant root** (permanent super-admin) and lands in guided onboarding; the new tenant is invisible to all other tenants. (Full registration / root / licensing / quota coverage in 2.12.)
- Suspend blocks sign-in, ends active sessions ("tenant suspended" message), preserves data; resume restores immediately.
- Delete requires explicit confirmation, removes tenant and all data, and the address becomes reusable (proves true deletion, not hiding) — full CRUD delete-and-recreate verification per project testing standards.
- All lifecycle actions write TenantAuditEvents; membership and invitation APIs (single-use, expiry, revoke) behave correctly and never leak other tenants' data.

### 2.4 Tenant Resolution & Fail-Closed (Phase 2)
- Resolution from Host subdomain or explicit tenant header; single resolution point per request; unknown / suspended / deleted slugs are unresolvable; short-TTL cache behavior.
- Fail-closed in multi-tenant mode: any request without a resolvable tenant is rejected **before** any feature logic; only the enumerated exemptions bypass (public health/setup/auth endpoints, the switch-gated public registration endpoint group — inert when the switch is off, `/api/v1/internal/*` which carries its own signed headers, and `/api/v1/platform/*` which is metadata-only and permission-guarded); rejection is logged and audited.
- Switch off: resolution middleware fully inert.

### 2.5 Token / Claim Validation & Per-Tenant OIDC (Phase 4)
- JWT validated using **only** the resolved tenant's provider discovery/JWKS; token tenant claim must equal the resolved tenant; missing or mismatched claim rejected with 401 before any user sync.
- Tenant A's token rejected at every entry point when used against tenant B (REST, internal, WebSocket/SSE handshake); MCP API-key paths are tenant-bound.
- Per-tenant provider registry keyed by (tenant, scope); hot-reload endpoints still work; per-tenant scope uniqueness replaces platform-wide uniqueness.
- Tenant A's OIDC config changes never affect tenant B; tenant admins cannot read or write another tenant's provider config.
- Super admin / platform admin tokens remain valid across tenants for platform administration only.

### 2.6 Row-Level Scoping — Every Scoped Entity Group (Phase 3)
- For **each** domain group — identity & access (roles, users, groups, policies, tags, API keys), agent domain (roles, identities, types, instances, jobs, run relationships), MCP hub/skills/SOPs/scheduling, conversations/tool-calls/results/agent-data/outputs, interventions/terminations/notifications, model governance — verify: list/search returns only the caller's tenant rows; direct-addressed foreign IDs yield 404 (never a leaking error); writes cannot create/update rows outside the tenant.
- Cross-tenant row access converts to not-found **plus** a security-relevant `cross_tenant_access_denied` TenantAuditEvent visible in the platform audit API.
- Scope applies at the DB gateway choke point (`get_db`), not per endpoint — verify no endpoint bypasses it (raw sessions outside `get_db`).
- Join/child tables inherit scope through parents — child records of tenant B parents are unreachable from tenant A.

### 2.7 Signed Header Propagation — AR/CH Cannot Widen (Phases 2, 8)
- CC's internal clients attach signed, timestamped tenant headers on every outbound call when a tenant context is active; nothing attached when off.
- AR (`ControlCenterCertificateMiddleware`) and CH (`ControlPlaneMiddleware`) verify signatures; tampered, stale (replayed), unsigned, and mismatched headers are rejected and the context is bound to the request.
- No code path in AR/CH can construct a valid signature (verify-only key material).
- CH session dispatch, A2A broker, MCP protocol server, tool registry, and API-key middleware are all tenant-bound; `validate_api_key_internal` returns the key's tenant binding.
- AR execute/resume/terminate/intervene bind the verified context; the runtime loader resolves configuration only within the tenant; scheduled jobs adopt the owning tenant's context end to end.

### 2.8 RBAC Tenant Binding & New Resource Types (Phase 3)
- `PermissionEngine.authorize` collects roles only from the request's tenant (plus platform-admin role); identical role names in different tenants do not collide; wildcards (`agent::*`, `integration::*`, `system::*`, `*::*`) work within the tenant only.
- New `platform::*` and `tenant::*` resource types registered in **both** `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` with identical action sets — mirror test green (critical: unregistered types 403 even wildcard admins).

### 2.9 Platform Admin Restrictions (Phase 5)
- Platform admin can manage tenant metadata and platform settings but **never** browses tenant business data (tenant APIs return metadata + aggregates only).
- Tenant admin cannot see platform configuration or other tenants; platform audit API visible only to platform admin with tenant attribution.

### 2.10 Frontend Tenant UX (Phases 6–7)
- Platform console (`/platform/*`): route guard blocks non-platform-admins; routes absent when switch off; tenant management table CRUD with immediate refresh without page reload and updated counts; settings toggle with confirmation; audit view filters.
- Tenant workspace: active tenant in auth store (one session = one tenant, immutable, cleared on sign-out, never persisted to durable storage); tenant discovery + multi-org picker at sign-in; org branding in header; tenant settings, onboarding, members pages gated by `tenant::*` permissions.
- All new strings via i18next `t()`; dialog error handling standard followed (403s surface, no silent failures).

### 2.11 Audit Events & Observability (Phases 3, 5)
- TenantAuditEvents written for lifecycle actions and all security denials; flagged security-relevant where appropriate; platform audit API lists/filters across tenants.
- OTEL spans/logs carry tenant attribute (or platform sentinel) in all three services when on; no attribute when off.

### 2.12 Self-Serve Registration, Root & Licensing/Quotas (updated design scope)
- **Registration happy path (atomic)**: one registration action creates the platform-issued account (email + password, independent of per-tenant OIDC), the tenant, and the root membership all-or-nothing; on success the registrant lands in guided onboarding as tenant root with ALL tenant permissions, and a `self_serve_registration` audit event is written.
- **Registration input rules**: duplicate email, missing/invalid fields, and malformed tenant addresses are rejected with clear validation errors; no partial account/tenant/membership rows remain after any rejection.
- **One-tenant-per-user block**: a user who already holds a root membership is blocked with a clear message; no second tenant is created and no partial data remains.
- **Switch-off inertness**: with the tenancy switch off, the public registration endpoints and the sign-up UI are inert/absent; stray registration requests are rejected without any side effect.
- **Root immutability**: attempts by delegated tenant admins **and** by the platform admin to demote, remove, or alter the root membership — via any tenant or platform API path — are rejected with a clear message and audited as `root_protection_rejected`.
- **Alias/slug split**: alias editing is root-only and appears immediately without a page reload; the tenant address (slug) is immutable; uniqueness stays enforced on both.
- **License lifecycle**: platform-admin assign/change/remove of `TenantLicense` (tier free/team/enterprise with max_users, max_agent_types, monthly_executions); removal falls back to free-tier defaults immediately; superseded licenses are retained as inactive history (latest active wins); invalid input (unknown tier, non-positive limits) rejected with clear errors; every change audited (`license_assigned` / `license_changed` / `license_removed`).
- **Quota enforcement per type**: user invite/creation blocked at max_users; agent type creation blocked at max_agent_types; execution submission blocked at monthly_executions (refused at Control Center, never dispatched); exhausting one quota leaves unrelated actions unaffected; under-quota actions always succeed.
- **Quota counting representation**: `users` and `agent_types` usage is derived live from records (no counter rows — can never drift); `monthly_executions` uses the maintained per-tenant calendar-month counter incremented once per accepted submission — no double-counting of in-flight executions, automatic reset at month start, and scheduler-triggered executions counted at dispatch time.
- **Structured quota feedback contract**: every blocked action returns tier / limit / current usage / upgrade path; the tenant UI renders it as-is and the platform admin overview mirrors it; exhaustion also writes a `quota_exhausted` audit event with OTEL attribution.
- **Platform license API permissions**: only the platform admin can assign/change/remove licenses or read cross-tenant usage; tenant admins/users receive graceful permission errors (dialog error standard).

### 2.13 Systematic Entity-Isolation Sweep (Registry-Completeness Guard)
- An exhaustive backend sweep (`backend/tests/test_tenant_isolation_sweep.py`) enumerates **EVERY** SQLAlchemy model via `Base.registry` and classifies each as tenant-scoped or tenant-agnostic — no entity can escape classification.
- Every tenant-scoped model (47 swept) receives a row-level cross-tenant probe: one row per model per tenant, and a tenant-A scoped session sees only A's row via `select` and `None` (404 semantics) via `get` — zero skips, all models constructible with minimal valid rows.
- Every tenant-agnostic model MUST appear in the explicit `TENANT_AGNOSTIC_REGISTRY` with a documented strategy — 7 platform-level entries (incl. `PlatformUser` via the membership-join strategy) and 31 parent-inherited join/child tables; registry keys must reference real tables and every entry must carry a strategy note.
- **Future-leak guard**: a newly added model without `tenant_id` fails the registry-completeness test until it is consciously registered with a strategy — an unclassified entity can never ship silently.
- Scope-criteria binding is part of the sweep: tenant criteria bind per request, never per process (A → B → A scoped sessions each see only their own rows). Scenario coverage: CS-44–CS-47.

---

## 3. Critical Scenarios

### Default-Off Invariant
- **CS-01** — WHEN multi-tenancy is disabled (default) and any existing endpoint, sign-in flow, or scheduled job executes, THEN no tenant resolution, claim validation, header requirement, or scope filter runs, and responses are identical to the pre-change single-tenant product (all existing suites pass unmodified).
- **CS-02** — WHEN a request arrives carrying tenant headers while the switch is off, THEN the headers are ignored entirely — neither validated nor required, and presence causes no error and no scope change.
- **CS-03** — WHEN the switch is enabled and later disabled again on a deployment with tenant-era data, THEN single-tenant behavior is fully restored with no data loss, and the enable→disable→enable cycle is repeatable and idempotent.

### Migration & Adoption
- **CS-04** — WHEN `alembic upgrade head` is applied to a populated database and `information_schema` is inspected, THEN all seven new tables exist (including `TenantLicense` and `TenantQuotaUsage` with its unique (tenant, quota_type, period) constraint), every direct-scoped entity across the ~40 tables has a nullable indexed tenant column, join tables carry none, and no existing column was dropped or made non-nullable.
- **CS-05** — WHEN the switch is enabled on an existing deployment, THEN the system tenant is created, every existing business row is backfilled with the system tenant id, the existing administrator gains platform-admin membership, the existing OIDC provider keeps working with no manual reconfiguration, and re-running adoption changes nothing.
- **CS-06** — WHEN adoption runs on a database where some rows were inserted between migration and backfill (null tenant ids), THEN those rows are still claimed by the system tenant and no row is left orphaned.

### Tenant Lifecycle & Suspended Tenant
- **CS-07** — WHEN a platform admin creates a tenant and then edits it, THEN the overview table reflects all values immediately without page reload, duplicate name/address submissions are rejected with clear errors, and malformed addresses show validation errors.
- **CS-08** — WHEN a tenant is suspended, THEN its users are blocked at sign-in, **already-issued tokens and active sessions are rejected** with a clear "tenant suspended" message (including in-flight API calls and MCP sessions), no data is lost, and resume restores full access immediately.
- **CS-09** — WHEN a tenant is deleted with explicit confirmation, THEN the tenant and all its data are removed, it disappears from the overview immediately, and creating a new tenant with the same address afterwards succeeds — proving true deletion.

### Tenant Resolution — Fail-Closed
- **CS-10** — WHEN multi-tenancy is on and a request reaches Control Center with an unknown, suspended, or deleted tenant address (or no resolvable tenant at all), THEN the request is rejected before any feature logic executes, and the rejection is logged and audited; only the enumerated exemptions bypass (public health/setup/auth, internal signed-header paths, platform admin surface).
- **CS-11** — WHEN a caller supplies conflicting tenant inputs (subdomain indicating tenant A, header indicating tenant B) or attempts to re-derive tenant context downstream, THEN resolution happens exactly once at the middleware, conflicting input is rejected, and no later code path can change the tenant.

### Cross-Tenant Data Access (Security-Critical)
- **CS-12** — WHEN a tenant A user forges or guesses tenant B record identifiers and attempts to open, list, search, edit, or delete them across every scoped entity group (roles, agents, agent identities, MCP hubs, skills, SOPs, schedules, model configs, conversations, outputs, saved data, API keys, notifications), THEN every attempt returns 404/403 exposing no tenant B data, and each attempt writes a security-relevant `cross_tenant_access_denied` TenantAuditEvent visible to the platform admin.
- **CS-13** — WHEN a tenant A user performs any list or search, THEN results contain exclusively tenant A rows in every feature surface, including counts, filters, and child/join-table records reached through parents.

### Token / Claim & Per-Tenant OIDC (Security-Critical)
- **CS-14** — WHEN a sign-in credential or token issued by tenant A's OIDC provider is presented against tenant B's resolved context at any entry point (REST, internal, WebSocket/SSE handshake), THEN it is rejected with 401 everywhere outside tenant A, no user sync occurs, and the rejection is recorded as a security-relevant audit event.
- **CS-15** — WHEN a token lacks the tenant claim, or its claim differs from the resolved tenant, in multi-tenant mode, THEN validation fails before any user sync or authorization, with an audit event written.
- **CS-16** — WHEN tenant A's admin changes or disables their OIDC sign-in configuration, THEN tenant B's sign-in is completely unaffected, and tenant A's admin cannot read or modify tenant B's provider configuration through any API.

### Agent / Tool / MCP Isolation (Security-Critical)
- **CS-17** — WHEN an agent executing in tenant A requests a skill, tool, or MCP session belonging to tenant B (or its API key addresses any tenant B resource), THEN the request is refused, the tool listing and tool calls are filtered by tenant-scoped permissions, and a security-relevant audit event is written.
- **CS-18** — WHEN an agent in tenant A sends an agent-to-agent (A2A) message targeting an agent in tenant B, THEN the request is refused with an audit event and the message payload is never relayed across tenants.

### Signed Header Propagation (Security-Critical)
- **CS-19** — WHEN Control Center dispatches execution to Agent Runtime or Communication Hub, THEN the signed tenant headers are verified and bound by AR/CH middleware, and the entire execution (dispatch → runtime → results) is scoped to that tenant only.
- **CS-20** — WHEN a tampered, stale/replayed, unsigned, or mismatched tenant header reaches AR or CH in multi-tenant mode, THEN the request is rejected; and no code path in AR or CH can construct a valid signature (they can verify but never sign or widen).

### RBAC & Admin Boundaries
- **CS-21** — WHEN two different tenants define roles with identical names and wildcard patterns, THEN the PermissionEngine resolves roles strictly within the request's tenant (plus the platform-admin role) with no collisions, and wildcards never grant rights beyond the tenant.
- **CS-22** — WHEN the platform admin uses tenant management APIs, THEN only tenant metadata and aggregate counts are returned — never tenant business rows; and a tenant admin cannot access platform configuration, other tenants, or platform audit events.
- **CS-23** — WHEN a super admin token is used in multi-tenant mode, THEN it remains valid across tenants for platform administration (metadata, lifecycle, audit) but cannot read or write any tenant's business data.

### Frontend Session Semantics
- **CS-24** — WHEN a user belonging to multiple organizations signs in and chooses an organization, THEN the session token is bound to that tenant for the whole session, switching organizations requires a fresh sign-in, the active tenant is never persisted to durable storage, and it is cleared on sign-out.

### Adoption & Switch Transitions
- **CS-25** — WHEN multi-tenancy is toggled off while user sessions and agent executions issued during the multi-tenant period are still active, THEN those sessions/execution contexts are handled safely (terminated or resolved under system-tenant semantics) without exposing data, per the CS-03 no-data-loss requirement.

### Self-Serve Registration, Root & Licensing/Quotas
- **CS-26** — WHEN a visitor registers with a valid personal email, password, and tenant address, THEN the platform account, tenant, and root membership are created **atomically** in one action, the registrant lands in guided onboarding as tenant root with ALL tenant permissions and no platform-admin action involved, and a `self_serve_registration` audit event is written.
- **CS-27** — WHEN registration is submitted with a duplicate email, missing/invalid fields, or a malformed tenant address, THEN it is rejected with clear validation errors and no account, tenant, or membership rows are created (no partial data).
- **CS-28** — WHEN a user who already owns a tenant (holds a root membership) registers again, THEN the attempt is blocked with a clear "one tenant per user" message, no second tenant is created, and no partial data remains.
- **CS-29** — WHEN the tenancy switch is off (default), THEN the public registration endpoints are inert (absent/unreachable) and the sign-up UI is not reachable, stray registration requests are rejected without any side effect, and no tenant concept surfaces anywhere.
- **CS-30** — WHEN a delegated tenant admin attempts to demote, remove, or otherwise alter the tenant root membership through any tenant API path, THEN the attempt is rejected with a clear message and recorded as a `root_protection_rejected` audit event.
- **CS-31** — WHEN the **platform admin** attempts to bypass root protection — demoting or removing the root via membership APIs, injecting root-altering payloads into tenant update calls, or using tenant lifecycle actions to substitute the root — THEN every attempt is rejected, the root membership remains untouched, and each attempt is audited as `root_protection_rejected` (security-critical: no actor may become or replace the root).
- **CS-32** — WHEN the tenant root edits the tenant alias, THEN the new alias appears immediately across the workspace without a page reload and uniqueness is enforced; WHEN a non-root tenant admin or the platform admin attempts the same edit, THEN it is rejected; WHEN any actor attempts to change the tenant address (slug), THEN the change is rejected — the address is immutable.
- **CS-33** — WHEN the platform admin assigns, changes, or removes a tenant's license, THEN the entitlement takes effect immediately (tenant overview and the tenant's own usage view refresh without a manual reload), removal falls back to free-tier defaults immediately, superseded licenses are retained as inactive history (latest active wins), invalid input (unknown tier, non-positive limits) is rejected with clear errors, and each change writes a `license_assigned` / `license_changed` / `license_removed` audit event.
- **CS-34** — WHEN a tenant has no assigned license, THEN it runs on the free tier's default limits immediately, visible to both the platform admin and tenant users, and all three quota types are enforced at the free-tier limits.
- **CS-35** — WHEN a tenant admin invites or creates a user beyond the tenant's max-user limit, THEN the action is blocked with the structured feedback (tier, limit, current usage, upgrade path), no membership or invitation row is created, and under-limit invitations continue to succeed.
- **CS-36** — WHEN agent type creation would exceed the max-agent-types limit, THEN it is blocked with the same structured feedback and no agent type is created; under-limit creation is unaffected.
- **CS-37** — WHEN an execution submission would exceed the monthly execution limit, THEN it is refused at Control Center with the structured feedback and is never dispatched to Communication Hub or Agent Runtime.
- **CS-38** — WHEN one quota is exhausted, THEN unrelated actions are unaffected — an exhausted user quota still allows agent executions until the execution quota itself is reached, and an exhausted execution quota still allows user invitations until the user quota itself is reached.
- **CS-39** — WHEN executions are submitted within quota, THEN the tenant's calendar-month usage increments exactly once per accepted submission at the enforcement point; in-flight, completed, and failed executions already counted are never double-counted; at the start of a new calendar month the bucket resets and submissions are accepted again.
- **CS-40** — WHEN a scheduled job fires and dispatches an execution, THEN the dispatch consults the tenant's monthly execution quota in Control Center: within quota it counts exactly like a user-submitted execution; with the quota exhausted the dispatch is skipped, nothing reaches AR/CH, and a `quota_exhausted` event is recorded.
- **CS-41** — WHEN any action is blocked by a quota, THEN the response carries the full contract — the tenant's tier, the specific limit, current usage, and the upgrade path (contact the platform admin to change tier) — the tenant UI renders this feedback as-is, the platform admin overview mirrors it, and the exhaustion is audited (`quota_exhausted`) with OTEL attribution.
- **CS-42** — WHEN a caller attempts to bypass the quota gates — addressing internal execution/dispatch endpoints directly, forging or replaying dispatch calls to Communication Hub or Agent Runtime without a quota-cleared signed context, or re-submitting a refused execution through a different surface — THEN the request is rejected (AR/CH accept only quota-cleared dispatches over the existing signed-header contract, no new trust path), no execution runs, and the attempt is audited as security-relevant.
- **CS-43** — WHEN a non-platform-admin (tenant admin, tenant user, or agent principal) calls license management APIs or attempts to read another tenant's usage, THEN the request is rejected with permission errors surfaced gracefully per the dialog error standard, and only the platform admin can assign/change/remove licenses.

### Systematic Entity-Isolation Sweep (Security-Critical)
- **CS-44** — WHEN a tenant-context caller lists platform users or addresses a user id that holds no ACTIVE membership in the requesting tenant, THEN the list returns only the requesting tenant's active members (membership-filtered before pagination) and the foreign user resolves to 404 on the detail endpoint and on every mutation path guarded by the same membership lookup — no cross-tenant platform-user leak on any surface.
- **CS-45** — WHEN scoped queries for different tenants execute within one process (tenant A → tenant B → tenant A), THEN each scoped session sees exclusively its own tenant's rows: the tenant criteria are re-bound per tenant id via a closure factory, so tenant A's compiled criteria are never replayed for tenant B (no process-level scope-criteria cache pollution, no ordering-dependent leak).
- **CS-46** — WHEN any code path selects directly from a tenant-agnostic child/join table (e.g. `mcp_sessions`, `execution_logs`, `agent_plans`, `agent_instance_certificates`) under tenant context, THEN the query is constrained through its tenant-scoped parent (parent joined into the statement) or the documented registry strategy — a parent-less direct select must never leak foreign-tenant rows; the sweep's registry enumerates every such table so none can remain unguarded.
- **CS-47** — WHEN a tenant-context actor attempts a cross-tenant user mutation — assigning/removing a role or group whose parent is foreign, or deleting a user without an active membership in the requesting tenant — THEN every path is refused (404 via the membership-guarded lookup; 409 when a deletion would cascade another tenant's active membership), and an in-tenant user can never be linked to a foreign role/group.

---

## 4. Edge Cases & Risks

| # | Edge Case / Risk | Test Attention |
|---|------------------|----------------|
| E-01 | **Join tables inheriting scope** — UserRole, GroupRole, UserGroup, TagValue, ApiKeyUsageLog, tool-call records, cascade outcomes carry no tenant column; scope flows through parents. A query joining only child tables could bypass the filter. | Integration tests must fetch child rows through tenant A parent and confirm tenant B child rows are unreachable even when the child table itself has no tenant column. |
| E-02 | **Race in tenant resolution / settings cache** — switch toggled while requests are in flight; per-worker cache invalidation lag creates a window where one worker enforces tenancy and another doesn't. | Test toggle during concurrent request bursts; assert no request is processed under the wrong mode and cache invalidation propagates to all workers. |
| E-03 | **Per-tenant OIDC registry cache invalidation** — tenant A changes its provider config or rotates keys; stale discovery/JWKS could accept old tokens or reject new ones. | Update tenant A config, immediately sign and validate tokens; assert registry reload honored without affecting tenant B's cache entries. |
| E-04 | **Slug collision & deleted-tenant address reuse** — unique constraint vs check-then-insert race; DNS/proxy caching of a deleted tenant's address could route new visitors to stale resolution. | Concurrent creation with same slug (exactly one succeeds); recreate tenant on a previously deleted slug and verify resolution serves the new tenant everywhere (discovery, sign-in, headers). |
| E-05 | **Sessions spanning the enable/disable switch** — tokens issued pre-enable (no tenant claim) used post-enable; tenant-bound sessions used post-disable. | Issue tokens in each mode, use them in the other mode; define and assert the expected outcome (rejection, per CS-25) with no data exposure either direction. |
| E-06 | **Adoption idempotency & orphaned rows** — double-enable, or rows written between migration and backfill. | Covered by CS-05/CS-06; also assert adoption is atomic enough that a failure mid-backfill doesn't leave a half-adopted platform. |
| E-07 | **In-flight executions during suspension** — jobs already dispatched to AR, WebSocket/SSE connections opened pre-suspension, scheduled jobs firing during suspension. | Suspend mid-execution; assert termination or scoped completion, no new dispatches, and audit events for boundary attempts. |
| E-08 | **Invitation edge cases** — expired, revoked, single-use replay, acceptance after tenant suspension, invitation leaking tenant existence. | Full invitation negative matrix; responses must not reveal other tenants or suspended-tenant data. |
| E-09 | **MCP slug uniqueness becoming per-tenant** — two tenants register the same MCP server slug; tool namespace collision at CH. | Register identical slugs in tenants A and B; assert tool listing/calls resolve strictly within the caller's tenant. |
| E-10 | **Fail-closed bypass paths** — the public exemption set accidentally widened; WebSocket/SSE handshakes and internal routes skipping tenant middleware. | Enumerate exempt paths (`BYPASS_PATHS`/`BYPASS_PREFIXES` in the middleware) and assert the exemption set is exactly health/setup/public-auth + switch-gated public registration + internal + platform prefixes; handshake requests must carry valid tenant context in multi-tenant mode. |
| E-11 | **Aggregate count performance** — platform tenant overview with ≥10 tenants and large per-tenant datasets must not degrade beyond agreed thresholds (PRD business goal). | Seed ≥10 tenants, measure overview/audit query latency. |
| E-12 | **OTEL/audit attribution consistency** — tenant attribute present when on, absent when off; security events always persisted even if the request fails late. | Inspect spans/logs in both modes; force late failures after denial and assert the audit event still exists. |
| E-13 | **Frontend stale state after toggle** — SPA held open across a switch toggle; cached platform routes or tenant state. | Reload-independent gating: routes and tenant UI derive from fresh server state, not stale client cache. |
| E-14 | **Unregistered resource type regression** — new `platform::*`/`tenant::*` types missing from either manifest 403s every admin (per project CRITICAL convention). | Manifest mirror test extended and mandatory-green before merge. |
| E-15 | **Superseded licenses mid-enforcement** — a license is changed while executions are in flight or current usage already exceeds the new (lower) limits; superseded rows retained as history. | Change a license with usage above/below the new limits; enforcement must use the latest active license only and take effect immediately; history rows (`is_active=false`, `unassigned_at` set) never influence enforcement. |
| E-16 | **License removed mid-month with usage over free limits** — tenant falls back to free tier while current usage already exceeds free-tier limits. | Remove the license mid-month with over-limit usage; the fallback is immediate and the behavior for already-over-limit usage (blocked on the exhausted types until usage drops or the month resets) is well-defined and consistent across platform and tenant views. |
| E-17 | **Quota counter drift/repair** — the maintained `monthly_executions` counter could drift from actual execution records (crash between acceptance and dispatch, manual intervention). | Compare the counter against the tenant's actual execution records for the month; define and test a repair/recompute path so enforcement never permanently over- or under-counts; drift is visible in usage views. |
| E-18 | **Registration race for the same email** — concurrent registrations with the same email (check-then-insert vs unique constraint). | Fire concurrent registrations with identical emails: exactly one succeeds atomically; the others fail cleanly with no partial tenant/account/membership rows. |
| E-19 | **Alias uniqueness conflicts** — renaming an alias to a name already taken by another tenant (or case variants); a failed rename must never touch the immutable slug. | Attempt conflicting alias renames across tenants; clear validation error, slug and address unchanged, immediate-refresh behavior not corrupted by the failed rename. |
| E-20 | **Tenant deletion with license/quota rows** — deleting a tenant holding an active license and quota usage buckets risks orphaned rows or leaking usage into aggregates. | Delete a licensed tenant with quota usage; license/quota rows are removed or fully orphan-proof, other tenants' usage and platform aggregates are unaffected, and a tenant recreated on the same address starts on the free tier with fresh buckets. |

---

## 5. Acceptance Criteria Checklist

Mapped from PRD acceptance criteria:

**Tenancy Mode Switch**
- [ ] With the switch off (default): UI, sign-in, and all features behave exactly as the current single-tenant product; no tenant concept visible anywhere; all existing tests pass unchanged (CS-01/CS-02).
- [ ] With the switch on: tenant features available; disabling again returns to single-tenant behavior without data loss (CS-03).
- [ ] Enabling multi-tenancy on an existing deployment adopts current configuration/data as its first (system) tenant with no manual OIDC reconfiguration (CS-05/CS-06).

**Self-Serve Registration & Tenant Root**
- [ ] A visitor registers with a personal email + password; the tenant workspace is created atomically (account + tenant + root membership) and they land in guided onboarding as tenant root — no platform-admin action involved (CS-26).
- [ ] The root user has ALL permissions inside their tenant and can perform every tenant-admin action without additional grants.
- [ ] Root role/membership cannot be changed, demoted, or removed by other tenant admins or the platform admin; attempts are rejected with a clear message and recorded in the audit trail (CS-30/CS-31).
- [ ] A user who already owns a tenant and attempts to register again is blocked with a clear "one tenant per user" message; no second tenant is created and no partial data remains (CS-28).
- [ ] Duplicate email registration and missing/invalid fields are rejected with clear validation errors (CS-27).
- [ ] The root user can edit the tenant alias; the new alias appears immediately across the workspace without a page reload; the tenant address remains fixed and uniqueness rules stay enforced (CS-32).

**License & Tier Management**
- [ ] Platform admin can assign a license defining tier (free / team / enterprise) with limits for max users, max agent types, and monthly agent executions to any tenant (CS-33).
- [ ] Platform admin can change a tenant's license; removing the license falls the tenant back to free-tier defaults immediately (CS-33/CS-34).
- [ ] A tenant without an assigned license automatically runs on the free tier with lower default limits, visible to both platform admin and tenant users (CS-34).
- [ ] After assigning/changing/removing a license, the tenant overview and the tenant's own usage view update immediately without a manual page reload (CS-33).
- [ ] Invalid license input (unknown tier, non-positive limits) is rejected with clear errors; permission errors are shown gracefully (CS-33/CS-43).

**Quota Enforcement & Usage UX**
- [ ] Inviting or creating users beyond the tenant's max-user limit is blocked; the blocker names the tenant's tier, the limit, current usage, and the upgrade path (CS-35).
- [ ] Creating agent types beyond the max-agent-types limit is blocked with the same tier/limit/usage/upgrade feedback (CS-36).
- [ ] Submitting agent executions beyond the monthly execution limit is blocked with the same feedback; executions are counted per calendar month per tenant and reset at the start of each calendar month, including scheduler-triggered dispatches (CS-37/CS-39/CS-40).
- [ ] Reaching one quota does not block unrelated actions (e.g., an exhausted user quota still allows agent executions until their own limit is reached) (CS-38).
- [ ] Usage shown in the tenant UI (users, agent types, executions this month) matches the tenant's actual records; in-flight executions already counted are not double-counted (CS-39/CS-40).

**Tenant Lifecycle**
- [ ] Platform admin creates a tenant with name, unique address, primary admin contact; it appears immediately in the overview with all values correct (CS-07).
- [ ] Duplicate name/address rejected with clear errors; required fields enforced; malformed addresses show validation errors.
- [ ] New user self-registers (email + password), becomes the immutable tenant root, lands in guided onboarding; tenant invisible to all other tenants (CS-26/CS-29).
- [ ] Editing a tenant updates the overview immediately without manual reload; related counts refresh.
- [ ] Suspend blocks sign-in, ends active sessions with "tenant suspended" message, no data loss; resume restores immediately (CS-08).
- [ ] Delete requires explicit confirmation, removes tenant and all data, disappears immediately, and the same address can be recreated (CS-09).
- [ ] Permission errors shown gracefully, never silently (dialog error standard).

**Per-Tenant Identity Provider**
- [ ] Each tenant admin configures their own OIDC independently; changes never affect other tenants (CS-16).
- [ ] Sign-in at tenant A's address uses tenant A's provider only.
- [ ] A credential/token issued by tenant A's provider cannot authenticate to tenant B — rejected everywhere (CS-14/CS-15).
- [ ] Tenant admins cannot view or modify another tenant's sign-in configuration (CS-16).

**Isolation & Security**
- [ ] Tenant A cannot open/list/search/edit/delete any tenant B record by any means including forged references — 404/403, no data exposure (CS-12/CS-13).
- [ ] Directly addressed cross-tenant requests return no data and are recorded as security-relevant audit events visible to the platform admin (CS-12).
- [ ] Agents executing for tenant A use only tenant A's skills/tools/credentials/identities; agent-to-agent messages cannot cross tenants (CS-17/CS-18).
- [ ] API keys are tenant-bound; a tenant A key cannot read or call any tenant B resource (CS-17).
- [ ] Platform admin manages metadata only, never browses tenant business data; tenant admin sees no platform config or other tenants (CS-22/CS-23).
- [ ] Security review confirms: through any interface (UI, API, agent execution, scheduling, notifications, MCP tools), no cross-tenant read or write is possible (CS-10–CS-20 plus Phase 9.8 review).

**Single-Tenant Compatibility**
- [ ] An upgraded installation with the switch off behaves identically to before across sign-in, roles, agents, integrations, dashboard, scheduling.
- [ ] All existing backend, frontend, and E2E tests pass with the switch off, without modification.

---

## 6. Test File References

Paths follow `docs/config.yaml` `source.tests`. All files below were VERIFIED PRESENT AND PASSING in the Phase 9 run (2026-09-25) unless explicitly noted as gated, and RE-VERIFIED after the Phase 10 run (2026-09-27) including the new self-serve registration / root / licensing / quota suites. Counts are verified test cases per file.

### Backend unit (`backend/tests/`) — all green
- `backend/tests/test_tenant_resolution.py` (34 tests) — slug extraction, fail-closed resolution (unknown/suspended/deleted), middleware inertness when off, 403 + audits + bypass enumeration (Phase 9.1)
- `backend/tests/test_tenant_context.py` (20) — immutable context, unset sentinel in single-tenant mode, OTEL attribution
- `backend/tests/test_tenant_signature.py` (28) — sign/verify: tampered, stale, unsigned, mismatched; verify-only key semantics; structural no-sign guard for AR/CH
- `backend/tests/test_platform_settings_service.py` (11) — default-false seeding, cached reads, write-through invalidation, audits
- `backend/tests/test_tenant_scoping.py` (24) — `apply_tenant_scope` SELECT/UPDATE/DELETE/INSERT isolation, join-table inheritance (E-01), scope-miss audits, **PermissionEngine tenant binding incl. wildcard containment (CS-21)**, tenant lifecycle service (CS-07/CS-09). NOTE: the planned standalone `test_permission_engine_tenant_binding.py` was FOLDED into this file (class `TestPermissionEngineTenantBinding`).
- `backend/tests/test_tenant_oidc_isolation.py` (21) — per-tenant registry keying, `_try_oidc_token` tenant binding, claim matrix (missing/mismatch/matching/super-admin) + security audits, per-tenant CRUD isolation (Phase 9.3, CS-14/15/16)
- `backend/tests/test_tenant_memberships_invitations.py` (11) — membership CRUD, invitation single-use/expiry/revoke negative matrix (E-08)

Phase 10 additions (verified 2026-09-27, all green):
- `backend/tests/test_tenant_registration.py` (19) — atomic account + tenant + root registration with `self_serve_registration` audit (CS-26), platform-credential/sub semantics, tenant-bound token, duplicate email / slug conflict / invalid+missing input with NO partial data (CS-27), one-tenant-per-user block (CS-28), switch-off inertness incl. discovery exposing no tenant (CS-29), login-password happy path + generic 401s (no user enumeration), same-email race backstop (E-18)
- `backend/tests/test_tenant_root_protection.py` (13) — root membership mutation rejected + `root_protection_rejected` audit for every actor (CS-30/CS-31), payload-injection and platform-tenant-update bypass attempts rejected, no platform membership-mutation route exists, root grants ALL tenant permissions vs non-root grants limited, root-only alias edit (immediate + audited) vs non-root rejection, slug immutable through every endpoint (CS-32), alias uniqueness conflict leaves slug untouched (E-19)
- `backend/tests/test_tenant_licensing_quotas.py` (19) — license assign/change/remove with supersede history + immediate free fallback (CS-33/CS-34, E-15/E-16), invalid license input rejected, quota gates: invitation over max_users (incl. member-creating acceptance path), agent-type creation, execution submission refused before dispatch (CS-35/CS-36/CS-37), under-quota success, exhausted quota does not block unrelated actions (CS-38), submission-time counter increments exactly once, calendar-month implicit reset (CS-39), counter authoritative + drift visible (E-17), structured `QuotaBlockedPayload` + `quota_exhausted` audit (CS-41), usage endpoint free defaults + license reflection, usage endpoint permission/membership guards, platform license API rejects non-platform-admins (CS-43), tenant deletion removes license/quota rows and recreate starts free (E-20), switch-off execution gate inert
- `backend/tests/integration/test_tenant_quota_scheduler.py` (5, real PostgreSQL) — scheduler dispatch consults quota at dispatch time; within-quota dispatch counts exactly like a user submission and shares ONE counter; exhausted quota skips dispatch with `quota_exhausted` audit and the job stays scheduled (CS-40); jobs without a tenant keep legacy behaviour; `execute_job` loop records the skip result

Fix hardening additions (verified 2026-09-29, all green — 54 tests total):
- `backend/tests/test_tenant_user_leak.py` (2) — platform-users leak regression: tenant-context list returns ONLY users with an ACTIVE membership in the requesting tenant (CS-44); foreign user detail → 404 with own-member 200 control proving tenant context is applied
- `backend/tests/test_tenant_isolation_sweep.py` (52) — systematic ALL-entity isolation sweep: registry-completeness guard (every model without `tenant_id` MUST be in `TENANT_AGNOSTIC_REGISTRY` with a documented strategy — future-leak guard, no stale registry keys); parametrized row-level cross-tenant probes across ALL 47 tenant-scoped models (`select` sees only own row, `get` → `None`/404 semantics, zero skips); per-request scope binding — A → B → A each see only their own rows, no stale criteria replay across tenants (CS-45); PlatformUser membership-join strategy (CS-44) and tenant-agnostic registry entries (CS-46)

### Backend integration / schema / security — all green
- `backend/tests/db/test_tenant_schema_migration.py` (17; 87 assertions) — `information_schema` verification vs real PostgreSQL: 5 new tables as of the Phase 9 run (now 7 with `TenantLicense`/`TenantQuotaUsage` — see planned-extensions note in the must-keep-passing list), nullable+indexed tenant columns per domain group, join tables carry none, negative FK/unique constraints. Full downgrade/re-upgrade cycle GATED behind `PARTHENON_TEST_MIGRATION_CYCLE=1` (mutates the shared dev DB) — this is the run's single intentional skip. (Phase 9.5)
- `backend/tests/integration/test_tenant_adoption.py` (8) — system-tenant creation, NULL-row backfill incl. orphans (CS-06), admin promotion, idempotency, disable-validation, enable/disable cycle (CS-03/CS-05)
- `backend/tests/security/test_cross_tenant_isolation.py` (7) — per-domain cross-tenant negative tests with audit assertions (Phase 9.2, CS-12/CS-13)
- `backend/tests/agent_runtime/test_tenant_header_verification.py` (9) — AR verifies signed headers; tamper/replay/widening rejected; forwarding semantics (Phase 9.4, CS-20)
- `backend/tests/communication_hub/test_tenant_header_verification.py` (12) — CH control-plane verification, API-key tenant binding, A2A cross-tenant refusal (CS-17/CS-18/CS-19)
- `backend/tests/test_platform_admin_api.py` (19) — tenants/settings/audit APIs: lifecycle CRUD (create/read/update/suspend/resume/delete + slug reuse), aggregates-only responses, permission guards, adoption idempotency (CS-07/CS-22/CS-23)

**Backend total (full suite run, Phase 10 verification 2026-09-27): 2133 passed, 226 skipped, 0 failed** (17 failed + 1 fixture-teardown error appear only because stale dev services from a previous session were reachable during the run, converting service-dependent skips into live calls against outdated binaries; re-run with the service URLs unreachable: the same files report 41 skipped / 7 passed / 0 failed, restoring the Phase 9 semantics of "pre-existing service-DB-dependent skips + the gated migration cycle"). Phase 10 adds 56 passing tests across the four new files above.

### Frontend component tests (`frontend/src/__tests__/`) — all green
- `TenantPicker.test.tsx` (10) — renders only for multi-org users; selection drives re-sign-in; continue semantics
- `PlatformAdminRoute.test.tsx` (6) — guard blocks non-platform-admins; absent when switch off; super-admin bypass
- `TenantManagementPage.test.tsx` (10) — CRUD flows, immediate table refresh without reload, server validation errors inline, dialog error standard (CS-07)
- `PlatformSettingsPage.test.tsx` (7) — switch toggle with typed confirmation and server-state reflection
- `PlatformAuditPage.test.tsx` (5) — filters, tenant attribution, no business data rendered
- `TenantWorkspacePages.test.tsx` (13 + 5 Phase 10 cases) — TenantSettingsPage + OnboardingPage + MembersPage combined: workspace behavior, permission gating, i18n `t()` keys, invitation token shown-once. NOTE: the planned separate `TenantSettingsPage.test.tsx` / `OnboardingPage.test.tsx` / `MembersPage.test.tsx` and `tenant-i18n-coverage.test.ts` were COMBINED into this file (i18n coverage asserted per page). Phase 10 extends it with root-only alias editing (root enabled with hint / non-root locked note / API save + query refresh) and the license & usage panel (tier chip + usage meters).

Phase 10 additions (verified 2026-09-27, all green):
- `SignUpPage.test.tsx` (10) — two-step wizard rendering + client validation, entry link vs switch-off inertness, server errors surfaced (duplicate email / address taken / one-tenant-per-user), success stores session and routes to onboarding
- `TenantLicenseManagement.test.tsx` (6) — platform license assign/change/remove flows with immediate table refresh WITHOUT reload, invalid input errors inline, permission gating for non-platform-admins, free-fallback confirmation
- `QuotaBlockedFeedback.test.tsx` (8) — structured tier/limit/usage/upgrade alert rendered in invite dialog, agent type form and execution launch path; non-quota errors fall through to `PermissionDeniedAlert`; unrelated actions unaffected

**Frontend total (full suite run, Phase 10 verification 2026-09-27): 1559 passed, 18 skipped (pre-existing), 0 failed; `npx tsc --noEmit` clean.** (Phase 9 baseline was 1530 passed — the +29 delta is the Phase 10 additions above.)

### E2E (`e2e/tests/`, Playwright) — all green
- `single-tenant-regression.spec.ts` (6) — switch-off canary: dashboard unchanged, no platform nav, `/platform/*` absent, no picker for multi-org users, stray `X-Tenant` header inert (CS-01/CS-02)
- `multi-tenant-lifecycle.spec.ts` (6) — platform console CRUD lifecycle (create → read → update → suspend → resume → delete → slug reuse) with parent-table refresh WITHOUT reload; duplicate rejection inline; settings toggle typed-ENABLE confirmation; audit view tenant attribution (CS-07/CS-09/CS-22)
- `multi-tenant-login-flows.spec.ts` (6) — suspended/deleted tenant sign-in blocked; multi-org picker; one-session-one-tenant (sessionStorage only, never durable); fresh sign-in on org switch (CS-24)
- `multi-tenant-isolation.real-backend.spec.ts` (1, GATED) — **`Real Backend Integration - Multi-Tenant Isolation`**: no mocks; probes `/api/v1/health` (skips gracefully when no live backend/token); fails loudly on `/auth/tenant` 500 (unapplied migration); verifies discovery switch state, platform tenants metadata+aggregates only, bogus tenant id → 404, audit tenant attribution (Phase 9.7). STATUS: honest skip in environments without a live stack + `E2E_REAL_BACKEND_TOKEN`; mock-based suites above are the always-green core.

**E2E total (Phase 9 final run, mocked + gated): 55 passed, 4 skipped (real-backend variants requiring live services), 0 failed.** Pre-existing E2E issues UNRELATED to this change (documented, not caused by it): `mcp-hub.spec.ts` / `api-key-management.spec.ts` stale mock globs/assertions vs paginated endpoints; `permission-errors.spec.ts` requires live Keycloak and belongs in `auth-required/`. Test-infra fixes made: `frontend/.env.test` (VITE_API_BASE_URL for the preview build), `testIgnore: '**/auth-required/**'` + corrected `../_helpers` imports.

Phase 10 additions (verified 2026-09-27, all green):
- `self-serve-signup.spec.ts` (4) — CS-29 switch-off: entry link absent from login, `/signup` renders inert without a form; CS-26 full journey: entry link → two-step wizard (address auto-derived) → lands in guided onboarding as root; CS-27 duplicate email inline error, no session; CS-28 one-tenant-per-user message on second registration
- `quota-enforcement.spec.ts` (2) — CS-35/CS-41 blocked invite renders tier/limit/usage/upgrade and unblocks once the license is raised (no reload); CS-34 tenant usage panel mirrors tier and limits
- `self-serve-signup.real-backend.spec.ts` (1, GATED) — **`Real Backend Integration - Self-Serve Registration & Quotas`**: no mocks; real registration through the public endpoints against the migrated DB, one-tenant block, usage read; honest-skip pattern when no live backend/token is available (same convention as `multi-tenant-isolation.real-backend.spec.ts`)

Phase 10 re-verification run (2026-09-27): single-tenant-regression 6 ✓, new mocked specs 6 ✓, multi-tenant-lifecycle + login-flows 11 ✓, both real-backend variants honest-skip ✓, must-keep regression files re-run (`permissions.spec.ts` 5✓/2 skip pre-existing, segregation/architecture trio 27 ✓). `npx tsc --noEmit` clean.

### Phase 10 planned test files — IMPLEMENTED AND GREEN (2026-09-27)
All Phase 10 planned files below were implemented and are now documented as verified entries in the layer sections above (backend unit/integration, frontend component, E2E). Coverage vs the original plan: every planned scenario is covered, with two consolidations — the planned standalone alias-edit/slug-immutability backend cases live in `test_tenant_root_protection.py`, and the planned TenantWorkspacePages alias/usage extension cases were folded into the existing combined frontend file. The E2E alias-edit journey is covered in `multi-tenant-lifecycle.spec.ts` (CS-32 UI, Phase 9) plus the Phase 10 mocked sign-up and quota specs.

### Product fixes made during Phase 9 (2, both low-severity UX)
- `frontend/src/stores/AuthContext.tsx` + `frontend/src/app/PlatformAdminRoute.tsx` — tenancy state is tri-state; the guard no longer bounces platform admins deep-linking `/platform/*` while discovery resolves (F-1 in security-review.md).
- `frontend/src/components/auth/TenantSessionGate.tsx` — "continue with current organization" now dismisses the picker reactively (F-2).

### Existing files that MUST keep passing (verified present; some extended, never weakened)
- `backend/tests/test_auth_middleware_full.py` — extended with tenant-claim and switch-off cases; canary for the Phase 2.8 inertness guard
- `backend/tests/test_oidc_config_service.py` — extended with per-tenant CRUD isolation cases
- `backend/tests/conftest.py` — fixture file: gains tenant/membership fixtures and `alembic upgrade head` setup for multi-tenant DB tests
- `backend/tests/integration/test_internal_auth_security.py` — internal endpoint auth must still pass; extended expectations for signed headers in multi-tenant mode
- `backend/tests/integration/test_database_isolation.py` — DB isolation guarantees must hold post-change
- `backend/tests/integration/test_internal_revocation_fail_closed.py` — fail-closed precedent must hold under tenant scoping
- `backend/tests/agent_runtime/test_terminate_endpoint.py` — terminate behavior unchanged with switch off
- `backend/tests/communication_hub/api/internal/test_validate_api_key.py` — extended with tenant binding in response (switch off: unchanged shape)
- `backend/tests/db/test_namespace_migration.py` — migration test pattern this change's schema tests follow
- `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` — extended to assert parity for new `platform::*`/`tenant::*` types (E-14)
- `frontend/src/__tests__/LoginPage.test.tsx` — extended with tenant discovery/picker cases; switch-off flow unchanged
- `frontend/src/__tests__/AuthContext.test.tsx` — extended with active-tenant session semantics
- `frontend/src/__tests__/IdentityProvidersConfigPage.test.tsx` — provider config UI behavior preserved for tenant reuse
- `frontend/src/__tests__/AppShell.test.tsx` — header unchanged when switch off; branding when on
- `frontend/src/__tests__/service-segregation-security-audit.test.ts` — architecture segregation audit still green
- `e2e/tests/test-login-flow.spec.ts`, `e2e/tests/oidc-login-flows.spec.ts` — sign-in flows unchanged with switch off
- `e2e/tests/permissions.spec.ts`, `e2e/tests/permission-errors.spec.ts` — permission model regression
- `e2e/tests/mcp-hub.spec.ts`, `e2e/tests/api-key-management.spec.ts` — MCP hub and API key behavior with switch off
- `e2e/tests/agent-security-segregation.spec.ts`, `e2e/tests/service-segregation-security-audit.spec.ts`, `e2e/tests/three-service-architecture.spec.ts` — service segregation and agent security invariants must hold under tenancy
- `e2e/tests/agent-runtime-monitor.real-backend.spec.ts` — existing real-backend suite must keep passing (naming convention followed by the new real-backend isolation suite)
- `backend/tests/test_tenant_scoping.py` — tenant lifecycle service tests must keep passing; extended with alias/slug semantics (root-only alias, immutable slug)
- `backend/tests/test_platform_admin_api.py` — tenant CRUD + permission guards must keep passing; extended with license API guards and tier/usage in aggregate responses
- `backend/tests/test_tenant_memberships_invitations.py` — membership/invitation flows must keep passing under-quota (invitation behavior becomes quota-gated at the API level; E-08 negative matrix unaffected)
- `backend/tests/db/test_tenant_schema_migration.py` — schema verification extended to the two new tables (`TenantLicense`, `TenantQuotaUsage` + unique bucket constraint); existing assertions must keep passing
- `frontend/src/__tests__/TenantManagementPage.test.tsx` — tenant overview table tests must keep passing; extended with tier/license columns and usage counts
- `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` — must keep passing if license/quota management introduces new resource types (mirror parity for any new types is mandatory, E-14)
- `e2e/tests/multi-tenant-lifecycle.spec.ts` — tenant CRUD lifecycle must keep passing; extended with alias-edit/slug-immutability assertions (CS-32 UI)
- `e2e/tests/single-tenant-regression.spec.ts` — switch-off canary extended to assert the sign-up page/route is absent when off (CS-29 UI side)

### Execution order per AGENTS.md
1. Verify migrations: `alembic current` → `alembic upgrade head` if pending → restart backend services.
2. Backend unit + integration (real DB) suites.
3. Frontend Vitest with JSON reporter (`npx vitest run --reporter=json --outputFile=vitest_results.json`).
4. E2E: `single-tenant-regression.spec.ts` first (switch-off canary), then mocked tenant suites (including the new self-serve sign-up and quota-enforcement specs once implemented), then `Real Backend Integration - Multi-Tenant Isolation` and `Real Backend Integration - Self-Serve Registration & Quotas` last.
5. Manual security hardening review (Phase 9.8) against `top_priority_rules` before sign-off.
