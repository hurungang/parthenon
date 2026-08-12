# Agent Plan Mode — Implementation Plan

## Overview

The agent-plan-mode change adds automatic LLM-powered plan generation when an Agent Type is saved. The backend traverses the role→SOP→Skill→Tool graph, constructs a detailed prompt with agent context, invokes the configured LLM to generate a human-readable implementation plan, produces a node-edge topology structure, and returns both inline in the save response. The frontend receives the payload, opens a Plan Preview Modal, and renders the LLM-generated plan steps alongside a visual topology diagram. When an agent session starts, the runtime loads the saved plan and injects it into the agent's system context to guide execution. No extra API round-trips are required after save.

---

## Task Checklist

### Phase 1 — Database Schema & Models
- [x] 1.1 — Add `AgentPlanStatus` enum to agents model file
- [x] 1.2 — Add `AgentPlan` SQLAlchemy model to agents model file
- [x] 1.3 — Register `AgentPlan` in models `__init__.py`
- [x] 1.4 — Generate Alembic migration for `agent_plans` table
- [x] 1.5 — Apply migration and verify schema

### Phase 2 — Backend Services
- [x] 2.1 — Create `TopologyBuilderService`
- [x] 2.2 — Create `PlanGenerationService` with LLM integration
- [x] 2.3 — Add plan/topology Pydantic schemas
- [x] 2.4 — Extend `AgentRuntimeLoader` to load and inject plan into agent context

### Phase 3 — Backend API Integration
- [x] 3.1 — Extend `AgentTypeRead` schema with optional plan fields
- [x] 3.2 — Extend `POST /agents/types` handler to invoke plan generation
- [x] 3.3 — Extend `PUT /agents/types/{type_id}` handler to invoke plan generation

### Phase 4 — Frontend Components
- [x] 4.1 — Add plan/topology TypeScript types
- [x] 4.2 — Add i18next translation keys for plan preview UI
- [x] 4.3 — Create `TopologyDiagramRenderer` component
- [x] 4.4 — Create `PlanPreviewModal` component
- [x] 4.5 — Extend `AgentManagementPage` to open plan preview after save

### Phase 5 — Integration & Testing
- [x] 5.1 — Write unit tests for `TopologyBuilderService`
- [x] 5.2 — Write unit tests for `PlanGenerationService` (with mocked LLM)
- [x] 5.3 — Write backend API integration test for extended save response
- [x] 5.4 — Write frontend component tests for `PlanPreviewModal`, `TopologyDiagramRenderer`, and `AgentManagementPage`
- [x] 5.5 — Write test for plan loading in `AgentRuntimeLoader`
- [x] 5.6 — Automated end-to-end tests

### Phase 6 — Documentation Updates
- [ ] 6.1 — Update master architecture docs
- [ ] 6.2 — Update master data model docs
- [ ] 6.3 — Update master tech spec

---

## Phase 1 — Database Schema & Models

### Task 1.1 — Add `AgentPlanStatus` enum to agents model file

In `backend/app/db/models/agents.py`, define a new `AgentPlanStatus` string enum with values `pending`, `success`, and `failed`. Follow the existing enum naming conventions (`class AgentPlanStatus(str, enum.Enum)`).

**Done when**: `AgentPlanStatus` exists in `backend/app/db/models/agents.py` with all three values and no syntax errors.

---

### Task 1.2 — Add `AgentPlan` SQLAlchemy model to agents model file

In `backend/app/db/models/agents.py`, define the `AgentPlan` model with the following mapped columns:

- `id` — UUID primary key
- `agent_type_id` — UUID FK → `agent_types.id`, unique constraint (one plan per agent type), `ondelete="CASCADE"`
- `plan_steps` — JSON, nullable
- `topology` — JSON, nullable
- `generation_status` — `AgentPlanStatus` enum, non-null
- `generation_error` — String(1000), nullable
- `agent_config_hash` — String(64), nullable
- `generated_at` — DateTime with timezone, nullable
- `created_at` — DateTime with timezone, server default now
- `updated_at` — DateTime with timezone, server default now, onupdate now

Add a `relationship` back-ref on `AgentType` pointing to its `AgentPlan` (one-to-one via `uselist=False`).

**Done when**: `AgentPlan` model is present in `backend/app/db/models/agents.py`; `AgentType` has a `.plan` relationship; no SQLAlchemy configuration errors on import.

---

### Task 1.3 — Register `AgentPlan` in models `__init__.py`

In `backend/app/db/models/__init__.py`, import and expose `AgentPlan` and `AgentPlanStatus` so Alembic's env.py can detect the new table during autogenerate.

**Done when**: `AgentPlan` and `AgentPlanStatus` appear in `backend/app/db/models/__init__.py` exports.

---

### Task 1.4 — Generate Alembic migration for `agent_plans` table

From the project root with the virtual environment active, run:

```
alembic revision --autogenerate -m "add_agent_plans"
```

Review the generated migration file to confirm it creates the `agent_plans` table with all columns, the unique constraint on `agent_type_id`, and the FK to `agent_types` with `CASCADE` delete. Do not edit the migration by hand.

**Done when**: A migration file exists under `backend/alembic/versions/` containing a `create_table("agent_plans", ...)` statement; manual review confirms correct columns, constraint, and FK.

---

### Task 1.5 — Apply migration and verify schema

Run `alembic upgrade head` and confirm via `alembic current` that the new migration is the head revision. Optionally query `information_schema.columns` to confirm the `agent_plans` table has the expected columns.

**Done when**: `alembic current` reports the `add_agent_plans` migration as the applied head; `agent_plans` table is present in the database.

---

## Phase 2 — Backend Services

### Task 2.1 — Create `TopologyBuilderService`

Create `backend/app/services/agents/topology_builder_service.py`. The service exposes a single async method `build_topology(graph)` that accepts the role→SOP→Skill→Tool graph structure (as returned by the role resolution query) and returns a serialisable dict containing:

- `nodes` — list of node objects, each with: `id` (string), `type` (`role` | `sop` | `skill` | `tool`), `label` (human-readable name), and optional `meta` dict
- `edges` — list of edge objects, each with: `source` (node id), `target` (node id), `label` (optional relationship name)

The builder assigns stable, deterministic IDs (e.g., `role:<uuid>`, `sop:<uuid>`, `skill:<uuid>`, `tool:<tool_identifier>`) so the frontend can render a consistent diagram. Include OTEL span instrumentation using the project's tracer pattern (`tracer.start_as_current_span`).

**Done when**: `TopologyBuilderService` exists at the target path; `build_topology` returns a dict with `nodes` and `edges` keys; import succeeds with no errors; existing unit test scaffold confirms the output shape.

---

### Task 2.2 — Create `PlanGenerationService` with LLM integration

Create `backend/app/services/agents/plan_generation_service.py`. The service exposes an async method `generate_plan(agent_type, db)` that:

1. Resolves the role→SOP→Skill→Tool graph by querying the database (reuse the traversal logic from `AgentPermissionManager._resolve_allowed_tools` as a read-only reference, but fetch full objects rather than identifiers — load `AgentRole`, its `AgentRoleSOP` and `AgentRoleSkill` assignments, the `Sop` objects with their `SopStep` lists, the `Skill` objects with their `SkillToolBinding` lists, and the linked `McpTool` records).
2. Constructs a detailed prompt for the LLM containing:
   - Agent's system instruction
   - Role name and description
   - All assigned SOPs with their steps
   - All assigned Skills with descriptions
   - All available Tools with descriptions
   - Request for a structured, step-by-step implementation plan
3. Invokes the configured LLM (use the platform's existing LLM provider configuration and client) with the constructed prompt.
4. Parses the LLM response into structured `plan_steps` list. Each step is a dict with at minimum: `order` (int), `type` (`sop_invocation` | `skill_invocation` | `tool_call`), `name` (string), `description` (string or null).
5. Calls `TopologyBuilderService.build_topology(graph)` to produce the topology payload.
6. Upserts an `AgentPlan` row for the agent type (insert if absent, update if present) with `generation_status = success` and the generated data.
7. On any exception (including LLM errors), upserts an `AgentPlan` row with `generation_status = failed` and `generation_error` set to the exception message. Does NOT re-raise — plan generation failure is non-blocking.
8. Computes and stores `agent_config_hash` as a deterministic hash of the agent type's `role_id`, `primary_sop_id`, and `system_instruction`.

Returns the upserted `AgentPlan` row (regardless of success/failure status).

Include OTEL instrumentation and structured logging consistent with other services in `backend/app/services/agents/`. Log LLM invocation details (model, token count, latency) for observability.

**Done when**: `PlanGenerationService` exists at the target path; `generate_plan` can be called with a mock agent type and a real or mocked db session and LLM client; no unhandled exceptions propagate; unit tests confirm happy-path (with mocked LLM) and error-path behaviour.

---

### Task 2.3 — Add plan/topology Pydantic schemas

In `backend/app/schemas/agents.py`, add the following schemas:

- `PlanStepRead` — `order: int`, `type: str`, `name: str`, `description: str | None`
- `TopologyNodeRead` — `id: str`, `type: str`, `label: str`, `meta: dict | None`
- `TopologyEdgeRead` — `source: str`, `target: str`, `label: str | None`
- `AgentPlanRead` — `id: uuid.UUID`, `agent_type_id: uuid.UUID`, `plan_steps: list[PlanStepRead]`, `topology_nodes: list[TopologyNodeRead]`, `topology_edges: list[TopologyEdgeRead]`, `generation_status: AgentPlanStatus`, `generation_error: str | None`, `agent_config_hash: str | None`, `generated_at: datetime | None`

All schemas use `model_config = {"from_attributes": True}` and import `AgentPlanStatus` from the models module.

**Done when**: All four schemas are present in `backend/app/schemas/agents.py`; importing the module produces no errors; Pydantic validation accepts correctly shaped input for each schema.

---

### Task 2.4 — Extend `AgentRuntimeLoader` to load and inject plan into agent context

Locate `backend/app/services/agents/runtime_loader.py` (or similar agent session initialization service). Extend the agent session initialization logic to:

1. Query the `agent_plans` table for the plan associated with the agent type being executed (join on `agent_type_id`).
2. If a plan exists with `generation_status = success`, extract the `plan_steps` JSON and format it as a structured text block.
3. Inject the formatted plan into the agent's system context (LLM system prompt) with clear instructions: "You must follow this pre-approved implementation plan during execution. The plan outlines the steps, SOPs, skills, and tools you should use."
4. If no plan exists or `generation_status != success`, proceed without plan injection (graceful degradation).

Include logging to record whether a plan was loaded and injected for observability.

**Done when**: Agent session initialization code loads and injects the plan when available; agent runtime logs indicate plan loading; unit tests verify plan injection into system context; agent sessions without plans do not fail.

---

## Phase 3 — Backend API Integration

### Task 3.1 — Extend `AgentTypeRead` schema with optional plan fields

In `backend/app/schemas/agents.py`, add an optional `plan: AgentPlanRead | None = None` field to `AgentTypeRead`. Update its `model_validate` classmethod to populate `plan` from the ORM relationship `obj.plan` when present.

**Done when**: `AgentTypeRead` has a `plan` field; calling `AgentTypeRead.model_validate(agent_type_orm_with_plan)` populates `plan` correctly; calling with an agent type that has no plan record yields `plan: None`.

---

### Task 3.2 — Extend `POST /agents/types` handler to invoke plan generation

In `backend/app/api/v1/agents.py`, locate the `POST /agents/types` route handler. After the agent type record is committed and refreshed, call `await plan_generation_service.generate_plan(agent_type, db)`. Ensure `PlanGenerationService` is instantiated as a module-level singleton alongside the other service singletons. The `AgentTypeRead` response will automatically include the plan via the relationship when the ORM object is serialised.

**Done when**: A `POST /agents/types` request returns a response body where the `plan` field is non-null when the agent type has a role assigned; plan generation errors do not cause the endpoint to return a non-2xx status.

---

### Task 3.3 — Extend `PUT /agents/types/{type_id}` handler to invoke plan generation

Apply the same change as Task 3.2 to the `PUT /agents/types/{type_id}` route handler: call `generate_plan` after a successful update commit.

**Done when**: A `PUT /agents/types/{type_id}` request returns a response body with an updated `plan` field reflecting the current role/SOP/Skill/Tool graph; regeneration replaces the previous plan content.

---

## Phase 4 — Frontend Components

### Task 4.1 — Add plan/topology TypeScript types

In `frontend/src/types/index.ts`, add:

- `AgentPlanStatus` — type alias: `'pending' | 'success' | 'failed'`
- `PlanStep` — interface: `order: number`, `type: string`, `name: string`, `description: string | null`
- `TopologyNode` — interface: `id: string`, `type: string`, `label: string`, `meta?: Record<string, unknown>`
- `TopologyEdge` — interface: `source: string`, `target: string`, `label?: string`
- `AgentPlan` — interface: `id: string`, `agent_type_id: string`, `plan_steps: PlanStep[]`, `topology_nodes: TopologyNode[]`, `topology_edges: TopologyEdge[]`, `generation_status: AgentPlanStatus`, `generation_error: string | null`, `agent_config_hash: string | null`, `generated_at: string | null`

Update the existing `AgentType` interface to add `plan?: AgentPlan | null`.

**Done when**: All new types exist in `frontend/src/types/index.ts`; `AgentType` includes `plan`; no TypeScript errors in the types file.

---

### Task 4.2 — Add i18next translation keys for plan preview UI

In `frontend/src/i18n/locales/en.json`, add a `plan` sub-key under `agents` with keys covering at minimum:

- `agents.plan.previewTitle` — Modal title
- `agents.plan.steps` — Section label for the steps list
- `agents.plan.noSteps` — Empty state when steps list is empty
- `agents.plan.topology` — Section label for the topology diagram
- `agents.plan.generationFailed` — Error message shown when `generation_status = failed`
- `agents.plan.generationFailedDetail` — Sub-text showing the `generation_error` value
- `agents.plan.close` — Close button label
- `agents.plan.stepTypes.sop_invocation` — Human label for SOP invocation step type
- `agents.plan.stepTypes.skill_invocation` — Human label for Skill invocation step type
- `agents.plan.stepTypes.tool_call` — Human label for Tool call step type
- `agents.plan.nodeTypes.role` — Human label for role topology node type
- `agents.plan.nodeTypes.sop` — Human label for SOP topology node type
- `agents.plan.nodeTypes.skill` — Human label for Skill topology node type
- `agents.plan.nodeTypes.tool` — Human label for Tool topology node type

**Done when**: All keys are present in `en.json` with meaningful English strings; no duplicate keys; the file remains valid JSON.

---

### Task 4.3 — Create `TopologyDiagramRenderer` component

Create `frontend/src/components/agents/TopologyDiagramRenderer.tsx`. The component accepts `nodes: TopologyNode[]` and `edges: TopologyEdge[]` as props and renders a visual diagram of the agent topology.

Implementation guidance:
- Use SVG or an HTML Canvas-based layout for rendering. A simple force-directed or layered layout (role → sops → skills → tools) is sufficient for v1.
- Node appearance should differ by `type` (role, sop, skill, tool) using distinct MUI `Chip` colours or icon badges.
- Edges should be rendered as simple lines or arrows connecting source to target nodes.
- All node labels come from `node.label`; no hardcoded names.
- Wrap all text through `t()` for any UI labels (e.g., empty state).
- The component should handle empty `nodes` and `edges` arrays gracefully with a placeholder message using `agents.plan.topology` key.

**Done when**: Component exists and renders without runtime errors when passed a representative nodes/edges payload; TypeScript compiles cleanly; empty state is handled.

---

### Task 4.4 — Create `PlanPreviewModal` component

Create `frontend/src/components/agents/PlanPreviewModal.tsx`. The component is an MUI `Dialog` with:

- Props: `open: boolean`, `onClose: () => void`, `plan: AgentPlan | null`, `agentTypeName: string`
- `DialogTitle`: uses `agents.plan.previewTitle` key, showing `agentTypeName`
- `DialogContent`:
  - If `plan === null` or `plan.generation_status === 'failed'`: show `PermissionDeniedAlert`-style error block using `agents.plan.generationFailed` and `agents.plan.generationFailedDetail`
  - Otherwise: render two sections:
    1. Plan Steps — ordered list of `PlanStep` items displaying `step.name`, `step.description`, and a `Chip` for `step.type` (translated via `agents.plan.stepTypes.*`)
    2. Topology — hosts `TopologyDiagramRenderer` with `plan.topology_nodes` and `plan.topology_edges`
- `DialogActions`: Close button using `agents.plan.close`
- `maxWidth="lg"`, `fullWidth`
- Follow the Dialog Error Handling Standard from `docs/config.yaml` conventions

**Done when**: Component exists and renders the plan steps list and topology diagram when given a valid `AgentPlan`; error state renders the error block; modal closes cleanly; no hardcoded UI strings.

---

### Task 4.5 — Extend `AgentManagementPage` to open plan preview after save

In `frontend/src/pages/agents/AgentManagementPage.tsx`, modify the `handleSave` function to:

1. After a successful `apiClient.post` or `apiClient.put` call, read the `plan` field from the response data.
2. Store the plan in new state: `const [planData, setPlanData] = useState<AgentPlan | null>(null)` and `const [planModalOpen, setPlanModalOpen] = useState(false)`.
3. If a plan is present in the response, set `planData` and open the plan modal (`setPlanModalOpen(true)`).
4. Close the edit dialog after setting plan data (existing `setDialogOpen(false)` call).
5. Render `<PlanPreviewModal open={planModalOpen} onClose={() => { setPlanModalOpen(false); setPlanData(null) }} plan={planData} agentTypeName={editType?.name ?? form.name} />` in the component's JSX.

**Done when**: Saving an Agent Type opens the Plan Preview Modal with the correct plan data; the edit dialog closes; closing the modal clears `planData`; no TypeScript or runtime errors.

---

## Phase 5 — Integration & Testing

### Task 5.1 — Write unit tests for `TopologyBuilderService`

In `backend/tests/unit/services/`, add test file `test_topology_builder_service.py`. Cover:

- Happy path: a graph with one role, two SOPs, three skills, and four tools produces the expected node count and edge count.
- Empty graph: role with no SOPs or skills produces a single `role` node and no edges.
- Node ID stability: calling `build_topology` twice with the same graph produces identical `id` values.

**Done when**: All three test cases pass with `pytest`; no test isolation issues (no DB required).

---

### Task 5.2 — Write unit tests for `PlanGenerationService`

In `backend/tests/unit/services/`, add test file `test_plan_generation_service.py`. Cover:

- Happy path: `generate_plan` with a mocked db session containing a role with SOPs and skills returns an `AgentPlan` with `generation_status = success` and non-empty `plan_steps`.
- Error path: if the db query raises an exception, the returned `AgentPlan` has `generation_status = failed` and `generation_error` is set; no exception propagates.
- Hash computation: same inputs produce the same `agent_config_hash`; different `role_id` produces a different hash.

**Done when**: All test cases pass; mocking is used for the `AsyncSession`; no real DB required.

---

### Task 5.3 — Write backend API integration test for extended save response

In `backend/tests/integration/` (or `backend/tests/api/`), add or extend the agent types test file to cover:

- `POST /agents/types` with a role assigned: response body contains a non-null `plan` field with `generation_status`.
- `PUT /agents/types/{type_id}` after updating the role: `plan` field reflects regenerated data.
- `POST /agents/types` with no role assigned: `plan` may be null or reflect a `failed`/`pending` status — confirm endpoint still returns 200/201.

Run against a real test database with migrations applied via `alembic upgrade head`.

**Done when**: All three scenarios pass in CI; test does not use mocked API routes.

---

### Task 5.4 — Write frontend component tests for plan preview

In `frontend/src/__tests__/`, add the following test files. Use Vitest + React Testing Library, consistent with the project's existing frontend test setup.

**`PlanPreviewModal.test.tsx`** — Cover:
- Renders plan steps when given a valid `AgentPlan` with `generation_status = success`.
- Renders the error block when `generation_status = failed`.
- Calls `onClose` when the Close button is clicked.
- Does not render when `open = false`.

**`TopologyDiagramRenderer.test.tsx`** — Cover:
- Renders without throwing when given a valid nodes/edges payload.
- All four node types (`role`, `sop`, `skill`, `tool`) present in rendered output.
- Empty `nodes` and `edges` arrays produce an empty-state indicator without throwing.

**`AgentManagementPage.test.tsx`** (extend existing) — Cover:
- `planModalOpen` is `true` after a successful create save; `planData` set from response.
- `planData` cleared and modal closed when dismissed.
- Save response with `plan: null` does not open the modal.

**Done when**: All tests pass with `npm run test` (or `vitest run`) from the `frontend/` directory.

---

---

### Task 5.5 — Write test for plan loading in `AgentRuntimeLoader`

Plan loading and injection by `AgentRuntimeLoader` is verified in `backend/tests/integration/api/test_agent_types_plan.py`. The integration tests confirm that:

- An agent type with a saved plan (`generation_status = success`) has its plan loaded from the `agent_plans` table.
- The plan is formatted and would be injected into the agent's system context.
- An agent type with no plan record does not cause the session initialization to fail (graceful degradation).
- A plan with `generation_status = failed` is ignored during session initialization.

**Done when**: Integration test suite passes against a real database; plan loading is verified through the API and database layer.

---

### Task 5.6 — Automated end-to-end tests

Add `e2e/tests/agent-plan-mode.spec.ts` with two suites:

**Mocked suite** (using `page.route()` for speed):
1. Create journey: fill form → save → `PlanPreviewModal` opens → step list visible → diagram rendered → dismiss → table row present.
2. Update journey: edit agent type → modify system instruction → save → modal opens with updated plan → dismiss → table reflects update.
3. Failed plan journey: mock returns `generation_status = failed` → modal opens → `generation_error` message visible → dismiss → agent type saved correctly.
4. Viewport tests: desktop 1280×800 and tablet 768×1024 — modal usable at both sizes.

**Real Backend Integration - Agent Plan Mode** suite (no `page.route()` mocks):
- Create an agent type via real `POST /api/v1/agents/types` → verify response includes `plan` field with valid `generation_status` → verify `PlanPreviewModal` opens → dismiss → delete agent type → verify `AgentPlan` row is also removed (CASCADE delete).

**Done when**: All mocked scenarios pass with `npx playwright test agent-plan-mode.spec.ts`; real-backend suite confirms migration was applied and plan round-trips correctly.

---

## Phase 6 — Documentation Updates

### Task 6.1 — Update master architecture docs

In `docs/master/architecture/system-overview.md`, add `Plan Generation Service` and `Topology Builder Service` to the Platform API component table. Note that the save-agent flow now returns a `plan` payload inline in the response.

Create or update `docs/master/architecture/modules/agent-types.md` to document the extended save response contract: `plan` field appended to the `AgentTypeRead` response schema.

**Done when**: Both files updated; component table in `system-overview.md` includes the two new services; no stale references.

---

### Task 6.2 — Update master data model docs

In `docs/master/data-model/agents.md` (create if absent), add the `agent_plans` entity to the agent domain entity list. Document the one-to-one relationship with `agent_types`, the `generation_status` enum values, and the `agent_config_hash` staleness-detection pattern.

**Done when**: `agents.md` includes `agent_plans` with entity attributes and relationship to `agent_types`.

---

### Task 6.3 — Update master tech spec

In `docs/master/technology/modules/agents/tech-spec.md`, add:

- `PlanGenerationService` and `TopologyBuilderService` to the Backend Services table.
- `AgentPlan` and `AgentPlanStatus` to the Backend Models table.
- `AgentPlanRead`, `PlanStepRead`, `TopologyNodeRead`, `TopologyEdgeRead` to the Backend Schemas table.
- `PlanPreviewModal` and `TopologyDiagramRenderer` to the Frontend components table.
- The extended `POST /agents/types` and `PUT /agents/types/{type_id}` responses to the API Endpoints table.
- New entries in the Code Reference Map for all new symbols.

**Done when**: All new components appear in the tech spec tables and Code Reference Map with correct file paths.

---

## Completion Checklist

- [x] `agent_plans` table created in database with correct schema
- [x] `PlanGenerationService` creates/upserts `AgentPlan` on every agent type save
- [x] Plan generation failures are non-blocking (agent type save succeeds regardless)
- [x] `POST /agents/types` and `PUT /agents/types/{type_id}` return `plan` field in response
- [x] `PlanPreviewModal` opens automatically after a successful save
- [x] Topology diagram renders nodes and edges without blank output
- [x] All UI text flows through `t()` with keys defined in `en.json`
- [x] Dialog Error Handling Standard followed in `PlanPreviewModal`
- [x] Unit tests pass for `TopologyBuilderService` and `PlanGenerationService`
- [x] API integration test confirms extended save response
- [x] Frontend component tests pass for `PlanPreviewModal`, `TopologyDiagramRenderer`, and `AgentManagementPage`
- [x] E2E tests pass for all plan preview scenarios
- [ ] Master architecture, data model, and tech spec docs updated
