# Implementation Plan: mcp-demo-app

## Overview

This change introduces a standalone Python FastAPI service (`mcp-demo-app/`) that authenticates with the Keycloak `ai_agents` realm, exposes a single `helloWorld` MCP tool, and self-registers with the Parthenon MCP Hub under the slug `demo`. The primary goal is to validate the end-to-end agent identity propagation pattern — from Keycloak issuance through Hub proxying to the demo app's JWT validation.

## Task Checklist

### Phase 1 — Project Scaffolding
- [x] 1.1 — Create project directory structure and `pyproject.toml`
- [x] 1.2 — Create `app/config.py` with Pydantic BaseSettings
- [x] 1.3 — Create `Dockerfile` and `.env.example`

### Phase 2 — Keycloak Authentication
- [x] 2.1 — Implement `KeycloakClient` with client credentials grant and JWKS cache
- [x] 2.2 — Implement `verify_agent_jwt()` and `get_agent_identity()` FastAPI dependency
- [x] 2.3 — Write unit tests for JWT validation logic

### Phase 3 — MCP Tool and Protocol Endpoint
- [x] 3.1 — Implement `hello_world_tool()` handler and `tool_registry`
- [x] 3.2 — Implement MCP JSON-RPC router (`POST /mcp`) handling `initialize`, `tools/list`, `tools/call`
- [x] 3.3 — Add `GET /health` endpoint

### Phase 4 — MCP Hub Registration
- [x] 4.1 — Implement `register_with_hub()` — POST server record and trigger tool sync
- [x] 4.2 — Hook registration into FastAPI lifespan startup; handle 409 idempotently

### Phase 5 — docker-compose Integration and Documentation
- [x] 5.1 — Add `mcp-demo-app` service to `docker-compose.yml`
- [x] 5.2 — Write `mcp-demo-app/README.md` with setup, env vars, and registration guide

### Phase 6 — End-to-End Validation
- [x] 6.1 — Start the stack and verify `demo` server and `helloWorld` tool appear in Hub UI
- [x] 6.2 — Simulate agent JWT forwarding and confirm identity surfaces in tool response

---

## Phase 1 — Project Scaffolding

### 1.1 — Create project directory structure and `pyproject.toml`

Create the `mcp-demo-app/` directory at the workspace root with the following layout:

```
mcp-demo-app/
├── pyproject.toml
├── Dockerfile
├── .env.example
├── README.md
└── app/
    ├── __init__.py
    ├── main.py
    ├── config.py
    ├── auth.py
    ├── tools.py
    ├── registration.py
    └── routes/
        ├── __init__.py
        ├── health.py
        └── mcp.py
```

`pyproject.toml` declares dependencies: `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `python-jose[cryptography]`, `httpx`, `pydantic`.

**Done when:** `mcp-demo-app/pyproject.toml` exists with correct package metadata and all listed dependencies declared; the `app/` module tree is present with empty `__init__.py` files.

---

### 1.2 — Create `app/config.py` with Pydantic BaseSettings

`AppSettings` reads all configuration from environment variables with sensible defaults. Required fields:

- `KEYCLOAK_URL` — base URL of the Keycloak instance
- `KEYCLOAK_REALM` — agent realm name (default: `ai_agents`)
- `KEYCLOAK_CLIENT_ID` — demo app's client ID in the agent realm
- `KEYCLOAK_CLIENT_SECRET` — demo app's client secret
- `HUB_BASE_URL` — Parthenon backend base URL (e.g. `http://localhost:8000`)
- `HUB_API_TOKEN` — static bearer token or service account token for Hub API calls
- `APP_BASE_URL` — publicly reachable URL of this demo app (used as `base_url` when registering with the Hub)
- `APP_PORT` — port to bind on (default: `8001`)
- `APP_SLUG` — MCP server slug (default: `demo`)

**Done when:** `AppSettings` instantiates without error when all required env vars are present; importing `from app.config import settings` provides a module-level singleton.

---

### 1.3 — Create `Dockerfile` and `.env.example`

`Dockerfile`: Python 3.11 slim base, copies `pyproject.toml` and `app/`, installs dependencies via `pip install -e .`, exposes `APP_PORT`, sets `CMD ["uvicorn", "app.main:app", ...]`.

`.env.example`: Lists all variables from `AppSettings` with placeholder values and inline comments explaining each field.

**Done when:** `docker build -t mcp-demo-app .` (run from `mcp-demo-app/`) completes without error; `.env.example` documents every `AppSettings` field.

---

## Phase 2 — Keycloak Authentication

### 2.1 — Implement `KeycloakClient` with client credentials grant and JWKS cache

`KeycloakClient` in `app/auth.py` wraps all Keycloak interactions:

- `get_own_access_token()` — performs the OAuth2 client credentials grant against `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token`; caches the token until near expiry (subtract 30 s buffer); refreshes automatically on next call if expired.
- `get_jwks()` — fetches the realm's JWKS from `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs`; caches for 10 minutes; used by JWT validation.

Uses `httpx.AsyncClient` for all HTTP calls.

**Done when:** `KeycloakClient.get_own_access_token()` returns a non-empty access token string when called with valid credentials against a real or mocked Keycloak; `get_jwks()` returns a dict with a `keys` list.

---

### 2.2 — Implement `verify_agent_jwt()` and `get_agent_identity()` FastAPI dependency

`verify_agent_jwt(token: str) -> dict` in `app/auth.py`:
- Fetches JWKS via `KeycloakClient.get_jwks()`
- Decodes and validates the JWT using `python-jose` (`jose.jwt.decode`)
- Validates `iss` matches `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}`
- Returns the decoded claims dict on success; raises `HTTPException(401)` on any failure

`get_agent_identity` FastAPI dependency:
- Extracts `Authorization: Bearer <token>` from the request
- Calls `verify_agent_jwt()` and returns the claims dict
- Used as a dependency on the MCP tool call handler

**Done when:** `verify_agent_jwt()` raises `HTTPException(401)` for expired, tampered, or wrong-realm tokens; returns claims dict for a valid token; `get_agent_identity` dependency injects claims into route handler.

---

### 2.3 — Write unit tests for JWT validation logic

Test file at `mcp-demo-app/tests/unit/test_auth.py` covers:
- Valid token → claims dict returned
- Expired token → `HTTPException(401)` raised
- Wrong issuer → `HTTPException(401)` raised
- Malformed/bad-signature token → `HTTPException(401)` raised
- JWKS cache used within TTL; re-fetched after 10 min expiry
- Access token cache used when still valid; refreshed within 30 s buffer; refreshed when no token cached
- `get_agent_identity`: missing header → 401; malformed header → 401; valid Bearer → claims returned

Tests use a static RSA key pair to generate test JWTs without requiring a live Keycloak instance.

**Done when:** `pytest mcp-demo-app/tests/` passes all 12 auth unit tests.

---

## Phase 3 — MCP Tool and Protocol Endpoint

### 3.1 — Implement `hello_world_tool()` handler and `tool_registry`

`hello_world_tool(agent_identity: dict) -> dict` in `app/tools.py`:
- Returns a JSON-serialisable dict: `{"message": "Hello from MCP Demo App!", "agent_sub": <sub claim>, "agent_claims": <full claims dict>}`

`tool_registry: dict[str, Callable]` in `app/tools.py`:
- Maps `"helloWorld"` → `hello_world_tool`

`TOOL_MANIFEST: list[dict]` in `app/tools.py`:
- Contains the MCP tool descriptor for `helloWorld`: name, description, input schema (empty object — no inputs required)

**Done when:** `hello_world_tool({"sub": "agent-123"})` returns the expected dict structure; `tool_registry["helloWorld"]` resolves to the handler; `TOOL_MANIFEST` contains exactly one entry with name `"helloWorld"`.

---

### 3.2 — Implement MCP JSON-RPC router (`POST /mcp`)

`mcp_router` in `app/routes/mcp.py` handles `POST /mcp` following MCP JSON-RPC 2.0:

| MCP Method | Behaviour |
|------------|-----------|
| `initialize` | Returns server info, protocol version, and capabilities (tools: `{}`) |
| `tools/list` | Returns `TOOL_MANIFEST` |
| `tools/call` | Resolves handler from `tool_registry`; injects `agent_identity` from `get_agent_identity` dependency; returns tool result wrapped in MCP response envelope |

Unknown methods return a JSON-RPC error response (`-32601 Method not found`).

**Done when:** `POST /mcp` with `{"method": "tools/list"}` returns the `helloWorld` descriptor; `POST /mcp` with `{"method": "tools/call", "params": {"name": "helloWorld", "arguments": {}}}` and a valid `Authorization: Bearer` header returns the greeting response including `agent_sub`.

---

### 3.3 — Add `GET /health` endpoint

`health_router` in `app/routes/health.py` returns `{"status": "ok", "slug": "<APP_SLUG>"}` with HTTP 200. No auth required.

**Done when:** `GET /health` returns HTTP 200 with the expected JSON body.

---

## Phase 4 — MCP Hub Registration

### 4.1 — Implement `register_with_hub()`

`register_with_hub(hub_base_url, api_token, slug, app_base_url)` in `app/registration.py`:

1. `POST {hub_base_url}/api/v1/mcp/servers` with body `{name: "MCP Demo App", slug: <slug>, base_url: <app_base_url>}` and `Authorization: Bearer <api_token>`
2. On HTTP 201 → server created; extract returned `server_id`
3. On HTTP 409 → server already exists; call `GET {hub_base_url}/api/v1/mcp/servers` to find the existing record and extract `server_id`
4. `POST {hub_base_url}/api/v1/mcp/servers/{server_id}/sync` to trigger tool sync

All calls use `httpx.AsyncClient`. Logs the outcome at INFO level.

**Done when:** `register_with_hub()` completes without exception against a running Parthenon backend; Hub shows `demo` server in its registry; after sync, `helloWorld` appears in the Hub's tool list under the `demo/` namespace.

---

### 4.2 — Hook registration into FastAPI lifespan startup

In `app/main.py`, the `lifespan` async context manager:

1. Calls `keycloak_client.get_own_access_token()` to validate Keycloak connectivity on startup (the `keycloak_client` singleton is created at module level in `app/auth.py`)
2. Calls `register_with_hub()` with values from `settings`
3. Logs startup completion

If either step fails, the startup error is logged at ERROR level and the process exits (fail-fast — no silent degraded state).

**Done when:** Starting `uvicorn app.main:app` with valid env vars produces log lines confirming Keycloak token obtained and Hub registration complete; the app accepts requests on `APP_PORT`.

---

## Phase 5 — docker-compose Integration and Documentation

### 5.1 — Add `mcp-demo-app` service to `docker-compose.yml`

Add a `mcp-demo-app` service to the root `docker-compose.yml`:
- Build context: `./mcp-demo-app`
- Ports: `${MCP_DEMO_PORT:-8001}:8001`
- Env vars sourced from a `.env` file or set inline with sensible defaults pointing to the other compose services
- `depends_on: [backend, keycloak]` with `condition: service_healthy`
- Healthcheck: `GET http://localhost:8001/health`

**Done when:** `docker compose up mcp-demo-app` starts the service and its healthcheck passes; the container appears in `docker compose ps` as healthy.

---

### 5.2 — Write `mcp-demo-app/README.md`

Cover:
- Purpose of the demo app
- Prerequisites (running Keycloak with `ai_agents` realm + `demo` client, running Parthenon Hub)
- All environment variables with descriptions
- Local development instructions (`uvicorn` run command)
- Docker Compose usage
- Registration flow explanation (what happens at startup)
- How to call the `helloWorld` tool manually (example `curl`)
- How to verify agent identity is visible in the response

**Done when:** A developer unfamiliar with the project can set up and run the app by following the README alone.

---

## Phase 6 — End-to-End Validation

### 6.1 — Verify Hub registration and tool sync

With the full stack running:
1. Navigate to the Parthenon Hub UI → MCP Servers
2. Confirm `demo` appears as a registered server with status `active`
3. Navigate to the server's tool list and confirm `helloWorld` appears under the `demo/` namespace

**Done when:** `demo/helloWorld` is visible in the Hub UI tool registry after app startup.

---

### 6.2 — Validate agent identity propagation

1. Obtain an agent JWT from Keycloak `ai_agents` realm (client credentials flow for any agent client)
2. Call `POST http://localhost:8001/mcp` with `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"helloWorld","arguments":{}}}` and `Authorization: Bearer <agent_jwt>`
3. Confirm the response includes `agent_sub` matching the agent's `sub` claim from the JWT

**Done when:** The tool response contains the correct `agent_sub` value matching the JWT's `sub` claim; no auth errors are returned.

---

## Completion Checklist

- [x] `mcp-demo-app/` directory exists at workspace root with all source files
- [x] App starts cleanly with valid env vars and logs Keycloak + Hub registration success
- [x] `GET /health` returns HTTP 200
- [x] `POST /mcp` with `tools/list` returns `helloWorld` descriptor
- [x] `POST /mcp` with `tools/call` and valid agent JWT returns greeting with `agent_sub`
- [x] `POST /mcp` with invalid/missing JWT returns HTTP 401
- [x] `demo` server and `demo/helloWorld` tool visible in Parthenon Hub UI after startup
- [x] Unit tests pass: `pytest mcp-demo-app/tests/`
- [x] `docker compose up mcp-demo-app` starts and healthcheck passes
- [x] `mcp-demo-app/README.md` documents all env vars and the end-to-end flow
