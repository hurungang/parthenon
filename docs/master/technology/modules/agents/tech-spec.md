# Module: agents — Tech Spec

## Overview

The agents module is the central execution layer for AI agents on the platform. It manages agent type definitions, a role-governed permission model, first-class OIDC agent identities, and an asynchronous session queue dispatched by a background `SessionDispatcher` and executed by `AgentRuntimeExecutor` using the **LangChain deep agent** observe-reason-act loop. Permissions flow through `AgentRole → SOPs → Skills → MCP tools` and are resolved by `AgentPermissionManager` with an LRU cache. Agent identities are registered users in a dedicated agent realm and authenticate via the OAuth authorization code flow; their tokens are stored AES-256 encrypted and proactively refreshed by `TokenRefreshService`. LLM provider configuration is managed through `ModelConfig` records, and `ModelBindingLayer` resolves an `AgentType.model_id` string to the correct provider client at runtime. On every agent type save, `PlanGenerationService` traverses the role→SOP→Skill→Tool graph, invokes the configured LLM, and persists a structured implementation plan and topology in the `agent_plans` table; plan generation is non-blocking (failures write a `failed` status row without blocking the save). When a session starts, `AgentRuntimeLoader` injects the saved plan into the agent's system context to ensure compliant, predictable execution.

**Dependency**: `langchain` and `langchain-community` (replaces the removed `langgraph` dependency).

---

## Key Components

### Backend — Permission & Identity

| Component | Description |
|-----------|-------------|
| `AgentRoleService` | CRUD for `AgentRole`; `assign_identities()` / `remove_identity()` / `list_identities()` / `is_identity_assigned()`; assigns/removes MCP sessions with one-session-per-server enforcement; invalidates the permission cache on role writes |
| `AgentIdentityService` | CRUD for `AgentIdentity`; generates OAuth authorization URLs; exchanges authorization code for tokens; stores access and refresh tokens AES-256 encrypted on the `AgentIdentity` record; `refresh_token()`, `get_reauth_url()`; `assign_roles()` / `remove_role()` / `list_roles()` |
| `AgentPermissionManager` | Resolves `AgentRole → SOPs → Skills → MCP tools` chain using `mcp_slug/tool_name` format; LRU cache keyed on `role_id`; invalidated on role SOP/Skill assignment changes |
| `RealmManager` | Initializes and configures the agent realm in the OIDC provider at bootstrap; creates realm-level token policies and registers the platform OAuth client for the authorization code flow |
| `TokenRefreshService` | Background service that proactively refreshes stored agent OAuth access tokens before expiry using the stored refresh token; updates `AgentIdentity` with a re-encrypted token pair |

### Backend — Execution Engine

| Component | Description |
|-----------|-------------|
| `AgentSessionService` | Enqueues sessions (`INSERT` with `status = queued`), manages state transitions (`queued → running → completed / failed`), persists results; tracks `conversation_history` for conversational agents |
| `SessionDispatcher` | Background worker; polls `queued` sessions using `SELECT … FOR UPDATE SKIP LOCKED`; dispatches to `AgentRuntimeExecutor`; manages concurrency |
| `AgentRuntimeExecutor` | Orchestrates agent execution using the LangChain deep agent observe-reason-act loop; validates that the agent identity is assigned to the agent role via `agent_role_identities` before execution; raises `PermissionDeniedError` if not; captures `ExecutionLogEntry` (system instruction + user prompt) before first LLM call; loads MCP session context from role's assigned sessions and injects pre-configured parameters into the system instruction; persists result via `save_result` |
| `TaskAgentLoop` | LangChain deep agent loop for task-based agents; observe-reason-act context producing a single structured or markdown result | 
| `ConversationalAgentLoop` | LangChain deep agent loop for conversational agents; multi-turn observe-reason-act loop with `conversation_history` state |
| `ModelBindingLayer` | Resolves `AgentType.model_id` string to a matching `ModelConfig` (scans `enabled_models`; falls back to provider-prefix matching); instantiates the correct LangChain/LiteLLM client; sends chat completion requests |
| `ModelConfigService` | CRUD for `ModelConfig`; encrypts/decrypts API credentials (AES-256); `fetch_available_models(config_id)` returns `enabled_models` if non-empty, otherwise queries live from the configured provider |
| `AgentInstanceManager` | Retained for session handle management; execution logic removed |
| `PlanGenerationService` | Orchestrates LLM-based plan generation on agent type save; traverses role→SOP→Skill→Tool graph; constructs prompt with agent context (instructions, role, SOPs, skills, tools); invokes configured LLM; parses response into structured plan steps; calls `TopologyBuilderService`; upserts `AgentPlan`; non-blocking — exceptions write a `failed` status row |
| `TopologyBuilderService` | Converts the role→SOP→Skill→Tool graph to a `nodes`/`edges` topology dict with deterministic node IDs; called by `PlanGenerationService` on every save |
| `AgentRuntimeLoader` | Loads the saved plan from `agent_plans` on session initialisation; injects plan into agent system context (LLM prompt); graceful degradation when no plan exists |

### Backend — Models

| Component | Description |
|-----------|-------------|
| `AgentRole` | SQLAlchemy model; permission role entity; relationships to `AgentRoleSOP`, `AgentRoleSkill`, and `AgentRoleIdentity` join tables |
| `AgentRoleSOP` | SQLAlchemy join model linking a role to a SOP |
| `AgentRoleSkill` | SQLAlchemy join model linking a role to a Skill |
| `AgentRoleIdentity` | SQLAlchemy join model linking a role to an identity; unique constraint on `(role_id, identity_id)`; authoritative source for identity-role access control |
| `AgentIdentity` | SQLAlchemy model; first-class OIDC identity entity; `realm_name`, `realm_username`, AES-256 encrypted `access_token` and `refresh_token`, `token_expires_at` |
| `AgentJob` | SQLAlchemy model for asynchronous session tracking; supports both task and conversational modes; includes `conversation_history` JSONB column (table: `agent_jobs`) |
| `AgentPromptLog` | SQLAlchemy model for prompt capture; written before first LLM call per session; fields: `id`, `session_id` (FK → agent_jobs CASCADE), `system_instruction`, `user_prompt`, `logged_at` (table: `execution_logs`) |
| `ModelConfig` | SQLAlchemy model for LLM provider configuration; `provider_type` (`openai`, `anthropic`, `litellm_proxy`, `azure_openai`), `display_name`, `api_base_url`, encrypted `api_key`, `enabled_models` (JSONB) |
| `AgentType` | SQLAlchemy model — modified; fields: `identity_id`, `role_id`, `model_id` (string), `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`; removed: `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key`, `model_config_id`, `model_name` |
| `AgentInstance` | SQLAlchemy model for session handle tracking; unchanged |
| `AgentPlanStatus` | `str` enum — `pending`, `success`, `failed`; represents the lifecycle of a plan generation attempt |
| `AgentPlan` | SQLAlchemy model; persists the latest generated plan for an agent type; stores `plan_steps` and `topology` as JSON, `generation_status`, `generation_error`, `agent_config_hash`; unique FK → `agent_types` with CASCADE delete |
| `AgentIdentityType` | `str` enum — `realm_user` |
| `AgentIdentityStatus` | `str` enum — `active`, `suspended`, `deprovisioned` |
| `AgentJobStatus` | `str` enum — `queued`, `running`, `completed`, `failed` |
| `AgentInputType` | `str` enum — `none`, `typed`, `conversation` |
| `AgentOutputType` | `str` enum — `auto`, `typed`, `markdown` |

### Frontend

| Component | Description |
|-----------|-------------|
| `AgentRoleListPage` | Table view of all agent roles; Name, SOP count chip, Skill count chip, Edit/Delete actions; launches `AgentRoleDialog` |
| `AgentRoleDialog` | Create/edit form with SOP multi-select, Skill multi-select, real-time MCP tool preview panel (debounced 300 ms, edit mode only); assigned identities data table with Assign/Remove actions; assigned MCP sessions section with Assign/Remove actions; `maxWidth="lg"` |
| `AssignIdentitiesToRoleDialog` | Multi-select dialog to bulk-assign identities to a role |
| `AssignMcpSessionsToRoleDialog` | Multi-select dialog to assign MCP sessions to a role; filtered by servers whose tools the role uses; enforces one-session-per-server |
| `AgentIdentityListPage` | Table view of all agent identities; realm_name, realm_username, token status chip (Active/Expired), identity status chip; Refresh Token and Re-Authenticate actions per row |
| `AgentIdentityDialog` | Create/edit form for `AgentIdentity`; realm_name and realm_username text fields; **"Sign In as Agent"** OAuth button that fetches the authorization URL and opens the agent realm sign-in in a popup; reflects updated token status after OAuth callback |
| `AssignRolesToIdentityDialog` | Multi-select dialog to bulk-assign roles to an identity |
| `AgentOAuthCallbackPage` | Loaded in the OAuth popup; exchanges code via backend callback, postMessages result to opener, then calls `window.close()` |
| `AgentTypeForm` | Modified — full form component; new fields: `identity_id`, `role_id`, `model_id` (string dropdown populated across all `ModelConfig` records), `system_instruction`, `input_type` (+schema), `output_type` (+schema); removed: `model_config_id`, `model_name`, `llm_*` fields; ADD validation: selected identity must be assigned to selected role |
| `AgentJobLaunchDialog` | Dynamic input form per `input_type` (none / typed / conversation); POSTs to `/agents/sessions`; shows returned session ID |
| `AgentJobPage` | Session metadata, status chip, 3 s polling for task agents; WebSocket chat UI for conversational agents; result panel (typed JSON or markdown); execution log section (system instruction + user prompt from `ExecutionLogEntry`) |
| `AgentManagementPage` | Modified — uses updated `AgentTypeForm`; adds Launch (▶) action per row linking to `AgentJobPage`; after a successful save reads `plan` from the response, stores it in `planData` state, and opens `PlanPreviewModal`; clears plan state on modal close |
| `PlanPreviewModal` | MUI Dialog opened after a successful agent type save; displays plan steps as an ordered list with step-type chips; hosts `TopologyDiagramRenderer`; shows error state when `generation_status = failed`; follows Dialog Error Handling Standard |
| `TopologyDiagramRenderer` | Renders node-edge topology payload as a visual diagram; distinguishes node types (role, sop, skill, tool) by colour/icon; handles empty state |
| `AgentInstanceDashboardPage` | Admin view of all `AgentJob` instances; columns: agent type name, status chip, triggered by, started/completed times; `status` and `since` filter controls |
| `ModelConfigListPage` | Table view of all model configurations; display_name, provider_type, credential status chip, Edit/Delete actions |
| `ModelConfigDialog` | Create/edit form for `ModelConfig`; provider_type select, display_name, api_base_url, api_key (masked), enabled_models chip multi-select via **"List Models"** button |

---

## API Endpoints

### Agent Roles

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/roles` | List all roles with SOP/Skill ID lists |
| `POST` | `/api/v1/agents/roles` | Create role and join records atomically |
| `GET` | `/api/v1/agents/roles/{id}` | Get role detail including SOP/Skill ID lists |
| `PUT` | `/api/v1/agents/roles/{id}` | Replace SOP/Skill assignments; invalidates permission cache |
| `DELETE` | `/api/v1/agents/roles/{id}` | Delete role; 409 if any `AgentType` references it |
| `GET` | `/api/v1/agents/roles/{id}/mcp-tools` | Resolved MCP tool identifiers for the role |
| `POST` | `/api/v1/agents/roles/{role_id}/identities` | Bulk assign identities to role |
| `DELETE` | `/api/v1/agents/roles/{role_id}/identities/{identity_id}` | Remove identity from role |
| `GET` | `/api/v1/agents/roles/{role_id}/identities` | List identities assigned to role |
| `POST` | `/api/v1/agents/roles/{role_id}/mcp-sessions` | Assign MCP session to role; one-session-per-server enforced |
| `DELETE` | `/api/v1/agents/roles/{role_id}/mcp-sessions/{session_id}` | Remove MCP session from role |
| `GET` | `/api/v1/agents/roles/{role_id}/mcp-sessions` | List MCP sessions assigned to role |
| `GET` | `/api/v1/agents/roles/{role_id}/available-mcp-sessions` | List assignable MCP sessions filtered by servers whose tools the role uses |

### Agent Identities

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/identities` | List all agent identities |
| `POST` | `/api/v1/agents/identities` | Create placeholder identity record; tokens obtained via OAuth flow |
| `GET` | `/api/v1/agents/identities/{id}` | Get identity detail |
| `PUT` | `/api/v1/agents/identities/{id}` | Update identity |
| `DELETE` | `/api/v1/agents/identities/{id}` | Delete identity; 409 if any `AgentType` references it |
| `POST` | `/api/v1/agents/identities/{identity_id}/roles` | Bulk assign roles to identity |
| `DELETE` | `/api/v1/agents/identities/{identity_id}/roles/{role_id}` | Remove role from identity |
| `GET` | `/api/v1/agents/identities/{identity_id}/roles` | List roles assigned to identity |
| `POST` | `/api/v1/agents/identities/{identity_id}/refresh-token` | Refresh expired access token using stored refresh token |
| `GET` | `/api/v1/agents/identities/{identity_id}/reauth-url` | Get OAuth re-authentication URL |
| `GET` | `/api/v1/agents/identities/oauth/authorize` | Generate OAuth authorization URL for agent identity (query: `?identity_id=<uuid>`) |
| `GET` | `/api/v1/agents/oauth/callback` | OIDC redirect handler; exchanges code; stores encrypted tokens; sets `status = active` |

### Agent Types

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/types` | List all agent types |
| `POST` | `/api/v1/agents/types` | Create an agent type; triggers `PlanGenerationService` after commit; response includes `plan: AgentPlanRead \| null` |
| `GET` | `/api/v1/agents/types/{type_id}` | Get agent type detail |
| `PUT` | `/api/v1/agents/types/{type_id}` | Update an agent type; triggers `PlanGenerationService` after commit; response includes `plan: AgentPlanRead \| null` |
| `DELETE` | `/api/v1/agents/types/{type_id}` | Delete an agent type |
| `GET` | `/api/v1/agents/types/{type_id}/instances` | List active instances for a type |
| `DELETE` | `/api/v1/agents/instances/{instance_id}` | Terminate an agent instance |

### Agent Sessions

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/agents/sessions` | Enqueue a session; returns 202 with session ID immediately |
| `GET` | `/api/v1/agents/sessions` | List sessions for current user; supports `?status=`, `?since=`, and `?agent_type_id=` filters |
| `GET` | `/api/v1/agents/sessions/{id}` | Current status and timing |
| `GET` | `/api/v1/agents/sessions/{id}/result` | Full output; 409 if session not yet completed |
| `GET` | `/api/v1/agents/sessions/{id}/execution-logs` | `ExecutionLogRead[]` — system instruction and user prompt captured before first LLM call; 404 if session not found |
| `GET` | `/api/v1/agents/sessions/{id}/logs` | `ExecutionLogEntryRead[]` — ordered event entries (event_type, log_level, message, data, timestamp) emitted during execution; 404 if session not found |

### Model Configurations

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/model-configs` | List all model configurations |
| `POST` | `/api/v1/agents/model-configs` | Create model config; API credentials AES-256 encrypted |
| `GET` | `/api/v1/agents/model-configs/{id}` | Get config; credential fields never returned |
| `PUT` | `/api/v1/agents/model-configs/{id}` | Update config; omitted `api_key` leaves existing credential unchanged |
| `DELETE` | `/api/v1/agents/model-configs/{id}` | Delete config; 409 if any `AgentType` references it |
| `GET` | `/api/v1/agents/model-configs/{id}/models` | Returns `enabled_models` if non-empty; otherwise queries live from the provider |

---

## Code Reference Map

### Backend Models (`backend/app/db/models/agents.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRole` | model | Permission role entity; relationships to `AgentRoleSOP`, `AgentRoleSkill`, `AgentRoleIdentity` | `backend/app/db/models/agents.py` |
| `AgentRoleSOP` | model | Join: role ↔ SOP | `backend/app/db/models/agents.py` |
| `AgentRoleSkill` | model | Join: role ↔ Skill | `backend/app/db/models/agents.py` |
| `AgentRoleIdentity` | model | Join: role ↔ identity; unique `(role_id, identity_id)`; `assigned_at`, `assigned_by`; authoritative source for identity-role access control | `backend/app/db/models/agents.py` |
| `AgentIdentity` | model | First-class OIDC identity entity; `realm_name`, `realm_username`, encrypted `access_token`, encrypted `refresh_token`, `token_expires_at` | `backend/app/db/models/agents.py` |
| `AgentIdentityType` | str enum | `realm_user` | `backend/app/db/models/agents.py` |
| `AgentIdentityStatus` | str enum | `active`, `suspended`, `deprovisioned` | `backend/app/db/models/agents.py` |
| `AgentJob` | model | Async session tracking; `conversation_history` JSONB for conversational agents (table: `agent_jobs`) | `backend/app/db/models/agents.py` |
| `AgentJobStatus` | str enum | `queued`, `running`, `completed`, `failed` | `backend/app/db/models/agents.py` |
| `AgentPromptLog` | model | Prompt capture before first LLM call; `session_id` FK → agent_jobs CASCADE; `system_instruction`, `user_prompt`, `logged_at` (table: `execution_logs`) | `backend/app/db/models/agents.py` |
| `ModelConfig` | model | LLM provider config; `provider_type`, `display_name`, `api_base_url`, encrypted `api_key`, `enabled_models` JSONB | `backend/app/db/models/agents.py` |
| `AgentType` | model | Modified — `identity_id`, `role_id`, `model_id` (string), `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`; `plan` relationship (`uselist=False`) → `AgentPlan`; removed `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_*`, `model_config_id`, `model_name` | `backend/app/db/models/agents.py` |
| `AgentInputType` | str enum | `none`, `typed`, `conversation` | `backend/app/db/models/agents.py` |
| `AgentOutputType` | str enum | `auto`, `typed`, `markdown` | `backend/app/db/models/agents.py` |
| `AgentInstance` | model | Session handle tracking; lifecycle status and timing metadata; unchanged | `backend/app/db/models/agents.py` |
| `AgentPlanStatus` | str enum | `pending \| success \| failed` | `backend/app/db/models/agents.py` |
| `AgentPlan` | model | Persists generated plan and topology for an agent type; `plan_steps` and `topology` JSON, `generation_status`, `generation_error`, `agent_config_hash`; unique FK → `agent_types` with CASCADE delete | `backend/app/db/models/agents.py` |

### Backend Schemas (`backend/app/schemas/agents.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleCreate` | Pydantic model | `name`, `description`, `sop_ids`, `skill_ids`; no `allowed_identity_types` | `backend/app/schemas/agents.py` |
| `AgentRoleUpdate` | Pydantic model | All fields optional; no `allowed_identity_types` | `backend/app/schemas/agents.py` |
| `AgentRoleRead` | Pydantic model | Includes `sop_ids`, `skill_ids`; no `allowed_identity_types` | `backend/app/schemas/agents.py` |
| `AgentRoleIdentityAssignment` | Pydantic model | `{identity_ids: UUID[]}` for bulk role→identity assignment | `backend/app/schemas/agents.py` |
| `AgentRoleAssignment` | Pydantic model | `{role_ids: UUID[]}` for bulk identity→role assignment | `backend/app/schemas/agents.py` |
| `AgentIdentityCreate` | Pydantic model | `realm_name`, `realm_username`, `identity_type`, `status` | `backend/app/schemas/agents.py` |
| `AgentIdentityUpdate` | Pydantic model | All fields optional | `backend/app/schemas/agents.py` |
| `AgentIdentityRead` | Pydantic model | Includes `token_expires_at`; never exposes raw token values | `backend/app/schemas/agents.py` |
| `AgentIdentityOAuthAuthorizeResponse` | Pydantic model | `{authorization_url: str}` returned by the authorize endpoint | `backend/app/schemas/agents.py` |
| `AgentJobCreate` | Pydantic model | Input for enqueuing a session (API path: `/agents/sessions`) | `backend/app/schemas/agents.py` |
| `AgentJobStatusRead` | Pydantic model | Subset fields for status polling; filter params: `status`, `since` | `backend/app/schemas/agents.py` |
| `AgentJobRead` | Pydantic model | Full fields including `output_data`, `conversation_history: list[dict]` | `backend/app/schemas/agents.py` |
| `ExecutionLogRead` | Pydantic model | `id`, `session_id`, `system_instruction`, `user_prompt`, `logged_at` | `backend/app/schemas/agents.py` |
| `ExecutionLogEntryRead` | Pydantic model | `id`, `session_id`, `timestamp`, `log_level`, `event_type`, `message`, `data: dict` — individual execution event entry | `backend/app/schemas/agents.py` |
| `ModelConfigCreate` | Pydantic model | `provider_type`, `display_name`, `api_base_url`, `api_key`, `enabled_models: list[str]` | `backend/app/schemas/agents.py` |
| `ModelConfigUpdate` | Pydantic model | All fields optional; omitting `api_key` leaves existing credential unchanged | `backend/app/schemas/agents.py` |
| `ModelConfigRead` | Pydantic model | `id`, `provider_type`, `display_name`, `api_base_url`, `has_credentials: bool`, `enabled_models: list[str]`; no credential fields | `backend/app/schemas/agents.py` |
| `AgentTypeCreate` | Pydantic model | Modified — added `model_id: str`; removed `model_config_id`, `model_name`, `llm_provider`, `llm_model`, `llm_api_key` | `backend/app/schemas/agents.py` |
| `AgentTypeUpdate` | Pydantic model | Modified — same field changes as `AgentTypeCreate` | `backend/app/schemas/agents.py` |
| `AgentTypeRead` | Pydantic model | Modified — exposes `model_id: str`; gains `plan: AgentPlanRead \| None`; no `model_config_id` FK, no raw LLM credential fields | `backend/app/schemas/agents.py` |
| `PlanStepRead` | Pydantic model | Single plan step: `order`, `type`, `name`, `description` | `backend/app/schemas/agents.py` |
| `TopologyNodeRead` | Pydantic model | Topology node: `id`, `type`, `label`, `meta` | `backend/app/schemas/agents.py` |
| `TopologyEdgeRead` | Pydantic model | Topology edge: `source`, `target`, `label` | `backend/app/schemas/agents.py` |
| `AgentPlanRead` | Pydantic model | Full plan record with embedded `plan_steps`, `topology_nodes`, `topology_edges`, `generation_status`, `generation_error`, `agent_config_hash` | `backend/app/schemas/agents.py` |

### Backend Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleService` | class | Role CRUD; `assign_identities()`, `remove_identity()`, `list_identities()`, `is_identity_assigned()`; MCP session assignment with one-session-per-server enforcement; invalidates permission cache on writes | `backend/app/services/agents/role_service.py` |
| `AgentIdentityService` | class | Identity CRUD; OAuth authorize URL generation; token exchange and encrypted storage; `refresh_token()`, `get_reauth_url()`; `assign_roles()`, `remove_role()`, `list_roles()` | `backend/app/services/agents/identity_service.py` |
| `AgentPermissionManager` | class | Resolves `AgentRole → SOPs → Skills → MCP tools`; tool identifiers use `mcp_slug/tool_name`; LRU cache keyed on `role_id`; `invalidate(role_id)` called on role writes | `backend/app/services/agents/permission_manager.py` |
| `RealmManager` | class | Agent realm initialization in OIDC provider; realm-level token policies; registers platform OAuth client | `backend/app/services/identity/realm_manager.py` |
| `TokenRefreshService` | class | Background proactive token refresh for agent identities approaching expiry; updates `AgentIdentity` with re-encrypted token pair | `backend/app/services/agents/token_refresh_service.py` |
| `AgentSessionService` | class | Session lifecycle management: `enqueue()` (INSERT queued), state transitions, result persistence; tracks `conversation_history` | `backend/app/services/agents/session_service.py` |
| `SessionDispatcher` | class | Background dispatch worker; `SELECT … FOR UPDATE SKIP LOCKED`; dispatches to `AgentRuntimeExecutor` | `backend/app/services/agents/session_dispatcher.py` |
| `AgentRuntimeExecutor` | class | LangChain deep agent observe-reason-act loop; validates identity→role assignment via `agent_role_identities`; captures `ExecutionLogEntry` before first LLM call; injects MCP session context into system instruction | `backend/app/services/agents/runtime_executor.py` |
| `TaskAgentLoop` | class | LangChain deep agent loop for task-based agents; single result output | `backend/app/services/agents/agent_loop.py` |
| `ConversationalAgentLoop` | class | LangChain deep agent loop for conversational agents; multi-turn with `conversation_history` state | `backend/app/services/agents/agent_loop.py` |
| `ModelBindingLayer` | class | Resolves `AgentType.model_id` string to a `ModelConfig`; instantiates correct LangChain/LiteLLM client; sends chat completion requests | `backend/app/services/agents/model_binding.py` |
| `ModelConfigService` | class | CRUD for `ModelConfig`; encrypts/decrypts credentials; `fetch_available_models(config_id)` | `backend/app/services/agents/model_config_service.py` |
| `AgentInstanceManager` | class | Session handle management; execution logic removed | `backend/app/services/agents/instance_manager.py` |
| `PlanGenerationService` | class | LLM-based plan generation on agent type save; constructs prompt with agent context; invokes LLM; parses response into structured plan steps; traverses role→SOP→Skill→Tool graph; upserts `AgentPlan`; non-blocking error handling | `backend/app/services/agents/plan_generation_service.py` |
| `TopologyBuilderService` | class | Converts role→SOP→Skill→Tool graph to `nodes`/`edges` topology dict; deterministic node IDs for stable rendering | `backend/app/services/agents/topology_builder_service.py` |
| `AgentRuntimeLoader` | class | Loads saved plan from `agent_plans` on session init; injects plan into system context for execution guidance; graceful degradation when no plan exists | `backend/app/services/agents/runtime_loader.py` |
| `SopAgentExecutor` | class | **Superseded** — retained in codebase but not invoked by job-queue flow; execution handled by `AgentRuntimeExecutor` | `backend/app/services/agents/sop_executor.py` |
| `SkillfulAgentExecutor` | class | **Superseded** — retained in codebase but not invoked by job-queue flow; execution handled by `AgentRuntimeExecutor` | `backend/app/services/agents/skillful_executor.py` |
| `AgentGraphState` | class | **Superseded** — old LangGraph TypedDict; file retained but not imported; replaced by `TaskAgentLoop`/`ConversationalAgentLoop` | `backend/app/services/agents/agent_state.py` |
| `ConversationalAgentState` | class | **Superseded** — old LangGraph TypedDict; file retained but not imported; replaced by `ConversationalAgentLoop` | `backend/app/services/agents/agent_state.py` |

### Backend API (`backend/app/api/v1/agents.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleRouter` | router | Mounts all `/agents/roles` endpoints | `backend/app/api/v1/agents.py` |
| `AgentIdentityRouter` | router | Mounts all `/agents/identities` endpoints | `backend/app/api/v1/agents.py` |
| `AgentOAuthRouter` | router | Mounts `/agents/identities/oauth/authorize` and `/agents/oauth/callback` | `backend/app/api/v1/agents.py` |
| `AgentJobRouter` | router | Mounts all `/agents/sessions` endpoints | `backend/app/api/v1/agents.py` |
| `AgentTypeRouter` | router | CRUD for AgentType; create and update handlers call `PlanGenerationService` after commit; response includes `plan: AgentPlanRead \| null` | `backend/app/api/v1/agents.py` |
| `AgentInstanceRouter` | router | Instance listing and force-termination; unchanged | `backend/app/api/v1/agents.py` |
| `ModelConfigRouter` | router | Mounts all `/agents/model-configs` endpoints | `backend/app/api/v1/agents.py` |

### Alembic Migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `add_agent_plans` | migration | Creates `agent_plans` table with all columns, unique constraint on `agent_type_id`, and FK to `agent_types` with CASCADE delete | `backend/alembic/versions/fcbe5b250e08_add_agent_plans.py` |

### Frontend Pages (`frontend/src/pages/agents/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleListPage` | component | Table view; Name, SOP count chip, Skill count chip, Edit/Delete actions | `frontend/src/pages/agents/AgentRoleListPage.tsx` |
| `AgentRoleDialog` | component | Create/edit; SOP checkbox list, Skill checkbox list, MCP tool preview panel (debounced, edit mode only); assigned identities and MCP sessions with Assign/Remove | `frontend/src/pages/agents/AgentRoleDialog.tsx` |
| `AssignIdentitiesToRoleDialog` | component | Multi-select dialog to bulk-assign identities to a role | `frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx` |
| `AssignMcpSessionsToRoleDialog` | component | Multi-select dialog to assign MCP sessions to a role; filtered by servers whose tools the role uses; one-session-per-server enforced | `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx` |
| `AgentIdentityListPage` | component | Table view; realm_name, realm_username, token status chip, identity status chip; Refresh Token and Re-Authenticate per row | `frontend/src/pages/agents/AgentIdentityListPage.tsx` |
| `AgentIdentityDialog` | component | Create/edit; realm_name, realm_username; "Sign In as Agent" OAuth button opens agent realm popup; reflects token status after callback | `frontend/src/pages/agents/AgentIdentityDialog.tsx` |
| `AssignRolesToIdentityDialog` | component | Multi-select dialog to bulk-assign roles to an identity | `frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx` |
| `AgentOAuthCallbackPage` | component | Loaded in OAuth popup; exchanges code via backend callback; postMessages result to opener; calls `window.close()` | `frontend/src/pages/agents/AgentOAuthCallbackPage.tsx` |
| `AgentTypeForm` | component | Modified — fields: `identity_id`, `role_id`, `model_id` (string dropdown across all configs), `system_instruction`, `input_type`/`output_type` (+schemas); removed `model_config_id`, `model_name`, `llm_*`; validates identity is assigned to selected role | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentJobLaunchDialog` | component | Dynamic input form per `input_type`; POSTs to `/agents/sessions`; shows returned session ID | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| `AgentJobPage` | component | Session metadata, status chip, 3 s polling (task agents), WebSocket chat UI (conversational agents), result panel; fetches `ExecutionLogEntry[]` inline and passes to `LogViewer`; optional `sessionId` prop for embedded dialog usage; conditionally hides back button when embedded | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `SessionExecutionLogsDialog` | component | Retained but no longer opened from `AgentJobPage`; "View Execution Logs" button removed from the job page | `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx` |
| `AgentManagementPage` | component | Agent types table; row click opens `AgentTypeDetailsDialog` (via `detailsDialogTypeId` state); inline instances sub-table removed; added "Role" and "Identity" columns resolved via `useAgentRoles()`/`useAgentIdentities()` name lookup maps; `AgentTypeDetailsDialog` invalidates `['agents','types']` query on close; Launch (▶) action per row retained; plan preview still opens `PlanPreviewModal` after save | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentInstanceDashboardPage` | component | Renamed to "Agent Executions"; route `/agents/executions` (redirect from `/agents/instances`); optional `agentTypeId` prop for dialog embedding; agent type filter dropdown via `useAgentTypes()`; View button opens `AgentExecutionDetailsDialog` instead of navigating away; status, date range, and agent type filter controls | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` |
| `ModelConfigListPage` | component | Table view; display_name, provider_type, credential status chip, Edit/Delete | `frontend/src/pages/agents/ModelConfigListPage.tsx` |
| `ModelConfigDialog` | component | Create/edit; provider_type select, display_name, api_base_url, api_key (masked), enabled_models chip multi-select via "List Models" | `frontend/src/pages/agents/ModelConfigDialog.tsx` |

### Frontend Types (`frontend/src/types/index.ts`)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRole` | interface | `id`, `name`, `description`, `sop_ids`, `skill_ids`; no `allowed_identity_types` | `frontend/src/types/index.ts` |
| `AgentIdentity` | interface | `id`, `name`, `identity_type`, `realm_name`, `realm_username`, `auth_provider`, `status`, `token_expires_at` | `frontend/src/types/index.ts` |
| `AgentIdentityType` | type alias | `'realm_user'` | `frontend/src/types/index.ts` |
| `AgentIdentityStatus` | type alias | `'active' \| 'suspended' \| 'deprovisioned'` | `frontend/src/types/index.ts` |
| `AgentJob` | interface | `id`, `agent_type_id`, `input_data`, `status`, `output_data`, `error_message`, `conversation_history` | `frontend/src/types/index.ts` |
| `AgentJobStatus` | type alias | `'queued' \| 'running' \| 'completed' \| 'failed'` | `frontend/src/types/index.ts` |
| `AgentInputType` | type alias | `'none' \| 'typed' \| 'conversation'` | `frontend/src/types/index.ts` |
| `AgentOutputType` | type alias | `'auto' \| 'typed' \| 'markdown'` | `frontend/src/types/index.ts` |
| `AgentType` | interface | Modified — added `model_id: string`, `plan?: AgentPlan \| null`; removed `model_config_id`, `model_name`, `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key` | `frontend/src/types/index.ts` |
| `ModelConfig` | interface | `id`, `provider_type`, `display_name`, `api_base_url`, `has_credentials`, `enabled_models: string[]` | `frontend/src/types/index.ts` |
| `ModelProviderType` | type alias | `'openai' \| 'anthropic' \| 'litellm_proxy' \| 'azure_openai'` | `frontend/src/types/index.ts` |
| `AgentPlanStatus` | type alias | `'pending' \| 'success' \| 'failed'` | `frontend/src/types/index.ts` |
| `PlanStep` | interface | `order`, `type`, `name`, `description` | `frontend/src/types/index.ts` |
| `TopologyNode` | interface | `id`, `type`, `label`, `meta` | `frontend/src/types/index.ts` |
| `TopologyEdge` | interface | `source`, `target`, `label` | `frontend/src/types/index.ts` |
| `AgentPlan` | interface | Full plan record; mirrors `AgentPlanRead`; `plan_steps`, `topology_nodes`, `topology_edges`, `generation_status`, `generation_error`, `agent_config_hash` | `frontend/src/types/index.ts` |
| `ExecutionLogEntry` | interface | Individual log entry: `event_type`, `message`, `data`, `timestamp`; moved from local `SessionExecutionLogsDialog` to shared types | `frontend/src/types/index.ts` |
| `StructuredLog` | interface | Container for all three presentation levels produced by `LogPresenter`: `summary: LogSummary`, `steps: WorkingStep[]`, and `rawLog: string` | `frontend/src/types/index.ts` |
| `LogSummary` | interface | Summary data: identity, role, model, SOPs/skills, plan progress, result status, `startedAt`/`completedAt` timestamps derived from first/last entry | `frontend/src/types/index.ts` |
| `WorkingStep` | interface | Single LLM iteration or tool call: `message`, `timestamp`, `iconType: WorkingStepIconType`, and optional `detail: WorkingStepDetail` | `frontend/src/types/index.ts` |
| `WorkingStepDetail` | interface | Collapsible detail block for a step: `label` and `content` string | `frontend/src/types/index.ts` |
| `WorkingStepIconType` | type alias | `'llm' \| 'tool' \| 'success' \| 'error' \| 'info'` | `frontend/src/types/index.ts` |

### Frontend Components (`frontend/src/components/agents/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTypeDetailsDialog` | component | Three-tab dialog (Details, Plan Preview, Execution Logs) for an agent type; fetches via `useAgentType(id)`; Details tab has clickable role/identity names opening `AgentRoleViewDialog`/`AgentIdentityViewDialog`; Execution Logs tab shows last 10 sessions with "View" opening `AgentExecutionDetailsDialog`; "Run Agent" opens `AgentJobLaunchDialog`; follows Dialog Error Handling Standard | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentExecutionsDialog` | component | Dialog wrapper for `AgentInstanceDashboardPage`; allows viewing the full execution list in dialog context without navigating away; pre-filtered by `agentTypeId` | `frontend/src/components/agents/AgentExecutionsDialog.tsx` |
| `AgentExecutionDetailsDialog` | component | Dialog wrapper for `AgentJobPage`; shows full session details and logs in dialog context; opened from the Execution Logs tab View button or post-launch | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `AgentPlanContent` | component | Presentational component for plan steps and topology diagram; extracted from `PlanPreviewModal`; receives `plan: AgentPlan \| null \| undefined`; reused by both `PlanPreviewModal` and the Plan Preview tab of `AgentTypeDetailsDialog` | `frontend/src/components/agents/AgentPlanContent.tsx` |
| `AgentRoleViewDialog` | component | Read-only view dialog for a single agent role; two-column detail grid; Edit and Close actions; opened from clickable role name in `AgentTypeDetailsDialog` Details tab | `frontend/src/components/agents/AgentRoleViewDialog.tsx` |
| `AgentIdentityViewDialog` | component | Read-only view dialog for a single agent identity; two-column detail grid; Edit and Close actions; opened from clickable identity name in `AgentTypeDetailsDialog` Details tab | `frontend/src/components/agents/AgentIdentityViewDialog.tsx` |
| `PlanPreviewModal` | component | MUI Dialog displaying plan steps as an ordered list with step-type chips and topology diagram after agent type save; shows error state when `generation_status = failed`; follows Dialog Error Handling Standard; plan content rendered via `AgentPlanContent` | `frontend/src/components/agents/PlanPreviewModal.tsx` |
| `TopologyDiagramRenderer` | component | Renders node-edge topology payload as a visual diagram; distinguishes node types (role, sop, skill, tool) by colour/icon; handles empty state | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |

### Frontend Components (`frontend/src/components/logs/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LogViewer` | component | Root log display component; owns `rawMode` boolean state; calls `presentLog()` once per render cycle; conditionally renders `LogSummaryPanel` + `WorkingStepsPanel` or a monospace raw log block; renders `RawLogToggle` in the header | `frontend/src/components/logs/LogViewer.tsx` |
| `LogSummaryPanel` | component | Execution Summary card: identity, role, model, SOPs/skills as MUI Chip elements, plan progress, result status badge; receives `LogSummary` prop; no data fetching or transformation | `frontend/src/components/logs/LogSummaryPanel.tsx` |
| `WorkingStepsPanel` | component | Execution Details card: flat top-level steps as log rows; all LLM iterations and tool calls in a single MUI `Collapse` section collapsed by default; each step may contain an expandable detail block for plan text or tool input/output; receives `WorkingStep[]` prop | `frontend/src/components/logs/WorkingStepsPanel.tsx` |
| `RawLogToggle` | component | "Friendly / Raw Output" labelled toggle switch and copy-to-clipboard button (visible in raw mode only); receives `checked`, `onChange`, and `rawLogText` props; no internal state | `frontend/src/components/logs/RawLogToggle.tsx` |

### Frontend Services (`frontend/src/services/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `presentLog` | function | Pure synchronous transformation: `presentLog(executionLog, entries): StructuredLog`; parses `system_instruction` for identity, role, model, SOPs/skills; maps entries to `WorkingStep[]` with `iconType` derived from `event_type`; derives result status from last entry; serialises entries to timestamped raw log string; no network calls | `frontend/src/services/LogPresenter.ts` |

### Frontend Hooks (`frontend/src/hooks/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useExecutionLogs` | hook | Fetches `ExecutionLogRead[]` from `GET /agents/sessions/{id}/execution-logs`; used by `AgentJobPage` to supply system instruction and user prompt to `LogViewer` | `frontend/src/hooks/useExecutionLogs.ts` |

### Frontend i18n (`frontend/src/i18n/locales/`)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `agents.plan.*` | translation namespace | All plan preview UI strings: title, step types, node types, error states, close button | `frontend/src/i18n/locales/en.json` |
| `agents.sessions.logViewer.*` | translation namespace | All Log Viewer UI strings: panel titles, toggle labels, copy button, status labels, step type labels | `frontend/src/i18n/locales/en.json` |
| `nav.aiAgent` | i18n key | "AI Agent" nav group label | `frontend/src/i18n/locales/en.json` |
| `nav.agentTypes` | i18n key | "Agent Types" nav item label (group child) | `frontend/src/i18n/locales/en.json` |
| `nav.agentExecutions` | i18n key | "Agent Executions" nav item label; replaces `nav.agentInstances` | `frontend/src/i18n/locales/en.json` |
| `nav.agentLogs` | i18n key | "Agent Logs" nav item label (group child) | `frontend/src/i18n/locales/en.json` |
| `nav.agentRoles` | i18n key | "Agent Roles" nav item label (group child) | `frontend/src/i18n/locales/en.json` |
| `nav.agentIdentities` | i18n key | "Agent Identities" nav item label (group child) | `frontend/src/i18n/locales/en.json` |
| `agents.roles.viewTitle` | i18n key | Title for `AgentRoleViewDialog` | `frontend/src/i18n/locales/en.json` |
| `agents.identities.viewTitle` | i18n key | Title for `AgentIdentityViewDialog` | `frontend/src/i18n/locales/en.json` |
| `agents.sessions.detailsTitle` | i18n key | Title for `AgentExecutionDetailsDialog` | `frontend/src/i18n/locales/en.json` |
| `agents.sessions.dashboardTitle` | i18n key | Updated dashboard title — "Agent Executions" (was "Agent Instances") | `frontend/src/i18n/locales/en.json` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_topology_builder_service` | unit test | Happy path, empty graph, node ID stability, duplicate tool deduplication | `backend/tests/unit/services/test_topology_builder_service.py` |
| `test_plan_generation_service` | unit test | Happy path, error path (non-blocking), hash stability, no-role case, LLM timeout handling | `backend/tests/unit/services/test_plan_generation_service.py` |
| `test_agent_types_plan` | integration test | Schema verification, unique constraint, CASCADE delete, save-response shape, upsert behaviour, failed generation path | `backend/tests/integration/api/test_agent_types_plan.py` |
| `PlanPreviewModal.test` | frontend component test | Renders plan steps, error state, close callback, hidden when closed, Dialog Error Handling Standard | `frontend/src/__tests__/PlanPreviewModal.test.tsx` |
| `AgentTypeDetailsDialog.test` | frontend component test | Loading state, all three tabs, clickable role/identity name behaviour, error handling, tab reset on open | `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` |
| `AgentRoleViewDialog.test` | frontend component test | Renders role detail grid, edit and close actions, loading and error states | `frontend/src/__tests__/AgentRoleViewDialog.test.tsx` |
| `AgentIdentityViewDialog.test` | frontend component test | Renders identity detail grid, edit and close actions, loading and error states | `frontend/src/__tests__/AgentIdentityViewDialog.test.tsx` |
| `AgentManagementPage.test` | frontend component test | Row-click opens dialog, Role/Identity column rendering, plan preview launch; mock updated for `useAgentType` and `defaultAgentTypeFormValues` | `frontend/src/__tests__/AgentManagementPage.test.tsx` |
| `agent-navigation.spec.ts` | E2E test | Nav group expand/collapse, agent executions page, agent type filter dropdown, dialog open/close flows | `e2e/tests/agent-navigation.spec.ts` |
