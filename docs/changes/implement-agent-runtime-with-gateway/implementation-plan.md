# Implementation Plan: Agent Runtime with Gateway

## Overview

This change introduces the Agent Runtime (powered by the **LangChain deep agent** framework), Agent Permission Manager, and Agent Session Queue as new core components, and extends the Communication Hub to serve as the Agent Gateway. The implementation rearchitects agent permission management from direct SOP/Skill bindings on AgentType to a role-based model via the new AgentRole entity, and replaces synchronous agent execution with a fully asynchronous session-queue pattern. Execution logs capture the full system instruction and user prompt before the first LLM call for complete traceability.

## Task Checklist

### Phase 1 — Database Schema and Models
- [x] 1.1 — Add AgentRole, AgentRoleSOP, AgentRoleSkill models
- [x] 1.2 — Add AgentIdentity model
- [x] 1.3 — Add AgentJob model (AgentSession)
- [x] 1.3a — Add allowed_identity_types field to AgentRole model (JSON array, defaults to []) ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 1.3b — DROP allowed_identity_types column from agent_roles table
- [x] 1.3c — CREATE agent_role_identities join table (role_id, identity_id, assigned_at, assigned_by, unique constraint)
- [x] 1.3d — Generate Alembic migration for schema changes
- [x] 1.4 — Migrate AgentType fields (add identity_id, role_id, input_type, output_type; remove mode, sop_id, identity_subject, system_prompt, max_instances) ⚠️ NEEDS REWORK
- [x] 1.5 — Remove AgentSkillAssignment model
- [x] 1.6 — Generate and verify Alembic migration
- [x] 1.7 — Add Alembic migration to add OAuth token fields to AgentIdentity schema
- [x] 1.8 — Add ModelConfig model (provider, model_name, encrypted credentials, config) ⚠️ NEEDS REWORK
- [x] 1.9 — Update AgentType model: remove LLM fields, add model_id FK ⚠️ NEEDS REWORK
- [x] 1.10 — Add conversation_history field to AgentJob model
- [x] 1.11 — Generate and verify Alembic migration for ModelConfig and AgentType updates

### Phase 2 — Backend Schemas and CRUD Services
- [x] 2.1 — Pydantic schemas for AgentRole CRUD
- [x] 2.1a — Update AgentRoleCreate and AgentRoleUpdate schemas to include allowed_identity_types field ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 2.1b — REMOVE allowed_identity_types from AgentRoleCreate/Update/Read schemas
- [x] 2.1c — ADD AgentRoleIdentityAssignment schema
- [x] 2.2 — Pydantic schemas for AgentIdentity CRUD
- [x] 2.3 — Pydantic schemas for AgentSession (create, read, status)
- [x] 2.4 — Update AgentType schemas to match rearchitected fields ⚠️ NEEDS REWORK
- [x] 2.5 — AgentRole CRUD service (create, list, get, update, delete)
- [x] 2.6 — AgentIdentity CRUD service
- [x] 2.7 — RealmManager: initialize and configure agent realm in OIDC provider
- [x] 2.8 — TokenRefreshService: background agent token refresh
- [x] 2.9 — Pydantic schemas for ModelConfig CRUD
- [x] 2.10 — ModelConfigService CRUD with credential encryption
- [x] 2.11 — Add `fetch_available_models(config_id)` method to ModelConfigService

### Phase 3 — Backend API Endpoints
- [x] 3.1 — Agent Role endpoints (GET/POST/PUT/DELETE /agents/roles)
- [x] 3.1a — Add query param support to GET /agents/roles endpoint for filtering by allowed_for_identity_type ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 3.1b — Add identity→role validation in AgentRuntimeExecutor.run() before session execution ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 3.1c — ADD endpoints: POST/DELETE/GET /agents/roles/{id}/identities
- [x] 3.1d — ADD endpoints: POST/DELETE/GET /agents/identities/{id}/roles
- [x] 3.1e — ADD endpoints: POST /agents/identities/{id}/refresh-token, GET /agents/identities/{id}/reauth-url
- [x] 3.1f — REMOVE allowed_for_identity_type filter from GET /agents/roles
- [x] 3.2 — Agent Identity endpoints (GET/POST/DELETE /agents/identities)
- [x] 3.3 — Agent Session endpoints (POST launch, GET status, GET result, WebSocket for conversational) ⚠️ NEEDS REWORK
- [x] 3.4 — Permission preview endpoint (GET /agents/roles/{id}/mcp-tools)
- [x] 3.5 — Update existing AgentType endpoints (use model_id not model_config_id) ⚠️ NEEDS REWORK
- [x] 3.6 — OAuth authorize and callback endpoints for agent identity
- [x] 3.7 — ModelConfig CRUD endpoints (GET/POST/PUT/DELETE /agents/model-configs) + GET /agents/model-configs/{id}/models ⚠️ NEEDS REWORK
- [ ] 3.8 — Update AgentSession list endpoint with status, date, and agent_type filters
- [ ] 3.9 — Add conversation history endpoint (GET /agents/sessions/{id}/history)

### Phase 4 — Agent Permission Manager
- [x] 4.1 — PermissionManager service: resolve AgentRole → SOPs → Skills → MCP tools
- [x] 4.2 — Skill dependency graph traversal (SOP → Skills → Tool list)
- [x] 4.3 — Directly-assigned Skill → Tool resolution
- [x] 4.4 — Combined allow-set calculation and caching
- [x] 4.4a — Fix tool identifier format in _resolve_tools_from_skills(): use mcp_slug/tool_name (not server_slug:tool_name)
- [x] 4.4b — Remove incorrect prefix stripping logic in runtime_executor._load_tool_definitions()
- [x] 4.4c — UPDATE permission_manager: remove any allowed_identity_types logic
- [x] 4.4d — UPDATE runtime_executor validation: check agent_role_identities membership
- [x] 4.4e — ADD identity_service methods: refresh_token(), get_reauth_url()
- [x] 4.4f — ADD role_service methods: assign_identities(), remove_identity(), list_identities()
- [x] 4.5 — Per-request permission enforcement hook for Agent Runtime

### Phase 5 — LangChain Deep Agent Setup and Session Queue
- [x] 5.1 — Replace `langgraph` with `langchain` + `langchain-community` in pyproject.toml
- [x] 5.2 — Define LangChain agent loop context dataclasses (TaskAgentLoop, ConversationalAgentLoop) in agent_loop.py
- [x] 5.3 — AgentSession persistence service (enqueue, update status, persist result)
- [x] 5.4 — Session dispatcher: routes queued sessions to Agent Runtime workers
- [x] 5.5 — Agent Runtime executor: observe-reason-act loop via LangChain deep agent framework
- [x] 5.6 — Communication Hub gateway extension: accept launch requests, return session ID, route results, maintain WebSocket for conversational agents
- [x] 5.6a — Add OAuth middleware to Communication Hub for agent identity token validation
- [x] 5.6b — Implement role-based tool filtering in LifecycleHandler (expose tools without descriptions/schemas)
- [x] 5.7 — Result persistence via Result Repository (save_result MCP tool)
- [x] 5.8 — OTEL instrumentation for session state transitions and LangChain agent.observe/agent.reason/agent.act spans
- [x] 5.9 — Bootstrap agent realm initialization via RealmManager
- [x] 5.10 — Replace LangGraph with LangChain deep agent observe-reason-act loop in `runtime_executor.py`
- [x] 5.11 — Add `AgentPromptLog` model and capture full system instruction and user prompt before first LLM call

### Phase 6 — Frontend UI Components
- [x] 6.1 — Agent Role list page (table with SOP/Skill chips, MCP tool count)
- [x] 6.2 — Agent Role create/edit dialog (SOP and Skill multi-select, real-time MCP tool preview)
- [x] 6.3 — Agent Identity list and create/edit dialog
- [x] 6.4 — Update Agent Type form (identity_id, role_id, input_type, output_type, system_instruction)
- [x] 6.4a — Update AgentTypeForm: identity selector first, role selector filtered by identity type ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 6.4b — Add allowed_identity_types multi-select to AgentRoleDialog ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 6.4c — Add i18n keys for new fields (allowed_identity_types, identity type labels) ⚠️ NEEDS REWORK - ARCHITECTURAL CORRECTION
- [x] 6.4d — CREATE AssignIdentitiesToRoleDialog component
- [x] 6.4e — CREATE AssignRolesToIdentityDialog component
- [x] 6.4f — UPDATE AgentRoleDialog: remove allowed_identity_types, add assigned identities table
- [x] 6.4g — UPDATE AgentIdentityListPage: add token status and management buttons
- [x] 6.4h — UPDATE AgentTypeForm: remove role filtering, add identity-role validation
- [x] 6.4i — ADD i18n keys for new components and actions
- [x] 6.5 — Agent Session launch dialog (collect input per input_type, submit async)
- [x] 6.6 — Agent Session status and result view (polling for task agents, chat interface for conversational agents, status indicator, structured/markdown result) ⚠️ NEEDS REWORK
- [x] 6.7 — Navigation wiring: Agent Roles and Agent Identities added to sidebar/routes ⚠️ NEEDS REWORK
- [x] 6.8 — i18n strings for all new UI text ⚠️ NEEDS REWORK
- [x] 6.9 — OAuth redirect handling in frontend (AgentOAuthCallbackPage, AppRouter route, i18n keys)
- [x] 6.10 — ModelConfigListPage (table with provider/model chips, credential indicator)
- [x] 6.11 — ModelConfigDialog with provider-specific credential fields and encryption ⚠️ NEEDS REWORK
- [x] 6.12 — Update AgentTypeForm to replace LLM fields with model_id dropdown ⚠️ NEEDS REWORK
- [ ] 6.13 — AgentInstanceDashboard with status filtering, date range, and execution history
- [ ] 6.14 — Update AgentJobPage for conversation history display
- [ ] 6.15 — Update navigation wiring for ModelConfigListPage and AgentInstanceDashboard
- [ ] 6.16 — Add i18n strings for model config, dashboard filters, and conversation history
- [x] 6.17 — Update `AgentJobPage` to display execution logs (system instruction and user prompt)
- [x] 6.18 — Add `useExecutionLogs(sessionId)` hook for fetching execution logs by `session_id`

### Phase 7 — Integration and Testing
- [x] 7.1 — Backend unit tests: AgentRole CRUD, PermissionManager resolution, AgentSession state machine, LangChain observe-reason-act loop
- [x] 7.2 — Backend integration tests: full session lifecycle against real database; execution_logs table schema; AgentPromptLog persistence
- [x] 7.3 — Frontend unit tests: Role editor, MCP tool preview panel, Session launch/status components
- [x] 7.4 — E2E tests: agent role management, agent type configuration, session launch and result polling, conversational agent chat UI
- [x] 7.5 — E2E integration variant: at least one test hits real backend (no page.route() mocks) to validate migration
- [ ] 7.6 — Backend unit tests: ModelConfigService CRUD, credential encryption round-trip, referential integrity rejection
- [ ] 7.7 — Frontend unit tests: AgentInstanceDashboard filtering, status counts, pagination
- [ ] 7.8 — Frontend unit tests: ModelConfigDialog provider fields, AgentJobPage conversation history
- [ ] 7.9 — E2E tests: model config management, instance dashboard filtering, conversation history display

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

### 1.4 — Migrate AgentType fields ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Remove any remaining LLM-specific fields (e.g., `llm_provider`, `llm_model`, `llm_api_key`) from `AgentType` and add `model_config_id` (FK → model_configs, nullable) plus `relationship()` to `ModelConfig`. See task 1.9 for the rework implementation.

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

### 1.8 — Add ModelConfig model ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add `enabled_models` (JSON array of model name strings, nullable) field to `ModelConfig`. This stores the subset of models the provider config has been configured to make available for selection on agent types. See tasks 2.11, 3.7, 6.11.

Add `ModelConfig` model to `backend/app/db/models/agents.py` with fields: `id`, `name` (display name, VARCHAR), `provider` (enum: `openai`, `anthropic`, `azure_openai`, `ollama`, `custom`), `model_name` (VARCHAR), `description` (Text, nullable), `encrypted_credentials` (TEXT, nullable, AES-256 encrypted JSON of provider-specific API credentials), `config` (JSON, nullable, non-secret settings such as `temperature`, `max_tokens`, `api_base`), `enabled_models` (JSON array, nullable, list of model name strings enabled for this config), `created_at`, `updated_at`. Add `ModelProvider` enum. Add `relationship()` back-reference from `AgentType` to `ModelConfig`.

**Done when**: `ModelConfig` is importable; `ModelProvider` enum is registered; `Base.metadata.tables` contains `model_configs`; `ModelConfig.enabled_models` is accessible and accepts a list of strings.

### 1.9 — Update AgentType model: remove LLM fields, add model_id FK ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Use `model_id` (VARCHAR, stores the selected model name string from the enabled models list) in addition to `model_config_id` (FK). The `AgentType` holds a FK to `model_configs` for which provider config to use, and separately stores `model_id` as the specific model chosen from `ModelConfig.enabled_models`. See tasks 1.8, 2.11, 3.5, 6.12.

Update `AgentType` in `backend/app/db/models/agents.py`: add `model_config_id` (FK → model_configs, nullable), `model_id` (VARCHAR, nullable, the specific model name selected from the config's enabled models), and `relationship("ModelConfig", back_populates="agent_types")`. Remove any LLM-specific fields (e.g., `llm_provider`, `llm_model`, `llm_api_key`) that were part of the prior design.

**Done when**: `AgentType.model_config_id` and `AgentType.model_id` are both present; `model_config` relationship resolves correctly; no LLM-specific field definitions remain in the class.

### 1.10 — Add conversation_history field to AgentJob model

Update `AgentJob` in `backend/app/db/models/agents.py`: add `conversation_history` (JSON, nullable) to store the ordered message thread for conversational agent sessions. Each entry is a dict with `role` (`user` | `assistant` | `tool`) and `content`.

**Done when**: `AgentJob.conversation_history` is accessible; ORM correctly serialises and deserialises JSON message lists; existing `AgentJob` rows are unaffected (nullable column).

### 1.11 — Generate and verify Alembic migration for ModelConfig and AgentType updates

Run `alembic revision --autogenerate -m "add-model-config-agent-type-model-config-id-conversation-history"`. Review the generated migration for: `model_configs` table creation with all fields, `model_config_id` FK column added to `agent_types`, `conversation_history` JSON column added to `agent_jobs`, `modelprovider` enum creation, and any LLM-specific column drops. Run `alembic upgrade head` and verify with `alembic current`.

**Done when**: Migration applies without error; `model_configs` table exists in the database; `agent_types.model_config_id` and `agent_jobs.conversation_history` columns are present in `information_schema.columns`.

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

### 2.4 — Update AgentType schemas ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add `model_config_id` (Optional UUID) to `AgentTypeCreate` and `AgentTypeUpdate`. Add `model_config` (Optional nested `ModelConfigRead`, read-only) to `AgentTypeRead`. Remove any LLM-specific fields from all three schemas. See task 2.9 for the `ModelConfigRead` schema definition.

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

### 2.9 — Pydantic schemas for ModelConfig CRUD

Add `ModelConfigCreate` (name, provider, model_name, description, credentials: dict | None, config: dict | None), `ModelConfigUpdate` (all fields optional), and `ModelConfigRead` (all fields; `encrypted_credentials` is never exposed — return `has_credentials: bool` instead) to `backend/app/schemas/agents.py`. Import `ModelProvider` enum. `ModelConfigCreate.credentials` is a plain dict that `ModelConfigService` encrypts before storage.

**Done when**: Schemas import without errors; `ModelConfigRead.model_validate(orm_obj)` returns `has_credentials=True` when `encrypted_credentials` is set; `ModelConfigRead` schema has no `encrypted_credentials` field.

### 2.10 — ModelConfigService CRUD with credential encryption

Add `ModelConfigService` to `backend/app/services/agents/` with async methods: `create_model_config` (encrypts `credentials` dict with `ENCRYPTION_MASTER_KEY` via AES-256 before storing as `encrypted_credentials`), `list_model_configs`, `get_model_config`, `update_model_config` (re-encrypts credentials when provided), `delete_model_config` (raises `ValidationError` if any `AgentType` references this config). Use the same AES-256 encryption helper as the MCP connector service.

**Done when**: Service methods pass unit tests; credentials are stored as encrypted ciphertext; plaintext credentials are never persisted; `delete_model_config` raises when referenced by an `AgentType`.

### 2.11 — Add `fetch_available_models(config_id)` method to ModelConfigService

Add `fetch_available_models(config_id: UUID, db: AsyncSession) → list[str]` to `ModelConfigService`. The method loads the `ModelConfig` record and returns `enabled_models` (the stored list of enabled model name strings). If `enabled_models` is null or empty, return an empty list. This method is called by the 3.7 endpoint to serve the model picker in the frontend.

**Done when**: Method returns the `enabled_models` list from the record; returns `[]` when the field is null; unit test covers both cases.

---

## Phase 3 — Backend API Endpoints

### 3.1 — Agent Role endpoints

Add `AgentRoleRouter` to `backend/app/api/v1/agents.py` with endpoints: `GET /agents/roles`, `POST /agents/roles`, `GET /agents/roles/{id}`, `PUT /agents/roles/{id}`, `DELETE /agents/roles/{id}`. All require `RT_AGENT` permission. Register the router in `backend/app/main.py`.

**Done when**: All five endpoints return correct HTTP status codes in integration tests; router is mounted and reachable.

### 3.2 — Agent Identity endpoints

> ⚠️ **REWORK REQUIRED**: Add `GET /agents/identities/oauth/authorize` (returns authorization URL) and `GET /agents/oauth/callback` (exchanges authorization code for tokens and stores encrypted token pair) to a new `AgentOAuthRouter`. Register in `backend/app/main.py`.

Add `AgentIdentityRouter` to `backend/app/api/v1/agents.py` with endpoints: `GET /agents/identities`, `POST /agents/identities`, `GET /agents/identities/{id}`, `PUT /agents/identities/{id}`, `DELETE /agents/identities/{id}`. Register in `backend/app/main.py`.

**Done when**: All endpoints are reachable and return typed responses matching `AgentIdentityRead`.

### 3.3 — Agent Session endpoints ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Update `GET /agents/sessions` to accept optional query parameters (`status`, `from_date`, `to_date`, `agent_type_id`) and return a paginated response. Add `GET /agents/sessions/{id}/history` for conversation history. See tasks 3.8 and 3.9 for rework implementation.

Add session endpoints to `backend/app/api/v1/agents.py`: `POST /agents/sessions` (enqueue, returns 202 + session ID), `GET /agents/sessions/{id}` (status), `GET /agents/sessions/{id}/result` (full output once completed), `GET /agents/sessions` (list for current user). For conversational agents, add WebSocket endpoint `WS /agents/sessions/{id}/chat`. Register in `backend/app/main.py`.

**Done when**: Launch endpoint returns 202 with a valid session ID; status endpoint reflects correct `AgentSessionStatus` at each stage; WebSocket connection works for conversational agents.

### 3.4 — Permission preview endpoint

Add `GET /agents/roles/{id}/mcp-tools` to `AgentRoleRouter`. Calls `PermissionManager.calculate_allowed_tools(role_id)` and returns a list of MCP tool identifiers. Used by the frontend real-time preview.

**Done when**: Endpoint returns the correct tool list for a role with assigned SOPs and Skills in an integration test.

### 3.5 — Update AgentType endpoints ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Update `AgentTypeRouter` handlers to accept both `model_config_id` (FK to the config) and `model_id` (the specific model name string selected from enabled models) in create/update payloads, and return both fields in read responses. Remove any remaining LLM-specific field handling. See tasks 1.9, 2.9, and the 2.4 rework.

Update existing `AgentTypeRouter` handlers in `backend/app/api/v1/agents.py` to accept and return the rearchitected `AgentTypeCreate`/`AgentTypeRead` schemas. Remove all references to `mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, and `max_instances`.

**Done when**: `GET /agents/types` and `POST /agents/types` pass integration tests using new schema with `model_config_id` + `model_id`; old field names return 422 if sent.

### 3.6 — OAuth authorize and callback endpoints for agent identity

Add `AgentOAuthRouter` to `backend/app/api/v1/agents.py`. Implement `GET /agents/identities/oauth/authorize?identity_id=<uuid>` that validates the identity record, generates the OAuth authorization URL against the configured agent realm, encodes `identity_id` in the `state` parameter, and returns `AgentIdentityOAuthAuthorizeResponse`. Implement `GET /agents/oauth/callback?code=...&state=...` that validates the state, calls `AgentIdentityService.complete_oauth_flow`, and returns the updated `AgentIdentityRead`. Register the router in `backend/app/main.py`. Both endpoints require `RT_AGENT` permission.

**Done when**: The authorize endpoint returns a valid authorization URL in an integration test; the callback endpoint processes a valid code, updates identity tokens, and returns `AgentIdentityRead` with `token_expires_at` populated.

---

### 3.7 — ModelConfig CRUD endpoints ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add `GET /agents/model-configs/{id}/models` endpoint that calls `ModelConfigService.fetch_available_models(config_id)` and returns the list of enabled model name strings. This endpoint is used by the frontend AgentTypeForm model picker. See tasks 1.8, 2.11, 6.12.

Add `ModelConfigRouter` to `backend/app/api/v1/agents.py` with endpoints: `GET /agents/model-configs` (list all, returns `list[ModelConfigRead]`), `POST /agents/model-configs` (create, returns 201 + `ModelConfigRead`), `GET /agents/model-configs/{id}` (get one), `PUT /agents/model-configs/{id}` (update), `DELETE /agents/model-configs/{id}` (delete, 409 if referenced by an agent type), `GET /agents/model-configs/{id}/models` (returns `list[str]` of enabled model names, 200 with `[]` if none configured). All require `RT_AGENT` permission. `GET` responses use `ModelConfigRead` — raw credentials are never returned. Register the router in `backend/app/main.py`.

**Done when**: All six endpoints return correct HTTP status codes; `GET` and `GET /{id}` response body contains `has_credentials` not `encrypted_credentials`; `DELETE` returns 409 when the config is referenced by an `AgentType`; `GET /{id}/models` returns the enabled model list or `[]`.

### 3.8 — Update AgentSession list endpoint with status and date filters

Update `GET /agents/sessions` in `backend/app/api/v1/agents.py` to accept optional query params: `status` (enum `AgentJobStatus`), `from_date` (ISO 8601 datetime string), `to_date` (ISO 8601 datetime string), `agent_type_id` (UUID). Apply filters to the database query. Return a paginated response schema with `total: int`, `page: int`, `page_size: int`, and `items: list[AgentJobRead]`.

**Done when**: Requests with each filter param return only matching sessions; unfiltered request returns all sessions for the current user; pagination fields present in all responses; integration test covers at least two filter combinations.

### 3.9 — Add conversation history endpoint

Add `GET /agents/sessions/{id}/history` to `backend/app/api/v1/agents.py`. Returns `conversation_history` (JSON array) from the `AgentJob` record. Returns 200 with empty array if `conversation_history` is null, 404 if session not found, 403 if not owned by the current user. Requires `RT_AGENT` permission.

**Done when**: Endpoint returns the full message thread for a completed conversational session; returns `[]` for task-type sessions with no history; ownership access control validated in an integration test.

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

## Phase 5 — LangChain Deep Agent Setup and Session Queue

### 5.3 — AgentSession persistence service

Create `backend/app/services/agents/session_service.py` with `AgentSessionService`: `enqueue(agent_type_id, input_data, user_id) → AgentSession`, `mark_running(session_id)`, `mark_completed(session_id, output_data)`, `mark_failed(session_id, error_message)`, `get_session(session_id) → AgentSession`.

**Done when**: All state transition methods update `AgentSession.status` and timing fields correctly; unit tests cover all four status values.

### 5.4 — Session dispatcher

Create `backend/app/services/agents/session_dispatcher.py`. Implement a background worker (async task or Redis-backed queue consumer) that polls for `queued` sessions and dispatches them to `AgentRuntimeExecutor`. Respects agent type concurrency limits from operational configuration.

**Done when**: A queued session transitions to `running` within the dispatch interval and then to `completed` or `failed` after executor returns.

### 5.5 — Agent Runtime executor with LangGraph ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Replace LangGraph state graph implementation with LangChain deep agent observe-reason-act loop. See task 5.10 for the rework implementation.

Update `backend/app/services/agents/` to implement `AgentRuntimeExecutor.run(session: AgentSession)` powered by **LangGraph**: fetches the `AgentType` and its `AgentRole`, calls `AgentPermissionManager.calculate_allowed_tools`, authenticates using `AgentIdentity` OIDC credentials, constructs a LangGraph state machine for the agent type (task vs conversational), and executes the graph with the allowed tool set. Persists the result. Removes the old `sop_executor.py` / `skillful_executor.py` split in favour of the role-governed LangGraph-based unified path.

**Done when**: An integration test with a seeded role, agent type, and session runs end-to-end and produces a persisted `output_data` on the session record, with LangGraph node transitions visible in OTEL traces.

### 5.6 — Communication Hub gateway extension

Update `backend/app/services/gateway/lifecycle_handler.py` to route inbound agent launch requests through `AgentSessionService.enqueue` and return the session ID synchronously. For conversational agents, establish and maintain WebSocket connections. Remove legacy synchronous execution path from `registry.py`.

**Done when**: POST to the gateway launch endpoint returns HTTP 202 with `{"session_id": "<uuid>"}` without blocking; WebSocket connections work for conversational agents.

### 5.7 — Result persistence via Result Repository

Ensure the `save_result` MCP tool is available in the allowed tool set for all agent roles (injected automatically by the runtime). Update `AgentRuntimeExecutor` to call `save_result` with the structured output before marking the session completed.

**Done when**: Completed sessions have a corresponding record in the results table accessible via `GET /agents/sessions/{id}/result`.

### 5.8 — OTEL instrumentation with LangGraph support ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Update OTEL instrumentation to instrument LangChain deep agent loop iterations (observe, reason, act steps) instead of LangGraph node transitions. See task 5.10.

Add OpenTelemetry spans and structured log events to `AgentSessionService` (enqueue, state transitions), `AgentRuntimeExecutor` (session start, LangGraph node transitions, skill calls, tool calls, session end), and `AgentPermissionManager` (allow/deny decisions). Follow the project's OTEL conventions from `config/telemetry.yaml`.

**Done when**: Running a session end-to-end produces OTEL trace spans for enqueue → dispatch → permission evaluation → LangGraph node transitions → skill execution → result persist → session complete.

### 5.9 — Bootstrap agent realm initialization via RealmManager

Update the platform bootstrap sequence (first-run setup wizard and startup path) to call `RealmManager.initialize_agent_realm` using `agent_realm_name` from `config/identity.yaml` (default `ai_agents`). Extend `config/identity.yaml` schema with the `agent_realm_name` field and update the setup wizard to collect and write it. When `provider_type = keycloak_bundled`, run `initialize_agent_realm` automatically on startup if the realm does not exist; when `provider_type = external`, log a warning that the agent realm must be pre-configured manually.

**Done when**: On first run with `keycloak_bundled` provider, the agent realm is present in Keycloak with correct token policies; `config/identity.yaml` contains `agent_realm_name`; startup logs confirm realm initialization was attempted.

### 5.10 — Replace LangGraph with LangChain deep agent in `runtime_executor.py`

> ⚠️ **REWORK REQUIRED** (replaces 5.1, 5.2, 5.5): Uninstall `langgraph`; install `langchain` and `langchain-community`. Update `pyproject.toml` to reflect the dependency change. Replace LangGraph `TypedDict` state schemas in `agent_state.py` with LangChain deep agent loop structures in `backend/app/services/agents/agent_loop.py`. Rewrite `AgentRuntimeExecutor.run(session)` to use the LangChain deep agent observe-reason-act loop: (1) **Observe** — load session context, resolved tool set, and `AgentIdentity` credentials; (2) **Reason** — call LLM with system instruction and conversation history; (3) **Act** — dispatch allowed tool calls via MCP, enforce permission boundary, append results to context; loop until the agent signals completion or max-iterations is exceeded. Update 5.8 OTEL instrumentation to trace observe/reason/act steps instead of LangGraph node transitions.

**Done when**: `AgentRuntimeExecutor.run()` uses LangChain deep agent loop; `langgraph` removed from `pyproject.toml` and `langchain`/`langchain-community` added; existing session lifecycle integration tests pass with the new executor; OTEL traces include observe/reason/act spans.

### 5.11 — Add `ExecutionLogEntry` model and capture full prompt logging before first LLM call

Add `ExecutionLogEntry` SQLAlchemy model to `backend/app/db/models/agents.py` (table: `execution_log_entries`) with fields: `id` (UUID), `session_id` (FK → agent_jobs), `system_instruction` (TEXT), `user_prompt` (TEXT), `logged_at` (TIMESTAMPTZ). Add `ExecutionLogRead` Pydantic schema to `backend/app/schemas/agents.py`. Update `AgentRuntimeExecutor.run()` to write an `ExecutionLogEntry` record before the first LLM call, capturing the fully-rendered system instruction and user prompt. Add `GET /agents/sessions/{id}/execution-logs` endpoint returning `list[ExecutionLogRead]`, requiring `RT_AGENT` permission. Generate and apply Alembic migration for the new table.

**Done when**: An `ExecutionLogEntry` record is persisted for every session before the first LLM call; `GET /agents/sessions/{id}/execution-logs` returns the entry with correct field values; migration applied cleanly with `alembic upgrade head`; unit test verifies `system_instruction` and `user_prompt` are captured correctly.

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

### 6.4 — Update Agent Type form ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Replace any inline LLM configuration fields with a `model_config_id` select dropdown populated from `GET /agents/model-configs`. Display the selected config’s provider and model name as a read-only subtitle beneath the dropdown. See task 6.12 for the rework implementation.

Update `frontend/src/pages/agents/AgentTypeForm.tsx` to replace removed fields (`mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, `max_instances`) with the new fields: `identity_id` (select from identities), `role_id` (select from roles), `system_instruction` (textarea), `input_type` (select enum), `input_schema` (JSON editor, shown when `input_type = typed`), `output_type` (select enum), `output_schema` (JSON editor, shown when `output_type = typed`). All UI text via i18n.

**Done when**: Form submits with new fields and receives 201/200 from the updated backend endpoints; removed fields are absent from the form.

### 6.5 — Agent Session launch dialog

Create `frontend/src/pages/agents/AgentSessionLaunchDialog.tsx`. Opens from the Agent Management page per agent type. Renders the appropriate input form based on `input_type` (`none` → confirm only, `typed` → form fields from `input_schema`, `conversation` → text area). Submits to `POST /agents/sessions` and displays the returned session ID with a link to the status view (or chat interface for conversational agents). Follow Dialog Error Handling Standard.

**Done when**: Launching a session with each `input_type` variant posts correctly; session ID is shown to the user immediately; conversational agents open chat UI.

### 6.6 — Agent Session status and result view ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add a “Conversation History” section below the status indicator for sessions with `input_type = conversation`. Fetch history from `GET /agents/sessions/{id}/history` and render as role-based message bubbles (user left, assistant right, tool calls collapsible). See task 6.14 for the rework implementation.

Create `frontend/src/pages/agents/AgentJobPage.tsx`. Display session metadata (agent type, triggered by, timestamps), live status indicator with polling (`GET /agents/sessions/{id}` every 3 seconds while `status = queued | running`) **for task agents**, and a chat interface (similar to VS Code chat sessions) **for conversational agents**. Result section renders as structured data or markdown depending on `output_type` when completed.

**Done when**: Page polls correctly for task agents and stops on terminal status; conversational agents show chat UI with message history; result renders in both `typed` and `markdown` formats.

### 6.7 — Navigation wiring ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add routes and sidebar items for `ModelConfigListPage` (`/agents/model-configs`) and `AgentInstanceDashboard` (`/agents/dashboard`). See task 6.15 for the rework implementation.

Add route entries in `frontend/src/app/` for: `/agents/roles` → `AgentRoleListPage`, `/agents/identities` → `AgentIdentityListPage`, `/agents/sessions/:id` → `AgentJobPage`. Add sidebar navigation items for "Agent Roles" and "Agent Identities" under the Agents section.

**Done when**: All new routes resolve correctly; sidebar items navigate to the correct pages; active state highlights correctly.

### 6.8 — i18n strings ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add i18n keys for model config fields (provider display names, credential field labels), `AgentInstanceDashboard` filter labels and status badge text, and conversation history section headings. See task 6.16 for the rework implementation.

Add all new UI text keys to `frontend/src/i18n/` locale files (English at minimum). Cover all labels, headings, dialog titles, button labels, status values, error messages, and empty state text introduced in 6.1–6.7.

**Done when**: No hardcoded strings remain in new components; switching locale displays translated strings where translations are provided.

### 6.9 — OAuth redirect handling in frontend

Add an `AgentOAuthCallbackPage` component at route `/agents/identities/oauth/callback` that reads `code` and `state` from URL params, calls `GET /agents/oauth/callback` on the backend to exchange the code (or proxies the redirect), then closes the popup and signals the opener `AgentIdentityDialog` to refresh the identity record. Update `AgentIdentityDialog` to include the "Sign In as Agent" OAuth button with `oauthInitiating` loading state and to handle the popup close/success signal. Add `agents.identities.oauthSignIn`, `agents.identities.oauthPending`, and `agents.identities.oauthSuccess` i18n keys.

**Done when**: Clicking "Sign In as Agent" opens the Keycloak agent realm login; after sign-in the identity shows `status: active` and `token_expires_at` is populated; popup closes cleanly; all OAuth flow strings go through i18n.

---
### 6.10 — ModelConfigListPage

Create `frontend/src/pages/agents/ModelConfigListPage.tsx`. Display a table listing all model configs with columns: Name, Provider (styled chip), Model Name, Config summary (temperature / max_tokens if set), Credentials (`has_credentials` indicator), Actions (edit, delete). Fetch from `GET /agents/model-configs`. Add a toolbar button to open `ModelConfigDialog` for creation. Handle loading and empty states. Delete action shows a confirmation dialog.

**Done when**: Page renders model configs with all columns; provider shown as a styled chip; `has_credentials` renders as a Yes/No indicator; delete confirmation dialog fires before calling `DELETE /agents/model-configs/{id}`.

### 6.11 — ModelConfigDialog with provider-specific credential fields ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Add a "Fetch Models" button in the dialog. When clicked, it calls `GET /agents/model-configs/{id}/models` (using the current saved config) and displays the returned model names as a checkbox list under an "Enabled Models" section. The user selects which models to enable; the selection is saved back to `ModelConfig.enabled_models` via `PUT /agents/model-configs/{id}`. The Fetch Models button is only active in edit mode (config already saved). See tasks 1.8, 2.11, 3.7.

Create `frontend/src/pages/agents/ModelConfigDialog.tsx`. Fields: `name` (text), `provider` (select from `ModelProvider` values), `model_name` (text), `description` (textarea), `config` (JSON editor for temperature / max_tokens / api_base), a collapsible "Credentials" section with provider-specific inputs: API key field for `openai`/`anthropic`; deployment name + endpoint + API key for `azure_openai`; base URL for `ollama`/`custom`, and an "Enabled Models" section with a "Fetch Models" button (edit mode only) that populates a checkbox list of available models. In edit mode, credential fields show a masked placeholder when credentials are already stored. Follow the Dialog Error Handling Standard.

**Done when**: Dialog creates and updates model configs via `POST`/`PUT /agents/model-configs`; credential fields switch correctly based on provider selection; existing credentials display a masked placeholder; "Fetch Models" button fetches and renders model checkboxes; enabled model selection is persisted; form validates required fields before submission.

### 6.12 — Update AgentTypeForm to replace LLM fields with model_id dropdown ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Replace the single `model_config_id` dropdown approach with a two-step picker. First, a `model_config_id` select chooses the provider config. Once selected, call `GET /agents/model-configs/{id}/models` to retrieve the enabled models list and render a second `model_id` dropdown populated from that list. The form submits both `model_config_id` and `model_id`. If the config has no enabled models, show an inline warning prompting the user to configure models in ModelConfigDialog. See tasks 1.9, 2.11, 3.7.

Update `frontend/src/pages/agents/AgentTypeForm.tsx`: remove any inline LLM configuration fields (provider, model name, API key). Add a `model_config_id` select dropdown that fetches options from `GET /agents/model-configs` and displays each option as `<name> — <provider>`. When a config is selected, fetch its enabled models via `GET /agents/model-configs/{id}/models` and populate a `model_id` dropdown with those model names. All UI text via i18n.

**Done when**: `model_config_id` dropdown populates from the API; selecting a config triggers the models fetch and populates the `model_id` dropdown; form submits with both `model_config_id` and `model_id`; no inline LLM fields remain; empty enabled-models warning shown when list is empty; both dropdowns clear correctly when config selection is cleared.

### 6.13 — AgentInstanceDashboard with status filtering and execution history

Create `frontend/src/pages/agents/AgentInstanceDashboard.tsx`. Features: status filter chips row (All / Queued / Running / Completed / Failed), date range picker (`from_date`, `to_date`), agent type filter dropdown. Table columns: Agent Type, Status (coloured badge), Triggered By, Started At, Duration (calculated from `started_at` / `completed_at`), Actions (link to `AgentJobPage`). Summary bar showing per-status counts. Fetch from `GET /agents/sessions` with active filters as query params. Support pagination (page size selector, page navigation). Handle loading and empty states.

**Done when**: Dashboard renders and filters the session list correctly; each filter change triggers an API refetch with the correct query params; status count summary updates with filters applied; pagination controls work; empty state displayed when no sessions match.

### 6.14 — Update AgentJobPage for conversation history display

Update `frontend/src/pages/agents/AgentJobPage.tsx`: for sessions with `input_type = conversation`, add a “Conversation History” section below the status indicator. Fetch history from `GET /agents/sessions/{id}/history`. Render messages as role-based bubbles: user messages aligned left, assistant messages aligned right, tool call entries collapsible. Add a “Refresh History” button. The history section is only visible when `input_type = conversation`; hidden for task-type sessions.

**Done when**: History section renders for conversational sessions; messages display with role-correct styling; tool call entries expand/collapse; section is absent for task-type sessions; empty state shown when history array is empty.

### 6.15 — Update navigation wiring for ModelConfigListPage and AgentInstanceDashboard

Update `frontend/src/app/` router and sidebar: add route `/agents/model-configs` → `ModelConfigListPage`, add route `/agents/dashboard` → `AgentInstanceDashboard`. Add sidebar navigation items “Model Configs” and “Agent Dashboard” under the Agents section, ordered after existing Agent items.

**Done when**: Both new routes resolve correctly in the browser; sidebar items navigate to the correct pages; active state highlights on the current route.

### 6.16 — Add i18n strings for model config, dashboard, and conversation history

Add all new UI text keys to `frontend/src/i18n/` locale files (English at minimum) for components 6.10–6.14. Cover: model config field labels (`providers.*` namespace), credential section headings, `AgentInstanceDashboard` filter labels, status badge text, summary bar labels, conversation history section heading, role labels (`user`, `assistant`, `tool`), and empty state text for dashboard and history.

**Done when**: No hardcoded strings in components 6.10–6.14; all new keys present in the English locale file; no keys missing (verified by exhaustive review or i18n lint).

### 6.17 — Update `AgentJobPage` to display execution logs

Update `frontend/src/pages/agents/AgentJobPage.tsx`: add an “Execution Log” collapsible section that displays the `system_instruction` and `user_prompt` captured from `ExecutionLogEntry`. Fetch via `useExecutionLogs(sessionId)`. The section is always present (collapsed by default) for any session. Render `system_instruction` and `user_prompt` as pre-formatted text blocks with copy-to-clipboard buttons. Add i18n keys under `agents.sessions.executionLog.*` for all section labels.

**Done when**: Execution Log section renders in `AgentJobPage`; collapsed by default; system instruction and user prompt display correctly; copy buttons work; all text goes through i18n.

### 6.18 — Add `useExecutionLogs(sessionId)` hook for fetching execution logs

Create `frontend/src/hooks/useExecutionLogs.ts`. Implement `useExecutionLogs(sessionId: string | null): { logs: ExecutionLogRead[], loading: boolean, error: unknown }`. Calls `GET /agents/sessions/{id}/execution-logs` when `sessionId` is non-null; returns an empty array while loading or on error. Add `ExecutionLogRead` TypeScript interface to `frontend/src/types/index.ts` with fields: `id`, `session_id`, `system_instruction`, `user_prompt`, `logged_at`.

**Done when**: Hook returns `ExecutionLogRead[]` for a valid session ID; returns `[]` for a null `sessionId`; unit test verifies fetch trigger and correct loading/error states.

---
## Phase 7 — Integration and Testing

### 7.1 — Backend unit tests ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Replace LangGraph graph execution test assertions with LangChain deep agent loop assertions. Add `test_execution_log.py` to verify `ExecutionLogEntry` creation and prompt capture. See tasks 5.10–5.11.

Add tests in `backend/tests/unit/` and `backend/tests/services/` covering: `AgentRoleService` CRUD, `AgentIdentityService` referential integrity check, `AgentPermissionManager` tool resolution with SOP and direct Skill paths, `AgentJobService` all four status transitions.

**Done when**: All new unit tests pass; coverage for new service modules ≥ 80%.

### 7.2 — Backend integration tests ⚠️ NEEDS REWORK

> ⚠️ **REWORK REQUIRED**: Replace LangGraph state trace assertions with LangChain deep agent loop trace assertions. Add assertion that `ExecutionLogEntry` is persisted and populated for the session. See tasks 5.10–5.11.

Add tests in `backend/tests/integration/` that: apply `alembic upgrade head` as a fixture step, create a role with SOPs/Skills, launch a session, confirm it transitions to `completed` with output (with LangChain deep agent loop traces visible), and verify schema correctness by querying `information_schema.columns` for new columns. Include negative tests for permission denial.

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

### 7.6 — Backend unit tests: ModelConfigService and credential security

Add tests in `backend/tests/unit/` and `backend/tests/services/` covering: `ModelConfigService.create_model_config` stores encrypted (not plaintext) credentials; `ModelConfigService.get_model_config` returns `has_credentials=True` when credentials are present; `ModelConfigService.update_model_config` re-encrypts credentials on update; `ModelConfigService.delete_model_config` raises `ValidationError` when an `AgentType` references the config; credential AES-256 encrypt-then-decrypt round-trip produces the original dict.

**Done when**: All new unit tests pass; coverage for `ModelConfigService` ≥ 80%; no test accesses raw plaintext credentials after `create`.

### 7.7 — Frontend unit tests: AgentInstanceDashboard filtering

Add tests in `frontend/src/__tests__/` covering: `AgentInstanceDashboard` — clicking a status filter chip triggers `GET /agents/sessions?status=<value>` with the correct param; clearing the date range removes date params from the next fetch; agent type filter dropdown change triggers refetch; status count summary renders correct numbers from mock response; pagination `page` param increments on next-page click; empty state component renders when `items: []`.

**Done when**: All dashboard unit tests pass; filter-to-query-param mapping verified for all filter combinations; no regressions in existing tests.

### 7.8 — Frontend unit tests: ModelConfigDialog and AgentJobPage conversation history

Add tests in `frontend/src/__tests__/` covering: `ModelConfigDialog` — selecting `openai` provider shows API key field only; selecting `azure_openai` shows deployment name, endpoint, and API key fields; edit mode with `has_credentials=true` renders a masked placeholder in credential fields; form prevents submission when required fields are empty. `AgentJobPage` — conversation history section renders when `input_type = conversation`; history section is absent when `input_type = task`; messages render with correct role-based layout; tool call entries collapse by default and expand on click.

**Done when**: All new frontend unit tests pass with no regressions.

### 7.9 — E2E tests: model config management, instance dashboard filtering, conversation history

Add test suites to `e2e/tests/agent-runtime.spec.ts` (or a new `e2e/tests/model-config.spec.ts`): **Model Config Management** — create a model config with credentials, verify it appears in the list with `has_credentials` indicator, edit to update description, delete with confirmation. **Agent Instance Dashboard** — launch two sessions of different statuses, apply status filter, verify only matching rows appear, clear filter. **Conversation History** — navigate to a completed conversational session, verify the history section renders message bubbles with correct role styling. Use `page.route()` mocks for speed.

**Done when**: All new E2E tests pass in the `chromium` project against the dev configuration; no flaky assertions.

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
- [ ] ModelConfig credentials never stored or returned in plaintext
- [ ] AgentInstanceDashboard filter-to-query-param mapping verified in unit tests
- [ ] Conversation history endpoint covered by integration test
- [ ] ModelConfigListPage and AgentInstanceDashboard routes wired in navigation
- [ ] All NEEDS REWORK tasks completed and original tasks re-verified
- [ ] `langgraph` removed from `pyproject.toml`; `langchain` and `langchain-community` installed and verified
- [ ] `ExecutionLogEntry` persisted for every agent session before first LLM call
- [ ] `GET /agents/sessions/{id}/execution-logs` endpoint verified in unit and integration tests
- [ ] `AgentJobPage` execution log section renders `system_instruction` and `user_prompt` correctly
