# MCP Demo App

A standalone Python FastAPI service that authenticates with the Keycloak `ai_agents` realm, exposes three MCP tools (`helloWorld`, `helloAgent`, `helloUser`), and self-registers with the Parthenon MCP Hub under the slug `demo`. Its primary purpose is to **validate the end-to-end dual-identity propagation pattern**: agent and user identity JWTs forwarded by the Communication Hub are independently validated against their respective Keycloak realms, and per-identity `mcp_role`-based access control is enforced at the tool level.

External contributions to this demo app are covered by the repository CLA
process. See [../CLA.md](../CLA.md) and [../CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Prerequisites

| Dependency | Notes |
|-----------|-------|
| Python 3.11+ | Local development |
| Docker / Docker Compose | Container run |
| Keycloak instance | `ai_agents` realm with a `mcp-demo-app` client (confidential, client-credentials grant enabled) |
| Parthenon backend | Running and reachable; Hub endpoints `POST /api/v1/mcp/servers` and `POST /api/v1/mcp/servers/{id}/sync` must be available |

---

## Quick Start

### First Time Setup

**Option 1: Automatic initialization (recommended)**
```powershell
# Initialize Keycloak client and create .env file
.\init.ps1

# Start the demo app
.\start.ps1
```

The `init.ps1` script will:
- ✅ Check Keycloak connectivity
- ✅ Verify the `ai_agents` realm exists
- ✅ Create the `mcp-demo-app` client if it doesn't exist
- ✅ Retrieve the client secret
- ✅ Create/update `.env` file with credentials
- ✅ Preserve existing `HUB_API_TOKEN` if present

**Option 2: Manual setup**
1. Copy `.env.example` to `.env`
2. Get the Keycloak client secret from your Keycloak admin console (`ai_agents` realm → Clients → `mcp-demo-app` → Credentials)
3. Set `KEYCLOAK_CLIENT_SECRET` in `.env`
4. Set `HUB_API_TOKEN` in `.env` (get from Parthenon backend admin)

### Starting and Stopping

**Start the demo app:**
```powershell
.\start.ps1
```

The script will:
- ✅ Check if port 7001 is available
- ✅ Create virtual environment if needed
- ✅ Install dependencies
- ✅ Verify Keycloak and Backend are running
- ✅ Start the server on port 7001

**Stop the demo app:**
```powershell
.\stop.ps1
```

### Re-initialization

If your Keycloak instance is reprovisioned or you need to recreate the client:
```powershell
# Force recreation of client and .env
.\init.ps1 -Force

# Or specify custom Keycloak URL
.\init.ps1 -KeycloakUrl "http://keycloak:8080" -Force
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values.

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_URL` | _(required)_ | Base URL of the Keycloak instance, e.g. `http://localhost:8082` |
| `KEYCLOAK_REALM` | `ai_agents` | Keycloak realm that issues agent identities |
| `KEYCLOAK_CLIENT_ID` | _(required)_ | Client ID registered in `ai_agents` realm for this app |
| `KEYCLOAK_CLIENT_SECRET` | _(required)_ | Client secret for `KEYCLOAK_CLIENT_ID` |
| `KEYCLOAK_USER_REALM` | _(empty)_ | Keycloak realm that issues user identities. Falls back to `KEYCLOAK_REALM` when unset (single-realm mode). |
| `KEYCLOAK_USER_CLIENT_ID` | _(empty)_ | Client ID in the user realm for this app. Not required when `KEYCLOAK_USER_REALM` is empty. |
| `HUB_BASE_URL` | _(required)_ | Parthenon backend base URL, e.g. `http://localhost:8000` |
| `HUB_API_TOKEN` | _(required)_ | Bearer token used when calling Hub registration APIs |
| `APP_BASE_URL` | _(required)_ | Publicly reachable URL of this service (used when registering with Hub) |
| `APP_PORT` | `7001` | Port to bind on |
| `APP_SLUG` | `demo` | MCP server slug registered with the Hub (must be unique) |

---

## Initialization Scripts

### `init.ps1` - Automated Keycloak Setup

Idempotent initialization script that sets up the Keycloak client and configuration. Safe to run multiple times.

**Basic usage:**
```powershell
.\init.ps1
```

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `-KeycloakUrl` | `http://localhost:8082` | Base URL of Keycloak instance |
| `-Realm` | `ai_agents` | Keycloak realm name |
| `-AdminUser` | `admin` | Keycloak admin username |
| `-AdminPassword` | `admin` | Keycloak admin password |
| `-HubApiToken` | _(prompts)_ | Hub API token to write to .env |
| `-UserRealm` | _(empty)_ | User realm for dual-realm setup |
| `-Force` | _(switch)_ | Force recreation of .env even if it exists |

**Examples:**
```powershell
# Standard initialization
.\init.ps1

# Custom Keycloak URL
.\init.ps1 -KeycloakUrl "http://keycloak:8080"

# Force recreation with custom token
.\init.ps1 -Force -HubApiToken "my-hub-token"

# Different admin credentials
.\init.ps1 -AdminUser "myadmin" -AdminPassword "mypassword"

# Dual-realm setup with user realm
.\init.ps1 -UserRealm "parthenon"
```

**What it does:**
1. ✅ Checks Keycloak connectivity and realm existence
2. ✅ Verifies user realm if `-UserRealm` is provided
3. ✅ Authenticates as Keycloak admin
4. ✅ Checks if `mcp-demo-app` client exists
5. ✅ Creates client if needed (idempotent)
6. ✅ Retrieves client secret
7. ✅ Creates realm roles `demo_agent` (agent realm) and `demo_user` (user realm) if needed
8. ✅ Creates/updates `.env` file with credentials
9. ✅ Preserves existing `HUB_API_TOKEN` if present (unless `-Force` used)

### `setup-keycloak.ps1` - Legacy Setup Script

Original setup script with similar functionality to `init.ps1`. Use `init.ps1` for new setups as it has better error handling and idempotency.

---

## Local Development

**Option 1: Using the start script (recommended)**
```powershell
# Configure environment first
cp .env.example .env
# ... edit .env with your values ...

# Start the server
.\start.ps1

# Stop the server (in another terminal)
.\stop.ps1
```

**Option 2: Manual setup**
```bash
cd mcp-demo-app

# Install dependencies
pip install -e ".[dev]"

# Copy and edit environment
cp .env.example .env
# ... edit .env with your values ...

# Run the server
uvicorn app.main:app --reload --port 7001
```

On startup the app will:
1. Obtain its own access token from Keycloak (client credentials grant).
2. Register itself with the Parthenon Hub (`POST /api/v1/mcp/servers`).
3. Trigger a tool sync (`POST /api/v1/mcp/servers/{id}/sync`) so the Hub discovers all three tools (`helloWorld`, `helloAgent`, `helloUser`).

---

## Docker Compose

```bash
# From the workspace root
docker compose up mcp-demo-app
```

The service depends on `api` (Parthenon backend) and `keycloak` being healthy before it starts. Set the required env vars via a root-level `.env` file:

```
MCP_DEMO_CLIENT_ID=mcp-demo-app
MCP_DEMO_CLIENT_SECRET=<your-secret>
HUB_API_TOKEN=<service-account-token>
```

---

## Endpoints

### `GET /health`

No authentication required. Returns:

```json
{"status": "ok", "slug": "demo"}
```

### `POST /mcp`

MCP JSON-RPC 2.0 endpoint. Three methods are supported:

#### `initialize`

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
```

#### `tools/list`

```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
```

Returns three tools: `helloWorld`, `helloAgent`, and `helloUser`.

#### `tools/call` — `helloWorld` (agent identity, no role gating)

Requires `Authorization: Bearer <agent_jwt>` header.

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {"name": "helloWorld", "arguments": {}}
}
```

#### `tools/call` — `helloAgent` (agent identity, requires `mcp_role: demo_agent`)

Requires `Authorization: Bearer <agent_jwt>` header. Returns an access-denied result when the agent's `mcp_role` claim is not `demo_agent`.

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {"name": "helloAgent", "arguments": {}}
}
```

Example success response:
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [{"type": "text", "text": "..."}],
    "result": {
      "message": "Hello Agent!",
      "agent_sub": "service-account-my-agent",
      "agent_realm": "http://keycloak:8082/realms/ai_agents",
      "agent_mcp_role": "demo_agent",
      "agent_claims": { ... }
    }
  }
}
```

Example access-denied response (HTTP 200):
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [{"type": "text", "text": "..."}],
    "result": {
      "access_denied": true,
      "reason": "Agent identity lacks required mcp_role: demo_agent"
    }
  }
}
```

#### `tools/call` — `helloUser` (user identity, requires `mcp_role: demo_user`)

Requires `X-User-Identity: Bearer <user_jwt>` header (does **not** require `Authorization`). Returns an access-denied result when the user's `mcp_role` claim is not `demo_user`.

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {"name": "helloUser", "arguments": {}}
}
```

Example success response:
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "result": {
    "content": [{"type": "text", "text": "..."}],
    "result": {
      "message": "Hello User!",
      "user_sub": "user-abc-123",
      "user_realm": "http://keycloak:8082/realms/parthenon",
      "user_mcp_role": "demo_user",
      "user_claims": { ... }
    }
  }
}
```

#### Identity Headers

| Header | Identity | Required For |
|--------|----------|-------------|
| `Authorization: Bearer <token>` | Agent identity JWT | `helloWorld`, `helloAgent` |
| `X-User-Identity: Bearer <token>` | User identity JWT | `helloUser` |

---

## Registration Flow

At startup the app calls:

```
POST {HUB_BASE_URL}/api/v1/mcp/servers
  { "name": "MCP Demo App", "slug": "demo", "base_url": "{APP_BASE_URL}" }
```

- **201 Created** → new server registered; `server_id` extracted from response.  
- **409 Conflict** → server already exists; performs `GET /api/v1/mcp/servers` to look up the existing record by slug.

Then:

```
POST {HUB_BASE_URL}/api/v1/mcp/servers/{server_id}/sync
```

This causes the Hub to call `POST {APP_BASE_URL}/mcp` with `{"method": "tools/list"}` and cache the tool manifest.

---

## Dual-Identity Setup

The MCP Demo App supports two identity validation modes:

| Mode | Description |
|------|-------------|
| **Single-realm** (default) | `KEYCLOAK_USER_REALM` is left empty. Both agent and user tokens are validated against the same Keycloak realm (`KEYCLOAK_REALM`). |
| **Dual-realm** | `KEYCLOAK_USER_REALM` is set to a separate realm (e.g. `parthenon`). Agent tokens are validated against `KEYCLOAK_REALM`, user tokens against `KEYCLOAK_USER_REALM`. |

### Configuring Dual-Realm Mode

1. Ensure both realms exist in Keycloak (e.g. `ai_agents` for agents, `parthenon` for users).
2. Run the init script with the user realm:
   ```powershell
   .\init.ps1 -UserRealm "parthenon"
   ```
   This verifies both realms exist, writes `KEYCLOAK_USER_REALM` to `.env`, and creates realm roles `demo_agent` (in `ai_agents`) and `demo_user` (in `parthenon`).
3. Or manually add to `.env`:
   ```
   KEYCLOAK_USER_REALM=parthenon
   KEYCLOAK_USER_CLIENT_ID=mcp-demo-app
   ```

### Assigning mcp_role Claims

The `helloAgent` tool requires the agent to have the `demo_agent` realm role, and `helloUser` requires the user to have the `demo_user` realm role. These roles must be assigned in Keycloak:

1. In the agent realm, assign the `demo_agent` realm role to the agent's client or user.
2. In the user realm, assign the `demo_user` realm role to the user.
3. If using client credentials, the service account must be granted the realm role.

Without these role assignments, the tools will return an access-denied result (HTTP 200 with `access_denied: true`).

## Verifying Tool Behavior

### `helloWorld` (agent identity, no role gating)

1. Obtain an agent JWT from Keycloak `ai_agents` realm:

```bash
curl -s -X POST http://localhost:8082/realms/ai_agents/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=<agent-client>&client_secret=<secret>" \
  | jq -r .access_token
```

2. Call `helloWorld` directly:

```bash
curl -s -X POST http://localhost:7001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <agent_jwt>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"helloWorld","arguments":{}}}' \
  | jq .result.result.agent_sub
```

### `helloAgent` (agent identity, requires `demo_agent` role)

1. Ensure the agent has the `demo_agent` realm role assigned in Keycloak.
2. Obtain an agent JWT (same as above).
3. Call `helloAgent`:

```bash
curl -s -X POST http://localhost:7001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <agent_jwt>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"helloAgent","arguments":{}}}' \
  | jq .
```

The response will include `agent_sub`, `agent_realm`, `agent_mcp_role`, and `agent_claims` on success, or `access_denied: true` if the role is missing.

### `helloUser` (user identity, requires `demo_user` role)

1. Ensure the user has the `demo_user` realm role assigned in Keycloak.
2. Obtain a user JWT from the user realm (or use a client credentials grant with the role assigned to the service account):

```bash
# Obtain user token (e.g. from parthenon realm)
USER_TOKEN=$(curl -s -X POST http://localhost:8082/realms/parthenon/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=<user-client>&client_secret=<secret>" \
  | jq -r .access_token)

# Obtain agent token (needed even when not used for helloUser — the Hub forwards it)
AGENT_TOKEN=$(curl -s -X POST http://localhost:8082/realms/ai_agents/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=<agent-client>&client_secret=<secret>" \
  | jq -r .access_token)
```

3. Call `helloUser` with the user identity in `X-User-Identity` header:

```bash
curl -s -X POST http://localhost:7001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -H "X-User-Identity: Bearer $USER_TOKEN" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"helloUser","arguments":{}}}' \
  | jq .
```

The response will include `user_sub`, `user_realm`, `user_mcp_role`, and `user_claims` on success, or `access_denied: true` if the role is missing.

> **Note:** The `X-User-Identity` header is the mechanism by which the Communication Hub forwards the user identity JWT to MCP servers. The `Authorization` header carries the agent identity. For `helloUser`, only the `X-User-Identity` header is inspected — the `Authorization` header is not required (though it is present when called through the Hub).

---

## Running Unit Tests

```bash
cd mcp-demo-app
pip install -e ".[dev]"
pytest tests/
```
