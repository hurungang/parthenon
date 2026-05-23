# Service Segregation Boundary Enforcement

## Trigger Symptoms

- Sudden spike in internal API 403 responses
- Logs show `internal.allowlist.denied` with `unknown_internal_caller` or `endpoint_not_allowlisted`
- Communication Hub or Agent Runtime internal calls fail after deployment
- Revocation checks fail and internal traffic is blocked under fail-closed policy
- Logs show `internal.allowlist.certificate_mismatch` for otherwise expected internal traffic

## First 10 Minutes

1. Confirm incident scope.
- Check deny rate by `caller_type` and list the top denied endpoints.
- Record whether impact is limited to Agent Runtime, Communication Hub, or both.

2. Capture mandatory evidence fields from denied events.
- Record `caller_type`, `caller_identity`, `certificate_type`, `endpoint`, `method`, `deny_reason`, `policy_version`, and `trace_id`.

3. Check for concurrent revocation and certificate indicators.
- Confirm whether `internal.revocation.check_failed` is present.
- Confirm whether certificate mismatch events are present.

## Triage Decision Tree

1. `unknown_internal_caller`
- Likely identity propagation or caller normalization regression.
- Check service certificate subject and mapping in Control Center policy dependency.
- If introduced in latest deployment, prioritize rollback of caller-normalization changes.

2. `endpoint_not_allowlisted`
- Likely contract drift (new/changed endpoint not in caller allowlist).
- Validate whether call is expected.
- If expected, add explicit allowlist entry and ship reviewed patch.

3. `certificate_mismatch`
- Caller presented wrong certificate class for its role.
- Confirm certificate issuance record maps service identity to correct certificate class.
- Re-issue the correct certificate and restart the affected service instance.
- If mismatch persists, escalate to [certificate-security.md](certificate-security.md).

4. Revocation check failures
- Fail-closed is expected behavior in target environments.
- Validate Control Center reachability for revocation endpoint and TLS trust.
- Do not bypass revocation checks during incident response.

## Deny Spike Response

1. Compare deny volume to baseline over the same hour-of-day window.
2. If deny volume is above baseline for more than 5 minutes, declare an incident and page on-call security owner.
3. Correlate deny spike start time with deployment and policy-version changes.
4. If valid allowlisted paths are impacted broadly, roll back to the last known good policy version.
5. Keep deny logging enabled throughout mitigation for audit continuity.

## Certificate Issue Response

1. If certificate mismatch or unknown caller appears, validate service certificate subject and certificate class assignment.
2. Confirm the certificate is active and not revoked or expired.
3. Re-issue and deploy the correct certificate when identity-class mismatch is confirmed.
4. Restart only the affected service after certificate replacement.
5. Confirm deny events for that caller return to baseline and allowlisted calls succeed.

## Containment

- If valid traffic is broadly denied, switch policy mode to audit only when approved by security on-call and only for the minimum time required.
- Roll back recent boundary policy changes if deny volume remains elevated.
- Do not disable service certificate validation in production.

## Recovery Validation

- Deny spike returns to baseline.
- Allowlisted endpoint calls succeed for both caller profiles.
- No new `certificate_mismatch` events for 15 minutes after recovery.
- No direct database path appears from Communication Hub or Agent Runtime.
- Structured deny events remain queryable for audit.

## Evidence to Collect

- Sample `internal.allowlist.denied` and `internal.allowlist.allowed` events with trace IDs
- Affected endpoint list and caller profile
- Incident window by policy version and deployment revision
- Certificate serial and issuance record for any mismatch incident
- Deployment revision and rollback actions (if any)
- Post-recovery metrics screenshot for deny rate and internal 403 rate
