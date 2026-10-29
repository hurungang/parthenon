# Tech Spec — Token Expiry Alerting

## Technical Overview

Token Expiry Alerting adds a computed token health state (`healthy` / `expiring-within-7-days` / `expired`) for agent identities and MCP sessions, computed exclusively in Control Center from token metadata it already owns, persisted on the entities, and surfaced through three channels: dashboard health cards with click-through remediation, an execution preflight gate in the Communication Hub Agent Gateway (expired ⇒ block + alert, expiring ⇒ warn), and warning/error badges on the unified agent topology canvas. A new `TokenHealthCheck` audit entity records every preflight evaluation. All `top_priority_rules` hold: the three backend services remain fully segregated, only Control Center touches the database, and agents never receive or hold identity tokens — they observe only blocked/warn/proceed outcomes returned by the Gateway.

## Component Breakdown

| Component | Service | Responsibility |
|---|---|---|
| Token Health Service | Control Center | Single owner of token expiry state; computes and persists `healthy`/`expiring`/`expired`/`unknown` for agent identities and MCP sessions; 7-day threshold constant. |
| Token Refresh Engine (extended) | Control Center | Existing identity refresh engine; now persists `token_health_state` and `last_token_refresh_outcome` after every refresh attempt and captures `refresh_token_expires_at`. |
| MCP OAuth Refresh (extended) | Control Center | Existing `OAuthRefreshService`; now persists health fields on `McpSession` and logs session refresh rows to `TokenRefreshLog` via the new nullable `mcp_session_id`. |
| Token Health Dashboard API (new) | Control Center | Tenant-scoped, JWT-authenticated REST surface: expired/expiring counts + itemized details per category, and refresh / re-auth trigger endpoints. |
| Execution Preflight API (new) | Control Center | Internal endpoint resolving every token an execution (including subagents) will use; returns PROCEED / PROCEED+WARN / BLOCKED with named targets; fails closed (401) without signed `X-Internal-Tenant-*` headers. |
| Topology Enrichment (new) | Control Center | Per-container token health computed via the Token Health Service and delivered through the itemized `GET /dashboard/token-health` payload (the zoned topology is composed client-side, so no separate topology API was added). |
| Agent Gateway Preflight Gate (new) | Communication Hub | Calls the preflight API before every execution start via `internal_httpx_client`; enforces block/warn/proceed; surfaces user-facing messages; forwards no token material. |
| Dashboard Token Health Cards (new) | Frontend | Expired / expiring counts per category with permission-checked visibility and click-through remediation routing. |
| Topology Badges (new) | Frontend | Warning (expiring ≤7 days) and error (expired) badges on containers in the single canonical topology canvas. |

## API Changes

All endpoints are tenant-scoped; internal endpoints fail closed (401) without valid signed `X-Internal-Tenant-*` headers carried by `internal_httpx_client`.

| Endpoint | Method | Service | Purpose |
|---|---|---|---|
| `/api/v1/dashboard/token-health` | GET | CC | Counts and itemized details of expired / expiring tokens per category (agent identities, MCP sessions), with remediation deep-link targets. |
| `/api/v1/agents/identities/{identity_id}/refresh-token` | POST | CC | Existing endpoint, reused as the dashboard's on-demand identity token refresh trigger. |
| `/api/v1/mcp/servers/{server_id}/sessions/{session_id}/refresh-token` | POST | CC | Existing endpoint, reused as the dashboard's MCP session re-auth/refresh trigger. |
| `/api/v1/internal/token-health/preflight` | POST | CC (internal) | Preflight evaluation for an execution: resolves agent + subagent tokens, returns PROCEED / PROCEED+WARN / BLOCKED with per-target messages. Signed internal calls only. |
| Topology data endpoints | — | — | No changes: the topology is composed client-side; per-container health arrives via the itemized `/api/v1/dashboard/token-health` response. |
| Agent execution endpoints (existing, CH gateway) | — | CH | Behavior change only: executions now pass through the preflight gate; BLOCKED returns an actionable message naming the identity/session. |

Resource-type note: any new endpoint guarded by `require_permission()` must have its resource type registered in both `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts`, or all users (including wildcard admins) receive 403.

## State Management

**Backend (Control Center — sole owner):**
- `token_health_state` on `AgentIdentity` and `McpSession` is the persisted, denormalized health classification; recomputed on every token refresh and on dashboard/topology read (read-time recomputation guards against stale rows).
- Classification is a pure function of timestamps (`token_expires_at`, `refresh_token_expires_at` / `oauth_expires_at`, `oauth_refresh_expires_at`) plus refresh outcome and entity status — deterministic and unit-testable; `unknown` when timestamps are missing.
- `TokenHealthCheck` rows are immutable audit records written per preflight evaluation (including blocked runs); `health_state` is computed at check time, never a stored invariant.
- CH holds no token state: the Gateway is stateless with respect to health, calling CC per execution start and propagating only the outcome.

**Frontend:**
- Dashboard token health data is fetched per page load (no global store) and held in local component state, consistent with existing `DashboardPage.tsx` data-fetching patterns.
- Topology token health arrives via the itemized `/dashboard/token-health` payload (fetched with `useTokenHealth`) and is derived into per-container badge state inside `PanelTopologyCanvas.tsx`'s existing render pipeline; no new state store is introduced.
- All wire states are typed as TypeScript string enums mirroring the backend Pydantic/Python enums.

## Data Access Patterns

- All database access occurs in Control Center only. CH reaches CC exclusively through `internal_httpx_client` (`backend/app/core/internal_http.py`) with auto-forwarded signed tenant headers; the frontend uses REST only.
- Token Health Service queries are tenant-scoped selects over `AgentIdentity` (filtering `token_expires_at` / `refresh_token_expires_at` / `token_status`) and `McpSession` (filtering `oauth_expires_at` / `oauth_refresh_expires_at`, active sessions only), using async SQLAlchemy 2 sessions — same pattern as `DashboardMetricsService` aggregate counting.
- Preflight resolves the agent type's identity and bound MCP sessions, then walks subagent composition to collect the full token set; for runtime trees, parent–child edges in `AgentRunRelationship` (`backend/app/db/models/agent_run_relationship.py`) provide the execution tree when resolving already-submitted subagents.
- Dashboard aggregate reads use indexed expiry-timestamp range queries (expired: `<= now`; expiring: `now` to `now + 7 days`); itemized details reuse the same predicates with a small limit.
- `TokenHealthCheck` writes are insert-only (append-only audit); no updates or deletes. `TokenRefreshLog` remains the per-attempt refresh audit, extended with the nullable `mcp_session_id`.

## Code Reference Map

| Symbol | Type | Description | File |
|---|---|---|---|
| `TokenHealthCheck` | SQLAlchemy model (new) | Preflight audit entity (tenant-scoped, target_kind/target_id, health_state, check_outcome, message) | `backend/app/db/models/token_health.py` |
| `TokenHealthState` | Python Enum (new) | healthy / expiring / expired / unknown | `backend/app/db/models/token_health.py` |
| `TokenCheckOutcome` | Python Enum (new) | passed / blocked | `backend/app/db/models/token_health.py` |
| `TokenRefreshOutcome` | Python Enum (new) | success / failure | `backend/app/db/models/token_health.py` |
| `AgentIdentity` | SQLAlchemy model | Agent OIDC principal; gains `refresh_token_expires_at`, `last_token_refresh_outcome`, `token_health_state` | `backend/app/db/models/agents.py` |
| `AgentTokenStatus` | Python Enum | Existing identity token status (active/expired/…); reused alongside new health state | `backend/app/db/models/agents.py` |
| `McpSession` | SQLAlchemy model | Named MCP session credential binding; gains `last_token_refresh_at`, `last_token_refresh_outcome`, `token_health_state` | `backend/app/db/models/mcp_hub.py` |
| `TokenRefreshLog` | SQLAlchemy model | Refresh audit log; gains nullable `mcp_session_id` | `backend/app/db/models/agent_security.py` |
| `AgentRunRelationship` | SQLAlchemy model | Runtime parent–child execution edges (subagent tree resolution) | `backend/app/db/models/agent_run_relationship.py` |
| `check_token_expiration` | function (extended) | Existing expiry check for an identity; extended to evaluate refresh-token expiry window | `backend/app/services/token_refresh.py` |
| `refresh_oauth_token` | function (extended) | Identity token refresh; now persists health state and refresh outcome | `backend/app/services/token_refresh.py` |
| `store_refreshed_token` | function (extended) | Persists refreshed tokens; captures `refresh_token_expires_at` | `backend/app/services/token_refresh.py` |
| `TokenRefreshServiceV2` | class | V2 refresh facade; methods extended to propagate health fields | `backend/app/services/token_refresh.py` |
| `AgentIdentityService` | class | Identity lifecycle service; remediation target for refresh trigger endpoint | `backend/app/services/agents/identity_service.py` |
| `OAuthRefreshService` | class (extended) | MCP session OAuth refresh; now persists `McpSession` health fields and logs via `mcp_session_id` | `backend/app/services/mcp/oauth_refresh.py` |
| Token Health Service | service module (new) | Computes/persists health classification for identities and sessions; 7-day constant | `backend/app/services/token_health.py` |
| Token health schemas | Pydantic models (new) | Dashboard summary/items + preflight request/result (PROCEED / PROCEED+WARN / BLOCKED) | `backend/app/schemas/token_health.py` |
| Token Health Dashboard endpoint | API endpoint (new) | `GET /dashboard/token-health` — expired/expiring counts + itemized details per category with permission flags | `backend/app/api/v1/dashboard.py` |
| `InternalTokenHealthRouter` | API router (new) | `POST /internal/token-health/preflight` — signed internal calls only, fail-closed 401 | `backend/app/api/v1/internal/token_health.py` (registered in `backend/app/api/v1/__init__.py`) |
| Preflight gate | service module (new) | CH-side gate: calls CC preflight via `internal_httpx_client`; BLOCKED raises, unreachable fails closed | `backend/app/services/gateway/preflight_gate.py` |
| `AgentExecuteResponse.warnings` | schema field (extended) | CH execution trigger response now carries expiring-token notices | `backend/app/communication_hub/api/internal/agent_execute.py` |
| `TokenRefreshLog.agent_identity_id` | migration (new) | Relaxed to nullable + exactly-one-target check constraint | `backend/alembic/versions/b1c2d3e4f5a6_token_refresh_log_nullable_identity_id.py` |
| Remediation trigger endpoints | API endpoints (existing, reused) | `POST /agents/identities/{id}/refresh-token` (`backend/app/api/v1/agents.py`) and `POST /mcp/servers/{server_id}/sessions/{session_id}/refresh-token` (`backend/app/api/v1/mcp_hub.py`) serve as the dashboard refresh / re-auth triggers — no new endpoints | — |
| `DashboardMetricsService` | class | Existing dashboard aggregation; pattern reference for tenant-scoped counts and permission-checked visibility | `backend/app/services/dashboard_metrics_service.py` |
| Token Health Dashboard router | API router (new) | `/dashboard/token-health`, refresh/re-auth trigger endpoints | `backend/app/api/v1/dashboard.py` |
| Identity admin router | API router (existing) | `/agents/identities` surface; hosts the identity refresh trigger | `backend/app/api/v1/agents.py` |
| MCP hub router | API router (existing) | MCP sessions surface; hosts the session re-auth trigger | `backend/app/api/v1/mcp_hub.py` |
| Preflight router | API router (new) | `/internal/token-health/preflight`; signed internal calls only | `backend/app/api/v1/internal/token_health.py` |
| `GatewayLifecycleHandler` | class (existing, unchanged) | Agent Gateway execution lifecycle in Control Center; does NOT invoke the preflight gate (runs in CC, not CH) | `backend/app/services/gateway/lifecycle_handler.py` |
| CH execution preflight enforcement | API handler (extended) | The preflight gate is enforced at the Communication Hub `POST /internal/agent/execute` execution-start path: `enforce_execution_preflight` runs before execution, BLOCKED raises 422, warnings are returned in the response | `backend/app/communication_hub/api/internal/agent_execute.py` |
| `GatewayEndpointRegistry` | class | Gateway endpoint registry; unchanged, listed for execution-path context | `backend/app/services/gateway/registry.py` |
| `internal_httpx_client` | function | The only approved internal HTTP client (signed `X-Internal-Tenant-*` headers); used by the Gateway preflight call | `backend/app/core/internal_http.py` |
| `DashboardPage` | React component (extended) | Adds token-health cards for identities and MCP sessions | `frontend/src/pages/DashboardPage.tsx` |
| `StatCard` | React component | Reused snapshot card; token-health cards follow its permission-denied placeholder pattern | `frontend/src/components/dashboard/StatCard.tsx` |
| `TimeSensitiveCard` | React component | Reused time-sensitive card wrapper for token-health indicators | `frontend/src/components/dashboard/TimeSensitiveCard.tsx` |
| `PanelTopologyCanvas` | React component (extended) | Single canonical topology view; derives per-container token health and renders badges | `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` |
| `TopologyDiagramRenderer` | React component (extended) | SVG renderer; gains warning/error badge rendering in viewBox units | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |
| `agentTypeToDraftComposition` | module | Maps agent type to canvas draft shape; unchanged, must keep working with enriched health data | `frontend/src/components/agents/agentTypeToDraftComposition.ts` |
| `AgentIdentityListPage` | React page (extended) | Remediation target for identity token warnings (refresh) | `frontend/src/pages/agents/AgentIdentityListPage.tsx` |
| `McpSessionManager` | React page (extended) | Remediation target for MCP session re-auth warnings | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpHubPage` | React page (existing) | MCP hub surface containing session management context | `frontend/src/pages/mcp/McpHubPage.tsx` |
| Token health API client | TypeScript module (new) | Typed fetchers + `TokenHealthState` enum for dashboard/topology data | `frontend/src/api/tokenHealthApi.ts`, `frontend/src/types/tokenHealth.ts` |
| `useTokenHealth` | React hook (new) | React Query hook for the dashboard token-health payload | `frontend/src/hooks/useTokenHealth.ts` |
| `RESOURCE_TYPE_MANIFEST` | constant (possibly extended) | Frontend resource-type registry; must mirror any new backend resource type | `frontend/src/constants/resourceTypes.ts` |
| Token health test suites | tests (new) | Service classification/persistence/preflight (`tests/services/test_token_health_service.py`), dashboard+preflight API (`tests/api/v1/test_token_health_api.py`), CH gate (`tests/communication_hub/test_gateway_preflight_gate.py`), dashboard cards (`TokenHealthDashboard.test.tsx`), topology badges (`PanelTopologyTokenHealth.test.tsx`) | `backend/tests/`, `frontend/src/__tests__/` |
| Topology enrichment note | design decision | The zoned agent topology is composed CLIENT-SIDE (no CC topology endpoint for the panel); the enriched data path is `GET /dashboard/token-health` consumed by `PanelTopologyCanvas` via `useTokenHealth`, which derives per-container badge state. `TopologyNode.tokenHealth` (`frontend/src/types/index.ts`) carries `'expiring' | 'expired'`. The CH preflight gate lives in `preflight_gate.py` invoked from `/internal/agent/execute` (the CH execution-start path) rather than `lifecycle_handler.py` (which runs in CC). No new resource types were needed — existing `agent::identities` / `integration::mcp_hub` guard the dashboard endpoint. | — |
