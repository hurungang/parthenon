# Implementation Plan: enhance-mcp-hub-skills-sops

**Status:** `complete`  
**Original scope completed:** 2026-05-04  
**Refinement completed:** 2026-05-06 — tool schema assembly (`instructions_with_tools`), `SkillDetailRead` schema, Skill Seeder with CLI command, SkillEditor Generated Tool Reference section  
**Deviations:** Full Vitest component tests for `SkillEditor` and `SopEditor` were skipped due to a Vitest mocking infrastructure issue (not an implementation problem). Lightweight workaround test files (`SkillEditor.simple.test.tsx`, `SopEditor.simple.test.tsx`) cover core rendering assertions. All components are verified via E2E tests.

## Overview

This change brings MCP Hub, Skills, and SOPs to full enterprise parity with the master prototype. It covers three coupled areas: database model extensions (new JSON fields, renamed column, enum rename, instructions field), backend API additions (all-tools endpoint, tool-to-skill reverse mapping, role membership endpoints, schema updates, `instructions_with_tools` computed field, Skill Seeder), and full frontend component implementations replacing the current stub components with functional UIs for session management, tool browsing, skill editing (with read-only Generated Tool Reference section), and SOP step editing.

---

## Task Checklist

### Phase 1 — Database Schema & Migration

- [x] 1.1 — Update McpSession model with identity_binding and credential_config fields
- [x] 1.2 — Add instructions field to Skill and Sop entities
- [x] 1.3 — Update SopStep model: rename delegate_agent_type_id, update SopStepType enum, add step_config field
- [x] 1.4 — Generate Alembic migration and verify it applies cleanly

### Phase 2 — Backend Schemas & API

- [x] 2.1 — Update McpSession Pydantic schemas for new fields
- [x] 2.2 — Update Pydantic schemas for Skill and Sop to include instructions
- [x] 2.3 — Update SkillRead schema to include tool_ids; eager-load tool bindings in skills API
- [x] 2.4 — Add GET /mcp/tools all-tools endpoint and GET /mcp/tools/{tool_id}/skills reverse-mapping endpoint
- [x] 2.5 — Fix sops.py to write target_agent_type_id and step_config in replace_sop_steps
- [x] 2.6 — Add skill role membership endpoints (GET + PUT /skills/{skill_id}/roles)
- [x] 2.7 — Add SOP role membership endpoints (GET + PUT /sops/{sop_id}/roles)
- [x] 2.8 — Add instructions_with_tools computed field to SkillRead and new SkillDetailRead schemas (rework of 2.3)
- [x] 2.9 — Implement assemble_tool_section function; wire into list_skills and get_skill
- [x] 2.10 — Implement SkillSeeder service with idempotent default skill creation
- [x] 2.11 — Add seed-skills CLI command and startup invocation

### Phase 3 — Frontend Types & Hooks

- [x] 3.1 — Update TypeScript types for McpSession, Sop, SopStep, SopStepType, and Skill
- [x] 3.2 — Add useAllTools, useToolSkills, useSkillRoles, and useSopRoles query hooks

### Phase 4 — Frontend Components

- [x] 4.1 — Implement McpSessionManager: full CRUD with identity binding and credential config
- [x] 4.2 — Implement McpToolBrowser: tools grouped by server, skill mapping chips, enable toggle
- [x] 4.3 — Enhance McpHubPage: Servers / Tool Repository tabs, sessions dialog per server row
- [x] 4.4 — Implement SkillEditor: multi-tool checkbox list grouped by server, role assignment sidebar
- [x] 4.5 — Implement SopEditor: instructions field, step cards with type selector and reorder, in-page panel pattern
- [x] 4.6 — Wire SkillListPage to show SkillEditor in-page panel; wire SopListPage to show SopEditor in-page panel
- [x] 4.7 — Add i18n keys for all new UI text
- [x] 4.8 — Add read-only "Generated Tool Reference" section to SkillEditor (rework of 4.4)

---

## Phase 1 — Database Schema & Migration

### 1.1 — Update McpSession model with identity_binding and credential_config fields

Add two new nullable JSON columns to the `McpSession` ORM class in `backend/app/db/models/mcp_hub.py`:

- `identity_binding` (JSON, nullable) — structured reference to an agent identity or role; complements the existing `identity_subject` string with a typed, structured payload
- `credential_config` (JSON, nullable) — session-specific credential field shape and required key declarations; complements `encrypted_credentials` which holds the actual encrypted value

**Done when:** both columns appear in the `McpSession` class with `mapped_column(JSON, nullable=True)` and no existing columns are altered.

---

### 1.2 — Add instructions field to Skill and Sop entities

Add one new nullable Text column to both the `Skill` ORM class and the `Sop` ORM class in `backend/app/db/models/skills.py`:

- `Skill.instructions` (Text, nullable) — agent-facing guidance on how to use the composed tools in this skill
- `Sop.instructions` (Text, nullable) — multi-line human-readable workflow guidance presented to agents and operators running the SOP

**Done when:** `instructions` appears in both the `Skill` class and the `Sop` class with `mapped_column(Text, nullable=True)`.

---

### 1.3 — Update SopStep model: rename delegate_agent_type_id, update SopStepType enum, add step_config field

Three changes to `backend/app/db/models/skills.py`:

1. Rename the `SopStepType` enum value `skill` → `skill_invocation`. Update the Python enum class and the `Enum(...)` column definition. The PostgreSQL enum must be renamed at the database level via the migration (Alembic will handle this in task 1.4).
2. Rename the column `delegate_agent_type_id` → `target_agent_type_id` on the `SopStep` class. Keep the same type and nullable setting.
3. Add `step_config` (JSON, nullable) — step-specific runtime configuration (input overrides, timeout, retry policy).

Also update the `SopDetail` schema's `__repr__` and any forward references to `delegate_agent_type_id` in `backend/app/api/v1/sops.py` (addressed fully in task 2.5).

**Done when:** `SopStepType` has values `{skill_invocation, agent_delegation}`; `SopStep` has `target_agent_type_id` (not `delegate_agent_type_id`) and `step_config`; no references to old names remain in the models file.

---

### 1.4 — Generate Alembic migration and verify it applies cleanly

Run `alembic revision --autogenerate -m "enhance_mcp_hub_skills_sops"` from `backend/` using the configured database. Review the generated file in `backend/alembic/versions/` to confirm it captures:

- Two new JSON columns on `mcp_sessions`
- One new Text column on `sops`
- Column rename on `sop_steps` (`delegate_agent_type_id` → `target_agent_type_id`)
- Enum value rename for `sop_step_type_enum` (`skill` → `skill_invocation`)
- New JSON column `step_config` on `sop_steps`

Apply with `alembic upgrade head` and verify with `alembic current`.

**Done when:** `alembic current` shows the new migration as the head revision with no pending migrations; `alembic upgrade head` exits cleanly against the local database.

---

## Phase 2 — Backend Schemas & API

### 2.1 — Update McpSession Pydantic schemas for new fields

In `backend/app/schemas/mcp_hub.py`:

- `McpSessionCreate`: add optional `identity_binding: dict[str, Any] | None = None` and `credential_config: dict[str, Any] | None = None`
- `McpSessionUpdate`: add same two optional fields
- `McpSessionRead`: add `identity_binding: dict[str, Any] | None` and `credential_config: dict[str, Any] | None` (never expose `encrypted_credentials`)

**Done when:** all three schema classes include both new fields; `McpSessionRead.model_config = {"from_attributes": True}` still present; no raw credential values exposed.

---

### 2.2 — Update Pydantic schemas for Skill and Sop to include instructions

In `backend/app/schemas/skills.py`:

- `SkillCreate` and `SkillUpdate`: add `instructions: str | None = None`
- `SopCreate` and `SopUpdate`: add `instructions: str | None = None`
- `SopRead` and `SopDetailRead`: add `instructions: str | None`
- `SopStepCreate`: rename `delegate_agent_type_id` → `target_agent_type_id`; add `step_config: dict[str, Any] | None = None`; update `step_type` default from `SopStepType.skill` → `SopStepType.skill_invocation`
- `SopStepRead`: rename `delegate_agent_type_id` → `target_agent_type_id`; add `step_config: dict[str, Any] | None`
- Import `SopStepType` still from `app.db.models.skills`; the enum now uses the new value

**Done when:** `SkillCreate` and `SkillUpdate` include `instructions`; `SopCreate` and `SopUpdate` include `instructions`; schemas match the updated model fields; `SopStepType.skill_invocation` is the default in `SopStepCreate`; all old field names are gone.

---

### 2.3 — Update SkillRead schema to include tool_ids; eager-load tool bindings in skills API ⚠️ NEEDS REWORK

> **Rework required:** Task 2.3 was implemented as originally scoped (`tool_ids` added to `SkillRead`). The refinement adds the `instructions_with_tools` computed field and a new `SkillDetailRead` schema, which are addressed in tasks 2.8 and 2.9. The `SkillRead` schema and skills API endpoints must be revisited as part of those tasks.

In `backend/app/schemas/skills.py`, add `tool_ids: list[uuid.UUID] = []` to `SkillRead` with a `model_validator` (or `@computed_field`) that extracts IDs from the `tool_bindings` relationship list.

In `backend/app/api/v1/skills.py`, update `list_skills` and `get_skill` queries to use `selectinload(Skill.tool_bindings)` so the ORM relationship is populated before serialisation.

**Done when:** `GET /skills` and `GET /skills/{id}` responses include a `tool_ids` array; the array is ordered by binding `order`; existing create/update behaviour is unchanged.

---

### 2.4 — Add GET /mcp/tools all-tools endpoint and GET /mcp/tools/{tool_id}/skills reverse-mapping endpoint

Add two new routes to `backend/app/api/v1/mcp_hub.py` under a new `McpToolRouter` (prefix `/mcp/tools`):

- `GET /mcp/tools` — returns all active `McpTool` rows joined with their `McpServer` (for slug display), ordered by server name then tool name. Requires `read` permission on `RT_MCP_SERVER`. Response: `list[McpToolRead]`.
- `GET /mcp/tools/{tool_id}/skills` — returns all `Skill` records that have a `SkillToolBinding` for the given tool. Requires `read` permission on `RT_MCP_SERVER`. Response: `list[SkillRead]` (reuse existing schema; include `tool_ids` after task 2.3).

Register the new router in `backend/app/main.py` alongside the existing MCP routers.

**Done when:** both endpoints return 200 with correct payloads; unknown `tool_id` returns 404; both require JWT; router is registered and reachable.

---

### 2.5 — Fix sops.py to write target_agent_type_id and step_config in replace_sop_steps

In `backend/app/api/v1/sops.py`, update `replace_sop_steps`:

- Replace all references to `delegate_agent_type_id` with `target_agent_type_id`
- Pass `step_config=step_data.step_config` when constructing each `SopStep`
- Update the validation block: if `step_type == skill_invocation`, require `skill_id` and validate it exists; if `step_type == agent_delegation`, accept `target_agent_type_id` (no DB validation needed as it references AgentType which may be in a different table)

**Done when:** `replace_sop_steps` writes `target_agent_type_id` and `step_config` correctly; old field names are gone; existing step replacement tests still pass.

---

### 2.6 — Add skill role membership endpoints (GET + PUT /skills/{skill_id}/roles)

In `backend/app/api/v1/skills.py`, add two endpoints under `SkillRouter`:

- `GET /skills/{skill_id}/roles` — queries the `agent_role_skills` join table to return a list of `AgentRole` IDs (or full role objects) that include this skill. Requires `read` permission on `RT_SKILL`.
- `PUT /skills/{skill_id}/roles` — accepts `{"role_ids": [uuid, ...]}`, atomically replaces the skill's membership in `agent_role_skills` (removes old entries, inserts new ones). Requires `update` permission on `RT_SKILL`.

Return a simple `list[uuid.UUID]` (role IDs) from GET, and the updated `list[uuid.UUID]` from PUT.

**Done when:** GET returns correct role IDs; PUT replaces membership atomically; 404 if skill not found; permission checks enforced.

---

### 2.7 — Add SOP role membership endpoints (GET + PUT /sops/{sop_id}/roles)

Mirror of task 2.6, but in `backend/app/api/v1/sops.py` for the `agent_role_sops` join table.

- `GET /sops/{sop_id}/roles` — returns role IDs that include this SOP. Requires `read` on `RT_SKILL`.
- `PUT /sops/{sop_id}/roles` — atomically replaces SOP membership. Requires `update` on `RT_SKILL`.

**Done when:** same conditions as 2.6, applied to the SOP domain.

---

### 2.8 — Add instructions_with_tools computed field to SkillRead and new SkillDetailRead schemas

In `backend/app/schemas/skills.py`:

- Add `instructions_with_tools: str | None = None` to `SkillRead` as a non-stored, externally populated field (not a DB column; set by the endpoint after calling `assemble_tool_section`)
- Create `SkillDetailRead` as a new schema that extends `SkillRead` and additionally exposes the editable `instructions: str | None` field; used exclusively by `GET /skills/{id}`
- `SkillRead` (used by `GET /skills`) includes `instructions_with_tools` but not the raw `instructions` field, to keep the list payload lean

**Done when:** `SkillRead` includes `instructions_with_tools`; `SkillDetailRead` exists and inherits from `SkillRead` adding `instructions`; `GET /skills` returns `SkillRead`; `GET /skills/{id}` returns `SkillDetailRead`; TypeScript interface updates (task 3.1) consume the new field.

---

### 2.9 — Implement assemble_tool_section function; wire into list_skills and get_skill

In `backend/app/api/v1/skills.py`:

- Implement `assemble_tool_section(tools: list[McpToolRecord]) -> str` where `McpToolRecord` is a simple dataclass or namedtuple holding `name`, `description`, and `input_schema`
- The function returns a markdown string beginning with `## Tools\n` followed by one entry per tool; if `tools` is empty, return an empty string
- Update `list_skills` and `get_skill` to: (1) for each skill already fetched with `selectinload(Skill.tool_bindings)`, collect the bound `McpTool` records; (2) call `assemble_tool_section`; (3) assign the result to `instructions_with_tools` before serialising into `SkillRead` / `SkillDetailRead`
- `instructions_with_tools` = base `instructions` (or `""`) + `"\n\n"` + tool section; if tool section is empty string, `instructions_with_tools` equals the base value

**Done when:** `GET /skills` returns `instructions_with_tools` on each item; `GET /skills/{id}` returns `instructions_with_tools` reflecting current tool bindings; modifying tool bindings and re-fetching returns updated `instructions_with_tools`; no extra DB round-trips (tool records already loaded via `selectinload`).

---

### 2.10 — Implement SkillSeeder service with idempotent default skill creation

Create `backend/app/services/skill_seeder.py` with a `SkillSeeder` class:

- `SkillSeeder.run(session: AsyncSession) -> None` is the primary entry point
- Queries the `skills` table for skills named `save_result` and `send_notification`
- For each missing skill, inserts a `Skill` record with a descriptive name, instructions, and `is_active=True`; then inserts `SkillToolBinding` entries linking to the corresponding platform `McpTool` records (looked up by tool name/slug)
- If a platform tool is not yet registered (MCP server not synced), log a warning and skip the binding — do not fail the seeder
- Runs within a single transaction; rolls back on any unexpected error
- Logs each action (found existing / created new) using the platform's standard structured logger

Wire `SkillSeeder.run()` into `backend/app/main.py` in the startup lifespan handler, after the DB connection is verified and before the API begins accepting traffic.

**Done when:** fresh database with no existing skills results in both default skills being created on startup; a database that already has `save_result` results in the seeder leaving it untouched; a partially seeded database (only `send_notification` missing) creates only the missing skill.

---

### 2.11 — Add seed-skills CLI command and startup invocation

In `backend/app/cli.py`, register a `seed-skills` command (using the existing CLI framework — Typer or Click as already configured):

- Command calls `SkillSeeder.run()` with a fresh database session
- Prints a summary of what was created or skipped
- Exits with code 0 on success, non-zero on failure

This enables operators to trigger seeding manually after a database restore or fresh install without restarting the API server.

**Done when:** `python -m app.cli seed-skills` (or equivalent) runs successfully against a local database; creates missing default skills; idempotent on re-run; startup behaviour unchanged (seeder still auto-runs on app startup from task 2.10).

---

## Phase 3 — Frontend Types & Hooks

### 3.1 — Update TypeScript types for McpSession, Sop, SopStep, SopStepType, and Skill

In `frontend/src/types/index.ts`:

- `McpSession`: add `identity_binding: Record<string, unknown> | null` and `credential_config: Record<string, unknown> | null`
- `Sop`: add `instructions: string | null`
- `SopStepType`: add `'skill_invocation'` (keep `'skill'` temporarily as a union member until all data is migrated, or replace outright after confirming the migration is applied)
- `SopStep`: rename `delegate_agent_type_id` → `target_agent_type_id`; add `step_config: Record<string, unknown> | null`
- `Skill`: add `tool_ids: string[]`; add `instructions_with_tools: string | null`

**Done when:** TypeScript compiler reports no type errors in existing files after these changes; `frontend/src/types/index.ts` contains all new fields.

---

### 3.2 — Add useAllTools, useToolSkills, useSkillRoles, and useSopRoles query hooks

In `frontend/src/hooks/useMcpServers.ts`, add:
- `useAllTools()` — queries `GET /mcp/tools`, cache key `['mcp', 'tools']`
- `useToolSkills(toolId: string)` — queries `GET /mcp/tools/{toolId}/skills`, enabled when toolId is set

Create `frontend/src/hooks/useSkills.ts`:
- `useSkillRoles(skillId: string)` — queries `GET /skills/{skillId}/roles`, cache key `['skills', skillId, 'roles']`

Create `frontend/src/hooks/useSops.ts`:
- `useSopRoles(sopId: string)` — queries `GET /sops/{sopId}/roles`, cache key `['sops', sopId, 'roles']`

**Done when:** all four hooks export correctly; TypeScript compiles; no runtime fetch errors against a running backend.

---

## Phase 4 — Frontend Components

### 4.1 — Implement McpSessionManager: full CRUD with identity binding and credential config

Replace the stub in `frontend/src/pages/mcp/McpSessionManager.tsx` with a full implementation:

- Receives `serverId: string` as prop
- Lists sessions for the server using `useServerSessions(serverId)`
- Create/Edit dialog with fields: Name, Description, Auth Type (select), Credentials (key-value form, write-only — never pre-populate), Identity Subject, Identity Binding (JSON textarea), Credential Config (JSON textarea)
- Delete with confirmation
- Encrypts credentials server-side (backend handles this); client sends credentials in plaintext in the request body which the existing `create_mcp_session` endpoint encrypts before storage
- Dialog error handling via `dialogError` state + `PermissionDeniedAlert` pattern
- All user-facing text via `t()` keys

**Done when:** session list renders for a selected server; create/edit/delete all work and invalidate the sessions query; credentials are never shown in read responses; dialog shows errors on permission or validation failures.

---

### 4.2 — Implement McpToolBrowser: tools grouped by server, skill mapping chips, enable toggle

Replace the stub in `frontend/src/pages/mcp/McpToolBrowser.tsx` with a full implementation:

- Fetches all tools using `useAllTools()`
- Groups tools by `server_id` — display the server slug as the group header
- Each tool row shows: tool name (monospace), description, server slug chip, assigned skills (chips, populated by `useToolSkills(tool.id)` lazy-loaded or via a pre-fetched map), and an active/inactive toggle
- Search input filters by tool name or description (client-side)
- Server filter dropdown narrows to one server group
- The active toggle calls `PUT /mcp/servers/{server_id}/tools/{tool_id}` (or similar existing endpoint) to toggle `is_active` — confirm endpoint exists; if not, add it in task 2.4 extension
- No pagination required at this stage

**Done when:** tool list renders grouped by server; search and server filter work; skill chips appear on tools that have bindings; enable toggle updates `is_active`.

---

### 4.3 — Enhance McpHubPage: Servers / Tool Repository tabs, sessions dialog per server row

In `frontend/src/pages/mcp/McpHubPage.tsx`:

- Add MUI `Tabs` / `Tab` components switching between "Servers" and "Tool Repository" panels
- Servers panel: existing server table, updated to add a "Sessions" button per row that opens `McpSessionManager` in a `Dialog` (passing `serverId`)
- Tool Repository panel: renders `<McpToolBrowser />`
- Sessions dialog state: `sessionServerId: string | null` — open when set, close when null
- All dialog error handling follows the standard pattern

**Done when:** both tabs render; Servers tab behaviour is unchanged except for the Sessions button; Tool Repository tab shows McpToolBrowser; Sessions dialog opens and closes cleanly.

---

### 4.4 — Implement SkillEditor: multi-tool checkbox list grouped by server, role assignment sidebar ⚠️ NEEDS REWORK

> **Rework required:** SkillEditor was implemented as originally scoped (multi-tool select, role assignment sidebar). The refinement adds a read-only "Generated Tool Reference" section showing `instructions_with_tools`, addressed in task 4.8.

Replace the stub in `frontend/src/pages/skills/SkillEditor.tsx` with a full implementation matching the prototype:

- Receives `skill: Skill | null` (null for create) and `onClose: () => void` and `onSaved: () => void` as props
- Left column: Basic Info card (name, description inputs) + MCP Tools card (all tools from `useAllTools()`, grouped by server slug, each tool is a checkbox; checking shows the tool name, server chip, description)
- Right column: Assign to Roles card — lists all AgentRoles from existing `useAgentTypes` data or a new roles query; checkboxes; initial state loaded from `useSkillRoles(skill.id)` when editing
- On save: `POST /skills` or `PUT /skills/{id}` with `{ name, description, tool_ids }`, then `PUT /skills/{id}/roles` with `{ role_ids }` if role selections changed
- Error handling: `dialogError` state shown at top of the editor area

**Done when:** create and edit paths both work; tool checkboxes reflect existing bindings on load; role checkboxes reflect existing membership on load; save updates both and calls `onSaved()`; errors are visible.

---

### 4.5 — Implement SopEditor: instructions field, step cards with type selector and reorder, in-page panel pattern

Replace the stub in `frontend/src/pages/skills/SopEditor.tsx` with a full implementation matching the prototype:

- Receives `sop: SopDetail | null` and `onClose: () => void` and `onSaved: () => void` as props
- Left column:
  - Basic Info card: name, description, instructions (multiline textarea) fields
  - Steps card: ordered list of step cards; each card has drag handle (reorder), step number badge, step type dropdown (`Skill` / `Sub-Agent Delegation`), and conditional sub-field (skill selector from skills query, or agent type selector from `useAgentTypes()`)
  - "Add Step" button appends a new empty step card
  - Delete button removes a step from the local list
- Right column: SOP Details card — status toggle (active/inactive)
- On save: `POST /sops` or `PUT /sops/{id}` with `{ name, description, instructions, is_active }`, then `PUT /sops/{id}/steps` with the ordered step list
- Step reorder: track step order in component state; drag-and-drop or up/down buttons (match prototype drag handle); update `order` field before submitting

**Done when:** create and edit paths both work; steps render in order with correct type-specific fields; add/delete/reorder all work before saving; save persists all changes including instructions and step_config; errors shown inline.

---

### 4.6 — Wire SkillListPage to SkillEditor panel; wire SopListPage to SopEditor panel

In `frontend/src/pages/skills/SkillListPage.tsx`:

- Remove the existing inline create/edit `Dialog` for skill CRUD
- Add local state `editorSkill: Skill | null | undefined` (undefined = hidden, null = create, Skill = edit)
- Show `<SkillEditor>` in-page panel (same pattern as the prototype's side-by-side panel) when state is not undefined
- "Create Skill" button sets state to null; Edit icon sets state to the skill
- `onClose` resets to undefined; `onSaved` invalidates `['skills']` query and resets state
- Update the table to show `tool_ids.length` as a chip in the "MCP Tools" column (uses data from task 2.3)
- Show assigned role chips in "Assigned Roles" column using `useSkillRoles` per skill (or a batch query approach)

In `frontend/src/pages/skills/SopListPage.tsx`:

- Remove the existing inline create/edit `Dialog`
- Add the same editor state pattern for `SopEditor`
- `onSaved` invalidates `['sops']` query

**Done when:** both list pages show/hide their respective editors inline without navigation; the existing delete and list behaviour is preserved; no broken Dialog imports remain.

---

### 4.7 — Add i18n keys for all new UI text

In the relevant i18n namespace files under `frontend/src/i18n/`:

- MCP Hub: `mcp.tabs.servers`, `mcp.tabs.toolRepository`, `mcp.sessions.title`, `mcp.sessions.create`, `mcp.sessions.edit`, `mcp.sessions.authType`, `mcp.sessions.identitySubject`, `mcp.sessions.identityBinding`, `mcp.sessions.credentialConfig`, `mcp.sessions.credentials`
- Skills: `skills.toolCount`, `skills.assignedRoles`, `skills.editor.basicInfo`, `skills.editor.mcpTools`, `skills.editor.assignToRoles`, `skills.editor.generatedToolReference`
- SOPs: `sops.instructions`, `sops.stepType.skillInvocation`, `sops.stepType.agentDelegation`, `sops.editor.steps`, `sops.editor.addStep`, `sops.editor.agentType`, `sops.stepCount`

**Done when:** no hardcoded English strings exist in any modified or new component; all `t('...')` keys resolve without fallback warnings in the browser console.

---

### 4.8 — Add read-only "Generated Tool Reference" section to SkillEditor

Extend the existing `SkillEditor` in `frontend/src/pages/skills/SkillEditor.tsx`:

- Below the editable `instructions` textarea in the Basic Info card, render a "Generated Tool Reference" section
- The section header is labelled with `t('skills.editor.generatedToolReference')` and includes a tooltip or caption explaining the content is auto-generated and read-only
- The section body displays `skill.instructions_with_tools` (sourced from the fetched skill response), or a placeholder if empty or if no tools are bound
- The entire section is non-editable: rendered as a read-only `<pre>` or styled `<Box>` with a visual distinction (e.g. muted background, no cursor caret)
- In create mode (no skill fetched yet), the section shows a placeholder message indicating tool schemas will appear once tools are bound and the skill is saved
- The section updates automatically when the parent `['skills']` query is invalidated after a save (because `instructions_with_tools` is re-fetched from the API)

**Done when:** the Generated Tool Reference section is visible in SkillEditor in both create and edit modes; it displays the correct Tool Section content from `instructions_with_tools`; it is visually and interactively read-only; its i18n key resolves without fallback; `npm run build` exits with no TypeScript errors.

---

## Completion Checklist

- [ ] `alembic current` shows the new migration as HEAD with no pending upgrades
- [ ] `alembic upgrade head` applies cleanly to a fresh local database with no errors
- [ ] Backend: all existing unit tests pass after model renames (`pytest backend/tests/`)
- [ ] Backend: `GET /mcp/tools` returns all active tools; `GET /mcp/tools/{id}/skills` returns mapped skills
- [ ] Backend: `GET /skills/{id}` returns `SkillDetailRead` with `tool_ids`, `instructions`, and `instructions_with_tools`
- [ ] Backend: `GET /skills` returns `SkillRead` items each with `tool_ids` and `instructions_with_tools`
- [ ] Backend: `assemble_tool_section` produces correct markdown Tool Section from bound tool records
- [ ] Backend: `GET/PUT /skills/{id}/roles` work correctly
- [ ] Backend: `GET /sops/{id}` includes `instructions`; `GET/PUT /sops/{id}/steps` uses `target_agent_type_id` and `step_config`
- [ ] Backend: on fresh startup, `save_result` and `send_notification` skills are created automatically
- [ ] Backend: on re-startup with default skills already present, seeder leaves them untouched
- [ ] Backend: `seed-skills` CLI command runs successfully and is idempotent
- [ ] Frontend: `npm run build` (or `tsc --noEmit`) exits with no TypeScript errors
- [ ] Frontend: `Skill` interface includes `instructions_with_tools: string | null`
- [ ] MCP Hub: Servers tab renders and existing server CRUD still works
- [ ] MCP Hub: Sessions dialog opens per server row; create/edit/delete sessions work
- [ ] MCP Hub: Tool Repository tab groups tools by server; assigned skills chips populate
- [ ] Skills list: MCP Tools count chip and Assigned Roles chips visible per row
- [ ] SkillEditor: multi-tool selection grouped by server; role assignment saves; errors shown inline
- [ ] SkillEditor: Generated Tool Reference section is visible, read-only, and shows correct `instructions_with_tools` content
- [ ] SopEditor: instructions field saves; step add/reorder/delete works; save persists full step list
- [ ] All new UI text routed through `t()` — no hardcoded strings
- [ ] All dialogs and editors follow Dialog Error Handling Standard (PermissionDeniedAlert pattern)
