# Token Expiry Alerting Test Plan

## Scope

Covers token expiry alerting across Control Center, Communication Hub (gateway preflight), frontend dashboard cards and topology badges, and database schema/migrations. This feature enforces pre-execution token health checks with clear warnings/blocking, tenant isolation, and remediation paths.

## Coverage Areas

### 1. Token Health Classification (Backend)
- Classification boundaries for agent identities (`token_expires_at`, `refresh_token_expires_at`) and MCP sessions (`oauth_expires_at`, `oauth_refresh_expires_at`)
- States: `healthy`, `expiring` (within 7 days), `expired`, `unknown` (missing timestamps)
- Read-time recomputation overrides stale persisted state
- Inactive MCP sessions excluded from aggregation

**Test files:**
- [backend/tests/services/test_token_health_service.py](../../../../backend/tests/services/test_token_health_service.py) — Health classification, persistence, preflight resolution

### 2. Token Refresh Engine & Persistence (Backend)
- Identity refresh persists `refresh_token_expires_at`, `last_token_refresh_outcome`, `token_health_state`
- MCP OAuth refresh persists health fields on `McpSession` and writes `TokenRefreshLog` with nullable `mcp_session_id`
- Failed refresh attempts recorded without corrupting health state

**Test files:**
- [backend/tests/services/test_token_health_service.py](../../../../backend/tests/services/test_token_health_service.py)

### 3. Dashboard Token Health API (Backend)
- `GET /api/v1/dashboard/token-health` returns counts and itemized details per category with remediation targets/paths
- JWT auth required; tenant scoping enforced
- Permission-checked visibility; remediation triggers (`/agents/identities/{id}/refresh`, `/mcp/sessions/{id}/re-auth`)

**Test files:**
- [backend/tests/api/v1/test_token_health_api.py](../../../../backend/tests/api/v1/test_token_health_api.py)

### 4. Execution Preflight API (Backend)
- PROCEED / PROCEED+WARN / BLOCKED resolution including full subagent composition (static + `AgentRunRelationship` trees)
- Per-target messages naming affected identity/session
- Fail-closed 401 without valid signed `X-Internal-Tenant-*` headers
- `TokenHealthCheck` audit rows written for every evaluation (insert-only)

**Test files:**
- [backend/tests/api/v1/test_token_health_api.py](../../../../backend/tests/api/v1/test_token_health_api.py)
- [backend/tests/services/test_token_health_service.py](../../../../backend/tests/services/test_token_health_service.py)

### 5. Agent Gateway Preflight Gate (Communication Hub)
- BLOCKED prevents execution start for agent and all associated subagents; user-facing message names identity/session
- PROCEED+WARN allows execution while surfacing warnings
- Uses `internal_httpx_client` only; no token material forwarded
- Fails closed on PermissionDenied/CC-unavailable

**Test files:**
- [backend/tests/communication_hub/test_gateway_preflight_gate.py](../../../../backend/tests/communication_hub/test_gateway_preflight_gate.py)

### 6. Dashboard Cards + Remediation Routing (Frontend)
- Separate expired/expiring indicators for agent identities and MCP sessions
- Click-through navigates to `AgentIdentityListPage` / `McpSessionManager`
- Permission-denied placeholder per `StatCard` pattern; i18n via `t()`
- Warnings disappear after refresh/re-auth (refetch)

**Test files:**
- [frontend/src/__tests__/TokenHealthDashboard.test.tsx](../../../../frontend/src/__tests__/TokenHealthDashboard.test.tsx)

### 7. Topology Badges (Frontend)
- Warning badge for containers with identity/MCP session ≤7 days to expiry; error badge for expired
- Badges rendered in `PanelTopologyCanvas` / `TopologyDiagramRenderer` in viewBox units
- Graceful handling when health data missing

**Test files:**
- [frontend/src/__tests__/PanelTopologyTokenHealth.test.tsx](../../../../frontend/src/__tests__/PanelTopologyTokenHealth.test.tsx)
- [frontend/src/__tests__/TopologyDiagramRenderer.test.tsx](../../../../frontend/src/__tests__/TopologyDiagramRenderer.test.tsx)

### 8. DB Migration & Schema (Backend)
- New columns/tables/indexes applied cleanly; `TokenHealthCheck` audit table created
- `TokenRefreshLog.mcp_session_id` nullable (backward compatible)
- ORM round-trips verified

**Test files:**
- [backend/tests/db/test_token_health_schema.py](../../../../backend/tests/db/test_token_health_schema.py)

### 9. E2E Flows (Mocked + Real-Backend Considerations)
- Dashboard alerts → click-through remediation → warnings cleared
- Execution BLOCKED with named identity (including subagent); expiring warns and proceeds
- Topology warning/error badges

**Test files:**
- [e2e/tests/token-expiry-dashboard-remediation.spec.ts](../../../../e2e/tests/token-expiry-dashboard-remediation.spec.ts)
- [e2e/tests/token-expiry-execution-preflight.spec.ts](../../../../e2e/tests/token-expiry-execution-preflight.spec.ts)
- [e2e/tests/token-expiry-topology-badges.spec.ts](../../../../e2e/tests/token-expiry-topology-badges.spec.ts)

### 10. Security & Tenant Isolation
- Tenant-scoped data and audit records
- Agents never receive token material
- Internal preflight fails closed without signed headers
- Resource types registered in backend and frontend manifests

**Test files:**
- [backend/tests/api/v1/test_token_health_api.py](../../../../backend/tests/api/v1/test_token_health_api.py)
- [backend/tests/services/test_token_health_service.py](../../../../backend/tests/services/test_token_health_service.py)

## Acceptance Criteria
- Dashboard shows separate expired/expiring indicators for agent identities and MCP sessions with click-through remediation
- Expired tokens block execution with named identity/session; expiring tokens warn but proceed
- No token failure discoverable only at execution time
- Topology shows warning/error badges appropriately
- All preflight evaluations create `TokenHealthCheck` audit rows
- Internal preflight fails closed without signed headers
- Warnings clear after successful refresh/re-auth
- Tenant isolation enforced end-to-end
- All UI text uses i18next; types mirror backend enums

## Execution Results (2026-10-27)
| Layer | Suites | Result |
|---|---|---|
| Backend (pytest) | token health service 23 + gateway gate 8 + token-health API 6 + schema/migration 10 | 47 passed |
| Frontend (Vitest) | TokenHealthDashboard 5 + PanelTopologyTokenHealth 6 (full suite 1739 passed / 1 pre-existing unrelated failure) | pass |
| E2E (Playwright, mocked) | dashboard remediation 6 + execution preflight 2 + topology badges 4 | 12 passed |
