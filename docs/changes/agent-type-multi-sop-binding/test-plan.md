## Test Plan: agent-type-multi-sop-binding

## Test Strategy

| Layer | Approach | Scope |
|-------|----------|-------|
| Unit (Backend) | Service-layer tests with mocked repository | Binding CRUD, validation, role-access checks |
| Unit (Frontend) | Component tests with mocked API | Binding list rendering, add/remove/reorder, validation states |
| Integration (Backend) | Real PostgreSQL via testcontainers | Schema migration verification, binding persistence, constraint enforcement |
| E2E | Playwright with real backend (one test) + mocked API (remaining) | Full user flow: create agent type with bindings, verify round-trip |
| Manual | Browser-based | Edge cases: orphan bindings, role switch, concurrent edit |

## Coverage Areas

| Area | Why Critical |
|------|-------------|
| Binding CRUD persistence | Core data model change — ensures new join tables store/retrieve correctly |
| Cascade delete behavior | If AgentType deleted, bindings must cascade; if SOP/skill deleted, bindings must handle gracefully |
| Unique constraints | Duplicate (agent_type_id, sop_id) and (agent_type_id, skill_id) must be prevented at DB level |
| Role-access validation | Users must not bind SOPs/skills the role doesn't have access to |
| Data migration from primary_sop_id | Existing agent types must retain their SOP access after schema change |
| System instruction generation | Generated instructions must reflect only the curated binding list, not all role-assigned |
| Plan mode topology | Topology must show bound SOPs/skills, not all role-assigned |
| Frontend binding list UI | Add, remove, reorder must work; validation feedback must display |
| Role-filtered dropdown | Available items must match role selection |

## Critical Scenarios

**Scenario 1: Create agent type with bindings**
WHEN a user creates an AgentType with two SOP bindings and one skill binding
THEN the bindings are persisted and returned in the GET response ordered correctly

**Scenario 2: Reorder bindings**
WHEN a user changes the order values of existing bindings
THEN the updated order is persisted and the system instruction generator respects the new order

**Scenario 3: Role-access validation blocks invalid binding**
WHEN a user attempts to bind a SOP that is not assigned to the agent's role
THEN the API returns a 422 validation error listing the inaccessible SOP

**Scenario 4: Duplicate binding rejected**
WHEN a user attempts to bind the same SOP twice to the same AgentType
THEN the API returns a 409 conflict error

**Scenario 5: Cascade delete on AgentType removal**
WHEN a user deletes an AgentType that has bindings
THEN all associated binding rows are cascade-deleted from the join tables

**Scenario 6: Data migration of existing primary_sop_id**
WHEN the migration runs and an AgentType has primary_sop_id = <existing SOP>
THEN an AgentTypeSopBinding row is created with order=0 for that SOP

**Scenario 7: Empty binding list fallback**
WHEN an AgentType has no SOP or skill bindings configured
THEN the system instruction generator produces empty SOP/skill context (no error)

**Scenario 8: Frontend add/remove/reorder**
WHEN a user adds, reorder, then removes a binding in the UI
THEN the component state reflects the final list correctly before save

## Edge Cases & Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| SOP/skill deleted while referenced by binding | Broken reference in binding list | Cascade delete set to SET NULL (or cascade); frontend shows "broken ref" indicator |
| Role changed to one without previously-bound SOPs | All bindings become inaccessible | Validation on save catches this; frontend warns user on role change |
| Extremely large binding lists (50+ bindings) | UI performance, LLM context bloat | Cap at 20 total bindings; paginate if needed |
| Concurrent edit overwrites bindings | Lost updates | Optimistic locking on AgentType; frontend stale-data detection |
| Migration rollback recreates primary_sop_id | Data loss on first SOP binding per AgentType | Migration must create first binding with order=0 for rollback |

## Acceptance Criteria Checklist

Maps to PRD acceptance criteria:

| # | Criterion | Test Coverage |
|---|-----------|---------------|
| AC-1 | Agent Type can bind multiple SOPs | Backend integration: create with 2+ SOP bindings |
| AC-2 | Agent Type can bind multiple skills | Backend integration: create with 2+ skill bindings |
| AC-3 | Bindings have an order field | Schema verification: information_schema has column |
| AC-4 | Duplicate binding references rejected | Backend unit: duplicate SOP ID returns error |
| AC-5 | Binding list visible in Agent Type form | Frontend component: binding list renders |
| AC-6 | Add binding via type selector + dropdown | Frontend component: add flow works |
| AC-7 | Remove binding | Frontend component: remove clears row |
| AC-8 | Reorder via up/down | Frontend component: order updates correctly |
| AC-9 | Available items filtered by role | Frontend component: dropdown changes on role switch |
| AC-10 | Inaccessible reference rejected | Backend integration: validation returns 422 |
| AC-11 | Duplicate shows inline error | Frontend component: error message displays |
| AC-12 | Broken reference shows warning | Frontend component: ⚠ indicator on stale ref |
| AC-13 | Plan Preview reflects binding list | Frontend component: plan tab matches binding list |
| AC-14 | Existing primary_sop migrated | Backend integration: migration creates binding row |
| AC-15 | primary_sop_id field removed | Schema verification: column does not exist |
| AC-16 | Generator uses curated list | Backend unit: instructions exclude non-bound SOPs |
| AC-17 | Empty bindings produce no SOP context | Backend unit: no bindings → empty context |
| AC-18 | Binding order preserved in generation | Backend unit: instructions follow binding order |

## Test File References

| Test Type | File Path |
|-----------|-----------|
| Backend unit — binding CRUD | `backend/tests/unit/test_agent_type_bindings.py` |
| Backend integration — schema | `backend/tests/integration/test_agent_type_binding_schema.py` |
| Backend unit — validation | `backend/tests/unit/test_binding_validation.py` |
| Backend unit — instruction generator | `backend/tests/unit/test_instruction_generator_bindings.py` |
| Backend integration — migration | `backend/tests/integration/test_primary_sop_migration.py` |
| Frontend component — binding list | `frontend/src/__tests__/components/SopSkillBindingsSection.test.tsx` |
| Frontend component — picker | `frontend/src/__tests__/components/BindingPicker.test.tsx` |
| Frontend hook — state | `frontend/src/__tests__/hooks/useAgentTypeBinding.test.ts` |
| E2E — real backend | `e2e/tests/agent-type-bindings.spec.ts` |
| E2E — mocked | `e2e/tests/agent-type-bindings-mocked.spec.ts` |
