# Runbook: Certificate Security

Resolving CA initialization failures, certificate expiry and renewal issues, certificate compromise, and agent identity token refresh failures for the Agent Runtime security segregation system.

---

## 1. CA Not Initialized

**Trigger**: `ca.initialization_failed` ERROR at backend startup; all certificate issuance and validation calls fail.

**Symptoms**: Backend log contains `ca.initialization_failed`; agent instances cannot start; `GET /api/v1/certificates/ca` returns non-200.

**Likely Causes**:
- Database unreachable at startup, preventing CA state from being loaded or persisted.
- `CREDENTIAL_VAULT_KEY` environment variable not set or incorrect; CA private key cannot be decrypted.
- Database migration not applied — `agent_instance_certificates` or related tables missing.

**Resolution**:
1. Confirm database is reachable and migrations are current (`alembic current` shows the expected revision).
2. Verify `CREDENTIAL_VAULT_KEY` is set in the deployment environment.
3. Restart the backend service after resolving connectivity or configuration issues.
4. Confirm `ca.initialized` INFO log appears after restart; verify `GET /api/v1/certificates/ca` returns `200 OK`.

---

## 2. Certificate Signature Invalid

**Trigger**: `cert.validation.failed` WARN with `outcome = invalid_signature`.

**Symptoms**: Agent instances fail certificate validation; tool calls are rejected with authorization errors; `cert.validation.failed` WARN log appears with `outcome = invalid_signature`.

**Likely Causes**:
- The Control Center CA was re-generated after a backend restart without a persisted CA key, invalidating all previously issued certificates.
- In a multi-instance deployment, agent certificates were issued by a different Control Center instance than the one currently validating them.

**Resolution**:
1. Check backend logs for `ca.initialized` — if the CA key was re-generated, all existing agent certificates are now invalid.
2. Revoke the affected certificates via `POST /api/v1/certificates/revoke`.
3. Re-issue certificates for all affected agent instances via `POST /api/v1/certificates/issue`.
4. Distribute the updated CA public certificate to all agents via `GET /api/v1/certificates/ca`.
5. Restart affected agent runtime instances to load the new certificate.

---

## 3. Certificate Expired / Renewal Failure

**Trigger Alert**: `AgentCertRenewalFailure` or `AgentCertExpired`.

**Symptoms**: `cert.renewal_failed` ERROR in backend log; agent runtime shuts down gracefully after expiry; `cert.validation.failed` WARN with `outcome = expired`.

**Likely Causes**:
- Backend was unreachable during the automatic renewal window.
- Database connectivity issue prevented a successful renewal from being persisted.
- Network partition between the agent host and the backend prevented renewal requests from being delivered.

**Resolution**:
1. Verify backend connectivity from the affected agent instance.
2. Manually issue a replacement certificate via `POST /api/v1/certificates/issue` for the affected instance.
3. Update the certificate at `AGENT_CERT_PATH` on the agent host.
4. Restart the agent runtime to load the new certificate.
5. Confirm `cert.issued` or `cert.renewed` INFO log appears after restart; verify validation succeeds.

---

## 4. Certificate Compromise Response

**Trigger**: Security incident — suspected certificate theft, unauthorized use, or anomalous validation activity.

**Symptoms**: Unexpected `cert.validation.valid` DEBUG log entries from an unfamiliar `validated_by_service`; unauthorized tool calls associated with a known serial number in `certificate_validation_logs`.

**Resolution**:
1. Immediately revoke the compromised certificate via `POST /api/v1/certificates/revoke`, citing the incident ticket as the reason. Revocation is effective immediately — no service restart required.
2. Query `certificate_validation_logs` for the revoked serial number to identify all operations performed before revocation.
3. Audit `token_refresh_logs` for the associated agent identity to check for unusual activity patterns.
4. Issue a replacement certificate to a newly verified instance via `POST /api/v1/certificates/issue`.
5. File a security incident report.

---

## 5. Agent Identity Token Refresh Failed

**Trigger Alert**: `AgentIdentityRefreshFailed` — count of `agent_identities.token_status = 'refresh_failed'` > 0.

**Symptoms**: Agent identity cannot execute; sessions fail with authentication errors; `identity.token_refresh_failed` ERROR log present; `identity.token_expired` WARN log may appear mid-session.

**Likely Causes**:
- OIDC provider (Keycloak) unreachable from the backend host.
- Agent client credentials expired or revoked in the identity provider.
- Stored refresh token invalidated by the provider's session expiry policy.

**Resolution**:
1. Verify the OIDC provider is reachable from the backend host.
2. Check agent client credentials in the Keycloak admin console — confirm they have not been revoked or expired.
3. If the refresh token has been invalidated, re-run the OAuth authorization flow: Admin UI → Agent Identities → select the affected identity → Re-authorize.
4. After re-authorization, confirm `token_status` resets to `active` and `identity.token_acquired` DEBUG log appears for the identity.

---

## 6. Token Leakage Investigation

**Trigger**: Security audit or anomaly detection flagging unexpected identity token presence in logs or telemetry.

**Symptoms**: Identity access tokens visible in log lines or traces; unfamiliar services appearing in `certificate_validation_logs.validated_by_service`.

**Resolution**:
1. Scan agent runtime logs for `access_token`, `bearer`, and `id_token` strings — agent runtime logs must return zero matches for these terms by design.
2. Query `certificate_validation_logs` grouped by `validated_by_service` for the past 24 hours to identify unexpected validation sources.
3. Revoke any certificates associated with unauthorized services (see procedure 4 above).
4. Review logging configuration to confirm debug-level logging does not capture credential values at any log level.
5. File a security incident report if unauthorized access is confirmed.

---

## Audit Log Retention

| Table | Retention | Action |
|-------|-----------|--------|
| `certificate_validation_logs` | 90 days | Archive to cold storage after 90 days; scheduled cleanup job removes older rows |
| `token_refresh_logs` | 90 days | Archive to cold storage after 90 days; scheduled cleanup job removes older rows |
| `certificate_revocation_entries` | Permanent | Never delete; required as a permanent audit trail |
| `agent_instance_certificates` | 30 days after revocation | Can be archived; retain in database for query access |
