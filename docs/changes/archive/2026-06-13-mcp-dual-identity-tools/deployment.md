# MCP Dual-Identity Tools — Deployment Notes

## 1. Environment Variables

### New Variables (mcp-demo-app/)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KEYCLOAK_USER_REALM` | No | `""` (falls back to `KEYCLOAK_REALM`) | Keycloak realm that issues user identities. Set to the name of your user realm (e.g. `parthenon`) if different from the agent realm. Leave empty for single-realm deployments. |
| `KEYCLOAK_USER_CLIENT_ID` | No | `""` (falls back to `KEYCLOAK_CLIENT_ID`) | Client ID registered in the user realm. Only needed if the user realm uses a different client than the agent realm. |

### Changed Variables

| Variable | Change |
|----------|--------|
| None | All existing variables retain their current meaning and defaults. |

### Environment Variable Behavior

- When `KEYCLOAK_USER_REALM` is empty (default), the app operates in **single-realm mode**: `verify_user_jwt` uses `KEYCLOAK_REALM` for issuer validation. This is backward-compatible with existing deployments.
- When `KEYCLOAK_USER_REALM` is set, the app operates in **dual-realm mode**: `verify_user_jwt` uses `KEYCLOAK_USER_REALM` for issuer validation and `user_keycloak_client` fetches JWKS from the user realm.
- The `X-User-Identity` header is only validated when a tool requiring user identity (currently only `helloUser`) is called. Other tools continue to use the `Authorization` header only.

---

## 2. Infrastructure Changes

### Services

No new services are added. No changes to Docker Compose, Kubernetes manifests, or infrastructure provisioning. The `mcp-demo-app` service remains a single container on port 7001.

### Scaling

No scaling changes. The demo app is a single-instance service.

### Dependencies

| Dependency | Change |
|------------|--------|
| Keycloak user realm | **New requirement** for dual-identity validation. If not present, the user-identity-gated tool (`helloUser`) will fail authentication because JWKS cannot be fetched. The agent-identity-gated tools continue to work. |
| Keycloak agent realm | Unchanged. |
| Parthenon Communication Hub | Unchanged. Must already be forwarding the `X-User-Identity` header for `helloUser` to work. |
| Parthenon MCP Hub | Unchanged. Registration at startup proceeds as before. |
| Python dependencies | No new packages. All new code uses existing libraries (httpx, jose, FastAPI). |

### Keycloak Realm Configuration Requirements

For dual-identity validation to be fully operational:

- **Agent realm** (`ai_agents` or custom): must have a `demo_agent` realm-level role that is assigned to at least one agent identity. This role appears as an `mcp_role` claim in the agent's JWT.
- **User realm** (`parthenon` or custom): must have a `demo_user` realm-level role that is assigned to at least one user identity. This role appears as an `mcp_role` claim in the user's JWT.
- The `init.ps1` script can create these roles automatically when invoked with the `-UserRealm` parameter.

---

## 3. Migration Steps

### Step 1: Configure User Realm in Keycloak

If using dual-realm mode (recommended for full validation):

1. Ensure the user realm exists in Keycloak (e.g. `parthenon`).
2. Create a client in the user realm for the demo app (optional — only if user realm uses a different client than agent realm).
3. Create a realm-level role `demo_user` in the user realm.
4. Assign the `demo_user` role to at least one test user identity.
5. Create a realm-level role `demo_agent` in the agent realm.
6. Assign the `demo_agent` role to at least one test agent identity.

The `init.ps1` script can automate steps 2-4 when run with the `-UserRealm` parameter:

```
.\init.ps1 -UserRealm "parthenon" -Force
```

### Step 2: Update Environment Variables

Add the new environment variables to `.env` (or the deployment environment):

```
# Only needed for dual-realm mode — leave empty for single-realm
KEYCLOAK_USER_REALM=parthenon
KEYCLOAK_USER_CLIENT_ID=mcp-demo-app
```

If you use Docker Compose, add these to the `mcp-demo-app` service's environment section or the root `.env` file with the `MCP_DEMO_` prefix (refer to `docker-compose.yml` for the exact mapping convention).

### Step 3: Deploy the Updated Demo App

1. Pull the updated `mcp-demo-app/` code.
2. Restart the `mcp-demo-app` service.

The app registers with the Hub on startup. The Hub will discover three tools (instead of one) on the next tool sync. No manual Hub re-registration is needed.

### Step 4: Verify Tool Discovery

Call the MCP endpoint to verify all three tools are visible:

```
POST /mcp → {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
```

Expected: response contains three tool descriptors named `helloWorld`, `helloAgent`, `helloUser`.

### Step 5: Verify Access Control

Test each tool with and without the required role:

- `helloWorld`: should work with any valid agent JWT (no role required)
- `helloAgent` with `mcp_role: demo_agent`: should return greeting with agent identity
- `helloAgent` without `mcp_role` claim: should return access-denied (HTTP 200 with access_denied: true)
- `helloUser` with `mcp_role: demo_user`: should return greeting with user identity
- `helloUser` without `mcp_role` claim: should return access-denied (HTTP 200 with access_denied: true)

---

## 4. Rollback Procedure

### Immediate Rollback

If issues are detected after deployment:

1. Revert the `mcp-demo-app/` directory to the previous version (git checkout the previous commit for `mcp-demo-app/` only).
2. Restart the `mcp-demo-app` service.
3. The Hub will sync only `helloWorld` on the next tool sync.

### Graceful Degradation

The deployment is designed to degrade gracefully:

- If `KEYCLOAK_USER_REALM` is not set, `helloUser` will reject calls with a 401 error because it cannot validate the user JWT. Agent-identity tools (`helloWorld`, `helloAgent`) continue to work normally.
- If the user realm is unreachable, only `helloUser` is affected. The `user_keycloak_client` will fail to fetch JWKS, causing 401 responses for user-identity-gated tools.
- If role claims are not configured on identities, the tools correctly return access-denied results (not errors), which is the expected behavior for missing permissions.

### Data Considerations

There is no data migration to roll back. The demo app has no persistent state.

---

## 5. Master Deployment Update Instructions

### File: `docs/master/deployment/environment-variables.md`

- Add `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID` to the table under a new subsection "MCP Demo App." Document their fallback behavior and default empty values.

### File: `docs/master/deployment/services.md`

- Update the MCP Demo App entry to note that the service now supports dual-identity JWT validation and requires either a single realm (backward-compatible) or two realms (user + agent) for full validation coverage.

### File: `docs/master/deployment/configuration-files.md`

- Add the `mcp-demo-app/.env.example` file to the configuration files index if not already listed.
- Note the new optional variables `KEYCLOAK_USER_REALM` and `KEYCLOAK_USER_CLIENT_ID`.
