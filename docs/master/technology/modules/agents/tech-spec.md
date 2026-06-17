# Module: agents — Tech Spec

## Overview

The agents module is the central execution layer for AI agents on the platform. It manages agent type definitions, a role-governed permission model, first-class OIDC agent identities, and an asynchronous session queue dispatched by a background `SessionDispatcher` and executed by `AgentRuntimeExecutor` using the **LangChain deep agent** observe-reason-act loop. Permissions flow through `AgentRole → SOPs → Skills → MCP tools` and are resolved by `AgentPermissionManager` with an LRU cache. Agent identities are registered users in a dedicated agent realm and authenticate via the OAuth authorization code flow; their tokens are stored AES-256 encrypted and proactively refreshed by `TokenRefreshService`. LLM provider configuration is managed through `ModelConfig` records, and `ModelBindingLayer` resolves an `AgentType.model_id` string to the correct provider client at runtime. The module also owns workflow-generation model selection settings consumed by Skill and SOP AI authoring endpoints. Agent Types support ordered lists of SOP and skill bindings (`AgentTypeSopBinding`, `AgentTypeSkillBinding`) that define a curated capability subset drawn from the role's permissions. On every agent type save, `PlanGenerationService` traverses the curated binding list (or the full role→SOP→Skill→Tool graph when no bindings exist), invokes the configured LLM, and persists a structured implementation plan and topology in the `agent_plans` table; plan generation is non-blocking (failures write a `failed` status row without blocking the save). When a session starts, `AgentRuntimeLoader` injects the saved plan into the agent's system context to ensure compliant, predictable execution.

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
| `AgentSessionService` | Enqueues sessions (`INSERT` with `status = queued`), manages state transitions (`queued → running → waiting_for_human → completed / failed`), persists results; tracks `conversation_history` for conversational agents; joins `AgentType` and `Identity` to populate `agent_type_name` and `triggered_by_user_name` on session reads |
| `SessionDispatcher` | Background worker; polls `queued` sessions using `SELECT … FOR UPDATE SKIP LOCKED`; dispatches to `AgentRuntimeExecutor`; manages concurrency |
| `AgentRuntimeExecutor` | Orchestrates agent execution using the LangChain deep agent observe-reason-act loop; validates that the agent identity is assigned to the agent role via `agent_role_identities` before execution; raises `PermissionDeniedError` if not; captures `ExecutionLogEntry` (system instruction + user prompt) before first LLM call; loads MCP session context from role's assigned sessions and injects pre-configured parameters into the system instruction; detects passthrough sessions and retrieves the executing agent's identity JWT via `_get_agent_identity_jwt()`; persists result via `save_result` |
| `TaskAgentLoop` | LangChain deep agent loop for task-based agents; observe-reason-act context producing a single structured or markdown result | 
| `ConversationalAgentLoop` | LangChain deep agent loop for conversational agents; multi-turn observe-reason-act loop with `conversation_history` state |
| `ModelBindingLayer` | Resolves `AgentType.model_id` string to a matching `ModelConfig` (scans `enabled_models`; falls back to provider-prefix matching); instantiates the correct LangChain/LiteLLM client; sends chat completion requests |
| `ModelConfigService` | CRUD for `ModelConfig`; encrypts/decrypts API credentials (AES-256); `fetch_available_models(config_id)` returns `enabled_models` if non-empty, otherwise queries live from the configured provider |
| `workflow_generation_settings` | Settings module that gets and sets the selected workflow generation model identifier used by authoring APIs |
| `workflow_authoring_service` | Shared workflow authoring service module used by Skill and SOP generation and preview endpoints |
| `AgentInstanceManager` | Retained for session handle management; execution logic removed |
| `PlanGenerationService` | Orchestrates LLM-based plan generation on agent type save; traverses role→SOP→Skill→Tool graph; applies system-instruction-aware SOP filtering before prompt assembly; constructs prompt with agent context (instructions, role, SOPs, skills, tools); invokes configured LLM; parses response into structured plan steps; calls `TopologyBuilderService`; upserts `AgentPlan`; non-blocking — exceptions write a `failed` status row |
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
| `ModelConfig` | SQLAlchemy model for LLM provider configuration; 12 supported providers across two dispatch families (OpenAI-compatible: `openai`, `azure_openai`, `litellm_proxy`, `mistral`, `groq`, `together`, `fireworks`, `perplexity`, `deepseek`; native-API: `anthropic`, `gemini`, `cohere`); `display_name`, `api_base_url`, encrypted `api_key`, `enabled_models` (JSONB) |
| `AgentType` | SQLAlchemy model — modified; fields: `identity_id`, `role_id`, `model_id` (string), `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`; removed: `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key`, `model_config_id`, `model_name` |
| `AgentInstance` | SQLAlchemy model for session handle tracking; unchanged |
| `AgentPlanStatus` | `str` enum — `pending`, `success`, `failed`; represents the lifecycle of a plan generation attempt |
| `AgentPlan` | SQLAlchemy model; persists the latest generated plan for an agent type; stores `plan_steps` and `topology` as JSON, `generation_status`, `generation_error`, `agent_config_hash`; unique FK → `agent_types` with CASCADE delete |
| `AgentIdentityType` | `str` enum — `realm_user` |
| `AgentIdentityStatus` | `str` enum — `active`, `suspended`, `deprovisioned` |
| `AgentJobStatus` | `str` enum — `queued`, `running`, `waiting_for_human`, `completed`, `failed` |
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
| `AgentTypeForm` | Modified — full form component; new fields: `identity_id`, `role_id`, `model_id` (string dropdown populated across all `ModelConfig` records), `system_instruction`, `input_type` (+schema), `output_type` (+schema); default SOP selector is shown for all input types and required only when `input_type = none`; removed: `model_config_id`, `model_name`, `llm_*` fields; ADD validation: selected identity must be assigned to selected role |
| `AgentJobLaunchDialog` | Dynamic input form per `input_type` (none / typed / conversation); POSTs to `/agents/sessions`; shows returned session ID |
| `AgentJobPage` | Session metadata, status chip, 3 s polling for task agents; WebSocket chat UI for conversational agents; result panel (typed JSON or markdown); execution log section (system instruction + user prompt from `ExecutionLogEntry`) |
| `AgentManagementPage` | Modified — uses updated `AgentTypeForm`; sends `primary_sop_id` for all input types while requiring it only when `input_type = none`; adds Launch (▶) action per row linking to `AgentJobPage`; after a successful save reads `plan` from the response, stores it in `planData` state, and opens `PlanPreviewModal`; clears plan state on modal close |
| `PlanPreviewModal` | MUI Dialog opened after a successful agent type save; displays plan steps as an ordered list with step-type chips; hosts `TopologyDiagramRenderer`; shows error state when `generation_status = failed`; follows Dialog Error Handling Standard |
| `TopologyDiagramRenderer` | Renders node-edge topology payload as a visual diagram; distinguishes node types (role, sop, skill, tool) by colour/icon; handles empty state |
| `AgentInstanceDashboardPage` | Admin view of all `AgentJob` instances; columns: agent type name, status chip, triggered by, started/completed times; `status` and `since` filter controls |
| `ModelConfigListPage` | Table view of all model configurations; display_name, provider_type, credential status chip, Edit/Delete actions; includes workflow generation model selection and persistence |
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
| `GET` | `/api/v1/agents/roles/{role_id}/available-mcp-sessions` | List assignable MCP sessions filtered by servers whose tools the role uses; each item includes `auth_type` |

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
| `GET` | `/api/v1/agents/sessions/{id}/logs/stream` | Live NDJSON stream of append-only execution log entries during active runs; emits terminal completion marker |

### Model Configurations

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/model-configs` | List all model configurations |
| `POST` | `/api/v1/agents/model-configs` | Create model config; API credentials AES-256 encrypted |
| `GET` | `/api/v1/agents/model-configs/{id}` | Get config; credential fields never returned |
| `PUT` | `/api/v1/agents/model-configs/{id}` | Update config; omitted `api_key` leaves existing credential unchanged |
| `DELETE` | `/api/v1/agents/model-configs/{id}` | Delete config; 409 if any `AgentType` references it |
| `GET` | `/api/v1/agents/model-configs/{id}/models` | Returns `enabled_models` if non-empty; otherwise queries live from the provider |
| `GET` | `/api/v1/agents/model-configs/workflow-generation` | Returns selected workflow generation model and available model options |
| `PUT` | `/api/v1/agents/model-configs/workflow-generation` | Updates selected workflow generation model after validation against available options |

### Intervene Requests

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/intervene/requests` | List intervene requests (filterable by status, intervention_type, agent_session_id, pagination) |
| `GET` | `/api/v1/intervene/requests/{id}` | Get single request with full context including response |
| `POST` | `/api/v1/intervene/requests/{id}/respond` | Submit operator response (approval bool, choice string, or text string) |
| `POST` | `/api/v1/intervene/requests/{id}/cancel` | Cancel a pending request |
| `GET` | `/api/v1/intervene/metrics` | Dashboard metrics: pending count, avg response time, resolution rate |

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
| `AgentJob` | model | Async session tracking; `conversation_history` JSONB for conversational agents; status includes `waiting_for_human` (table: `agent_jobs`) | `backend/app/db/models/agents.py` |
| `AgentJobStatus` | str enum | `queued`, `running`, `waiting_for_human`, `completed`, `failed` | `backend/app/db/models/agents.py` |
| `AgentPromptLog` | model | Prompt capture before first LLM call; `session_id` FK → agent_jobs CASCADE; `system_instruction`, `user_prompt`, `logged_at` (table: `execution_logs`) | `backend/app/db/models/agents.py` |
| `ExecutionLogEntry` | model | Structured execution log entry model used for guardrail decision and counter audit events | `backend/app/db/models/session_logs.py` |
| `ModelConfig` | model | LLM provider config; `provider_type`, `display_name`, `api_base_url`, encrypted `api_key`, `enabled_models` JSONB | `backend/app/db/models/agents.py` |
| `AgentType` | model | Modified — `identity_id`, `role_id`, `model_id` (string), `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`; `plan` relationship (`uselist=False`) → `AgentPlan`; `sop_bindings` and `skill_bindings` relationships → `AgentTypeSopBinding`/`AgentTypeSkillBinding` (cascade delete); removed `mode`, `primary_sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_*`, `model_config_id`, `model_name` | `backend/app/db/models/agents.py` |
| `AgentTypeSopBinding` | model | Join: AgentType ↔ Sop with `order`; unique `(agent_type_id, sop_id)`; surrogate UUID PK | `backend/app/db/models/agents.py` |
| `AgentTypeSkillBinding` | model | Join: AgentType ↔ Skill with `order`; unique `(agent_type_id, skill_id)`; surrogate UUID PK | `backend/app/db/models/agents.py` |
| `AgentInputType` | str enum | `none`, `typed`, `conversation` | `backend/app/db/models/agents.py` |
| `AgentOutputType` | str enum | `auto`, `typed`, `markdown` | `backend/app/db/models/agents.py` |
| `AgentInstance` | model | Session handle tracking; lifecycle status and timing metadata; unchanged | `backend/app/db/models/agents.py` |
| `AgentPlanStatus` | str enum | `pending \| success \| failed` | `backend/app/db/models/agents.py` |
| `AgentPlan` | model | Persists generated plan and topology for an agent type; `plan_steps` and `topology` JSON, `generation_status`, `generation_error`, `agent_config_hash`; unique FK → `agent_types` with CASCADE delete | `backend/app/db/models/agents.py` |
| `InterveneRequestStatus` | str enum | `pending`, `responded`, `cancelled`, `expired` | `backend/app/db/models/intervene.py` |
| `InterventionType` | str enum | `approval`, `choice`, `text` | `backend/app/db/models/intervene.py` |
| `InterveneRequest` | model | Agent-initiated human intervention request; FK to `agent_jobs` and `agent_types`; tracks lifecycle status; extended with `conversation_session_id` FK to conversation sessions, `delegation_depth` (integer), and `conversation_session` ORM relationship | `backend/app/db/models/intervene.py` |
| `InterveneResponse` | model | Operator response to an intervene request; 1:1 FK to `intervene_requests`; FK to `identities` | `backend/app/db/models/intervene.py` |

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
| `AgentJobStatusRead` | Pydantic model | Subset fields for status polling; filter params: `status`, `since`; includes `agent_type_name`, `triggered_by_user_name` | `backend/app/schemas/agents.py` |
| `AgentJobRead` | Pydantic model | Full fields including `output_data`, `conversation_history: list[dict]`; includes `agent_type_name`, `triggered_by_user_name` | `backend/app/schemas/agents.py` |
| `ExecutionLogRead` | Pydantic model | `id`, `session_id`, `system_instruction`, `user_prompt`, `logged_at` | `backend/app/schemas/agents.py` |
| `ExecutionLogEntryRead` | Pydantic model | `id`, `session_id`, `timestamp`, `log_level`, `event_type`, `message`, `data: dict` — individual execution event entry | `backend/app/schemas/agents.py` |
| `ModelConfigCreate` | Pydantic model | `provider_type`, `display_name`, `api_base_url`, `api_key`, `enabled_models: list[str]` | `backend/app/schemas/agents.py` |
| `ModelConfigUpdate` | Pydantic model | All fields optional; omitting `api_key` leaves existing credential unchanged | `backend/app/schemas/agents.py` |
| `ModelConfigRead` | Pydantic model | `id`, `provider_type`, `display_name`, `api_base_url`, `has_credentials: bool`, `enabled_models: list[str]`; no credential fields | `backend/app/schemas/agents.py` |
| `WorkflowGenerationModelConfigRead` | Pydantic model | Response contract for selected workflow generation model and available options | `backend/app/schemas/agents.py` |
| `WorkflowGenerationModelConfigUpdate` | Pydantic model | Request contract for updating selected workflow generation model | `backend/app/schemas/agents.py` |
| `AgentTypeSopBindingCreate` | Pydantic model | `sop_id: uuid`, `order: int` | `backend/app/schemas/agents.py` |
| `AgentTypeSopBindingResponse` | Pydantic model | `id`, `agent_type_id`, `sop_id`, `sop_name`, `order` | `backend/app/schemas/agents.py` |
| `AgentTypeSkillBindingCreate` | Pydantic model | `skill_id: uuid`, `order: int` | `backend/app/schemas/agents.py` |
| `AgentTypeSkillBindingResponse` | Pydantic model | `id`, `agent_type_id`, `skill_id`, `skill_name`, `order` | `backend/app/schemas/agents.py` |
| `AgentTypeCreate` | Pydantic model | Modified — added `model_id: str`, `sop_bindings: list[AgentTypeSopBindingCreate]`, `skill_bindings: list[AgentTypeSkillBindingCreate]`; removed `model_config_id`, `model_name`, `llm_provider`, `llm_model`, `llm_api_key` | `backend/app/schemas/agents.py` |
| `AgentTypeUpdate` | Pydantic model | Modified — same field changes as `AgentTypeCreate` | `backend/app/schemas/agents.py` |
| `AgentTypeRead` | Pydantic model | Modified — exposes `model_id: str`, `sop_bindings: list[AgentTypeSopBindingResponse]`, `skill_bindings: list[AgentTypeSkillBindingResponse]`; gains `plan: AgentPlanRead \| None`; no `model_config_id` FK, no raw LLM credential fields | `backend/app/schemas/agents.py` |
| `PlanStepRead` | Pydantic model | Single plan step: `order`, `type`, `name`, `description` | `backend/app/schemas/agents.py` |
| `TopologyNodeRead` | Pydantic model | Topology node: `id`, `type`, `label`, `meta` | `backend/app/schemas/agents.py` |
| `TopologyEdgeRead` | Pydantic model | Topology edge: `source`, `target`, `label` | `backend/app/schemas/agents.py` |
| `AgentPlanRead` | Pydantic model | Full plan record with embedded `plan_steps`, `topology_nodes`, `topology_edges`, `generation_status`, `generation_error`, `agent_config_hash` | `backend/app/schemas/agents.py` |

### Backend Schemas (`backend/app/schemas/intervene.py`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `InterveneRequestCreate` | schema | Pydantic model for request creation: `agent_session_id`, `agent_type_id`, `intervention_type`, `reason`, `choices` (optional), `conversation_session_id` (optional), `delegation_depth` (optional) | `backend/app/schemas/intervene.py` |
| `InterveneRequestRead` | schema | Pydantic model for request response output; includes `agent_name`, `triggered_by_user_name`, `operator_user_name` when resolved, `conversation_session_id`, and `delegation_depth` | `backend/app/schemas/intervene.py` |
| `InterveneResponseSubmit` | schema | Pydantic model for operator response input: `approval_value`, `selected_choice`, or `text_value` depending on type | `backend/app/schemas/intervene.py` |
| `InterveneResponseRead` | schema | Pydantic model for response output; includes `operator_user_name` | `backend/app/schemas/intervene.py` |
| `InterveneMetrics` | schema | Pydantic model for dashboard metrics: `pending_count`, `avg_response_time_seconds`, `resolution_rate` | `backend/app/schemas/intervene.py` |

### Backend Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleService` | class | Role CRUD; `assign_identities()`, `remove_identity()`, `list_identities()`, `is_identity_assigned()`; MCP session assignment with one-session-per-server enforcement; `get_available_mcp_sessions()` includes `auth_type` in returned session dicts; invalidates permission cache on writes | `backend/app/services/agents/role_service.py` |
| `AgentIdentityService` | class | Identity CRUD; OAuth authorize URL generation; token exchange and encrypted storage; `refresh_token()`, `get_reauth_url()`; `assign_roles()`, `remove_role()`, `list_roles()` | `backend/app/services/agents/identity_service.py` |
| `AgentPermissionManager` | class | Resolves `AgentRole → SOPs → Skills → MCP tools`; tool identifiers use `mcp_slug/tool_name`; includes A2A permission evaluation for target agent type slugs derived from SOP `agent_delegation` steps; LRU cache keyed on `role_id`; `invalidate(role_id)` called on role writes | `backend/app/services/agents/permission_manager.py` |
| `RealmManager` | class | Agent realm initialization in OIDC provider; realm-level token policies; registers platform OAuth client | `backend/app/services/identity/realm_manager.py` |
| `TokenRefreshService` | class | Background proactive token refresh for agent identities approaching expiry; updates `AgentIdentity` with re-encrypted token pair | `backend/app/services/agents/token_refresh_service.py` |
| `AgentSessionService` | class | Session lifecycle management: `enqueue()` (INSERT queued), state transitions, result persistence; tracks `conversation_history` | `backend/app/services/agents/session_service.py` |
| `SessionDispatcher` | class | Background dispatch worker; `SELECT … FOR UPDATE SKIP LOCKED`; dispatches to `AgentRuntimeExecutor` | `backend/app/services/agents/session_dispatcher.py` |
| `AgentRuntimeExecutor` | class | LangChain deep agent observe-reason-act loop; validates identity→role assignment via `agent_role_identities`; captures `ExecutionLogEntry` before first LLM call; injects MCP session context into system instruction; enforces A2A target-agent permission checks and session-link lifecycle handoff metadata during delegation; detects passthrough sessions and calls `_get_agent_identity_jwt()` to retrieve the agent's access token | `backend/app/services/agents/runtime_executor.py` |
| `_extract_agent_delegation_target` | function | Extracts delegated target slug from canonical delegation tool names for status/event labeling | `backend/app/services/agents/runtime_executor.py` |
| `_run_task_loop_ar` | method | Runtime task loop enforcement path for iteration ceilings, delegated step budgets, and timeout guardrails | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn` | method | Conversational runtime path with mode-aware token guardrail handling and current-session usage reporting | `backend/app/services/agents/runtime_executor.py` |
| `execute_conversation_turn_from_context` | method | Context-driven conversation execution path used by chat transport, including additive status/tool events for delegation visibility | `backend/app/services/agents/runtime_executor.py` |
| `_get_agent_identity_jwt` | method | `AgentRuntimeExecutor._get_agent_identity_jwt()`; decrypts the executing agent's identity access token from the credential vault for passthrough sessions; returns error dict if token unavailable | `backend/app/services/agents/runtime_executor.py` |
| `_load_role_mcp_session_map` | method | `AgentRuntimeExecutor._load_role_mcp_session_map()`; returns `{session_id, auth_type}` per server; used to detect passthrough sessions at execution time | `backend/app/services/agents/runtime_executor.py` |
| `delegation_resumed` | status event | Emitted after `wait_for_a2a_response()` returns (sub-agent completed, HITL resolved); carries `agent_type`; used in `execute_conversation_turn_from_context` delegation path to trigger frontend delegation log polling restart | `backend/app/services/agents/runtime_executor.py` |
| `TaskAgentLoop` | class | LangChain deep agent loop for task-based agents; single result output | `backend/app/services/agents/agent_loop.py` |
| `ConversationalAgentLoop` | class | LangChain deep agent loop for conversational agents; multi-turn with `conversation_history` state | `backend/app/services/agents/agent_loop.py` |
| `ModelBindingLayer` | class | Resolves `AgentType.model_id` string to a `ModelConfig`; routes 12 providers through `PROVIDER_REGISTRY` dispatch facade (OpenAI-compatible and native-API families); sends chat completion requests via `\_call_openai_compat`, `\_call_anthropic`, `\_call_gemini`, `\_call_cohere` | `backend/app/services/agents/model_binding.py` |
| `PROVIDER_REGISTRY` | constant | Module-level registry mapping each of 12 provider keys to dispatch-family tag and default API base URL | `backend/app/services/agents/model_binding.py` |
| `ModelConfigService` | class | CRUD for `ModelConfig`; encrypts/decrypts credentials; `fetch_available_models(config_id)`; 12-provider model listing through `\_list_openai_compat_models`, `\_list_gemini_models`, `\_list_cohere_models`, and existing `\_list_*` helpers | `backend/app/services/agents/model_config_service.py` |
| `workflow_generation_settings` | module | Stores and retrieves selected workflow generation model identifier used by authoring APIs | `backend/app/services/agents/workflow_generation_settings.py` |
| `workflow_authoring_service` | module | Shared workflow generation and preview composition service used by Skill and SOP endpoints | `backend/app/services/agents/workflow_authoring_service.py` |
| `AgentInstanceManager` | class | Session handle management; execution logic removed | `backend/app/services/agents/instance_manager.py` |
| `PlanGenerationService` | class | LLM-based plan generation on agent type save; reads curated binding list from `AgentTypeSopBinding`/`AgentTypeSkillBinding`; when bindings exist, only bound SOPs/skills enter the plan prompt; when no bindings, falls back to all role-assigned SOPs/skills; constructs prompt with agent context; invokes LLM; parses response into structured plan steps; traverses graph; upserts `AgentPlan`; non-blocking error handling | `backend/app/services/agents/plan_generation_service.py` |
| `TopologyBuilderService` | class | Converts binding-filtered role→SOP→Skill→Tool graph to `nodes`/`edges` topology dict; deterministic node IDs for stable rendering; only bound entries appear when SOP scope is narrowed | `backend/app/services/agents/topology_builder_service.py` |
| `validate_bindings` | function | Validates SOP/skill binding entries against role-granted permissions; rejects references outside the role's assigned SOPs/skills with per-entry error messages; prevents duplicate references; invoked on agent type create and update | `backend/app/services/agents/binding_validation.py` |
| `AgentRuntimeLoader` | class | Loads saved plan from `agent_plans` on session init; injects plan into system context for execution guidance; graceful degradation when no plan exists | `backend/app/services/agents/runtime_loader.py` |
| `InterveneRequestStore` | service | CRUD + metrics for intervene requests; `create_request` accepts optional `conversation_session_id` and `delegation_depth`; `list_pending_for_conversation(session_id)` returns pending requests filtered by conversation session; `submit_response` auto-creates `ConversationTurn` of type `intervene_response` when `conversation_session_id` is present; `list_requests()` eager loads `agent_session.agent_type` and Identity for user names; `get_metrics()` returns pending count, avg response time, resolution rate | `backend/app/services/agents/intervene_service.py` |
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
| `create_agent_type` | endpoint | Agent type create endpoint where guardrail policy defaults and validation are applied before persistence | `backend/app/api/v1/agents.py` |
| `update_agent_type` | endpoint | Agent type update endpoint where guardrail policy compatibility checks and validation are applied | `backend/app/api/v1/agents.py` |
| `AgentInstanceRouter` | router | Instance listing and force-termination; unchanged | `backend/app/api/v1/agents.py` |
| `ModelConfigRouter` | router | Mounts all `/agents/model-configs` endpoints | `backend/app/api/v1/agents.py` |
| `get_session_execution_logs` | endpoint | Pull endpoint returning ordered `ExecutionLogEntryRead[]` for a session | `backend/app/api/v1/agents.py` |
| `stream_session_execution_logs` | endpoint | Live NDJSON stream endpoint for incremental execution-log entries and terminal completion marker | `backend/app/api/v1/agents.py` |
| `get_session_prompt_logs` | endpoint | Pull endpoint returning captured system-instruction and user-prompt records (`ExecutionLogRead[]`) | `backend/app/api/v1/agents.py` |
| `get_workflow_generation_model` | endpoint | Returns selected workflow generation model and available model options | `backend/app/api/v1/agents.py` |
| `set_workflow_generation_model` | endpoint | Validates and updates selected workflow generation model setting | `backend/app/api/v1/agents.py` |

### Backend Internal APIs (`backend/app/api/v1/internal/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `agent_data` | module | Internal API surface for agent-specific data operations and A2A routing metadata | `backend/app/api/v1/internal/agent_data.py` |
| `get_agent_context` | endpoint | Returns runtime context including SOP content and role-derived SOP summaries for system-instruction assembly | `backend/app/api/v1/internal/agent_data.py` |
| `session_data` | module | Internal API surface for session-bound state and lifecycle transitions used by A2A flows | `backend/app/api/v1/internal/session_data.py` |

### Alembic Migrations

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `add_agent_plans` | migration | Creates `agent_plans` table with all columns, unique constraint on `agent_type_id`, and FK to `agent_types` with CASCADE delete | `backend/alembic/versions/fcbe5b250e08_add_agent_plans.py` |

### Frontend Pages (`frontend/src/pages/agents/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentRoleListPage` | component | Table view; Name, SOP count chip, Skill count chip, Edit/Delete actions | `frontend/src/pages/agents/AgentRoleListPage.tsx` |
| `AgentRoleDialog` | component | Create/edit; SOP checkbox list, Skill checkbox list, MCP tool preview panel (debounced, edit mode only); includes allowed target agent type slug preview derived from SOP `agent_delegation` policy mappings; assigned identities and MCP sessions with Assign/Remove | `frontend/src/pages/agents/AgentRoleDialog.tsx` |
| `AssignIdentitiesToRoleDialog` | component | Multi-select dialog to bulk-assign identities to a role | `frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx` |
| `AssignMcpSessionsToRoleDialog` | component | Multi-select dialog to assign MCP sessions to a role; filtered by servers whose tools the role uses; Passthrough chip shown for passthrough sessions; passthrough sessions may coexist with other sessions per server (no one-session-per-server enforcement for passthrough) | `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx` |
| `AgentIdentityListPage` | component | Table view; realm_name, realm_username, token status chip, identity status chip; Refresh Token and Re-Authenticate per row | `frontend/src/pages/agents/AgentIdentityListPage.tsx` |
| `AgentIdentityDialog` | component | Create/edit; realm_name, realm_username; "Sign In as Agent" OAuth button opens agent realm popup; reflects token status after callback | `frontend/src/pages/agents/AgentIdentityDialog.tsx` |
| `AssignRolesToIdentityDialog` | component | Multi-select dialog to bulk-assign roles to an identity | `frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx` |
| `AgentOAuthCallbackPage` | component | Loaded in OAuth popup; exchanges code via backend callback; postMessages result to opener; calls `window.close()` | `frontend/src/pages/agents/AgentOAuthCallbackPage.tsx` |
| `AgentTypeForm` | component | Modified — fields: `identity_id`, `role_id`, `model_id` (string dropdown across all configs), `system_instruction`, `input_type`/`output_type` (+schemas); includes SOP/Skill binding list section with add/remove/reorder controls; binding picker filtered by role-accessible items; removed `model_config_id`, `model_name`, `llm_*`, `primary_sop_id`; validates identity is assigned to selected role; validates binding entries are role-accessible | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `AgentJobLaunchDialog` | component | Dynamic input form per `input_type`; POSTs to `/agents/sessions`; shows returned session ID | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` |
| `AgentJobPage` | component | Session metadata, status chip, 3 s polling (task agents), WebSocket chat UI (conversational agents), result panel; fetches `ExecutionLogEntry[]` inline and passes to `LogViewer`; optional `sessionId` prop for embedded dialog usage; conditionally hides back button when embedded; shows agent name + triggered-by user in session metadata grid | `frontend/src/pages/agents/AgentJobPage.tsx` |
| `SessionExecutionLogsDialog` | component | Retained but no longer opened from `AgentJobPage`; "View Execution Logs" button removed from the job page | `frontend/src/pages/agents/SessionExecutionLogsDialog.tsx` |
| `AgentManagementPage` | component | Agent types table; row click opens `AgentTypeDetailsDialog` (via `detailsDialogTypeId` state); inline instances sub-table removed; added "Role" and "Identity" columns resolved via `useAgentRoles()`/`useAgentIdentities()` name lookup maps; submits binding lists (sop_bindings, skill_bindings) with save payload; `AgentTypeDetailsDialog` invalidates `['agents','types']` query on close; Launch (▶) action per row retained; plan preview opens `PlanPreviewModal` after save | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentInstanceDashboardPage` | component | Renamed to "Agent Executions"; route `/agents/executions` (redirect from `/agents/instances`); optional `agentTypeId` prop for dialog embedding; agent type filter dropdown via `useAgentTypes()`; View button opens `AgentExecutionDetailsDialog` instead of navigating away; status, date range, and agent type filter controls; columns include Agent Type and Triggered By (populated via `agent_type_name`, `triggered_by_user_name`) | `frontend/src/pages/agents/AgentInstanceDashboardPage.tsx` |
| `ModelConfigListPage` | component | Table view; display_name, provider_type, credential status chip, Edit/Delete; workflow generation model section loads and saves `/agents/model-configs/workflow-generation` | `frontend/src/pages/agents/ModelConfigListPage.tsx` |
| `ModelConfigDialog` | component | Create/edit; provider_type select, display_name, api_base_url, api_key (masked), enabled_models chip multi-select via "List Models" | `frontend/src/pages/agents/ModelConfigDialog.tsx` |
| `ModelConfigListPage.handleSaveWorkflowModel` | function | Persists selected workflow generation model while preserving existing selection when save is invoked without change | `frontend/src/pages/agents/ModelConfigListPage.tsx` |

### Frontend Intervene Pages

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `IntervenePage` | component | Pending and history intervene request tables; agent name + triggered-by user columns; shows conversation context for conversation-scoped intervention requests; auto-opens `AgentExecutionDetailsDialog` after response submission | `frontend/src/pages/agents/IntervenePage.tsx` |
| `InterveneRequestList` | component | Existing intervention request list; may show conversation context for conversation-scoped requests | `frontend/src/components/agents/InterveneRequestList.tsx` |
| `useInterveneRequests` | hook | Existing hook for dashboard intervention polling; preserved unchanged | `frontend/src/hooks/useInterveneRequests.ts` |
| `interveneApi` | module | Existing API module; unchanged (new conversation-scoped endpoints are on conversations router) | `frontend/src/api/interveneApi.ts` |
| `InterveneResponseDialog` | component | Type-specific response dialog (approval Yes/No, choice selection, text input); follows Dialog Error Handling Standard | `frontend/src/components/agents/InterveneResponseDialog.tsx` |

### Frontend Types (`frontend/src/types/index.ts`)

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentRole` | interface | `id`, `name`, `description`, `sop_ids`, `skill_ids`; no `allowed_identity_types` | `frontend/src/types/index.ts` |
| `AgentIdentity` | interface | `id`, `name`, `identity_type`, `realm_name`, `realm_username`, `auth_provider`, `status`, `token_expires_at` | `frontend/src/types/index.ts` |
| `AgentIdentityType` | type alias | `'realm_user'` | `frontend/src/types/index.ts` |
| `AgentIdentityStatus` | type alias | `'active' \| 'suspended' \| 'deprovisioned'` | `frontend/src/types/index.ts` |
| `AgentJob` | interface | `id`, `agent_type_id`, `input_data`, `status`, `output_data`, `error_message`, `conversation_history`; includes `agent_type_name`, `triggered_by_user_name` | `frontend/src/types/index.ts` |
| `InterveneRequestStatus` | type alias | `'pending' \| 'responded' \| 'cancelled' \| 'expired'` | `frontend/src/types/index.ts` |
| `InterventionType` | type alias | `'approval' \| 'choice' \| 'text'` | `frontend/src/types/index.ts` |
| `InterveneRequest` | interface | `id`, `agent_session_id`, `agent_type_id`, `intervention_type`, `reason`, `choices?`, `status`, `created_at`, `responded_at?`; extended with `conversation_session_id` and `delegation_depth`; includes `agent_name`, `triggered_by_user_name` | `frontend/src/types/index.ts` |
| `InterveneResponse` | interface | `id`, `request_id`, `operator_user_id`, `approval_value?`, `selected_choice?`, `text_value?`, `responded_at`; includes `operator_user_name` | `frontend/src/types/index.ts` |
| `InterveneMetrics` | interface | `pending_count`, `avg_response_time_seconds`, `resolution_rate` | `frontend/src/types/index.ts` |
| `AgentJobStatus` | type alias | `'queued' \| 'running' \| 'waiting_for_human' \| 'completed' \| 'failed'` | `frontend/src/types/index.ts` |
| `AgentInputType` | type alias | `'none' \| 'typed' \| 'conversation'` | `frontend/src/types/index.ts` |
| `AgentOutputType` | type alias | `'auto' \| 'typed' \| 'markdown'` | `frontend/src/types/index.ts` |
| `AgentType` | interface | Modified — added `model_id: string`, `sop_bindings: AgentTypeSopBinding[]`, `skill_bindings: AgentTypeSkillBinding[]`, `plan?: AgentPlan \| null`; removed `model_config_id`, `model_name`, `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key` | `frontend/src/types/index.ts` |
| `AgentTypeSopBinding` | interface | `id`, `agent_type_id`, `sop_id`, `sop_name`, `order` | `frontend/src/types/index.ts` |
| `AgentTypeSkillBinding` | interface | `id`, `agent_type_id`, `skill_id`, `skill_name`, `order` | `frontend/src/types/index.ts` |
| `ModelConfig` | interface | `id`, `provider_type`, `display_name`, `api_base_url`, `has_credentials`, `enabled_models: string[]` | `frontend/src/types/index.ts` |
| `ModelProviderType` | type alias | `'openai' \| 'anthropic' \| 'litellm_proxy' \| 'azure_openai' \| 'gemini' \| 'mistral' \| 'cohere' \| 'groq' \| 'together' \| 'fireworks' \| 'perplexity' \| 'deepseek'` | `frontend/src/types/index.ts` |
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

### Test Files

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_agent_runtime_executor` | test module | Unit tests for `AgentRuntimeExecutor`; 2 passthrough tests: proxy called with `agent_jwt`, error returned when no JWT available | `backend/tests/unit/test_agent_runtime_executor.py` |
| `test_permission_manager` | test module | Unit tests for permission resolution and allow/deny behavior, including A2A delegation permission checks | `backend/tests/unit/test_permission_manager.py` |
| `AssignMcpSessionsToRoleDialog.test` | test module | Component tests for `AssignMcpSessionsToRoleDialog`; 2 passthrough tests: Passthrough chip shown for passthrough session, chip absent for regular sessions | `frontend/src/__tests__/AssignMcpSessionsToRoleDialog.test.tsx` |

### Frontend Components (`frontend/src/components/agents/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTypeDetailsDialog` | component | Three-tab dialog (Details, Plan Preview, Execution Logs) for an agent type; fetches via `useAgentType(id)`; Details tab has clickable role/identity names opening `AgentRoleViewDialog`/`AgentIdentityViewDialog`; Execution Logs tab shows last 10 sessions with "View" opening `AgentExecutionDetailsDialog`; "Run Agent" opens `AgentJobLaunchDialog`; follows Dialog Error Handling Standard | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `AgentExecutionsDialog` | component | Dialog wrapper for `AgentInstanceDashboardPage`; allows viewing the full execution list in dialog context without navigating away; pre-filtered by `agentTypeId` | `frontend/src/components/agents/AgentExecutionsDialog.tsx` |
| `AgentExecutionDetailsDialog` | component | Dialog wrapper for `AgentJobPage`; shows full session details and logs in dialog context; three dynamic conditional tabs — Execution (0), Result (1), Conversation History (2); each tab only appears when corresponding data exists; tab bar hidden if only one tab qualifies; fetches conversation history on open; auto-opens after intervene response submission | `frontend/src/components/agents/AgentExecutionDetailsDialog.tsx` |
| `AgentPlanContent` | component | Presentational component for plan steps and topology diagram; includes `agent_delegation` step rendering in ordered plan previews; extracted from `PlanPreviewModal`; receives `plan: AgentPlan \| null \| undefined`; reused by both `PlanPreviewModal` and the Plan Preview tab of `AgentTypeDetailsDialog` | `frontend/src/components/agents/AgentPlanContent.tsx` |
| `AgentRoleViewDialog` | component | Read-only view dialog for a single agent role; two-column detail grid; Edit and Close actions; opened from clickable role name in `AgentTypeDetailsDialog` Details tab | `frontend/src/components/agents/AgentRoleViewDialog.tsx` |
| `AgentIdentityViewDialog` | component | Read-only view dialog for a single agent identity; two-column detail grid; Edit and Close actions; opened from clickable identity name in `AgentTypeDetailsDialog` Details tab | `frontend/src/components/agents/AgentIdentityViewDialog.tsx` |
| `PlanPreviewModal` | component | MUI Dialog displaying plan steps as an ordered list with step-type chips and topology diagram after agent type save; shows error state when `generation_status = failed`; follows Dialog Error Handling Standard; plan content rendered via `AgentPlanContent` | `frontend/src/components/agents/PlanPreviewModal.tsx` |
| `TopologyDiagramRenderer` | component | Renders node-edge topology payload as a visual diagram; includes delegation nodes/edges for A2A plan preview; distinguishes node types (role, sop, skill, tool) by colour/icon; handles empty state | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |

### Frontend Components (`frontend/src/components/executions/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `LogViewer` | component | Root log display component; owns `rawMode` boolean state; calls `presentLog()` once per render cycle; conditionally renders `LogSummaryPanel` + `WorkingStepsPanel` or a monospace raw log block; renders `RawLogToggle` in the header | `frontend/src/components/executions/LogViewer.tsx` |
| `LogSummaryPanel` | component | Execution Summary card: identity, role, model, SOPs/skills as MUI Chip elements, plan progress, result status badge; receives `LogSummary` prop; no data fetching or transformation | `frontend/src/components/executions/LogSummaryPanel.tsx` |
| `WorkingStepsPanel` | component | Execution Details card: flat top-level steps as log rows; all LLM iterations and tool calls in a single MUI `Collapse` section collapsed by default; each step may contain an expandable detail block for plan text or tool input/output; receives `WorkingStep[]` prop | `frontend/src/components/executions/WorkingStepsPanel.tsx` |
| `RawLogToggle` | component | "Friendly / Raw Output" labelled toggle switch and copy-to-clipboard button (visible in raw mode only); receives `checked`, `onChange`, and `rawLogText` props; no internal state | `frontend/src/components/executions/RawLogToggle.tsx` |

### Frontend Services (`frontend/src/services/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `presentLog` | function | Pure synchronous transformation: `presentLog(executionLog, entries): StructuredLog`; parses `system_instruction` for identity, role, model, SOPs/skills; maps entries to `WorkingStep[]` with `iconType` derived from `event_type`; derives result status from last entry; serialises entries to timestamped raw log string; no network calls | `frontend/src/services/LogPresenter.ts` |

### Frontend Hooks (`frontend/src/hooks/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useExecutionLogs` | hook | Fetches `ExecutionLogRead[]` from `GET /agents/sessions/{id}/execution-logs`; used by `AgentJobPage` to supply system instruction and user prompt to `LogViewer` | `frontend/src/hooks/useExecutionLogs.ts` |
| `useSessionExecutionLogStream` | hook | Consumes `GET /agents/sessions/{id}/logs/stream` live updates with reconnect and pull-backfill fallback for non-conversation execution logs | `frontend/src/hooks/useSessionExecutionLogStream.ts` |

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
| `agents.intervene.*` | translation namespace | All intervene UI strings: request list, response dialog (approval/choice/text), history, metrics | `frontend/src/i18n/locales/en.json` |
| `triggeredBy` | i18n key | "Triggered by" label in execution listings | `frontend/src/i18n/locales/en.json` |
| `noHistory` | i18n key | "No history" empty state for conversation history | `frontend/src/i18n/locales/en.json` |
| `loading` | i18n key | "Loading" generic loading state | `frontend/src/i18n/locales/en.json` |
| `noData` | i18n key | "No data" generic empty state | `frontend/src/i18n/locales/en.json` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_topology_builder_service` | unit test | Happy path, empty graph, node ID stability, duplicate tool deduplication | `backend/tests/unit/services/test_topology_builder_service.py` |
| `test_plan_generation_service` | unit test | Happy path, error path (non-blocking), hash stability, no-role case, LLM timeout handling | `backend/tests/unit/services/test_plan_generation_service.py` |
| `test_agent_types_plan` | integration test | Schema verification, unique constraint, CASCADE delete, save-response shape, upsert behaviour, failed generation path | `backend/tests/integration/api/test_agent_types_plan.py` |
| `ModelConfigListPage.workflow-generation` | frontend component test | Verifies workflow generation model section load and save behavior on model config page | `frontend/src/__tests__/ModelConfigListPage.workflow-generation.test.tsx` |
| `PlanPreviewModal.test` | frontend component test | Renders plan steps, error state, close callback, hidden when closed, Dialog Error Handling Standard | `frontend/src/__tests__/PlanPreviewModal.test.tsx` |
| `AgentTypeDetailsDialog.test` | frontend component test | Loading state, all three tabs, clickable role/identity name behaviour, error handling, tab reset on open | `frontend/src/__tests__/AgentTypeDetailsDialog.test.tsx` |
| `AgentRoleViewDialog.test` | frontend component test | Renders role detail grid, edit and close actions, loading and error states | `frontend/src/__tests__/AgentRoleViewDialog.test.tsx` |
| `AgentIdentityViewDialog.test` | frontend component test | Renders identity detail grid, edit and close actions, loading and error states | `frontend/src/__tests__/AgentIdentityViewDialog.test.tsx` |
| `AgentManagementPage.test` | frontend component test | Row-click opens dialog, Role/Identity column rendering, plan preview launch; mock updated for `useAgentType` and `defaultAgentTypeFormValues` | `frontend/src/__tests__/AgentManagementPage.test.tsx` |
| `agent-navigation.spec.ts` | E2E test | Nav group expand/collapse, agent executions page, agent type filter dropdown, dialog open/close flows | `e2e/tests/agent-navigation.spec.ts` |
| `test_agent_type_bindings_api` | backend integration test | 16 tests: binding CRUD via API, role-access validation (rejects invalid refs, duplicates), cascade delete on agent type, UUID→name resolution | `backend/tests/api/test_agent_type_bindings_api.py` |
| `AgentTypeForm.test` | frontend component test | 32 tests: binding list renders, add/remove/reorder bindings, role-filtered picker, validation states, save payload includes bindings | `frontend/src/__tests__/AgentTypeForm.test.tsx` |
| `agent-type-bindings-mocked.spec` | E2E test | 8 mocked E2E tests: binding section renders, add binding dialog, remove/reorder, save payload capture | `e2e/tests/agent-type-bindings-mocked.spec.ts` |
| `agent-type-bindings.spec` | E2E test | 1 real-backend integration test: POST returns binding fields; skips gracefully when backend unavailable | `e2e/tests/agent-type-bindings.spec.ts` |
| `test_intervene_service` | test suite | Backend unit tests for `InterveneRequestStore`: CRUD, status transitions, duplicate prevention, metrics aggregation, expiry logic | `backend/tests/services/test_intervene_service.py` |
| `test_intervene_api` | test suite | Backend integration tests for intervene endpoints: request lifecycle, state machine, authorization, constraint validation | `backend/tests/api/v1/test_intervene.py` |

## Runtime Control & Model Guardrail Hierarchy

The following components and services support the **vendor → model → guardrail hierarchy** for model-usage guardrails and the **Runtime Control Dashboard** for live execution visibility and operator-controlled termination. Operator-initiated termination is a distinct `terminated` state, separate from `failed` (genuine agent or runtime error). The dashboard merges three node kinds — `agent` (live `AgentJob`), `conversation` (`ConversationSession` with synthetic active/sleep status), and `instance` (`AgentInstance`) — and supports a tickable filter legend.

### Frontend Components (`frontend/src/components/agents/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RuntimeControlDashboardPage` | page | Dedicated runtime control dashboard at `/agents/runtime-control`; hosts the live SVG topology, selected-node details, the new Model Guardrails view (vendor → model → guardrail hierarchy), and the terminate entry point. Owns the `Set<string>` filter state and `SleepConversationActions` sub-component | `frontend/src/pages/agents/RuntimeControlDashboardPage.tsx` |
| `RuntimeTopologyDiagram` | component | SVG-based live delegation topology with rounded-rect nodes, status fills, click-to-select, tickable filter legend (12 entries: 5 agent + 4 conversation + 3 instance), single-row-per-depth layout, and horizontal scrollbar via `overflowX:'auto'` wrapping Box | `frontend/src/components/agents/RuntimeTopologyDiagram.tsx` |
| `RuntimeTopologyPanel` | component | Legacy flat-card grouped-by-depth runtime execution-tree view with selected-node details and terminate entry point (retained for compatibility) | `frontend/src/components/agents/RuntimeTopologyPanel.tsx` |
| `NodeTerminationDialog` | component | Terminate modal with permission/API denial feedback and cascade scope selection | `frontend/src/components/agents/NodeTerminationDialog.tsx` |
| `VendorModelGuardrailPanel` | component | Hierarchy-aware panel: vendor rows (with vendor enable/disable toggle and enabled-model count) → model rows (with per-model enable/disable toggle, cascade source indicator) → guardrail rows (with period, limit, unit, posture state, per-guardrail enable/edit/remove) | `frontend/src/components/agents/VendorModelGuardrailPanel.tsx` |
| `AddGuardrailForm` | component | Inline (non-modal) form inside an expanded model row; period select filtered to periods not yet configured on the model; single per-period create dispatch | `frontend/src/components/agents/AddGuardrailForm.tsx` |

### Frontend Hooks (`frontend/src/hooks/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `useRuntimeTopology` | hook | Server-state hook for active runtime topology and polling refresh | `frontend/src/hooks/useRuntimeTopology.ts` |
| `useNodeTermination` | hook | Mutation/query hooks for terminate requests and cascade outcome polling | `frontend/src/hooks/useNodeTermination.ts` |
| `useModelUsagePosture` | hook | Server-state hook for model-usage posture data and refresh | `frontend/src/hooks/useModelUsagePosture.ts` |
| `useModelUsageLimits` | hook | Server-state hook for per-guardrail configurations and refresh | `frontend/src/hooks/useModelUsagePosture.ts` |
| `useAvailableModels` | hook | Flattens `ModelConfig.enabled_models` into `AvailableModel[]` for guardrail configuration surfaces | `frontend/src/hooks/useAvailableModels.ts` |
| `useCreateModelUsageLimit` | hook | Mutation hook to create a per-period guardrail row using the per-guardrail shape | `frontend/src/hooks/useModelUsageGuardrailMutations.ts` |
| `useUpdateModelUsageLimit` | hook | Mutation hook to update a per-period guardrail row using the per-guardrail shape | `frontend/src/hooks/useModelUsageGuardrailMutations.ts` |
| `useDeleteModelUsageLimit` | hook | Mutation hook to delete a per-period guardrail row | `frontend/src/hooks/useModelUsageGuardrailMutations.ts` |
| `useModelAvailability` | hook | Server-state hook for the full vendor → model → enabled state and refresh | `frontend/src/hooks/useModelAvailability.ts` |
| `useToggleVendorDisabled` | hook | Mutation hook for the vendor-level `is_disabled` toggle | `frontend/src/hooks/useModelAvailabilityMutations.ts` |
| `useToggleModelDisabled` | hook | Mutation hook for the per-model availability toggle | `frontend/src/hooks/useModelAvailabilityMutations.ts` |
| `usePreflightAvailability` | hook | Mutation hook Agent Runtime (or server-to-server test harness) uses for the pre-execution availability check | `frontend/src/hooks/usePreflightAvailability.ts` |
| `useEndConversationSession` | hook | Mutation hook to end a sleep conversation session | `frontend/src/hooks/useConversationSessions.ts` |

### Frontend Types (`frontend/src/types/index.ts`)

| Symbol | Type | Description |
|--------|------|-------------|
| `AgentJobStatus` | enum | Extended with `terminated` (distinct from `failed`) |
| `RuntimeTopologyNode` | interface | Topology node: `kind: 'agent' \| 'conversation' \| 'instance'`, `status: string`, `title?: string`, plus delegation metadata |
| `RuntimeTopologyEdge` | interface | Topology edge: `source: string`, `target: string` |
| `RuntimeTopologyRead` | interface | Topology response: `nodes: RuntimeTopologyNode[]`, `edges: RuntimeTopologyEdge[]` |
| `LogSummary` | interface | Extended with `terminated` outcome distinct from `failed` (renders amber `BlockIcon` Chip) |
| `AvailableModel` | interface | `model_id`, `model_name`, `vendor` |
| `ModelAvailability` | interface | `model_id`, `model_name`, `is_disabled`, `disabled_reason?: 'manual' \| 'vendor_cascaded'` |
| `ModelUsagePosture` | interface | `posture_state: 'within_limit' \| 'approaching_limit' \| 'breached'`, `current_units`, `period` |

### Frontend i18n (`frontend/src/i18n/locales/en.json`)

| Symbol | Kind | Description |
|--------|------|-------------|
| `runtime.runtimeControlTitle` | i18n key | Title for the runtime control dashboard page |
| `runtime.statusActive` | i18n key | "Active" runtime status label |
| `runtime.statusSleep` | i18n key | "Sleep" runtime status label (synthetic, no live agent job) |
| `runtime.statusClosed` | i18n key | "Closed" runtime status label |
| `runtime.statusArchived` | i18n key | "Archived" runtime status label |
| `runtime.statusError` | i18n key | "Error" runtime status label |
| `runtime.runtimeEndSession` | i18n key | "End session" button label (sleep conversations) |
| `runtime.runtimeTopologyConversationLabel` | i18n key | Prefix label for conversation nodes in topology |
| `runtime.runtimeTopologyFilteredEmpty` | i18n key | Empty state message when all nodes are filtered out |
| `agents.statusCreated` | i18n key | "Created" instance status label |
| `agents.statusTerminated` | i18n key | "Terminated" agent job status label (2 places: dialog badge, page warning) |

### Backend Services (`backend/app/services/control_center/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `RuntimeTopologyController` | service | Active runtime topology projection; merges `AgentJob` (live), `ConversationSession` (synthetic active/sleep), and `AgentInstance` (created/active/closed/error) sources | `backend/app/services/control_center/runtime_topology_controller.py` |
| `TerminationOrchestrator` | service | Permission-gated node terminate and cascade orchestration; routes terminate requests from CC through CH to AR; records `TerminationRequest` and `TerminationCascadeOutcome` rows | `backend/app/services/control_center/termination_orchestrator.py` |
| `RecursionValidationService` | service | Recursion/dead-loop risk validation at create, update, and run entry points; persists `SopRecursionValidationCheck` and `SopRecursionValidationFinding` | `backend/app/services/control_center/recursion_validation_service.py` |
| `ModelAvailabilityService` | service | Vendor and per-model enabled state; exposes the pre-execution availability check; materialises the vendor-cascade transaction | `backend/app/services/control_center/model_availability_service.py` |
| `ModelUsageGuardrailService` | service | Per-guardrail CRUD and period-rollup aggregation; defaults to `terminate` posture and `k` unit | `backend/app/services/control_center/model_usage_guardrail_service.py` |
| `AgentRuntimeClient` | class | Outbound client from Control Center to Communication Hub for agent execute and terminate forwarding | `backend/app/services/control_center/agent_runtime_client.py` |

### Backend Communication Hub (`backend/app/communication_hub/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `agent_terminate_internal` | endpoint | CH-internal terminate forwarder; calls AR's `/internal/agent/terminate/{session_id}` with 30s read timeout and 3-attempt retry (delays 0s, 2s, 4s) | `backend/app/communication_hub/api/internal/agent_terminate.py` |
| `ControlPlaneMiddleware` | middleware | Mounts internal AR paths including terminate prefix; mirrors the shape of the execute path | `backend/app/communication_hub/middleware/control_plane.py` |
| `_AGENT_TERMINATE_PATH_PREFIX` | constant | Path prefix registered for terminate forwarding | `backend/app/communication_hub/middleware/control_plane.py` |

### Backend Agent Runtime (`backend/app/agent_runtime/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `terminate_agent_session` | endpoint | AR-internal terminate endpoint; cancels in-flight task via task registry; walks delegation graph to cascade children; updates `AgentJob.status` to `terminated` | `backend/app/agent_runtime/api/terminate.py` |
| `ControlCenterCertificateMiddleware` | middleware | Accepts only `service:communication-hub` service certificates on `/internal/agent/*` paths (including terminate); `_EXPECTED_SERVICE_NAME = "communication-hub"` | `backend/app/agent_runtime/middleware.py` |
| `AgentRuntimeExecutor._preflight_availability` | method | Pre-execution availability check; calls Control Center preflight endpoint for the resolved model; on deny, produces a policy-block outcome with `termination_category` of `model_disabled` or `vendor_disabled` | `backend/app/services/agents/runtime_executor.py` |
| `add_done_callback` (session task registry) | mechanism | Cleans up session entries in the in-flight task registry on completion | `backend/app/agent_runtime/session_task_registry.py` |

### Backend Database Models (`backend/app/db/models/`)

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ModelGuardrailConfiguration` | model | Per-period model usage limit; one row per `(model_id, model_name, period)`; `period`, `limit_value`, `unit`, `enforcement_posture`, `is_active` | `backend/app/db/models/model_guardrail_configuration.py` |
| `ModelUsagePosture` | model | Dashboard-facing model usage posture snapshot per configured period; `posture_state: within_limit \| approaching_limit \| breached` | `backend/app/db/models/model_usage_posture.py` |
| `ModelAvailability` | model | Per-model enabled state; `is_disabled`, `disabled_reason: manual \| vendor_cascaded`; unique on `(vendor_model_config_id, model_name)` | `backend/app/db/models/model_availability.py` |
| `ModelGuardrailEvaluation` | model | Per-run model guardrail policy evaluation outcomes | `backend/app/db/models/model_guardrail_evaluation.py` |
| `GuardrailThresholdEvent` | model | Observe-only threshold alerts; `event_category: model_disabled \| vendor_disabled \| guardrail_breached` | `backend/app/db/models/guardrail_threshold_event.py` |
| `AgentRunRelationship` | model | Parent-child runtime relationship for active topology mapping | `backend/app/db/models/agent_run_relationship.py` |
| `TerminationRequest` | model | Termination request record with permission outcome and request lifecycle | `backend/app/db/models/termination_request.py` |
| `TerminationCascadeOutcome` | model | Per-node cascade result for terminate orchestration | `backend/app/db/models/termination_cascade_outcome.py` |
| `SopRecursionValidationCheck` | model | Validation-check audit model for create/update/run contexts | `backend/app/db/models/sop_recursion_validation_check.py` |
| `SopRecursionValidationFinding` | model | Detailed recursion-risk finding model linked to validation checks | `backend/app/db/models/sop_recursion_validation_finding.py` |
| `AgentInstance` | model | Agent instance dashboard record; `instance_id`, `status: created \| active \| closed \| error` | `backend/app/db/models/agent_instance.py` |
| `AgentJobStatus.terminated` | enum value | New `terminated` value added to `agent_job_status_enum`; distinct from `failed` | `backend/app/db/models/agents.py` |
| `ExecutionEventCategory.guardrail_breached` | enum value | New `guardrail_breached` event category | `backend/app/db/models/session_logs.py` |
| `ExecutionEventCategory.model_disabled` | enum value | New `model_disabled` event category for vendor-cascaded or manual model blocks | `backend/app/db/models/session_logs.py` |
| `ExecutionEventCategory.vendor_disabled` | enum value | New `vendor_disabled` event category for vendor-level blocks | `backend/app/db/models/session_logs.py` |
| `AgentInstanceStatus` | enum | `created` / `active` / `closed` / `error` for the agent instance dashboard | `backend/app/db/models/agent_instance.py` |
| `ModelGuardrailPeriod` | enum | `hour` / `day` / `week` / `month` for per-period guardrail rows | `backend/app/db/models/model_guardrail_configuration.py` |
| `ModelGuardrailEnforcementPosture` | enum | `terminate` (default) / `observe_only` for per-guardrail posture | `backend/app/db/models/model_guardrail_configuration.py` |
| `ModelUsageUnit` | enum | `k` (thousand tokens, default) / `tokens` (raw tokens) for per-period limit value | `backend/app/db/models/model_guardrail_configuration.py` |
| `ModelAvailabilityDisabledReason` | enum | `manual` (operator-driven) / `vendor_cascaded` (vendor `is_disabled` cascade) | `backend/app/db/models/model_availability.py` |

### Backend API Endpoints (`backend/app/api/v1/agents.py`)

| Symbol | Type | Description |
|--------|------|-------------|
| `get_runtime_topology` | endpoint | Returns active runtime topology projection (nodes, edges, depth, statuses) for the dashboard |
| `request_runtime_termination` | endpoint | Performs permission-gated terminate requests with explicit denial reasons |
| `get_runtime_termination_outcomes` | endpoint | Returns per-node cascade outcomes for a termination request |
| `list_runtime_policy_events` | endpoint | Returns structured policy/guardrail/termination log events for runtime correlation |
| `get_model_usage_posture` | endpoint | Returns current posture rollups (within_limit, approaching_limit, breached) for configured per-period guardrails |
| `list_model_usage_limits` | endpoint | Lists configured per-guardrail rows (one period per item); per-guardrail shape |
| `create_model_usage_limit` | endpoint | Creates a single per-period guardrail row; returns 409 on `(model_id, model_name, period)` conflict |
| `get_model_usage_limit` | endpoint | Fetches a single per-period guardrail configuration |
| `update_model_usage_limit` | endpoint | Updates a single per-period guardrail row using the per-guardrail shape |
| `delete_model_usage_limit` | endpoint | Deletes a single per-period guardrail configuration |
| `set_vendor_disabled` | endpoint | Toggles vendor-level `is_disabled` on `ModelConfig` and triggers the cascade transaction |
| `set_model_availability` | endpoint | Toggles a single `(vendor, model_name)` `ModelAvailability` row; sets `disabled_reason = manual` |
| `list_model_availability` | endpoint | Returns the full vendor → model → enabled state for the dashboard hierarchy, including the cascade source indicator |
| `preflight_availability` | endpoint | Agent Runtime pre-execution availability check; accepts `model_id` + `model_name`, returns `{ allowed, reason?, disabled_reason? }` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_agent_runtime_controls_api` | test | Backend API tests for recursion validation 422 on create/update and instance termination 204/404 | `backend/tests/api/v1/test_agent_runtime_controls_api.py` |
| `test_model_usage_guardrails_api` | test | Backend API tests for per-guardrail CRUD endpoints and posture refresh query; per-period shape, `unit` round-trip, `(model_id, model_name, period)` conflict 409 | `backend/tests/api/v1/test_model_usage_guardrails_api.py` |
| `test_model_availability_api` | test | Backend API tests for the four new availability endpoints (vendor toggle, per-model toggle, list, preflight); cascade semantics and deny paths | `backend/tests/api/v1/test_model_availability_api.py` |
| `test_runtime_topology_controller` | test | 19 unit tests for topology controller: 14 conversation + 5 instance scenarios | `backend/tests/unit/services/test_runtime_topology_controller.py` |
| `test_termination_orchestrator` | test | 3 orchestrator tests updated for `terminated` handling | `backend/tests/services/test_termination_orchestrator.py` |
| `test_agent_runtime_client_terminate` | test | 4 CH-routed terminate tests | `backend/tests/services/test_agent_runtime_client_terminate.py` |
| `test_session_status_update_guards` | test | 2 new `terminated` late-update guard tests | `backend/tests/api/v1/internal/test_session_status_update_guards.py` |
| `test_model_availability_service` | test | 5 unit tests for guardrail breach enforcement | `backend/tests/services/test_model_availability_service.py` |
| `RuntimeControlDashboardPage.test` | frontend test | 4 tests for the dedicated `/agents/runtime-control` page — route registration, live SVG topology rendering, rect/line counts, sleep conversation gets "End session" instead of "Terminate" | `frontend/src/__tests__/RuntimeControlDashboardPage.test.tsx` |
| `RuntimeTopologyPanel.test` | frontend test | 2 tests for topology grouping/selection and permission-gated terminate control state | `frontend/src/__tests__/RuntimeTopologyPanel.test.tsx` |
| `LogPresenter.test` | frontend test | 116 tests verifying `terminated` mapping to a distinct `terminated` outcome (not `failed`) | `frontend/src/__tests__/LogPresenter.test.ts` |
| `LogSummaryPanel.test` | frontend test | 17 tests verifying amber `BlockIcon` Chip for `terminated` distinct from red `ErrorIcon` for `failed` | `frontend/src/__tests__/LogSummaryPanel.test.tsx` |
| `runtime-control-dashboard.spec` | E2E test | Observe-only policy visibility, topology/terminate flow, recursion contract, real-backend runtime-control checks, vendor/model availability hierarchy | `e2e/tests/runtime-control-dashboard.spec.ts` |
