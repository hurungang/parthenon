# Test Plan: Service Segregation Security Audit

Created by: Tester Agent  
Date: 2026-05-22  
Status: Implemented for scoped automation update (backend/frontend/e2e)

## 1. Test Strategy

This plan validates that service segregation is enforced end to end across UI, Communication Hub, Control Center, Agent Runtime, and database boundaries, with deny-by-default controls for internal APIs.

Primary strategy:
- Validate policy boundaries from docs/config.yaml top-priority rules: agents execute only in Agent Runtime, only Control Center accesses database directly, and Agent Runtime never receives sensitive identity data.
- Validate caller-scoped Control Center allowlists independently for Agent Runtime and Communication Hub.
- Validate deny-by-default behavior for all non-allowlisted internal endpoints.
- Validate remediation of documented security gaps: missing internal auth dependency, coarse service-certificate authorization, fail-open revocation behavior, endpoint contract drift, and insecure fallback transport behavior.

Test layers:
- Backend tests in backend/tests/ for authorization dependencies, middleware behavior, allowlist enforcement, and denial audit events.
- Frontend tests in frontend/src/__tests__/ for boundary-safe API usage patterns and client behavior that must not bypass service boundaries.
- E2E tests in e2e/tests/ for full-path behavior across UI to Communication Hub to Agent Runtime and Control Center with both positive and negative flows.
- MCP demo tests in mcp-demo-app/tests/ for contract expectations at integration boundaries where applicable.

Execution approach:
- Run all test layers with emphasis on backend integration and e2e boundary tests for segregation assertions.
- Prefer real-backend variants for critical denial-path validation and contract checks to ensure remediations are effective in operational conditions.
- Capture and review denial evidence (status codes, structured deny events, and caller identity context) as audit artifacts.

## 2. Coverage Areas

1. Service Boundary Segregation
- Confirm UI communicates through API and WebSocket only.
- Confirm Communication Hub and Agent Runtime do not introduce direct database access paths.
- Confirm Control Center remains the sole service with database ownership and direct persistence access.

2. Caller-Scoped Control Center Allowlists
- Validate Agent Runtime allowlist permits only runtime-essential internal endpoints.
- Validate Communication Hub allowlist permits only hub-essential internal endpoints.
- Validate endpoint partitioning between Agent Runtime and Communication Hub blocks cross-scope access.

3. Deny-by-Default Enforcement
- Validate all internal endpoints not on a caller allowlist are denied.
- Validate unknown caller types, missing caller identity, and certificate-type mismatches are denied.
- Validate deny decisions occur before handler execution.

4. Internal Endpoint Hardening
- Validate internal system-tools endpoints require service-certificate dependency.
- Validate JWT bypass on internal paths does not result in unauthenticated access.

5. Certificate and Revocation Enforcement
- Validate revocation endpoint contract alignment using revoked/{serial_number}.
- Validate fail-closed behavior when revocation status cannot be validated.
- Validate revoked or unverified certificates cannot be used to access protected internal endpoints.

6. Security Gap Remediation Verification
- Validate closure of critical unauthorized internal access risk on system-tools routes.
- Validate closure of privilege overlap risk between Communication Hub and Agent Runtime.
- Validate closure of fail-open boundary bypass risk under revocation service outage or error.
- Validate closure of endpoint/path mismatch risk between internal clients and Control Center.

7. Auditability and Compliance Evidence
- Validate blocked calls produce structured deny events with caller type, endpoint, method, reason, and timestamp.
- Validate repeat deny patterns can be attributed to caller identity for audit review.

## 3. Critical Scenarios (WHEN/THEN)

Automated in current implementation scope:

1. Agent Runtime calls allowlisted runtime endpoint
- WHEN Agent Runtime calls an endpoint in the Agent Runtime allowlist with valid service identity.
- THEN Control Center permits the request and returns success for that endpoint.

2. Agent Runtime calls Communication Hub-only endpoint
- WHEN Agent Runtime calls an endpoint only allowlisted for Communication Hub.
- THEN Control Center denies the request with explicit authorization failure and records a structured deny event.

3. Communication Hub calls allowlisted hub endpoint
- WHEN Communication Hub calls an endpoint in the Communication Hub allowlist with valid service identity.
- THEN Control Center permits the request and returns success for that endpoint.

4. Communication Hub calls Agent Runtime-only endpoint
- WHEN Communication Hub calls an endpoint only allowlisted for Agent Runtime.
- THEN Control Center denies the request and records a structured deny event.

5. Internal endpoint not in any allowlist
- WHEN any internal caller invokes a non-allowlisted internal endpoint.
- THEN request is denied by default prior to handler execution and deny evidence is emitted.

6. Unknown or malformed caller identity
- WHEN internal request has unknown caller type, missing caller identity, or certificate-type mismatch.
- THEN request is denied and logged with reason code indicating identity/certificate policy failure.

7. System-tools endpoint without valid service certificate
- WHEN request targets internal system-tools endpoint and lacks valid service-certificate authentication.
- THEN request is denied regardless of JWT bypass behavior on internal path prefixes.

8. Revocation service unreachable
- WHEN certificate revocation status cannot be validated for an internal request.
- THEN request is denied under fail-closed policy and an auditable deny event is recorded.

9. Revocation endpoint contract correctness
- WHEN Communication Hub checks revocation status.
- THEN it uses the supported revoked/{serial_number} contract and no obsolete revocation-status path is used.

10. Database ownership boundary
- WHEN regression checks evaluate service imports and access patterns.
- THEN non-Control-Center service trees do not introduce direct ORM session or database access usage.

Planned/manual follow-up scenarios (not automated in this scope):
- Revoked certificate used for internal call should be validated in a certificate-lifecycle integration path with explicit revoked cert fixtures.
- Runtime sensitive-data boundary should be validated by asserting no identity token material appears in runtime context payloads.

## 4. Edge Cases and Risks

- Route-template normalization risk: allowlist checks may mismatch dynamic path templates versus concrete path instances and accidentally allow or deny incorrectly.
- Middleware ordering risk: deny-by-default checks can be bypassed if dependencies are not consistently attached before handler logic.
- Environment drift risk: local development bypass flags may leak into non-development profiles and weaken certificate enforcement.
- Contract drift risk: caller clients may regress to obsolete endpoint paths, causing silent policy gaps or noisy authorization failures.
- Audit gap risk: denies may occur but without structured event fields required by compliance reviewers.
- Availability versus security tradeoff risk: fail-closed revocation policy may increase temporary denials during dependent-service outages; operations runbooks must be validated.
- Cross-service privilege creep risk: new internal endpoints can be added without explicit allowlist mapping if governance checks are missing.

## 5. Acceptance Criteria Checklist

- [ ] Service segregation model is validated with explicit allowed and disallowed interactions among UI, Communication Hub, Control Center, Agent Runtime, and Database.
- [ ] Agents are verified to execute only in Agent Runtime service paths.
- [x] Only Control Center is verified to hold direct database access in code paths and test assertions.
- [ ] Sensitive identity data is verified to remain unavailable to Agent Runtime responses and context payloads.
- [x] Agent Runtime-specific Control Center allowlist is enforced and tested with allow and deny outcomes.
- [x] Communication Hub-specific Control Center allowlist is enforced and tested with allow and deny outcomes.
- [x] Deny-by-default is verified for all non-allowlisted internal endpoints.
- [x] Internal system-tools endpoints are verified to require service-certificate authentication.
- [x] Certificate revocation checks are fail-closed in non-development operation.
- [x] Communication Hub revocation client path is aligned to revoked/{serial_number}.
- [x] Structured deny events are emitted with caller type, endpoint, method, reason, and timestamp.
- [ ] Security gaps are traceable to remediation validation outcomes with severity-aware evidence.

## 6. Test File References

The following references use configured source.tests roots from docs/config.yaml.

Created in this change:
- backend/tests/integration/test_internal_allowlist_partitioning.py
- backend/tests/integration/test_internal_deny_audit_events.py
- backend/tests/integration/test_internal_revocation_fail_closed.py
- frontend/src/__tests__/service-segregation-security-audit.test.ts
- e2e/tests/service-segregation-security-audit.spec.ts

Updated in this change:
- backend/tests/integration/test_data_clients.py
- backend/tests/integration/test_database_isolation.py
- backend/tests/unit/test_control_center_comm_hub_client.py

## 7. Implementation Snapshot (Current Request Scope)

Implemented in this request scope:
- backend/tests/integration/test_internal_allowlist_partitioning.py
- backend/tests/integration/test_internal_deny_audit_events.py
- backend/tests/integration/test_internal_revocation_fail_closed.py
- backend/tests/integration/test_data_clients.py
- backend/tests/integration/test_database_isolation.py
- backend/tests/unit/test_control_center_comm_hub_client.py
- frontend/src/__tests__/service-segregation-security-audit.test.ts
- e2e/tests/service-segregation-security-audit.spec.ts

Execution status is tracked in this request output with per-layer pass/fail totals.
