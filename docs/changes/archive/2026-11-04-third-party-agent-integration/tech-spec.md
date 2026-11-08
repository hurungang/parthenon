# Technical Specification: third-party-agent-integration

## Technical Overview

This change introduces a new primitive — the **client** — that grants third-party access to an agent type's *input interface* (conversation turn or typed submit). A client is a separate credential class from the existing **API key**: an API key authenticates *as* an agent identity (+ role) for MCP tool access (unchanged), while a client is bound to one agent type and can only invoke it. Clients carry a `key_type` of `secret` (server-side) or `publishable` (browser-safe), plus white-label theme, allowed origins, and a rate limit. Because a client is not an identity, it cannot list/call tools, reach the MCP hub, or impersonate an agent — the invoked agent type runs with its own identity + role as configured.

## Component Breakdown

- **`AgentClient`** — tenant-owned access grant bound to exactly one `AgentType`; holds the credential (hash/prefix/`key_type`/status), white-label theme, allowed origins, and rate-limit config.
- **`AgentClientUsageLog`** — append-only audit record per invocation (action = `conversation_turn`/`submit_request`), never storing the credential value.
- **Client service (CC)** — create/list/revoke clients; enforce `key_type` immutability, per-tenant uniqueness, and the publishable-credential soft-warning; resolve a client credential → agent type + config.
- **Client management endpoints (CC)** — JWT-authenticated admin routes for client CRUD and credential issuance/revocation.
- **Client validation endpoint (CC, internal/mTLS)** — resolves a hashed client credential to `(client → agent type + config)`, returning **no agent identity token** (a client is not an identity); a `secret` client may additionally carry a validated optional end-user identity for server-side dual identity.
- **Client auth middleware (CH)** — detects client credentials, calls CC resolution over mTLS, enforces origin + rate limit, and attaches the resolved client context (tokens held CH-side only).
- **Integration gateway (CH)** — `/integrate/*` router: conversational chat, typed submit, widget/theme serving, SDK distribution.
- **SDKs + example** — JS SDK (widget + turns + request/response), Python SDK (request/response + server-side), runnable local example.

## API Changes

| Method | Path | Service | Change | Auth |
|--------|------|---------|--------|------|
| `GET` | `/api/v1/clients` | Control Center | New — list clients (optional `agent_type_id` filter) | JWT (admin) |
| `POST` | `/api/v1/clients` | Control Center | New — create a client (secret/publishable) | JWT (admin) |
| `POST` | `/api/v1/clients/{id}/credential` | Control Center | New — rotate credential (clear-text once) | JWT (admin) |
| `PATCH` | `/api/v1/clients/{id}` | Control Center | New — edit allowed origins + rate limit (only mutable fields) | JWT (admin) |
| `PATCH` | `/api/v1/clients/{id}/status` | Control Center | New — activate/deactivate a client (`active`/`inactive`) | JWT (admin) |
| `DELETE` | `/api/v1/clients/{id}` | Control Center | New — remove a client (hard delete, cascades usage logs) | JWT (admin) |
| `POST` | `/api/v1/internal/clients/validate` | Control Center | New — resolve client credential → agent type + config (**exempt from tenant headers** — it discovers the tenant) | Service certificate (mTLS) |
| `POST` | `/api/v1/internal/clients/invoke` | Control Center | New — enqueue + trigger agent execution for a client | Service certificate (mTLS) |
| `GET` | `/integrate/config` | Communication Hub | New — public widget/theme config (white-label) | client credential |
| `POST` | `/integrate/conversations` | Communication Hub | New — start a **stateful** conversation session (conversational types only) | client credential |
| `POST` | `/integrate/conversations/{id}/messages` | Communication Hub | New — send a message in the conversation (stateful; returns reply) | client credential |
| `POST` | `/integrate/conversations/{id}/end` | Communication Hub | New — end the conversation session | client credential |
| `POST` | `/integrate/submit` | Communication Hub | New — typed request/response for **non-conversational** types (async session id; rejected for conversational types) | client credential |
| `GET` | `/integrate/session/{id}` | Communication Hub | New — poll an execution session's status/output | client credential |
| `GET` | `/integrate/sdk/parthenon-chat.js` | Communication Hub | New — JS SDK bundle | public |
| `GET` | `/integrate/sdk/parthenon-python` | Communication Hub | New — Python SDK metadata | public |

No existing endpoint is removed or deprecated; API-key (identity) endpoints and the MCP protocol server are unchanged.

## State Management

Server-side state is the resolved client context held by the CH client-auth middleware (client id, `key_type`, agent type, theming/origin/rate config, rate counters) — never the credential value. The target agent type runs with its own identity + role for both `secret` and `publishable` clients; that identity token (and, for `secret` clients, the optional validated end-user token) is held CH-side and injected per call, never serialized to the client. Frontend state is standard list/dialog state with `dialogError` handling; publishable-client creation surfaces a soft-warning banner.

## Data Access Patterns

- **Control Center** is the sole database owner: client CRUD, credential resolution, and usage-log writes all go through CC.
- **Communication Hub** has no direct DB access: it validates client credentials over mTLS and routes execution to Agent Runtime over the signed internal path.
- **Agent Runtime** executes the target agent type with its own identity + role; no identity is derived from the client.
- **Frontend** calls CC REST APIs over JWT; no direct DB access.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentClient` | model | Access grant bound to an agent type | `backend/app/db/models/agent_client.py` |
| `AgentClientUsageLog` | model | Per-invocation audit record | `backend/app/db/models/agent_client.py` |
| `AgentClientKeyType` | enum | `secret` / `publishable` | `backend/app/db/models/agent_client.py` |
| `AgentClientStatus` | enum | `active` / `revoked` | `backend/app/db/models/agent_client.py` |
| `AgentClientRateLimitWindow` | enum | `per_minute` / `per_hour` / `per_day` | `backend/app/db/models/agent_client.py` |
| `AgentClientAction` | enum | `conversation_turn` / `submit_request` | `backend/app/db/models/agent_client.py` |
| `AgentType.clients` | relationship | Agent type → its clients (1:N) | `backend/app/db/models/agents.py` |
| `AgentClientCreate` | schema | Client create payload (key_type, theming, origins, rate) | `backend/app/schemas/agent_client.py` |
| `ClientValidateRequest` / `ClientValidateResponse` | schema | Internal validation payloads | `backend/app/schemas/agent_client.py` |
| `generate_client_key` | function | Generate `phn_cl_sk_`/`phn_cl_pk_` credential | `backend/app/services/agent_client_service.py` |
| `hash_client_key` | function | SHA-256 hash a client credential | `backend/app/services/agent_client_service.py` |
| `validate_client_from_hash` | function | Resolve an active client by credential hash | `backend/app/services/agent_client_service.py` |
| `is_client_expired` | function | Expiry check | `backend/app/services/agent_client_service.py` |
| `create_client_usage_log` | function | Write an `AgentClientUsageLog` row | `backend/app/services/agent_client_service.py` |
| `AdminAgentClientRouter` | router | CC client CRUD routes (`/api/v1/clients`) | `backend/app/api/v1/agent_clients.py` |
| `validate_client_internal` | endpoint | Resolve client credential over mTLS | `backend/app/api/v1/internal/agent_client_validation.py` |
| `invoke_client_agent` | endpoint | Enqueue + trigger execution for a client | `backend/app/api/v1/internal/agent_client_invoke.py` |
| `require_client` | dependency | Validate client credential; origin + rate enforcement | `backend/app/communication_hub/integration/client_auth.py` |
| `is_rate_limited` | function | Per-client rate limit | `backend/app/communication_hub/integration/rate_limit.py` |
| `integration_router` | router | CH `/integrate/*` public routes | `backend/app/communication_hub/api/integration_gateway.py` |
| `chat` / `submit` | endpoints | Conversational / typed invocation (async session) | `backend/app/communication_hub/api/integration_gateway.py` |
| `get_config` | endpoint | White-label widget/theme config | `backend/app/communication_hub/api/integration_gateway.py` |
| `serve_js_sdk` | endpoint | JS SDK bundle | `backend/app/communication_hub/api/integration_gateway.py` |
| `AgentClientsPanel` | component | Clients list + create dialog + guide (agent-type **Clients tab** and global page) | `frontend/src/components/agents/AgentClientsPanel.tsx` |
| `AgentClientsPage` | component | Global clients page (wraps the panel) | `frontend/src/pages/agent-types/AgentClientsPage.tsx` |
| `fetchAgentClients` / `createAgentClient` / `revokeAgentClient` | functions | Frontend API client | `frontend/src/api/agentClientsApi.ts` |
| `ParthenonClient` / `ParthenonChat` | module | JS SDK: client + embeddable widget | `sdk/parthenon-js/index.js` |
| `Client` | class | Python SDK: request/response + server-side | `sdk/parthenon-python/parthenon/client.py` |
| `AgentClientDemoApp` | app | Standalone demo app (proxy + chat/form UI) | `agent-client-demo-app/demo_app/main.py` |
| `start.sh` / `stop.sh` / `start.ps1` / `stop.ps1` | scripts | Run the demo app on port 7002 | `agent-client-demo-app/` |
