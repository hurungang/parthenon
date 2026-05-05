# Technical Specification: enhance-mcp-hub-skills-sops

## Technical Overview

This change extends three existing backend domains (MCP Hub, Skills, SOPs) with additive model fields and new API endpoints, then replaces four stub frontend components with full implementations. The backend changes are purely additive (new nullable columns, column rename, enum value rename, new endpoints) requiring one Alembic migration. The frontend changes implement the full prototype UI for McpSessionManager, McpToolBrowser, SkillEditor, and SopEditor, all connected to the extended API surface via React Query hooks.

---

## Component Breakdown

### Backend — Data Layer

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpSession` ORM model | Add `identity_binding` and `credential_config` JSON columns | `backend/app/db/models/mcp_hub.py` |
| `Skill` ORM model | Add `instructions` Text column | `backend/app/db/models/skills.py` |
| `Sop` ORM model | Add `instructions` Text column | `backend/app/db/models/skills.py` |
| `SopStep` ORM model | Rename `delegate_agent_type_id` → `target_agent_type_id`; add `step_config` JSON; rename `SopStepType.skill` → `skill_invocation` | `backend/app/db/models/skills.py` |
| `SopStepType` enum | Enum class with values `skill_invocation` and `agent_delegation` | `backend/app/db/models/skills.py` |
| Alembic migration | Generated migration covering all three model changes | `backend/alembic/versions/10703a671de6_enhance_mcp_hub_skills_sops.py` |

### Backend — Schema Layer

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpSessionCreate` | Request schema for session creation; accepts `identity_binding`, `credential_config` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionUpdate` | Partial update schema; includes new fields | `backend/app/schemas/mcp_hub.py` |
| `McpSessionRead` | Response schema; exposes `identity_binding`, `credential_config`; never exposes `encrypted_credentials` | `backend/app/schemas/mcp_hub.py` |
| `SopCreate` / `SopUpdate` | Request schemas; add `instructions` field | `backend/app/schemas/skills.py` |
| `SopRead` / `SopDetailRead` | Response schemas; include `instructions` | `backend/app/schemas/skills.py` |
| `SopStepCreate` | Request schema; uses `target_agent_type_id`, `step_config`; default `step_type` is `skill_invocation` | `backend/app/schemas/skills.py` |
| `SopStepRead` | Response schema; uses `target_agent_type_id`, `step_config` | `backend/app/schemas/skills.py` |
| `SkillCreate` | Request schema for skill creation; accepts `instructions` | `backend/app/schemas/skills.py` |
| `SkillUpdate` | Partial update schema; accepts `instructions` | `backend/app/schemas/skills.py` |
| `SkillRead` | Response schema; extended with `tool_ids: list[uuid.UUID]` derived from `tool_bindings` relationship | `backend/app/schemas/skills.py` |

### Backend — API Layer

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpSessionRouter` | Existing session CRUD; updated to persist and return `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | New router: all-tools listing + tool-to-skill reverse mapping | `backend/app/api/v1/mcp_hub.py` |
| `SkillRouter` | Existing skill CRUD; updated to eager-load `tool_bindings`; new role membership endpoints | `backend/app/api/v1/skills.py` |
| `SopRouter` | Existing SOP CRUD; updated to persist `instructions`; `replace_sop_steps` updated for renamed fields; new role membership endpoints | `backend/app/api/v1/sops.py` |

### Frontend — Types

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpSession` interface | Add `identity_binding`, `credential_config` | `frontend/src/types/index.ts` |
| `Sop` interface | Add `instructions` | `frontend/src/types/index.ts` |
| `SopStep` interface | Rename `delegate_agent_type_id` → `target_agent_type_id`; add `step_config` | `frontend/src/types/index.ts` |
| `SopStepType` type | Add `'skill_invocation'` value | `frontend/src/types/index.ts` |
| `Skill` interface | Add `tool_ids: string[]` | `frontend/src/types/index.ts` |

### Frontend — Hooks

| Component | Responsibility | File |
|-----------|---------------|------|
| `useMcpServers` | Existing; unchanged | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | Existing; returns updated `McpSession` type | `frontend/src/hooks/useMcpServers.ts` |
| `useAllTools` | New: `GET /mcp/tools` — all active tools across servers | `frontend/src/hooks/useMcpServers.ts` |
| `useToolSkills` | New: `GET /mcp/tools/{toolId}/skills` — skills mapped to a specific tool | `frontend/src/hooks/useMcpServers.ts` |
| `useSkillRoles` | New: `GET /skills/{skillId}/roles` — role IDs that include a skill | `frontend/src/hooks/useSkills.ts` |
| `useSopRoles` | New: `GET /sops/{sopId}/roles` — role IDs that include a SOP | `frontend/src/hooks/useSops.ts` |

### Frontend — Components

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpHubPage` | Tabbed view: Servers tab + Tool Repository tab; Sessions dialog wired per row | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpSessionManager` | Full session CRUD: list, create, edit, delete; fields include auth type, credentials (write-only), identity binding, credential config | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpToolBrowser` | Tool Repository: all tools grouped by server, assigned skill chips, search, server filter, active toggle | `frontend/src/pages/mcp/McpToolBrowser.tsx` |
| `SkillListPage` | Skill list with tool count and assigned role chips; in-page panel host for SkillEditor | `frontend/src/pages/skills/SkillListPage.tsx` |
| `SkillEditor` | In-page skill editor: Basic Info, MCP Tools multi-select grouped by server, Assign to Roles sidebar | `frontend/src/pages/skills/SkillEditor.tsx` |
| `SopListPage` | SOP list with step count; in-page panel host for SopEditor | `frontend/src/pages/skills/SopListPage.tsx` |
| `SopEditor` | In-page SOP editor: Basic Info + instructions, ordered step cards with drag reorder, step type selector, SOP Details sidebar | `frontend/src/pages/skills/SopEditor.tsx` |

---

## API Changes

### New Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/mcp/tools` | Return all active `McpTool` records across all servers, ordered by server name then tool name | `read` on `RT_MCP_SERVER` |
| `GET` | `/mcp/tools/{tool_id}/skills` | Return all `Skill` records bound to the given tool via `skill_tool_bindings` | `read` on `RT_MCP_SERVER` |
| `GET` | `/skills/{skill_id}/roles` | Return list of `AgentRole` IDs that include this skill (via `agent_role_skills`) | `read` on `RT_SKILL` |
| `PUT` | `/skills/{skill_id}/roles` | Atomically replace skill's role membership; body: `{"role_ids": [uuid, ...]}` | `update` on `RT_SKILL` |
| `GET` | `/sops/{sop_id}/roles` | Return list of `AgentRole` IDs that include this SOP (via `agent_role_sops`) | `read` on `RT_SKILL` |
| `PUT` | `/sops/{sop_id}/roles` | Atomically replace SOP's role membership; body: `{"role_ids": [uuid, ...]}` | `update` on `RT_SKILL` |

### Modified Endpoints

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/mcp/servers/{server_id}/sessions` | Accepts and stores `identity_binding`, `credential_config` |
| `PUT` | `/mcp/servers/{server_id}/sessions/{session_id}` | Accepts and stores `identity_binding`, `credential_config` |
| `GET` | `/mcp/servers/{server_id}/sessions` | Response includes `identity_binding`, `credential_config` |
| `GET` | `/mcp/servers/{server_id}/sessions/{session_id}` | Response includes `identity_binding`, `credential_config` |
| `POST` | `/sops` | Accepts `instructions` field |
| `PUT` | `/sops/{sop_id}` | Accepts `instructions` field |
| `GET` | `/sops/{sop_id}` | Response includes `instructions` |
| `PUT` | `/sops/{sop_id}/steps` | Request/response use `target_agent_type_id` and `step_config`; default `step_type` is `skill_invocation` |
| `GET` | `/skills` | Response items include `tool_ids` array |
| `GET` | `/skills/{skill_id}` | Response includes `tool_ids` array |
| `POST` | `/skills` | Accepts `instructions` field |
| `PUT` | `/skills/{skill_id}` | Accepts `instructions` field |

### No Breaking Changes — Field Rename Handling

The `delegate_agent_type_id` → `target_agent_type_id` rename and `skill` → `skill_invocation` enum rename are breaking changes at the API contract level. All existing clients (frontend types) must be updated in Phase 3 before the Phase 4 components consume the updated API. No dual-field compatibility shim is needed because frontend and backend are deployed together.

---

## State Management

### React Query Cache Keys

| Key | Data | Hook |
|-----|------|------|
| `['mcp', 'servers']` | All MCP servers | `useMcpServers` |
| `['mcp', 'servers', serverId, 'sessions']` | Sessions for one server | `useServerSessions` |
| `['mcp', 'servers', serverId, 'tools']` | Tools for one server | `useServerTools` |
| `['mcp', 'tools']` | All tools across all servers | `useAllTools` |
| `['mcp', 'tools', toolId, 'skills']` | Skills mapped to a tool | `useToolSkills` |
| `['skills']` | All skills (includes `tool_ids`) | existing query in `SkillListPage` |
| `['skills', skillId, 'roles']` | Role IDs for a skill | `useSkillRoles` |
| `['sops']` | All SOPs | existing query in `SopListPage` |
| `['sops', sopId, 'roles']` | Role IDs for a SOP | `useSopRoles` |

### Local Component State

- `McpHubPage`: `activeTab: 'servers' | 'tools'`; `sessionServerId: string | null`
- `SkillListPage`: `editorSkill: Skill | null | undefined` (undefined = hidden, null = create mode, Skill = edit mode)
- `SopListPage`: `editorSop: SopDetail | null | undefined` (same pattern)
- `SkillEditor`: `selectedToolIds: string[]`; `selectedRoleIds: string[]`; `form: { name, description }`
- `SopEditor`: `steps: SopStepDraft[]` (local reorderable list); `form: { name, description, instructions, is_active }`
- `McpSessionManager`: `dialogOpen`; `editSession`; `form`; `dialogError` — all per Dialog Error Handling Standard

---

## Data Access Patterns

All data access follows the project convention: frontend calls backend REST APIs; no direct database access from frontend.

| Pattern | Used For | Rationale |
|---------|----------|-----------|
| React Query `useQuery` | All read operations | Caching, background refresh, loading/error state |
| React Query `useMutation` + `queryClient.invalidateQueries` | Create / update / delete operations | Automatic cache invalidation after mutation |
| `selectinload` in SQLAlchemy queries | Eager-loading `Skill.tool_bindings` in `list_skills` / `get_skill` | Avoids N+1 when serialising `tool_ids` |
| Atomic DB operation (delete + insert) | `replace_sop_steps`, `PUT /skills/{id}/roles`, `PUT /sops/{id}/roles` | Ensures no partial state between steps |
| Join table queries | `GET /skills/{id}/roles`, `GET /sops/{id}/roles` | Query `agent_role_skills` / `agent_role_sops` directly |
| Encrypt-on-write, never-return | MCP session credentials | AES-256 via `CredentialVault`; `encrypted_credentials` excluded from all read schemas |
| Client-side filtering | Tool search in `McpToolBrowser`, skill search in `SkillListPage` | Data sets are small enough; avoids extra API round-trips |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `McpSession` | ORM model | MCP session with credentials and identity binding | `backend/app/db/models/mcp_hub.py` |
| `Sop` | ORM model | Standard Operating Procedure with instructions field | `backend/app/db/models/skills.py` |
| `SopStep` | ORM model | Ordered SOP step; uses `target_agent_type_id`, `step_config` | `backend/app/db/models/skills.py` |
| `SopStepType` | enum | `skill_invocation` or `agent_delegation` | `backend/app/db/models/skills.py` |
| `SkillToolBinding` | ORM model | Join between Skill and McpTool with ordering | `backend/app/db/models/skills.py` |
| `McpSessionCreate` | Pydantic schema | Session creation payload; includes `identity_binding`, `credential_config` | `backend/app/schemas/mcp_hub.py` |
| `McpSessionUpdate` | Pydantic schema | Session partial update payload | `backend/app/schemas/mcp_hub.py` |
| `McpSessionRead` | Pydantic schema | Session response; no credentials | `backend/app/schemas/mcp_hub.py` |
| `SopCreate` | Pydantic schema | SOP creation payload with `instructions` | `backend/app/schemas/skills.py` |
| `SopUpdate` | Pydantic schema | SOP partial update with `instructions` | `backend/app/schemas/skills.py` |
| `SopRead` | Pydantic schema | SOP response with `instructions` | `backend/app/schemas/skills.py` |
| `SopDetailRead` | Pydantic schema | SOP response with `instructions` and `steps` list | `backend/app/schemas/skills.py` |
| `SopStepCreate` | Pydantic schema | Step creation payload; uses `target_agent_type_id`, `step_config` | `backend/app/schemas/skills.py` |
| `SopStepRead` | Pydantic schema | Step response; uses `target_agent_type_id`, `step_config` | `backend/app/schemas/skills.py` |
| `SkillRead` | Pydantic schema | Skill response extended with `tool_ids` list | `backend/app/schemas/skills.py` |
| `SkillCreate` | Pydantic schema | Skill creation payload with `instructions` | `backend/app/schemas/skills.py` |
| `SkillUpdate` | Pydantic schema | Skill partial update with `instructions` | `backend/app/schemas/skills.py` |
| `McpServerRouter` | FastAPI router | MCP server CRUD; prefix `/mcp/servers` | `backend/app/api/v1/mcp_hub.py` |
| `McpSessionRouter` | FastAPI router | Session CRUD under `/mcp/servers/{id}/sessions`; updated for new fields | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | FastAPI router | New: `GET /mcp/tools` and `GET /mcp/tools/{id}/skills` | `backend/app/api/v1/mcp_hub.py` |
| `list_all_tools` | endpoint function | Returns all active tools across all servers | `backend/app/api/v1/mcp_hub.py` |
| `list_tool_skills` | endpoint function | Returns skills bound to a specific tool | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_session` | endpoint function | Creates session; encrypts credentials; stores identity_binding, credential_config | `backend/app/api/v1/mcp_hub.py` |
| `update_mcp_session` | endpoint function | Updates session; re-encrypts credentials if provided; stores new fields | `backend/app/api/v1/mcp_hub.py` |
| `SkillRouter` | FastAPI router | Skill CRUD + new role membership endpoints; prefix `/skills` | `backend/app/api/v1/skills.py` |
| `list_skills` | endpoint function | Returns all skills with eager-loaded `tool_ids` | `backend/app/api/v1/skills.py` |
| `get_skill` | endpoint function | Returns one skill with eager-loaded `tool_ids` | `backend/app/api/v1/skills.py` |
| `get_skill_roles` | endpoint function | New: returns role IDs that include this skill | `backend/app/api/v1/skills.py` |
| `set_skill_roles` | endpoint function | New: atomically replaces skill's role membership | `backend/app/api/v1/skills.py` |
| `SopRouter` | FastAPI router | SOP CRUD + new role membership endpoints; prefix `/sops` | `backend/app/api/v1/sops.py` |
| `replace_sop_steps` | endpoint function | Replaces full step list; updated for `target_agent_type_id`, `step_config` | `backend/app/api/v1/sops.py` |
| `get_sop_roles` | endpoint function | New: returns role IDs that include this SOP | `backend/app/api/v1/sops.py` |
| `set_sop_roles` | endpoint function | New: atomically replaces SOP's role membership | `backend/app/api/v1/sops.py` |
| `McpSession` (TS) | TypeScript interface | Frontend type with `identity_binding`, `credential_config` | `frontend/src/types/index.ts` |
| `Sop` (TS) | TypeScript interface | Frontend type with `instructions` | `frontend/src/types/index.ts` |
| `SopStep` (TS) | TypeScript interface | Frontend type with `target_agent_type_id`, `step_config` | `frontend/src/types/index.ts` |
| `SopStepType` (TS) | TypeScript union type | `'skill_invocation' \| 'agent_delegation'` | `frontend/src/types/index.ts` |
| `Skill` (TS) | TypeScript interface | Frontend type extended with `tool_ids: string[]` | `frontend/src/types/index.ts` |
| `useAllTools` | React Query hook | Fetches `GET /mcp/tools`; cache key `['mcp', 'tools']` | `frontend/src/hooks/useMcpServers.ts` |
| `useToolSkills` | React Query hook | Fetches `GET /mcp/tools/{toolId}/skills` | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | React Query hook | Existing; now returns updated `McpSession` type | `frontend/src/hooks/useMcpServers.ts` |
| `useSkillRoles` | React Query hook | Fetches `GET /skills/{skillId}/roles` | `frontend/src/hooks/useSkills.ts` |
| `useSopRoles` | React Query hook | Fetches `GET /sops/{sopId}/roles` | `frontend/src/hooks/useSops.ts` |
| `McpHubPage` | React component | Tabbed MCP Hub: Servers + Tool Repository; sessions dialog trigger | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpSessionManager` | React component | Session CRUD UI; receives `serverId` prop | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpToolBrowser` | React component | Tool Repository UI; all tools grouped by server | `frontend/src/pages/mcp/McpToolBrowser.tsx` |
| `SkillListPage` | React component | Skill list with tool count and role chips; hosts SkillEditor in-page panel | `frontend/src/pages/skills/SkillListPage.tsx` |
| `SkillEditor` | React component | In-page skill editor; instructions field; multi-tool select grouped by server; role assignment sidebar | `frontend/src/pages/skills/SkillEditor.tsx` |
| `SopListPage` | React component | SOP list with step count; hosts SopEditor in-page panel | `frontend/src/pages/skills/SopListPage.tsx` |
| `SopEditor` | React component | In-page SOP editor; instructions field; step cards with reorder | `frontend/src/pages/skills/SopEditor.tsx` |
