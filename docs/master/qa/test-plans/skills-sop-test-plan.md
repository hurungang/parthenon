# Skill & SOP Engine Test Plan

## What to Test

### Skills — API
- Single-tool and multi-tool skill creation and execution
- `POST /skills` and `PUT /skills/{id}` accept `instructions` field (nullable string)
- `GET /skills/{id}` response includes `instructions` with persisted value
- `GET /skills` and `GET /skills/{id}` responses include `tool_ids` array (no N+1 query)
- `GET /skills/{skill_id}/roles` returns role IDs that include the skill
- `PUT /skills/{skill_id}/roles` atomically replaces all role memberships
- `PUT /skills/{skill_id}/roles` with empty `role_ids` removes all memberships
- Permission enforcement on skill endpoints (`skill:read`, `skill:create`, `skill:update`, `skill:delete`)
- 403 structured error responses with resource type, action, and resource ID

### Skills — Frontend (SkillEditor)
- Full skill CRUD lifecycle via in-page editor panel
- `instructions` field present and persisted on save
- Tool bindings multi-select grouped by server with server-slug namespace prefix
- `tool_ids` count visible on each row in SkillListPage
- Assigned roles sidebar shows current role membership
- Role assignment changes saved via `PUT /skills/{id}/roles`
- SkillListPage parent table refreshes after create/edit/delete without page reload
- SkillEditor form errors displayed inline on 422 validation failure

### SOPs — API
- SOP sequencing and step management
- `POST /sops` and `PUT /sops/{id}` accept `instructions` field (nullable string)
- `GET /sops/{id}` response includes `instructions`
- `PUT /sops/{id}/steps` uses `target_agent_type_id` (not legacy `delegate_agent_type_id`) in request and response
- `PUT /sops/{id}/steps` uses `step_config` in request and response
- Default `step_type` is `skill_invocation` when not provided
- `GET /sops/{sop_id}/roles` and `PUT /sops/{sop_id}/roles` behave symmetrically to skill role endpoints
- Agent delegation and context passing
- Allowed A2A target agent type slugs are derived from `agent_delegation` steps on SOP save/update
- Permission enforcement on SOP endpoints

### SOPs — Frontend (SopEditor)
- Full SOP CRUD lifecycle via in-page editor panel
- `instructions` field present in Basic Info form and persisted on save
- Step ordered management: add, reorder (drag), remove
- Step type selector shows `skill_invocation` and `agent_delegation` options
- `target_agent_type_id` and `step_config` submitted for each step
- Role assignment sidebar functional
- SopListPage parent table refreshes after create/edit/delete without page reload

### Cross-Cutting
- Atomic role replacement: `PUT /{resource}/{id}/roles` fully replaces previous memberships — no partial state
- All new endpoints require authentication; unauthenticated requests rejected (401/403)

### AI-Assisted Workflow Authoring (ai-assisted-workflow-authoring-for-sop-and-skill)
- Skill and SOP create/edit/view surfaces use workflow terminology consistently (no legacy system instruction wording in authoring surfaces)
- Skill workflow generation uses current description plus selected tools context
- SOP workflow generation uses current description plus ordered step context, including delegation steps
- Skill and SOP preview render a single formatted instruction file and include configured model metadata in preview headers
- Generate and preview actions reflect latest in-memory edits and selections without requiring save or page reload
- Missing model configuration blocks generate and preview with user-visible error (no fallback model)
- Existing authorization model is enforced for workflow generation and preview endpoints
- Responses from generation and preview endpoints exclude identity tokens, database credentials, and internal secret material

## Critical Scenarios
- Skill composes two tool calls
- SOP step delegates to a second agent type
- SOP with delegation steps produces derived allowed target slug set used by A2A permission checks
- SOP without delegation for a target slug denies A2A request to that slug
- `instructions` provided in skill form — `GET /skills/{id}` returns exact text
- `instructions` omitted — accepted (column is nullable), returns `null`
- `PUT /skills/{id}/roles` with new list — all previous memberships replaced, none remaining
- `PUT /skills/{id}/roles` with `{"role_ids": []}` — skill has zero role memberships after call
- `PUT /sops/{id}/roles` with `{"role_ids": []}` — SOP has zero role memberships after call
- SOP step submitted with `step_type = 'skill_invocation'` — stored and returned with `target_agent_type_id` (not `delegate_agent_type_id`)
- Steps reordered in SopEditor and saved — new order reflected in `GET /sops/{id}` step list
- SkillListPage shows updated `tool_ids` count badge immediately after skill save (no page reload)
- SopListPage shows deleted SOP removed immediately (no page reload)
- Skill create/edit/view uses workflow label and no legacy system instruction wording
- SOP create/edit/view uses workflow label and no legacy system instruction wording
- Skill generate inserts editable workflow text from current description and selected tools
- SOP generate inserts editable workflow text from current description and ordered steps
- Skill preview renders single instruction file from latest unsaved editor state
- SOP preview renders single instruction file from latest unsaved editor state, including delegation context
- Missing workflow generation model configuration returns user-visible error with no fallback model
- User without `skill:read` receives 403 on `GET /api/v1/skills`; UI shows permission-denied message
- User without `skill:create` receives 403 on `POST /api/v1/skills`; snackbar pre-filled with resource context
- User with correct permissions completes full Skill CRUD flow

## Edge Cases
- First tool succeeds, second fails (partial state)
- Circular agent delegation
- Delegated agent exceeds instance limit
- Permission revoked mid-SOP execution
- Skill created without `instructions` — nullable, returns `null` (not error)
- `SopStep` created without `target_agent_type_id` — nullable, accepted
- Tool search in SkillEditor matches display name and namespace-prefixed slug

## Known Limitations
- Full Vitest component tests for `SkillEditor` and `SopEditor` were not implemented due to a Vitest/MSW mocking infrastructure issue. Lightweight workaround files (`SkillEditor.simple.test.tsx`, `SopEditor.simple.test.tsx`) cover core rendering assertions. Full CRUD coverage is provided by E2E tests.

## Test File References

### Backend
- `backend/tests/unit/test_skill_executor.py` — skill execution logic, multi-tool composition
- `backend/tests/unit/test_skill_sop.py` — SOP step sequencing, agent delegation
- `backend/tests/unit/test_permission_manager.py` — delegation-step-derived allowed agent type slug resolution
- `backend/tests/api/v1/test_skills_workflow_generation_preview.py` — Skill workflow generate/preview API contracts, configured-model requirement, preview payload shape
- `backend/tests/api/v1/test_sops_workflow_generation_preview.py` — SOP workflow generate/preview API contracts, configured-model requirement, preview payload shape
- `backend/tests/api/v1/test_skills_api.py` — `POST/PUT /skills` with `instructions` field, `GET /skills/{id}` returns `instructions`, `GET /skills` includes `tool_ids`, `GET/PUT /skills/{id}/roles`
- `backend/tests/api/v1/test_sops_api.py` — `POST/PUT /sops` with `instructions`, `PUT /sops/{id}/steps` with `target_agent_type_id`/`step_config`/default step type, `GET/PUT /sops/{id}/roles`
- `backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py` — `skill_invocation` enum validity, legacy `skill` enum rejection, nullable field acceptance (`instructions`, `target_agent_type_id`), atomic role replacement correctness, `Skill.instructions` field persistence

### Frontend
- `frontend/src/__tests__/SkillEditor.test.tsx` — instructions field, tool selection with namespace prefix, role sidebar, form submission *(skipped — mocking infrastructure issue)*
- `frontend/src/__tests__/SkillEditor.minimal.test.tsx` — core rendering assertions (workaround)
- `frontend/src/__tests__/SopEditor.test.tsx` — instructions field, step add/reorder/remove, step type selector, `target_agent_type_id` in submission, role assignment *(skipped — mocking infrastructure issue)*
- `frontend/src/__tests__/SopEditor.simple.test.tsx` — core rendering assertions (workaround)
- `frontend/src/__tests__/SkillEditor.workflow-generation-preview.test.tsx` — Skill generate/preview actions, preview freshness from unsaved state, dialog-visible API error handling
- `frontend/src/__tests__/SopEditor.workflow-generation-preview.test.tsx` — SOP generate/preview actions, delegation-aware preview freshness, dialog-visible API error handling
- `frontend/src/__tests__/ModelConfigListPage.workflow-generation.test.tsx` — workflow generation model selection and persistence behavior used by Skill/SOP generate and preview flows
- `frontend/src/__tests__/WorkflowTerminology.rename-coverage.test.tsx` — workflow terminology rename coverage for Skill and SOP surfaces

### E2E
- `e2e/tests/skills-sops.spec.ts` — SkillEditor with tool binding and role assignment (mocked), SopEditor with instructions and steps (mocked), parent table refresh for both, `target_agent_type_id` round-trip; `test.describe('Real Backend Integration - Skills and SOPs')` — real skill creation with tool bindings (verifies `tool_ids`), real SOP creation with `instructions` and steps using `target_agent_type_id`
- `e2e/tests/skills-workflow-generation-preview.spec.ts` — Skill workflow generate/preview flows with model-selection dependency and preview rendering behavior
- `e2e/tests/sops-workflow-generation-preview.spec.ts` — SOP workflow generate/preview flows with ordered-step context and preview rendering behavior
- `e2e/tests/agent-a2a-communication.spec.ts` — delegation-focused UI coverage tied to SOP-derived A2A permissions
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| ai-assisted-workflow-authoring-for-sop-and-skill | Added workflow terminology rename coverage, Skill/SOP workflow generate+preview coverage, configured-model dependency checks, and preview freshness/security assertions across backend/frontend/e2e | 2026-05-29 |
