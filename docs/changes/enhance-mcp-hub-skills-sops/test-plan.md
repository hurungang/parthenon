# Test Plan: enhance-mcp-hub-skills-sops

---

## 1. Test Strategy

This change has **database schema changes** (`has_db_changes: true`) and requires all three test layers to pass before the change can be considered complete.

| Layer | Framework | Scope |
|-------|-----------|-------|
| Backend unit/API | pytest | New endpoints, modified endpoints, schema serialisation, credential exclusion, `instructions_with_tools` assembly, default skill seeding |
| Backend integration | pytest + real DB | Schema migration verification, constraint enforcement, atomic operations, seeding idempotency |
| Frontend component | Vitest + React Testing Library | New components (McpSessionManager, McpToolBrowser, SkillEditor, SopEditor), hook behaviour, Generated Tool Reference section |
| E2E (mocked) | Playwright | Full user flows for MCP Hub tabs, Skill editor, SOP editor, Generated Tool Reference section, default skills presence |
| E2E (real backend) | Playwright | At least one test per domain area that hits the running backend to catch migration issues |

**Database change pre-test checklist** (must be confirmed before running any tests):
- Alembic migration was generated and committed
- `alembic upgrade head` applied locally — verify with `alembic current`
- Test database fixture applies migrations via `alembic upgrade head` in setup

---

## 2. Coverage Areas

### 2.1 Database Schema — Migration Correctness

Critical because: schema rename (`delegate_agent_type_id` → `target_agent_type_id`) and enum rename (`skill` → `skill_invocation`) are silent at runtime if migration is not applied; old field names silently return `None`.

- `McpSession.identity_binding` column exists and accepts JSON
- `McpSession.credential_config` column exists and accepts JSON
- `Sop.instructions` column exists, is nullable (Text)
- `SopStep.target_agent_type_id` column exists (renamed from `delegate_agent_type_id`)
- `SopStep.step_config` column exists and accepts JSON
- `SopStepType.skill_invocation` enum value is valid (renamed from `skill`)
- Old enum value `skill` is NOT valid after migration

### 2.2 MCP Session API — New Fields

- `POST /mcp/servers/{id}/sessions` accepts and stores `identity_binding`, `credential_config`
- `PUT /mcp/servers/{id}/sessions/{id}` accepts and stores updated values
- `GET /mcp/servers/{id}/sessions` response includes `identity_binding`, `credential_config`
- `GET /mcp/servers/{id}/sessions/{id}` response includes both new fields
- `encrypted_credentials` is **never** present in any session response

### 2.3 New Tool Repository Endpoints

- `GET /mcp/tools` returns all active tools across all servers, ordered by server name then tool name
- `GET /mcp/tools` returns empty list when no active tools exist
- `GET /mcp/tools/{tool_id}/skills` returns all skills bound to the given tool
- `GET /mcp/tools/{tool_id}/skills` returns empty list for tool with no skill bindings
- Both endpoints require authentication; unauthenticated requests are rejected (401/403)

### 2.4 Skill Instructions and Role Membership Endpoints

- `POST /skills` and `PUT /skills/{id}` accept `instructions` field (nullable string)
- `GET /skills/{id}` response includes `instructions` with the persisted value
- `GET /skills/{skill_id}/roles` returns role IDs that include the skill
- `PUT /skills/{skill_id}/roles` atomically replaces role membership (remove all, add provided list)
- `PUT /skills/{skill_id}/roles` with empty `role_ids` removes all role memberships
- `GET /skills` and `GET /skills/{id}` responses include `tool_ids` array

### 2.5 SOP Endpoints — Instructions and Role Membership

- `POST /sops` and `PUT /sops/{id}` accept `instructions` field
- `GET /sops/{id}` response includes `instructions`
- `PUT /sops/{id}/steps` uses `target_agent_type_id` (not `delegate_agent_type_id`) in request and response
- `PUT /sops/{id}/steps` uses `step_config` in request and response
- `GET /sops/{sop_id}/roles` and `PUT /sops/{sop_id}/roles` behave symmetrically to skill role endpoints
- Default `step_type` is `skill_invocation` when not provided

### 2.6 Skill API — `instructions_with_tools` Field

These scenarios cover the new requirement that tool schemas and usage descriptions are automatically appended to agent instructions.

- `GET /skills/{id}` response includes an `instructions_with_tools` field
- When a skill has tool bindings, `instructions_with_tools` equals the user-provided `instructions` concatenated with an auto-generated Tool Section derived from the MCP tool registry
- When a skill has no tool bindings, `instructions_with_tools` equals `instructions` (no Tool Section appended), or is null if `instructions` is also null
- `instructions_with_tools` is **read-only**: `POST /skills` and `PUT /skills/{id}` ignore any `instructions_with_tools` field in the request body
- `GET /skills` (list) includes `instructions_with_tools` for each skill in the response
- After `PUT /skills/{id}` updates the tool bindings, a subsequent `GET /skills/{id}` returns an updated `instructions_with_tools` reflecting the new tool set
- After `PUT /skills/{id}` updates the `instructions` text, `instructions_with_tools` reflects the new text with the same Tool Section appended

### 2.7 Tool Schema Assembly Logic

These scenarios validate the content and structure of the auto-generated Tool Section.

- The Tool Section includes each bound tool's name, usage description, and JSON input schema
- The Tool Section format is consistent across responses (same heading, delimiter, and structure)
- When multiple tools are bound to a skill, all tools appear in the Tool Section (no omissions)
- Tools are listed in a deterministic order within the Tool Section (e.g., by server name then tool name)
- When a tool's description or schema is updated in the MCP tool registry, the next `GET /skills/{id}` call returns the updated information in `instructions_with_tools`
- When a tool has an empty description in the registry, the Tool Section entry for that tool has an empty description rather than causing an error
- When a tool has no input schema in the registry, the Tool Section entry omits the schema block rather than causing an error or rendering `null`

### 2.8 Default Skills Seeding

These scenarios cover the requirement that `save_result` and `send_notification` skills exist after platform installation.

- After the installation seed command runs on a clean database, a skill named `save_result` is present in the database
- After the installation seed command runs on a clean database, a skill named `send_notification` is present in the database
- `GET /skills` returns both default skills after seeding
- Running the seed command a second time on a database that already contains both default skills does **not** create duplicates (idempotent — count remains the same)
- Default skills have expected name, description, and initial configuration (tool bindings may be empty on first install)
- Default skills are mutable: a user with appropriate permissions can update a default skill's `instructions` field, and the change is persisted
- Default skills do not block installation if the database already contains skills with conflicting names — they are upserted, not blindly inserted

### 2.9 Frontend — McpHubPage Tabs

- Servers tab and Tool Repository tab are present and switchable
- Sessions dialog is accessible from a server row action
- Switching tabs does not cause runtime errors

### 2.10 Frontend — McpSessionManager CRUD

- Full session CRUD lifecycle: create, read in list, update, delete
- Parent server list (McpHubPage) does not require page reload after session changes
- New fields (`identity_binding`, `credential_config`) are editable in the session form
- Credential field is write-only — existing value is not pre-populated in edit form
- Dialog error handling: API errors (403, 422, 500) are shown in the dialog, not silently swallowed

### 2.11 Frontend — McpToolBrowser

- All active tools displayed, grouped by server
- Search filters tools by name in real time (client-side)
- Server filter dropdown narrows tool list to selected server
- Each tool shows which skills are assigned to it (skill chips)
- Active-only toggle works correctly

### 2.12 Frontend — SkillEditor CRUD

- Full skill CRUD lifecycle via in-page editor panel
- Tool bindings multi-select shows tools grouped by server with server-slug namespace prefix
- Assigned roles sidebar shows current role membership
- Role assignment changes are saved with `PUT /skills/{id}/roles`
- SkillListPage parent table refreshes after create/edit/delete without page reload
- `tool_ids` count displayed on each row in SkillListPage

### 2.13 Frontend — SkillEditor Generated Tool Reference Section

These scenarios cover the read-only Tool Section rendered below the instructions field in the skill editor.

- When tools are selected in SkillEditor, a "Generated Tool Reference" section is visible below the instructions input
- The Generated Tool Reference section is rendered as read-only; the user cannot type in or modify it directly
- The section displays each selected tool's name, description, and schema
- When a tool is added to the selection, the section updates to include the new tool (reactive, no save required)
- When a tool is removed from the selection, the section updates to exclude that tool
- When no tools are selected, the Generated Tool Reference section is either hidden or shows an empty-state message (no error, no stale content)
- The section is visually distinct from the editable instructions field (e.g., different background, label, or styling)
- The section content matches the `instructions_with_tools` value returned by the API after saving

### 2.14 Frontend — SopEditor CRUD

- Full SOP CRUD lifecycle via in-page editor panel
- `instructions` field present in Basic Info form and persisted on save
- SOP steps support ordered management: add, reorder (drag), remove
- Step type selector shows `skill_invocation` and `agent_delegation` options
- `target_agent_type_id` and `step_config` are submitted for each step
- Role assignment sidebar for SOP is functional
- SopListPage parent table refreshes after create/edit/delete without page reload

---

## 3. Critical Scenarios

### 3.1 Database Migration Verification

**WHEN** the Alembic migration is applied to a clean database  
**THEN** `information_schema.columns` shows `identity_binding`, `credential_config` on `mcp_session`; `instructions` on `sop`; `target_agent_type_id` and `step_config` on `sop_step`

**WHEN** a `SopStep` is created with `step_type = 'skill_invocation'`  
**THEN** the record is persisted and returned with `step_type = 'skill_invocation'`

**WHEN** a `SopStep` is created with the legacy `step_type = 'skill'`  
**THEN** the database rejects it (enum violation)

**WHEN** a `Sop` is created without `instructions`  
**THEN** it is accepted (column is nullable) and `instructions` is `null` in the response

**WHEN** a `SopStep` is created without `target_agent_type_id`  
**THEN** it is accepted (column is nullable) and `target_agent_type_id` is `null` in the response

### 3.2 Credential Security

**WHEN** a session is created with a plaintext credential  
**THEN** the response body does not contain the credential value in any field

**WHEN** the session list is fetched  
**THEN** `encrypted_credentials` is absent from every session object in the response

**WHEN** a session is updated with a new credential  
**THEN** the old credential is replaced; the new credential is never returned in the response

### 3.3 Tool Repository

**WHEN** `GET /mcp/tools` is called  
**THEN** tools from all active servers are returned ordered by server name then tool name

**WHEN** a tool with no skill bindings is queried at `GET /mcp/tools/{id}/skills`  
**THEN** an empty array is returned (not 404)

**WHEN** `McpToolBrowser` is rendered with tools from two servers  
**THEN** tools are visually grouped under their respective server headings

### 3.4 Atomic Role Replacement

**WHEN** `PUT /skills/{id}/roles` is called with a new list of role IDs  
**THEN** the previous role memberships are fully replaced — no partial state exists

**WHEN** `PUT /skills/{id}/roles` is called with `{"role_ids": []}`  
**THEN** the skill has zero role memberships after the call

**WHEN** `PUT /sops/{id}/roles` is called with `{"role_ids": []}`  
**THEN** the SOP has zero role memberships after the call

### 3.5 Parent Table Refresh

**WHEN** a new session is created via McpSessionManager dialog  
**THEN** the session appears in the session list without a page reload

**WHEN** a skill is created via SkillEditor  
**THEN** the new skill row appears in SkillListPage without a page reload

**WHEN** a SOP is deleted via SopEditor  
**THEN** the SOP row disappears from SopListPage without a page reload

**WHEN** a skill's tool bindings are updated  
**THEN** the `tool_ids` count badge on the SkillListPage row updates immediately

### 3.6 SkillEditor Tool Binding

**WHEN** SkillEditor is opened to create a new skill  
**THEN** available MCP tools are grouped by server with namespace prefixes shown

**WHEN** multiple tools are selected and the skill is saved  
**THEN** `GET /skills/{id}` returns `tool_ids` containing exactly those tool IDs

**WHEN** `instructions` is provided in the Skill form  
**THEN** `GET /skills/{id}` returns the exact text in the `instructions` field

**WHEN** a skill is created without `instructions`  
**THEN** it is accepted (column is nullable) and `instructions` is `null` in the response

### 3.7 SopEditor Step Management

**WHEN** a SOP step is added with `step_type = 'skill_invocation'`  
**THEN** `PUT /sops/{id}/steps` sends `target_agent_type_id` (not `delegate_agent_type_id`)

**WHEN** steps are reordered in SopEditor and saved  
**THEN** the new order is reflected in `GET /sops/{id}` step list

**WHEN** `instructions` is provided in the SOP form  
**THEN** `GET /sops/{id}` returns the exact text in the `instructions` field

### 3.8 Error Handling

**WHEN** session creation fails with 403 (insufficient permission)  
**THEN** the error is displayed inside the McpSessionManager dialog — not a silent failure

**WHEN** skill save fails with 422 (validation error)  
**THEN** the SkillEditor panel shows the error message

### 3.9 Tool Schema Auto-Attachment (`instructions_with_tools`)

**WHEN** a skill has tools A and B bound and user has written instructions text  
**THEN** `GET /skills/{id}` returns `instructions_with_tools` containing both the user instructions and a Tool Section with schemas for tools A and B

**WHEN** a skill has tools bound but `instructions` is null  
**THEN** `GET /skills/{id}` returns `instructions_with_tools` containing only the Tool Section (no null-prefix artefact)

**WHEN** a skill's tool bindings are changed from {A, B} to {A} and saved  
**THEN** `GET /skills/{id}` returns `instructions_with_tools` containing only tool A's schema (tool B no longer present)

**WHEN** a skill has no tool bindings  
**THEN** `instructions_with_tools` equals `instructions` (no Tool Section appended) or is null if `instructions` is also null

**WHEN** a request to `PUT /skills/{id}` includes an `instructions_with_tools` field in the body  
**THEN** the field is ignored and the value in the response is still server-computed

**WHEN** a tool referenced by a skill has no description in the registry  
**THEN** `GET /skills/{id}` succeeds (2xx); the tool appears in the Tool Section with an empty description rather than an error

### 3.10 Default Skills Seeding and Idempotency

**WHEN** the installation seed command is run against a clean database  
**THEN** `GET /skills` returns at least two skills: one named `save_result` and one named `send_notification`

**WHEN** the installation seed command is run a second time against a database that already contains both default skills  
**THEN** `GET /skills` still returns exactly one skill named `save_result` and one named `send_notification` (no duplicates)

**WHEN** a user updates the `instructions` field of the `save_result` skill  
**THEN** the updated value is persisted and returned on subsequent `GET /skills/{id}` calls (default skills are mutable)

**WHEN** the installation seed is run after a user has already modified a default skill  
**THEN** the user's modifications are preserved (seed does not overwrite existing records)

### 3.11 Generated Tool Reference Section in SkillEditor

**WHEN** SkillEditor is open with no tools selected  
**THEN** the Generated Tool Reference section is either hidden or shows an empty-state placeholder — no stale content from a previously selected tool

**WHEN** the user selects a tool in the SkillEditor tool binding control  
**THEN** the Generated Tool Reference section appears and shows that tool's description and schema without requiring a save

**WHEN** the user removes a tool from the selection  
**THEN** the Generated Tool Reference section updates immediately to exclude the removed tool

**WHEN** a skill is opened for editing and already has tool bindings  
**THEN** the Generated Tool Reference section is pre-populated with the current tools' schemas on initial render

**WHEN** the user attempts to type in the Generated Tool Reference section  
**THEN** the input is blocked (the section is read-only)

---

## 4. Edge Cases & Risks

| Risk | Why It Matters | Mitigations |
|------|---------------|-------------|
| Migration not applied | `target_agent_type_id` returns `None`; `skill_invocation` enum unknown; all renamed fields silently broken | Backend integration test queries `information_schema`; real-backend E2E test confirms API returns correct fields |
| `encrypted_credentials` leaks in response | Security violation — AES key exposed | Explicit assertion in every session-read test that the field is absent |
| Partial role replacement | Bug in atomic delete-then-insert leaves stale memberships | Integration test verifies exact post-operation membership; tests for concurrent calls |
| N+1 query on `tool_ids` | `list_skills` without `selectinload` causes O(n) queries | Backend API test verifies `tool_ids` is populated for all skills in a single response |
| SOP step field name mismatch | Frontend sends `delegate_agent_type_id`, backend rejects or silently ignores it | E2E test round-trips a step through create→read and asserts `target_agent_type_id` is present |
| Parent table stale after dialog close | Users see outdated data without reload; existing issue pattern in this codebase | Dedicated parent-table-refresh tests for each CRUD operation on each component |
| Enum rename breaks existing data | Records written with `skill` step_type unreadable after migration | Integration test verifies existing data migrated or migration includes data transformation |
| Credential loss on update | Update without providing credential field should NOT overwrite existing encrypted credential with null | API test: create session with credential, update only `name`, verify session still functions |
| Tool search client-side filtering | Empty result when search term doesn't match tool name formats (slug vs display name) | Frontend component test verifies search against display name and slug |
| `instructions_with_tools` stale after tool change | Agent receives outdated tool schema if the field is cached rather than recomputed on read | API test: update tool bindings, immediately fetch skill, assert Tool Section reflects new bindings |
| Tool Section injected into editable `instructions` field | User could accidentally edit or lose the Tool Section separator on re-save if the boundary is not enforced server-side | API test verifies `instructions_with_tools` is always server-computed regardless of what the client submits |
| Default skill duplicate on concurrent installs | Two parallel installation processes both attempt to insert default skills, causing constraint errors | Seed uses upsert (INSERT … ON CONFLICT DO NOTHING or equivalent); integration test confirms no error on double-seed |
| Default skill overwrites user edits on reinstall | Re-running the seed after a user has customised a default skill resets their work | Seed must use `ON CONFLICT DO NOTHING` (not `DO UPDATE`); integration test verifies custom instructions survive re-seed |
| Generated Tool Reference section flicker | Section briefly shows stale content when tool selection changes before re-render completes | Frontend component test asserts section content matches exactly the currently selected tool set after each change |

---

## 5. Acceptance Criteria Checklist

Maps directly to PRD Acceptance Criteria.

### MCP Hub
- [ ] User can create, view, edit, and delete MCP sessions with `identity_binding` and `credential_config` fields
- [ ] Session credentials are write-only — never shown in plaintext in any response or UI field
- [ ] Created, updated, or deleted sessions are immediately visible in session list after saving (no page reload)
- [ ] Tool Repository tab shows all active tools from all servers, grouped by server
- [ ] Each tool shows which skills are bound to it (tool-to-skill mapping visible in UI)
- [ ] Validation and permission errors are clearly shown inside dialogs (not silent failures)

### Skills
- [ ] User can create, view, edit, and delete skills with multiple tool bindings
- [ ] `tool_ids` count is visible on each skill row in the list
- [ ] Skills list and detail response includes `tool_ids` array
- [ ] User can assign roles to a skill and see current role assignments
- [ ] Skill list parent table refreshes immediately after create/edit/delete
- [ ] Tool namespace (server slug prefix) is visible when selecting tools in SkillEditor
- [ ] `GET /skills/{id}` response includes `instructions_with_tools` field
- [ ] `instructions_with_tools` contains the user-authored instructions combined with an auto-generated Tool Section of selected tools' schemas and usage descriptions
- [ ] `instructions_with_tools` is always server-computed and cannot be overridden by the client
- [ ] `instructions_with_tools` updates automatically when tool bindings are changed
- [ ] SkillEditor shows a read-only "Generated Tool Reference" section when tools are selected
- [ ] The Generated Tool Reference section updates reactively when tool selection changes (no save required)
- [ ] The Generated Tool Reference section cannot be edited directly by the user

### SOPs
- [ ] User can create, view, edit, and delete SOPs with `instructions` field
- [ ] SOP editor supports ordered step management with `skill_invocation` and `agent_delegation` step types
- [ ] Step data round-trips correctly using `target_agent_type_id` and `step_config`
- [ ] User can assign roles to a SOP and see current role assignments
- [ ] SOP list parent table refreshes immediately after create/edit/delete

### Default Skills
- [ ] `save_result` skill exists in the skills list after platform installation seed runs
- [ ] `send_notification` skill exists in the skills list after platform installation seed runs
- [ ] Installation seed is idempotent — running it a second time does not create duplicate default skills
- [ ] Default skills can be updated by users (mutable after installation)
- [ ] Re-running the seed after a user has modified a default skill does not overwrite user's changes

### Cross-Cutting
- [ ] All new endpoints require authentication (401 for unauthenticated, 403 for unauthorised)
- [ ] Database migration applies cleanly: `alembic upgrade head` succeeds on clean schema
- [ ] Migration is reversible: `alembic downgrade -1` succeeds without data errors

---

## 6. Test File References

### Backend — API Tests (updated files)

| File | What It Covers |
|------|---------------|
| `backend/tests/api/v1/test_mcp_hub_api.py` | `GET /mcp/tools`, `GET /mcp/tools/{id}/skills`, session create/update/read with new fields, credential exclusion |
| `backend/tests/api/v1/test_skills_api.py` | `POST/PUT /skills` with `instructions` field; `GET /skills/{id}` returns `instructions`, `tool_ids`, and `instructions_with_tools`; `instructions_with_tools` content and structure; read-only enforcement; update propagation after tool binding change; `GET/PUT /skills/{id}/roles` |
| `backend/tests/api/v1/test_sops_api.py` | `POST/PUT /sops` with `instructions`, `PUT /sops/{id}/steps` with renamed fields and default step type, `GET/PUT /sops/{id}/roles` |

### Backend — Unit Tests (new file)

| File | What It Covers |
|------|---------------|
| `backend/tests/unit/test_skill_tool_section_builder.py` | Tool Section assembly: correct format and delimiter; all bound tools included; deterministic ordering; graceful handling of tools with no description; graceful handling of tools with no input schema; multi-tool output structure |

### Backend — Integration Tests (updated file)

| File | What It Covers |
|------|---------------|
| `backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py` | Schema migration verification via `information_schema` queries; `skill_invocation` enum validity; `skill` enum rejection; nullable field acceptance; `target_agent_type_id` presence; `Skill.instructions` field persistence; credential-not-returned integration path; atomic role replacement correctness; **default skills seeding: both skills present after seed**; **default skills idempotency: double-seed produces no duplicates**; **user modification of default skill survives re-seed** |

### Frontend — Component Tests (new / updated files)

> **Note:** Full Vitest component tests for `SkillEditor` and `SopEditor` were skipped in the prior iteration due to a Vitest mocking infrastructure issue (MSW/React Query context interaction in the test environment). This iteration adds targeted tests for the Generated Tool Reference section using a lightweight stub approach that avoids the MSW dependency.

| File | What It Covers | Status |
|------|---------------|--------|
| `frontend/src/__tests__/McpSessionManager.test.tsx` | Session CRUD rendering, new field inputs, write-only credential field, dialog error display | Implemented (prior iteration) |
| `frontend/src/__tests__/McpToolBrowser.test.tsx` | Tool list rendering grouped by server, search filtering, server filter, skill chips | Implemented (prior iteration) |
| `frontend/src/__tests__/SkillEditor.test.tsx` | Instructions field rendering and persistence; tool selection grouped by server with namespace prefix; role assignment sidebar; **Generated Tool Reference section present when tools selected**; **section hidden/empty when no tools selected**; **section updates reactively on tool add/remove**; **section is read-only** | New (Generated Tool Reference scenarios added) |
| `frontend/src/__tests__/SopEditor.test.tsx` | Instructions field, step add/reorder/remove, step type selector, `target_agent_type_id` in submission, role assignment | Skipped — mocking infrastructure issue (unchanged from prior iteration) |

### Frontend — Component Tests (updates to existing files)

| File | What It Covers |
|------|---------------|
| `frontend/src/__tests__/McpHubPage.test.tsx` | Tab navigation (Servers / Tool Repository), session dialog trigger from server row |

### E2E Tests (updates to existing files)

| File | What It Covers |
|------|---------------|
| `e2e/tests/mcp-hub.spec.ts` | Full McpSessionManager CRUD flow (mocked), Tool Repository tab with tool grouping and search (mocked), parent table refresh after session operations |
| `e2e/tests/skills-sops.spec.ts` | SkillEditor with tool binding and role assignment (mocked); SopEditor with instructions and steps (mocked); parent table refresh for both; `target_agent_type_id` round-trip; **Generated Tool Reference section appears when tools selected**; **section clears when tools deselected**; **section content matches selected tool schemas**; **default skills (`save_result`, `send_notification`) visible in skills list after first navigation** |

### E2E Tests — Real Backend (new describe blocks within existing files)

| Location | What It Covers |
|----------|---------------|
| `e2e/tests/mcp-hub.spec.ts` — `test.describe('Real Backend Integration - MCP Sessions')` | Creates a real session via API, verifies `identity_binding` and `credential_config` returned, confirms `encrypted_credentials` absent |
| `e2e/tests/skills-sops.spec.ts` — `test.describe('Real Backend Integration - Skills and SOPs')` | Creates a real skill with tool bindings; verifies `tool_ids` and `instructions_with_tools` in response (Tool Section present and non-empty); creates a real SOP with `instructions` and steps using `target_agent_type_id`; verifies round-trip |
| `e2e/tests/skills-sops.spec.ts` — `test.describe('Real Backend Integration - Default Skills')` | Calls `GET /skills` against the running backend and asserts that skills named `save_result` and `send_notification` are present; verifies each has a non-null `name` and is returned in the list |
