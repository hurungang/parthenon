## Implementation Plan: agent-type-multi-sop-binding

## Overview

Replace the single `primary_sop_id` field on AgentType with ordered lists of SOP and skill bindings, using the same join-table pattern already established by SopStep and AgentRoleSOP. Update the system instruction generator and Agent Plan Mode to consume the curated binding list instead of all role-assigned SOPs/skills. Update the frontend Agent Type editor to manage bindings.

## Task Checklist

### Phase 1 — Database Schema
- [x] 1.1 — Add `AgentTypeSopBinding` and `AgentTypeSkillBinding` SQLAlchemy models
- [x] 1.2 — Remove `primary_sop_id` column and relationship from `AgentType`
- [x] 1.3 — Generate and review Alembic migration, apply it

### Phase 2 — Backend API Layer
- [x] 2.1 — Add Pydantic schemas for binding create/update/response
- [x] 2.2 — Add binding CRUD operations to AgentType service layer
- [x] 2.3 — Add binding validation (role-access check) to service layer
- [x] 2.4 — Update AgentType create/update API endpoints to include bindings
- [x] 2.5 — Add migration task for existing `primary_sop_id` values

### Phase 3 — System Instruction Generator
- [x] 3.1 — Update generator to read `agent_type_sop_bindings` and `agent_type_skill_bindings`
- [x] 3.2 — Merge and sort bindings by order, produce curated context
- [x] 3.3 — Fall back to empty context when no bindings are configured

### Phase 4 — Agent Plan Mode
- [x] 4.1 — Update PlanGenerationService to read curated binding list
- [x] 4.2 — Update topology diagram generator to show bound SOPs/skills
- [x] 4.3 — Update AgentPlan model/API if plan_steps schema changes

### Phase 5 — Frontend Agent Type Editor
- [x] 5.1 — Add binding list UI section to Agent Type form
- [x] 5.2 — Implement Add/Remove/Reorder bindings with type picker (SOP vs Skill)
- [x] 5.3 — Implement role-filtered dropdown for binding picker
- [x] 5.4 — Add validation feedback (duplicate, inaccessible, broken reference)
- [x] 5.5 — Update Plan Preview tab to reflect binding list
- [x] 5.6 — Wire UI to updated backend API schema

### Phase 6 — Integration Testing & Cleanup
- [x] 6.1 — Backend integration tests for binding CRUD and validation
- [x] 6.2 — Frontend component tests for binding list UI
- [ ] 6.3 — E2E tests with real backend for binding flow
- [x] 6.4 — Remove deprecated code paths for old primary_sop_id

## Phase 1 — Database Schema

**1.1 — Add new SQLAlchemy models**
Create `AgentTypeSopBinding` and `AgentTypeSkillBinding` in `backend/app/db/models/agents.py`. Follow the same pattern as `AgentRoleSOP`: surrogate UUID PK, agent_type_id FK, sop_id/skill_id FK, order int, created_at datetime. Add UniqueConstraint on (agent_type_id, sop_id) and (agent_type_id, skill_id). Add relationship backrefs to AgentType.

_Done when_: Models are defined, `alembic revision --autogenerate` produces create-table statements for both join tables.

**1.2 — Remove primary_sop_id from AgentType**
Remove the `primary_sop_id` column and `primary_sop` relationship from the `AgentType` model. Update any code that references `agent_type.primary_sop_id` or `agent_type.primary_sop`.

_Done when_: Model compiles and tests referencing the old field fail (confirming removal).

**1.3 — Alembic migration**
Run `alembic revision --autogenerate -m "replace_primary_sop_with_multi_sop_skill_bindings"`. Review the generated migration file for correctness. Apply with `alembic upgrade head`. Verify with `alembic current`.

_Done when_: Migration applies cleanly, `alembic current` shows the new revision.

## Phase 2 — Backend API Layer

**2.1 — Pydantic schemas**
Add `AgentTypeSopBindingCreate`, `AgentTypeSopBindingResponse`, `AgentTypeSkillBindingCreate`, `AgentTypeSkillBindingResponse`, and `AgentTypeBindingsUpdate` (containing lists of both) in `backend/app/schemas/`.

_Done when_: Schema models parse/pass validation tests with sample binding data.

**2.2 — Binding CRUD service**
Add methods to the AgentType service layer: `set_bindings(agent_type_id, sop_bindings, skill_bindings)` that replaces all bindings atomically. Use cascade delete + re-insert pattern.

_Done when_: Service can add, remove, reorder bindings via the service layer.

**2.3 — Role-access validation**
When setting bindings, validate that each referenced SOP and skill is accessible through the agent type's assigned role. Return a list of invalid references with clear error messages.

_Done when_: Validation rejects bindings to SOPs/skills not assigned to the role.

**2.4 — Update API endpoints**
Update `POST /api/v1/agent-types` and `PUT /api/v1/agent-types/{id}` to accept binding lists in the request body. Update `GET /api/v1/agent-types/{id}` to return binding lists in the response.

_Done when_: Full CRUD cycle works via REST API with bindings included.

**2.5 — Data migration**
Add a startup migration that reads existing `primary_sop_id` values and creates `AgentTypeSopBinding` rows with `order = 0`. Log each migrated agent type.

_Done when_: Existing agent types with `primary_sop_id` set appear in the new binding table.

## Phase 3 — System Instruction Generator

**3.1 — Read new bindings**
Update the system instruction generator to query `agent_type_sop_bindings` and `agent_type_skill_bindings` joined with SOP and Skill tables to get names, descriptions, and instructions.

_Done when_: Generator outputs include bound SOP/skill content.

**3.2 — Merge and order**
Merge both binding lists sorted by `order`, producing a single curated sequence. Format instructions as a sequential numbered list. Bound SOPs provide step-by-step procedures; bound skills provide tool-callable capabilities.

_Done when_: Output instructions follow the order specified in bindings.

**3.3 — Empty fallback**
When no bindings exist, produce an empty instruction section (no SOPs/skills context). The agent executes with only the base system instruction.

_Done when_: Generator handles empty binding lists without error.

## Phase 4 — Agent Plan Mode

**4.1 — Update PlanGenerationService**
Modify `PlanGenerationService` to read the curated binding list from `AgentTypeSopBinding` and `AgentTypeSkillBinding` instead of the single `primary_sop_id`. The LLM prompt for plan generation should reference only the bound SOPs/skills.

_Done when_: Generated plans reflect the curated binding list.

**4.2 — Topology diagram**
Update the topology diagram generator to include bound SOPs (with their skills) and bound skills directly under the agent type → role path. Show both binding paths.

_Done when_: Topology SVG includes SOP bindings and skill bindings as distinct node types.

**4.3 — AgentPlan schema**
Update `plan_steps` JSON schema if the plan structure changes. Ensure backward compatibility with existing plan data.

_Done when_: Existing plan data is still readable after schema update.

## Phase 5 — Frontend Agent Type Editor

**5.1 — Binding list UI**
Add a `SopSkillBindingsSection` component to the Agent Type editor form. Display existing bindings in an ordered list with type badge (SOP/Skill), name, and order number. Each row has up/down reorder and remove buttons.

_Done when_: Binding list renders below the role picker with correct data from API.

**5.2 — Add/Remove/Reorder**
"Add Binding" shows a type selector (SOP/Skill radio) and a filtered dropdown. Remove button deletes the row client-side. Up/down arrows adjust order. Drag-and-drop support is optional.

_Done when_: Can add new bindings, reorder existing ones, and remove them. Changes are saved to server on form submit.

**5.3 — Role-filtered dropdown**
When the role selector changes, re-query available SOPs and skills assigned to that role. The "Add Binding" dropdown shows only available items. Already-bound items are shown as disabled.

_Done when_: Dropdown correctly filters based on selected role.

**5.4 — Validation feedback**
Show inline per-binding errors: duplicate binding (same SOP/skill bound twice), reference not in role permissions, and stale references (SOP/skill deleted). Show a summary banner listing all errors. Disable save when validation fails.

_Done when_: All validation states render correctly with clear error messages.

**5.5 — Plan Preview**
Update the Plan Preview tab to show the curated binding list as numbered plan steps. Include type badges and the topology path.

_Done when_: Plan Preview matches the binding list with correct ordering.

**5.6 — Wire to API**
Connect the form's save handler to the updated backend API schema. Send binding lists in the request body. Handle binding-related validation errors from the server.

_Done when_: Save creates/updates bindings via API and refreshed data displays correctly.

## Phase 6 — Integration Testing & Cleanup

**6.1 — Backend integration tests**
Test binding CRUD via API service layer. Test role-access validation rejects invalid references. Test cascade delete removes bindings when agent type is deleted. Test data migration from primary_sop_id.

_Done when_: All backend binding tests pass.

**6.2 — Frontend component tests**
Test `SopSkillBindingsSection` renders, adds, removes, reorders bindings. Test role-filtered dropdown behavior. Test validation states.

_Done when_: Frontend component tests pass.

**6.3 — E2E tests**
One E2E test with real backend (no mocks): create agent type with bindings, verify they persist and display. One E2E with mocks for edge cases.

_Done when_: E2E tests pass and real-backend variant verifies database round-trip.

**6.4 — Cleanup**
Remove any code paths that reference `primary_sop_id` directly (outside the data migration). Update imports and type references.

_Done when_: `git grep primary_sop_id` returns only migration-related references.

## Completion Checklist (Phases 1-5 ✅, 6 pending)
- [x] New join tables `agent_type_sop_bindings` and `agent_type_skill_bindings` exist in schema
- [x] `primary_sop_id` column removed from `agent_types`
- [x] Alembic migration applied and reversible
- [x] Existing agent types with `primary_sop_id` migrated to binding rows
- [x] Backend API accepts binding lists in create/update
- [x] Backend API returns binding lists in responses
- [x] Role-access validation rejects invalid bindings
- [x] System instruction generator reads curated binding list
- [x] Agent Plan Mode reads curated binding list
- [x] Frontend editor shows binding list with add/remove/reorder
- [x] Role-filtered dropdown works correctly
- [x] Validation states render with clear error messages
- [x] Plan Preview tab reflects curated bindings
- [x] Backend integration tests pass
- [x] Frontend component tests pass
- [ ] E2E tests pass with real backend
- [x] All old `primary_sop_id` code paths cleaned up (app code only; test code still has references)
