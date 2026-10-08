# Tech Spec: strict-tenant-isolation

## Technical Overview

Tenant isolation becomes strict and fail-closed on the data plane. Signed `X-Internal-Tenant-*` headers (HMAC over tenant id + slug + timestamp, per `backend/app/core/tenant_signature.py`) become **mandatory** on `/api/v1/internal/*` data-plane endpoints — missing or invalid binding is a 401, never a silently unscoped session. Every data-plane service additionally adds explicit tenant predicates as defense in depth, independent of the session-level scoping choke point (`backend/app/db/tenant_scoping.py`).

The NULL-tenant "shared slot" concept is retired: a single idempotent Alembic data migration adopts all legacy NULL-tenant rows into the root tenant, then `tenant_id` becomes NOT NULL on all data-plane tables and every `tenant_id IS NULL OR tenant_id = own` fallback is removed in favor of exact tenant matching. When multi-tenancy is disabled, all contexts (request, internal, scheduler, seeder) resolve to the root tenant — behavior identical, never tenant-less.

MCP hub identity changes from platform-wide slug to per-tenant `(tenant, slug)`. Tool sync stamps a denormalized tenant binding on `McpTool`. The tool wire formats (`server____tool`, `agent____<slug>`) and the header contract are unchanged — resolution becomes tenant-qualified at lookup time, so existing permission grants and skill bindings referencing old global tool names keep working: at resolution time the slug component is matched against the calling tenant's own registry, and the grant/binding rows (adopted into root, or per-tenant) authorize only same-tenant tools with the identical wire name.

Agent Runtime gains virtual tenant awareness: it resolves the calling tenant once from the signed context on the execution request and applies it to all tool/MCP/A2A resolution and every downstream internal call during the run. No code snippets; see the Code Reference Map for exact locations.

## Component Breakdown

- **Internal tenant enforcement dependency** (new, CC): a shared FastAPI dependency wrapping `verify_request_tenant_context` that requires a verified tenant context on internal data-plane routers; applied to the routers in `backend/app/api/v1/internal/` (`system_tools`, `session_data`, `outputs`, `agent_data`, `mcp_proxy`, `authorization`). Non-data-plane internal routers (certificates, bootstrap, validate_api_key) keep certificate-only auth.
- **Session scoping choke point** (CC): `backend/app/db/session.py` `_maybe_apply_request_tenant_scope` loses the verify-if-present branch for internal data-plane traffic; with multi-tenancy off it binds the root tenant instead. `backend/app/db/tenant_scoping.py` semantics unchanged (scoped sessions, `execute_unscoped` reserved for identity plane, scope-miss auditing).
- **Data-plane services** (CC): `AgentDataService`, `OutputService`, `NotificationService`/`NotificationRepository`, `DecisionToolService` — explicit tenant predicates and explicit tenant stamping on writes.
- **Adoption migration** (new, Alembic): one idempotent data-migration revision adopting NULL-tenant rows into the root tenant across all data-plane tables, plus schema-tightening revisions making `tenant_id` NOT NULL and dropping NULL-variant partial unique indexes.
- **MCP hub** (CC): per-tenant `McpServer.slug` uniqueness, `McpTool.tenant_id`, tenant-bound `ToolSyncService`, `(tenant, slug)` lookups everywhere, tenant-aware resolution of `server____tool` names, same-tenant skill bindings and `ToolPermission` grants.
- **A2A naming** (CC + CH): `agent____<slug>` resolution strictly by `(tenant, name)` at `prepare_a2a_request` (CC) and CH `/internal/a2a` forwarding.
- **CH MCP protocol server**: per-tenant `tools/list` / `tools/call` filtering for API-key-authenticated MCP clients.
- **Agent Runtime tenant awareness** (AR): `backend/app/agent_runtime/middleware.py` verifies the signed tenant binding fail-closed; the run carries the tenant through `runtime_executor.py` and `langchain_tool_wrapper.py`, stamping signed headers on every downstream internal call.
- **Scheduler & seeder** (CC): `SchedulingEngine` requires tenant at creation and dispatch (no fallback chain); `SkillSeeder` seeds into root tenant with tenant-scoped lookups.

## API Changes

No endpoint removals. All changes are to `/api/v1/internal/*` (service-to-service, service-certificate authenticated as today):

- **All internal data-plane routers** — signed `X-Internal-Tenant-Id/Slug/Timestamp/Signature` headers are now **required**: absent, stale, or invalidly signed requests return 401 before any handler or DB access. Previously verify-if-present.
- `POST /internal/tools/query_result` (`system_tools.py`) — behavior: resolves `AgentDataType` by slug/name within the bound tenant only; output queries tenant-filtered. Contract unchanged.
- `POST` save_data / get_data / get_output internal tools — behavior: writes stamped and reads filtered by the bound tenant. Contract unchanged.
- `POST /internal/outputs` create + query (`outputs.py`) — behavior: tenant-stamped writes, tenant-filtered queries. Contract unchanged.
- `POST /internal/a2a/request` (`session_data.py`) — behavior: target agent type resolved by `(tenant, name)`; name collisions across tenants no longer resolve. Contract unchanged.
- `get-recipient-group` internal tool — behavior: resolves groups within the bound tenant only.
- **CH MCP protocol server** (`tools/list`, `tools/call`) — behavior: listings and call resolution per the authenticated client's tenant.
- Frontend-facing APIs: **no route, payload, or header changes** — the UI already sends `X-Tenant` and tenant scoping is server-side.

## State Management

- **Frontend: none.** No frontend changes are required. The tenant header (`X-Tenant`) is already sent on workspace requests by the existing frontend tenant handling, and all isolation enforcement in this change is server-side (internal headers, DB predicates, migrations). No new stores, hooks, or state.
- **Backend context state:** the tenant binding for a run is carried as a per-execution verified context in AR (resolved once from signed headers, never ambient/global) and forwarded on each internal call via the existing header-forwarding contextvar mechanism in `backend/app/core/tenant_signature.py` (`bind_forwarded_tenant_headers` / `forward_tenant_headers`).

## Data Access Patterns

- All business data access is server-side (CC owns the database; AR/CH never connect — top priority rule preserved).
- **Session-level scoping (existing, retained):** `get_db` applies `apply_tenant_scope` when a tenant context exists; the `do_orm_execute` listener rewrites SELECTs (`with_loader_criteria`) and ORM UPDATE/DELETE with tenant criteria; INSERTs are stamped at flush; cross-tenant probe misses are audited.
- **Explicit predicates (new, defense in depth):** every service-level query listed in the Code Reference Map adds `tenant_id == <bound tenant>` explicitly, so containment does not hinge solely on session decoration. Writes set `tenant_id` explicitly rather than relying on flush stamping.
- **Identity-plane exemption (unchanged):** `execute_unscoped` remains limited to PlatformUser/Identity-by-sub lookups in the login plane.
- **Migrations:** schema changes only via Alembic revisions under `backend/alembic/versions/`; latest head at planning time is `a7b9c1d3e5f7` (per-tenant entity name uniqueness); implemented revisions `b8c9d0e1f2a3` (adoption + MCP slug scoping, new head) and a replay guard in `232324b61ea4`. Migrations must be applied (`alembic upgrade head`) before backend testing.

## Migration & Compatibility Strategy

- **Ordering:** (1) fail-closed enforcement can ship before the adoption migration only in root-default mode; the strict `IS NULL`-free matching (Phase 2 tasks 2.2–2.6) must go live **after** migration 2.1 has adopted legacy rows. Deployment order: apply migrations → restart CC → restart AR/CH.
- **Adoption migration idempotency:** the update guards on `tenant_id IS NULL` and resolves the root tenant id at runtime; re-running is a no-op, and downgrade restores NULLs so upgrade can be replayed.
- **Existing permission grants & skill bindings referencing old global tool names:** the wire format is unchanged and grants/bindings are not rewritten; they keep working because resolution-time tenant scoping matches the slug against the calling tenant's registry and containment is enforced between grant and tool rows within the same (adopted) tenant. A grant in tenant A never authorizes tenant B's same-named tool.
- **Single-tenancy-disabled regression safety:** with the switch off, every context resolves to the root tenant — internal calls without headers bind root instead of 401ing, scheduler/seeder/decision tools operate on root rows, and behavior is byte-for-byte equivalent to today's single-tenant deployment.
- **Entity name/slug uniqueness:** the per-tenant uniqueness from migration `a7b9c1d3e5f7` is preserved; this change only removes the NULL-variant (global) uniqueness alternatives and the platform-wide `McpServer.slug` constraint.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TenantResolutionMiddleware` | class | Request tenant resolution (CC, external traffic); internal paths bypass | `backend/app/middleware/tenant_resolution.py` |
| `BYPASS_PREFIXES` | constant | Path prefixes skipping tenant resolution (includes `/api/v1/internal/`) | `backend/app/middleware/tenant_resolution.py` |
| `apply_tenant_scope` | function | Records tenant scope on a session (choke point) | `backend/app/db/tenant_scoping.py` |
| `execute_unscoped` | function | Identity-plane per-statement scope exemption | `backend/app/db/tenant_scoping.py` |
| `flush_scope_miss_audits` | function | Persists cross-tenant probe audits | `backend/app/db/tenant_scoping.py` |
| `_maybe_apply_request_tenant_scope` | function | Binds scope for request sessions; becomes fail-closed for internal data-plane traffic | `backend/app/db/session.py` |
| `get_db` | function | Request DB session dependency | `backend/app/db/session.py` |
| `build_tenant_signature_headers` | function | Builds signed `X-Internal-Tenant-*` headers | `backend/app/core/tenant_signature.py` |
| `verify_request_tenant_context` | function | Verifies signed tenant headers; basis of the new mandatory dependency | `backend/app/core/tenant_signature.py` |
| `VerifiedTenantContext` | class | Verified tenant binding result | `backend/app/core/tenant_signature.py` |
| `forward_tenant_headers` | function | Returns signed headers from the forwarding contextvar | `backend/app/core/tenant_signature.py` |
| `bind_forwarded_tenant_headers` | function | Binds the header-forwarding contextvar | `backend/app/core/tenant_signature.py` |
| `TenantContext` | class | Immutable tenant identity value | `backend/app/core/tenant_context.py` |
| `query_result_tool` | endpoint | `query_result` system tool; gains tenant predicates (A1) | `backend/app/api/v1/internal/system_tools.py` |
| `save_data_tool` | endpoint | `save_data` system tool; tenant-stamped writes (A2) | `backend/app/api/v1/internal/system_tools.py` |
| `get_data_tool` | endpoint | `get_data` system tool; tenant-filtered reads (A2) | `backend/app/api/v1/internal/system_tools.py` |
| `get_output_tool` | endpoint | `get_output` system tool; tenant-filtered reads | `backend/app/api/v1/internal/system_tools.py` |
| `get_recipient_group_tool` | endpoint | `get-recipient-group` system tool; tenant-scoped resolution (A6) | `backend/app/api/v1/internal/system_tools.py` |
| `send_notification_tool` | endpoint | Notification dispatch tool; tenant-bound group resolution | `backend/app/api/v1/internal/system_tools.py` |
| `resolve_skills_internal` | endpoint | Skill resolution for AR; tenant-scoped | `backend/app/api/v1/internal/system_tools.py` |
| `list_decision_tools_internal` | endpoint | Decision tool listing; tenant-scoped | `backend/app/api/v1/internal/system_tools.py` |
| `execute_decision_tool_internal` | endpoint | Decision tool execution; tenant-scoped | `backend/app/api/v1/internal/system_tools.py` |
| `prepare_a2a_request` | endpoint | A2A target resolution; becomes `(tenant, name)` (A4) | `backend/app/api/v1/internal/session_data.py` |
| `_extract_delegation_target_slug` | function | Parses `agent____<slug>` names; wire format unchanged | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `build_langchain_tools_for_ar_path` | function | Builds AR tool set; tenant-aware resolution | `backend/app/services/agents/langchain_tool_wrapper.py` |
| `create_internal_output` | endpoint | Output creation; tenant-stamped (A3) | `backend/app/api/v1/internal/outputs.py` |
| `query_internal_outputs` | endpoint | Output listing; tenant-filtered (A3) | `backend/app/api/v1/internal/outputs.py` |
| `AgentDataService` | class | save/list/query for AgentData; explicit tenant predicates + stamping (A2) | `backend/app/services/agent_data/service.py` |
| `OutputService` | class | Typed output persistence/query; tenant predicates (A1/A3) | `backend/app/services/outputs/service.py` |
| `NotificationService` | class | Dispatch; group/channel resolution strictly tenant-equal — NULL default removed, context-less background paths resolve the root tenant (A5) | `backend/app/services/notifications/notification_service.py` |
| `NotificationRepository` | class | Group/channel lookups; mandatory tenant predicates (A5/D) | `backend/app/services/notifications/repository.py` |
| `SkillSeeder` | class | Seeds skills into root tenant; tenant-scoped lookups (B2) | `backend/app/services/skill_seeder.py` |
| `SchedulingEngine` | class | Job dispatch; tenant mandatory at creation and dispatch (B4) | `backend/app/services/scheduling/scheduler.py` |
| `_resolve_type` (decision draft data-type resolution) | closure | Drops `IS NULL OR own`; exact tenant match (B1) | `backend/app/api/v1/decision_tools.py` |
| `_resolve_data_types` | method | Decision tool input/output data-type resolution; exact tenant match (B1) | `backend/app/services/system_one/decision_tool_service.py` |
| `require_internal_tenant_context` | function | Shared dependency enforcing mandatory signed tenant context on internal data-plane routers; 401 on missing/invalid headers, root-default when multi-tenancy off | `backend/app/api/deps.py` |
| `enqueue` (`SessionService.enqueue` with `tenant_id`) | method | Session/delegated job creation; `tenant_id` param stamps the owning tenant so delegation never creates tenant-less sessions | `backend/app/services/agents/session_service.py` |
| `tenant_headers` signing in validate_api_key | endpoint behavior | CC signs the API key's tenant context so CH can forward `X-Internal-Tenant-*` to internal hops | `backend/app/api/v1/internal/validate_api_key.py` |
| AR `comm_hub_client` header forwarding | client behavior | Every AR→CH/CC internal call stamps the run's forwarded signed tenant headers | `backend/app/agent_runtime/comm_hub_client.py` |
| `DecisionToolService` | class | Decision tool CRUD; strict tenant data-type resolution (B1) | `backend/app/services/system_one/decision_tool_service.py` |
| `resolve_virtual_tool_id` | function | Virtual decision-tool id resolution; tenant-scoped | `backend/app/services/system_one/decision_tool_service.py` |
| `McpServer` | model | Slug unique per tenant; tenant mandatory | `backend/app/db/models/mcp_hub.py` |
| `McpTool` | model | Gains denormalized `tenant_id` | `backend/app/db/models/mcp_hub.py` |
| `ToolPermission` | model | Tool grants; same-tenant containment | `backend/app/db/models/mcp_hub.py` |
| `ToolSyncService` | class | Tool sync; tenant-bound upserts (B3) | `backend/app/services/mcp/tool_sync.py` |
| `build_tool_name` | function | `server____tool` builder; wire format unchanged | `backend/app/services/agents/tool_naming.py` |
| `parse_tool_name` | function | `server____tool` parser; resolution becomes tenant-qualified at call sites | `backend/app/services/agents/tool_naming.py` |
| `RESERVED_SERVER_NAMES` | constant | `system`/`decision` reserved namespaces | `backend/app/services/agents/tool_naming.py` |
| `runtime_executor` (McpTool lookup by namespaced name) | function | Tool invocation; tenant-filtered, fails closed (B3) | `backend/app/services/agents/runtime_executor.py` |
| AR tenant-verification middleware | middleware | Requires signed tenant binding on execution requests; fail-closed | `backend/app/agent_runtime/middleware.py` |
| CH control-plane middleware | middleware | Verifies/forwards signed tenant context on `/internal/a2a` and MCP server hops | `backend/app/communication_hub/middleware/control_plane.py` |
| `TenantAdoptionService` | class | Enable/disable adoption flows; reuses idempotent adoption and realigns `McpTool.tenant_id` with its server's tenant (Phase 3 alignment) | `backend/app/services/tenancy/tenant_adoption_service.py` |
| `get_root_tenant_context` | function | Root tenant resolution for switch-off default binding | `backend/app/services/tenancy/root_tenant.py` |
| Adoption migration (NULL tenant → root, per-tenant MCP slug scoping) | migration | One-time idempotent data + schema migration; current Alembic head | `backend/alembic/versions/b8c9d0e1f2a3_per_tenant_entity_adoption_and_mcp_slug_scoping.py` |
| `oauth_*` column replay guard in `232324b61ea4` | migration touch-up | Guards pre-existing duplicate `mcp_sessions.oauth_*` column adds so the chain replays from an empty DB (required by the adoption-migration tests) | `backend/alembic/versions/232324b61ea4_add_model_config_agent_type_model_.py` |
| Per-tenant entity name uniqueness | migration | Prior head; preserved by this change | `backend/alembic/versions/a7b9c1d3e5f7_per_tenant_entity_name_uniqueness.py` |
