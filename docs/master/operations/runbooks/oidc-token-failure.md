# Runbook: OIDC Token Validation Failures

## Symptoms

- All Platform API endpoints are returning HTTP 401
- Logs from Control Center contain entries with `oidc.discovery.failure`, `oidc.jwks.fetch_failure`, or `auth.oidc.jwt_invalid`
- `oidc.provider.reachability` gauge is 0 for an active provider
- `oidc.jwks.fetch_failures_total` counter is incrementing
- Users and agents cannot authenticate; no requests are reaching application logic

---

## Resolution Steps

### OIDC Provider Unreachable

1. Confirm that the OIDC Discovery endpoint is reachable from within the Control Center container. Attempt a network request to the `.well-known/openid-configuration` endpoint from within the container's network namespace:
   ```
   curl -v <issuer_url>/.well-known/openid-configuration
   ```
   A failure here is the most common cause — check firewall rules, network policies, and DNS resolution between the Control Center and the identity provider.

2. Verify the identity provider service is running and accessible from the deployment environment.

3. Check DNS resolution for the issuer hostname from within the Control Center container.

4. Verify firewall rules allow outbound HTTPS from Control Center to the provider.

5. If using a self-signed or internal CA certificate on the OIDC provider, ensure the CA cert is trusted by the Control Center container.

6. Once connectivity is restored, the registry will pick up the provider on the next JWT validation request (no restart needed).

### Keycloak Realm Not Provisioned (Bundled Deployments Only)

7. If using bundled Keycloak, the Parthenon realm may not exist because the setup command was not run. A missing realm will cause all JWT validation to fail because the issuer is unknown. This is now detected proactively at startup — CC will fail with `startup.validation.keycloak_not_found`.

8. Run `setup verify` to check realm existence. If the realm is missing, run `setup identity` to provision it. See [setup-tool.md](setup-tool.md) for detailed setup tool guidance and [startup-validation-failure.md](startup-validation-failure.md) if CC is failing to start.

### JWKS Endpoint Unreachable

9. Verify that `OIDC_ISSUER_URL` exactly matches the `iss` claim in tokens issued by the identity provider. Retrieve a sample token, decode the payload, and compare the `iss` value character-by-character against the configured variable. Trailing slash differences (e.g., `https://idp.example.com/realm` vs `https://idp.example.com/realm/`) are a common source of silent mismatches.

10. Verify the JWKS URI from the provider's `.well-known/openid-configuration` is reachable from the Control Center container. The JWKS URI may be on a different host than the issuer — check that firewall rules cover both endpoints.

11. If the provider recently rotated signing keys, the JWKS cache may have stale keys. Trigger a manual registry reload via the System Config UI (Test Connection button) or restart the Control Center service. This forces a fresh JWKS fetch.

12. Check that the JWKS cache TTL is appropriate for the provider's key rotation frequency (default: 1 hour). If the provider uses infrequent key rotation, consider increasing the JWKS cache TTL.

### Token Claim Mismatches

13. Check that the audience (`aud` claim) in issued tokens matches the expected audience in the provider config. If the audience is missing from tokens, check the identity provider client configuration — the client may need to be configured to include the audience in token payloads.

14. If the issue affects only a specific user or agent, check that their identity record exists in the platform identity store (`GET /api/v1/identities`).

15. **If using multiple OIDC providers**: verify per-provider configuration in the database. Use the `provider_type` labels in logs to distinguish user provider failures from agent provider failures. Agent identities with client credentials will automatically refresh tokens on next execution.

### After Provider Configuration Change

16. If the failure occurred after updating a provider config via the System Config UI, verify that:
    - The issuer URL is character-exact, including trailing slashes
    - Claims mapping changes haven't broken required claim validation
    - The registry is not serving stale config (check `oidc.registry.reload_failed` log events; save any provider config in the UI to trigger a reload)

17. **Expected behaviour**: After a provider change, existing tokens from the old provider will fail validation. Users and agents will need to re-authenticate to obtain new tokens from the current provider. Schedule provider changes during maintenance windows and communicate that re-authentication will be required.

---

## Notes

- Do not expose raw JWT payloads in logs or support tickets — they may contain identity claims
- Log only the first 8 characters of JWT tokens as a `token_hint` for correlation; never log full token values
- In Kubernetes, if a network policy was recently changed, verify the policy allows egress from the Control Center pod to the identity provider's hostname and port
- The JWKS key cache is in-memory only; a Control Center restart or registry reload will clear it
- For emergency access when OIDC is broken, see [super-admin-lockout.md](super-admin-lockout.md)
