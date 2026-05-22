# Service Segregation Boundary Enforcement

## Trigger Symptoms

- Sudden spike in internal API 403 responses
- Logs show `internal.allowlist.denied` with `unknown_internal_caller` or `endpoint_not_allowlisted`
- Communication Hub or Agent Runtime internal calls fail after deployment
- Revocation checks fail and internal traffic is blocked under fail-closed policy

## Immediate Checks

1. Confirm caller and endpoint from logs.
- Inspect `caller_type`, `caller_identity`, `method`, `endpoint`, `deny_reason`, and `trace_id`.

2. Validate caller contract.
- `agent_runtime` should call runtime data/session endpoints only.
- `communication_hub` should call certificate/authorize, conversation/A2A data, system-tools, and MCP proxy endpoints.

3. Validate certificate identity path.
- Confirm service certificate CN matches expected service name.
- Confirm certificate is not revoked using `GET /api/v1/internal/certificates/revoked/{serial_number}`.

## Triage Decision Tree

1. `unknown_internal_caller`
- Likely identity propagation or caller normalization regression.
- Check service certificate subject and mapping in Control Center policy dependency.

2. `endpoint_not_allowlisted`
- Likely contract drift (new/changed endpoint not in caller allowlist).
- Validate whether call is expected.
- If expected, add explicit allowlist entry and ship reviewed patch.

3. Revocation check failures
- Fail-closed is expected behavior in target environments.
- Validate Control Center reachability for revocation endpoint and TLS trust.

## Containment

- If valid traffic is broadly denied, switch policy mode to audit while preserving deny event logging.
- Roll back recent boundary policy changes if deny volume remains elevated.
- Do not disable service certificate validation in production.

## Recovery Validation

- Deny spike returns to baseline.
- Allowlisted endpoint calls succeed for both caller profiles.
- No direct database path appears from Communication Hub or Agent Runtime.
- Structured deny events remain queryable for audit.

## Evidence to Collect

- Sample `internal.allowlist.denied` and `internal.allowlist.allowed` events with trace IDs
- Affected endpoint list and caller profile
- Deployment revision and rollback actions (if any)
- Post-recovery metrics screenshot for deny rate and internal 403 rate
