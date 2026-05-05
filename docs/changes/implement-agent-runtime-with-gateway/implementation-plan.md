# Implementation Plan: Agent Runtime with Gateway

## Overview

This change introduces the Agent Runtime (powered by **LangGraph**), Agent Permission Manager, and Agent Session Queue as new core components, and extends the Communication Hub to serve as the Agent Gateway. The implementation rearchitects agent permission management from direct SOP/Skill bindings on AgentType to a role-based model via the new AgentRole entity, and replaces synchronous agent execution with a fully asynchronous session-queue pattern.

## Task Checklist

### Phase 1 — Database Schema and Models
- [x] 1.1 — Add AgentRole, AgentRoleSOP, AgentRoleSkill models
- [x] 1.2 — Add AgentIdentity model
- [x] 1.3 — Add AgentJob model (AgentSession)
- [x] 1.4 — Migrate AgentType fields (add identity_id, role_id, input_type, output_type; remove mode, sop_id, identity_subject, system_prompt, max_instances)
- [x] 1.5 — Remove AgentSkillAssignment model
- [x] 1.6 — Generate and verify Alembic migration
- [x] 1.7 — Add Alembic migration to add OAuth token fields to AgentIdentity schema

### Phase 2 — Backend Schemas and CRUD Services
- [x] 2.1 — Pydantic schemas for AgentRole CRUD
- [x] 2.2 — Pydantic schemas for AgentIdentity CRUD
- [x] 2.3 — Pydantic schemas for AgentSession (create, read, status)
- [x] 2.4 — Update AgentType schemas to match rearchitected fields
- [x] 2.5 — AgentRole CRUD service (create, list, get, update, delete)
- [x] 2.6 — AgentIdentity CRUD service
- [x] 2.7 — RealmManager: initialize and configure agent realm in OIDC provider
- [x] 2.8 — TokenRefreshService: background agent token refresh

### Phase 3 — Backend API Endpoints
- [x] 3.1 — Agent Role endpoints (GET/POST/PUT/DELETE /agents/roles)
- [x] 3.2 — Agent Identity endpoints (GET/POST/DELETE /agents/identities)
- [x] 3.3 — Agent Session endpoints (POST launch, GET status, GET result, WebSocket for conversational)
- [x] 3.4 — Permission preview endpoint (GET /agents/roles/{id}/mcp-tools)
- [x] 3.5 — Update existing AgentType endpoints to use new schema
- [x] 3.6 — OAuth authorize and callback endpoints for agent identity

### Phase 4 — Agent Permission Manager
- [x] 4.1 — PermissionManager service: resolve AgentRole → SOPs → Skills → MCP tools
- [x] 4.2 — Skill dependency graph traversal (SOP → Skills → Tool list)
- [x] 4.3 — Directly-assigned Skill → Tool resolution
- [x] 4.4 — Combined allow-set calculation and caching
- [x] 4.5 — Per-request permission enforcement hook for Agent Runtime

### Phase 5 — LangGraph Setup and Agent Session Queue
- [x] 5.1 — Install LangGraph dependency (`pip install langgraph`)
- [x] 5.2 — Define base LangGraph state schemas for task and conversational agents
- [x] 5.3 — AgentSession persistence service (enqueue, update status, persist result)
- [x] 5.4 — Session dispatcher: routes queued sessions to Agent Runtime workers
- [x] 5.5 — Agent Runtime executor: orchestrates LangGraph state graphs with LLM + Skill execution within permission boundaries
- [x] 5.6 — Communication Hub gateway extension: accept launch requests, return session ID, route results, maintain WebSocket for conversational agents
- [x] 5.7 — Result persistence via Result Repository (save_result MCP tool)
- [x] 5.8 — OTEL instrumentation for all session state transitions, LangGraph node transitions, and runtime actions
- [x] 5.9 — Bootstrap agent realm initialization via RealmManager

### Phase 6 — Frontend UI Components
- [x] 6.1 — Agent Role list page (table with SOP/Skill chips, MCP tool count)
- [x] 6.2 — Agent Role create/edit dialog (SOP and Skill multi-select, real-time MCP tool preview)
- [x] 6.3 — Agent Identity list and create/edit dialog
- [x] 6.4 — Update Agent Type form (identity_id, role_id, input_type, output_type, system_instruction)
- [x] 6.5 — Agent Session launch dialog (collect input per input_type, submit async)
- [x] 6.6 — Agent Session status and result view (polling for task agents, chat interface for conversational agents, status indicator, structured/markdown result)
- [x] 6.7 — Navigation wiring: Agent Roles and Agent Identities added to sidebar/routes
- [x] 6.8 — i18n strings for all new UI text
- [x] 6.9 — OAuth redirect handling in frontend (AgentOAuthCallbackPage, AppRouter route, i18n keys)

### Phase 7 — Integration and Testing
- [x] 7.1 — Backend unit tests: AgentRole CRUD, PermissionManager resolution, AgentSession state machine, LangGraph graph execution
- [x] 7.2 — Backend integration tests: full session lifecycle against real database (schema verified with alembic upgrade head)
- [x] 7.3 — Frontend unit tests: Role editor, MCP tool preview panel, Session launch/status components
- [x] 7.4 — E2E tests: agent role management, agent type configuration, session launch and result polling, conversational agent chat UI
- [x] 7.5 — E2E integration variant: at least one test hits real backend (no page.route() mocks) to validate migration

---

## Phase 1 — Database Schema and Models

### 1.1 — Add AgentRole, AgentRoleSOP, AgentRoleSkill models

Add three new SQLAlchemy declarative models to `backend/app/db/models/agents.py`: `AgentRole` (name, description, timestamps), `AgentRoleSOP` (composite PK on role_id + sop_id, FK to both tables), and `AgentRoleSkill` (composite PK on role_id + skill_id, FK to both tables). Include `relationship()` back-references on `AgentRole` for `sop_assignments` and `skill_assignments`.

**Done when**: Models are importable with no errors and appear in `Base.metadata.tables`.

### 1.2 — Add AgentIdentity model ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add `realm_name` (VARCHAR), `realm_username` (VARCHAR), AES-256 encrypted `access_token` (TEXT, nullable), encrypted `refresh_token` (TEXT, nullable), `token_expires_at` (TIMESTAMP WITH TIME ZONE, nullable) fields. Update `AgentIdentityType` enum value to `realm_user`.

Add `AgentIdentity` model to `backend/app/db/models/agents.py` with fields: `id`, `name`, `identity_type` (enum: `oauth`, `service_account`, `user_delegate`), `client_id`, `auth_provider`, `status` (enum: `active`, `suspended`, `deprovisioned`), `created_at`, `updated_at`. Add enums `AgentIdentityType` and `AgentIdentityStatus`.

**Done when**: Model is importable and all enum values are registered in the database session metadata.

### 1.3 — Add AgentJob model

Add `AgentJob` model to `backend/app/db/models/agents.py` with fields: `id`, `agent_type_id` (FK → agent_types), `triggered_by_user_id` (nullable FK → identities), `input_data` (JSON), `status` (enum: `queued`, `running`, `completed`, `failed`), `started_at`, `completed_at`, `output_data` (JSON), `error_message`, `created_at`. Add enum `AgentJobStatus`.

**Done when**: Model is importable; relationship from `AgentType` to `AgentJob` resolves correctly.

### 1.4 — Migrate AgentType fields

Update `AgentType` in `backend/app/db/models/agents.py`: add `identity_id` (FK → agent_identities, nullable), `role_id` (FK → agent_roles, nullable), `system_instruction` (Text), `input_type` (enum: `none`, `typed`, `conversation`), `input_schema` (JSON), `output_type` (enum: `auto`, `typed`, `markdown`), `output_schema` (JSON). Remove `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`. Update `relationship()` declarations accordingly.

**Done when**: `AgentType` has all new fields and none of the removed fields; `AgentMode` enum class can be removed.

### 1.5 — Remove AgentSkillAssignment model

Delete the `AgentSkillAssignment` class from `backend/app/db/models/agents.py` and remove all references from `AgentType.skill_assignments` relationship and any service/API imports.

**Done when**: `AgentSkillAssignment` is absent from the codebase; no import errors remain.

### 1.6 — Generate and verify Alembic migration

Run `alembic revision --autogenerate -m "agent-runtime-with-gateway"` from `backend/`. Review the generated migration for correctness: new tables created, old columns dropped, enum types added. Run `alembic upgrade head` against the local development database and verify with `alembic current`.

**Done when**: `alembic upgrade head` completes without error; `alembic current` shows the new revision head.

### 1.7 — Add Alembic migration for AgentIdentity OAuth token fields

Generate a new Alembic migration that alters the `agent_identities` table: add `realm_name` (VARCHAR NOT NULL), `realm_username` (VARCHAR NOT NULL), `access_token` (TEXT, nullable), `refresh_token` (TEXT, nullable), `token_expires_at` (TIMESTAMP WITH TIME ZONE, nullable). Update the `agentidentitytype` enum to add `realm_user`. Run `alembic upgrade head` and verify with `alembic current`.

**Done when**: `alembic upgrade head` applies without error; new columns appear in `information_schema.columns` for `agent_identities`; `agentidentitytype` enum contains `realm_user`.

---

## Phase 2 — Backend Schemas and CRUD Services

### 2.1 — Pydantic schemas for AgentRole CRUD

Add `AgentRoleCreate`, `AgentRoleUpdate`, and `AgentRoleRead` schemas to `backend/app/schemas/agents.py`. `AgentRoleRead` includes nested lists of assigned SOP IDs and Skill IDs. All fields use strong typing with Pydantic v2 `model_config = {"from_attributes": True}`.

**Done when**: Schemas import without errors and `AgentRoleRead.model_validate(role_orm_obj)` succeeds in a test.

### 2.2 — Pydantic schemas for AgentIdentity CRUD ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add `AgentIdentityOAuthAuthorizeResponse` schema (`authorization_url: str`). Update `AgentIdentityCreate` to include `realm_name` and `realm_username`. Update `AgentIdentityRead` to include `token_expires_at` (never expose raw token values).

Add `AgentIdentityCreate`, `AgentIdentityUpdate`, and `AgentIdentityRead` schemas to `backend/app/schemas/agents.py` using the `AgentIdentityType` and `AgentIdentityStatus` enums.

**Done when**: Schemas import without errors and pass a basic Pydantic validation test.

### 2.3 — Pydantic schemas for AgentJob

Add `AgentJobCreate` (agent_type_id, input_data), `AgentJobRead` (all fields), and `AgentJobStatusRead` (id, status, started_at, completed_at, error_message) to `backend/app/schemas/agents.py`.

**Done when**: All three schemas are importable and serialise correctly from ORM instances.

### 2.4 — Update AgentType schemas

Update `AgentTypeCreate`, `AgentTypeUpdate`, and `AgentTypeRead` in `backend/app/schemas/agents.py` to reflect new fields (`identity_id`, `role_id`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`) and remove old fields (`mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, `max_instances`). Add `AgentInputType` and `AgentOutputType` enums.

**Done when**: Schemas match the updated `AgentType` model; no references to removed fields remain in schemas.

### 2.5 — AgentRole CRUD service

Add `AgentRoleService` to `backend/app/services/agents/` with async methods: `create_role`, `list_roles`, `get_role`, `update_role`, `delete_role`. Handle SOP and Skill assignment via `AgentRoleSOP` and `AgentRoleSkill` join records within the same transaction.

**Done when**: Service methods execute against the test database without error; assignment records are created and deleted correctly.

### 2.6 — AgentIdentity CRUD service

> ⚠️ **REWORK REQUIRED**: Add `get_oauth_authorize_url(identity_id, redirect_uri) → str` that generates the authorization URL against the configured agent realm. Add `complete_oauth_flow(identity_id, code, redirect_uri)` that exchanges the authorization code for tokens and stores the AES-256 encrypted token pair on the identity record. Proactive background token refresh is handled by `TokenRefreshService`.

Add `AgentIdentityService` to `backend/app/services/agents/` with async methods: `create_identity`, `list_identities`, `get_identity`, `update_identity`, `delete_identity`. `delete_identity` must reject if any `AgentType` references the identity.

**Done when**: Service methods pass unit tests including the referential integrity rejection.

### 2.7 — RealmManager: initialize and configure agent realm in OIDC provider

Create `backend/app/services/identity/realm_manager.py` with `RealmManager`. Implement `initialize_agent_realm(realm_name: str)` that configures the agent realm in the OIDC provider (Keycloak): creates the realm if absent, applies token lifetime and session policies matching the user realm, and registers the platform's OAuth client for the authorization code flow with the callback `redirect_uri`. Read `agent_realm_name` from `config/identity.yaml` (default `ai_agents`). When `provider_type = external`, log a warning and skip initialization.

**Done when**: `initialize_agent_realm` runs without error against a local Keycloak instance; the realm exists with correct settings confirmed via the Keycloak admin API.

### 2.8 — TokenRefreshService: background agent token refresh

Create `backend/app/services/agents/token_refresh_service.py` with `TokenRefreshService`. Implement `refresh_token(identity_id, db)` that reads the stored encrypted refresh token from `AgentIdentity`, calls the agent realm token endpoint, and updates the identity record with the new encrypted access and refresh tokens. Implement `refresh_expiring_soon(db)` as a background worker method that queries all identities with `token_expires_at < now() + 5 min` and refreshes each.

**Done when**: `refresh_token` updates an identity's tokens in a unit test with a mocked IdP token endpoint; `refresh_expiring_soon` triggers refresh only for qualifying identities.

---

## Phase 3 — Backend API Endpoints

### 3.1 — Agent Role endpoints

Add `AgentRoleRouter` to `backend/app/api/v1/agents.py` with endpoints: `GET /agents/roles`, `POST /agents/roles`, `GET /agents/roles/{id}`, `PUT /agents/roles/{id}`, `DELETE /agents/roles/{id}`. All require `RT_AGENT` permission. Register the router in `backend/app/main.py`.

**Done when**: All five endpoints return correct HTTP status codes in integration tests; router is mounted and reachable.

### 3.2 — Agent Identity endpoints

> ⚠️ **REWORK REQUIRED**: Add `GET /agents/identities/oauth/authorize` (returns authorization URL) and `GET /agents/oauth/callback` (exchanges authorization code for tokens and stores encrypted token pair) to a new `AgentOAuthRouter`. Register in `backend/app/main.py`.

Add `AgentIdentityRouter` to `backend/app/api/v1/agents.py` with endpoints: `GET /agents/identities`, `POST /agents/identities`, `GET /agents/identities/{id}`, `PUT /agents/identities/{id}`, `DELETE /agents/identities/{id}`. Register in `backend/app/main.py`.

**Done when**: All endpoints are reachable and return typed responses matching `AgentIdentityRead`.

### 3.3 — Agent Session endpoints

Add session endpoints to `backend/app/api/v1/agents.py`: `POST /agents/sessions` (enqueue, returns 202 + session ID), `GET /agents/sessions/{id}` (status), `GET /agents/sessions/{id}/result` (full output once completed), `GET /agents/sessions` (list for current user). For conversational agents, add WebSocket endpoint `WS /agents/sessions/{id}/chat`. Register in `backend/app/main.py`.

**Done when**: Launch endpoint returns 202 with a valid session ID; status endpoint reflects correct `AgentSessionStatus` at each stage; WebSocket connection works for conversational agents.

### 3.4 — Permission preview endpoint

Add `GET /agents/roles/{id}/mcp-tools` to `AgentRoleRouter`. Calls `PermissionManager.calculate_allowed_tools(role_id)` and returns a list of MCP tool identifiers. Used by the frontend real-time preview.

**Done when**: Endpoint returns the correct tool list for a role with assigned SOPs and Skills in an integration test.

### 3.5 — Update AgentType endpoints

Update existing `AgentTypeRouter` handlers in `backend/app/api/v1/agents.py` to accept and return the rearchitected `AgentTypeCreate`/`AgentTypeRead` schemas. Remove all references to `mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, and `max_instances`.

**Done when**: `GET /agents/types` and `POST /agents/types` pass integration tests using new schema; old field names return 422 if sent.

### 3.6 — OAuth authorize and callback endpoints for agent identity

Add `AgentOAuthRouter` to `backend/app/api/v1/agents.py`. Implement `GET /agents/identities/oauth/authorize?identity_id=<uuid>` that validates the identity record, generates the OAuth authorization URL against the configured agent realm, encodes `identity_id` in the `state` parameter, and returns `AgentIdentityOAuthAuthorizeResponse`. Implement `GET /agents/oauth/callback?code=...&state=...` that validates the state, calls `AgentIdentityService.complete_oauth_flow`, and returns the updated `AgentIdentityRead`. Register the router in `backend/app/main.py`. Both endpoints require `RT_AGENT` permission.

**Done when**: The authorize endpoint returns a valid authorization URL in an integration test; the callback endpoint processes a valid code, updates identity tokens, and returns `AgentIdentityRead` with `token_expires_at` populated.

---

## Phase 4 — Agent Permission Manager

### 4.1 — PermissionManager service: role → SOP → Skill → MCP tool resolution

Create `backend/app/services/agents/permission_manager.py` with `AgentPermissionManager` class. Implement `calculate_allowed_tools(role_id, db)` as the primary public method that returns a set of allowed MCP tool identifiers.

**Done when**: `calculate_allowed_tools` returns a non-empty set for a role with at least one SOP assigned in a unit test.

### 4.2 — Skill dependency graph traversal

Implement the SOP → Skill resolution step within `AgentPermissionManager`. Query `AgentRoleSOP` for the role, then for each SOP retrieve all associated Skill IDs from the SOP's skill dependency records. Merge with the role's directly assigned skills from `AgentRoleSkill`.

**Done when**: Given a role with SOP A (containing Skills X and Y), the traversal returns {X, Y}; given a role also directly assigning Skill Z, the result is {X, Y, Z}.

### 4.3 — Tool set resolution from Skills

For the unified skill set, query each Skill's required MCP tool records to produce the allowed tool identifier set.

**Done when**: Unit test with known Skill → Tool mappings produces the exact expected tool set.

### 4.4 — Combined allow-set calculation and caching

Wrap `calculate_allowed_tools` with an in-process LRU cache keyed on `role_id`. Invalidate the cache entry on any `AgentRole`, `AgentRoleSOP`, or `AgentRoleSkill` write operation (via service layer hooks).

**Done when**: Repeated calls with the same `role_id` do not issue additional database queries; cache invalidates after a role update.

### 4.5 — Per-request permission enforcement in Agent Runtime

Integrate `AgentPermissionManager.calculate_allowed_tools` into the Agent Runtime executor so that every MCP tool call is validated against the allowed set before dispatch. Denied tool calls raise a structured `PermissionDeniedError` that is recorded on the `AgentSession`.

**Done when**: A runtime test attempting a disallowed tool call results in `AgentSession.status = failed` with `error_message` referencing the denied tool.

---

## Phase 5 — LangGraph Setup and Agent Session Queue

### 5.3 — AgentSession persistence service

Create `backend/app/services/agents/session_service.py` with `AgentSessionService`: `enqueue(agent_type_id, input_data, user_id) → AgentSession`, `mark_running(session_id)`, `mark_completed(session_id, output_data)`, `mark_failed(session_id, error_message)`, `get_session(session_id) → AgentSession`.

**Done when**: All state transition methods update `AgentSession.status` and timing fields correctly; unit tests cover all four status values.

### 5.4 — Session dispatcher

Create `backend/app/services/agents/session_dispatcher.py`. Implement a background worker (async task or Redis-backed queue consumer) that polls for `queued` sessions and dispatches them to `AgentRuntimeExecutor`. Respects agent type concurrency limits from operational configuration.

**Done when**: A queued session transitions to `running` within the dispatch interval and then to `completed` or `failed` after executor returns.

### 5.5 — Agent Runtime executor with LangGraph

Update `backend/app/services/agents/` to implement `AgentRuntimeExecutor.run(session: AgentSession)` powered by **LangGraph**: fetches the `AgentType` and its `AgentRole`, calls `AgentPermissionManager.calculate_allowed_tools`, authenticates using `AgentIdentity` OIDC credentials, constructs a LangGraph state machine for the agent type (task vs conversational), and executes the graph with the allowed tool set. Persists the result. Removes the old `sop_executor.py` / `skillful_executor.py` split in favour of the role-governed LangGraph-based unified path.

**Done when**: An integration test with a seeded role, agent type, and session runs end-to-end and produces a persisted `output_data` on the session record, with LangGraph node transitions visible in OTEL traces.

### 5.6 — Communication Hub gateway extension

Update `backend/app/services/gateway/lifecycle_handler.py` to route inbound agent launch requests through `AgentSessionService.enqueue` and return the session ID synchronously. For conversational agents, establish and maintain WebSocket connections. Remove legacy synchronous execution path from `registry.py`.

**Done when**: POST to the gateway launch endpoint returns HTTP 202 with `{"session_id": "<uuid>"}` without blocking; WebSocket connections work for conversational agents.

### 5.7 — Result persistence via Result Repository

Ensure the `save_result` MCP tool is available in the allowed tool set for all agent roles (injected automatically by the runtime). Update `AgentRuntimeExecutor` to call `save_result` with the structured output before marking the session completed.

**Done when**: Completed sessions have a corresponding record in the results table accessible via `GET /agents/sessions/{id}/result`.

### 5.8 — OTEL instrumentation with LangGraph support

Add OpenTelemetry spans and structured log events to `AgentSessionService` (enqueue, state transitions), `AgentRuntimeExecutor` (session start, LangGraph node transitions, skill calls, tool calls, session end), and `AgentPermissionManager` (allow/deny decisions). Follow the project's OTEL conventions from `config/telemetry.yaml`.

**Done when**: Running a session end-to-end produces OTEL trace spans for enqueue → dispatch → permission evaluation → LangGraph node transitions → skill execution → result persist → session complete.

### 5.9 — Bootstrap agent realm initialization via RealmManager

Update the platform bootstrap sequence (first-run setup wizard and startup path) to call `RealmManager.initialize_agent_realm` using `agent_realm_name` from `config/identity.yaml` (default `ai_agents`). Extend `config/identity.yaml` schema with the `agent_realm_name` field and update the setup wizard to collect and write it. When `provider_type = keycloak_bundled`, run `initialize_agent_realm` automatically on startup if the realm does not exist; when `provider_type = external`, log a warning that the agent realm must be pre-configured manually.

**Done when**: On first run with `keycloak_bundled` provider, the agent realm is present in Keycloak with correct token policies; `config/identity.yaml` contains `agent_realm_name`; startup logs confirm realm initialization was attempted.

---

## Phase 6 — Frontend UI Components

### 6.1 — Agent Role list page

Create `frontend/src/pages/agents/AgentRoleListPage.tsx`. Display a `DataGrid` or table listing all agent roles with columns: Name, Description, Assigned SOPs (chips), Assigned Skills (chips), Allowed MCP Tools (count chip), Actions. Fetch from `GET /agents/roles`. Add toolbar button to open the create dialog.

**Done when**: Page renders the role list with correct SOP/Skill chips and MCP tool count; loading and empty states handled.

### 6.2 — Agent Role create/edit dialog

Create `frontend/src/pages/agents/AgentRoleDialog.tsx`. Include name/description fields, a multi-select for SOPs, a multi-select for Skills, and a real-time MCP tool preview panel that calls `GET /agents/roles/{id}/mcp-tools` (or a local calculation endpoint) whenever the SOP/Skill selection changes. Follow the Dialog Error Handling Standard (dialogError state + PermissionDeniedAlert).

**Done when**: Creating a role with two SOPs populates the MCP tool preview; saving posts to `POST /agents/roles`; errors display in the dialog.

### 6.3 — Agent Identity list and dialog

> ⚠️ **REWORK REQUIRED**: Add a "Sign In as Agent" button to `AgentIdentityDialog` that calls `GET /agents/identities/oauth/authorize?identity_id=<id>`, opens the returned `authorization_url` in a popup window, and polls or waits for the OAuth callback to complete. After the OAuth flow, refresh the identity record to show `status: active` and `token_expires_at`. Add the `/agents/identities/oauth/callback` route to the frontend router.

Create `frontend/src/pages/agents/AgentIdentityListPage.tsx` and `AgentIdentityDialog.tsx`. List page shows identity name, type, auth_provider, status. Dialog handles create and edit with dropdown for `identity_type` and `status`. Follow Dialog Error Handling Standard.

**Done when**: List page fetches and renders identities; dialog creates and edits via `POST`/`PUT /agents/identities`.

### 6.4 — Update Agent Type form

Update `frontend/src/pages/agents/AgentTypeForm.tsx` to replace removed fields (`mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, `max_instances`) with the new fields: `identity_id` (select from identities), `role_id` (select from roles), `system_instruction` (textarea), `input_type` (select enum), `input_schema` (JSON editor, shown when `input_type = typed`), `output_type` (select enum), `output_schema` (JSON editor, shown when `output_type = typed`). All UI text via i18n.

**Done when**: Form submits with new fields and receives 201/200 from the updated backend endpoints; removed fields are absent from the form.

### 6.5 — Agent Session launch dialog

Create `frontend/src/pages/agents/AgentSessionLaunchDialog.tsx`. Opens from the Agent Management page per agent type. Renders the appropriate input form based on `input_type` (`none` → confirm only, `typed` → form fields from `input_schema`, `conversation` → text area). Submits to `POST /agents/sessions` and displays the returned session ID with a link to the status view (or chat interface for conversational agents). Follow Dialog Error Handling Standard.

**Done when**: Launching a session with each `input_type` variant posts correctly; session ID is shown to the user immediately; conversational agents open chat UI.

### 6.6 — Agent Session status and result view

Create `frontend/src/pages/agents/AgentJobPage.tsx`. Display session metadata (agent type, triggered by, timestamps), live status indicator with polling (`GET /agents/sessions/{id}` every 3 seconds while `status = queued | running`) **for task agents**, and a chat interface (similar to VS Code chat sessions) **for conversational agents**. Result section renders as structured data or markdown depending on `output_type` when completed.

**Done when**: Page polls correctly for task agents and stops on terminal status; conversational agents show chat UI with message history; result renders in both `typed` and `markdown` formats.

### 6.7 — Navigation wiring

Add route entries in `frontend/src/app/` for: `/agents/roles` → `AgentRoleListPage`, `/agents/identities` → `AgentIdentityListPage`, `/agents/sessions/:id` → `AgentJobPage`. Add sidebar navigation items for "Agent Roles" and "Agent Identities" under the Agents section.

**Done when**: All new routes resolve correctly; sidebar items navigate to the correct pages; active state highlights correctly.

### 6.8 — i18n strings

Add all new UI text keys to `frontend/src/i18n/` locale files (English at minimum). Cover all labels, headings, dialog titles, button labels, status values, error messages, and empty state text introduced in 6.1–6.7.

**Done when**: No hardcoded strings remain in new components; switching locale displays translated strings where translations are provided.

### 6.9 — OAuth redirect handling in frontend

Add an `AgentOAuthCallbackPage` component at route `/agents/identities/oauth/callback` that reads `code` and `state` from URL params, calls `GET /agents/oauth/callback` on the backend to exchange the code (or proxies the redirect), then closes the popup and signals the opener `AgentIdentityDialog` to refresh the identity record. Update `AgentIdentityDialog` to include the "Sign In as Agent" OAuth button with `oauthInitiating` loading state and to handle the popup close/success signal. Add `agents.identities.oauthSignIn`, `agents.identities.oauthPending`, and `agents.identities.oauthSuccess` i18n keys.

**Done when**: Clicking "Sign In as Agent" opens the Keycloak agent realm login; after sign-in the identity shows `status: active` and `token_expires_at` is populated; popup closes cleanly; all OAuth flow strings go through i18n.

---

## Phase 7 — Integration and Testing

### 7.1 — Backend unit tests

Add tests in `backend/tests/unit/` and `backend/tests/services/` covering: `AgentRoleService` CRUD, `AgentIdentityService` referential integrity check, `AgentPermissionManager` tool resolution with SOP and direct Skill paths, `AgentJobService` all four status transitions.

**Done when**: All new unit tests pass; coverage for new service modules ≥ 80%.

### 7.2 — Backend integration tests

Add tests in `backend/tests/integration/` that: apply `alembic upgrade head` as a fixture step, create a role with SOPs/Skills, launch a session, confirm it transitions to `completed` with output (with LangGraph state traces visible), and verify schema correctness by querying `information_schema.columns` for new columns. Include negative tests for permission denial.

**Done when**: Integration tests pass against the real database; `alembic upgrade head` completes as part of test setup.

### 7.3 — Frontend unit tests

Add tests in `frontend/src/__tests__/` covering: `AgentRoleDialog` SOP/Skill selection and MCP tool preview fetch trigger, `AgentSessionLaunchDialog` input rendering per `input_type`, `AgentJobPage` polling behaviour for task agents and chat UI for conversational agents, result rendering.

**Done when**: All new frontend unit tests pass with no regressions in existing tests.

### 7.4 — E2E tests

Add `e2e/tests/agent-runtime.spec.ts` with test suites: Agent Role Management (create, assign SOPs/Skills, verify MCP tool count), Agent Type Configuration (create with role and identity, verify new fields), Agent Session Lifecycle (launch, poll to completion for task agents, chat UI interaction for conversational agents, view result). Use `page.route()` mocks for speed.

**Done when**: All E2E tests pass in the `chromium` project against the dev configuration.

### 7.5 — E2E integration variant

Add at least one `test.describe('Real Backend Integration — Agent Session Lifecycle')` block within `e2e/tests/agent-runtime.spec.ts` that does not mock any API calls, hits the real backend with the real database, launches a session, polls to completion, and asserts the result. Label clearly to allow selective CI execution.

**Done when**: The integration variant test passes with real backend running; validates migration was applied correctly.

---

## Completion Checklist

- [ ] All Alembic migrations applied and verified with `alembic current`
- [ ] All backend unit tests passing
- [ ] All backend integration tests passing against real database
- [ ] All frontend unit tests passing
- [ ] All E2E tests passing (mocked)
- [ ] E2E integration variant passing against real backend
- [ ] No hardcoded UI strings (all through i18n)
- [ ] OTEL instrumentation verified end-to-end
- [ ] Architecture master docs updated per `architecture.md` instructions
- [ ] No references to removed fields (`mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `AgentSkillAssignment`) remain in codebase
