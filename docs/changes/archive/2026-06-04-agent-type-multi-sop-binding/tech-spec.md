## Technical Specification: agent-type-multi-sop-binding

## Technical Overview

Replace the single `primary_sop_id` FK on AgentType with ordered join tables `AgentTypeSopBinding` and `AgentTypeSkillBinding`, following the same pattern used by `SopStep` (SOP → skill ordering) and `AgentRoleSOP` (role → SOP association). The ordered binding list becomes the single source of truth for which SOPs and skills the agent type uses — consumed by the system instruction generator and Agent Plan Mode instead of the full role-assigned set.

## Component Breakdown

| Component | Responsibility |
|---|---|
| `AgentTypeSopBinding` (model) | Join entity linking AgentType → SOP with order; unique per (agent_type_id, sop_id) |
| `AgentTypeSkillBinding` (model) | Join entity linking AgentType → Skill with order; unique per (agent_type_id, skill_id) |
| `AgentTypeService.set_bindings()` | Atomically replaces all bindings for an agent type; validates role-access before persisting |
| `BindingValidationService` | Checks each referenced SOP/skill against the role's current assignments; returns failed references |
| `SystemInstructionGenerator` | Reads merged sorted binding lists instead of all role-assigned SOPs; produces curated context |
| `PlanGenerationService` | Reads binding lists to generate plan steps and topology diagram |
| `AgentTypeController` | Updated REST endpoints that accept/return binding lists in JSON payload |
| `SopSkillBindingsSection` (UI) | React component managing the binding list editor with add/remove/reorder |
| `BindingPicker` (UI) | Dropdown with type selector filtered by current role assignments |
| `useAgentTypeBinding` (hook) | State management for binding lists, validation, and API sync |

## API Changes

### Updated Endpoints

| Method | Route | Change |
|--------|-------|--------|
| `POST` | `/api/v1/agent-types` | Request body accepts optional `sop_bindings` and `skill_bindings` arrays |
| `PUT` | `/api/v1/agent-types/{id}` | Request body accepts optional `sop_bindings` and `skill_bindings` arrays; full replacement |
| `GET` | `/api/v1/agent-types/{id}` | Response includes `sop_bindings` and `skill_bindings` arrays with id, order, and embedded SOP/skill name |

### New Inner Schemas (embedded in AgentType payload)

| Schema | Fields | Notes |
|--------|--------|-------|
| `SopBindingCreate` | `sop_id` (uuid), `order` (int) | |
| `SkillBindingCreate` | `skill_id` (uuid), `order` (int) | |
| `SopBindingResponse` | `id`, `sop_id`, `sop_name`, `order` | Includes denormalized SOP name |
| `SkillBindingResponse` | `id`, `skill_id`, `skill_name`, `order` | Includes denormalized skill name |

## State Management

The frontend manages binding state in a `useAgentTypeBinding` hook that tracks:

- `sopBindings` — ordered array of SOP bindings (id, sop_id, sop_name, order)
- `skillBindings` — ordered array of skill bindings (id, skill_id, skill_name, order)
- `availableSops` / `availableSkills` — filtered by current role ID, fetched via separate GET endpoints
- `validationErrors` — per-entry validation state (duplicate, inaccessible, stale)

On role change, available lists re-fetch. On save, both arrays are serialized into the request body. On load, both arrays are deserialized from the response.

## Data Access Patterns

| Data | Access Pattern | Storage |
|------|---------------|---------|
| Binding models (SOP/Skill) | Server-side ORM queries via AgentType relationship | PostgreSQL — `agent_type_sop_bindings` and `agent_type_skill_bindings` tables |
| Available SOPs/Skills for role | Server-side JOIN: `role → AgentRoleSOP/AgentRoleSkill → Sop/Skill` | SQLAlchemy eager-loaded on role fetch |
| Curated binding list (merged) | Two queries sorted by `order`, merged in application layer | In-memory merge |
| Binding validation | EXIST check on role's current SOP/skill assignments | Single query with two IN conditions |

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTypeSopBinding` | model | Join entity AgentType ↔ SOP with order | `backend/app/db/models/agents.py` |
| `AgentTypeSkillBinding` | model | Join entity AgentType ↔ Skill with order | `backend/app/db/models/agents.py` |
| `SopBindingCreate` | schema | Pydantic create schema for SOP binding | `backend/app/schemas/agent_type_bindings.py` |
| `SopBindingResponse` | schema | Pydantic response schema for SOP binding | `backend/app/schemas/agent_type_bindings.py` |
| `SkillBindingCreate` | schema | Pydantic create schema for skill binding | `backend/app/schemas/agent_type_bindings.py` |
| `SkillBindingResponse` | schema | Pydantic response schema for skill binding | `backend/app/schemas/agent_type_bindings.py` |
| `AgentTypeService.set_bindings()` | service | Atomically replaces all bindings | `backend/app/services/agents/agent_type_service.py` |
| `validate_bindings()` | service | Checks role-access for all bindings | `backend/app/services/agents/binding_validation.py` |
| AgentType endpoints | controller | REST endpoints for AgentType CRUD | `backend/app/api/v1/agents.py` |
| `_build_binding_content()` | helper | Builds SOP+Skill binding content for system instruction | `backend/app/api/v1/internal/agent_data.py` |
| `_load_binding_content()` | helper | Loads binding content in Agent Runtime | `backend/app/services/agents/runtime_executor.py` |
| `PlanGenerationService._resolve_graph()` | service | Generates agent plan using binding-filtered graph | `backend/app/services/agents/plan_generation_service.py` |
| `PlanGenerationService._compute_config_hash()` | service | Config hash includes binding IDs | `backend/app/services/agents/plan_generation_service.py` |
| `SopSkillBindingsSection` | component | Binding list editor UI | `frontend/src/components/agent-types/SopSkillBindingsSection.tsx` |
| `BindingPicker` | component | Type + dropdown picker for new binding | `frontend/src/components/agent-types/BindingPicker.tsx` |
| `useAgentTypeBinding` | hook | State management for bindings | `frontend/src/hooks/useAgentTypeBinding.ts` |
| `AgentTypeEditor` | component | Main editor form (updated) | `frontend/src/components/agent-types/AgentTypeEditor.tsx` |
| `PlanPreviewTab` | component | Plan preview tab (updated) | `frontend/src/components/agent-types/PlanPreviewTab.tsx` |
