# Implementation Plan — Token Expiry Alerting

## Overview

This plan implements the Token Expiry Alerting epic: token health state computation in Control Center, dashboard token-health cards with remediation routing, an execution preflight gate in the Communication Hub Agent Gateway, and warning/error badges on the unified agent topology canvas. Work is ordered so the data model and Control Center health service land first, followed by APIs, the Agent Gateway gate, and finally the frontend surfaces.

All tasks respect `docs/config.yaml` `top_priority_rules`: services remain fully segregated, only Control Center accesses the database, and agents never receive or hold identity tokens.

## Task Checklist

### Phase 1 — Data Model & Migration

- [x] 1.1 — Define `TokenHealthState`, `TokenRefreshOutcome`, and `TokenCheckOutcome` enums and the `TokenHealthCheck` entity
- [x] 1.2 — Add token health fields to `AgentIdentity`
- [x] 1.3 — Add token health fields to `McpSession`
- [x] 1.4 — Add nullable `mcp_session_id` to `TokenRefreshLog`
- [x] 1.5 — Export new models and generate/review/apply the Alembic migration

### Phase 2 — Control Center Token Health Service

- [x] 2.1 — Implement the Token Health Service (expiry classification)
- [x] 2.2 — Wire health-state persistence into the identity token refresh flow
- [x] 2.3 — Wire health-state persistence into the MCP session OAuth refresh flow
- [x] 2.4 — Add unit tests for the Token Health Service

### Phase 3 — Control Center APIs

- [x] 3.1 — Token Health Dashboard API (counts, details, refresh/re-auth triggers)
- [x] 3.2 — Execution Preflight internal API
- [x] 3.3 — Topology enrichment of container token health
- [x] 3.4 — Permission/resource-type registration and API tests

### Phase 4 — Communication Hub Agent Gateway Preflight Gate

- [x] 4.1 — Call the preflight API from the Agent Gateway execution path
- [x] 4.2 — Enforce block/warn outcomes and surface user-facing messages
- [x] 4.3 — Gateway unit tests for the preflight gate

### Phase 5 — Frontend: Dashboard & Remediation Routing

- [x] 5.1 — Token health API client and typed models
- [x] 5.2 — Dashboard token-health cards (identities / MCP sessions, expired vs expiring)
- [x] 5.3 — Click-through remediation routing to identity and MCP session pages
- [x] 5.4 — Frontend unit tests for dashboard cards and routing

### Phase 6 — Frontend: Topology Badges

- [x] 6.1 — Derive per-container token health in the unified topology canvas
- [x] 6.2 — Render warning/error badges on containers
- [x] 6.3 — Topology badge unit tests

### Phase 7 — End-to-End Verification & Docs

- [ ] 7.1 — End-to-end verification of the full flow
- [ ] 7.2 — Update `docs/master/` documentation per architecture.md §6 and data-model.md §5

## Phase 1 — Data Model & Migration

**1.1 — Define `TokenHealthState`, `TokenRefreshOutcome`, and `TokenCheckOutcome` enums and the `TokenHealthCheck` entity**
Create `backend/app/db/models/token_health.py` with the `TokenHealthCheck` preflight-audit entity exactly as specified in `data-model.md` §1 (tenant-scoped, `target_kind`/`target_id` polymorphic reference, `health_state`, `check_outcome`, `message`, `checked_at`) and the three new Python enums. Use strong typing (SQLAlchemy 2 `Mapped`/`mapped_column`, `str`-based Python Enums).

Done when: the model file exists, imports cleanly, and matches the entity definition in `data-model.md`.

**1.2 — Add token health fields to `AgentIdentity`**
In `backend/app/db/models/agents.py`, add `refresh_token_expires_at`, `last_token_refresh_outcome`, and `token_health_state` to `AgentIdentity` per `data-model.md` §2. Do not alter existing encrypted token columns.

Done when: the three nullable columns exist on `AgentIdentity` and no existing column is modified.

**1.3 — Add token health fields to `McpSession`**
In `backend/app/db/models/mcp_hub.py`, add `last_token_refresh_at`, `last_token_refresh_outcome`, and `token_health_state` to `McpSession` per `data-model.md` §2.

Done when: the three nullable columns exist on `McpSession`.

**1.4 — Add nullable `mcp_session_id` to `TokenRefreshLog`**
In `backend/app/db/models/agent_security.py`, add a nullable `mcp_session_id` reference alongside `agent_identity_id` on `TokenRefreshLog` (exactly one set per row, per `data-model.md` §2).

Done when: the column exists with a check constraint (or documented invariant) ensuring exactly one target per row.

**1.5 — Export new models and generate/review/apply the Alembic migration**
Export the new model in `backend/app/db/models/__init__.py` so autogenerate detects it. Then: `python -m alembic revision --autogenerate -m "token expiry alerting"`, review the generated file (correct `down_revision` chain, `postgresql.ENUM(..., create_type=False)` for enums, reversible `downgrade()`), then `python -m alembic upgrade head` and verify with `python -m alembic current` — all BEFORE any backend testing.

Done when: `alembic current` shows the new revision; the upgrade runs cleanly against a fresh database and the downgrade round-trips.

## Phase 2 — Control Center Token Health Service

**2.1 — Implement the Token Health Service (expiry classification)**
New CC-only service (e.g. `backend/app/services/token_health.py`) that computes `healthy / expiring / expired / unknown` for agent identities (from `token_expires_at`, `refresh_token_expires_at`, `token_status`, `last_token_refresh_outcome`) and MCP sessions (from `oauth_expires_at`, `oauth_refresh_expires_at`). 7-day threshold for "expiring" is a named constant. Tenant-scoped queries only; this is the single owner of token expiry state and the only new reader of token metadata. Extend the existing refresh engine (`backend/app/services/token_refresh.py` — `refresh_oauth_token`, `check_token_expiration`, `TokenRefreshServiceV2`) to evaluate and persist the health state after each refresh.

Done when: classification is a pure, unit-testable function of timestamps; the service compiles and is registered for CC use only.

**2.2 — Wire health-state persistence into the identity token refresh flow**
Update the identity refresh path (`backend/app/services/token_refresh.py`, called from `backend/app/services/agents/identity_service.py` — `AgentIdentityService`) to set `token_health_state` and `last_token_refresh_outcome` (and capture `refresh_token_expires_at` from the provider response) on every refresh attempt.

Done when: a refresh (success or failure) leaves the identity's health fields correct; existing refresh behaviour and `TokenRefreshLog` audit rows are unchanged in structure.

**2.3 — Wire health-state persistence into the MCP session OAuth refresh flow**
Update `backend/app/services/mcp/oauth_refresh.py` (`OAuthRefreshService.refresh_access_token`, `check_and_refresh_if_needed`) to set the new `McpSession` health fields and route session refresh audit rows through `TokenRefreshLog` with `mcp_session_id` set.

Done when: session refreshes update health state and outcome; audit rows carry exactly one of `agent_identity_id` / `mcp_session_id`.

**2.4 — Add unit tests for the Token Health Service**
Tests in `backend/tests/` covering: healthy, expiring (boundary at exactly 7 days), expired, unknown (missing timestamps), tenant scoping, and refresh-outcome propagation for both entity kinds.

Done when: `pytest backend/tests` passes with the new tests; edge cases at the 7-day boundary covered.

## Phase 3 — Control Center APIs

**3.1 — Token Health Dashboard API (counts, details, refresh/re-auth triggers)**
New endpoints (extend `backend/app/api/v1/dashboard.py` or add a router) returning, per category (agent identities / MCP sessions): expired count, expiring count, and itemized details (name, state, remediation deep-link target). Include trigger endpoints for identity refresh and MCP session re-auth initiation. All JWT-authenticated, permission-checked, tenant-scoped, consistent with `DashboardMetricsService` (`backend/app/services/dashboard_metrics_service.py`) patterns including the "Permission Denied" placeholder behavior.

Done when: the API returns correct counts/details for seeded data; unauthenticated and cross-tenant requests fail closed.

**3.2 — Execution Preflight internal API**
New internal endpoint (under `backend/app/api/v1/internal/`) that, given an agent type and execution context, resolves every token the run will use — the agent type's identity/MCP sessions plus all associated subagents' — and returns PROCEED / PROCEED+WARN / BLOCKED with per-target messages. Consumed only via signed internal calls; fails closed (401) without valid `X-Internal-Tenant-*` headers.

Done when: the endpoint classifies correctly including subagent tokens; requests without signed tenant headers are rejected with 401.

**3.3 — Topology enrichment of container token health**
Deliver per-container token health (computed via the Token Health Service; no new DB readers) through the itemized `GET /dashboard/token-health` payload. The zoned topology is composed client-side (no CC topology endpoint for the panel), so `PanelTopologyCanvas` consumes the enriched dashboard data via `useTokenHealth` and derives per-container badge state.

Done when: the dashboard token-health payload carries the per-container token health states consumed by the topology canvas.

**3.4 — Permission/resource-type registration and API tests**
If `require_permission()` guards any new endpoint, register resource types in BOTH `backend/app/core/resource_types.py` (manifest + `MODULE_GROUPS`) and `frontend/src/constants/resourceTypes.ts` — otherwise all users including wildcard admins get 403. Add API tests for all new endpoints.

Done when: new endpoints are reachable by permitted admins (no spurious 403); tests pass.

## Phase 4 — Communication Hub Agent Gateway Preflight Gate

**4.1 — Call the preflight API from the Agent Gateway execution path**
At the Communication Hub execution-start endpoint `POST /internal/agent/execute` (`backend/app/communication_hub/api/internal/agent_execute.py`), call the CC preflight endpoint via `enforce_execution_preflight` from `backend/app/services/gateway/preflight_gate.py`, using `internal_httpx_client` from `backend/app/core/internal_http.py` (signed `X-Internal-Tenant-*` headers; never a raw httpx client; CH never signs — forward-only receiver per convention). Note: `GatewayLifecycleHandler` (`backend/app/services/gateway/lifecycle_handler.py`) runs in Control Center and is not the enforcement point.

Done when: every execution start performs the preflight call; no raw httpx clients introduced.

**4.2 — Enforce block/warn outcomes and surface user-facing messages**
BLOCKED ⇒ do not start the execution and return a clear message naming the identity/session to refresh. PROCEED+WARN ⇒ start the execution with an expiring-soon notice. PROCEED ⇒ unchanged behavior. No token material crosses the CH/AR boundary — agents receive only the outcome.

Done when: expired tokens block with an actionable message; expiring tokens warn without blocking; agent payloads contain no token data.

**4.3 — Gateway unit tests for the preflight gate**
Tests covering: block path, warn path, proceed path, preflight endpoint unreachable (fail closed), and message content.

Done when: tests in `backend/tests/` pass for all paths.

## Phase 5 — Frontend: Dashboard & Remediation Routing

**5.1 — Token health API client and typed models**
Add typed API client functions and TypeScript interfaces/enums (e.g. `TokenHealthState`) under `frontend/src/api/` (or `frontend/src/services/`) and `frontend/src/types/`. Strong typing throughout.

Done when: typed client functions exist and compile with no `any`.

**5.2 — Dashboard token-health cards**
On `frontend/src/pages/DashboardPage.tsx`, add token health cards for agent identities and MCP sessions using existing card components (`frontend/src/components/dashboard/StatCard.tsx`, `TimeSensitiveCard.tsx`), showing expired and expiring-within-7-days counts separately, with permission-checked visibility ("Permission Denied" placeholder, not 403 errors). All text via i18next `t()`.

Done when: both cards render correct counts from the API; permission-denied shows the placeholder; no hardcoded strings.

**5.3 — Click-through remediation routing**
Clicking an expired/expiring indicator navigates to `frontend/src/pages/agents/AgentIdentityListPage.tsx` (identity remediation) or `frontend/src/pages/mcp/McpSessionManager.tsx` / `McpHubPage.tsx` (session re-auth), highlighting the affected item where feasible.

Done when: every warning is clickable and lands on the page where refresh/re-auth can be performed.

**5.4 — Frontend unit tests for dashboard cards and routing**
Vitest tests in `frontend/src/__tests__/` covering card rendering, count display, permission-denied placeholder, and navigation targets.

Done when: `npx vitest run` passes including the new tests.

## Phase 6 — Frontend: Topology Badges

**6.1 — Derive per-container token health in the unified topology canvas**
In `frontend/src/components/agents/panel/PanelTopologyCanvas.tsx` (the single canonical topology view, per the Unified Agent Topology rule), consume the enriched topology data and derive per-container token health from bound identity and MCP session states. Keep all fitting in viewBox units per `frontend/src/components/agents/topologyTextFit.ts` constraints.

Done when: containers carry a computed warning/error/none token-health derived state without breaking the canvas contract (dialog preview via `frontend/src/components/agents/agentTypeToDraftComposition.ts` still works).

**6.2 — Render warning/error badges on containers**
Render badges through `frontend/src/components/agents/TopologyDiagramRenderer.tsx`: warning for expiring-within-7-days, error for expired, nothing for healthy. Text via i18next.

Done when: badges render for both states in both embedding contexts (management panel and details dialog preview).

**6.3 — Topology badge unit tests**
Vitest tests for badge presence/absence per state, in `frontend/src/__tests__/` (extend the existing `PanelTopologyCanvas.test.tsx` patterns, mocking `TopologyDiagramRenderer` as the existing tests do).

Done when: tests pass.

## Phase 7 — End-to-End Verification & Docs

**7.1 — End-to-end verification of the full flow**
Restart backend services via `./scripts/restart-backend.sh` (macOS). Verify: dashboard cards show seeded expired/expiring data; click-through reaches remediation pages; an execution using an expired token is blocked with a named message and a `TokenHealthCheck` audit row; an expiring token warns and proceeds; refreshing clears the warning automatically; topology badges reflect state. Check `backend/logs/control-center.log`, `agent-runtime.log`, `communication-hub.log` for errors.

Done when: every PRD acceptance criterion is demonstrably met in a running environment.

**7.2 — Update `docs/master/` documentation**
Apply the updates listed in `architecture.md` §6 (token-refresh, identity, mcp-hub, communication-hub, agent-runtime, agent-lifecycle, dashboard, system-overview) and `data-model.md` §5 (identity, mcp-hub, security entities, overview). Keep module docs reference-based — no schema code.

Done when: all listed master docs are updated consistently with the shipped implementation.

## Completion Checklist

- [ ] Alembic migration generated, reviewed, and applied (`alembic upgrade head`) before backend testing
- [ ] `TokenHealthCheck` audit rows are written for every preflight check, including blocked executions
- [ ] Dashboard shows separate expired / expiring (≤7 days) counts for agent identities and MCP sessions
- [ ] Every dashboard warning deep-links to the identity or MCP session remediation page
- [ ] Execution preflight covers the agent and all associated subagents; expired blocks, expiring warns
- [ ] Topology containers show warning (expiring) and error (expired) badges in both embedding contexts
- [ ] All new CC internal endpoints fail closed without signed `X-Internal-Tenant-*` headers
- [ ] Only Control Center accesses the database; CH/AR use `internal_httpx_client` exclusively for internal calls
- [ ] Agents never receive or hold identity tokens
- [ ] Warnings disappear automatically after refresh/re-auth
- [ ] All UI text uses i18next `t()`; strong typing on frontend and backend
- [ ] Resource types registered in both `backend/app/core/resource_types.py` and `frontend/src/constants/resourceTypes.ts` (if new permission-guarded endpoints were added)
- [ ] Backend tests (`backend/tests/`) and frontend tests (Vitest) all pass
- [ ] `docs/master/` updates from architecture.md §6 and data-model.md §5 completed
