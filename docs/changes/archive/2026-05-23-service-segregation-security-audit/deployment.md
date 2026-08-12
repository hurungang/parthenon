# Deployment Guide: Service Segregation Security Audit

Feature: Service Segregation Security Audit and Control Center Caller-Specific API Allowlists  
Date: 2026-05-22  
Status: Ready for deployment planning and staged rollout

## Deployment Intent
This deployment enforces two security controls across Control Center, Agent Runtime, and Communication Hub:
- Service segregation with explicit caller-specific Control Center internal API allowlists
- Deny-by-default enforcement for all non-allowlisted internal routes

The rollout preserves top-priority architecture rules:
- Agents execute only in Agent Runtime
- Only Control Center can access the database directly
- Sensitive identity material remains centralized and is not exposed to Agent Runtime execution surfaces

## New Environment Variables

### Control Center
| Variable | Required | Purpose |
| --- | --- | --- |
| INTERNAL_API_POLICY_MODE | Yes | Controls policy enforcement mode for caller-specific allowlists. Values: audit or enforce. |
| INTERNAL_API_DENY_AUDIT_ENABLED | Yes | Enables structured deny-event emission for blocked internal calls. |
| INTERNAL_API_ALLOWLIST_VERSION | No | Explicit allowlist policy version marker for change tracking and rollback coordination. |
| INTERNAL_API_REQUIRE_SERVICE_IDENTITY | Yes | Requires normalized caller identity from validated service certificate before internal route evaluation. |
| INTERNAL_API_FAIL_CLOSED_REVOCATION | Yes | Enforces fail-closed behavior when revocation checks are unavailable. |

### Agent Runtime
| Variable | Required | Purpose |
| --- | --- | --- |
| CONTROL_CENTER_URL | Yes | Control Center base URL used for internal runtime-essential calls. |
| SERVICE_IDENTITY | Yes | Runtime caller identity used for service certificate bootstrap and policy matching. |
| SERVICE_BOOTSTRAP_KEY | Yes | Bootstrap secret matching Control Center runtime bootstrap key. |
| INTERNAL_CALLS_REQUIRE_MTLS | Yes | Forces internal calls to use mutual TLS in non-local environments. |
| INTERNAL_ALLOWLIST_CALLER_TYPE | Yes | Declares caller type as agent_runtime for policy and audit normalization. |

### Communication Hub
| Variable | Required | Purpose |
| --- | --- | --- |
| CONTROL_CENTER_URL | Yes | Control Center base URL used for hub-essential internal calls. |
| SERVICE_IDENTITY | Yes | Hub caller identity used for service certificate bootstrap and policy matching. |
| SERVICE_BOOTSTRAP_KEY | Yes | Bootstrap secret matching Control Center communication hub bootstrap key. |
| INTERNAL_CALLS_REQUIRE_MTLS | Yes | Forces internal calls to use mutual TLS in non-local environments. |
| INTERNAL_ALLOWLIST_CALLER_TYPE | Yes | Declares caller type as communication_hub for policy and audit normalization. |

### Existing Variables That Become Strictly Required for This Rollout
| Variable | Service | Requirement Change |
| --- | --- | --- |
| AGENT_RUNTIME_BOOTSTRAP_KEY | Control Center | Must be present and rotated if previously shared or weak. |
| COMM_HUB_BOOTSTRAP_KEY | Control Center | Must be present and rotated if previously shared or weak. |
| CERT_RENEWAL_THRESHOLD_HOURS | Agent Runtime and Communication Hub | Must be set to avoid certificate expiry during rollout. |
| CONTROL_CENTER_URL | Agent Runtime and Communication Hub | Must reference internal TLS endpoint used for mTLS trust. |

## Infrastructure Changes

### Service Boundary and Routing
- Keep Control Center as the only database-connected service.
- Ensure Agent Runtime and Communication Hub have no direct database network route, credentials, or mounted database secrets.
- Enforce internal route segmentation so non-allowlisted Control Center internal paths are inaccessible by default.
- Route only approved internal service traffic to Control Center internal API surface.

### mTLS and Certificate Lifecycle
- Require mutual TLS for Agent Runtime to Control Center and Communication Hub to Control Center traffic in all non-local environments.
- Validate caller identity from service certificate before allowlist evaluation.
- Enforce revocation checks with fail-closed behavior when revocation status cannot be verified.
- Confirm certificate bootstrap, renewal, and revocation monitoring are operational before switching policy mode to enforce.

### Observability and Auditability
- Emit structured deny events containing caller type, endpoint, method, policy reason, and correlation metadata.
- Add alerting for spikes in deny events by caller type to detect misconfiguration or abuse.
- Add rollout dashboards for allowlist matches, denied calls, revocation failures, and certificate renewal status.

## Ordered Migration Steps

1. Preparation and Freeze
- Freeze Control Center internal endpoint contract and caller-specific allowlists for agent_runtime and communication_hub.
- Confirm production inventory of all active internal calls from Agent Runtime and Communication Hub.
- Confirm bootstrap keys and certificate trust assets are ready and distributed through secret management.

2. Infrastructure Readiness
- Deploy or verify mTLS trust chain for Control Center, Agent Runtime, and Communication Hub.
- Validate no direct database path from Agent Runtime or Communication Hub.
- Validate health probes for all three services and internal TLS connectivity checks.

3. Deploy Control Center with Audit Mode
- Deploy Control Center with caller-aware allowlist policy loaded.
- Set INTERNAL_API_POLICY_MODE to audit.
- Keep deny-event logging enabled and verify structured audit records are emitted.

4. Deploy Agent Runtime Client Alignment
- Deploy Agent Runtime with required caller identity and mTLS settings.
- Verify runtime-essential allowlisted endpoints succeed.
- Verify non-allowlisted internal endpoints generate denied audit events.

5. Deploy Communication Hub Client Alignment
- Deploy Communication Hub with required caller identity and mTLS settings.
- Verify hub-essential allowlisted endpoints succeed.
- Verify non-allowlisted internal endpoints generate denied audit events.

6. Contract Validation Window
- Run a controlled validation window using representative workloads.
- Confirm zero dependency on non-allowlisted internal paths.
- Resolve any allowlist drift before policy hard enforcement.

7. Switch to Enforce Mode (Deny-by-Default Active)
- Change INTERNAL_API_POLICY_MODE from audit to enforce.
- Confirm blocked paths now return denied responses and continue to emit audit events.
- Verify normal agent execution and communication workflows remain healthy.

8. Post-Cutover Security Verification
- Validate that Agent Runtime cannot call Communication Hub-only Control Center endpoints.
- Validate that Communication Hub cannot call Agent Runtime-only Control Center endpoints.
- Validate that unknown caller types, missing caller identity, and certificate mismatch are denied.

9. Stabilization and Sign-Off
- Monitor deny-event and certificate telemetry through a defined stabilization period.
- Capture deployment evidence bundle for security audit and compliance review.
- Record allowlist version and enforcement timestamp in deployment records.

## Rollback Procedure

### Rollback Triggers
- Sustained failures in legitimate agent execution paths caused by allowlist enforcement.
- Persistent mTLS handshake failures between internal services.
- Widespread deny events on expected allowlisted calls indicating policy or identity mapping regression.

### Immediate Safe Rollback
1. Revert Control Center policy mode from enforce to audit.
2. Keep deny-event logging enabled to retain evidence while service continuity is restored.
3. Revert Agent Runtime and Communication Hub to the last known-good release that matches the previous allowlist contract.
4. Validate internal service health and core user-facing workflows.

### Secondary Rollback if Needed
1. Roll back the allowlist version in Control Center to the previous approved policy bundle.
2. If certificate issues are root cause, rotate affected service certificates and re-bootstrap service identities.
3. Re-validate revocation checks and mTLS trust before re-enabling enforce mode.

### Rollback Guardrails
- Do not disable service certificate validation for internal routes.
- Do not introduce direct database access for Agent Runtime or Communication Hub during rollback.
- Keep deny-event telemetry active throughout rollback to preserve forensic traceability.

## What to Update in docs/master/deployment/

### Required Updates
- docs/master/deployment/environment-variables.md
  - Add new policy and caller-identity variables for Control Center, Agent Runtime, and Communication Hub.
  - Clarify which variables are mandatory when deny-by-default and mTLS are enforced.

- docs/master/deployment/services.md
  - Add caller-specific Control Center allowlist model by service.
  - Document service-boundary guarantees and explicit disallowed paths.

- docs/master/deployment/operational-runbooks.md
  - Add runbook entries for audit-to-enforce cutover, deny-event triage, and certificate failure response.
  - Add escalation thresholds for deny spikes and revocation-check failures.

- docs/master/deployment/rollback.md
  - Add rollback sequence for policy mode downgrade and allowlist version rollback.
  - Add constraints that preserve segregation controls during rollback.

- docs/master/deployment/README.md
  - Add deployment order for caller-specific allowlist rollout and enforce-mode activation.
  - Link to updated service, environment, operations, and rollback documents.

### Optional but Recommended Updates
- docs/master/deployment/configuration-files.md
  - Document where allowlist policy bundles are stored and versioned.
  - Document configuration precedence between environment variables and declarative policy sources.

## Deployment Considerations for Deny-by-Default and mTLS
- Deny-by-default should be activated only after a completed audit-mode observation window with zero unresolved allowlist drift.
- mTLS trust validation must be treated as a hard dependency for enforce-mode rollout.
- Revocation checks must run fail-closed in target environments; temporary fail-open behavior is not acceptable for production segregation controls.
- Operational teams must have real-time visibility into denied calls and certificate health before and after enforce-mode activation.
- Rollout communication should include caller contract ownership so endpoint additions require explicit approval and allowlist updates before deployment.
