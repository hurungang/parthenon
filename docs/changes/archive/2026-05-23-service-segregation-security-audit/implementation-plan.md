## Overview
This implementation plan closes the service-segregation gaps identified in the current codebase while preserving existing runtime behavior. The work is organized to first establish explicit caller allowlists and deny-by-default controls in Control Center, then align Communication Hub and Agent Runtime call paths to those controls. Final phases validate enforcement with integration tests and lock in operational evidence required for security auditability.

## Task Checklist

### Phase 1 — Baseline Hardening Scope
- [x] 1.1 — Confirm audited boundary matrix and endpoint inventory
- [x] 1.2 — Classify current gaps by severity and ownership
- [x] 1.3 — Freeze target allowlist contract for Agent Runtime and Communication Hub

### Phase 2 — Control Center Policy Enforcement
- [x] 2.1 — Add caller identity extraction and normalization for internal requests
- [x] 2.2 — Implement Agent Runtime Control Center API allowlist
- [x] 2.3 — Implement Communication Hub Control Center API allowlist
- [x] 2.4 — Enforce deny-by-default for non-allowlisted internal endpoints
- [x] 2.5 — Add structured deny event logging for blocked internal calls

### Phase 3 — Service Client Alignment
- [x] 3.1 — Align Communication Hub revocation-check path with Control Center endpoint contract
- [x] 3.2 — Require certificate-authenticated calls from Communication Hub to internal system-tool endpoints
- [x] 3.3 — Remove or gate insecure development fallbacks for internal service calls
- [x] 3.4 — Resolve service-boundary inconsistencies in Agent Runtime and Communication Hub internal control flow

### Phase 4 — Verification and Security Tests
- [x] 4.1 — Add Control Center allowlist unit tests for Agent Runtime caller profile
- [x] 4.2 — Add Control Center allowlist unit tests for Communication Hub caller profile
- [x] 4.3 — Add integration tests for deny-by-default and blocked-path evidence
- [x] 4.4 — Add regression tests proving Agent Runtime and Communication Hub have no direct database access

### Phase 5 — Documentation and Operational Readiness
- [x] 5.1 — Update architecture and security master docs with final allowlists and denied paths
- [x] 5.2 — Publish operational runbook updates for cert rotation and deny-event monitoring
- [x] 5.3 — Produce implementation evidence bundle for security review sign-off

## Phase 1 — Baseline Hardening Scope

### 1.1 — Confirm audited boundary matrix and endpoint inventory
Description: Reconfirm all active interaction paths among UI, Communication Hub, Control Center, Agent Runtime, and database; include internal endpoint-level mapping and caller identity assumptions.
Done when:
- The interaction matrix explicitly lists allowed and disallowed paths for all five domains.
- Internal Control Center endpoints are cataloged with current callers and authentication assumptions.
- The inventory is reviewed against docs/config.yaml top_priority_rules with no unresolved ambiguity.

### 1.2 — Classify current gaps by severity and ownership
Description: Convert audit findings into prioritized gap records with technical root cause, impact, and owning service team.
Done when:
- Each gap has severity, exploitability context, and business impact.
- Ownership is assigned to a concrete component boundary (Control Center, Communication Hub, Agent Runtime, UI, or platform operations).
- Critical and high gaps are marked as mandatory for Phase 2 or Phase 3 remediation.

### 1.3 — Freeze target allowlist contract for Agent Runtime and Communication Hub
Description: Define the exact endpoint contract that each caller may invoke on Control Center, with no shared implicit permissions.
Done when:
- Agent Runtime and Communication Hub allowlists are approved as separate caller contracts.
- Any endpoint not listed in a caller contract is marked denied by default.
- The contract is ready for direct implementation in Control Center policy middleware/dependencies.

## Phase 2 — Control Center Policy Enforcement

### 2.1 — Add caller identity extraction and normalization for internal requests
Description: Standardize internal caller identity derivation from validated service certificates and expose a normalized caller type for policy checks.
Done when:
- Internal request handling yields a stable caller identifier for policy evaluation.
- Caller identity is available consistently across all internal routers.
- Missing or malformed caller identity fails closed.

### 2.2 — Implement Agent Runtime Control Center API allowlist
Description: Enforce an explicit endpoint allowlist for Agent Runtime internal calls, limited to runtime-essential Control Center endpoints.
Done when:
- Agent Runtime requests are evaluated against a dedicated allowlist.
- Allowed runtime paths succeed without behavior regression.
- Any Agent Runtime request to non-allowlisted internal paths is blocked with explicit denial reason.

### 2.3 — Implement Communication Hub Control Center API allowlist
Description: Enforce an explicit endpoint allowlist for Communication Hub internal calls, limited to broker/gateway-essential Control Center endpoints.
Done when:
- Communication Hub requests are evaluated against a dedicated allowlist.
- Allowed communication-hub paths succeed without behavior regression.
- Any Communication Hub request to non-allowlisted internal paths is blocked with explicit denial reason.

### 2.4 — Enforce deny-by-default for non-allowlisted internal endpoints
Description: Add a single default-deny decision point for all internal Control Center routes not explicitly allowlisted by caller type.
Done when:
- Default policy for internal routes is deny unless explicitly allowed.
- No implicit fallback paths remain for internal callers.
- Denial behavior is deterministic and testable.

### 2.5 — Add structured deny event logging for blocked internal calls
Description: Emit consistent audit events for blocked calls including caller type, endpoint, method, reason, and correlation metadata.
Done when:
- Blocked calls generate structured logs suitable for security reporting.
- Events can be filtered by caller type and endpoint.
- Logging does not leak sensitive identity material.

## Phase 3 — Service Client Alignment

### 3.1 — Align Communication Hub revocation-check path with Control Center endpoint contract
Description: Correct revocation-check path usage so Communication Hub and Agent Runtime call the same supported Control Center revocation endpoint.
Done when:
- Revocation checks use a valid Control Center route in all callers.
- Any obsolete or mismatched revocation path references are removed.
- Revocation behavior is validated in integration tests.

### 3.2 — Require certificate-authenticated calls from Communication Hub to internal system-tool endpoints
Description: Ensure Communication Hub always presents service identity when calling internal system-tool routes in Control Center.
Done when:
- Internal system-tool routes require authenticated internal caller identity.
- Communication Hub system-tool calls include certificate-derived caller identity in both HTTP and HTTPS modes supported by project conventions.
- Unauthorized direct access to internal system-tool endpoints is blocked.

### 3.3 — Remove or gate insecure development fallbacks for internal service calls
Description: Eliminate fail-open internal-call patterns or gate them behind explicit, non-default development flags with warnings.
Done when:
- Internal service clients no longer silently downgrade to unauthenticated behavior in normal environments.
- Any remaining development-only fallback requires explicit opt-in and emits high-visibility warnings.
- Security tests verify fail-closed behavior for certificate and revocation validation failures.

### 3.4 — Resolve service-boundary inconsistencies in Agent Runtime and Communication Hub internal control flow
Description: Align boundary assumptions, comments, and endpoint semantics so runtime control flow consistently reflects the approved architecture.
Done when:
- Caller expectations in middleware, route docs, and implementation are consistent.
- Execution trigger flow and conversation flow use clearly defined service boundaries.
- No contradictory caller-trust assumptions remain in internal service code.

## Phase 4 — Verification and Security Tests

### 4.1 — Add Control Center allowlist unit tests for Agent Runtime caller profile
Description: Add focused tests that validate Agent Runtime can access only approved internal endpoints.
Done when:
- Positive tests cover all Agent Runtime allowlisted endpoints.
- Negative tests confirm denied access to non-allowlisted internal endpoints.
- Tests assert both HTTP status and denial reason shape.

### 4.2 — Add Control Center allowlist unit tests for Communication Hub caller profile
Description: Add focused tests that validate Communication Hub can access only approved internal endpoints.
Done when:
- Positive tests cover all Communication Hub allowlisted endpoints.
- Negative tests confirm denied access to non-allowlisted internal endpoints.
- Tests assert both HTTP status and denial reason shape.

### 4.3 — Add integration tests for deny-by-default and blocked-path evidence
Description: Add end-to-end internal-call tests proving deny-by-default is active and denial events are observable.
Done when:
- Integration tests execute representative blocked calls from both caller types.
- Structured deny events are verifiable in logs/telemetry.
- No blocked-path test passes due to mocked bypasses.

### 4.4 — Add regression tests proving Agent Runtime and Communication Hub have no direct database access
Description: Add checks that preserve the architecture rule that only Control Center accesses the database.
Done when:
- Regression tests confirm no database session imports or ORM usage in Agent Runtime and Communication Hub modules.
- CI fails when direct database access patterns are introduced in those services.
- Test output is linked to segregation controls in security review documentation.

## Phase 5 — Documentation and Operational Readiness

### 5.1 — Update architecture and security master docs with final allowlists and denied paths
Description: Update architecture/security documentation to reflect implemented caller allowlists and deny-by-default controls.
Done when:
- Master architecture docs contain caller-specific internal API allowlists.
- Security model docs capture denied-path behavior and evidence expectations.
- Documentation language matches implemented endpoint contracts.

### 5.2 — Publish operational runbook updates for cert rotation and deny-event monitoring
Description: Update runbooks for operational handling of certificate lifecycle failures and internal API denial spikes.
Done when:
- Runbooks define monitoring signals, alerts, and response actions for deny events.
- Certificate renewal/revocation troubleshooting steps are explicit.
- Operations can validate segregation control health without code inspection.

### 5.3 — Produce implementation evidence bundle for security review sign-off
Description: Prepare final evidence artifacts for security and platform leadership approval.
Done when:
- Evidence includes test results, endpoint contract matrix, and deny-event samples.
- Critical and high-severity gap closures are traceable to concrete changes.
- Security review sign-off criteria are met and documented.

## Completion Checklist
- [x] Agent Runtime and Communication Hub have separate, enforced Control Center allowlists
- [x] Control Center internal APIs run with deny-by-default policy
- [x] Unauthorized internal endpoint attempts are blocked and logged with structured evidence
- [x] Internal system-tool and MCP proxy paths require authenticated service callers
- [x] Revocation checks are consistent across Agent Runtime and Communication Hub clients
- [x] Service boundary behavior matches docs/config.yaml top-priority rules
- [x] Unit, integration, and regression tests pass for segregation controls
- [x] Documentation and runbooks are updated for audit and operations readiness
