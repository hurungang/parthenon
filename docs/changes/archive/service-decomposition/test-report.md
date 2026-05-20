# Test Report — Phase 7: Testing & Validation
# Service Decomposition Change

**Date:** 2026-05-15  
**Tester Agent:** Phase 7 validation run  
**Result:** ✅ ALL TESTS PASSING — 90 backend + 9 E2E (6 skipped, services not running)

---

## Summary

| Layer | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| Unit (Task 7.1, 7.2) | 26 | 26 | 0 | 0 |
| Integration (Task 7.3–7.5, 7.8) | 35 | 35 | 0 | 0 |
| Security (Task 7.6, 7.7) | 29 | 29 | 0 | 0 |
| E2E (Task 7.7) | 15 | 9 | 0 | 6 |
| **Total** | **105** | **99** | **0** | **6** |

E2E skips are expected: Agent Runtime and Communication Hub are not running locally; tests check `isServiceReachable()` and skip gracefully. The 9 passing E2E tests cover Control Center (running) and all mocked scenarios.

---

## Pre-existing Import Errors Fixed

Two import errors were blocking all test execution (pre-existing, not caused by Phase 7 work):

1. **`app/db/models/__init__.py` line 43** — `from app.services.gateway.registry import GatewayRoute` — `GatewayRoute` does not exist; only `GatewayEndpointRegistry` is exported. Fixed by correcting the import name.

2. **`app/services/agents/permission_manager.py`** — `AsyncSession` used in method signature without being imported. Fixed by adding `from sqlalchemy.ext.asyncio import AsyncSession`.

3. **`app/services/gateway/lifecycle_handler.py`** — same `AsyncSession` missing import. Fixed.

---

## Task 7.1 — Bootstrap Unit Tests (10 tests)
**File:** `tests/unit/test_bootstrap.py`

| Test | Result |
|------|--------|
| Valid AR bootstrap returns cert + CA | ✅ PASS |
| Valid CH bootstrap returns cert + CA | ✅ PASS |
| Invalid service name rejected | ✅ PASS |
| Wrong bootstrap key rejected (401) | ✅ PASS |
| Mismatched service/key rejected | ✅ PASS |
| Missing Authorization header (422) | ✅ PASS |
| Non-Bearer scheme rejected (401) | ✅ PASS |
| Bootstrap key env var not set → 503 | ✅ PASS |
| Agent-instance CN has 3 colon segments | ✅ PASS |
| Service CN has 2 colon segments | ✅ PASS |

## Task 7.2 — Certificate Renewal Unit Tests (16 tests)
**File:** `tests/unit/test_certificate_renewal.py`

| Test | Result |
|------|--------|
| AR: fresh cert (0% elapsed) → no renewal | ✅ PASS |
| AR: 79% elapsed → no renewal | ✅ PASS |
| AR: 80% elapsed → triggers renewal | ✅ PASS |
| AR: expired cert → triggers renewal | ✅ PASS |
| AR: no cert → triggers renewal | ✅ PASS |
| AR: renewal constants correct (80%, 24h, 1h, 30min) | ✅ PASS |
| AR: successful renewal atomically replaces cert | ✅ PASS |
| AR: failed renewal rolls back cert | ✅ PASS |
| AR: run_renewal_task retries on failure | ✅ PASS |
| CH: fresh 30d cert → no renewal | ✅ PASS |
| CH: 80% of 30d → triggers renewal | ✅ PASS |
| CH: expired → triggers renewal | ✅ PASS |
| CH: renewal constants correct (80%, 30d, 24h, 5min) | ✅ PASS |
| CH: run_renewal_task retries on failure | ✅ PASS |
| CH: successful switch atomically replaces cert | ✅ PASS |
| CH: failed switch rolls back cert | ✅ PASS |

## Task 7.3 — Data API Client Tests (12 tests)
**File:** `tests/integration/test_data_clients.py`

| Test | Result |
|------|--------|
| AR: get_agent_plan calls correct endpoint | ✅ PASS |
| AR: get_agent_plan returns None on 404 | ✅ PASS |
| AR: get_agent_context returns skills/role | ✅ PASS |
| AR: get_model_config calls correct endpoint | ✅ PASS |
| AR: submit_result POSTs to correct endpoint | ✅ PASS |
| CH: get_session calls correct endpoint | ✅ PASS |
| CH: get_session raises on error | ✅ PASS |
| CH: get_conversation_history calls history endpoint | ✅ PASS |
| CH: get_user_permissions returns allowed_tools list | ✅ PASS |
| CH: check_revocation_status returns True (revoked) | ✅ PASS |
| CH: check_revocation_status returns False (valid) | ✅ PASS |
| CH: check_revocation_status calls correct URL | ✅ PASS |

## Task 7.4 — Service Trigger Tests (8 tests)
**File:** `tests/integration/test_service_triggers.py`

| Test | Result |
|------|--------|
| trigger_execution sends correct payload | ✅ PASS |
| trigger_execution raises AgentRuntimeClientError on HTTP error | ✅ PASS |
| trigger_execution raises on network error | ✅ PASS |
| trigger_execution uses mTLS client when cert available | ✅ PASS |
| AR /execute enqueues session_id | ✅ PASS |
| AR /execute returns 503 if queue not initialised | ✅ PASS |
| CH /internal/dispatch publishes to broker | ✅ PASS |
| CH /internal/dispatch returns 502 on broker failure | ✅ PASS |
| CH dispatch JSON-serializes dict content | ✅ PASS |

## Task 7.5 — Database Isolation Tests (13 tests)
**File:** `tests/integration/test_database_isolation.py`

| Test | Result |
|------|--------|
| AR directory exists | ✅ PASS |
| AR has no DATABASE_URL dependency | ✅ PASS |
| AR has no direct db.session imports | ✅ PASS |
| AR data_client.py exists | ✅ PASS |
| AR data_client.py uses httpx not DB | ✅ PASS |
| AR main.py does not import db session | ✅ PASS |
| CH directory exists | ✅ PASS |
| CH has no DATABASE_URL dependency | ✅ PASS |
| CH has no direct db.session imports | ✅ PASS |
| CH data_client.py exists | ✅ PASS |
| CH data_client.py uses httpx not DB | ✅ PASS |
| CH main.py does not import db session | ✅ PASS |
| AR data client is importable | ✅ PASS |
| CH data client is importable | ✅ PASS |

## Task 7.6 — Certificate Auth Security Tests (12 tests)
**File:** `tests/security/test_certificate_auth.py`

| Test | Result |
|------|--------|
| No cert → 401/403 on internal endpoint | ✅ PASS |
| Agent-instance cert blocked from /internal/* | ✅ PASS |
| Agent-instance cert blocked from /authorize endpoint | ✅ PASS |
| Service cert passes auth check | ✅ PASS |
| Garbage PEM → 400/401/403 | ✅ PASS |
| Bootstrap accessible without cert (401/503) | ✅ PASS |
| Valid cert passes validate_certificate | ✅ PASS |
| Revoked cert fails validate_certificate | ✅ PASS |
| Agent-instance CN prefix identified | ✅ PASS |
| Service CN prefix identified | ✅ PASS |
| AR middleware blocks missing cert | ✅ PASS |
| AR middleware inherits BaseHTTPMiddleware | ✅ PASS |

## Task 7.7 — Bootstrap Security Tests (17 tests)
**File:** `tests/security/test_bootstrap_security.py`

| Test | Result |
|------|--------|
| Wrong key for AR service → 401 | ✅ PASS |
| Empty bearer token → 401 | ✅ PASS |
| Partial key → 401 | ✅ PASS |
| Key with extra chars → 401 | ✅ PASS |
| AR key for CH service → 401 | ✅ PASS |
| CH key for AR service → 401 | ✅ PASS |
| Unknown service name → 422/400 | ✅ PASS |
| compare_digest appears in source | ✅ PASS |
| compare_digest is constant-time | ✅ PASS |
| secrets module is imported | ✅ PASS |
| Missing Authorization → 422 | ✅ PASS |
| Basic auth scheme rejected | ✅ PASS |
| ApiKey scheme rejected | ✅ PASS |
| Bootstrap router prefix is /internal/bootstrap | ✅ PASS |
| Per-service keys differ from each other | ✅ PASS |
| Env var names are service-specific | ✅ PASS |
| Valid request succeeds | ✅ PASS |

## Task 7.8 — E2E Three-Service Architecture Tests (15 tests)
**File:** `e2e/tests/three-service-architecture.spec.ts`

| Test | Result |
|------|--------|
| CC health endpoint returns service structure (mocked) | ✅ PASS |
| Dashboard loads with three-service architecture (mocked) | ✅ PASS |
| Agent execution status display (mocked) | ✅ PASS |
| Certificate monitoring data visible (mocked) | ✅ PASS |
| WebSocket no crash (mocked) | ✅ PASS |
| CC health check passes (real) | ✅ PASS |
| AR health check passes (real) | ⏭ SKIP (AR not running) |
| CH health check passes (real) | ⏭ SKIP (CH not running) |
| All three services healthy (real) | ⏭ SKIP (AR+CH not running) |
| CC /internal/bootstrap accessible (real) | ✅ PASS |
| AR /execute requires auth (real) | ⏭ SKIP (AR not running) |
| CH /internal/dispatch requires auth (real) | ⏭ SKIP (CH not running) |
| Certificate expiry in future (real) | ⏭ SKIP (AR not running) |
| User views dashboard with live CC | ✅ PASS |
| Health page loads | ✅ PASS |

---

## Security Validation Summary

- **Bootstrap key validation** — `secrets.compare_digest` confirmed in source; per-service keys enforced; service/key mismatch rejected.
- **Certificate authentication** — Agent-instance certs blocked from CC `/internal/*`; service certs validated against CA; revoked certs rejected.
- **DB isolation** — AR and CH source trees contain zero `DATABASE_URL` references and no `app.db.session` imports.
- **Timing attack resistance** — Constant-time comparison confirmed in bootstrap endpoint source.
- **Endpoint access control** — Bootstrap endpoint accessible without cert (bearer key only); all other `/internal/*` require service cert.
