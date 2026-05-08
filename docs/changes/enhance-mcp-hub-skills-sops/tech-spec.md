# Technical Specification: enhance-mcp-hub-skills-sops

## Technical Overview

This change extends three existing backend domains (MCP Hub, Skills, SOPs) with additive model fields and new API endpoints, then replaces four stub frontend components with full implementations. Two cross-cutting capabilities are introduced: (1) automatic assembly of tool schemas into skill instructions via a computed `instructions_with_tools` field returned on every skill read, and (2) a Skill Seeder that creates default skills (`save_result`, `send_notification`) during platform installation. The backend changes are purely additive (new nullable columns, column rename, enum value rename, new endpoints, new computed field, new seeder service) requiring one Alembic migration. The frontend changes implement the full prototype UI for McpSessionManager, McpToolBrowser, SkillEditor (with read-only Generated Tool Reference section), and SopEditor, all connected to the extended API surface via React Query hooks.

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
| `SkillRead` | Response schema for list endpoint; includes `tool_ids: list[uuid.UUID]` derived from `tool_bindings` relationship; includes computed `instructions_with_tools: str \| None` (base instructions + appended Tool Section) | `backend/app/schemas/skills.py` |
| `SkillDetailRead` | New response schema for the skill detail endpoint (`GET /skills/{id}`); extends `SkillRead`; includes the full editable `instructions` field alongside computed `instructions_with_tools` | `backend/app/schemas/skills.py` |

### Backend — API Layer

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpSessionRouter` | Existing session CRUD; updated to persist and return `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | New router: all-tools listing + tool-to-skill reverse mapping | `backend/app/api/v1/mcp_hub.py` |
| `SkillRouter` | Existing skill CRUD; updated to eager-load `tool_bindings`; new role membership endpoints; calls `assemble_tool_section` when building skill responses | `backend/app/api/v1/skills.py` |
| `assemble_tool_section` | Function that builds the read-only Tool Section markdown block from a list of tool records (name, description, input_schema); appended to base `instructions` to produce `instructions_with_tools`; never stored, always regenerated on read | `backend/app/api/v1/skills.py` |
| `SopRouter` | Existing SOP CRUD; updated to persist `instructions`; `replace_sop_steps` updated for renamed fields; new role membership endpoints | `backend/app/api/v1/sops.py` |

### Backend — New Services

| Component | Responsibility | File |
|-----------|---------------|------|
| `SkillSeeder` | Idempotent initializer; checks for `save_result` and `send_notification` skills by canonical name; creates skill records and binds platform tool entries if absent; leaves existing skills untouched; invoked at startup and via CLI | `backend/app/services/skill_seeder.py` |

### Frontend — Types

| Component | Responsibility | File |
|-----------|---------------|------|
| `McpSession` interface | Add `identity_binding`, `credential_config` | `frontend/src/types/index.ts` |
| `Sop` interface | Add `instructions` | `frontend/src/types/index.ts` |
| `SopStep` interface | Rename `delegate_agent_type_id` → `target_agent_type_id`; add `step_config` | `frontend/src/types/index.ts` |
| `SopStepType` type | Add `'skill_invocation'` value | `frontend/src/types/index.ts` |
| `Skill` interface | Add `tool_ids: string[]`; add `instructions_with_tools: string \| null` | `frontend/src/types/index.ts` |

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
| `SkillEditor` | In-page skill editor: Basic Info, MCP Tools multi-select grouped by server, Assign to Roles sidebar, read-only "Generated Tool Reference" section below the instructions textarea showing the `instructions_with_tools` Tool Section | `frontend/src/pages/skills/SkillEditor.tsx` |
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
| `GET` | `/skills` | Response items use `SkillRead`; now include `tool_ids` and computed `instructions_with_tools` |
| `GET` | `/skills/{skill_id}` | Response uses new `SkillDetailRead`; includes `tool_ids`, `instructions`, and computed `instructions_with_tools` |
| `POST` | `/skills` | Accepts `instructions` field |
| `PUT` | `/skills/{skill_id}` | Accepts `instructions` field |

### No Breaking Changes — Field Rename Handling

The `delegate_agent_type_id` → `target_agent_type_id` rename and `skill` → `skill_invocation` enum rename are breaking changes at the API contract level. All existing clients (frontend types) must be updated in Phase 3 before the Phase 4 components consume the updated API. No dual-field compatibility shim is needed because frontend and backend are deployed together.

---

## Tool Schema Assembly

The `instructions_with_tools` field is a computed, read-only value assembled at skill-read time. It is never stored in the database — only the base `instructions` field is persisted.

**Field semantics:**

- `instructions` — the human-authored base text; editable in the skill editor; stored in the `Skill` table
- `instructions_with_tools` — computed on every read: base `instructions` (or empty string if null) + `\n\n` + Tool Section markdown block; returned in both `SkillRead` (list) and `SkillDetailRead` (detail)
- If the skill has no tool bindings, `instructions_with_tools` equals the base `instructions` value with no Tool Section appended
- Schema drift is impossible: the Tool Section is always regenerated from the current MCP tool registry entries

**Tool Section format:**

- Heading: `## Tools`
- One subsection per bound tool showing tool name, description, and input schema
- Tools are ordered by `SkillToolBinding.order`

**Assembly function:** `assemble_tool_section` in `backend/app/api/v1/skills.py`

- Accepts a list of tool records (`name: str`, `description: str | None`, `input_schema: dict | None`)
- Returns a markdown string beginning with `## Tools\n`
- Called by both `list_skills` and `get_skill` after the Tool Repository returns the bound tool records

**Data flow (detail path):**

1. Client calls `GET /skills/{id}`
2. `get_skill` fetches the `Skill` record with `selectinload(Skill.tool_bindings)` + joined `McpTool` rows
3. `assemble_tool_section` builds the Tool Section markdown from the fetched tool records
4. Response serialised as `SkillDetailRead` with `instructions_with_tools = instructions + "\n\n" + tool_section`
5. The Tool Section portion is rendered read-only in the frontend; the `instructions` field remains editable

---

## Skill Seeder & Default Skills

The `SkillSeeder` in `backend/app/services/skill_seeder.py` is a lightweight idempotent initializer that creates the two default platform skills if they do not already exist.

**Default skills created:**

| Canonical name | Purpose |
|----------------|---------|
| `save_result` | Persists structured agent outputs to the Result Repository |
| `send_notification` | Dispatches notifications through configured channel integrations |

**Seeder behaviour:**

- Queries the `skills` table by canonical name — name is the idempotency key
- If a skill is absent, inserts the skill record and binds the corresponding platform `McpTool` entries
- If a skill already exists (including if a user has edited it), leaves it completely untouched — seeder never overwrites
- Runs within a single database transaction; failure rolls back without partial state

**Invocation points:**

- Application startup: `SkillSeeder.run()` called from the lifespan/startup event in `backend/app/main.py`, after Alembic migrations complete and before the API accepts traffic
- CLI command `seed-skills` in `backend/app/cli.py`: allows operators to manually trigger seeding after a fresh install or database restore

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
| `['skills']` | All skills (includes `tool_ids`, `instructions_with_tools`) | existing query in `SkillListPage` |
| `['skills', skillId, 'roles']` | Role IDs for a skill | `useSkillRoles` |
| `['sops']` | All SOPs | existing query in `SopListPage` |
| `['sops', sopId, 'roles']` | Role IDs for a SOP | `useSopRoles` |

### Local Component State

- `McpHubPage`: `activeTab: 'servers' | 'tools'`; `sessionServerId: string | null`
- `SkillListPage`: `editorSkill: Skill | null | undefined` (undefined = hidden, null = create mode, Skill = edit mode)
- `SopListPage`: `editorSop: SopDetail | null | undefined` (same pattern)
- `SkillEditor`: `selectedToolIds: string[]`; `selectedRoleIds: string[]`; `form: { name, description, instructions }`; `instructions_with_tools` sourced from the fetched skill response (read-only display; not part of local form state)
- `SopEditor`: `steps: SopStepDraft[]` (local reorderable list); `form: { name, description, instructions, is_active }`
- `McpSessionManager`: `dialogOpen`; `editSession`; `form`; `dialogError` — all per Dialog Error Handling Standard

---

## Data Access Patterns

All data access follows the project convention: frontend calls backend REST APIs; no direct database access from frontend.

| Pattern | Used For | Rationale |
|---------|----------|-----------|
| React Query `useQuery` | All read operations | Caching, background refresh, loading/error state |
| React Query `useMutation` + `queryClient.invalidateQueries` | Create / update / delete operations | Automatic cache invalidation after mutation |
| `selectinload` in SQLAlchemy queries | Eager-loading `Skill.tool_bindings` in `list_skills` / `get_skill` | Avoids N+1 when serialising `tool_ids` and fetching tool schemas for `instructions_with_tools` assembly |
| Atomic DB operation (delete + insert) | `replace_sop_steps`, `PUT /skills/{id}/roles`, `PUT /sops/{id}/roles` | Ensures no partial state between steps |
| Join table queries | `GET /skills/{id}/roles`, `GET /sops/{id}/roles` | Query `agent_role_skills` / `agent_role_sops` directly |
| Encrypt-on-write, never-return | MCP session credentials | AES-256 via `CredentialVault`; `encrypted_credentials` excluded from all read schemas |
| Client-side filtering | Tool search in `McpToolBrowser`, skill search in `SkillListPage` | Data sets are small enough; avoids extra API round-trips |
| Idempotent insert by canonical name | Skill Seeder default skills | Name-based check prevents duplicate creation across restarts |

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
| `SkillRead` | Pydantic schema | Skill list response with `tool_ids` and computed `instructions_with_tools` | `backend/app/schemas/skills.py` |
| `SkillDetailRead` | Pydantic schema | New skill detail response (`GET /skills/{id}`); extends `SkillRead`; includes full editable `instructions` and computed `instructions_with_tools` | `backend/app/schemas/skills.py` |
| `SkillCreate` | Pydantic schema | Skill creation payload with `instructions` | `backend/app/schemas/skills.py` |
| `SkillUpdate` | Pydantic schema | Skill partial update with `instructions` | `backend/app/schemas/skills.py` |
| `McpServerRouter` | FastAPI router | MCP server CRUD; prefix `/mcp/servers` | `backend/app/api/v1/mcp_hub.py` |
| `McpSessionRouter` | FastAPI router | Session CRUD under `/mcp/servers/{id}/sessions`; updated for new fields | `backend/app/api/v1/mcp_hub.py` |
| `McpToolRouter` | FastAPI router | New: `GET /mcp/tools` and `GET /mcp/tools/{id}/skills` | `backend/app/api/v1/mcp_hub.py` |
| `list_all_tools` | endpoint function | Returns all active tools across all servers | `backend/app/api/v1/mcp_hub.py` |
| `list_tool_skills` | endpoint function | Returns skills bound to a specific tool | `backend/app/api/v1/mcp_hub.py` |
| `create_mcp_session` | endpoint function | Creates session; encrypts credentials; stores `identity_binding`, `credential_config` | `backend/app/api/v1/mcp_hub.py` |
| `update_mcp_session` | endpoint function | Updates session; re-encrypts credentials if provided; stores new fields | `backend/app/api/v1/mcp_hub.py` |
| `SkillRouter` | FastAPI router | Skill CRUD + new role membership endpoints; prefix `/skills` | `backend/app/api/v1/skills.py` |
| `list_skills` | endpoint function | Returns all skills with eager-loaded `tool_ids` and computed `instructions_with_tools` | `backend/app/api/v1/skills.py` |
| `get_skill` | endpoint function | Returns one skill via `SkillDetailRead` with `tool_ids` and `instructions_with_tools` | `backend/app/api/v1/skills.py` |
| `assemble_tool_section` | function | Builds read-only Tool Section markdown from list of tool records; called by `_build_skill_read` and `_build_skill_detail_read` | `backend/app/api/v1/skills.py` |
| `_build_skill_read` | helper function | Constructs `SkillRead` with computed `instructions_with_tools`; uses nested eager-loaded tool bindings | `backend/app/api/v1/skills.py` |
| `_build_skill_detail_read` | helper function | Constructs `SkillDetailRead` with computed `instructions_with_tools`; used by `get_skill`, `create_skill`, `update_skill` | `backend/app/api/v1/skills.py` |
| `get_skill_roles` | endpoint function | New: returns role IDs that include this skill | `backend/app/api/v1/skills.py` |
| `set_skill_roles` | endpoint function | New: atomically replaces skill's role membership | `backend/app/api/v1/skills.py` |
| `SopRouter` | FastAPI router | SOP CRUD + new role membership endpoints; prefix `/sops` | `backend/app/api/v1/sops.py` |
| `replace_sop_steps` | endpoint function | Replaces full step list; updated for `target_agent_type_id`, `step_config` | `backend/app/api/v1/sops.py` |
| `get_sop_roles` | endpoint function | New: returns role IDs that include this SOP | `backend/app/api/v1/sops.py` |
| `set_sop_roles` | endpoint function | New: atomically replaces SOP's role membership | `backend/app/api/v1/sops.py` |
| `SkillSeeder` | service class | Idempotent initializer; creates `save_result` and `send_notification` skills if absent | `backend/app/services/skill_seeder.py` |
| `seed_skills` | CLI command | CLI entry point for manual skill seeding; triggers `SkillSeeder.run()` | `backend/app/cli.py` |
| `McpSession` (TS) | TypeScript interface | Frontend type with `identity_binding`, `credential_config` | `frontend/src/types/index.ts` |
| `Sop` (TS) | TypeScript interface | Frontend type with `instructions` | `frontend/src/types/index.ts` |
| `SopStep` (TS) | TypeScript interface | Frontend type with `target_agent_type_id`, `step_config` | `frontend/src/types/index.ts` |
| `SopStepType` (TS) | TypeScript union type | `'skill_invocation' \| 'agent_delegation'` | `frontend/src/types/index.ts` |
| `Skill` (TS) | TypeScript interface | Frontend type with `tool_ids: string[]` and `instructions_with_tools: string \| null` | `frontend/src/types/index.ts` |
| `useAllTools` | React Query hook | Fetches `GET /mcp/tools`; cache key `['mcp', 'tools']` | `frontend/src/hooks/useMcpServers.ts` |
| `useToolSkills` | React Query hook | Fetches `GET /mcp/tools/{toolId}/skills` | `frontend/src/hooks/useMcpServers.ts` |
| `useServerSessions` | React Query hook | Existing; now returns updated `McpSession` type | `frontend/src/hooks/useMcpServers.ts` |
| `useSkillRoles` | React Query hook | Fetches `GET /skills/{skillId}/roles` | `frontend/src/hooks/useSkills.ts` |
| `useSopRoles` | React Query hook | Fetches `GET /sops/{sopId}/roles` | `frontend/src/hooks/useSops.ts` |
| `McpHubPage` | React component | Tabbed MCP Hub: Servers + Tool Repository; sessions dialog trigger | `frontend/src/pages/mcp/McpHubPage.tsx` |
| `McpSessionManager` | React component | Session CRUD UI; receives `serverId` prop | `frontend/src/pages/mcp/McpSessionManager.tsx` |
| `McpToolBrowser` | React component | Tool Repository UI; all tools grouped by server | `frontend/src/pages/mcp/McpToolBrowser.tsx` |
| `SkillListPage` | React component | Skill list with tool count and role chips; hosts SkillEditor in-page panel | `frontend/src/pages/skills/SkillListPage.tsx` |
| `SkillEditor` | React component | In-page skill editor; instructions field; multi-tool select grouped by server; role assignment sidebar; read-only Generated Tool Reference section | `frontend/src/pages/skills/SkillEditor.tsx` |
| `SopListPage` | React component | SOP list with step count; hosts SopEditor in-page panel | `frontend/src/pages/skills/SopListPage.tsx` |
| `SopEditor` | React component | In-page SOP editor; instructions field; step cards with reorder | `frontend/src/pages/skills/SopEditor.tsx` |
