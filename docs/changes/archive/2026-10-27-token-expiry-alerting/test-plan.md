# Test Plan — Token Expiry Alerting

## Test Strategy

Token Expiry Alerting spans Control Center (health computation, dashboard API, internal preflight API, audit persistence), Communication Hub (execution preflight gate), frontend (dashboard cards, remediation routing, topology badges), and the database (new `token_health` tables/columns plus the nullable `mcp_session_id` on `TokenRefreshLog`). Testing is layered accordingly:

1. **Backend unit tests** (backend/tests/) — the health classification function is deterministic and pure; cover every boundary of the 7-day threshold, both entity kinds, and the `unknown` state. No service mocks beyond the session boundary.
2. **Backend integration tests** (backend/tests/) — exercise the Token Health Service, dashboard API, preflight API, and refresh-engine extensions against the real database. **These tests MUST verify the schema changes took effect** (new tables/columns exist, migration applied), not just behavior. Migration application is verified via `alembic current` / `alembic upgrade head` before the suite runs.
3. **Frontend component tests** (frontend/src/__tests__/) — dashboard card rendering, permission-checked visibility, click-through routing, topology badge derivation and rendering states.
4. **E2E tests** (e2e/tests/) — full-stack flows: dashboard visibility → click-through remediation → warnings cleared; execution blocking/warning behavior through the Gateway; tenant isolation. **At least one E2E variant must run against a real backend stack** (started via `scripts/restart-backend.sh`), not only mocked services, to prove migration + preflight + gateway integration end to end.
5. **MCP demo app tests** (mcp-demo-app/tests/) — regression: existing MCP tool-call flows are unaffected by session health fields.

Key invariants validated at every layer:
- Control Center is the sole owner of token health state; agents never receive or hold tokens.
- Internal preflight endpoint fails closed (401) without valid signed `X-Internal-Tenant-*` headers.
- All health data and warnings are tenant-scoped.
- `TokenHealthCheck` rows are insert-only audit records.

## Coverage Areas

### 1. Token Health Classification (backend unit + integration)
- Classification boundaries for agent identities: `token_expires_at`, `refresh_token_expires_at`.
- Classification boundaries for MCP sessions: `oauth_expires_at`, `oauth_refresh_expires_at`.
- States: `healthy`, `expiring` (within 7 days), `expired`, `unknown` (missing timestamps).
- Interaction with refresh outcome (`last_token_refresh_outcome`) and entity status (active sessions only for MCP).
- Read-time recomputation overrides stale persisted `token_health_state`.
- 7-day threshold constant consistency.

### 2. Token Refresh Engine extensions (backend integration)
- Identity refresh persists `refresh_token_expires_at`, `last_token_refresh_outcome`, `token_health_state`.
- MCP OAuth refresh persists `McpSession` health fields and writes `TokenRefreshLog` rows with `mcp_session_id`.
- Failed refresh attempts persist failure outcome and do not corrupt health state.

### 3. Dashboard Token Health API (backend integration)
- `/api/v1/dashboard/token-health`: counts and itemized details per category with deep-link targets.
- JWT auth required; tenant scoping of results; permission-checked visibility (403 / permission-denied placeholder behavior).
- Refresh trigger endpoint (`/agents/identities/{id}/refresh`) and re-auth trigger (`/mcp/sessions/{id}/re-auth`).

### 4. Execution Preflight API (backend integration)
- PROCEED / PROCEED+WARN / BLOCKED resolution including full subagent composition (static composition + `AgentRunRelationship` runtime trees).
- Per-target messages naming the affected identity/session.
- Fail-closed 401 without signed internal headers.
- `TokenHealthCheck` audit rows written for every evaluation, including blocked runs (append-only).

### 5. Agent Gateway Preflight Gate (backend integration, CH side)
- BLOCKED prevents execution start for agent AND all associated subagents; user-facing message names the identity/session.
- PROCEED+WARN allows execution while surfacing the warning.
- Gate uses `internal_httpx_client` only; no token material forwarded; CH holds no token state.
- PermissionDenied / CC-unavailable behavior fails closed.

### 6. Dashboard Cards + Remediation Routing (frontend)
- Separate, clearly labeled expired vs expiring indicators for agent identities and MCP sessions.
- Click-through navigates to `AgentIdentityListPage` / `McpSessionManager` respectively.
- Permission-denied placeholder per `StatCard` pattern; i18n keys used (no hardcoded strings).
- Warnings disappear after refresh/re-auth (data refetch).

### 7. Topology Badges (frontend)
- Warning badge for containers with identity/MCP session ≤7 days of expiry; error badge for expired.
- Badge rendering in `PanelTopologyCanvas` / `TopologyDiagramRenderer` stays in viewBox units (no font-scale regressions).
- `agentTypeToDraftComposition` keeps working with enriched health data; agent types without health data render unchanged.

### 8. DB Migration & Schema Verification (backend integration + real-backend E2E)
- Migration up/down applies cleanly; `alembic current` matches head.
- New columns exist: `AgentIdentity.refresh_token_expires_at`, `last_token_refresh_outcome`, `token_health_state`; `McpSession.last_token_refresh_at`, `last_token_refresh_outcome`, `token_health_state`; `TokenRefreshLog.mcp_session_id` (nullable).
- `TokenHealthCheck` table created, tenant-scoped, with target_kind/target_id/health_state/check_outcome/message.
- ORM round-trips on all new fields; index usage on expiry-range predicates.

### 9. Tenant Isolation & Security (all layers)
- Token health data, warnings, and audit records are tenant-scoped end to end.
- Agents never observe token material — only blocked/warn/proceed outcomes.
- Resource types registered in both backend manifest and frontend `RESOURCE_TYPE_MANIFEST` (no wildcard-admin 403).

## Critical Scenarios (WHEN/THEN)

**Classification**
- WHEN an agent identity's `refresh_token_expires_at` is more than 7 days in the future, THEN health state is `healthy`.
- WHEN an identity's refresh token expires in exactly 7 days (boundary), THEN state is `expiring`.
- WHEN an identity's refresh token expires in 6 days 23 hours, THEN state is `expiring`.
- WHEN an identity's refresh token expiry is in the past, THEN state is `expired`.
- WHEN required timestamps are missing, THEN state is `unknown` (never crashes, never misclassified as healthy).
- WHEN an MCP session's `oauth_expires_at`/`oauth_refresh_expires_at` crosses each boundary, THEN the same healthy/expiring/expired classification applies.
- WHEN an MCP session is inactive, THEN it is excluded from health aggregation.
- WHEN `token_health_state` is persisted stale but timestamps indicate a different state, THEN read-time recomputation returns the timestamp-derived state.

**Dashboard**
- WHEN a tenant has 2 expired identities and 3 expiring identities, THEN the dashboard card shows 2 and 3 in separate, labeled indicators.
- WHEN a user clicks an expired-identity warning, THEN they land on the agent identity page where refresh is possible.
- WHEN a user clicks an MCP session warning, THEN they land on the MCP session manager where re-auth is possible.
- WHEN a user lacks permission on the underlying data domain, THEN the card shows the permission-denied placeholder instead of a 403 error.
- WHEN a token is refreshed/re-authed successfully, THEN the warning disappears from the dashboard after reload/refetch.
- WHEN tenant B has expiring tokens and the viewer belongs to tenant A, THEN no tenant B items appear in counts or details.

**Execution Preflight**
- WHEN an execution starts and the agent's identity token is expired, THEN execution is BLOCKED with a message naming that identity, and no session is created.
- WHEN an execution starts and a subagent's identity token is expired, THEN the whole execution (parent included) is BLOCKED naming the subagent's identity.
- WHEN an execution's bound MCP session token is expired, THEN execution is BLOCKED naming the session.
- WHEN any required token is expiring (≤7 days) but none expired, THEN execution PROCEEDS with a warning naming the target.
- WHEN all tokens are healthy, THEN execution PROCEEDS with no warnings.
- WHEN a preflight evaluation runs (passed or blocked), THEN a `TokenHealthCheck` audit row is written with the resolved health state, outcome, and message.
- WHEN the preflight internal endpoint is called without valid signed `X-Internal-Tenant-*` headers, THEN it returns 401 (fail closed).
- WHEN the same expired token would be used again, THEN after refresh/re-auth the preflight returns PROCEED and the execution succeeds.
- WHEN a runtime subagent already exists in `AgentRunRelationship`, THEN preflight resolves its tokens via the execution tree.

**Topology**
- WHEN a container's identity/MCP session expires within 7 days, THEN a warning badge is rendered on that container.
- WHEN a container's identity/MCP session is expired, THEN an error badge is rendered on that container.
- WHEN all tokens are healthy or unknown, THEN no warning/error badge is rendered.
- WHEN the topology data has no health enrichment (older payload), THEN the canvas renders without badges and without errors.

**Remediation round-trip (E2E)**
- WHEN an administrator triggers identity refresh from the dashboard deep-link, THEN the entity's health state flips to `healthy` and the dashboard/topology/preflight surfaces all reflect it without residual warnings.

## Edge Cases

- Expiry exactly at `now` (boundary: expired vs expiring classification; documented behavior asserted consistently for identities and sessions).
- Timezone/UTC handling: timestamps stored UTC, compared UTC; DST-boundary local times don't shift classification.
- Very large expiry values (far-future tokens) — no overflow, classified healthy.
- Identity with `token_expires_at` healthy but refresh token expired — classified by the binding that matters for refresh (assert per spec).
- Concurrent refresh + preflight on the same identity — no race producing contradictory audit rows.
- Deeply nested subagent compositions (3+ levels) — full token set resolved, blocking propagates to the root.
- Subagent referencing a deleted/missing identity — preflight fails closed rather than proceeding silently.
- Duplicate MCP sessions bound to the same identity — each evaluated independently; one expired session blocks.
- `TokenHealthCheck` accumulation — insert-only table remains queryable; no unique constraint violations on repeated checks.
- `mcp_session_id` on `TokenRefreshLog` remains NULL for identity refresh rows (backward compatibility).
- Empty tenant (no identities/sessions) — dashboard returns zero counts, no errors.
- Clock skew: system clock behind token `not-before` — treated as healthy, not negative-expiry crash.
- Topology with mixed health states across containers — badges map to the correct containers (no off-by-one in mapping).
- i18n: all new card labels, badges, and block messages render via `t()` and are present in locale files.

## Acceptance Criteria Checklist

- [ ] Dashboard shows separate, clearly labeled "expired" and "about to expire (within 7 days)" indicators for agent identities AND for MCP sessions.
- [ ] Each dashboard warning is clickable and navigates to the agent identity page or MCP session page where refresh/re-auth is possible.
- [ ] Before execution, all tokens the execution will use — including associated subagents' — are checked.
- [ ] Expired token ⇒ execution BLOCKED with clear message naming the affected identity/session; execution proceeds only after refresh/re-auth.
- [ ] Expiring (≤7 days) token ⇒ warning surfaced, execution proceeds.
- [ ] No token failure is first discoverable at execution time — every expired token in use is surfaced pre-run.
- [ ] Topology diagram: warning state for containers within 7 days of expiry; error state for expired.
- [ ] Token health checks respect tenant isolation — users see/alert only their tenant's tokens (verified cross-tenant negative test).
- [ ] Agents never receive or hold tokens; CH forwards only block/warn/proceed outcomes.
- [ ] Warnings disappear automatically once tokens are refreshed/re-authenticated.
- [ ] `TokenHealthCheck` audit records written for every preflight evaluation including blocked runs; append-only.
- [ ] DB migration verified applied in backend integration tests (schema/columns/tables asserted) and in a real-backend E2E variant.
- [ ] Internal preflight endpoint fails closed (401) without signed internal headers.
- [ ] New resource types registered in both backend and frontend manifests (wildcard admin gets no 403).
- [ ] All new UI text uses i18next `t()`; new wire states typed as TS enums mirroring backend enums.
- [ ] Existing MCP demo app tool-call flows regress-clean.

## Test File References

Paths per `docs/config.yaml` `source.tests` (backend/tests/, frontend/src/__tests__/, e2e/tests/, mcp-demo-app/tests/):

| Area | Location |
|---|---|
| Health classification unit tests (identities + sessions, boundaries, unknown) | `backend/tests/services/test_token_health_service.py` |
| Refresh engine / OAuth refresh persistence tests | `backend/tests/services/test_token_health_service.py` (TestPersistence, TestSessionClassification) |
| Dashboard token-health API + remediation trigger endpoint tests | `backend/tests/api/v1/test_token_health_api.py` |
| Preflight API tests (outcomes, subagent trees, fail-closed 401, audit rows, tenant stamp, remediation round-trip) | `backend/tests/api/v1/test_token_health_api.py` + `backend/tests/services/test_token_health_service.py` (TestPreflight) |
| Migration / schema verification tests (new columns, `TokenHealthCheck` table, `mcp_session_id`, ORM round-trips, migration files) | `backend/tests/db/test_token_health_schema.py` |
| Gateway preflight gate tests (CH-side block/warn/proceed, no token forwarding, fail-closed on unreachable CC) | `backend/tests/communication_hub/test_gateway_preflight_gate.py` |
| Tenant isolation tests (cross-tenant audit stamping, signed-header enforcement / fail-closed 401) | `backend/tests/api/v1/test_token_health_api.py` (headerless-401 + tenant-stamp tests) |
| Dashboard cards: counts, labels, permission placeholder, click-through routing, refetch-clears-warnings | `frontend/src/__tests__/TokenHealthDashboard.test.tsx` |
| Topology badge derivation + rendering (warning/error, viewBox regression) | `frontend/src/__tests__/PanelTopologyTokenHealth.test.tsx` + `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` |
| Token health API client typing / enum mirroring | `frontend/src/types/tokenHealth.ts` (typed via `frontend/src/__tests__/TokenHealthDashboard.test.tsx` and `PanelTopologyTokenHealth.test.tsx` usage) |
| E2E (mocked backend): dashboard alerts → click-through remediation → warnings cleared | `e2e/tests/token-expiry-dashboard-remediation.spec.ts` |
| E2E (mocked backend): execution BLOCKED with named identity incl. subagent; expiring warns and proceeds | `e2e/tests/token-expiry-execution-preflight.spec.ts` |
| E2E (mocked backend): topology warning/error badges on the live topology view | `e2e/tests/token-expiry-topology-badges.spec.ts` |
| Regression: MCP tool calls unaffected by session health fields | `mcp-demo-app/tests/` — existing MCP session regression suite (no session-health coupling introduced; `mcp_session_id` on `TokenRefreshLog` is nullable) |

### Execution results (2026-10-27)

| Layer | Suites | Result |
|---|---|---|
| Backend (pytest) | token health service 23 + gateway gate 8 + token-health API 6 + schema/migration 10 | **47 passed** |
| Frontend (Vitest) | TokenHealthDashboard 5 + PanelTopologyTokenHealth 6 (full frontend suite: 1739 passed / 1 pre-existing unrelated `ConversationDialog` failure) | **pass** |
| E2E (Playwright, mocked backend) | dashboard remediation 6 + execution preflight 2 + topology badges 4 | **12 passed** |
