# Agent Plan Mode — Tech Spec

## Technical Overview

The agent-plan-mode change extends the Agent Type save flow to automatically generate an LLM-powered implementation plan for each agent. On every create or update of an Agent Type, the backend's `PlanGenerationService` traverses the configured role→SOP→Skill→Tool graph (using the same permission graph already maintained by `AgentPermissionManager`), constructs a detailed prompt containing the agent's instructions, role context, SOPs, skills, and available tools, and invokes the configured LLM to generate a human-readable, step-by-step implementation plan. The LLM response is parsed and structured into an ordered `plan_steps` list. The service also calls `TopologyBuilderService` to serialize the graph as a `nodes`/`edges` structure for visualization. Both outputs are persisted in the new `agent_plans` table and returned inline in the save response — no second API call is required. The frontend detects the `plan` field in the save response and opens the new `PlanPreviewModal`, which renders the step list and delegates diagram rendering to `TopologyDiagramRenderer`. Plan generation failure is non-blocking: if generation fails, the agent type record is still saved and the error is surfaced in the modal rather than blocking the save workflow. Critically, when an agent session is started, the Agent Runtime loads the saved plan from the database and injects it into the agent's system context, instructing the LLM-powered agent to follow the pre-approved plan during execution. This ensures compliant, predictable agent behavior aligned with the reviewed plan.

---

## Component Breakdown

### Backend — New Models

| Component | Responsibility |
|-----------|----------------|
| `AgentPlanStatus` | Enum (`pending`, `success`, `failed`) representing the lifecycle of a plan generation attempt |
| `AgentPlan` | SQLAlchemy model persisting the latest plan for an agent type; stores `plan_steps` and `topology` as JSON, `generation_status`, `generation_error`, and `agent_config_hash`; one record per agent type (unique FK) |

### Backend — New Services

| Component | Responsibility |
|-----------|----------------|
| `PlanGenerationService` | Orchestrates LLM-based plan generation on agent type save; queries the role→SOP→Skill→Tool graph; constructs a detailed prompt with agent context (instructions, role, SOPs, skills, tools); invokes the configured LLM; parses LLM response into structured plan steps; calls `TopologyBuilderService`; upserts the `AgentPlan` row; handles failures non-blocking by catching exceptions and writing a `failed` status record |
| `TopologyBuilderService` | Accepts the resolved role→SOP→Skill→Tool graph and serializes it as a dict with `nodes` (id, type, label, meta) and `edges` (source, target, label); assigns deterministic node IDs for stable rendering |

### Backend — Modified Services

| Component | Responsibility |
|-----------|----------------|
| `AgentRuntimeLoader` | Extended to load the saved plan from `agent_plans` table when initializing an agent session; injects the plan into the agent's system context (LLM prompt) to guide execution; if no plan exists, agent runs without plan guidance (graceful degradation) |

### Backend — Modified Schemas

| Component | Responsibility |
|-----------|----------------|
| `PlanStepRead` | Pydantic schema for a single plan step: `order`, `type`, `name`, `description` |
| `TopologyNodeRead` | Pydantic schema for a topology node: `id`, `type`, `label`, `meta` |
| `TopologyEdgeRead` | Pydantic schema for a topology edge: `source`, `target`, `label` |
| `AgentPlanRead` | Pydantic schema for the full plan record; embeds `plan_steps`, `topology_nodes`, `topology_edges`, status, error, hash |
| `AgentTypeRead` | Extended with optional `plan: AgentPlanRead | None` field populated from the ORM relationship |

### Backend — Modified API Handlers

| Component | Responsibility |
|-----------|----------------|
| `POST /agents/types` handler | After committing the new agent type, calls `PlanGenerationService.generate_plan()`; the `AgentTypeRead` response automatically includes the plan via the ORM relationship |
| `PUT /agents/types/{type_id}` handler | Same as above after a successful update commit |

### Frontend — New Components

| Component | Responsibility |
|-----------|----------------|
| `PlanPreviewModal` | MUI Dialog opened after a successful agent type save; displays plan steps as an ordered list with step-type chips; hosts `TopologyDiagramRenderer`; shows error state when `generation_status = failed`; follows Dialog Error Handling Standard |
| `TopologyDiagramRenderer` | Renders the node-edge topology payload as a visual diagram; distinguishes node types (role, sop, skill, tool) by colour/icon; handles empty state gracefully |

### Frontend — Modified Components

| Component | Responsibility |
|-----------|----------------|
| `AgentManagementPage` | After a successful save, reads `plan` from the response, stores it in local state, and opens `PlanPreviewModal`; clears plan state on modal close |

### Frontend — New Types

| Component | Responsibility |
|-----------|----------------|
| `AgentPlanStatus` | Type alias: `'pending' | 'success' | 'failed'` |
| `PlanStep` | Interface for a plan step: `order`, `type`, `name`, `description` |
| `TopologyNode` | Interface for a topology node: `id`, `type`, `label`, `meta` |
| `TopologyEdge` | Interface for a topology edge: `source`, `target`, `label` |
| `AgentPlan` | Interface for the full plan record; mirrors `AgentPlanRead` |

---

## API Changes

### Modified Endpoints

Both agent type create and update endpoints have their response shape extended. No new routes are added.

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/api/v1/agents/types` | Response body gains `plan: AgentPlanRead \| null`; side-effect: `PlanGenerationService` is called after commit |
| `PUT` | `/api/v1/agents/types/{type_id}` | Same response extension; plan is regenerated on every update |

### Response Shape Extension

The `AgentTypeRead` schema gains an optional `plan` field. When plan generation succeeds, the field is populated with the full `AgentPlanRead` payload. When generation fails (or the agent type has no role assigned), `plan` is either null or has `generation_status = failed` with a `generation_error` message. Clients should treat the field as always-optional and never assume it is present.

---

## State Management

### `AgentManagementPage` — new state

| State variable | Type | Purpose |
|----------------|------|---------|
| `planData` | `AgentPlan \| null` | Holds the plan returned from the most recent save response |
| `planModalOpen` | `boolean` | Controls visibility of `PlanPreviewModal` |

Lifecycle:
- Set to the response `plan` value (and modal opened) immediately after a successful `apiClient.post` or `apiClient.put` call, before `setDialogOpen(false)`.
- Cleared (`null`, modal closed) when the user dismisses the `PlanPreviewModal`.
- No persistence required — the plan is re-fetched on every save.

### `PlanPreviewModal` — no internal async state

The modal receives `plan` as a prop directly from `AgentManagementPage`. No internal API calls or async effects are required; all data is available at open time.

---

## Data Access Patterns

### Plan data flows inline with the save response

`PlanGenerationService` is called synchronously within the save request handler, and the resulting `AgentPlan` row is loaded from the ORM relationship before serialization. The frontend receives the plan in the same HTTP response as the saved agent type — no second request is made.

This approach is intentional: the plan is valid at save time, the latency addition is bounded (graph traversal is a small read-only query), and it avoids the complexity of polling or websocket delivery for a config-time operation.

### Frontend reads plan from the save response only

The frontend does not fetch `AgentPlan` records independently. The `useAgentTypes` list query does not include the `plan` field; the plan is only present in the create/update response payload. If the user navigates away and returns, the plan preview is not re-displayed — it only appears on the next save.

### Plan staleness detection (backend only)

`PlanGenerationService` computes an `agent_config_hash` from the agent's `role_id`, `primary_sop_id`, and `system_instruction`. This hash is stored on the `AgentPlan` row and can be used in future work to detect whether a stored plan is stale without regenerating it. It is not used by the frontend in this change.

---

## Code Reference Map

### Backend Models

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentPlanStatus` | str enum | `pending \| success \| failed` | `backend/app/db/models/agents.py` |
| `AgentPlan` | model | Persists generated plan and topology for an agent type; FK → `agent_types` (unique, CASCADE) | `backend/app/db/models/agents.py` |
| `AgentType` | model | Extended — adds `plan` relationship (`uselist=False`) to `AgentPlan` | `backend/app/db/models/agents.py` |

### Backend Schemas

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PlanStepRead` | Pydantic model | Single plan step: `order`, `type`, `name`, `description` | `backend/app/schemas/agents.py` |
| `TopologyNodeRead` | Pydantic model | Topology node: `id`, `type`, `label`, `meta` | `backend/app/schemas/agents.py` |
| `TopologyEdgeRead` | Pydantic model | Topology edge: `source`, `target`, `label` | `backend/app/schemas/agents.py` |
| `AgentPlanRead` | Pydantic model | Full plan record with embedded steps, topology, status, error, hash | `backend/app/schemas/agents.py` |
| `AgentTypeRead` | Pydantic model | Extended — gains `plan: AgentPlanRead \| None` field | `backend/app/schemas/agents.py` |

### Backend Services

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PlanGenerationService` | class | Orchestrates LLM-based plan generation on save; constructs prompt with agent context; invokes LLM; parses response; traverses role→SOP→Skill→Tool graph; upserts `AgentPlan`; non-blocking error handling | `backend/app/services/agents/plan_generation_service.py` |
| `TopologyBuilderService` | class | Converts role→SOP→Skill→Tool graph to `nodes`/`edges` topology dict; deterministic node IDs | `backend/app/services/agents/topology_builder_service.py` |
| `AgentRuntimeLoader` | class | Modified — loads saved plan from `agent_plans` on session init; injects plan into system context for execution guidance | `backend/app/services/agents/runtime_loader.py` |

### Backend API

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTypeRouter` | router | Modified — create and update handlers call `PlanGenerationService` after commit | `backend/app/api/v1/agents.py` |

### Alembic Migration

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `add_agent_plans` | migration | Creates `agent_plans` table with all columns, unique constraint on `agent_type_id`, and FK to `agent_types` with CASCADE delete | `backend/alembic/versions/fcbe5b250e08_add_agent_plans.py` |

### Frontend Types

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `AgentPlanStatus` | type alias | `'pending' \| 'success' \| 'failed'` | `frontend/src/types/index.ts` |
| `PlanStep` | interface | `order`, `type`, `name`, `description` | `frontend/src/types/index.ts` |
| `TopologyNode` | interface | `id`, `type`, `label`, `meta` | `frontend/src/types/index.ts` |
| `TopologyEdge` | interface | `source`, `target`, `label` | `frontend/src/types/index.ts` |
| `AgentPlan` | interface | Full plan record; mirrors `AgentPlanRead` | `frontend/src/types/index.ts` |
| `AgentType` | interface | Extended — gains optional `plan?: AgentPlan \| null` field | `frontend/src/types/index.ts` |

### Frontend Components

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PlanPreviewModal` | component | MUI Dialog displaying plan steps and topology diagram after agent type save | `frontend/src/components/agents/PlanPreviewModal.tsx` |
| `TopologyDiagramRenderer` | component | Renders node-edge topology payload as SVG/Canvas visual diagram; distinguishes node types by colour or icon | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |
| `AgentManagementPage` | component | Modified — handles `plan` field from save response; manages `planData` and `planModalOpen` state; renders `PlanPreviewModal` | `frontend/src/pages/agents/AgentManagementPage.tsx` |

### Frontend i18n

| Symbol | Kind | Description | File |
|--------|------|-------------|------|
| `agents.plan.*` | translation namespace | All plan preview UI strings: title, step types, node types, error states, close button | `frontend/src/i18n/locales/en.json` |

### Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_topology_builder_service` | unit test module | Happy path, empty graph, node ID stability, duplicate tool deduplication | `backend/tests/unit/services/test_topology_builder_service.py` |
| `test_plan_generation_service` | unit test module | Happy path, error path (non-blocking), hash stability, no-role case, LLM timeout handling | `backend/tests/unit/services/test_plan_generation_service.py` |
| `test_agent_types_plan` | integration test | Schema verification, unique constraint, CASCADE delete, save-response shape, upsert behaviour, failed generation path | `backend/tests/integration/api/test_agent_types_plan.py` |
| `PlanPreviewModal.test` | frontend component test | Renders plan steps, error state, close callback, hidden when closed, Dialog Error Handling Standard | `frontend/src/__tests__/PlanPreviewModal.test.tsx` |
| `TopologyDiagramRenderer.test` | frontend component test | All four node types rendered, empty state, unknown extra fields, snapshot | `frontend/src/__tests__/TopologyDiagramRenderer.test.tsx` |
| `AgentManagementPage.test` | frontend component test | Plan modal opens after save, plan data set from response, modal cleared on close, graceful null plan handling | `frontend/src/__tests__/AgentManagementPage.test.tsx` |
| `agent-plan-mode.spec` | E2E test | Create/update/failed-plan journeys (mocked); viewport tests; Real Backend Integration suite (no mocks) | `e2e/tests/agent-plan-mode.spec.ts` |
