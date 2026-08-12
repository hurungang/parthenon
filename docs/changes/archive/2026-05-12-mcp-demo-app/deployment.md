# Deployment — MCP Demo App

## 1. Environment Variables

New environment variables required by the `mcp-demo-app` service. None of the existing Parthenon services require changes.

| Variable | Description | Secret |
|----------|-------------|--------|
| `KEYCLOAK_URL` | Base URL of the Keycloak instance reachable from the container (e.g., `http://keycloak:8080` inside Docker; public URL in production) | |
| `KEYCLOAK_REALM` | Keycloak realm for agent identities. Must be set to `ai_agents`. | |
| `KEYCLOAK_CLIENT_ID` | Client ID of the demo app's Keycloak client in the `ai_agents` realm | |
| `KEYCLOAK_CLIENT_SECRET` | Client secret for the demo app's Keycloak client | ✓ |
| `HUB_URL` | Internal base URL of the Parthenon MCP Hub (e.g., `http://api:8000/api/v1`) | |
| `HUB_API_KEY` | API key or bearer token used to authenticate registration calls to the MCP Hub | ✓ |
| `APP_URL` | Externally reachable base URL of the demo app that the Hub will use to proxy tool calls (e.g., `http://mcp-demo-app:9000`) | |
| `APP_SLUG` | Unique slug used when registering with the MCP Hub. Must be set to `demo`. | |
| `APP_PORT` | Port the FastAPI application listens on. Defaults to `9000`. | |

---

## 2. Infrastructure Changes

### New Service — MCP Demo App

A new standalone container is added to the deployment. It lives on the existing `parthenon` Docker network alongside all other services.

| Property | Value |
|----------|-------|
| Service name | `mcp-demo-app` |
| Container name | `parthenon-mcp-demo-app` |
| Source | `mcp-demo-app/` (new directory in workspace root) |
| Exposed port | `9000` (internal only; no public port mapping required) |
| Network | `parthenon` |
| Dependencies | `keycloak` (healthy), `api` (healthy) |

The container must start **after** Keycloak and the Platform API are healthy. Its startup sequence validates connectivity to Keycloak (client credentials grant) and then registers itself with the MCP Hub.

### docker-compose.yml Change

A new `mcp-demo-app` service block must be added to `docker-compose.yml`. It depends on `keycloak` (condition: `service_healthy`) and `api` (condition: `service_healthy`), and joins the `parthenon` network.

### Keycloak — New OIDC Client

A new client must be created in the Keycloak `ai_agents` realm before the container starts.

| Property | Value |
|----------|-------|
| Realm | `ai_agents` |
| Client ID | `mcp-demo-app` (must match `KEYCLOAK_CLIENT_ID`) |
| Access type | Confidential |
| Grant types enabled | Client Credentials |
| Service accounts | Enabled |
| Standard flow | Disabled |
| Direct access grants | Disabled |

The generated client secret becomes the value of `KEYCLOAK_CLIENT_SECRET`.

### No Database Changes

The demo app is stateless. No Alembic migrations, no new tables, and no schema changes are required.

### No Changes to Existing Services

No configuration, environment variables, or networking changes are required for any existing Parthenon service.

---

## 3. Migration Steps

Perform these steps in order. All steps must complete successfully before the deployment is considered live.

1. **Create the Keycloak client** — In the `ai_agents` realm, create the `mcp-demo-app` confidential client with Client Credentials grant and service accounts enabled. Copy the generated client secret.

2. **Add environment variables** — Add all variables listed in Section 1 to the deployment environment (`.env` file for Docker Compose; Kubernetes Secrets + ConfigMap for Helm). Set `KEYCLOAK_CLIENT_SECRET` and `HUB_API_KEY` via the secrets mechanism; never commit them to source control.

3. **Add the `mcp-demo-app` service to `docker-compose.yml`** — Configure the build context (`mcp-demo-app/`), environment variable bindings, port `9000`, dependency conditions, and network membership as described in Section 2.

4. **Build the demo app container image** — Build the `mcp-demo-app` Docker image from `mcp-demo-app/Dockerfile`. Confirm the build succeeds with no errors.

5. **Start the demo app container** — Bring up only the `mcp-demo-app` service (Keycloak and API must already be healthy). The container's startup sequence will perform the Keycloak token grant and MCP Hub registration automatically.

6. **Verify startup registration** — Confirm the demo app registered successfully by querying the MCP Hub's server list and checking that a server with slug `demo` appears. Confirm the `helloWorld` tool is listed under that server.

7. **Verify the health endpoint** — Send a `GET /health` request to the demo app. Expect `{"status": "ok", "slug": "demo"}` with HTTP 200.

8. **Verify tool invocation** — Using a valid agent JWT from the `ai_agents` realm, invoke the `helloWorld` tool via the MCP Hub. Confirm the response includes the agent's `sub` claim.

9. **Confirm no impact on existing services** — Run the standard Parthenon health checks for the Platform API and Keycloak. Confirm their status is unchanged.

---

## 4. Rollback Procedure

The demo app is stateless and its registration with the Hub is the only persistent side effect.

1. **Stop and remove the container** — Bring down the `mcp-demo-app` container. All in-memory state (token cache, JWKS cache) is discarded on shutdown.

2. **Remove the Hub server record** — Delete the `demo` slug server record from the MCP Hub via the Hub admin API or directly in the database. This removes the `helloWorld` tool from the Hub's tool registry.

3. **Remove the docker-compose.yml service block** — Revert the `docker-compose.yml` change that added the `mcp-demo-app` service.

4. **Remove environment variables** — Delete the `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`, `HUB_URL`, `HUB_API_KEY`, `APP_URL`, `APP_SLUG`, and `APP_PORT` variables from the deployment environment.

5. **Optionally remove the Keycloak client** — If the rollback is permanent, delete the `mcp-demo-app` client from the `ai_agents` realm to eliminate unused credential exposure. If a future retry is planned, the client may be retained.

6. **Verify no impact on remaining services** — Confirm the Platform API, Keycloak, and MCP Hub are all healthy after the rollback. The Hub should no longer list the `demo` server or `helloWorld` tool.

No database downgrade is required. No other services are affected.

---

## 5. Master Deployment Update Instructions

After this change is deployed and verified, update the following master deployment docs:

### `docs/master/deployment/services.md`

Add a new row to the **Service Inventory** table:

| Service | Container / Pod Name | Role |
|---------|----------------------|------|
| MCP Demo App | `parthenon-mcp-demo-app` | Standalone MCP server demonstrating end-to-end agent identity propagation; authenticates with the `ai_agents` Keycloak realm via client credentials; registers with the MCP Hub under slug `demo`; exposes the `helloWorld` tool |

Add `mcp-demo-app` to the **Service Dependencies** note: it depends on `keycloak` (healthy) and `platform-api` (healthy); it does not expose a public port and is not behind the nginx gateway.

### `docs/master/deployment/environment-variables.md`

Add a new **MCP Demo App** section with the variables listed in Section 1 of this document.

### `docs/master/deployment/configuration-files.md`

Note that the `mcp-demo-app` service has no configuration files — all configuration is supplied exclusively via environment variables.

### `docs/master/deployment/rollback.md`

Add a note under the section covering stateless services: stateless MCP servers (like `mcp-demo-app`) can be rolled back by stopping the container and removing the Hub server record — no database downgrade is needed.
