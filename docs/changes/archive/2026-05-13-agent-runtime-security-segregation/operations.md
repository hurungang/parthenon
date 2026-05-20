# Operations Guide: Agent Runtime Security Segregation

**Feature:** Agent Runtime Security Segregation  
**Date:** 2026-05-13  
**Audience:** DevOps Engineers, Security Administrators, Platform Operators

---

## Certificate Monitoring

### Check CA Certificate Expiration

```bash
curl -s http://localhost:8000/api/v1/certificates/ca | jq .expires_at
```

The CA certificate is valid for 10 years.  Set an alert to fire 6 months before expiry.

### Check Agent Certificate Expiration

Query the database directly:
```sql
SELECT instance_id, serial_number, expires_at, status, agent_type_id
FROM agent_instance_certificates
WHERE status = 'active'
  AND expires_at < NOW() + INTERVAL '6 hours'
ORDER BY expires_at ASC;
```

Or via the backend logs — the CertificateManager logs renewal events:
```
[INFO] Certificate renewed successfully: new serial=... expires=...
```

### Watch for Renewal Failures

```bash
grep "Certificate renewal attempt.*failed" /var/log/parthenon/backend.log
grep "Certificate.*EXPIRED.*shutting down" /var/log/parthenon/backend.log
```

If renewal fails, the agent runtime shuts down gracefully after the certificate expires.
Re-provision the certificate and restart the agent runtime.

---

## Certificate Revocation Procedure

When an agent instance is compromised or decommissioned:

```bash
# Find the certificate serial number
curl -s http://localhost:8000/api/v1/certificates/ca  # Not needed for serial lookup

# Or query the database
psql -c "SELECT serial_number FROM agent_instance_certificates WHERE instance_id = '<instance-id>';"

# Revoke the certificate
curl -X POST http://localhost:8000/api/v1/certificates/revoke \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "serial_number": "<serial-number>",
    "reason": "Instance compromised — security incident #<ticket>"
  }'
```

**Effect is immediate** — all subsequent validation calls for the revoked serial will fail with `revoked` outcome.

---

## Token Refresh Failure Resolution

### Detect Token Refresh Failures

```sql
SELECT ai.name, trl.agent_identity_id, trl.attempted_at, trl.outcome, trl.error_message
FROM token_refresh_logs trl
JOIN agent_identities ai ON trl.agent_identity_id = ai.id
WHERE trl.outcome IN ('failure', 'rate_limited')
  AND trl.attempted_at > NOW() - INTERVAL '1 hour'
ORDER BY trl.attempted_at DESC;
```

Or from logs:
```bash
grep "Token refresh failed" /var/log/parthenon/backend.log
```

### Resolution Steps

1. **Check OAuth provider health** — Is Keycloak/OIDC provider reachable?
2. **Check refresh token validity** — Has the user's session expired?
   ```sql
   SELECT status, token_status, token_expires_at FROM agent_identities WHERE name = '<identity-name>';
   ```
3. **Re-authorize identity** — If refresh token expired, re-run OAuth flow:
   - Go to Admin UI → Agent Identities → Select identity → Re-authorize

4. **Check token_status** — If `refresh_failed`, the identity needs manual intervention:
   ```sql
   UPDATE agent_identities SET token_status = NULL WHERE name = '<identity-name>';
   -- Then trigger re-authorization via UI
   ```

### Alert: `token_status = 'refresh_failed'`

Set an alert for:
```sql
SELECT COUNT(*) FROM agent_identities WHERE token_status = 'refresh_failed';
```
If count > 0, page on-call.

---

## Audit Log Queries

### View Recent Certificate Validations

```sql
SELECT certificate_serial_number, certificate_cn, validated_at, outcome,
       failure_reason, validated_by_service, requested_operation
FROM certificate_validation_logs
WHERE validated_at > NOW() - INTERVAL '1 hour'
ORDER BY validated_at DESC
LIMIT 100;
```

### Find All Failed Authorizations in Last 24h

```sql
SELECT certificate_serial_number, certificate_cn, outcome, failure_reason,
       requested_operation, validated_at
FROM certificate_validation_logs
WHERE outcome != 'valid'
  AND validated_at > NOW() - INTERVAL '24 hours'
ORDER BY validated_at DESC;
```

### Audit Trail for Specific Agent

```sql
-- All validations for a specific agent type
SELECT cvl.*
FROM certificate_validation_logs cvl
JOIN agent_instance_certificates aic ON aic.serial_number = cvl.certificate_serial_number
WHERE aic.agent_type_id = '<agent-type-uuid>'
ORDER BY cvl.validated_at DESC;
```

### Token Refresh History for Identity

```sql
SELECT attempted_at, outcome, retry_attempt, error_message, next_retry_at
FROM token_refresh_logs
WHERE agent_identity_id = '<identity-uuid>'
ORDER BY attempted_at DESC
LIMIT 50;
```

---

## Audit Log Retention Policy

Per compliance requirements:

| Table | Retention | Action |
|-------|-----------|--------|
| `certificate_validation_logs` | 90 days | Archive to cold storage after 90 days |
| `token_refresh_logs` | 90 days | Archive to cold storage after 90 days |
| `certificate_revocation_entries` | Permanent | Never delete (audit trail) |
| `agent_instance_certificates` | 30 days after revocation | Can archive; keep in DB for queries |

Cleanup query (run as scheduled job):
```sql
-- Archive certificate validation logs older than 90 days
DELETE FROM certificate_validation_logs WHERE created_at < NOW() - INTERVAL '90 days';

-- Archive token refresh logs older than 90 days
DELETE FROM token_refresh_logs WHERE created_at < NOW() - INTERVAL '90 days';
```

---

## Troubleshooting Guide

### Problem: `CA not initialized` error on startup

**Cause:** Control Center failed to initialize the CA (database connection issue or exception).
**Resolution:**
1. Check backend logs for `Certificate Authority initialization failed`
2. Verify database is reachable: `alembic current` should work
3. Verify `CREDENTIAL_VAULT_KEY` is set
4. Restart backend service

### Problem: `Certificate signature invalid`

**Cause:** Certificate was not signed by this Control Center's CA.
**Resolution:**
1. Check if the CA was re-generated (after Control Center restart without persisted CA key)
2. Re-provision the agent's certificate using the current CA:
   ```bash
   # Revoke old cert if possible, then issue new one
   POST /certificates/issue
   ```
3. Distribute new CA certificate to all agents: `GET /certificates/ca`

### Problem: `Certificate expired` in logs, agent unresponsive

**Cause:** Certificate renewal failed and certificate has now expired.
**Resolution:**
1. Manually issue a new certificate: `POST /certificates/issue`
2. Distribute to the agent instance (update cert file at `AGENT_CERT_PATH`)
3. Restart the agent runtime

### Problem: Token refresh rate-limited

**Cause:** OAuth provider is rate-limiting token refresh requests.
**Resolution:**
1. Check `Retry-After` header logged in `token_refresh_logs.metadata`
2. Wait for the rate limit window to expire
3. The service automatically retries with exponential backoff
4. If persistent, contact OAuth provider admin to increase rate limits for the agent client

### Problem: `invalid_grant` on token refresh

**Cause:** The stored refresh token has been invalidated (e.g., provider session expiry).
**Resolution:**
1. Re-run OAuth authorization flow for the agent identity in Admin UI
2. Update `encrypted_refresh_token` field (done automatically on re-auth)
3. Reset `token_status` to `active`

---

## Security Runbook

### Suspected Certificate Compromise

1. **Immediately revoke** the certificate:
   ```bash
   POST /certificates/revoke  {"serial_number": "...", "reason": "Suspected compromise — incident #..."}
   ```
2. Revocation is immediate — no restart required
3. Investigate: Query `certificate_validation_logs` for the serial number to see all operations performed
4. Issue replacement certificate to a new instance
5. Audit `token_refresh_logs` for the associated identity to check for unusual activity
6. File security incident report

### Token Leakage Investigation

Query for any validation log anomalies:
```sql
-- Look for unexpected validation sources
SELECT validated_by_service, COUNT(*) 
FROM certificate_validation_logs 
WHERE validated_at > NOW() - INTERVAL '24 hours'
GROUP BY validated_by_service;
```

Verify agent runtime logs contain NO identity tokens:
```bash
grep -i "access_token\|bearer\|id_token" /var/log/parthenon/agent.log
# Should return ZERO matches
```
