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

## Critical Scenarios
- Skill composes two tool calls
- SOP step delegates to a second agent type
- `instructions` provided in skill form — `GET /skills/{id}` returns exact text
- `instructions` omitted — accepted (column is nullable), returns `null`
- `PUT /skills/{id}/roles` with new list — all previous memberships replaced, none remaining
- `PUT /skills/{id}/roles` with `{"role_ids": []}` — skill has zero role memberships after call
- `PUT /sops/{id}/roles` with `{"role_ids": []}` — SOP has zero role memberships after call
- SOP step submitted with `step_type = 'skill_invocation'` — stored and returned with `target_agent_type_id` (not `delegate_agent_type_id`)
- Steps reordered in SopEditor and saved — new order reflected in `GET /sops/{id}` step list
- SkillListPage shows updated `tool_ids` count badge immediately after skill save (no page reload)
- SopListPage shows deleted SOP removed immediately (no page reload)
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
- `backend/tests/api/v1/test_skills_api.py` — `POST/PUT /skills` with `instructions` field, `GET /skills/{id}` returns `instructions`, `GET /skills` includes `tool_ids`, `GET/PUT /skills/{id}/roles`
- `backend/tests/api/v1/test_sops_api.py` — `POST/PUT /sops` with `instructions`, `PUT /sops/{id}/steps` with `target_agent_type_id`/`step_config`/default step type, `GET/PUT /sops/{id}/roles`
- `backend/tests/integration/test_enhance_mcp_hub_skills_sops_db.py` — `skill_invocation` enum validity, legacy `skill` enum rejection, nullable field acceptance (`instructions`, `target_agent_type_id`), atomic role replacement correctness, `Skill.instructions` field persistence

### Frontend
- `frontend/src/__tests__/SkillEditor.test.tsx` — instructions field, tool selection with namespace prefix, role sidebar, form submission *(skipped — mocking infrastructure issue)*
- `frontend/src/__tests__/SkillEditor.simple.test.tsx` — core rendering assertions (workaround)
- `frontend/src/__tests__/SopEditor.test.tsx` — instructions field, step add/reorder/remove, step type selector, `target_agent_type_id` in submission, role assignment *(skipped — mocking infrastructure issue)*
- `frontend/src/__tests__/SopEditor.simple.test.tsx` — core rendering assertions (workaround)

### E2E
- `e2e/tests/skills-sops.spec.ts` — SkillEditor with tool binding and role assignment (mocked), SopEditor with instructions and steps (mocked), parent table refresh for both, `target_agent_type_id` round-trip; `test.describe('Real Backend Integration - Skills and SOPs')` — real skill creation with tool bindings (verifies `tool_ids`), real SOP creation with `instructions` and steps using `target_agent_type_id`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
