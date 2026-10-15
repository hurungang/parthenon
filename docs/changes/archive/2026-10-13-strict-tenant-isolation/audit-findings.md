# Multi-Tenancy Independence Audit Findings (2026-10-07)

Source: codebase audit after multi-tenancy implementation. STRICT RULE (owner-confirmed): tenants are fully independent — no cross-tenant fallback/sharing of business data. Root tenant = platform management users, and the single tenant when multi-tenancy is disabled.

## Root systemic cause
- `backend/app/db/session.py` + `backend/app/db/tenant_scoping.py`: session-level tenant scoping is applied ONLY when signed `X-Internal-Tenant-*` headers are present on `/api/v1/internal/*` traffic ("verify-if-present" → fail-open). Headerless internal traffic = completely unscoped DB session.
- Data-plane services additionally omit explicit tenant predicates, so containment hinges entirely on session decoration.

## A. Violations (data plane)
| # | Location | Issue |
|---|----------|-------|
| A1 | `backend/app/api/v1/internal/system_tools.py` (~488-505) `query_result` tool | Resolves AgentDataType by slug then name with NO tenant predicate; `OutputService.list_outputs` (`backend/app/services/outputs/service.py` 92-137) queries AgentOutput unfiltered → cross-tenant output reads |
| A2 | `backend/app/services/agent_data/service.py` (26-203) + system_tools save_data/get_data (574-729) | Queries filter only `is_active`; `save()` never sets `tenant_id` (relies on session scoping); unscoped traffic reads/writes NULL-tenant rows and cross-tenant via `data_name` |
| A3 | `backend/app/api/v1/internal/outputs.py` (157-222) + `backend/app/services/outputs/service.py` | AgentOutput selects at ~110/162/191/356 have zero tenant filtering |
| A4 | `backend/app/api/v1/internal/session_data.py` (~727) A2A target resolution | `select(AgentType).where(AgentType.name == slug)` — name-only, cross-tenant hijack of delegation target |
| A5 | `backend/app/services/notifications/notification_service.py` (66) | `get_recipient_group_by_slug(group_slug)` defaults tenant_id=None → always resolves NULL-tenant shared slot; tenant groups unreachable; `repository.py` 159-174 filters `tenant_id IS NULL` |
| A6 | `backend/app/api/v1/internal/system_tools.py` (171-180) `get-recipient-group` | No tenant predicate (inconsistent with `notifications/mcp_tool.py` 170-178 which uses contextvar — itself unset on internal CC paths) |

## B. Shared-slot designs contradicting strict containment (retire on data plane)
| # | Location | Issue |
|---|----------|-------|
| B1 | `backend/app/api/v1/decision_tools.py` (150-157), `backend/app/services/system_one/decision_tool_service.py` (394-401) | `or_(AgentDataType.tenant_id.is_(None), tenant_id == own)` — NULL "platform shared types" referenceable by every tenant |
| B2 | `backend/app/services/skill_seeder.py` (48, 67-73, 102-106) | Seeds skills with tenant_id=NULL visible to all tenants; global name lookups can mutate tenant skills into system skills |
| B3 | `backend/app/services/agents/runtime_executor.py` (4042-4046), `backend/app/services/mcp/tool_sync.py` (343) | McpTool has no tenant_id; global registry keyed by platform-wide McpServer.slug; tool naming (`backend/app/services/agents/tool_naming.py` build_tool_name/parse_tool_name), A2A `agent____<slug>` (`langchain_tool_wrapper.py` 247-252, 575), skill bindings and permission grants all assume platform-wide slug |
| B4 | `backend/app/services/scheduling/scheduler.py` (140-151) | `job.tenant_id or agent_type.tenant_id`; both NULL → dispatch chain runs with tenant_context=None (escapes quotas/scoping) |

## C. Accepted (login/identity plane — NOT in scope)
- `backend/app/middleware/auth.py` (208-247) own→shared→root token-validation chain — documented login-context resolution.
- `backend/app/services/oidc_provider_registry.py` get_provider_candidates — login-plane.
- `backend/app/db/tenant_scoping.py` execute_unscoped identity lookups (PlatformUser/Identity by sub).
- Agent OAuth/refresh resolvers already made strict per-identity-tenant (identity_service.py, token_refresh_service.py, token_refresh.py).
- Entity name/slug unique constraints already tenant-scoped (migration a7b9c1d3e5f7); McpServer.slug still platform-wide — in scope here.

## D. Secondary
- `NotificationRepository.get_channel/list_channels/get_recipient_group` by id — no tenant predicate (choke-point-only protection).
- `DataTypeService.get/update/delete` raw `db.get()` — same.

## Fix strategy
1. Make signed X-Internal-Tenant-* headers MANDATORY on `/api/v1/internal/*` (fail closed 401).
2. Add explicit tenant predicates inside services (defense in depth).
3. One-time adoption migration: NULL-tenant legacy rows → root tenant; then strict `tenant_id == root` matching (drop `IS NULL OR own` patterns); treat NULL tenant at dispatch/creation as hard error.
4. Tenant-bind McpServer.slug; tenant-scope tool namespacing, skill bindings, permission grants; Agent Runtime runs agents with virtual tenant awareness so tool invocation resolves the calling tenant's server/tools.
