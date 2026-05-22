# Operations: Service Segregation Security Audit

## Purpose

Define operational controls for ongoing enforcement of Control Center internal API allowlists that are separated by caller:
- Agent Runtime allowlist
- Communication Hub allowlist

This operations change assumes deny-by-default policy at the Control Center boundary and continuous boundary enforcement telemetry.

## Operational Scope

This document covers:
- Monitoring and alerting needed to detect boundary drift, policy bypass attempts, and segregation regressions.
- Logging requirements for allowlist decisions, revocation checks, and internal authorization outcomes.
- Common failure modes and operator response priorities.
- Required updates to master operations documentation under [docs/master/operations](docs/master/operations).

This document does not redefine architecture ownership:
- Control Center remains the only database-connected service.
- Agent execution remains in Agent Runtime.

## New Monitoring and Alerting

### Monitoring Objectives

- Prove caller-scoped allowlists are actively enforced.
- Detect denied access spikes and classify by caller and endpoint.
- Detect false denials affecting valid runtime or hub paths.
- Detect contract drift between internal callers and Control Center endpoints.
- Detect certificate trust chain issues that can degrade allowlist enforcement.

### Metrics to Add

Add the following operational metrics to the Control Center and boundary services.

| Metric | Source | Labels | Why It Matters |
|---|---|---|---|
| Internal allowlist decisions total | Control Center policy guard | caller_type, endpoint, method, decision | Baseline visibility into allowed versus denied volume by caller and route |
| Internal deny total | Control Center policy guard | caller_type, endpoint, method, reason | Primary signal for deny-by-default activity and possible abuse |
| Unknown caller denials total | Control Center policy guard | endpoint, method | Detects missing identity context or spoofed service identity |
| Caller-certificate mismatch denials total | Control Center policy guard | caller_type, presented_cert_type | Detects certificate misuse and misconfiguration |
| Non-allowlisted endpoint attempts total | Control Center policy guard | caller_type, endpoint, method | Detects privilege-overreach attempts or stale client behavior |
| Revocation check failures total | Agent Runtime and Communication Hub revocation clients | caller_service, failure_mode | Detects trust-chain instability that may block internal calls under fail-closed policy |
| Revocation check latency p99 | Agent Runtime and Communication Hub revocation clients | caller_service | Shows upstream slowness before widespread internal request failures |
| Internal authorization latency p99 | Control Center internal API path | caller_type, endpoint_group | Detects policy gate or dependency performance regressions |
| Internal 403 rate | Control Center internal API path | caller_type, endpoint_group | Distinguishes expected denied traffic from misconfigured allowed traffic |
| System-tools unauthenticated reject total | Control Center internal system-tools routes | endpoint | Confirms hardened service-certificate dependency is active |

### Dashboard Changes

Add or extend dashboards with a dedicated panel group named Service Segregation Boundary Enforcement.

Recommended panels:
- Allowed versus denied internal calls over time, split by caller type.
- Top denied endpoints by caller type and deny reason.
- Unknown-caller and certificate-mismatch deny trend.
- Revocation check error rate and latency p99 for Agent Runtime and Communication Hub.
- Control Center internal authorization latency p99 and saturation indicators.
- Internal system-tools unauthenticated rejects.

### Alerts to Add

| Alert Name | Condition | Severity | Routing |
|---|---|---|---|
| InternalDenySpike | Internal deny rate exceeds normal baseline for 5 minutes | Warning | Operations on-call channel |
| NonAllowlistedEndpointAttemptDetected | Non-allowlisted endpoint attempts sustained for 2 minutes | Critical | Immediate on-call escalation |
| UnknownCallerDenied | Unknown caller denials greater than zero for 2 minutes | Critical | Immediate on-call escalation |
| CallerCertificateMismatch | Certificate mismatch denials greater than zero for 2 minutes | Critical | Immediate on-call escalation |
| RevocationCheckFailureSustained | Revocation check failures sustained for 2 minutes | Critical | Immediate on-call escalation |
| InternalAuthorizationLatencyHigh | Internal authorization latency p99 above threshold for 10 minutes | Warning | Operations on-call channel |
| Internal403RegressionAllowedPath | 403 rate increases on known allowlisted endpoints for 5 minutes | Warning | Operations on-call channel |
| SystemToolsUnauthenticatedAccessAttempt | Any unauthenticated access attempt on internal system-tools routes | Critical | Immediate on-call escalation |

Threshold calibration guidance:
- Start from current production baseline.
- Use stricter thresholds for unknown caller, certificate mismatch, and unauthenticated system-tools attempts.
- Adjust deny spike sensitivity after two release cycles to reduce alert fatigue.

## Logging Details

### Required Log Events

Add or standardize structured events for boundary decisions:

| Event | Level | Description |
|---|---|---|
| internal.allowlist.allowed | INFO | Internal request was allowlisted for caller and endpoint |
| internal.allowlist.denied | WARN | Internal request denied by default policy |
| internal.allowlist.unknown_caller | WARN | Caller identity missing or not recognized |
| internal.allowlist.certificate_mismatch | WARN | Caller certificate type did not match expected caller type |
| internal.allowlist.endpoint_not_allowlisted | WARN | Caller attempted endpoint outside its allowlist |
| internal.revocation.check_failed | ERROR | Revocation status could not be validated |
| internal.system_tools.unauthenticated_rejected | WARN | Internal system-tools request rejected due to missing service certificate |

### Required Fields per Event

All boundary log events must include:
- timestamp
- service_name
- trace_id
- span_id
- caller_type
- caller_identity
- certificate_type
- endpoint
- method
- decision
- deny_reason
- policy_version
- environment

### Log Retention and Queryability

- Keep boundary decision logs queryable in the aggregated store used by operations.
- Retain at least enough history to compare deny trends across two release cycles.
- Ensure operators can query by caller_type, endpoint, deny_reason, and trace_id during incidents.

### Privacy and Sensitive Data Controls

- Do not log tokens, certificate private key material, or decrypted secrets.
- Do not log request payload content for system-tools execution paths.
- Keep caller identity values to operational identifiers only.

## Common Failure Modes

### 1. Legitimate Path Denied After Policy Tightening

Symptoms:
- New or recently modified internal flow begins returning 403.
- Deny reason indicates endpoint not allowlisted.

Likely causes:
- Missing allowlist entry for a valid endpoint.
- Route template change not reflected in canonical endpoint matching.

Operator action:
- Confirm caller, endpoint, and deny reason in boundary logs.
- Validate if this is an approved business path.
- If approved, open urgent allowlist correction change with security review.

### 2. Unknown Caller Spikes

Symptoms:
- Unknown caller denials increase suddenly.

Likely causes:
- Missing caller identity propagation headers.
- Invalid certificate subject mapping.
- Deployment regression in internal auth middleware.

Operator action:
- Correlate with deployment timeline.
- Validate certificate identity extraction path in Control Center.
- Roll back latest boundary-related deployment if widespread impact is confirmed.

### 3. Certificate Type Mismatch

Symptoms:
- Certificate mismatch denials appear for otherwise valid traffic.

Likely causes:
- Service presenting wrong certificate class.
- Expired cert replaced with incorrect identity profile.

Operator action:
- Check certificate issuance and renewal records.
- Re-issue certificate for affected service identity.
- Validate service bootstrap and restart sequence.

### 4. Revocation Path Contract Drift

Symptoms:
- Revocation check failures increase.
- Internal calls fail closed even when certificates are expected valid.

Likely causes:
- Caller using obsolete revocation endpoint contract.
- Control Center route changes not propagated to clients.

Operator action:
- Confirm path mismatch in logs.
- Prioritize client contract fix release.
- Keep fail-closed behavior active; do not bypass revocation checks.

### 5. System-Tools Boundary Bypass Attempts

Symptoms:
- Unauthenticated reject events on internal system-tools routes.

Likely causes:
- Unauthorized request attempts.
- Misrouted internal traffic.

Operator action:
- Treat as security event until triaged.
- Validate source service identity and network path.
- Escalate to security owner if attempts persist.

### 6. Deny Event Flood During Release

Symptoms:
- High deny volume immediately after deployment.

Likely causes:
- Endpoint canonicalization mismatch.
- Allowlist map loaded with stale or incorrect policy version.

Operator action:
- Verify policy version in deny events.
- Compare expected versus active allowlist payload.
- Roll back policy update if valid traffic is broadly impacted.

## Update Plan for Master Operations Docs

Apply these updates in the master operations set.

### 1. Update [docs/master/operations/monitoring.md](docs/master/operations/monitoring.md)

Add a new subsection under Control Center and service trust monitoring:
- New metric definitions for allowlist decisions and deny reasons.
- New dashboard panel group: Service Segregation Boundary Enforcement.
- New alert definitions listed in this document.
- Runbook references for deny spikes and caller mismatch incidents.

### 2. Update [docs/master/operations/logging.md](docs/master/operations/logging.md)

Add a new subsection for boundary enforcement logs:
- Event catalog and level expectations.
- Mandatory fields list for allowlist decisions.
- Sensitive-data exclusions for boundary logs.
- Query guidance for incident triage by caller_type and deny_reason.

### 3. Add Runbook [docs/master/operations/runbooks/service-segregation-boundary-enforcement.md](docs/master/operations/runbooks/service-segregation-boundary-enforcement.md)

Create a runbook focused on:
- Triage flow for 403 spikes on internal APIs.
- Decision tree for endpoint-not-allowlisted versus unknown-caller versus certificate-mismatch events.
- Immediate containment and rollback criteria.
- Evidence checklist for post-incident review.

### 4. Update [docs/master/operations/README.md](docs/master/operations/README.md)

Add references to the new runbook and mention boundary-enforcement observability scope so operators can discover the new controls quickly.

## Operational Acceptance Criteria

- Boundary dashboards show allowed and denied internal requests by caller type.
- Alerts fire on simulated unknown caller and endpoint-not-allowlisted events.
- Logs include all required boundary fields and exclude sensitive data.
- Operators can complete first-response triage using the new runbook.
- Master operations documents are updated and linked consistently.
