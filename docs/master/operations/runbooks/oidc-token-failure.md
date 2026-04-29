# Runbook: OIDC Token Validation Failures

## Symptoms

- All Platform API endpoints are returning HTTP 401
- Logs from `platform-api` contain entries with `JWT validation error` or `JWKS fetch failed`
- Users and agents cannot authenticate; no requests are reaching application logic

---

## Resolution Steps

1. Confirm that `OIDC_JWKS_URI` is reachable from inside the Platform API container. Attempt a network request to the JWKS endpoint from within the container's network namespace. A failure here is the most common cause — check firewall rules, network policies, and DNS resolution between the Platform API and the identity provider.

2. Verify that `OIDC_ISSUER_URL` exactly matches the `iss` claim in tokens issued by the identity provider. Retrieve a sample token, decode the payload, and compare the `iss` value character-by-character against the configured variable. Trailing slash differences (e.g., `https://idp.example.com/realm` vs `https://idp.example.com/realm/`) are a common source of silent mismatches.

3. Check that `OIDC_AUDIENCE` matches the `aud` claim in issued tokens. Retrieve a sample token and confirm the `aud` value. If the audience is missing from tokens, check the identity provider client configuration — the client may need to be configured to include the audience in token payloads.

4. If the identity provider recently rotated its signing keys and the JWKS endpoint now returns new keys, the Platform API may be holding a cached copy of the old keys. Restart the Platform API container to force a fresh JWKS fetch. The key cache is in-memory only and is cleared on restart.

---

## Notes

- Do not expose raw JWT payloads in logs or support tickets — they may contain identity claims
- If the issue affects only a specific user or agent, check that their identity record exists in the platform identity store (`GET /api/v1/identities`)
- In Kubernetes, if a network policy was recently changed, verify the policy allows egress from the `platform-api` pod to the identity provider's hostname and port
