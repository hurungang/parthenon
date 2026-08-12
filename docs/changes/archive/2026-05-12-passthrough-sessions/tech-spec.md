# Technical Specification: passthrough-sessions

## 1. Technical Approach

The passthrough session type is implemented as a new value on the existing `McpSessionAuthType` enum. No new tables or top-level services are introduced.

At call time the `McpProxyEngine` inspects the resolved session's `auth_type`. For `passthrough` sessions it skips credential decryption entirely and instead injects the caller's agent JWT — sourced from the HTTP request context (API layer) or the agent runtime context (background execution) — as the `Authorization: Bearer` header sent to the MCP server.

Three integration points are extended:

| Layer | Change |
|---|---|
| **Auth Middleware** | Stores the raw bearer token string on `request.state.raw_token` so API endpoints can access it for passthrough forwarding |
| **MCP Proxy Engine** | Accepts optional `agent_jwt` parameter in `call_tool()`; dispatches it as Bearer for passthrough sessions; raises `McpProxyError` if passthrough is selected but no JWT is available |
| **Agent Runtime** | Detects passthrough sessions in the role session map; retrieves the executing agent's identity token and passes it to the proxy instead of looking up stored credentials |

Session creation for passthrough type skips credential encryption and the live connection test, activating the session immediately. The tool test UI presents an agent identity picker for passthrough servers instead of the existing session picker.

---

## 2. Code Changes

| File | Change |
|---|---|
| `backend/app/db/models/mcp_hub.py` | Added `passthrough = "passthrough"` to `McpSessionAuthType` |
| `backend/alembic/versions/5c2910c238a8_add_passthrough_to_mcp_session_auth_type.py` | Migration: `ALTER TYPE mcp_session_auth_type_enum ADD VALUE IF NOT EXISTS 'passthrough'` outside a transaction |
| `backend/app/main.py` | `validation_exception_handler` registered for `RequestValidationError`: converts Pydantic v2 `model_validator` exception objects in `ctx` to strings before JSON serialisation (bug fix required for passthrough credential validator) |
| `backend/app/middleware/auth.py` | `JWTAuthMiddleware.dispatch()` stores raw bearer token on `request.state.raw_token` immediately after extraction |
| `backend/app/services/mcp/proxy.py` | `call_tool()` accepts `agent_jwt` param; `_build_auth_headers()` has passthrough branch that injects JWT and skips credential decrypt; `_resolve_session()` already handles passthrough (only checks `is_active`) |
| `backend/app/schemas/mcp_hub.py` | `McpSessionCreate` validates no credentials for passthrough via `@model_validator`; `TestToolRequest` makes `session_id` optional and adds `agent_subject` field (agent identity UUID for token retrieval) |
| `backend/app/api/v1/mcp_hub.py` | `create_mcp_session` skips credential encrypt + test for passthrough, activates immediately; `test_mcp_tool` detects passthrough, extracts `request.state.raw_token`, passes `agent_jwt` to proxy; accepts `Request` param |
| `backend/app/services/mcp_session_test.py` | `test_mcp_session_connection()` returns immediate success for passthrough auth type |
| `backend/app/services/agents/runtime_executor.py` | `_load_role_mcp_session_map()` returns `{session_id, auth_type}` per server; `_execute_mcp_tool()` detects passthrough and calls `_get_agent_identity_jwt()`; new `_get_agent_identity_jwt()` decrypts identity access token from vault |
| `backend/app/services/agents/role_service.py` | `get_available_mcp_sessions()` includes `auth_type` in returned session dicts |
| `backend/tests/unit/test_auth_middleware.py` | New: 2 tests — `raw_token` stored after valid JWT; `raw_token` absent on public paths that bypass auth |
| `backend/tests/unit/test_mcp_proxy.py` | Added 3 passthrough tests: success case, missing JWT, empty JWT |
| `backend/tests/unit/test_agent_runtime_executor.py` | Added 2 passthrough tests: proxy called with `agent_jwt`, error returned when no JWT |
| `frontend/src/types/index.ts` | Added `'passthrough'` to `McpSessionAuthType` union |
| `frontend/src/pages/mcp/McpSessionManager.tsx` | `AUTH_TYPES` includes `passthrough`; credential fields hidden for passthrough; info `Alert` displayed; credentials omitted in submit; `Passthrough` chip in table |
| `frontend/src/pages/mcp/TestMcpToolDialog.tsx` | `McpSession` interface includes `auth_type`; `isPassthrough` derived from sessions; agent identity picker replaces session picker for passthrough; `handleTest` sends correct payload; agent identities fetched from `/agents/identities` |
| `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx` | `McpSessionInfo` includes `auth_type`; `Passthrough` chip shown; `toggle()` allows passthrough sessions to coexist with other sessions per server |
| `frontend/src/__tests__/McpSessionManager.test.tsx` | 3 new passthrough tests: auth type in options, credential fields hidden, chip in table |
| `frontend/src/__tests__/TestMcpToolDialog.test.tsx` | New file: 2 passthrough tests — identity picker vs session picker |
| `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` | New file: 2 passthrough tests — chip shown, chip absent for regular sessions |
| `frontend/src/i18n/locales/en.json` | Added `mcp.sessions.passthroughInfo` and `mcp.sessions.passthrough` keys |

---

## 3. API Changes

### 3.1 Session Creation — passthrough behaviour

`POST /api/v1/mcp/servers/{server_id}/sessions`

**Passthrough session request**

```json
{
  "name": "Agent Identity Passthrough",
  "description": "Forwards the executing agent JWT to the MCP server",
  "auth_type": "passthrough"
}
```

Validation rules:
- `credentials` must be absent or `null` when `auth_type` is `passthrough`; returns HTTP 422 if credentials are provided.

**Passthrough session response** (same `McpSessionRead` shape)

```json
{
  "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "server_id": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
  "name": "Agent Identity Passthrough",
  "description": "Forwards the executing agent JWT to the MCP server",
  "auth_type": "passthrough",
  "identity_subject": null,
  "is_active": true,
  "identity_binding": null,
  "credential_config": null,
  "oauth_expires_at": null,
  "oauth_refresh_expires_at": null,
  "created_at": "2026-05-12T10:00:00Z",
  "updated_at": "2026-05-12T10:00:00Z",
  "connection_test": {
    "success": true,
    "message": "Passthrough session — no credential test required"
  }
}
```

---

### 3.2 Tool Test Endpoint — updated contract

`POST /api/v1/mcp/tools/{tool_id}/test`

**Updated request schema**

```json
{
  "session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "agent_subject": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "tool_input": {
    "param1": "value1"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | `UUID \| null` | Required for non-passthrough sessions | Must identify an active session belonging to the tool's server |
| `agent_subject` | `string \| null` | Required for passthrough sessions | Agent identity UUID or username (realm_username); backend looks up by ID first, falls back to username; retrieves/refreshes the agent's access token and forwards it to the MCP server |
| `tool_input` | `object` | Always required | Input arguments for the tool |

**Passthrough error responses**

| Scenario | Status | Detail |
|---|---|---|
| Passthrough session selected but caller has no valid JWT | `400 Bad Request` | `"Passthrough tool test requires an authenticated caller"` |
| Non-passthrough session but `session_id` absent | `422 Unprocessable Entity` | Standard Pydantic validation error |
| `session_id` does not belong to the tool's server | `400 Bad Request` | `"Session belongs to a different server"` |

---

### 3.3 Role MCP Sessions — available sessions endpoint

`GET /api/v1/agents/roles/{role_id}/available-mcp-sessions`

Response shape updated: each item now includes `auth_type`.

```json
[
  {
    "id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "name": "Agent Identity Passthrough",
    "server_id": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
    "server_name": "MCP Demo App",
    "server_slug": "mcp-demo-app",
    "auth_type": "passthrough"
  }
]
```

---

## 4. Data Changes

### 4.1 `McpSessionAuthType` enum extension

**Declarative model file:** `backend/app/db/models/mcp_hub.py`

```python
class McpSessionAuthType(str, enum.Enum):
    api_key = "api_key"
    bearer_token = "bearer_token"
    basic_auth = "basic_auth"
    oauth2 = "oauth2"
    none = "none"
    passthrough = "passthrough"   # NEW
```

### 4.2 Migration

New Alembic revision (`add_passthrough_to_mcp_session_auth_type`):

- **Upgrade**: `ALTER TYPE mcp_session_auth_type_enum ADD VALUE IF NOT EXISTS 'passthrough'` — executed outside a transaction (`execute_if` / `connection.execution_options(isolation_level='AUTOCOMMIT')`) to satisfy PostgreSQL's restriction on `ADD VALUE` in transactions.
- **Downgrade**: no-op (PostgreSQL does not support removing enum values; existing pattern from migration `06519db12d6e`).

### 4.3 Business rules for `passthrough` sessions

| Rule | Behaviour |
|---|---|
| Credentials storage | `encrypted_credentials` is always `null`; any supplied credentials are rejected at creation time |
| Session activation | Session is set `is_active = True` immediately on creation without a live connection test |
| Runtime credential resolution | `McpProxyEngine` skips `_build_auth_headers()` credential decryption path; uses caller-supplied `agent_jwt` |
| Role assignment | Passthrough sessions appear in role session assignment; no extra constraint beyond one passthrough session per server per role |

---

## 5. Dependencies

No new external libraries or services. The feature relies entirely on:

- Existing Keycloak OIDC infrastructure for JWT issuance and introspection
- Existing `McpProxyEngine` and `httpx` for MCP server communication
- Existing `request.state.identity` / middleware JWT extraction pipeline (extended with `raw_token`)

---

## 6. Error Handling

| Error Scenario | Detection Point | Response |
|---|---|---|
| Passthrough session created with credentials | `McpSessionCreate` Pydantic validator | HTTP 422 — `"credentials must be null for passthrough auth type"` |
| Tool call via passthrough but no agent JWT in request context | `McpProxyEngine._build_auth_headers()` | Raises `McpProxyError("Passthrough session requires a caller JWT")` → HTTP 502 from tool test endpoint |
| Passthrough tool test called by unauthenticated user | `test_mcp_tool` endpoint | HTTP 400 — `"Passthrough tool test requires an authenticated caller"` |
| MCP server rejects forwarded JWT (401/403) | `McpProxyEngine.call_tool()` — `httpx.HTTPStatusError` | Raises `McpProxyError("Tool call failed: HTTP 401")` → surfaced as `TestToolResponse(success=False, error=...)` |
| Passthrough session in role but agent identity token unavailable at runtime | `_execute_mcp_tool()` | Returns error dict: `{"error": "Agent identity token unavailable for passthrough session on server <name>"}` — agent loop continues |
| Session not found for passthrough server | `_resolve_session()` | Raises `McpProxyError("No active session found for server <id>")` — same as standard flow |

---

## 7. Performance

- **Reduced latency per passthrough call**: credential decryption (AES-256 vault decrypt + JSON parse) is skipped entirely for passthrough sessions. Impact is minimal but net positive.
- **No new network calls at call time**: the agent JWT is already present in the request context or agent runtime state — no additional Keycloak introspection is performed by the proxy for passthrough forwarding. The MCP server performs its own JWT validation against Keycloak independently.
- **No credential cache required**: passthrough sessions carry no per-session state that needs refreshing (unlike OAuth2 sessions with token expiry tracking).

---

## 8. Security

| Concern | Mitigation |
|---|---|
| JWT forwarded to wrong server | `McpProxyEngine._resolve_session()` verifies the resolved session belongs to the tool's server before forwarding; MCP server URL is verified during registration |
| Raw token logged | `request.state.raw_token` is never written to application logs; `_build_auth_headers()` for passthrough follows existing convention of not logging credential values |
| Passthrough bypass credential checks | Passthrough sessions cannot be created with credentials (validated at creation); `_build_auth_headers()` for passthrough explicitly does not access the credential vault |
| Replay attack via forwarded JWT | JWT expiry enforced by both Keycloak (issuer) and the MCP server (recipient); no change to existing expiry behaviour |
| Unauthenticated callers triggering passthrough tool test | Endpoint checks `request.state.raw_token` is present (set only after successful JWT validation by middleware); returns HTTP 400 if absent |
| Agent impersonation via `agent_subject` field | Backend validates `agent_subject` is a valid agent identity UUID owned by the authenticated user before retrieving tokens; prevents impersonation of other users' agents |
