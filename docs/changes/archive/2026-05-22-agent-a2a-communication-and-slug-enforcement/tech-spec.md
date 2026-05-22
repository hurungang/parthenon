# Technical Specification: Agent-to-Agent Communication and Slug Enforcement

## Technical Overview
This change extends the current Communication Hub and Agent Runtime integration so agents can invoke other agents through A2A protocol using target agent type slugs as deterministic routing identifiers. The system adds dynamic receiver auto-provisioning when targets are unavailable, derives SOP-level A2A permissions from delegation step definitions, and enforces consistent slug validation across agent and MCP naming surfaces. Existing SOP editor flows are retained; preview surfaces are extended to render agent-delegation steps in both plan list and topology diagram.

## Component Breakdown
- Communication Hub A2A Router
  - Accepts A2A requests, resolves target by agent type slug, enforces permission gates, and dispatches to runtime endpoint.
- Agent Runtime Dynamic Receiver Provisioner
  - Creates receiver instances on demand and returns session binding metadata for same-session conversation continuity.
- A2A Session Link Tracker
  - Maintains requester-receiver relationship and lifecycle state until explicit disconnect cleanup.
- SOP Permission Evaluator
  - Reads delegation-step-derived allow policy and decides whether requester can invoke target agent type slug.
- SOP Step Derivation Engine
  - Converts `agent_delegation` steps into persisted agent association and permission mappings during SOP save/update.
- Shared Slug Validation Module
  - Provides normalized slug validation for agent type, agent name, and MCP server naming paths.
- Agent Plan Preview Renderer
  - Extends existing plan and topology rendering so agent-delegation steps are visible alongside skill/tool steps.
- Agent Role Allowed-Type Preview UI
  - Shows all allowed target agent type slugs tied to role policy.

## API Changes
- Internal Agent Runtime APIs
  - Add/extend endpoint or command path for target-agent availability resolution with create-on-miss semantics.
  - Add/extend endpoint or command path for dynamic receiver disconnect and cleanup.
- Communication Hub Internal Endpoints
  - Extend A2A dispatch payload to include target agent type slug and session-link metadata.
- SOP Management APIs
  - On save/update, derive and persist allowed target agent type mappings from `agent_delegation` step definitions.
- Agent Role APIs
  - Add response projection for allowed agent type slug preview in role edit contexts.
- Validation Behavior
  - Creation and update endpoints for agent types, agents, and MCP servers return validation errors for non-slug values.

## State Management
- Frontend state reuses existing SOP editor step state and adds derivation-aware save result handling.
- Frontend role editing state includes a derived and persisted preview list of allowed agent type slugs.
- Frontend plan preview state includes delegation step nodes and edges in list and topology rendering.
- Backend session state includes A2A link lifecycle markers (requested, active, disconnecting, removed).

## Data Access Patterns
- Backend service layer remains the system-of-record for A2A permission resolution and session lifecycle mutation.
- UI reads and writes SOP and role policy data through REST APIs; no direct database access.
- SOP save/update pipelines derive A2A permission associations from step definitions rather than separate manual mapping forms.
- Runtime lifecycle updates are coordinated through internal service calls between Communication Hub and Agent Runtime paths.
- Slug validation occurs in both frontend pre-submit checks and backend authoritative validation.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `PermissionManager` | class | Resolves access permissions for agent operations, including A2A extension points | `backend/app/services/agents/permission_manager.py` |
| `RuntimeExecutor` | class | Executes agent runtime workflow and session lifecycle orchestration | `backend/app/services/agents/runtime_executor.py` |
| `CommunicationHubClient` | class | Handles hub-side message and runtime coordination paths | `backend/app/agent_runtime/comm_hub_client.py` |
| `plan_generation_service` | module | Existing agent planning service that may incorporate A2A action planning semantics | `backend/app/services/agents/plan_generation_service.py` |
| `agent_data` | module | Internal API surface for agent-specific data operations and routing metadata | `backend/app/api/v1/internal/agent_data.py` |
| `session_data` | module | Internal API for session-bound state and lifecycle transitions | `backend/app/api/v1/internal/session_data.py` |
| `skills` | module | Skill and SOP related API layer where A2A permission fields may be surfaced | `backend/app/api/v1/skills.py` |
| `toolNaming` | utility | Frontend naming/slug formatting helpers reused for validation consistency | `frontend/src/utils/toolNaming.ts` |
| `SopEditor` | component | Existing SOP step editor where `agent_delegation` steps are authored and persisted | `frontend/src/pages/skills/SopEditor.tsx` |
| `AgentPlanContent` | component | Renders ordered plan steps and should include delegation steps in preview | `frontend/src/components/agents/AgentPlanContent.tsx` |
| `TopologyDiagramRenderer` | component | Renders plan topology and should include delegation nodes/edges | `frontend/src/components/agents/TopologyDiagramRenderer.tsx` |
| `AgentRoleDialog` | component | Agent role edit UI where allowed agent type slug preview is displayed | `frontend/src/pages/agents/AgentRoleDialog.tsx` |
| `AgentTypeDetailsDialog` | component | Agent type configuration UI where slug requirement is enforced and explained | `frontend/src/components/agents/AgentTypeDetailsDialog.tsx` |
| `test_permission_manager` | test module | Backend permission tests to extend for SOP A2A allow/deny behavior | `backend/tests/unit/test_permission_manager.py` |
