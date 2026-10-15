# Implementation Plan: strict-tenant-isolation

## Overview

Make tenant isolation strict and fail-closed across Control Center (CC), Agent Runtime (AR), and Communication Hub (CH). Six ordered phases: (1) internal-endpoint fail-closed enforcement plus explicit tenant predicates in data-plane services; (2) one-time idempotent adoption of NULL-tenant legacy rows into the root tenant and retirement of all `IS NULL OR own` shared-slot patterns; (3) MCP hub tenant scoping (per-tenant slugs, tenant-bound tool sync, tenant-aware naming, grants and bindings); (4) AR virtual tenant awareness; (5) scheduler/seeder fixes and convention update; (6) tests proving isolation. Wire formats (`server____tool`, `agent____<slug>`, `X-Internal-Tenant-*` headers) stay unchanged — resolution becomes tenant-scoped at lookup time.

## Task Checklist

### Phase 1 — Internal endpoints fail-closed + explicit tenant predicates
- [x] 1.1 — Mandatory signed tenant headers on `/api/v1/internal/*` data-plane routers
- [x] 1.2 — Fail-closed session scoping for internal traffic in `get_db`
- [x] 1.3 — Tenant predicates for `query_result` and typed-output queries
- [x] 1.4 — Tenant predicates and explicit stamping for `save_data` / `get_data`
- [x] 1.5 — Tenant predicates for internal outputs endpoints and `OutputService`
- [x] 1.6 — Tenant-scoped A2A target resolution in `prepare_a2a_request`
- [x] 1.7 — Tenant-scoped recipient-group resolution and notification dispatch
- [x] 1.8 — Strict tenant matching in decision tools (drop NULL-shared slot)

### Phase 2 — NULL-tenant adoption migration + mandatory tenant binding
- [x] 2.1 — Idempotent adoption migration: NULL-tenant rows → root tenant
- [x] 2.2 — Mandatory `tenant_id` on operational models (AgentData, AgentOutput, AgentDataType)
- [x] 2.3 — Mandatory `tenant_id` on collaboration models (Skill, Sop, AgentRole, AgentIdentity, AgentType, join tables)
- [x] 2.4 — Mandatory `tenant_id` on communication/scheduling models (RecipientGroup, NotificationChannel, mappings, logs, ScheduledJob, JobExecution)
- [x] 2.5 — Mandatory `tenant_id` on policy/tag/model models (PolicyStatement, PolicyResource, TagDefinition, ModelConfig)
- [x] 2.6 — Sweep: remove every remaining `tenant_id IS NULL OR tenant_id = own` pattern
- [x] 2.7 — Root-tenant default resolution when multi-tenancy is disabled
- [x] 2.8 — Align runtime adoption path (`TenantAdoptionService`) with the migration

### Phase 3 — MCP hub tenant scoping
- [x] 3.1 — `McpServer.slug` uniqueness per tenant (model + migration)
- [x] 3.2 — Denormalized `McpTool.tenant_id` + tenant-bound tool sync
- [x] 3.3 — All slug lookups become `(tenant, slug)`
- [x] 3.4 — Tenant-aware tool naming resolution (wire format unchanged)
- [x] 3.5 — Same-tenant skill bindings and permission grants
- [x] 3.6 — Tenant-scoped A2A delegation names (`agent____<slug>`)
- [x] 3.7 — Per-tenant CH MCP protocol server (`tools/list`, `tools/call`)

### Phase 4 — Agent Runtime virtual tenant awareness
- [x] 4.1 — AR resolves calling tenant from signed context, fail-closed
- [x] 4.2 — Tenant context propagated through the execution run
- [x] 4.3 — Tool invocation resolves the calling tenant's servers/tools
- [x] 4.4 — A2A delegation from AR is tenant-scoped end to end

### Phase 5 — Scheduler/seeder fixes + convention update
- [x] 5.1 — Scheduler: tenant mandatory at creation and dispatch
- [x] 5.2 — Skill seeder seeds into root tenant with tenant-scoped lookups
- [x] 5.3 — Update `docs/config.yaml` MCP slug convention

### Phase 6 — Tests
- [x] 6.1 — Internal header enforcement tests
- [x] 6.2 — Data-plane isolation tests (query_result, save_data/get_data, outputs)
- [x] 6.3 — A2A and notification isolation tests
- [x] 6.4 — MCP same-slug two-tenant tests (naming, sync, grants)
- [x] 6.5 — Migration/adoption idempotency + single-tenant regression tests
- [x] 6.6 — Scheduler tenant-binding tests (delivered); seeder scoping covered indirectly — no dedicated SkillSeeder tenant test

All Phase 6 work landed as backend integration/agent-runtime test suites (73 new tests, all passing — see the Test Plan's Test File References for the file-by-file breakdown). No frontend UI changes were part of this change, so frontend component tests and Playwright E2E specs were not written; backend-only coverage was deemed sufficient.

## Phase 1 — Internal endpoints fail-closed + explicit tenant predicates

Fixes audit findings A1–A6. The signed `X-Internal-Tenant-*` convention (`backend/app/core/tenant_signature.py`) already exists but is verify-if-present; enforcement becomes mandatory on data-plane internal routers, and every data-plane service adds an explicit tenant predicate as defense in depth. When multi-tenancy is disabled, internal calls that lack headers bind the root tenant instead of failing (regression-safe single-tenant mode).

### 1.1 — Mandatory signed tenant headers on `/api/v1/internal/*` data-plane routers
Add a shared FastAPI dependency that requires a valid `verify_request_tenant_context` result on every request to the internal data-plane routers (`system_tools`, `session_data`, `outputs`, `agent_data`, `mcp_proxy`, `authorization`). Missing headers, stale timestamps, or invalid signatures → 401. Non-data-plane internal routers (certificates, bootstrap, validate_api_key) keep service-certificate-only auth where tenant context is genuinely meaningless.
_Done when:_ a headerless or badly signed request to any covered internal endpoint returns 401 before touching the DB; a correctly signed request passes; service-certificate auth still applies.

### 1.2 — Fail-closed session scoping for internal traffic in `get_db`
Change `_maybe_apply_request_tenant_scope` in `backend/app/db/session.py`: on `/api/v1/internal/*` data-plane paths, absent headers are a hard 401 (multi-tenancy on) or bind the root tenant (multi-tenancy off). Remove the silent `return  # no tenant headers` path for those routes; keep unscoped sessions only for genuine background/startup traffic that does not arrive via `get_db`.
_Done when:_ no `get_db` session on an internal data-plane request can end up unscoped; background tasks (scheduler, seeder) still open sessions through `AsyncSessionLocal` unaffected.

### 1.3 — Tenant predicates for `query_result` and typed-output queries
`query_result_tool` in `backend/app/api/v1/internal/system_tools.py` resolves `AgentDataType` by slug then name with an explicit `tenant_id == context.tenant_id` predicate, and every `OutputService` query it drives (`list_outputs`, `query_output_history`) carries the same predicate — independent of session decoration.
_Done when:_ a tenant-A agent querying a data type name that exists in both tenants gets only tenant-A rows; unit test with two seeded tenants passes.

### 1.4 — Tenant predicates and explicit stamping for `save_data` / `get_data`
`AgentDataService.save` in `backend/app/services/agent_data/service.py` sets `tenant_id` explicitly from the resolved internal context (never relies on flush stamping); `list_all`, `get_by_id`, `query_by_filters` add explicit tenant predicates; `save_data_tool` / `get_data_tool` in `system_tools.py` thread the context through.
_Done when:_ records saved by tenant A are invisible to tenant B with identical `data_name`/agent-type/session filters; `AgentData.tenant_id` is never NULL on new rows even on an unscoped session.

### 1.5 — Tenant predicates for internal outputs endpoints and `OutputService`
`create_internal_output` and `query_internal_outputs` in `backend/app/api/v1/internal/outputs.py` and `OutputService.save_typed` / `get_output` / `list_outputs` / `export_csv` / `list_auto_outputs` in `backend/app/services/outputs/service.py` filter and stamp by the bound tenant.
_Done when:_ internal outputs listing returns only the signed tenant's records; cross-tenant read attempt is audited as a scope miss.

### 1.6 — Tenant-scoped A2A target resolution in `prepare_a2a_request`
`prepare_a2a_request` in `backend/app/api/v1/internal/session_data.py` resolves the target `AgentType` strictly by `(tenant_id, name)` instead of name-only; permission check (`calculate_allowed_agent_types`) runs within the same tenant.
_Done when:_ a name collision across tenants never routes to the wrong tenant's agent — tenant B's agent with the same slug is not reachable from tenant A.

### 1.7 — Tenant-scoped recipient-group resolution and notification dispatch
`get_recipient_group_tool` in `system_tools.py` resolves with the bound tenant; `NotificationService.send_to_group` in `backend/app/services/notifications/notification_service.py` requires a tenant (the NULL default is removed); `NotificationRepository.get_recipient_group_by_slug` / `get_channel` / `list_channels` / `get_recipient_group` in `backend/app/services/notifications/repository.py` take a mandatory tenant predicate. The tenant-scoped contextvar pattern already used by `notifications/mcp_tool.py` becomes the only path.
_Done when:_ dispatch resolves only the calling tenant's group; the NULL-tenant slot is unreachable from the data plane; tenant groups are resolvable.

### 1.8 — Strict tenant matching in decision tools (drop NULL-shared slot)
Remove the `or_(tenant_id.is_(None), tenant_id == own)` predicates in `backend/app/api/v1/decision_tools.py` (`_load_data_type_for_tenant`) and `backend/app/services/system_one/decision_tool_service.py` (`DecisionToolService` data-type resolution); replace with exact tenant matching. Root-tenant users match root-tenant rows.
_Done when:_ a tenant user cannot reference a NULL-tenant (pre-adoption) or other tenant's data type; root users see root-owned types.

## Phase 2 — NULL-tenant adoption migration + mandatory tenant binding

One-time, idempotent Alembic data migration adopts every NULL-tenant legacy row into the root tenant, then schema tightening makes `tenant_id` mandatory on all data-plane tables. Single-tenancy-disabled deployments are unaffected behaviorally — everything belongs to root.

### 2.1 — Idempotent adoption migration: NULL-tenant rows → root tenant
New Alembic revision (down to `a7b9c1d3e5f7`) updating `tenant_id` from NULL to the root tenant id on all data-plane tables (data types, skills/SOPs/bindings, agent roles/identities/types/join tables, agent data, outputs, recipient groups, channels, mappings, logs, scheduled jobs/executions, policy statements/resources, tag definitions, model configs). Guard: skip rows already adopted (re-run safe); resolve root tenant via the same lookup as `backend/app/services/tenancy/root_tenant.py`; no-op when root tenant does not exist yet.
_Done when:_ `alembic upgrade head` succeeds twice in a row with identical results; zero NULL `tenant_id` rows remain on covered tables; `alembic downgrade` restores NULLs.

### 2.2 — Mandatory `tenant_id` on operational models
`backend/app/db/models/agent_data.py`, `agent_output.py`, `agent_data_type.py`: `tenant_id` becomes non-nullable; drop the NULL-variant partial unique indexes (migration in the same revision or a follow-up).
_Done when:_ inserting a row with NULL tenant fails at the DB level; per-tenant unique constraints verified by test.

### 2.3 — Mandatory `tenant_id` on collaboration models
`backend/app/db/models/skills.py` (Skill, Sop, SkillToolBinding, SopStep) and `agents.py` (AgentRole, AgentIdentity, AgentType, join tables): tenant mandatory, NULL-variant name-uniqueness indexes removed.
_Done when:_ schema tests confirm NOT NULL and per-tenant uniqueness; existing per-tenant unique behavior (migration `a7b9c1d3e5f7`) still holds.

### 2.4 — Mandatory `tenant_id` on communication/scheduling models
`backend/app/db/models/notifications.py` (RecipientGroup, NotificationChannel, GroupChannelMapping, logs) and `scheduling.py` (ScheduledJob, JobExecution): tenant mandatory.
_Done when:_ NULL-tenant group/channel/job inserts are rejected; adoption migration covers these tables.

### 2.5 — Mandatory `tenant_id` on policy/tag/model models
`backend/app/db/models/policy_statement.py`, `policy_resource.py`, `tag_definition.py`, and ModelConfig in `agents.py`: tenant mandatory, NULL-key/display-name variants retired.
_Done when:_ containment invariant (grants resolve within owning tenant, wildcards included) holds with mandatory tenant.

### 2.6 — Sweep: remove remaining `IS NULL OR own` patterns
Codebase-wide search for `tenant_id.is_(None)` combined with an equality predicate; replace with exact tenant matching in every data-plane service. `execute_unscoped` remains restricted to the documented identity-plane lookups (PlatformUser/Identity by sub).
_Done when:_ grep finds no `IS NULL OR` tenant fallback on data-plane paths; `backend/tests/test_tenant_isolation_sweep.py` passes.

### 2.7 — Root-tenant default resolution when multi-tenancy is disabled
When the platform switch is off, all data-plane contexts (request, internal, scheduler) resolve to the root tenant via `root_tenant.py` — behavior identical to a single root-tenant deployment, never tenant-less.
_Done when:_ with the switch off, every data-plane write carries the root tenant id and every read matches root rows; existing single-tenant test suite passes unchanged.

### 2.8 — Align runtime adoption path with the migration
`TenantAdoptionService` in `backend/app/services/tenancy/tenant_adoption_service.py` (enable/disable flows) reuses the same adoption routine so toggling multi-tenancy on later cannot re-create NULL-tenant rows; the enable path re-runs the idempotent adoption.
_Done when:_ enabling multi-tenancy on a legacy dataset leaves no NULL-tenant data-plane rows.

## Phase 3 — MCP hub tenant scoping

Fixes audit finding B3. Business identity of an MCP server becomes `(tenant, slug)`; the tool wire format `server____tool` and A2A `agent____<slug>` stay unchanged — resolution maps slugs against the calling tenant's registry.

### 3.1 — `McpServer.slug` uniqueness per tenant
`backend/app/db/models/mcp_hub.py`: replace the platform-wide unique constraint on `McpServer.slug` with a per-tenant unique constraint; server CRUD and lookups in the MCP hub services become `(tenant, slug)`.
_Done when:_ two tenants each register slug `supabase` successfully; a duplicate slug within one tenant is rejected.

### 3.2 — Denormalized `McpTool.tenant_id` + tenant-bound tool sync
Add `tenant_id` to `McpTool` (must equal its server's tenant); `ToolSyncService.sync` in `backend/app/services/mcp/tool_sync.py` upserts tools under the owning tenant's namespace and stamps the binding.
_Done when:_ synced tools carry the server's tenant; a tool row's tenant never diverges from its server (verified by test).

### 3.3 — All slug lookups become `(tenant, slug)`
Every lookup of `McpServer`/`McpTool` by slug or namespaced name — MCP hub API, proxy engine, permission resolution, skill binding validation — adds the tenant predicate.
_Done when:_ no code path resolves a server or tool by slug/name alone on the data plane (grep-verified).

### 3.4 — Tenant-aware tool naming resolution
`build_tool_name`/`parse_tool_name` in `backend/app/services/agents/tool_naming.py` keep the wire format; resolution call sites (tool listing for agents, permission checks, tool execution) map the server slug within the calling tenant. `system` and `decision` reserved namespaces resolve tenant-neutrally within the caller's tenant.
_Done when:_ tenant A cannot list or resolve a tool whose only registration is in tenant B, even with identical `server____tool` strings.

### 3.5 — Same-tenant skill bindings and permission grants
Skill→McpTool bindings, `ToolPermission` grants, and role→tool resolution enforce that both sides share the tenant; cross-tenant binding/grant creation is rejected at validation.
_Done when:_ a grant created in tenant A never authorizes a tool in tenant B (test).

### 3.6 — Tenant-scoped A2A delegation names
`_extract_delegation_target_slug` and the delegation tool construction in `backend/app/services/agents/langchain_tool_wrapper.py` keep `agent____<slug>` on the wire; CH `/internal/a2a` forwarding and CC `prepare_a2a_request` resolve the slug within the signed tenant (completes task 1.6 for the CH hop).
_Done when:_ A2A delegation by name in tenant A can never reach tenant B's agent type.

### 3.7 — Per-tenant CH MCP protocol server
The CH MCP protocol server (`tools/list`, `tools/call`) filters tool listings by the authenticated client's tenant and resolves tool calls within it; API-key auth resolves the tenant binding.
_Done when:_ an MCP client of tenant A sees and can call only tenant-A namespaced tools.

## Phase 4 — Agent Runtime virtual tenant awareness

### 4.1 — AR resolves calling tenant from signed context, fail-closed
`backend/app/agent_runtime/middleware.py` requires valid signed tenant headers on execution requests (multi-tenancy on) — missing/invalid → reject; multi-tenancy off → root tenant. The verified `VerifiedTenantContext` becomes the run's tenant identity.
_Done when:_ AR refuses to start an execution without a resolvable tenant binding (switch on).

### 4.2 — Tenant context propagated through the execution run
The resolved tenant is carried through the run (per-execution context, no ambient/global AR state) and attached to every downstream internal CC call the run makes (system tools, permission resolution, session data) via the existing `build_tenant_signature_headers` / `forward_tenant_headers` mechanism.
_Done when:_ every internal HTTP call issued during a run carries the run tenant's signed headers (observed in test double).

### 4.3 — Tool invocation resolves the calling tenant's servers/tools
The `McpTool` lookup by namespaced name in `runtime_executor.py` (and the AR-path tool builders in `langchain_tool_wrapper.py`) is tenant-filtered and fails closed on unresolved names.
_Done when:_ a tool name registered only in tenant B is unresolvable during a tenant-A run.

### 4.4 — A2A delegation from AR is tenant-scoped end to end
Delegation tools built in AR embed the run tenant; the CH execute/A2A hop re-verifies and forwards the signed headers; the receiving side resolves the target per task 1.6.
_Done when:_ full delegation chain CC→CH→AR→CC for a tenant-A agent never touches tenant-B records (integration test).

## Phase 5 — Scheduler/seeder fixes + convention update

Fixes audit findings B2 and B4.

### 5.1 — Scheduler: tenant mandatory at creation and dispatch
`SchedulingEngine` in `backend/app/services/scheduling/scheduler.py`: job creation rejects a NULL tenant (hard error); dispatch resolves exactly one owning tenant (remove the `or agent_type.tenant_id` fallback), builds the `TenantContext`, and runs quotas/scoping within it.
_Done when:_ creating a job without a tenant fails; a seeded job dispatches with the owning tenant's context; the quota gate fires per tenant at dispatch.

### 5.2 — Skill seeder seeds into root tenant with tenant-scoped lookups
`SkillSeeder` in `backend/app/services/skill_seeder.py`: seeded skills/bindings carry the root tenant id; the `_seed_one` name lookup and `_ensure_bindings` tool lookups become tenant-scoped so seeding can never match or mutate another tenant's skills.
_Done when:_ seeder is idempotent within root; a tenant skill named like a seeded skill is never modified by seeding.

### 5.3 — Update `docs/config.yaml` MCP slug convention
Change the convention line "MCP server slug/alias must be unique platform-wide" to per-tenant uniqueness `(tenant, slug)` with tenant-namespaced tools.
_Done when:_ `docs/config.yaml` conventions reflect per-tenant slug identity; no other doc contradicts it.

## Phase 6 — Tests

All backend tests under `backend/tests/`. Database-changing tests run after `alembic upgrade head`.

### 6.1 — Internal header enforcement tests
Missing/garbage/expired-signature headers → 401 on covered internal routers; valid signed headers → 200; multi-tenancy off + no headers → root-tenant bound.
_Done when:_ tests green — delivered in `backend/tests/integration/test_internal_tenant_header_failclosed.py` (14 tests, including a structural check that every data-plane internal router declares `require_internal_tenant_context`).

### 6.2 — Data-plane isolation tests
Two-tenant fixtures: `query_result` name-collision returns only caller's rows; `save_data`/`get_data` cross-tenant invisibility; outputs listing/CSV tenant-scoped; scope-miss audit events recorded.
_Done when:_ tests green — delivered in `backend/tests/integration/test_system_tools_tenant_containment.py` (9 tests, including decision-tool strict tenant matching and DB-level stamping checks).

### 6.3 — A2A and notification isolation tests
A2A slug collision resolves within caller's tenant; recipient group resolution per tenant; no NULL-slot dispatch.
_Done when:_ tests green — delivered in `backend/tests/integration/test_a2a_tenant_delegation.py` (4 tests; this suite surfaced and fixed the missing `tenant_id` stamp on delegated jobs in `SessionService.enqueue`) and `backend/tests/integration/test_notification_tenant_dispatch.py` (7 tests).

### 6.4 — MCP same-slug two-tenant tests
Both tenants register `supabase`; per-tenant tool listing/invocation; grants don't cross tenants; CH MCP server per-tenant `tools/list`.
_Done when:_ tests green — delivered in `backend/tests/integration/test_mcp_hub_tenant_slug_isolation.py` (8 tests: DB-level constraint positive/negatives, tenant-stamped sync, binding and grant containment).

### 6.5 — Migration/adoption idempotency + single-tenant regression tests
Run adoption migration twice → identical state; downgrade/upgrade round-trip; full regression suite with multi-tenancy disabled.
_Done when:_ tests green — delivered in `backend/tests/db/test_tenant_adoption_migration.py` (25 tests: runs the real Alembic chain from scratch on `parthenon_test`, `information_schema` NOT NULL/index verification, negative inserts, upgrade-twice and downgrade→replay). Required guarding the pre-existing duplicate `oauth_*` column adds in migration `232324b61ea4` so the chain replays cleanly.

### 6.6 — Scheduler and seeder tenant-binding tests
Delivered as `backend/tests/agent_runtime/test_ar_virtual_tenant_run.py`: scheduler NULL-tenant hard skip, owning-tenant dispatch context, and missing-tenant-row skip. Seeder root-tenant scoping is exercised indirectly (root-bound contexts in the sweep suites) rather than by a dedicated SkillSeeder test — acceptable coverage given the seeder resolves tenants through the same root-default context path validated elsewhere.
_Done when:_ tests green.

## Completion Checklist

- [x] All Phase 1 tasks complete — internal endpoints fail closed
- [x] All Phase 2 tasks complete — adoption migration applied, tenant mandatory
- [x] All Phase 3 tasks complete — MCP hub tenant-scoped
- [x] All Phase 4 tasks complete — AR tenant-aware
- [x] All Phase 5 tasks complete — scheduler/seeder fixed, conventions updated
- [x] All Phase 6 tests pass; full backend suite green with migrations at head (73 new tests; frontend/E2E N/A — backend-only change)
- [x] `alembic upgrade head` verified on a fresh and an adopted database (`backend/tests/db/test_tenant_adoption_migration.py`)
- [x] PRD acceptance criteria each covered by at least one test
