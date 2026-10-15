# Test Plan: strict-tenant-isolation

## Test Strategy

- **Primary: backend integration tests** (`backend/tests/`) against a real PostgreSQL database with migrations applied (`alembic upgrade head` before run — required per `.change.yaml` `has_db_changes` and the CRITICAL database-changes rules). Integration tests must verify actual DB constraints (per-tenant slug uniqueness, NOT NULL `tenant_id`), include negative tests, and query `information_schema` where relevant.
- **Unit tests** for pure functions: tool-name parsing/resolution, signature build/verify, delegation-slug extraction.
- **Security tests** for header fail-closed behavior and cross-tenant probing (extend existing `backend/tests/security/` and `backend/tests/integration/test_internal_auth_security.py` patterns).
- **E2E (Playwright, `e2e/tests/`)**: **N/A — not delivered.** This is a backend-only change with no UI changes; tenant isolation is enforced server-side (signed internal headers, DB predicates, migrations), so no frontend component tests or Playwright specs were added. The backend integration suites double as regression coverage, including the real-Alembic-chain run in `backend/tests/db/test_tenant_adoption_migration.py` that catches unapplied-migration failures.
- **Multi-tenant fixtures**: a shared fixture creates two tenants (A and B) with their own users, MCP servers, tools, skills, data types, agent types, and recipient groups, mirroring the pattern in `backend/tests/security/test_cross_tenant_isolation.py` and `backend/tests/test_tenant_isolation_sweep.py`.
- **Dual-mode matrix**: each critical scenario is run twice — multi-tenancy enabled (strict per-tenant) and disabled (everything resolves to root tenant, behavior unchanged).

## Coverage Areas

1. **MCP hub per-tenancy** — `McpServer` slug uniqueness becomes `(tenant, slug)`; `McpTool` carries denormalized `tenant_id`; tool sync, skill bindings, and `ToolPermission` grants are tenant-bound. Critical because a global slug blocked same-named servers and grants could cross tenants.
2. **Tool-name resolution & A2A delegation containment** — `server____tool` and `agent____<slug>` wire formats are unchanged, but resolution is tenant-qualified. Critical: name collisions across tenants must never route a call or delegation to the wrong tenant's target.
3. **Fail-closed internal endpoints** — all `/api/v1/internal/*` data-plane routers require valid signed `X-Internal-Tenant-*` headers; missing/stale/invalid = 401 before any DB access. Critical: eliminates the verify-if-present fail-open path.
4. **System tools & data-plane records** — `query_result`, `save_data`, `get_data`, `get_output`, outputs and agent-data internal endpoints must stamp/filter strictly by the bound tenant. Critical: business-data leakage paths.
5. **Notification dispatch** — group resolution and dispatch scoped to the calling tenant; the global/shared NULL-tenant slot is retired. Critical: notifications must reach the tenant's own group.
6. **Adoption migration & shared-slot retirement** — NULL-tenant legacy rows (data types, seeded skills, scheduled jobs, shared recipient groups) adopted into root; `tenant_id` becomes NOT NULL; NULL-variant partial unique indexes dropped. Critical: strict exact-tenant matching depends on no NULL rows remaining.
7. **Scheduler & seeder** — jobs bound to tenant at creation and dispatch; `SkillSeeder` seeds into root tenant. Critical: a tenant A job must never execute with tenant B access.
8. **Agent Runtime virtual tenant awareness** — AR resolves the calling tenant once from the signed context and stamps it on every downstream internal call. Critical: agents must operate tenant-less never.
9. **Communication Hub** — per-tenant `tools/list` / `tools/call` for MCP clients; signed-context verification/forwarding on `/internal/a2a`.
10. **Regression** — single-tenancy-disabled root-default behavior; per-tenant entity name/slug uniqueness (migration `a7b9c1d3e5f7`); per-identity-tenant OAuth token refresh.

## Critical Scenarios (WHEN/THEN)

### 1. Two tenants with same MCP slug "supabase" — full isolation

- **WHEN** tenant A and tenant B each register an MCP server with slug `supabase`
  **THEN** both registrations succeed (per-tenant `(tenant, slug)` uniqueness); DB constraint allows same slug across tenants.
- **WHEN** each tenant's tools are synced
  **THEN** each `McpTool` row carries its own tenant's `tenant_id`; each tenant sees only its own `supabase` tool list.
- **WHEN** each tenant creates a skill referencing slug `supabase`
  **THEN** each skill binding resolves within the creating tenant only.
- **WHEN** an agent in tenant A invokes tool `supabase____query`
  **THEN** the invocation resolves to tenant A's server; tenant B's server/credentials are never touched; wire name is identical in both tenants.
- **WHEN** tenant A registers slug `supabase` and tries to register `supabase` again within tenant A
  **THEN** the second registration is rejected (duplicate within one tenant).

### 2. Tool-name resolution & A2A delegation tenant containment

- **WHEN** a tenant A agent lists or invokes a tool registered by tenant B (same wire name)
  **THEN** the lookup misses, the call fails closed, and a scope-miss audit is recorded.
- **WHEN** `parse_tool_name` parses `server____tool` / `agent____<slug>` names
  **THEN** the wire format and parse output are unchanged; the slug is matched against the calling tenant's registry at resolution time.
- **WHEN** tenant A delegates via `agent____helper` and tenant B also has an agent type named `helper`
  **THEN** `prepare_a2a_request` resolves strictly by `(tenant, name)` to tenant A's agent; a tenant-B agent named `helper` is never reachable from tenant A.
- **WHEN** a `ToolPermission` grant exists in tenant A for `supabase____query`
  **THEN** it authorizes tenant A's tool only; tenant B's same-named tool remains unauthorized for tenant A principals.

### 3. Internal endpoints reject headerless requests (fail-closed)

- **WHEN** a request hits any `/api/v1/internal/*` data-plane router (system_tools, session_data, outputs, agent_data, mcp_proxy, authorization) without `X-Internal-Tenant-*` headers
  **THEN** it returns 401 before any handler or DB access.
- **WHEN** the headers are present but the signature is invalid, the timestamp is stale, or the tenant id/slug do not match the signature
  **THEN** the request returns 401.
- **WHEN** valid signed headers are present
  **THEN** the request succeeds and the bound tenant is used for all scoping.
- **WHEN** an agent-instance certificate calls an internal endpoint
  **THEN** existing certificate-based access control is preserved (non-data-plane internal routers keep certificate-only auth).
- **WHEN** multi-tenancy is disabled and internal calls arrive without headers
  **THEN** they bind the root tenant instead of 401ing (single-tenant behavior preserved).

### 4. Cross-tenant negative tests — query_result / save_data / get_data / outputs

- **WHEN** a data type with the same slug/name exists in tenant A and tenant B, and a tenant A agent calls `query_result`
  **THEN** the data type resolves within tenant A only, and the result set contains only tenant A outputs.
- **WHEN** tenant A saves a record via `save_data` and tenant B calls `get_data` with identical `data_name`, `agent_type_id`, or `session_id` filters
  **THEN** tenant B retrieves nothing; the tenant A record is never returned.
- **WHEN** `save_data` writes a record during a tenant B run
  **THEN** the record is stamped with tenant B's `tenant_id` explicitly (verified in DB, not just via API).
- **WHEN** tenant A creates an internal output and tenant B queries the outputs internal endpoint
  **THEN** tenant B's query returns only tenant B records; the tenant A output is invisible.
- **WHEN** a direct service-level query (`AgentDataService`, `OutputService`) runs without a matching tenant predicate
  **THEN** explicit tenant predicates still contain results (defense in depth independent of session scoping).

### 5. Notification dispatch per tenant

- **WHEN** tenant A and tenant B each define a recipient group and their agents dispatch a notification
  **THEN** `get-recipient-group` resolves only the calling tenant's group and the message goes to that group's channels only.
- **WHEN** a legacy NULL-tenant shared group exists before migration
  **THEN** the adoption migration moves it into the root tenant; after migration no data-plane dispatch ever targets a shared/global slot.
- **WHEN** tenant A requests a group name that exists only in tenant B
  **THEN** resolution misses and dispatch fails closed (no fallback to another tenant's group).

### 6. Adoption migration (NULL → root) and shared-slot retirement

- **WHEN** the migration runs against a database containing NULL-tenant data types, seeded skills, scheduled jobs, and recipient groups
  **THEN** all such rows are adopted into the root tenant; `information_schema` shows `tenant_id` is NOT NULL on all data-plane tables; NULL-variant partial unique indexes are dropped.
- **WHEN** the migration runs a second time (and after downgrade → re-upgrade)
  **THEN** it is idempotent — a no-op on re-run; downgrade restores NULLs so the upgrade can be replayed.
- **WHEN** any lookup (data types, skills, jobs) executes after migration
  **THEN** it matches the exact session tenant only — no `tenant_id IS NULL OR tenant_id = own` fallback remains; a tenant user cannot see or reference root-tenant or other tenants' data types, skills, or jobs.
- **WHEN** multi-tenancy is disabled
  **THEN** all contexts (request, internal, scheduler, seeder) resolve to the root tenant and behavior matches the single-tenant deployment byte-for-byte.

### 7. Scheduler & AR virtual tenant awareness

- **WHEN** a scheduled job is created in tenant A and dispatched
  **THEN** it executes under tenant A's context; it cannot read tenant B resources during the run.
- **WHEN** an execution request reaches Agent Runtime
  **THEN** the AR middleware verifies the signed tenant binding fail-closed (missing/invalid = rejected); the run resolves the tenant once and stamps signed headers on every downstream internal call (verified via forwarded-header capture).
- **WHEN** a tenant A agent runs with MCP tools and A2A targets
  **THEN** all resolution during the run (`runtime_executor`, `langchain_tool_wrapper`) is tenant-filtered against the run's tenant.
- **WHEN** the CH MCP protocol server serves `tools/list` / `tools/call` to an API-key-authenticated client
  **THEN** the listing and call resolution use the client's tenant only.

### 8. DB constraint verification (CRITICAL database-changes rules)

- **WHEN** `information_schema` / pg catalog is queried after migrations
  **THEN** `mcp_servers.slug` uniqueness is a composite per-tenant constraint (no platform-wide unique on slug alone); `mcp_tools.tenant_id` exists and is NOT NULL; data-plane tables have NOT NULL `tenant_id`.
- **WHEN** a duplicate `(tenant, slug)` MCP server insert is attempted directly at the DB level
  **THEN** the constraint rejects it.
- **WHEN** two different tenants insert the same slug directly at the DB level
  **THEN** both succeed.
- **WHEN** an insert with NULL `tenant_id` is attempted on any tightened data-plane table
  **THEN** the NOT NULL constraint rejects it (negative test against the removed NULL-variant index).

### 9. Regression

- **WHEN** per-tenant entity name/slug uniqueness (migration `a7b9c1d3e5f7`) is exercised
  **THEN** behavior is unchanged.
- **WHEN** per-identity-tenant OAuth token refresh runs
  **THEN** each identity refreshes within its own tenant, unchanged.
- **WHEN** existing grants/skill bindings reference old global tool names after adoption
  **THEN** they keep working via resolution-time tenant matching (root-adopted rows).

## Edge Cases & Risks

- **Migration ordering risk**: strict `IS NULL`-free matching going live before the adoption migration would break lookups on un-adopted rows — tests must verify the deployment-order assumption (migrations → restart CC → restart AR/CH); E2E real-backend run catches unapplied migrations.
- **Downgrade/re-upgrade cycles**: adoption downgrade restores NULLs; tests must cover replay to guarantee idempotency.
- **Same wire names everywhere**: identical `server____tool` / `agent____<slug>` names across tenants maximize collision surface; tests must use identical names, not just different ones.
- **Root-tenant vs platform access**: root/platform users may see all data as platform operations — tests must not treat root visibility as a leak; tenant users must never see root rows.
- **Stale timestamps / clock skew** on signed headers — verify stale-timestamp rejection window behavior is testable and consistent between CC, AR, and CH.
- **`execute_unscoped` creep**: identity-plane exemption must remain limited to PlatformUser / identity-by-sub lookups; a regression letting it reach the data plane would silently defeat isolation — include a guard test.
- **Forwarding contextvar leakage**: `bind_forwarded_tenant_headers` is per-execution — verify no context bleed between concurrent runs (async tasks on the same event loop).
- **Reserved namespaces**: `system` / `decision` reserved server names must still resolve correctly per tenant.
- **Seeder/bootstrap under multi-tenancy off**: `SkillSeeder` must seed into root and not create duplicate rows when the switch is toggled off → on → off (interaction with `TenantAdoptionService` idempotent adoption).
- **Quota/licensing interplay**: tenant-scoped enforcement must not alter quota mechanics (out of scope) — light regression only.

## Acceptance Criteria Checklist

| # | PRD Acceptance Criterion | Covered By |
|---|--------------------------|------------|
| 1 | Same slug "supabase" in two tenants; skills and agents resolve own tenant's server | Scenarios 1, 8 |
| 2 | Tool names, parsing, and A2A names tenant-scoped; no cross-tenant list/invoke/delegation | Scenario 2 |
| 3 | Permission grants enforced within granting tenant only | Scenario 2 (grant containment) |
| 4 | Internal endpoints fail closed without signed tenant headers; no cross-tenant data-plane path | Scenario 3 |
| 5 | `query_result` resolves data type and outputs within calling tenant only | Scenario 4 |
| 6 | `save_data`/`get_data` tenant-stamped writes and strict tenant-filtered reads | Scenario 4 |
| 7 | Internal outputs and agent-data listing endpoints return only bound tenant records | Scenario 4 |
| 8 | A2A resolves strictly by (tenant, name); collisions never misroute | Scenario 2 |
| 9 | `get-recipient-group` returns only bound-tenant groups | Scenario 5 |
| 10 | Notification dispatch per tenant; shared slot retired from data plane | Scenario 5 |
| 11 | NULL-tenant shared slot retired: legacy rows adopted to root; exact tenant matching only | Scenarios 6, 8 |
| 12 | Scheduler dispatch under owning tenant's context | Scenario 7 |
| 13 | Multi-tenancy disabled → identical root-default behavior everywhere | Scenarios 3, 6 (dual-mode matrix) |
| 14 | Per-tenant entity name/slug uniqueness and per-identity-tenant token refresh regression | Scenario 9 |

## Test File References

Existing files to extend (real paths under `backend/tests/`):

- `backend/tests/test_tenant_isolation_sweep.py` — broad isolation sweep; add MCP/system-tool/notification cases
- `backend/tests/security/test_cross_tenant_isolation.py` — two-tenant fixture pattern; add data-plane negative tests
- `backend/tests/test_tenant_scoping.py` — session-level scoping choke point; add fail-closed internal-traffic cases
- `backend/tests/test_tenant_signature.py` — signed header build/verify; add stale/invalid/mismatched-signature cases
- `backend/tests/test_tenant_context.py` — root-tenant resolution for switch-off binding
- `backend/tests/test_tenant_adoption.py` — extend for new adoption migration idempotency + downgrade/replay
- `backend/tests/test_query_result_tool.py` — add two-tenant same-slug data-type negative tests
- `backend/tests/integration/test_system_tool_endpoints.py` — save_data/get_data/get_output/get-recipient-group tenant stamping/filtering
- `backend/tests/integration/test_internal_auth_security.py` and `backend/tests/integration/test_internal_allowlist_partitioning.py` — headerless 401 fail-closed across all data-plane routers
- `backend/tests/integration/test_mcp_hub.py` and `backend/tests/integration/test_mcp_protocol_server.py` — per-tenant slug registration, tools/list / tools/call tenant filtering
- `backend/tests/services/test_tool_sync.py` — tenant-bound tool sync upserts
- `backend/tests/integration/test_tool_naming_refactor.py` — `build_tool_name`/`parse_tool_name` wire-format unchanged, tenant-qualified resolution
- `backend/tests/integration/test_tenant_quota_scheduler.py` and `backend/tests/test_scheduling.py` — tenant-bound job creation/dispatch
- `backend/tests/integration/test_notification_api.py` — per-tenant group resolution and dispatch
- `backend/tests/integration/test_decision_tool_data_types.py` — exact tenant data-type matching (no `IS NULL OR own`)
- `backend/tests/agent_runtime/test_tenant_header_verification.py` — AR fail-closed middleware + per-run forwarding
- `backend/tests/communication_hub/test_tenant_header_verification.py` — CH verification/forwarding on `/internal/a2a`
- `backend/tests/db/test_tenant_schema_migration.py` — extend with `information_schema` NOT NULL / unique-constraint verification and negative inserts
- `e2e/tests/` tenant-isolation specs — **N/A (not delivered)**: backend-only change, no UI changes; real-backend coverage provided by `backend/tests/db/test_tenant_adoption_migration.py` instead

New files to create (implemented):

- `backend/tests/integration/_strict_tenant_utils.py` — shared parthenon_test schema/fixture helpers (two-tenant builder, agent type/job builders, NULL-row counters)
- `backend/tests/integration/test_mcp_hub_tenant_slug_isolation.py` — Scenario 1 + 8: same-slug two-tenant registration, per-tenant slug DB constraint (positive/negative inserts), tenant-stamped tool sync, same-tenant skill bindings, invocation resolution via scoped session, ToolPermission grant containment ✅ (8 tests passing)
- `backend/tests/integration/test_internal_tenant_header_failclosed.py` — Scenario 3: 401 on missing/invalid/stale/tampered/partial/mismatched signed headers; root binding when multi-tenancy off; structural check that every internal data-plane router enforces `require_internal_tenant_context` ✅ (14 tests passing)
- `backend/tests/integration/test_system_tools_tenant_containment.py` — Scenario 4: query_result/save_data/get_data/get_output/outputs cross-tenant negatives with identical names, DB-level tenant stamping, service-level defense in depth; plus decision-tool strict (tenant, name) matching ✅ (9 tests passing)
- `backend/tests/integration/test_notification_tenant_dispatch.py` — Scenario 5: per-tenant group resolution/dispatch, shared-slot retirement, fail-closed group miss, inactive-group rejection, contextless dispatch → root (not shared) ✅ (7 tests passing)
- `backend/tests/db/test_tenant_adoption_migration.py` — Scenario 6 + 8: runs the REAL Alembic chain from scratch on parthenon_test; `information_schema` NOT NULL verification on all tightened tables, retired NULL-variant index checks, DB-level negative inserts (NULL tenant, duplicate `(tenant, slug)`, cross-tenant same slug), upgrade-twice idempotency, downgrade→replay ✅ (25 tests passing). NOTE: required guarding pre-existing duplicate `oauth_*` column adds in migration `232324b61ea4` (chain could not replay from an empty DB otherwise).
- `backend/tests/integration/test_a2a_tenant_delegation.py` — Scenario 2: `agent____<slug>` (tenant, name) resolution, cross-tenant name collisions, delegated-job tenant stamping, fail-closed 404 miss ✅ (4 tests passing). Found and fixed: `SessionService.enqueue` did not stamp `tenant_id` on delegated jobs — now accepts and sets it (passed from `prepare_a2a_request`).
- `backend/tests/agent_runtime/test_ar_virtual_tenant_run.py` — Scenario 7: forwarded-header binding, no contextvar bleed between concurrent runs, AR `CommHubToolClient.call_tool` stamps forwarded `X-Internal-Tenant-*` verbatim, scheduler NULL-tenant hard skip / owning-tenant dispatch / missing-tenant-row skip ✅ (6 tests passing)
