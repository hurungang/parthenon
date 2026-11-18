# Fix Log: token-expiry-alerting

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20261116-214714

**Created:** 2026-11-16T21:47:14Z
**Status:** Resolved
**Issue:** Dashboard token-health tiles stay red/orange even when nothing is expiring, and dashboard tiles are statically ordered with no visual priority for actionable items.

### Observed Behavior

- The agent-identity token tile always uses the `red` variant and the MCP-session tile always uses `orange`, regardless of whether `expired_count` and `expiring_count` are both zero.
- All dashboard tiles render in a fixed hard-coded order across the operational, token-health, and time-sensitive sections.
- Nothing visually distinguishes a tile that requires action (expired tokens, pending interventions, breaches, failed executions, pending access requests) from purely informational tiles.

### Expected Behavior

- A token-health tile shows a green tone when both `expired_count` and `expiring_count` are zero; it escalates to warning/orange when anything is expiring within 7 days and to error/red when anything is expired.
- Tiles requiring action are sorted to the top (within their section and by section-level severity), with a distinct action-highlight background and border so they stand out.
- Informational tiles keep the existing neutral styling and relative order.

### Analysis

- **Affected components:**
  - `frontend/src/pages/DashboardPage.tsx`
  - `frontend/src/components/dashboard/StatCard.tsx`
  - `frontend/src/components/dashboard/TimeSensitiveCard.tsx`
  - `frontend/src/i18n/locales/en.json` (action-required badge label)
- **Root cause hypothesis:** card tone is a static prop chosen at authoring time, and the dashboard grids are hard-coded rather than derived from a severity-ranked card list.
- **Documentation impact:** change `tech-spec.md` Code Reference Map and the merged master dashboard feature doc.

### Fix Tasks

- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Expected Changes

- **Code files:**
  - `frontend/src/pages/DashboardPage.tsx`
  - `frontend/src/components/dashboard/StatCard.tsx`
  - `frontend/src/components/dashboard/TimeSensitiveCard.tsx`
  - `frontend/src/i18n/locales/en.json`
- **Test files:**
  - `frontend/src/__tests__/pages/DashboardPage.test.tsx`
  - `frontend/src/__tests__/components/dashboard/StatCard.test.tsx`
  - `frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx`
  - `frontend/src/__tests__/TokenHealthDashboard.test.tsx` (regression)
- **Docs:**
  - `docs/changes/archive/2026-10-27-token-expiry-alerting/tech-spec.md`
  - `docs/master/product/features/dashboard-metrics.md`
  - `docs/master/product/features/token-expiry-alerting.md`

### Implementation Details

<!-- Will be filled in as fix progresses -->

### Test Cases Added/Modified

**Status: 22 new reproduction tests added across 4 files — 20 fail against current production code; 2 pass as guards (permission-denied suppression, which trivially holds while no badge exists at all). No existing test was modified in intent; `DashboardPage.test.tsx` mock plumbing was made payload-controllable without changing existing assertions.**

Frontend component contract — `frontend/src/__tests__/components/dashboard/StatCard.test.tsx` (new describe `StatCard — status tone and action-required highlight`):

| Test | Expected | Current result |
| --- | --- | --- |
| `renders the action-required badge and data-action-required="true" when action is required` | root Card `data-action-required="true"` + `dashboard.actionRequired` text | FAILED (`expected null to be 'true'`) |
| `defaults to data-action-required="false" and renders no badge` | root Card `data-action-required="false"`, no badge | FAILED (`expected null to be 'false'`) |
| `exposes data-status-tone="neutral" when no status tone is supplied` | `neutral` | FAILED (`expected null to be 'neutral'`) |
| `maps statusTone="success" / "warning" / "error"` (3 tests) | matching `data-status-tone` | FAILED ×3 (attribute absent) |
| `does NOT render the action-required badge in the permission-denied state` | access-denied placeholder only | passed (guard) |

Frontend component contract — `frontend/src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx` (new describe `TimeSensitiveCard — status tone and action-required highlight`):

- Same 6 contract tests for `statusTone` / `actionRequired` / default `neutral` / default `false` — FAILED (attribute absent).
- `supports the action-required contract on the dual variant` (completed/failed card + `statusTone="error"`) — FAILED (`expected null to be 'error'`).
- `does NOT render the action-required badge in the permission-denied state` — passed (guard).

Frontend page layout — `frontend/src/__tests__/pages/DashboardPage.test.tsx` (new describe `DashboardPage — severity-ranked tiles (FIX-20261116-214714)`; `dashboardApi` + new `tokenHealthApi` mocks are now payload-controllable, existing 6 assertions unchanged):

| Test | Expected | Current result |
| --- | --- | --- |
| `renders all three section wrappers and every card wrapper with a severity` | `dashboard-section-{operational,token,time}` + 14 `dashboard-card-<key>` wrappers, each with `data-severity` ∈ critical/warning/normal | FAILED (no `dashboard-card-token-identities` wrapper) |
| `healthy token payload … green token tiles with no action badge` | both token root Cards `data-status-tone="success"`, severity `normal`, no badge anywhere | FAILED (wrapper missing) |
| `expiring-only token payload renders warning tone + warning severity` | tone `warning`, severity `warning`, badge shown; MCP tile stays `success` | FAILED (wrapper missing) |
| `expired token payload renders error tone + critical severity + action badge` | tone `error`, severity `critical`, `data-action-required="true"`, badge visible | FAILED (wrapper missing) |
| `sorts sections by highest card severity (critical token section first)` | section DOM order `token → time → operational` | FAILED (wrapper missing) |
| `sorts critical/warning cards above normal cards inside their section` | token: identities before MCP; operational: pending-interventions & permission-requests before agent-types; time: notification-delivery before guardrail-breaches | FAILED (wrapper missing) |
| `places every action-required wrapper before normal wrappers within each section` | per section, no actionable card after a normal card | FAILED (wrapper missing) |
| `does not render the action-required badge when the tile is permission-denied` | access-denied placeholder, no badge | FAILED (wrapper missing) |

Regression — `frontend/src/__tests__/TokenHealthDashboard.test.tsx` (one test appended; existing 5 untouched):

- `renders green token tiles and no action badge when nothing is expired or expiring` — healthy payload (0 expired / 0 expiring) must yield `data-status-tone="success"` and `data-action-required="false"` on both token Cards and no `dashboard.actionRequired` text. FAILED (`expected null to be 'success'`).

Failure summary (`npx vitest run <4 files>`): **46 tests — 24 passed / 22 failed**; the 22 pre-existing/guard tests pass, all 20 new contract assertions fail with "attribute absent" (`expected null to be …`) or "wrapper missing" (`Unable to find … [data-testid="dashboard-card-…"]`) — i.e. the missing props/data attributes/badge/sorting, not a test-environment error.

### Code Changes

**`frontend/src/components/dashboard/StatCard.tsx`**

- New optional props: `statusTone?: CardStatusTone` (`'success' | 'warning' | 'error'`, exported as `CardStatusTone`) and `actionRequired?: boolean`.
- Root MUI `Card` now always exposes `data-status-tone={statusTone ?? 'neutral'}` and `data-action-required={actionRequired ? 'true' : 'false'}`.
- Action highlight (only when `actionRequired`, not permission-denied): `error` → `#FEF2F2` bg / `#FECACA` border, `warning` → `#FFFBEB` / `#FDE68A`, `success` → `#F0FDF4` / `#BBF7D0`. `success` on its own never sets `actionRequired`.
- Permission-denied visuals keep precedence (dashed `#EF4444` border, `#FFF5F5` bg, blurred content, overlay) and always suppress the badge.
- New exported `ActionRequiredBadge` pill (i18n `dashboard.actionRequired`) rendered inside the header row, top-right after the label, so it never overlaps the icon or label; hidden while loading or permission-denied.

**`frontend/src/components/dashboard/TimeSensitiveCard.tsx`**

- Same `statusTone` / `actionRequired` props, `data-status-tone` / `data-action-required` attributes and `ActionRequiredBadge` (both single and dual variants).
- `error`/`warning` tones tint the card (`#FEF2F2` / `#FFFBEB`) with matching border colour and thicken the left accent bar from 3px to 4px; `success` renders the green tint without a badge. Permission-denied precedence unchanged.
- Local `TONE_STYLES` map (mirrors `StatCard`) to avoid exporting non-component values from a component module.

**`frontend/src/pages/DashboardPage.tsx`**

- Replaced the three hard-coded `Grid` blocks with derived, severity-ranked card lists. Added `DashboardSeverity = 'critical' | 'warning' | 'normal'`, `DashboardCardItem` / `DashboardSectionItem` types and local helpers `severityFromCount`, `isActionable`, `actionableTone`, `sortBySeverity` (stable, critical → warning → normal), `highestSeverity`.
- Section wrappers `data-testid="dashboard-section-{operational,token,time}"`; each card wrapper `data-testid="dashboard-card-<key>"` plus `data-severity` and `data-action-required`.
- Severity rules: token identity/session `critical` when `expired_count > 0`, `warning` when `expiring_count > 0`, else `normal`; `pending-interventions` / `permission-requests` / `guardrail-breaches` / `posture-breaches` `critical` when their count > 0; `agent-executions` `critical` when `failed > 0`; `notification-delivery` `warning` when `notification_failed > 0`; all remaining operational tiles `normal`.
- Cards sorted inside each section (stable) and the three sections sorted by their highest card severity with the stable operational → token → time tie-break, so a critical token section renders first.
- `critical` cards get `statusTone="error"`, `warning` cards `statusTone="warning"`, both `actionRequired`; token-health tiles with `normal` severity get `statusTone="success"` and no `actionRequired`.
- Token `colorVariant` is now derived from severity: identity green/amber/red, MCP session green/orange/red for normal/warning/critical.
- All existing labels, icons, values, sub-breakdowns, navigation targets, permission flags and loading states preserved; `DateRangePicker` renders with the time-sensitive section and headings keep the existing overline style.
- `frontend/src/i18n/locales/en.json`: additive `dashboard.actionRequired = "Action required"` (existing uncommitted content untouched, JSON validated).

### Documentation Updates

**Updated by:** conductor agent
**Timestamp:** 2026-11-16T22:35:00Z

- `docs/changes/archive/2026-10-27-token-expiry-alerting/tech-spec.md` — Code Reference Map entries for `DashboardPage`, `StatCard`, and `TimeSensitiveCard` now describe severity ranking, status tones, the action badge, and the green healthy token state.
- `docs/master/product/features/dashboard-metrics.md` — new "Action-First Tile Ordering" subsection and green/warning/error token-tile behavior.
- `docs/master/product/features/token-expiry-alerting.md` — healthy tiles return to green after remediation; actionable tiles sort first with the action highlight.

**Document review:** es-document-reviewer APPROVED with no edits. It confirmed both product docs are behavior-level, concise, and consistent with the merged token-refresh semantics. It noted a pre-existing, out-of-scope staleness in `dashboard-metrics.md` (card counts still say 7 operational / 3 time-sensitive tiles and omit Permission Requests + Notification Delivery); no change made here.

### Verification Results

**Verified 2026-11-16** (macOS, Vitest 4.1.6, Playwright 1.59.1).

**Targeted dashboard/component suites: PASS (46/46)**

`cd frontend && npx vitest run src/__tests__/components/dashboard/StatCard.test.tsx src/__tests__/components/dashboard/TimeSensitiveCard.test.tsx src/__tests__/pages/DashboardPage.test.tsx src/__tests__/TokenHealthDashboard.test.tsx`
→ **46 passed, 0 failed** (pre-fix: 24 passed / 22 failed). All new contract/sorting/tone tests now pass; no existing assertion was weakened.

**Token/identity/MCP + dashboard regression:** covered green by the full run below (none of the failing files touch these surfaces). The developer's focused regression run was 46 passed / 8 skipped.

**Full frontend Vitest suite: 2139 passed / 5 failed / 18 skipped (2162 tests)**

The 5 failures are **unrelated order/load flakes**, none in dashboard/token/identity/MCP code:
- `src/__tests__/AgentManagementPage.test.tsx` — post-save navigation test.
- `src/__tests__/AgentRuntimeMapCanvas.test.tsx` — delegated-child promotion test.
- `src/__tests__/DecisionToolForm.test.tsx` — 3 mapping/data-type tests.

Re-running exactly those three files in isolation: **133 passed / 0 failed**, confirming environment/order flakiness rather than a regression from this fix.

**Token E2E (Playwright): 10/10 passed**

`cd e2e && npx playwright test tests/token-expiry-dashboard-remediation.spec.ts tests/token-expiry-topology-badges.spec.ts --workers=1`
→ 10 passed (45.1s), including click-through remediation, refetch-clears-warnings, permission-denied placeholder, and all topology badge states. A fresh `build:e2e` was served via `preview` on :4173 (no config change).

**Type safety:** `cd frontend && npx tsc --noEmit` → exit 0, zero diagnostics.

**Loading/error hardening:** the green healthy tone is applied only after token-health data has loaded (`!isLoading && !isError && data`); loading or failed fetches stay neutral instead of showing a reassuring green tile.

---

## FIX-20261116-061805

**Created:** 2026-11-16T06:18:05Z
**Status:** Resolved
**Issue:** Token health status is driven by the current access-token expiry instead of the refresh-token expiry, so the dashboard, agent identity list, and MCP session list report "expired" for tokens that can still be refreshed.

### Observed Behavior

- `POST`/`GET` surfaces classify an agent identity or MCP session as `expired` as soon as its **access token** (`AgentIdentity.token_expires_at`, `McpSession.oauth_expires_at`) passes, even when the stored **refresh token** is still valid and Control Center can renew the access token automatically.
- The dashboard "expired" counts, the agent identity list token chip, and the MCP session token chip all read the access-token timestamp.
- Several token issuance/refresh paths do not persist `refresh_token_expires_at` (identity OAuth code exchange, manual identity refresh, background sweep), so a refresh-token-based status would have no timestamp to read.

### Expected Behavior

- When a refresh token exists, token health is classified **only** by the refresh token's expiry (`refresh_token_expires_at` / `oauth_refresh_expires_at`). An expired access token is not an error state while it can be refreshed.
- When no refresh token exists (no refresh mechanism available), classification falls back to the access-token expiry so the user is still warned before a hard failure.
- The dashboard, agent identity list, and MCP session list show the **refresh token** status and expiry, and label it explicitly as such.
- Every token issuance/refresh path persists the refresh token expiry reported by the identity provider, so status stays aligned after refresh.

### Analysis

- **Affected components:**
  - `backend/app/services/token_health.py` — `classify_identity_health`, `classify_session_health`, `compute_identity_state`, `compute_session_state`
  - `backend/app/services/agents/identity_service.py` — OAuth code exchange, manual refresh, re-auth callback
  - `backend/app/services/agents/token_refresh_service.py` — background proactive refresh
  - `backend/app/services/token_refresh.py` — on-demand refresh (already captures refresh expiry)
  - `backend/app/schemas/agents.py` — `AgentIdentityRead` (missing `refresh_token_expires_at` / `token_status`)
  - `frontend/src/types/index.ts` — `AgentIdentity` type
  - `frontend/src/pages/agents/AgentIdentityListPage.tsx`
  - `frontend/src/pages/mcp/McpSessionManager.tsx`
  - `frontend/src/pages/DashboardPage.tsx` + `frontend/src/i18n/locales/en.json`
- **Root cause hypothesis:** Health classification took the earliest of access-token and refresh-token expiry, and each UI surface independently bound its chip to the access-token timestamp. Refresh-token expiry was treated as a secondary signal instead of the authoritative one.
- **Documentation impact:** PRD acceptance criteria, spec-change delta, data-model notes, tech-spec classification rules and Code Reference Map, test plan scenarios, and the merged master docs for token refresh / identity / MCP hub / dashboard.

### Fix Tasks

- [x] **Reproduce** — Create test case that demonstrates the issue
- [x] **Fix** — Implement the fix in code
- [x] **Verify** — Run all tests (backend, frontend, E2E)
- [x] **Document** — Update affected documentation

### Expected Changes

- **Code files:**
  - `backend/app/services/token_health.py`
  - `backend/app/services/agents/identity_service.py`
  - `backend/app/services/agents/token_refresh_service.py`
  - `backend/app/schemas/agents.py`
  - `frontend/src/types/index.ts`
  - `frontend/src/pages/agents/AgentIdentityListPage.tsx`
  - `frontend/src/pages/mcp/McpSessionManager.tsx`
  - `frontend/src/pages/DashboardPage.tsx`
  - `frontend/src/i18n/locales/en.json`
- **Test files:**
  - `backend/tests/services/test_token_health_service.py`
  - `backend/tests/api/v1/test_token_health_api.py`
  - `frontend/src/__tests__/AgentIdentityListPage.test.tsx`
  - `frontend/src/__tests__/McpSessionManager.test.tsx`
- **Docs:**
  - `docs/changes/archive/2026-10-27-token-expiry-alerting/prd.md`
  - `docs/changes/archive/2026-10-27-token-expiry-alerting/spec-change.md`
  - `docs/changes/archive/2026-10-27-token-expiry-alerting/data-model.md`
  - `docs/changes/archive/2026-10-27-token-expiry-alerting/tech-spec.md`
  - `docs/changes/archive/2026-10-27-token-expiry-alerting/test-plan.md`
  - `docs/master/product/features/token-expiry-alerting.md`
  - `docs/master/product/features/agent-identity.md`
  - `docs/master/product/features/mcp-hub.md`
  - `docs/master/architecture/modules/token-refresh.md`
  - `docs/master/architecture/modules/identity.md`
  - `docs/master/architecture/modules/dashboard.md`
  - `docs/master/technology/modules/agents/tech-spec.md`
  - `docs/master/technology/modules/mcp-hub/tech-spec.md`
  - `docs/master/technology/modules/control-center/tech-spec.md`
  - `docs/master/qa/test-plans/token-expiry-alerting-test-plan.md`

### Implementation Details

<!-- Will be filled in as fix progresses -->

### Test Cases Added/Modified

**Status: 14 new reproduction tests added — 10 fail against current production code (6 backend, 4 frontend). Existing tests that encode the old semantics were left unchanged.**

Backend — `backend/tests/services/test_token_health_service.py` (new classes appended; no existing test touched):

| Test | Expected (2A) | Current result |
| --- | --- | --- |
| `TestRefreshTokenDrivenIdentityClassification::test_expired_access_token_with_valid_refresh_token_is_healthy` | `healthy` | FAILED (`expired`) |
| `TestRefreshTokenDrivenIdentityClassification::test_access_token_expiring_within_window_and_far_future_refresh_is_healthy` | `healthy` | FAILED (`expiring`) |
| `TestRefreshTokenDrivenIdentityClassification::test_far_future_access_token_with_refresh_token_expiring_is_expiring` | `expiring` | passed (guard) |
| `TestRefreshTokenDrivenIdentityClassification::test_far_future_access_token_with_expired_refresh_token_is_expired` | `expired` | passed (guard) |
| `TestRefreshTokenDrivenIdentityClassification::test_no_refresh_token_expired_access_token_falls_back_to_expired` | `expired` (fallback) | passed (guard) |
| `TestRefreshTokenDrivenSessionClassification::test_expired_access_token_with_valid_refresh_token_is_healthy` | `healthy` | FAILED (`expired`) |
| `TestRefreshTokenDrivenSessionClassification::test_access_token_expiring_within_window_and_far_future_refresh_is_healthy` | `healthy` | FAILED (`expiring`) |
| `TestRefreshTokenDrivenSessionClassification::test_far_future_access_token_with_refresh_token_expiring_is_expiring` | `expiring` | passed (guard) |
| `TestSessionRequiresReauthClassification::test_session_with_requires_reauth_is_expired` | `expired` | FAILED (returns `healthy`) |

Failure excerpt:
```
assert <TokenHealthState.expired: 'expired'> == <TokenHealthState.healthy: 'healthy'>
assert <TokenHealthState.expiring: 'expiring'> == <TokenHealthState.healthy: 'healthy'>
assert compute_session_state(session, now=NOW) == TokenHealthState.expired
E  assert <TokenHealthState.healthy: 'healthy'> == <TokenHealthState.expired: 'expired'>
```

Backend — `backend/tests/api/v1/test_token_health_api.py`:

- `test_token_health_counts_refresh_valid_targets_as_not_expired` — seeds a genuinely expired control identity, an identity with expired access token + valid refresh token, and an OAuth session with expired access token + valid refresh token; asserts the refreshable rows are not itemized/counted as `expired`/`expiring` and the control row still is. FAILED:
  `AssertionError: identity with an expired access token but a valid refresh token was counted as expired: ['control-expired-identity', 'refresh-ok-identity']`

Frontend — `frontend/src/__tests__/AgentIdentityListPage.test.tsx` (new describe `AgentIdentityListPage — token status reflects refresh token`):

- `renders a NON-expired token status when access token expired but refresh token is valid` — FAILED (`Expected true to be false`: chip label still matches /expired/i because `token_expires_at` drives the chip).
- `renders EXPIRED token status when refresh token expired even though access token is still valid` — FAILED (`Expected false to be true`: chip still renders "Token Active" from a future `token_expires_at`).

Frontend — `frontend/src/__tests__/McpSessionManager.test.tsx` (new describe `McpSessionManager — token status reflects OAuth refresh token`):

- `renders a valid (NOT expired) token status when access token expired but refresh token is valid` — FAILED (`expected <span> to be null`: `getTokenStatus()` renders `mcp.sessions.tokenExpired` from `oauth_expires_at`).
- `renders EXPIRED token status when OAuth refresh token is expired even though access token is valid` — FAILED (`expected null not to be null`: no error-colored token chip because `oauth_expires_at` is future).

Test data note: the frontend fixtures include `refresh_token_expires_at` on `AgentIdentity`, which is not yet on the `AgentIdentity` type — expected until the fix adds it (fixtures are untyped mocks, so no compilation break today).

E2E — `e2e/tests/token-expiry-dashboard-remediation.spec.ts`: updated the stale dashboard label selectors/strings to the renamed refresh-token copy (`Refresh Token Health`, `Expired Agent Identity Refresh Tokens`, `Expired MCP Session Refresh Tokens`, `N refresh tokens expiring within 7 days`). This was a test-data-only update required by the intentional label change; the spec's assertions (counts, click-through, refetch-clears-warnings) are unchanged. Re-run: 6/6 pass (10/10 with the topology spec).

Failure counts: backend `6 failed, 38 passed`; frontend `4 failed` (all new) / `30 passed` + `8 skipped` (all pre-existing).

### Code Changes

**Backend — classification (`backend/app/services/token_health.py`)**

- `classify_identity_health` (L57): added `has_refresh_token: bool | None = None` (inferred from `refresh_token_expires_at` when omitted). Reordered rules: failure `token_status`/outcome → `expired`; refresh token present → no known refresh expiry = `healthy`, past = `expired`, ≤7 days = `expiring`, else `healthy`; no refresh token → access-token fallback (`None` = `unknown`, past = `expired`, ≤7 days = `expiring`, else `healthy`). `TOKEN_EXPIRING_WINDOW` unchanged (7 days); function stays pure.
- `classify_session_health` (L130): added `requires_reauth: bool = False` (True → `expired`) and `has_refresh_token: bool | None = None` (inferred from `oauth_refresh_expires_at`); same refresh-first / access-token-fallback rules.
- `compute_identity_state` (L173): passes `has_refresh_token` = stored `refresh_token`/`encrypted_refresh_token` present **or** a recorded `refresh_token_expires_at` (evidence a refresh token exists).
- `compute_session_state` (L191): passes `requires_reauth=session.requires_reauth`; refresh presence inferred from `oauth_refresh_expires_at`.

**Backend — refresh/issuance paths persist refresh-token expiry + health**

- `backend/app/services/agents/identity_service.py`
  - New helpers `_parse_refresh_token_expires_at` (L48; `0`/absent ⇒ `None` = no known expiry, so an existing known expiry is never lost) and `_mark_refresh_success` (L69; sets `token_status=active`, `last_token_refresh_at`, then lazily imports and calls `persist_identity_health_state(..., refresh_outcome=TokenRefreshOutcome.success)`).
  - `complete_oauth_flow` (L384): captures `refresh_expires_in` → `refresh_token_expires_at` (L443) and persists success health (L454).
  - `create_identity_from_oauth` (L465): captures refresh expiry (L519); both update and create branches persist success health (L565, L587).
  - `refresh_token` (L667): on non-200 sets `token_status=refresh_failed` and persists `TokenRefreshOutcome.failure` health before raising (existing clear-refresh-token/suspend behaviour kept); on success captures refresh expiry (L732) and persists success health (L763).
- `backend/app/services/agents/token_refresh_service.py` (`refresh_token`, L156): same `refresh_expires_in` capture (L233) plus success health persistence; failure persists `token_status=refresh_failed` + `TokenRefreshOutcome.failure` health. Existing flush/commit behaviour unchanged.
- `backend/app/services/token_refresh.py`: unchanged — already captures `refresh_expires_in` (treats `0`/absent as no known expiry, leaving the stored value intact) and persists health; its tests still pass.
- `backend/app/schemas/agents.py`: `AgentTokenStatus` added to the model import (L18); `AgentIdentityRead` exposes `refresh_token_expires_at` and `token_status` (L342-343) in both the model fields and the `_compute_has_refresh_token` validator's returned dict.

**Frontend**

- `frontend/src/types/index.ts` (L264-265): `AgentIdentity` gains `refresh_token_expires_at: string | null` and optional `token_status?: string | null` (additive only).
- `frontend/src/pages/agents/AgentIdentityListPage.tsx`: `TOKEN_EXPIRING_WINDOW_MS` (L52); `getIdentityTokenStatus` (L212) drives the chip from `refresh_token_expires_at` when `has_refresh_token` (expired / expiring ≤7 days / active, `refresh_failed` ⇒ expired), falls back to `token_expires_at` otherwise, and shows the exact expiry in a tooltip. Column header is now "Refresh Token Status" with an explaining tooltip (L290-291). Action buttons unchanged.
- `frontend/src/pages/mcp/McpSessionManager.tsx`: `TOKEN_EXPIRING_WINDOW_MS` (L53); `getTokenStatus` (L387) uses `oauth_refresh_expires_at` when present (7-day `expiring soon` window), falls back to `oauth_expires_at`, and keeps `requires_reauth` ⇒ needs re-auth. Column header renamed with tooltip (L482-483); chip tooltip shows the exact expiry. Action-button logic unchanged.
- `frontend/src/pages/DashboardPage.tsx` + `frontend/src/i18n/locales/en.json`: token-health section/card labels and the "expiring within 7 days" sublabel now say refresh token explicitly (`dashboard.tokenHealthSection`, `tokenHealthIdentities`, `tokenHealthMcpSessions`, `expiringWithin7Days`); new chip/tooltip keys added under `agents.identities.*` and `mcp.sessions.*` (`refreshTokenStatus`, `refreshTokenStatusTooltip`, `refreshTokenExpiresTooltip`, `accessTokenExpiresTooltip`, `refreshTokenNoExpiry`, `tokenExpiringSoon`). Additive edits only — no existing keys removed.

**Tests**

- `backend/tests/services/test_token_health_service.py`: updated the old-semantics `TestIdentityClassification::test_expired_access_token` (expired access token + refresh token valid 1 day ⇒ now `expiring`, not `expired`). New reproduction classes untouched.
- `backend/tests/unit/test_agent_identity_service.py` / `backend/tests/unit/test_token_refresh_service.py`: mock identity fixtures now initialise the new health fields (`refresh_token_expires_at`, `token_status`, `last_token_refresh_*`, `token_health_state`, `encrypted_refresh_token`) to `None`.
- `frontend/src/__tests__/AgentIdentityViewDialog.test.tsx`: fixture gains `refresh_token_expires_at: null` (required by the extended `AgentIdentity` type). Reproduction frontend suites untouched.

### Documentation Updates

**Updated by:** conductor agent
**Timestamp:** 2026-11-16T07:05:00Z

Change docs (this change):
- `prd.md` — acceptance criteria and dependencies now state that refresh-token expiry is the alert signal, access-token expiry is not, and the status is explicitly labeled on identity/session surfaces.
- `spec-change.md` — new/modified capability deltas rewritten for refresh-token health, access-token fallback, and explicit refresh-token expiry display.
- `data-model.md` — `refresh_token_expires_at` / `oauth_refresh_expires_at` documented as authoritative; `requires_reauth` and no-refresh-token fallbacks documented; `refresh_expires_in` persistence noted.
- `tech-spec.md` — classification rules, component breakdown, Code Reference Map (including `AgentIdentityRead` and updated `AgentIdentityService` / identity / MCP UI entries) updated by developer + conductor.
- `test-plan.md` — coverage areas, critical scenarios, and edge cases rewritten for refresh-first classification and the access-token fallback.

Merged master docs:
- `docs/master/product/features/token-expiry-alerting.md`
- `docs/master/product/features/dashboard-metrics.md`
- `docs/master/product/features/agent-identity.md`
- `docs/master/product/features/mcp-hub.md`
- `docs/master/architecture/system-overview.md`
- `docs/master/architecture/modules/token-refresh.md`
- `docs/master/architecture/modules/identity.md`
- `docs/master/architecture/modules/dashboard.md`
- `docs/master/data-model/modules/identity/entities.md`
- `docs/master/data-model/modules/mcp-hub/entities.md`
- `docs/master/technology/modules/agents/tech-spec.md`
- `docs/master/technology/modules/mcp-hub/tech-spec.md`
- `docs/master/technology/modules/control-center/tech-spec.md`
- `docs/master/qa/test-plans/token-expiry-alerting-test-plan.md`

**Document review:** es-document-reviewer APPROVED after 4 minimal policy edits — removed a raw DB column name from product prose, removed a duplicated/renamed "Token Lifecycle States" section in `token-refresh.md` (folded its unique content into the classification section), disambiguated "expired tokens" to "expired refresh tokens" in `spec-change.md`, and replaced an implementation-plan table in `data-model.md` with a reference note. No inconsistencies remain between the change docs and the merged master docs.

### Verification Results

**Verified 2026-11-16** (macOS, `.venv` Python 3.11, Vitest 4.1.6, Playwright 1.59.1).

**Backend — targeted suites: PASS (70/70)**

`cd backend && ../.venv/bin/python -m pytest tests/services/test_token_health_service.py tests/api/v1/test_token_health_api.py tests/unit/test_agent_identity_service.py tests/unit/test_token_refresh_service.py -q`
→ **70 passed, 0 failed** in 144s (`test_token_health_service.py` 37, `test_token_health_api.py` 7, `test_agent_identity_service.py` 16, `test_token_refresh_service.py` 10).

All previously failing reproduction tests now pass:
- `TestRefreshTokenDrivenIdentityClassification` — 5/5 (incl. `test_expired_access_token_with_valid_refresh_token_is_healthy` and `test_access_token_expiring_within_window_and_far_future_refresh_is_healthy`, both failed pre-fix).
- `TestRefreshTokenDrivenSessionClassification` — 3/3 (incl. the 2 pre-fix failures).
- `TestSessionRequiresReauthClassification` — 4/4 (incl. `test_session_with_requires_reauth_is_expired`, which returned `healthy` pre-fix).
- `test_token_health_counts_refresh_valid_targets_as_not_expired` — passes (pre-fix: `AssertionError: identity with an expired access token but a valid refresh token was counted as expired`).
- Updated old-semantics test `TestIdentityClassification::test_expired_access_token` passes against the new refresh-first rule.

No backend failures observed. **The full backend suite (`pytest tests/`) is being run separately by the conductor session — no result for it is claimed here.**

**Frontend — full Vitest suite: 2118 passed / 2 failed / 18 skipped (2138 tests, 529 files, 1335s)**

`cd frontend && npx vitest run --reporter=json --outputFile=vitest_results.json`

- Token surfaces all green: `AgentIdentityListPage` 17, `McpSessionManager` 25, `TokenHealthDashboard` 5, `PanelTopologyTokenHealth` 6, `TopologyDiagramRenderer` 58, `PanelTopologyCanvas` 42, `pages/DashboardPage` 6, `AgentIdentityViewDialog` 7, `AgentIdentityDialog` 6.
- Previously failing reproduction tests now pass: `AgentIdentityListPage — token status reflects refresh token` (2/2) and `McpSessionManager — token status reflects OAuth refresh token` (2/2).
- The 2 failures are **unrelated to this fix** and both live in `src/__tests__/service-decomposition/issue-3-sop-skill-autoselect.test.tsx` (`AgentRoleDialog: SOP→Skill Auto-Selection`):
  1. `auto-checks required skill when its SOP is selected` — `Error: STACK_TRACE_ERROR` at the test body.
  2. `makes required skill checkbox disabled (read-only) when its SOP is selected` — `expect(element).toBeDisabled()`: received checkbox not disabled.
  Both the spec and `AgentRoleDialog.tsx` are unmodified vs `HEAD` and touch no token/identity/MCP code; the file **passes 4/4 when run in isolation**, so this is an order/load-dependent flake, not a regression from FIX-20261116-061805.

**E2E — Playwright token specs: 10 passed / 0 failed**

Initial verification run: 5 passed / 5 failed. All 5 failures were stale label selectors in `e2e/tests/token-expiry-dashboard-remediation.spec.ts` (the spec still asserted the pre-fix dashboard copy); product behavior and counts were correct. The spec was updated to the renamed refresh-token labels (`Refresh Token Health`, `Expired Agent Identity Refresh Tokens`, `Expired MCP Session Refresh Tokens`, `N refresh tokens expiring within 7 days`), and the suite was re-run:

`cd e2e && npx playwright test tests/token-expiry-dashboard-remediation.spec.ts tests/token-expiry-topology-badges.spec.ts --workers=1`
→ **10 passed, 0 failed** (36.6s), covering both specs including click-through remediation, refetch-clears-warnings, topology badges, and the older-payload-without-health-enrichment case.

Environment note: the config `webServer` timed out because `npm run build:e2e` needs ~2m42s; the run used a pre-built `npm run preview` server on :4173 with `reuseExistingServer` (no config change).

**Type safety — `tsc --noEmit`: PASS**

`cd frontend && npx tsc --noEmit` → exit 0, zero diagnostics (4m26s under load). No pre-existing type errors; the additive `AgentIdentity.refresh_token_expires_at`/`token_status` fields and the new i18n keys type-check cleanly.

**Summary**

| Layer | Result |
| --- | --- |
| Backend (targeted, 4 files) | 70/70 pass |
| Backend (full `pytest tests/`) | Not completed: the first run hit a pre-existing collection error (`tests/unit/test_setup_tenant_demo.py`, missing `setup` module); the re-run excluding it was interrupted by the session environment at 63% without a summary. All affected suites are covered by the 70/70 targeted run above. |
| Frontend Vitest (full) | 2118 passed / 2 unrelated flakes / 18 skipped |
| E2E (token specs) | 10/10 pass after updating the stale label selectors |
| `tsc --noEmit` | clean |

The fix is functionally verified: classification, API, schema, persistence paths, and all UI surfaces behave per the Expected Behavior, and every reproduction test that failed pre-fix now passes. The only test-side follow-up (dashboard E2E label selectors) is complete and the suite is green.

---
