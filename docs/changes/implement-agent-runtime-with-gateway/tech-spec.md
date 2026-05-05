# Tech Spec: Agent Runtime with Gateway

## 1. Technical Overview

This change rearchitects agent management from a flat, mode-driven model to a role-governed, asynchronous execution model. The key shifts are:

- **Permission model**: from per-AgentType SOP/Skill assignments to a shared `AgentRole` entity with inherited MCP tool resolution via the new `AgentPermissionManager` service.
- **Identity model**: from an `identity_subject` string on `AgentType` to a first-class `AgentIdentity` entity registered in the OIDC provider.
- **Execution model**: from synchronous instance-based execution to an asynchronous session queue (`AgentSession`) dispatched by a background `SessionDispatcher` and executed by `AgentRuntimeExecutor` using **LangGraph** state machine framework.
- **Gateway**: the Communication Hub is extended to accept agent launch requests and route results, removing the separate synchronous lifecycle path.
- **Agent Framework**: Agents are implemented using **LangGraph**, which provides explicit state machine definitions, deterministic execution paths, checkpointing, and built-in support for human-in-the-loop workflows.

No changes to the OIDC provider integration protocol, MCP Hub tool registration, or Skill/SOP data structures are required. All new backend code follows FastAPI + SQLAlchemy 2 async patterns. All new frontend code uses React 19 + TypeScript + MUI 7 with i18n for every UI string.

---

## 2. Component Breakdown

### Backend Services

| Component | File | Responsibility |
|-----------|------|----------------|
| `AgentRoleService` | `backend/app/services/agents/role_service.py` | CRUD for `AgentRole`, `AgentRoleSOP`, `AgentRoleSkill` in a single transaction |
| `AgentIdentityService` | `backend/app/services/agents/identity_service.py` | CRUD for `AgentIdentity`; initiates and completes OAuth authorization code flow against the agent realm; stores encrypted access and refresh tokens; referential integrity guard on delete |
| `AgentSessionService` | `backend/app/services/agents/session_service.py` | Enqueue sessions, manage state transitions (`queued → running → completed / failed`), persist results; for conversational agents, track message history |
| `AgentPermissionManager` | `backend/app/services/agents/permission_manager.py` | Resolve `AgentRole → SOPs → Skills → MCP tools`; LRU cache keyed on `role_id`; invalidated on role writes |
| `AgentRuntimeExecutor` | `backend/app/services/agents/runtime_executor.py` | Orchestrate agent execution using **LangGraph** state graphs; enforce permission boundary per tool call; support both task-based and conversational agents; persist result via `save_result` |
| `SessionDispatcher` | `backend/app/services/agents/session_dispatcher.py` | Background worker; polls `queued` sessions; dispatches to `AgentRuntimeExecutor`; manages concurrency |
| `LifecycleHandler` (extended) | `backend/app/services/gateway/lifecycle_handler.py` | Extended to route launch requests through `AgentSessionService.enqueue`; returns session ID synchronously; for conversational agents, maintains bidirectional WebSocket connection |
| `AgentInstanceManager` (modified) | `backend/app/services/agents/instance_manager.py` | Retained for session handle management; no longer handles execution logic |
| `RealmManager` | `backend/app/services/identity/realm_manager.py` | Initializes and configures the agent realm in the OIDC provider at bootstrap; mirrors user realm setup for the configured `agent_realm_name`; creates realm-level token policies and registers the platform OAuth client for the authorization code flow |
| `TokenRefreshService` | `backend/app/services/agents/token_refresh_service.py` | Background service that proactively refreshes stored agent OAuth access tokens before expiry using the stored refresh token; updates `AgentIdentity` with a re-encrypted token pair |

### Frontend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `AgentRoleListPage` | `frontend/src/pages/agents/AgentRoleListPage.tsx` | Table view of all agent roles; launch create dialog |
| `AgentRoleDialog` | `frontend/src/pages/agents/AgentRoleDialog.tsx` | Create/edit form with SOP multi-select, Skill multi-select, real-time MCP tool preview panel |
| `AgentIdentityListPage` | `frontend/src/pages/agents/AgentIdentityListPage.tsx` | Table view of all agent identities with status chips |
| `AgentIdentityDialog` | `frontend/src/pages/agents/AgentIdentityDialog.tsx` | Create/edit form for `AgentIdentity`; dropdown for type and status |
| `AgentTypeForm` (modified) | `frontend/src/pages/agents/AgentTypeForm.tsx` | Updated to use `identity_id`, `role_id`, `system_instruction`, `input_type`, `output_type`; removed old fields |
| `AgentJobLaunchDialog` | `frontend/src/pages/agents/AgentJobLaunchDialog.tsx` | Input collection per `input_type`; submits async session; shows returned session ID |
| `AgentJobPage` | `frontend/src/pages/agents/AgentJobPage.tsx` | Status polling (3 s interval) for task-based agents; real-time chat UI for conversational agents; result rendering (structured or markdown); stops polling on terminal status |
| `AgentManagementPage` (modified) | `frontend/src/pages/agents/AgentManagementPage.tsx` | Adds "Launch" action per agent type row; links to `AgentJobPage` |

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
| `GET` | `/api/v1/agents/identities` | — | `list[AgentIdentityRead]` | Lists all agent identities |
| `POST` | `/api/v1/agents/identities` | `AgentIdentityCreate` | `AgentIdentityRead` (201) | Creates a placeholder identity record with `realm_name` and `realm_username`; no tokens at creation — tokens are obtained via the `/oauth/authorize` → `/oauth/callback` flow |
| `GET` | `/api/v1/agents/identities/{id}` | — | `AgentIdentityRead` | |
| `PUT` | `/api/v1/agents/identities/{id}` | `AgentIdentityUpdate` | `AgentIdentityRead` | |
| `DELETE` | `/api/v1/agents/identities/{id}` | — | 204 | Fails 409 if any `AgentType` references the identity |
| `GET` | `/api/v1/agents/identities/oauth/authorize` | `?identity_id=<uuid>` (query param) | `{authorization_url: string}` (200) | Generates the OAuth authorization URL for signing in as the agent user in the configured agent realm; embeds `identity_id` in the OAuth `state` parameter |
| `GET` | `/api/v1/agents/oauth/callback` | `?code=...&state=...` (OIDC redirect params) | `AgentIdentityRead` (200) | Handles OIDC redirect; validates state; exchanges authorization code for tokens; stores AES-256 encrypted access and refresh tokens on the `AgentIdentity` record; sets `status = active` |
| `POST` | `/api/v1/agents/sessions` | `AgentJobCreate` | `AgentJobStatusRead` (202) | Enqueues session; returns immediately with session ID |
| `GET` | `/api/v1/agents/sessions` | — | `list[AgentJobStatusRead]` | Sessions triggered by current user |
| `GET` | `/api/v1/agents/sessions/{id}` | — | `AgentJobStatusRead` | Current status and timing |
| `GET` | `/api/v1/agents/sessions/{id}/result` | — | `AgentJobRead` | Full output; 409 if session not yet completed |

### Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/api/v1/agents/types` | Request/response schema updated; removed `mode`, `sop_id`, `skill_ids`, `identity_subject`, `system_prompt`, `max_instances`; added `identity_id`, `role_id`, `llm_provider`, `llm_model`, `llm_api_key`, `system_instruction`, `input_type`, `input_schema`, `output_type`, `output_schema` |
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
| Permission tool resolution | Join query: `agent_role_sops → sops → sop_skills → skills → skill_tools`; merged with `agent_role_skills → skills → skill_tools`; result cached in LRU by `role_id` |
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

## 6. Code Reference Map

### Backend Models (`backend/app/db/models/agents.py`)

| Symbol | Type | Purpose |
|--------|------|---------|
| `AgentRole` | SQLAlchemy model | New — permission role entity |
| `AgentRoleSOP` | SQLAlchemy model | New — join: role ↔ SOP |
| `AgentRoleSkill` | SQLAlchemy model | New — join: role ↔ Skill |
| `AgentIdentity` | SQLAlchemy model | New — first-class OIDC identity entity; includes `realm_name`, `realm_username`, AES-256 encrypted `access_token`, encrypted `refresh_token`, and `token_expires_at` fields |
| `AgentIdentityType` | `str enum` | New — `realm_user` (agent is a user account in the dedicated agent realm, signed in via OAuth authorization code flow) |
| `AgentIdentityStatus` | `str enum` | New — `active`, `suspended`, `deprovisioned` |
| `AgentJob` | SQLAlchemy model | New — asynchronous session tracking with support for both task and conversational modes (table: `agent_jobs`) |
| `AgentJobStatus` | `str enum` | New — `queued`, `running`, `completed`, `failed` |
| `AgentType` | SQLAlchemy model | Modified — new fields; removed `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances` |
| `AgentInputType` | `str enum` | New — `none`, `typed`, `conversation` |
| `AgentOutputType` | `str enum` | New — `auto`, `typed`, `markdown` |
| `AgentInstance` | SQLAlchemy model | Unchanged — session handle tracking |
| `AgentSkillAssignment` | SQLAlchemy model | **Removed** |
| `AgentMode` | `str enum` | **Removed** |

### Backend Schemas (`backend/app/schemas/agents.py`)

| Symbol | Type | Purpose |
|--------|------|---------|
| `AgentRoleCreate` | Pydantic model | New |
| `AgentRoleUpdate` | Pydantic model | New |
| `AgentRoleRead` | Pydantic model | New — includes `sop_ids`, `skill_ids` |
| `AgentIdentityCreate` | Pydantic model | New — includes `realm_name`, `realm_username` |
| `AgentIdentityUpdate` | Pydantic model | New |
| `AgentIdentityRead` | Pydantic model | New — includes `token_expires_at`; never exposes raw token values |
| `AgentIdentityOAuthAuthorizeResponse` | Pydantic model | New — `{authorization_url: str}` returned by the authorize endpoint |
| `AgentJobCreate` | Pydantic model | New (API path: `/agents/sessions`, DB model: `AgentJob`) |
| `AgentJobStatusRead` | Pydantic model | New — subset fields for polling |
| `AgentJobRead` | Pydantic model | New — full fields including `output_data` |
| `AgentTypeCreate` | Pydantic model | Modified — new fields, removed old |
| `AgentTypeUpdate` | Pydantic model | Modified |
| `AgentTypeRead` | Pydantic model | Modified |

### Backend Services

| Symbol | File | Purpose |
|--------|------|---------|
| `AgentRoleService` | `backend/app/services/agents/role_service.py` | New — role CRUD |
| `AgentIdentityService` | `backend/app/services/agents/identity_service.py` | New — identity CRUD; OAuth authorize URL generation; token exchange and encrypted storage |
| `RealmManager` | `backend/app/services/identity/realm_manager.py` | New — agent realm initialization and lifecycle management in the OIDC provider |
| `TokenRefreshService` | `backend/app/services/agents/token_refresh_service.py` | New — background proactive token refresh for all agent identities approaching expiry |
| `AgentSessionService` | `backend/app/services/agents/session_service.py` | New — session lifecycle management (`AgentJob` state machine) |
| `AgentPermissionManager` | `backend/app/services/agents/permission_manager.py` | New — permission resolution and LRU cache |
| `AgentRuntimeExecutor` | `backend/app/services/agents/runtime_executor.py` | New — LangGraph-based agent execution; unified replacement for old per-mode executors |
| `SessionDispatcher` | `backend/app/services/agents/session_dispatcher.py` | New — background dispatch worker (poll + `SKIP LOCKED`) |
| `TaskAgentState`, `ConversationalAgentState` | `backend/app/services/agents/agent_state.py` | New — LangGraph `TypedDict` state schemas |
| `ModelBindingLayer` | `backend/app/services/agents/model_binding.py` | New — resolves LLM provider config (`llm_provider`, `llm_model`, encrypted credentials) and sends chat completion requests |
| `AgentInstanceManager` | `backend/app/services/agents/instance_manager.py` | Modified — execution logic removed |
| `LifecycleHandler` | `backend/app/services/gateway/lifecycle_handler.py` | Modified — routes launch through session queue |
| `SopAgentExecutor` | `backend/app/services/agents/sop_executor.py` | **Superseded** — retained in codebase but not invoked by the new job-queue flow; execution handled by `AgentRuntimeExecutor` |
| `SkillfulAgentExecutor` | `backend/app/services/agents/skillful_executor.py` | **Superseded** — retained in codebase but not invoked by the new job-queue flow; execution handled by `AgentRuntimeExecutor` |

### Backend API (`backend/app/api/v1/agents.py`)

| Symbol | Purpose |
|--------|---------|
| `AgentRoleRouter` | New — mounts all `/agents/roles` endpoints |
| `AgentIdentityRouter` | New — mounts all `/agents/identities` endpoints |
| `AgentOAuthRouter` | New — mounts `/agents/identities/oauth/authorize` and `/agents/oauth/callback` endpoints |
| `AgentJobRouter` | New — mounts all `/agents/sessions` endpoints (class named `AgentJobRouter`; path prefix `/agents/sessions`) |
| `AgentTypeRouter` | Modified — updated schema references |
| `AgentInstanceRouter` | Unchanged |

### Frontend Pages (`frontend/src/pages/agents/`)

| Symbol | File | Purpose |
|--------|------|---------|
| `AgentRoleListPage` | `AgentRoleListPage.tsx` | **New** — table view; Name, SOP count chip, Skill count chip, Edit/Delete actions |
| `AgentRoleDialog` | `AgentRoleDialog.tsx` | **New** — create/edit; SOP checkbox list, Skill checkbox list, MCP tool preview (debounced, edit mode only) |
| `AgentIdentityListPage` | `AgentIdentityListPage.tsx` | **New** — table view; realm_name, realm_username, token status chip (Active/Expired), status chip |
| `AgentIdentityDialog` | `AgentIdentityDialog.tsx` | **New** — create/edit; realm_name, realm_username text fields; **"Sign In as Agent" OAuth button** that fetches the authorization URL and opens the agent realm sign-in in a popup; reflects updated token status after OAuth callback |
| `AgentOAuthCallbackPage` | `AgentOAuthCallbackPage.tsx` | **New** — loaded in the OAuth popup; exchanges code via backend callback, postMessages result to opener, then calls `window.close()` |
| `AgentJobLaunchDialog` | `AgentJobLaunchDialog.tsx` | **New** — dynamic input form per input_type (none / typed / conversation); POSTs to `/agents/sessions` |
| `AgentJobPage` | `AgentJobPage.tsx` | **New** — session metadata, status chip, 3 s polling (task agents), WebSocket chat UI (conversational agents), result panel (typed JSON or markdown) |
| `AgentManagementPage` | `AgentManagementPage.tsx` | **Modified** — uses `AgentTypeForm`; adds Launch (▶) action per row; links to `AgentJobPage` |
| `AgentTypeForm` | `AgentTypeForm.tsx` | **Modified** — full form component; new fields: identity_id, role_id, system_instruction, input_type (+schema), output_type (+schema); removed old fields |

### Frontend Types (`frontend/src/types/index.ts`)

| Symbol | Kind | Purpose |
|--------|------|---------|
| `AgentRole` | interface | **New** — id, name, description, sop_ids, skill_ids |
| `AgentIdentity` | interface | **New** — id, name, identity_type, realm_name, realm_username, auth_provider, status, token_expires_at |
| `AgentJob` | interface | **New** — id, agent_type_id, input_data, status, output_data, error_message |
| `AgentIdentityType` | type alias | **New** — `'realm_user'` |
| `AgentIdentityStatus` | type alias | **New** — `'active' \| 'suspended' \| 'deprovisioned'` |
| `AgentJobStatus` | type alias | **New** — `'queued' \| 'running' \| 'completed' \| 'failed'` |
| `AgentInputType` | type alias | **New** — `'none' \| 'typed' \| 'conversation'` |
| `AgentOutputType` | type alias | **New** — `'auto' \| 'typed' \| 'markdown'` |
| `AgentType` | interface | **Modified** — new fields; removed `mode`, `sop_id`, `identity_subject`, `system_prompt`, `max_instances` |

### Frontend App (`frontend/src/app/`)

| Symbol | File | Change |
|--------|------|--------|
| `AppRouter` | `AppRouter.tsx` | **Modified** — added routes: `/agents/roles`, `/agents/identities`, `/agents/identities/oauth/callback`, `/agents/sessions/:id` |
| `AppShell` | `AppShell.tsx` | **Modified** — added sidebar items: Agent Roles (`AssignmentIndIcon`), Agent Identities (`BadgeIcon`) |

### i18n (`frontend/src/i18n/`)

| Namespace / Key Prefix | Coverage |
|------------------------|----------|
| `agents.roles.*` | Role list/dialog: title, subtitle, create/edit, SOP/Skill counts, MCP preview, empty state, delete confirm |
| `agents.identities.*` | Identity list/dialog: title, subtitle, create/edit, identity types, statuses, OAuth sign-in button, token status, empty state, delete confirm |
| `agents.types.*` | Updated/added: role, identity, systemInstruction, inputType variants, inputSchema, outputType variants, outputSchema, launch |
| `agents.sessions.*` | Session launch dialog, status page, chat UI: all labels, status values, result, polling hint |
| `nav.agentRoles` | Sidebar item: "Agent Roles" |
| `nav.agentIdentities` | Sidebar item: "Agent Identities" |

### Tests

| File | Scope |
|------|-------|
| `backend/tests/unit/test_agent_role_service.py` | New — `AgentRoleService` CRUD |
| `backend/tests/unit/test_permission_manager.py` | New — tool resolution logic |
| `backend/tests/unit/test_agent_session_service.py` | New — state transitions and LangGraph integration |
| `backend/tests/unit/test_agent_identity_service.py` | New — referential integrity; OAuth flow token exchange |
| `backend/tests/unit/test_token_refresh_service.py` | New — token refresh logic against mocked IdP endpoint |
| `backend/tests/unit/test_realm_manager.py` | New — realm initialization against mocked Keycloak admin API |
| `backend/tests/integration/test_agent_session_lifecycle.py` | New — end-to-end session flow against real DB with LangGraph |
| `frontend/src/__tests__/AgentRoleDialog.test.tsx` | New — SOP/Skill selection and preview |
| `frontend/src/__tests__/AgentSessionLaunchDialog.test.tsx` | New — input_type rendering |
| `frontend/src/__tests__/AgentSessionPage.test.tsx` | New — polling for task agents, chat UI for conversational agents, result rendering |
| `e2e/tests/agent-runtime.spec.ts` | New — mocked E2E suites + real backend integration variant |
