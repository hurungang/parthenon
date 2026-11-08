# Module: third-party-agent-integration — Tech Spec

## Overview

This module introduces a new primitive — the **client** — that grants third-party access to an agent type's *input interface* (conversation turn or typed submit). A client is a separate credential class from the existing **API key**: an API key authenticates *as* an agent identity (+ role) for MCP tool access (unchanged), while a client is bound to one agent type and can only invoke it. Clients carry a `key_type` of `secret` (server-side) or `publishable` (browser-safe), plus white-label theme, allowed origins, and a rate limit. Because a client is not an identity, it cannot list/call tools, reach the MCP hub, or impersonate an agent — the invoked agent type runs with its own identity + role as configured.

**Critical architectural constraints:**

- Only Control Center connects to the database — Communication Hub has no database access
- All CH→CC calls are mTLS-secured with service certificates
- The resolved agent identity token (and, for `secret` clients, the optional validated end-user token) is held CH-side and injected per call — never serialized to the client
- The client credential value is stored only as a SHA-256 hash; the clear-text is shown once at issuance/rotation
- Client invocation never derives an identity from the client — Agent Runtime executes the target agent type with its own identity + role

---

## Key Components

### Backend Components (Control Center)

| Component | Description |
|-----------|-------------|
| `AgentClient` | Tenant-owned access grant bound to exactly one `AgentType`; holds the credential (hash/prefix/`key_type`/status), white-label theme, allowed origins, and rate-limit config |
| `AgentClientUsageLog` | Append-only audit record per invocation (action = `conversation_turn`/`submit_request`); never stores the credential value |
| Client service | Create/list/revoke clients; enforce `key_type` immutability, per-tenant uniqueness, and the publishable-credential soft-warning; resolve a client credential → agent type + config |
| Client management endpoints | JWT-authenticated admin routes for client CRUD and credential issuance/revocation |
| Client validation endpoint | Internal (mTLS) resolution of a hashed client credential → `(client → agent type + config)`; returns **no agent identity token**; a `secret` client may additionally carry a validated optional end-user identity for server-side dual identity |

### Backend Components (Communication Hub)

| Component | Description |
|-----------|-------------|
| Client auth middleware | Detects client credentials, calls CC resolution over mTLS, enforces origin + rate limit, and attaches the resolved client context (tokens held CH-side only) |
| Rate limiting | Per-client Redis counters with per_minute/per_hour/per_day windows |
| Integration gateway | `/integrate/*` router: conversational chat (stateful sessions), typed submit (async sessions, non-conversational types only), widget/theme config serving, SDK distribution |

### SDKs and Example

| Component | Description |
|-----------|-------------|
| JS SDK | `ParthenonClient` + embeddable `ParthenonChat` widget (turns + request/response) |
| Python SDK | `Client` for request/response and server-side (secret-client) usage |
| Demo app | Standalone runnable demo (proxy + chat/form UI) on port 7002 |

---

## API Surface Summary

### Control Center — Admin (JWT)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/clients` | List clients (optional `agent_type_id` filter) |
| `POST` | `/api/v1/clients` | Create a client (secret/publishable) |
| `POST` | `/api/v1/clients/{id}/credential` | Rotate credential (clear-text shown once) |
| `PATCH` | `/api/v1/clients/{id}` | Edit allowed origins + rate limit (only mutable fields) |
| `PATCH` | `/api/v1/clients/{id}/status` | Activate/deactivate a client (`active`/`inactive`) |
| `DELETE` | `/api/v1/clients/{id}` | Remove a client (hard delete, cascades usage logs) |

### Control Center — Internal (service certificate / mTLS)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/internal/clients/validate` | Resolve client credential → agent type + config (**exempt from tenant headers** — it discovers the tenant) |
| `POST` | `/api/v1/internal/clients/invoke` | Enqueue + trigger agent execution for a client |

### Communication Hub — Public gateway (client credential)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/integrate/config` | Public widget/theme config (white-label) |
| `POST` | `/integrate/conversations` | Start a **stateful** conversation session (conversational types only) |
| `POST` | `/integrate/conversations/{id}/messages` | Send a message in the conversation (stateful; returns reply) |
| `POST` | `/integrate/conversations/{id}/end` | End the conversation session |
| `POST` | `/integrate/submit` | Typed request/response for **non-conversational** types (async session id; rejected for conversational types) |
| `GET` | `/integrate/session/{id}` | Poll an execution session's status/output |
| `GET` | `/integrate/sdk/parthenon-chat.js` | JS SDK bundle (public) |
| `GET` | `/integrate/sdk/parthenon-python` | Python SDK metadata (public) |

No existing endpoint is removed or deprecated; API-key (identity) endpoints and the MCP protocol server are unchanged.

---

## Data Access Patterns

- **Control Center** is the sole database owner: client CRUD, credential resolution, and usage-log writes all go through CC.
- **Communication Hub** has no direct DB access: it validates client credentials over mTLS and routes execution to Agent Runtime over the signed internal path.
- **Agent Runtime** executes the target agent type with its own identity + role; no identity is derived from the client.
- **Frontend** calls CC REST APIs over JWT; no direct DB access.

Server-side state is the resolved client context held by the CH client-auth middleware (client id, `key_type`, agent type, theming/origin/rate config, rate counters) — never the credential value.

---

## Code Reference Map

### Database Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentClient` | model | Access grant bound to an agent type | `backend/app/db/models/agent_client.py` |
| `AgentClientUsageLog` | model | Per-invocation audit record | `backend/app/db/models/agent_client.py` |
| `AgentClientKeyType` | enum | `secret` / `publishable` | `backend/app/db/models/agent_client.py` |
| `AgentClientStatus` | enum | `active` / `revoked` | `backend/app/db/models/agent_client.py` |
| `AgentClientRateLimitWindow` | enum | `per_minute` / `per_hour` / `per_day` | `backend/app/db/models/agent_client.py` |
| `AgentClientAction` | enum | `conversation_turn` / `submit_request` | `backend/app/db/models/agent_client.py` |
| `AgentType.clients` | relationship | Agent type → its clients (1:N) | `backend/app/db/models/agents.py` |

### Schemas (Control Center)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentClientCreate` | schema | Client create payload (key_type, theming, origins, rate) | `backend/app/schemas/agent_client.py` |
| `ClientValidateRequest` / `ClientValidateResponse` | schema | Internal validation payloads | `backend/app/schemas/agent_client.py` |

### Client Service (Control Center)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `generate_client_key` | function | Generate `phn_cl_sk_`/`phn_cl_pk_` credential | `backend/app/services/agent_client_service.py` |
| `hash_client_key` | function | SHA-256 hash a client credential | `backend/app/services/agent_client_service.py` |
| `validate_client_from_hash` | function | Resolve an active client by credential hash | `backend/app/services/agent_client_service.py` |
| `is_client_expired` | function | Expiry check | `backend/app/services/agent_client_service.py` |
| `create_client_usage_log` | function | Write an `AgentClientUsageLog` row | `backend/app/services/agent_client_service.py` |

### Control Center Endpoints

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AdminAgentClientRouter` | router | CC client CRUD routes (`/api/v1/clients`) | `backend/app/api/v1/agent_clients.py` |
| `validate_client_internal` | endpoint | Resolve client credential over mTLS | `backend/app/api/v1/internal/agent_client_validation.py` |
| `invoke_client_agent` | endpoint | Enqueue + trigger execution for a client | `backend/app/api/v1/internal/agent_client_invoke.py` |

### Communication Hub — Integration Gateway

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `require_client` | dependency | Validate client credential; origin + rate enforcement | `backend/app/communication_hub/integration/client_auth.py` |
| `is_rate_limited` | function | Per-client rate limit | `backend/app/communication_hub/integration/rate_limit.py` |
| `integration_router` | router | CH `/integrate/*` public routes | `backend/app/communication_hub/api/integration_gateway.py` |
| `chat` / `submit` | endpoints | Conversational / typed invocation (async session) | `backend/app/communication_hub/api/integration_gateway.py` |
| `get_config` | endpoint | White-label widget/theme config | `backend/app/communication_hub/api/integration_gateway.py` |
| `serve_js_sdk` | endpoint | JS SDK bundle | `backend/app/communication_hub/api/integration_gateway.py` |

### Frontend

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentClientsPanel` | component | Clients list + create dialog + guide (agent-type **Clients tab** and global page) | `frontend/src/components/agents/AgentClientsPanel.tsx` |
| `AgentClientsPage` | component | Global clients page (wraps the panel) | `frontend/src/pages/agent-types/AgentClientsPage.tsx` |
| `fetchAgentClients` / `createAgentClient` / `revokeAgentClient` | functions | Frontend API client | `frontend/src/api/agentClientsApi.ts` |

### SDKs and Demo App

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ParthenonClient` / `ParthenonChat` | module | JS SDK: client + embeddable widget | `sdk/parthenon-js/index.js` |
| `Client` | class | Python SDK: request/response + server-side | `sdk/parthenon-python/parthenon/client.py` |
| `AgentClientDemoApp` | app | Standalone demo app (proxy + chat/form UI) | `agent-client-demo-app/demo_app/main.py` |
| `start.sh` / `stop.sh` / `start.ps1` / `stop.ps1` | scripts | Run the demo app on port 7002 | `agent-client-demo-app/` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| Client service + admin API tests | tests | Backend unit/integration coverage for clients | `backend/tests/test_agent_client.py` |
| Integration gateway tests | tests | CH gateway, auth middleware, rate limiting | `backend/tests/test_integration_gateway.py` |
| AgentClientsPage tests | tests | Frontend page/component tests | `frontend/src/__tests__/agent-clients/AgentClientsPage.test.tsx` |
| Agent clients E2E | tests | End-to-end browser coverage | `e2e/tests/agent-clients.spec.ts` |
| Python SDK tests | tests | Python client tests | `sdk/parthenon-python/test/test_client.py` |
