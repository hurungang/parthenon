# Tech Spec: mcp-demo-app

## 1. Technical Overview

The MCP Demo App is a standalone Python FastAPI service (`mcp-demo-app/`) that lives outside the main Parthenon codebase. It authenticates with the Keycloak `ai_agents` realm using the OAuth2 client credentials grant, registers itself with the Parthenon MCP Hub under the slug `demo`, and exposes a single MCP JSON-RPC 2.0 endpoint. On every tool invocation it validates the forwarded agent JWT against the Keycloak JWKS and surfaces the agent's identity (`sub` claim) in the response — proving the end-to-end agent identity propagation pattern.

There are no database dependencies, no frontend changes, and no modifications to existing Parthenon backend code. The only integration with the main codebase is a service entry in `docker-compose.yml` and calls to the existing Hub registration endpoints at startup.

---

## 2. Component Breakdown

| Component | Responsibility |
|-----------|----------------|
| `AppSettings` | Reads all configuration from environment variables (Keycloak URL, realm, client credentials, Hub URL, app URL, slug). Single source of truth for runtime config. |
| `KeycloakClient` | Encapsulates all Keycloak HTTP interactions: client credentials token grant (with expiry-aware cache), and JWKS fetch (with 10-minute cache). |
| `verify_agent_jwt` | Validates a forwarded agent JWT using the cached JWKS. Checks signature, expiry, and issuer. Returns decoded claims on success. |
| `get_agent_identity` | FastAPI dependency that extracts and validates the `Authorization: Bearer` token on each MCP tool call request. |
| `hello_world_tool` | Tool handler function. Accepts the validated agent identity claims and returns a greeting response that includes the agent's `sub` claim. |
| `tool_registry` | In-memory mapping of MCP tool name strings to their handler functions. |
| `TOOL_MANIFEST` | Static list of MCP tool descriptors (name, description, input JSON schema). Published via `tools/list`. |
| `register_with_hub` | Startup function that registers the demo app with the Parthenon Hub (`POST /api/v1/mcp/servers`) and triggers a tool sync (`POST .../sync`). Handles 409 idempotently. |
| `mcp_router` | FastAPI `APIRouter` handling `POST /mcp`. Dispatches JSON-RPC method calls to `initialize`, `tools/list`, and `tools/call` handlers. |
| `health_router` | FastAPI `APIRouter` handling `GET /health`. Returns `{"status": "ok", "slug": "demo"}`. No auth required. |
| `create_app` | FastAPI application factory. Configures the lifespan handler (Keycloak token validation + Hub registration on startup) and mounts routers. The `KeycloakClient` singleton is created at module level in `app/auth.py`. |
| `lifespan` | Async context manager. Validates Keycloak connectivity and triggers Hub registration on startup; exits the process on failure. |

---

## 3. API Endpoints

These endpoints are served by the standalone `mcp-demo-app` service, not the Parthenon backend.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/mcp` | `Authorization: Bearer <agent JWT>` required for `tools/call`; optional for `initialize` and `tools/list` | MCP JSON-RPC 2.0 endpoint. Dispatches `initialize`, `tools/list`, and `tools/call` methods. |
| `GET` | `/health` | None | Health check. Returns `{"status": "ok", "slug": "demo"}` with HTTP 200. |

### MCP JSON-RPC Methods

| Method | Description |
|--------|-------------|
| `initialize` | Returns server capabilities, protocol version, and server info. |
| `tools/list` | Returns array of tool descriptors from `TOOL_MANIFEST`. |
| `tools/call` | Invokes a named tool. `helloWorld` returns `{"message": "...", "agent_sub": "<sub>", "agent_claims": {...}}`. |

Unknown methods return JSON-RPC error code `-32601` (Method not found).

### Existing Parthenon Backend — No Changes

No new endpoints are added to or removed from the Parthenon backend API. The Hub registration is performed by the demo app calling the existing `POST /api/v1/mcp/servers` and `POST /api/v1/mcp/servers/{id}/sync` endpoints at startup.

---

## 4. Data Access Patterns

The demo app has no persistent data store. All state is held in-memory for the lifetime of the process.

| Data | Access Pattern | Notes |
|------|----------------|-------|
| Own access token | In-memory cache in `KeycloakClient` | Refreshed automatically ~30 s before expiry via client credentials grant |
| Keycloak JWKS | In-memory cache in `KeycloakClient` | Re-fetched every 10 minutes via `GET {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs` |
| Hub server record | Written once at startup via `POST /api/v1/mcp/servers` | Idempotent — 409 is handled by looking up the existing record |
| Tool manifest | Static in-process constant (`TOOL_MANIFEST`) | Published to the Hub via the standard MCP `tools/list` response during tool sync |
| Agent identity claims | Request-scoped only | Extracted from the forwarded JWT on each tool call; not persisted |

All outbound HTTP calls use `httpx.AsyncClient` with async/await.

---

## 5. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AppSettings` | class | Pydantic BaseSettings for all env-var configuration | `mcp-demo-app/app/config.py` |
| `settings` | instance | Module-level `AppSettings` singleton | `mcp-demo-app/app/config.py` |
| `KeycloakClient` | class | Keycloak client credentials grant + JWKS cache | `mcp-demo-app/app/auth.py` |
| `keycloak_client` | instance | Module-level `KeycloakClient` singleton; Keycloak connectivity validated during lifespan startup | `mcp-demo-app/app/auth.py` |
| `verify_agent_jwt` | function | Validates agent JWT against Keycloak JWKS; returns decoded claims | `mcp-demo-app/app/auth.py` |
| `get_agent_identity` | function | FastAPI dependency; extracts and validates bearer token from request | `mcp-demo-app/app/auth.py` |
| `hello_world_tool` | function | `helloWorld` tool handler; returns greeting with agent `sub` claim | `mcp-demo-app/app/tools.py` |
| `tool_registry` | dict | Maps MCP tool name strings to handler functions | `mcp-demo-app/app/tools.py` |
| `TOOL_MANIFEST` | list | Static MCP tool descriptor list published via `tools/list` | `mcp-demo-app/app/tools.py` |
| `register_with_hub` | function | Registers demo app with Parthenon Hub; triggers tool sync | `mcp-demo-app/app/registration.py` |
| `health_router` | APIRouter | FastAPI router for `GET /health` | `mcp-demo-app/app/routes/health.py` |
| `mcp_router` | APIRouter | FastAPI router for `POST /mcp` (MCP JSON-RPC dispatcher) | `mcp-demo-app/app/routes/mcp.py` |
| `mcp_endpoint` | function | FastAPI route handler for `POST /mcp`; parses the JSON-RPC envelope and dispatches to method handlers | `mcp-demo-app/app/routes/mcp.py` |
| `create_app` | function | FastAPI app factory; configures lifespan, mounts routers | `mcp-demo-app/app/main.py` |
| `lifespan` | async context manager | Validates Keycloak connectivity and triggers Hub registration on startup; exits the process on failure | `mcp-demo-app/app/main.py` |
| `app` | instance | Module-level FastAPI application instance | `mcp-demo-app/app/main.py` |
| — | conftest | Test env-var setup so `AppSettings()` can initialise in CI | `mcp-demo-app/tests/conftest.py` |
| `init.ps1` | script | Idempotent initialization script; checks Keycloak connectivity, creates/verifies mcp-demo-app client, retrieves secret, updates .env | `mcp-demo-app/init.ps1` |
| `setup-keycloak.ps1` | script | Legacy Keycloak setup script (use init.ps1 for new setups) | `mcp-demo-app/setup-keycloak.ps1` |
| `start.ps1` | script | Starts the demo app locally; checks prerequisites, creates venv, installs deps, starts server on port 7001 | `mcp-demo-app/start.ps1` |
| `stop.ps1` | script | Stops the demo app; finds and kills process on port 7001 | `mcp-demo-app/stop.ps1` |
