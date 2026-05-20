# MCP Demo App

A standalone Python FastAPI service that authenticates with the Keycloak `ai_agents` realm, exposes a single `helloWorld` MCP tool, and self-registers with the Parthenon MCP Hub under the slug `demo`. Its primary purpose is to **validate the end-to-end agent identity propagation pattern**: a Keycloak-issued agent JWT flows from the Hub proxy into this service, is validated against the Keycloak JWKS, and the agent's identity is surfaced in the tool response.

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
```

**What it does:**
1. ✅ Checks Keycloak connectivity and realm existence
2. ✅ Authenticates as Keycloak admin
3. ✅ Checks if `mcp-demo-app` client exists
4. ✅ Creates client if needed (idempotent)
5. ✅ Retrieves client secret
6. ✅ Creates/updates `.env` file with credentials
7. ✅ Preserves existing `HUB_API_TOKEN` if present (unless `-Force` used)

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
3. Trigger a tool sync (`POST /api/v1/mcp/servers/{id}/sync`) so the Hub discovers `helloWorld`.

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

#### `tools/call` — requires `Authorization: Bearer <agent_jwt>`

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {"name": "helloWorld", "arguments": {}}
}
```

Example response:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{"type": "text", "text": "..."}],
    "result": {
      "message": "Hello from MCP Demo App!",
      "agent_sub": "service-account-my-agent",
      "agent_claims": { ... }
    }
  }
}
```

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

## Verifying Agent Identity

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

The printed value should match the `sub` claim in the JWT — confirming end-to-end agent identity propagation.

---

## Running Unit Tests

```bash
cd mcp-demo-app
pip install -e ".[dev]"
pytest tests/
```
