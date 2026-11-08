# Implementation Plan: third-party-agent-integration

## Overview

Add a governed, secure way for third-party systems to invoke Parthenon **agent types** through **clients** — a client is a tenant-managed access grant bound to one agent type, with a `secret` (server-side) or `publishable` (browser-safe) credential. Clients grant input-interface-only access (conversation turn or typed submit) and are fully decoupled from agent identity: the existing API key (identity credential) is unchanged.

## Task Checklist

### Phase 1 — Client data model
- [x] 1.1 — Add `AgentClient` and `AgentClientUsageLog` models + enums
- [x] 1.2 — Add the `AgentType → AgentClient` relationship
- [x] 1.3 — Add client Pydantic schemas
- [x] 1.4 — Generate and apply the Alembic migration

### Phase 2 — Control Center client service & endpoints
- [x] 2.1 — Implement the client service (CRUD, credential hashing, resolution, logging)
- [x] 2.2 — Implement client management REST endpoints
- [x] 2.3 — Implement the internal client-validation endpoint (mTLS)

### Phase 3 — Communication Hub integration gateway
- [x] 3.1 — Implement the client-auth middleware (secret/publishable, origin + rate limit)
- [x] 3.2 — Implement `/integrate/chat` (streaming conversational turn)
- [x] 3.3 — Implement `/integrate/submit` (typed request/response)
- [x] 3.4 — Implement widget/theme and SDK serving

### Phase 4 — SDKs & example
- [x] 4.1 — Implement the JavaScript SDK
- [x] 4.2 — Implement the Python SDK
- [x] 4.3 — Implement the runnable local example
- [x] 4.4 — Write consumer integration guidance

### Phase 5 — Frontend management UI
- [x] 5.1 — Clients list for an agent type
- [x] 5.2 — Create-client dialog (secret/publishable) with soft warning
- [x] 5.3 — Revoke client with confirmation and parent-table refresh
- [x] 5.4 — Integration guide / embed snippet view

### Phase 6 — Testing
- [x] 6.1 — Backend tests (client model, CRUD, resolution, scope, rate/origin, audit)
- [x] 6.2 — Frontend tests (list, dialog, warning, guide)
- [x] 6.3 — E2E tests incl. a real-backend migration variant
- [x] 6.4 — SDK and example tests

### Phase 7 — Deployment, operations & docs
- [x] 7.1 — Configure origin/CORS and public endpoint exposure
- [x] 7.2 — Wire rate-limit/abuse monitoring, audit logging, OTEL
- [x] 7.3 — Update master docs (done via `/es-change-update-master`)

## Phase 1

### 1.1 — Client models
Create `backend/app/db/models/agent_client.py` with `AgentClient` (tenant, name, slug, `agent_type_id`, `key_type`, `key_hash`, `key_prefix`, `status`, white-label theme, allowed origins, rate limit, expiry) and `AgentClientUsageLog`, plus the `key_type` and `action` enums.
**Done when**: models import cleanly; `key_type` is immutable; publishable-only config fields are nullable.

### 1.2 — AgentType relationship
Add the `AgentType.clients` relationship (1:N) in `backend/app/db/models/agents.py` (no column change).
**Done when**: `agent_type.clients` resolves and the FK is defined on `agent_clients.agent_type_id`.

### 1.3 — Schemas
Create `backend/app/schemas/agent_client.py` with create/read/credential-read schemas.
**Done when**: schemas serialize all fields; `key_hash`/`key_prefix` are server-computed and the clear-text credential is returned exactly once.

### 1.4 — Migration
Run `alembic revision --autogenerate -m "third-party agent integration"`, review, then `alembic upgrade head`.
**Done when**: `alembic current` shows the new revision and the `agent_clients` + `agent_client_usage_logs` tables exist.

## Phase 2

### 2.1 — Client service
Create `backend/app/services/agent_client_service.py` for client CRUD, SHA-256 credential hashing with `phn_cl_sk_`/`phn_cl_pk_` prefixes, agent-type binding validation, per-tenant name uniqueness, and invocation logging.
**Done when**: create/read/revoke and credential issue/rotate behave as specified; `key_type` cannot be mutated after creation.

### 2.2 — Client endpoints
Create `backend/app/api/v1/agent_clients.py` exposing JWT-authenticated list/create/revoke + credential issue, gated by the existing agent-type management permission.
**Done when**: each endpoint validates input and returns the documented shape; publishable creation flags the soft warning.

### 2.3 — Internal validation endpoint
Create `backend/app/api/v1/internal/agent_client_validation.py` (mTLS) resolving a hashed client credential → `(client → agent type + config)`, returning no identity token for `publishable` and the validated optional end-user identity for `secret`.
**Done when**: valid credentials resolve; invalid/revoked/expired return a non-distinguishing 401.

## Phase 3

### 3.1 — Client-auth middleware
Create `backend/app/communication_hub/middleware/client_auth.py` detecting client credentials, calling CC resolution over mTLS, enforcing origin + rate limit, and attaching the resolved context (tokens held CH-side only).
**Done when**: origin-denied and rate-limited requests return graceful errors; no credential value or identity token crosses the external boundary.

### 3.2 — Conversational endpoint
Implement `/integrate/chat` streaming turns with heartbeats and guardrail/timeout error turns, delegating to the target agent type over the signed internal path.
**Done when**: a widget holds a multi-turn conversation; failures surface as error turns (no endless spinner).

### 3.3 — Request/response endpoint
Implement `/integrate/submit` returning a validated `AgentOutput` (validation status + raw-output fallback).
**Done when**: valid input returns a validated typed result; invalid input returns an actionable input-shape error.

### 3.4 — Widget/theme + SDK serving
Implement `/integrate/{client_ref}/config` and `/integrate/sdk/*`.
**Done when**: the widget renders with configured branding (no Parthenon branding) and SDK artifacts are retrievable.

## Phase 4

### 4.1 — JavaScript SDK
Implement `sdk/parthenon-js/` (embed + conversational turns + request/response).
**Done when**: the SDK mounts the widget and drives both flows against a local instance.

### 4.2 — Python SDK
Implement `sdk/parthenon-python/` (request/response + server-side conversational usage).
**Done when**: a Python client invokes a non-conversational agent and receives a validated typed result.

### 4.3 — Runnable example
Implement `examples/third-party-integration/` exercising both paths end-to-end.
**Done when**: the example runs locally with documented steps and no external dependencies.

### 4.4 — Consumer guidance
Write the embed snippet / connection guide and worked JS + Python examples.
**Done when**: an integrator can follow the guidance to embed a chatbot and wire a request/response flow.

## Phase 5

### 5.1 — Clients list
Create `frontend/src/pages/agent-types/AgentClientsList.tsx` showing a type's clients (name, key type, origins, rate limit, status).
**Done when**: the list renders real data and reflects CRUD changes without a manual reload.

### 5.2 — Create-client dialog
Create `frontend/src/pages/agent-types/CreateClientDialog.tsx` (secret/publishable, theming, origins, rate limit) with a soft warning for publishable, following the dialog error-handling standard.
**Done when**: creating a client persists correctly and surfaces the warning and any validation/permission errors.

### 5.3 — Revoke client
Implement revoke with confirmation and parent-table refresh.
**Done when**: revoking immediately renders the client as revoked and removes it from counts.

### 5.4 — Integration guide view
Create `frontend/src/pages/agent-types/IntegrationGuide.tsx` with copy-ready JS/Python snippets.
**Done when**: the guide renders accurate snippets matching the SDKs.

## Phase 6

### 6.1 — Backend tests
Cover client model, CRUD, resolution, input-interface-only scope, rate/origin enforcement, and audit under `backend/tests/`.
**Done when**: all pass, including negatives for out-of-scope behavior and real-DB constraint checks.

### 6.2 — Frontend tests
Cover the clients list, create dialog (warning), and guide under `frontend/src/__tests__/`.
**Done when**: Vitest passes with warning and dialog error-handling cases.

### 6.3 — E2E tests
Add E2E coverage under `e2e/tests/`, including a real-backend (no-mocks) variant labeled `Real Backend Integration - third-party-agent-integration`.
**Done when**: Playwright passes for the widget and request/response flows, including the migration check.

### 6.4 — SDK/example tests
Add JS/Python SDK tests and example end-to-end coverage.
**Done when**: both SDK suites and the example pass in the dev environment.

## Phase 7

### 7.1 — Origin/CORS + public exposure
Configure origin handling and nginx public routes for `/integrate/*`; add env vars for the public base URL.
**Done when**: allowlisted origins succeed and others are rejected in the deployed environment.

### 7.2 — Monitoring & audit
Wire rate-limit/abuse metrics, audit logging, and OTEL for client traffic.
**Done when**: client traffic is fully instrumented and rate-limit/abuse alerts are actionable.

### 7.3 — Master doc updates
Update `docs/master/architecture`, `data-model`, `product`, `qa`, `deployment`, and `operations` per the change docs' master-update instructions.
**Done when**: master docs reflect the new surface and the code reference map is current.

## Completion Checklist

- [x] `AgentClient` + `AgentClientUsageLog` migrated; `AgentType → AgentClient` relationship in place
- [x] Client CRUD + credential lifecycle working in Control Center; `key_type` immutable
- [x] Internal validation resolves clients with no identity token for publishable keys
- [x] CH gateway enforces origin + rate limits and serves chat, submit, widget, SDK
- [x] Conversational white-label widget and typed request/response work end-to-end
- [x] Clients grant input-interface-only access — no tool/identity access
- [x] JS + Python SDKs and runnable local example ship with guidance
- [x] Management UI lists/creates/revokes clients with the publishable soft warning
- [x] All backend, frontend, E2E, and SDK tests pass
- [x] Deployment and operations notes finalized; master docs updated
