# Tech Spec: Agent Runtime with Gateway

## 1. Technical Overview

This change rearchitects agent management from a flat, mode-driven model to a role-governed, asynchronous execution model. The key shifts are:

- **Permission model**: from per-AgentType SOP/Skill assignments to a shared `AgentRole` entity with inherited MCP tool resolution via the new `AgentPermissionManager` service.
- **Identity model**: from an `identity_subject` string on `AgentType` to a first-class `AgentIdentity` entity registered in the OIDC provider.
- **Execution model**: from synchronous instance-based execution to an asynchronous session queue (`AgentSession`) dispatched by a background `SessionDispatcher` and executed by `AgentRuntimeExecutor` using the **LangChain deep agent** framework's observe-reason-act loop.
- **Gateway**: the Communication Hub is extended to accept agent launch requests and route results, removing the separate synchronous lifecycle path.
- **Agent Framework**: Agents are implemented using the **LangChain deep agent** framework, which provides an observe-reason-act loop for skill-based execution, flexible tool binding, and built-in support for both task and conversational agent patterns. Execution logs capture the full system instruction and user prompt before the first LLM call for complete traceability.

No changes to the OIDC provider integration protocol, MCP Hub tool registration, or Skill/SOP data structures are required. All new backend code follows FastAPI + SQLAlchemy 2 async patterns. All new frontend code uses React 19 + TypeScript + MUI 7 with i18n for every UI string.

**Dependency change**: `langgraph` is removed from `pyproject.toml`; replaced by `langchain` and `langchain-community`.

---

## 2. Component Breakdown

### Backend Services

| Component | File | Responsibility |
|-----------|------|----------------|
| `AgentRoleService` | `backend/app/services/agents/role_service.py` | CRUD for AgentRole; assign/remove identities to/from roles; assign/remove MCP sessions to/from roles (enforces one session per server constraint); query available MCP sessions filtered by role's tool usage; referential integrity enforcement |
| `AgentIdentityService` | `backend/app/services/agents/identity_service.py` | CRUD for AgentIdentity; OAuth flow; token refresh and re-authentication; assign/remove roles to/from identities |
| `AgentSessionService` | `backend/app/services/agents/session_service.py` | Enqueue sessions, manage state transitions (`queued → running → completed / failed`), persist results; for conversational agents, track message history |
| `AgentPermissionManager` | `backend/app/services/agents/permission_manager.py` | Resolve `AgentRole → SOPs → Skills → MCP tools` using unified `mcp_slug/tool_name` format; LRU cache keyed on `role_id`; invalidated on role writes |
| `AgentRuntimeExecutor` | `backend/app/services/agents/runtime_executor.py` | Orchestrate agent execution using the **LangChain deep agent** observe-reason-act loop; capture `ExecutionLogEntry` with full system instruction and user prompt before first LLM call; enforce permission boundary per tool call; support both task-based and conversational agents; persist result via `save_result`; validates agent identity is assigned to agent role via agent_role_identities join table; **loads MCP session context** from role's assigned sessions and injects into system instruction with pre-configured parameters (project IDs, regions, credentials) |
| `SessionDispatcher` | `backend/app/services/agents/session_dispatcher.py` | Background worker; polls `queued` sessions; dispatches to `AgentRuntimeExecutor`; manages concurrency |
| `LifecycleHandler` (extended) | `backend/app/services/gateway/lifecycle_handler.py` | Modified — routes launch requests through `AgentSessionService.enqueue`; `validate_agent_identity_token()` checks token presence, expiry, and identity type vs role `allowed_identity_types`; `get_role_tools_for_agent()` returns tool stubs without descriptions/schemas for role-based exposure; raises `AgentAuthError` on validation failure |
| `AgentInstanceManager` (modified) | `backend/app/services/agents/instance_manager.py` | Retained for session handle management; no longer handles execution logic |
| `RealmManager` | `backend/app/services/identity/realm_manager.py` | Initializes and configures the agent realm in the OIDC provider at bootstrap; mirrors user realm setup for the configured `agent_realm_name`; creates realm-level token policies and registers the platform OAuth client for the authorization code flow |
| `TokenRefreshService` | `backend/app/services/agents/token_refresh_service.py` | Background service that proactively refreshes stored agent OAuth access tokens before expiry using the stored refresh token; updates `AgentIdentity` with a re-encrypted token pair |
| `ModelConfigService` | `backend/app/services/agents/model_config_service.py` | CRUD for `ModelConfig`; stores provider API credentials AES-256 encrypted; `fetch_available_models(config_id)` returns the `enabled_models` list if non-empty, otherwise queries available model names live from the configured provider (direct LLM API or LiteLLM proxy) |

### Frontend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `AgentRoleListPage` | `frontend/src/pages/agents/AgentRoleListPage.tsx` | Table view of all agent roles; launch create dialog |
| `AgentRoleDialog` | `frontend/src/pages/agents/AgentRoleDialog.tsx` | Create/edit form with SOP multi-select, Skill multi-select, real-time MCP tool preview panel; REMOVE allowed_identity_types field; ADD assigned identities data table with Assign/Remove actions; ADD assigned MCP sessions section with Assign/Remove actions; responsive dialog with maxWidth="lg" for wider screens |
| `AssignIdentitiesToRoleDialog` | `frontend/src/pages/agents/AssignIdentitiesToRoleDialog.tsx` | Multi-select dialog to assign identities to a role; responsive design |
| `AssignMcpSessionsToRoleDialog` | `frontend/src/pages/agents/AssignMcpSessionsToRoleDialog.tsx` | Multi-select dialog to assign MCP sessions to a role; filtered by servers whose tools the role uses; enforces one session per server constraint; responsive design |
| `AgentIdentityListPage` | `frontend/src/pages/agents/AgentIdentityListPage.tsx` | Table view of all agent identities with status chips; ADD token status chips, Refresh Token and Re-Authenticate buttons per row |
| `AssignRolesToIdentityDialog` | `frontend/src/pages/agents/AssignRolesToIdentityDialog.tsx` | Multi-select dialog to assign roles to an identity |
| `AgentIdentityDialog` | `frontend/src/pages/agents/AgentIdentityDialog.tsx` | Create/edit form for `AgentIdentity`; dropdown for type and status |
| `AgentTypeForm` (modified) | `frontend/src/pages/agents/AgentTypeForm.tsx` | Updated to use `identity_id`, `role_id`, `system_instruction`, `input_type`, `output_type`; removed old fields; REMOVE role filtering by identity type; ADD validation: selected identity must be assigned to selected role |
| `AgentJobLaunchDialog` | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` | Input collection per `input_type`; submits async session; shows returned session ID |
| `AgentJobPage` | `frontend/src/pages/agents/AgentJobPage.tsx` | Status polling (3 s interval) for task-based agents; real-time chat UI for conversational agents; result rendering (structured or markdown); stops polling on terminal status |
| `AgentManagementPage` (modified) | `frontend/src/pages/agents/AgentManagementPage.tsx` | Adds "Launch" action per agent type row; links to `AgentJobPage` |
| `ModelConfigListPage` | `frontend/src/pages/agents/ModelConfigListPage.tsx` | Table view of all model configurations; launch create/edit dialog |
| `ModelConfigDialog` | `frontend/src/pages/agents/ModelConfigDialog.tsx` | Create/edit form for `ModelConfig`; provider type selector, API endpoint, credentials (masked); "List Models" action to preview available models |

---

## 3. API Changes

All endpoints require `Authorization: Bearer <JWT>` and are validated against the `RT_AGENT` resource type.

### New Endpoints

| Method | Path | Request Body | Response | Notes |
|--------|------|--------------|----------|-------|
| `GET` | `/api/v1/agents/roles` | — | `list[AgentRoleRead]` | Lists all roles with SOP/Skill ID lists |
| `POST` | `/api/v1/agents/roles` | `AgentRoleCreate` | `AgentRoleRead` (201) | Creates role and join records atomically |
| `GET` | `/api/v1/agents/roles/{id}` | — | `AgentRoleRead` | Includes SOP/Skill ID lists |
| `PUT` | `/api/v1/agents/roles/{id}` | `AgentRoleUpdate` | `AgentRoleRead` | Replaces SOP/Skill assignments; invalidates permission cache |
| `DELETE` | `/api/v1/agents/roles/{id}` | — | 204 | Fails 409 if any `AgentType` references the role |
| `GET` | `/api/v1/agents/roles/{id}/mcp-tools` | — | `list[str]` | Resolved MCP tool identifiers for the role |
| `POST` | `/api/v1/agents/roles/{role_id}/identities` | `{identity_ids: UUID[]}` | 204 | Bulk assign identities to role |
| `DELETE` | `/api/v1/agents/roles/{role_id}/identities/{identity_id}` | — | 204 | Remove identity from role |
| `GET` | `/api/v1/agents/roles/{role_id}/identities` | — | `list[AgentIdentityRead]` | List identities assigned to role |
| `POST` | `/api/v1/agents/roles/{role_id}/mcp-sessions` | `{mcp_session_id: UUID, server_id: UUID}` | 204 | Assign MCP session to role; enforces one-session-per-server constraint |
| `DELETE` | `/api/v1/agents/roles/{role_id}/mcp-sessions/{session_id}` | — | 204 | Remove MCP session from role |
| `GET` | `/api/v1/agents/roles/{role_id}/mcp-sessions` | — | `list[McpSessionRead]` | List MCP sessions assigned to role |
| `GET` | `/api/v1/agents/roles/{role_id}/available-mcp-sessions` | — | `list[McpSessionRead]` | List MCP sessions available for assignment; filtered by servers whose tools the role uses |
| `GET` | `/api/v1/agents/identities` | — | `list[AgentIdentityRead]` | Lists all agent identities |
| `POST` | `/api/v1/agents/identities` | `AgentIdentityCreate` | `AgentIdentityRead` (201) | Creates a placeholder identity record with `realm_name` and `realm_username`; no tokens at creation — tokens are obtained via the `/oauth/authorize` → `/oauth/callback` flow |
| `GET` | `/api/v1/agents/identities/{id}` | — | `AgentIdentityRead` | |
| `PUT` | `/api/v1/agents/identities/{id}` | `AgentIdentityUpdate` | `AgentIdentityRead` | |
| `DELETE` | `/api/v1/agents/identities/{id}` | — | 204 | Fails 409 if any `AgentType` references the identity |
| `POST` | `/api/v1/agents/identities/{identity_id}/roles` | `{role_ids: UUID[]}` | 204 | Bulk assign roles to identity |
| `DELETE` | `/api/v1/agents/identities/{identity_id}/roles/{role_id}` | — | 204 | Remove role from identity |
| `GET` | `/api/v1/agents/identities/{identity_id}/roles` | — | `list[AgentRoleRead]` | List roles assigned to identity |
| `POST` | `/api/v1/agents/identities/{identity_id}/refresh-token` | — | `AgentIdentityRead` | Refresh expired access token using refresh token |
| `GET` | `/api/v1/agents/identities/{identity_id}/reauth-url` | — | `{authorization_url: string}` | Get OAuth re-auth URL |
| `GET` | `/api/v1/agents/identities/oauth/authorize` | `?identity_id=<uuid>` (query param) | `{authorization_url: string}` (200) | Generates the OAuth authorization URL for signing in as the agent user in the configured agent realm; embeds `identity_id` in the OAuth `state` parameter |
| `GET` | `/api/v1/agents/oauth/callback` | `?code=...&state=...` (OIDC redirect params) | `AgentIdentityRead` (200) | Handles OIDC redirect; validates state; exchanges authorization code for tokens; stores AES-256 encrypted access and refresh tokens on the `AgentIdentity` record; sets `status = active` |
| `POST` | `/api/v1/agents/sessions` | `AgentJobCreate` | `AgentJobStatusRead` (202) | Enqueues session; returns immediately with session ID |
| `GET` | `/api/v1/agents/sessions` | — | `list[AgentJobStatusRead]` | Sessions triggered by current user; supports `?status=<queued\|running\|completed\|failed\|cancelled>` and `?since=<ISO-8601 datetime>` query params for filtering |
| `GET` | `/api/v1/agents/sessions/{id}` | — | `AgentJobStatusRead` | Current status and timing |
| `GET` | `/api/v1/agents/sessions/{id}/result` | — | `AgentJobRead` | Full output; 409 if session not yet completed |
| `GET` | `/api/v1/agents/sessions/{id}/execution-logs` | — | `list[ExecutionLogRead]` | Returns all execution log entries for the session, including `system_instruction` and `user_prompt`; 404 if session not found |
| `GET` | `/api/v1/agents/model-configs` | — | `list[ModelConfigRead]` | Lists all model configurations |
| `POST` | `/api/v1/agents/model-configs` | `ModelConfigCreate` | `ModelConfigRead` (201) | Creates model config; API credentials stored AES-256 encrypted |
| `GET` | `/api/v1/agents/model-configs/{id}` | — | `ModelConfigRead` | Credentials fields never returned in response |
| `PUT` | `/api/v1/agents/model-configs/{id}` | `ModelConfigUpdate` | `ModelConfigRead` | Partial credential update supported |
| `DELETE` | `/api/v1/agents/model-configs/{id}` | — | 204 | Fails 409 if any `AgentType` references the config |
| `GET` | `/api/v1/agents/model-configs/{id}/models` | — | `list[str]` | Returns `ModelConfig.enabled_models` if non-empty; otherwise calls `fetch_available_models(config_id)` to query live from the configured provider; used by `AgentTypeForm` to populate the `model_id` dropdown |

### Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/api/v1/agents/roles` | Request schema: REMOVED `allowed_identity_types` field (use role-identity assignment endpoints instead) |
| `PUT` | `/api/v1/agents/roles/{id}` | Request schema: REMOVED `allowed_identity_types` field (use role-identity assignment endpoints instead) |
| `POST` | `/api/v1/agents/types` | Request/response schema updated; removed `mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key`, `model_config_id`, `model_name`; added `identity_id`, `role_id`, `model_id` (string — provider-scoped model identifier resolved by `ModelBindingLayer`), `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema` |
| `PUT` | `/api/v1/agents/types/{id}` | Same schema changes as POST |
| `GET` | `/api/v1/agents/types` | Response schema updated to match new `AgentTypeRead` |

### Removed Endpoints

None. Previously existing instance management endpoints (`/agents/instances/*`) are retained for session handle tracking.

---

## 4. State Management

The frontend manages agent-domain state through page-level React state and direct API calls (no Redux or Zustand store is added for this change). The existing `authStore.ts` / `AuthContext.tsx` pattern for JWT-authenticated requests is reused via `apiClient.ts`.

### Page-level state patterns

| Page / Dialog | Key State Variables | Notes |
|---------------|--------------------|-|
| `AgentRoleListPage` | `roles: AgentRoleRead[]`, `loading: boolean`, `dialogOpen: boolean` | Refetch after create/edit/delete |
| `AgentRoleDialog` | `sopIds: UUID[]`, `skillIds: UUID[]`, `previewTools: string[]`, `previewLoading: boolean`, `dialogError: unknown` | `previewTools` fetched on every SOP/Skill selection change; `dialogError` follows Dialog Error Handling Standard |
| `AgentIdentityListPage` | `identities: AgentIdentityRead[]`, `loading: boolean` | |
| `AgentIdentityDialog` | `oauthInitiating: boolean`, `oauthUrl: string \| null`, `dialogError: unknown` | OAuth button calls `GET /agents/identities/oauth/authorize?identity_id=<id>`; on success opens the authorization URL in a popup; `dialogError` follows Dialog Error Handling Standard |
| `AgentJobLaunchDialog` | `inputData: Record<string, unknown>`, `submitting: boolean`, `dialogError: unknown` | Input form driven by `AgentType.input_schema` |
| `AgentJobPage` | `session: AgentJob \| null`, `loading: boolean`, `fetchError: unknown` | For task agents: polling stops when `status` is `completed` or `failed`; for conversational agents: opens chat interface with message history |

### Dialog Error Handling Standard

All dialogs follow the project's Dialog Error Handling Standard (defined in `docs/config.yaml`):

1. `const [dialogError, setDialogError] = useState<unknown>(null)` on dialog open state.
2. `try { setDialogError(null); await apiCall(); onClose(); } catch (err) { setDialogError(err); }` in submit handlers.
3. `PermissionDeniedAlert` rendered as the first child of `DialogContent` when `dialogError` is non-null.
4. Error cleared on dialog open and close.

Reference implementation: `frontend/src/hooks/useDialogErrorHandler.ts`.

---

## 5. Data Access Patterns

### Backend

| Operation | Pattern |
|-----------|---------|
| Role list with SOP/Skill counts | `SELECT` on `agent_roles` with `selectinload` of `sop_assignments` and `skill_assignments` relationships |
| Permission tool resolution | Join query: `agent_role_sops → sops → sop_skills → skills → skill_tools`; merged with `agent_role_skills → skills → skill_tools`; result cached in LRU by `role_id`; tool references resolved as `mcp_slug/tool_name` (not `server_slug:tool_name`) |
| Session enqueue | `INSERT INTO agent_jobs` with `status = queued`; returns immediately |
| Session dispatch | Background worker `SELECT ... WHERE status = 'queued' ORDER BY created_at LIMIT N FOR UPDATE SKIP LOCKED` to avoid double-dispatch |
| Result store | `UPDATE agent_jobs SET output_data = ..., status = 'completed', completed_at = now()` |
| Permission cache invalidation | Triggered in `AgentRoleService.update_role` and `delete_role` via `permission_manager.invalidate(role_id)` |

### Frontend

| Operation | Mechanism |
|-----------|-----------|
| Fetch roles/identities | `apiClient.get(...)` on component mount; stored in local `useState` |
| MCP tool preview | `apiClient.get('/agents/roles/{id}/mcp-tools')` debounced 300 ms after selection change |
| Launch session | `apiClient.post('/agents/sessions', body)` returns 202 + session ID |
| Poll session status | `setInterval` at 3 000 ms calling `apiClient.get('/agents/sessions/{id}')`; cleared on unmount or terminal status |

---

## 6. Identity-Role Validation Pattern

### Backend Validation
| Operation | Pattern |
|-----------|---------|
| Role assignment check | Query `agent_role_identities` for `(role_id, identity_id)` pair → raise `PermissionDeniedError` if not found |
| Cache invalidation | Invalidate permission cache when role SOP/Skill assignments change |

### Frontend Validation
| Operation | Mechanism |
|-----------|----------|
| Identity-role assignment check | `GET /api/v1/agents/identities/{id}/roles` → check if selected role is in the list → show warning if not |
| Form validation | Show `roleNotAssignedToIdentity` warning if selected identity is not assigned to selected role |

---

## 7. Code Reference Map

### Backend Models (`backend/app/db/models/agents.py`)

| Symbol | Type | Purpose |
|--------|------|---------|
| `AgentRole` | SQLAlchemy model | New — permission role entity; `allowed_identity_types` field **removed** (see `AgentRoleIdentity` join table) |
| `AgentRoleSOP` | SQLAlchemy model | New — join: role ↔ SOP |
| `AgentRoleSkill` | SQLAlchemy model | New — join: role ↔ Skill |
| `AgentRoleIdentity` | SQLAlchemy model | New — join: role ↔ identity; fields: `role_id`, `identity_id`, `assigned_at`, `assigned_by`; unique constraint on `(role_id, identity_id)`; **authoritative source for identity-role access control** |
| `AgentIdentity` | SQLAlchemy model | New — first-class OIDC identity entity; includes `realm_name`, `realm_username`, AES-256 encrypted `access_token`, encrypted `refresh_token`, and `token_expires_at` fields |
| `AgentIdentityType` | `str enum` | New — `realm_user` (agent is a user account in the dedicated agent realm, signed in via OAuth authorization code flow) |
| `AgentIdentityStatus` | `str enum` | New — `active`, `suspended`, `deprovisioned` |
| `AgentJob` | SQLAlchemy model | New — asynchronous session tracking with support for both task and conversational modes; includes `conversation_history` JSONB column for message arrays (conversational agents) (table: `agent_jobs`) |
| `AgentPromptLog` | SQLAlchemy model | New — prompt capture entry written before the first LLM call per agent session; fields: `id` (UUID), `session_id` (FK → agent_jobs, CASCADE), `system_instruction` (TEXT nullable), `user_prompt` (TEXT nullable), `logged_at` (TIMESTAMPTZ) (table: `execution_logs`) |
| `ModelConfig` | SQLAlchemy model | New — LLM provider configuration; fields: `provider_type` (`openai`, `anthropic`, `litellm_proxy`, `azure_openai`), `display_name`, `api_base_url` (optional), encrypted `api_key`, `enabled_models` (JSONB array of model ID strings; if non-empty, restricts available models to this allowlist) |
| `AgentJobStatus` | `str enum` | New — `queued`, `running`, `completed`, `failed` |
| `AgentType` | SQLAlchemy model | Modified — new fields: `identity_id`, `role_id`, `model_id` (string — provider-scoped model identifier resolved by `ModelBindingLayer`), `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema`; removed `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key`, `model_config_id` (FK removed), `model_name` |
| `AgentInputType` | `str enum` | New — `none`, `typed`, `conversation` |
| `AgentOutputType` | `str enum` | New — `auto`, `typed`, `markdown` |
| `AgentInstance` | SQLAlchemy model | Unchanged — session handle tracking |
| `AgentSkillAssignment` | SQLAlchemy model | **Removed** |
| `AgentMode` | `str enum` | **Removed** |

### Backend Schemas (`backend/app/schemas/agents.py`)

| Symbol | Type | Purpose |
|--------|------|---------|
| `AgentRoleCreate` | Pydantic model | New — `allowed_identity_types` field **removed** |
| `AgentRoleUpdate` | Pydantic model | New — `allowed_identity_types` field **removed** |
| `AgentRoleRead` | Pydantic model | New — `allowed_identity_types` field **removed**; includes `sop_ids`, `skill_ids` |
| `AgentRoleIdentityAssignment` | Pydantic model | New — `{identity_ids: UUID[]}` for bulk role→identity assignment |
| `AgentRoleAssignment` | Pydantic model | New — `{role_ids: UUID[]}` for bulk identity→role assignment |
| `AgentIdentityCreate` | Pydantic model | New — includes `realm_name`, `realm_username` |
| `AgentIdentityUpdate` | Pydantic model | New |
| `AgentIdentityRead` | Pydantic model | New — includes `token_expires_at`; never exposes raw token values |
| `AgentIdentityOAuthAuthorizeResponse` | Pydantic model | New — `{authorization_url: str}` returned by the authorize endpoint |
| `AgentJobCreate` | Pydantic model | New (API path: `/agents/sessions`, DB model: `AgentJob`) |
| `AgentJobStatusRead` | Pydantic model | New — subset fields for polling; accepted filter query params: `status`, `since` |
| `AgentJobRead` | Pydantic model | New — full fields including `output_data`, `conversation_history: list[dict]` (message array; empty list for non-conversational agents) |
| `ExecutionLogRead` | Pydantic model | New — `id`, `session_id`, `system_instruction`, `user_prompt`, `logged_at`; returned by `GET /agents/sessions/{id}/execution-logs` |
| `ModelConfigCreate` | Pydantic model | New — `provider_type`, `display_name`, `api_base_url`, `api_key`, `enabled_models: list[str]` (optional; empty list = all models allowed) |
| `ModelConfigUpdate` | Pydantic model | New — all fields optional; omitted `api_key` leaves existing credential unchanged |
| `ModelConfigRead` | Pydantic model | New — excludes credential fields; includes `id`, `provider_type`, `display_name`, `api_base_url`, `has_credentials: bool`, `enabled_models: list[str]` |
| `AgentTypeCreate` | Pydantic model | Modified — added `model_id: str`; removed `model_config_id`, `model_name`, `llm_provider`, `llm_model`, `llm_api_key` |
| `AgentTypeUpdate` | Pydantic model | Modified — same field changes as `AgentTypeCreate` |
| `AgentTypeRead` | Pydantic model | Modified — exposes `model_id: str`; no `model_config_id` FK, no raw LLM credential fields |

### Backend Services

| Symbol | File | Purpose |
|--------|------|---------|
| `AgentRoleService` | `backend/app/services/agents/role_service.py` | New — role CRUD; `assign_identities()`, `remove_identity()`, `list_identities()`, `is_identity_assigned()` |
| `AgentIdentityService` | `backend/app/services/agents/identity_service.py` | New — identity CRUD; OAuth authorize URL generation; token exchange and encrypted storage; `refresh_token()`, `get_reauth_url()`; `assign_roles()`, `remove_role()`, `list_roles()` |
| `RealmManager` | `backend/app/services/identity/realm_manager.py` | New — agent realm initialization and lifecycle management in the OIDC provider |
| `TokenRefreshService` | `backend/app/services/agents/token_refresh_service.py` | New — background proactive token refresh for all agent identities approaching expiry |
| `AgentSessionService` | `backend/app/services/agents/session_service.py` | New — session lifecycle management (`AgentJob` state machine) |
| `AgentPermissionManager` | `backend/app/services/agents/permission_manager.py` | New — permission resolution and LRU cache; tool identifiers use `McpTool.name` directly (`mcp_slug/tool_name` format) |
| `ModelConfigService` | `backend/app/services/agents/model_config_service.py` | New — CRUD for `ModelConfig`; encrypts/decrypts credentials; `fetch_available_models(config_id)` returns `enabled_models` if non-empty, otherwise queries live from the provider |
| `AgentRuntimeExecutor` | `backend/app/services/agents/runtime_executor.py` | New — **LangChain deep agent** observe-reason-act loop; validates identity is assigned to role via `agent_role_identities` table before execution; raises `PermissionDeniedError` if not assigned; `_load_tool_definitions()` uses `mcp_slug/tool_name` identifiers directly without prefix stripping; captures `ExecutionLogEntry` before first LLM call |
| `SessionDispatcher` | `backend/app/services/agents/session_dispatcher.py` | New — background dispatch worker (poll + `SKIP LOCKED`) |
| `TaskAgentLoop`, `ConversationalAgentLoop` | `backend/app/services/agents/agent_loop.py` | New — LangChain deep agent loop definitions; observe-reason-act context for task and conversational agents |
| `ModelBindingLayer` | `backend/app/services/agents/model_binding.py` | New — resolves `AgentType.model_id` string to a matching `ModelConfig` (scans `enabled_models` across all configs; falls back to provider-prefix matching if `enabled_models` is empty); instantiates the correct LangChain/LiteLLM client for direct provider APIs or LiteLLM proxy; sends chat completion requests |
| `AgentInstanceManager` | `backend/app/services/agents/instance_manager.py` | Modified — execution logic removed |
| `LifecycleHandler` | `backend/app/services/gateway/lifecycle_handler.py` | Modified — routes launch through session queue; `validate_agent_identity_token()` validates OAuth token; `get_role_tools_for_agent()` exposes tool stubs without descriptions/schemas; `AgentAuthError` raised on validation failure |
| `SopAgentExecutor` | `backend/app/services/agents/sop_executor.py` | **Superseded** — retained in codebase but not invoked by the new job-queue flow; execution handled by `AgentRuntimeExecutor` |
| `SkillfulAgentExecutor` | `backend/app/services/agents/skillful_executor.py` | **Superseded** — retained in codebase but not invoked by the new job-queue flow; execution handled by `AgentRuntimeExecutor` |
| `AgentGraphState`, `ConversationalAgentState` | `backend/app/services/agents/agent_state.py` | **Superseded** — old LangGraph TypedDicts; file retained but not imported; replaced by `TaskAgentLoop`/`ConversationalAgentLoop` in `agent_loop.py` |

### Backend API (`backend/app/api/v1/agents.py`)

| Symbol | Purpose |
|--------|---------|
| `AgentRoleRouter` | New — mounts all `/agents/roles` endpoints |
| `AgentIdentityRouter` | New — mounts all `/agents/identities` endpoints |
| `AgentOAuthRouter` | New — mounts `/agents/identities/oauth/authorize` and `/agents/oauth/callback` endpoints |
| `AgentJobRouter` | New — mounts all `/agents/sessions` endpoints (class named `AgentJobRouter`; path prefix `/agents/sessions`) |
| `AgentTypeRouter` | Modified — updated schema references |
| `AgentInstanceRouter` | Unchanged |
| `ModelConfigRouter` | New — mounts all `/agents/model-configs` endpoints |

### Frontend Pages (`frontend/src/pages/agents/`)

| Symbol | File | Purpose |
|--------|------|---------|
| `AgentRoleListPage` | `AgentRoleListPage.tsx` | **New** — table view; Name, SOP count chip, Skill count chip, Edit/Delete actions |
| `AgentRoleDialog` | `AgentRoleDialog.tsx` | **New** — create/edit; SOP checkbox list, Skill checkbox list, MCP tool preview (debounced, edit mode only) |
| `AgentIdentityListPage` | `AgentIdentityListPage.tsx` | **New** — table view; realm_name, realm_username, token status chip (Active/Expired), status chip |
| `AgentIdentityDialog` | `AgentIdentityDialog.tsx` | **New** — create/edit; realm_name, realm_username text fields; **"Sign In as Agent" OAuth button** that fetches the authorization URL and opens the agent realm sign-in in a popup; reflects updated token status after OAuth callback |
| `AgentOAuthCallbackPage` | `AgentOAuthCallbackPage.tsx` | **New** — loaded in the OAuth popup; exchanges code via backend callback, postMessages result to opener, then calls `window.close()` |
| `AgentJobLaunchDialog` | `AgentJobLaunchDialog.tsx` | **New** — dynamic input form per input_type (none / typed / conversation); POSTs to `/agents/sessions` |
| `AgentJobPage` | `AgentJobPage.tsx` | **New** — session metadata, status chip, 3 s polling (task agents), WebSocket chat UI (conversational agents), result panel (typed JSON or markdown); **execution log section** displays system instruction and user prompt fetched via `useExecutionLogs(sessionId)` |
| `AgentManagementPage` | `AgentManagementPage.tsx` | **Modified** — uses `AgentTypeForm`; adds Launch (▶) action per row; links to `AgentJobPage` |
| `AgentTypeForm` | `AgentTypeForm.tsx` | **Modified** — full form component; new fields: `identity_id`, `role_id`, `model_id` (string dropdown populated via `GET /model-configs/{id}/models` across all configs), `system_instruction`, `input_type` (+schema), `output_type` (+schema); removed `model_config_id`, `model_name`, `llm_provider`, `llm_model`, `llm_api_key` fields |
| `ModelConfigListPage` | `ModelConfigListPage.tsx` | **New** — table view; displays `display_name`, `provider_type`, credential status chip, Edit/Delete actions |
| `ModelConfigDialog` | `ModelConfigDialog.tsx` | **New** — create/edit form; `provider_type` select, `display_name`, `api_base_url`, `api_key` (masked input), `enabled_models` (chip multi-select populated via **"List Models"** button calling `GET /model-configs/{id}/models`; empty = all models allowed) |
| `AgentInstanceDashboardPage` | `AgentInstanceDashboardPage.tsx` | **New** — table/list of all `AgentJob` instances across all users (admin view); columns: agent type name, status chip, triggered by, started/completed times; `status` and `since` filter controls at top of page |
| `AgentJobPage` (modified) | `AgentJobPage.tsx` | **Modified** — result panel now also renders `conversation_history` as a read-only message thread for completed conversational agents; adds execution log panel displaying `system_instruction` and `user_prompt` from `ExecutionLogEntry` |

### Frontend Types (`frontend/src/types/index.ts`)

| Symbol | Kind | Purpose |
|--------|------|---------|
| `AgentRole` | interface | **New** — id, name, description, sop_ids, skill_ids (`allowed_identity_types` removed) |
| `AgentIdentity` | interface | **New** — id, name, identity_type, realm_name, realm_username, auth_provider, status, token_expires_at |
| `AgentJob` | interface | **New** — id, agent_type_id, input_data, status, output_data, error_message, conversation_history (message array) |
| `AgentIdentityType` | type alias | **New** — `'realm_user'` |
| `AgentIdentityStatus` | type alias | **New** — `'active' \| 'suspended' \| 'deprovisioned'` |
| `AgentJobStatus` | type alias | **New** — `'queued' \| 'running' \| 'completed' \| 'failed'` |
| `AgentInputType` | type alias | **New** — `'none' \| 'typed' \| 'conversation'` |
| `AgentOutputType` | type alias | **New** — `'auto' \| 'typed' \| 'markdown'` |
| `AgentType` | interface | **Modified** — added `model_id: string`; removed `model_config_id`, `model_name`, `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances`, `llm_provider`, `llm_model`, `llm_api_key` |
| `ModelConfig` | interface | **New** — id, provider_type, display_name, api_base_url, has_credentials, enabled_models: string[] |
| `ModelProviderType` | type alias | **New** — `'openai' \| 'anthropic' \| 'litellm_proxy' \| 'azure_openai'` |

### Frontend App (`frontend/src/app/`)

| Symbol | File | Change |
|--------|------|--------|
| `AppRouter` | `AppRouter.tsx` | **Modified** — added routes: `/agents/roles`, `/agents/identities`, `/agents/identities/oauth/callback`, `/agents/sessions/:id`, `/agents/model-configs`, `/agents/instances` |
| `AppShell` | `AppShell.tsx` | **Modified** — added sidebar items: Agent Roles (`AssignmentIndIcon`), Agent Identities (`BadgeIcon`), Model Configs (`TuneIcon`), Agent Instances (`MonitorHeartIcon`) |

### Frontend Hooks (`frontend/src/hooks/`)

| Symbol | File | Purpose |
|--------|------|--------|
| `useExecutionLogs` | `useExecutionLogs.ts` | **New** — fetches `ExecutionLogEntry` list for a given `session_id` via `GET /agents/sessions/{id}/execution-logs`; returns `{ logs: ExecutionLogRead[], loading: boolean, error: unknown }` |

### i18n (`frontend/src/i18n/`)

| Namespace / Key Prefix | Coverage |
|------------------------|----------|
| `agents.roles.*` | Role list/dialog: title, subtitle, create/edit, SOP/Skill counts, MCP preview, empty state, delete confirm |
| `agents.identities.*` | Identity list/dialog: title, subtitle, create/edit, identity types, statuses, OAuth sign-in button, token status, empty state, delete confirm |
| `agents.types.*` | Updated/added: role, identity, systemInstruction, inputType variants, inputSchema, outputType variants, outputSchema, launch |
| `agents.sessions.*` | Session launch dialog, status page, chat UI, instance dashboard: all labels, status values, filter controls, result, polling hint, conversation history heading, execution log section heading and field labels |
| `agents.modelConfigs.*` | Model config list/dialog: title, subtitle, create/edit, provider types, credential status, list-models button, empty state, delete confirm |
| `nav.agentRoles` | Sidebar item: "Agent Roles" |
| `nav.agentIdentities` | Sidebar item: "Agent Identities" |
| `nav.modelConfigs` | Sidebar item: "Model Configs" |
| `nav.agentInstances` | Sidebar item: "Agent Instances" |

### Tests

| File | Scope |
|------|-------|
| `backend/tests/unit/test_agent_role_service.py` | New — `AgentRoleService` CRUD |
| `backend/tests/unit/test_permission_manager.py` | New — tool resolution logic |
| `backend/tests/unit/test_agent_session_service.py` | New — state transitions and LangChain deep agent loop integration |
| `backend/tests/unit/test_execution_log.py` | New — `ExecutionLogEntry` creation and prompt capture verification |
| `backend/tests/unit/test_agent_identity_service.py` | New — referential integrity; OAuth flow token exchange |
| `backend/tests/unit/test_token_refresh_service.py` | New — token refresh logic against mocked IdP endpoint |
| `backend/tests/unit/test_realm_manager.py` | New — realm initialization against mocked Keycloak admin API |
| `backend/tests/unit/test_model_config_service.py` | New — CRUD, credential encryption/decryption, model-list proxying against mocked provider HTTP |
| `backend/tests/integration/test_agent_session_lifecycle.py` | New — end-to-end session flow against real DB with LangChain deep agent; asserts `ExecutionLogEntry` is persisted for the session |
| `frontend/src/__tests__/AgentRoleDialog.test.tsx` | New — SOP/Skill selection and preview |
| `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` | New — input_type rendering |
| `frontend/src/__tests__/AgentSessionPage.test.tsx` | New — polling for task agents, chat UI for conversational agents, conversation history render for completed sessions, result rendering, execution log section display |
| `frontend/src/__tests__/ModelConfigDialog.test.tsx` | New — provider type selection, credential masking, list-models preview |
| `frontend/src/__tests__/AgentInstanceDashboard.test.tsx` | New — status/time filter controls, table rendering |
| `e2e/tests/agent-runtime.spec.ts` | New — mocked E2E suites + real backend integration variant |
