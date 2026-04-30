# Skill & SOP Engine Test Plan

## What to Test
- Single-tool skill execution
- Multi-tool skill composition
- Step sequencing in SOPs
- Agent delegation and context passing
- Permission enforcement on skill and SOP endpoints (`skill:read`, `skill:create`, `skill:update`, `skill:delete`)
- 403 structured error responses with resource type, action, and resource ID
- Permission-denied UI rendering on Skills and SOPs pages

## Critical Scenarios
- Skill composes two tool calls
- SOP step delegates to a second agent type
- User without `skill:read` receives 403 on `GET /api/v1/skills`; UI shows permission-denied message
- User without `skill:create` receives 403 on `POST /api/v1/skills`; snackbar pre-filled with resource context
- User with correct permissions completes full Skill CRUD flow

## Edge Cases
- First tool succeeds, second fails (partial state)
- Circular agent delegation
- Delegated agent exceeds instance limit
- Permission revoked mid-SOP execution

## Test File References
- `backend/tests/unit/test_skill_executor.py`
- `backend/tests/unit/test_skill_sop.py`
- `backend/tests/api/v1/test_skills_api.py`
- `e2e/tests/skills-sops.spec.ts`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering per page
