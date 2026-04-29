# Module: agents — Tech Spec

## Overview

The agents module is the central execution layer for AI agents on the platform. It manages the definition of agent types (either `sop-agent` or `skillful-agent`), enforces per-type concurrent instance limits, binds agent types to their configured LLM provider and model, and dispatches incoming prompts to the appropriate executor. The `SopAgentExecutor` runs a bound SOP through the SOP Orchestrator; the `SkillfulAgentExecutor` runs a reasoning loop in which the LLM selects from available skills and the Skill Executor invokes them.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `AgentTypeRouter` | FastAPI router for full CRUD operations on AgentType definitions; supports both `sop-agent` and `skillful-agent` modes with appropriate binding configuration |
| `AgentInstanceRouter` | FastAPI router for listing active instances for a given agent type and for force-terminating an instance by ID |
| `AgentInstanceManager` | Service class that spawns new agent instances on demand, enforces the `max_instances` cap per agent type, tracks lifecycle status transitions (created → running → closed), and destroys instances on explicit close or timeout |
| `ModelBindingLayer` | Service class that resolves LLM provider credentials and model configuration for an agent type, constructs the prompt payload, dispatches it to the LLM provider, and returns the structured response |
| `SopAgentExecutor` | Service class for `sop-agent` types; receives a user prompt and executes the agent's bound SOP via `SopOrchestrator`, passing the prompt as the execution context |
| `SkillfulAgentExecutor` | Service class for `skillful-agent` types; implements a reasoning loop in which the LLM selects from the agent's assigned skills, `SkillExecutor` invokes the selected tools, and results are fed back into the context until the LLM produces a final response |
| `AgentType` | SQLAlchemy model for an agent type definition; records the agent mode, model binding, skill or SOP assignment, max instance limit, and OIDC client configuration |
| `AgentInstance` | SQLAlchemy model for a runtime agent instance; records the parent type, current lifecycle status, session handle, and timing metadata |
| `AgentSkillAssignment` | SQLAlchemy join model linking a Skill to a `skillful-agent` type; determines which tools are available to the agent's reasoning loop |

### Frontend

| Component | Description |
|-----------|-------------|
| `useAgentTypes` | React Query hook that fetches and caches the agent type list from the Platform API |
| `AgentManagementPage` | Agent type list with creation workflow controls and an active instance status table per type |
| `AgentTypeForm` | Create and edit form for agent type definitions covering mode selection, model binding, SOP or skill assignment, and instance limit configuration |
| `GatewayConfigPage` | Gateway route list with endpoint URLs and transport option display per agent type |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/agents/types` | List all agent types |
| `POST` | `/api/v1/agents/types` | Create an agent type |
| `GET` | `/api/v1/agents/types/{type_id}` | Get agent type detail |
| `PUT` | `/api/v1/agents/types/{type_id}` | Update an agent type |
| `DELETE` | `/api/v1/agents/types/{type_id}` | Delete an agent type |
| `GET` | `/api/v1/agents/types/{type_id}/instances` | List active instances for a type |
| `DELETE` | `/api/v1/agents/instances/{instance_id}` | Terminate an agent instance |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AgentTypeRouter` | router | CRUD endpoints for AgentType definitions | `backend/app/api/v1/agents.py` |
| `AgentInstanceRouter` | router | Instance listing and force-termination endpoints | `backend/app/api/v1/agents.py` |
| `AgentInstanceManager` | class | Spawns and destroys agent instances; enforces max_instances per type; tracks lifecycle status | `backend/app/services/agents/instance_manager.py` |
| `ModelBindingLayer` | class | Resolves LLM provider config per agent type and dispatches prompts to the configured model | `backend/app/services/agents/model_binding.py` |
| `SopAgentExecutor` | class | Executes a sop-agent prompt by delegating to SopOrchestrator with the bound SOP | `backend/app/services/agents/sop_executor.py` |
| `SkillfulAgentExecutor` | class | Executes a skillful-agent prompt via LLM reasoning loop with SkillExecutor invocations | `backend/app/services/agents/skillful_executor.py` |
| `AgentType` | model | SQLAlchemy model for an agent type definition (mode, model, bindings, instance limits) | `backend/app/db/models/agents.py` |
| `AgentInstance` | model | SQLAlchemy model for a runtime agent instance with lifecycle status and session handle | `backend/app/db/models/agents.py` |
| `AgentSkillAssignment` | model | SQLAlchemy join model linking a Skill to a skillful-agent type | `backend/app/db/models/agents.py` |
| `useAgentTypes` | hook | React Query hook for fetching and caching the agent type list | `frontend/src/hooks/useAgentTypes.ts` |
| `AgentManagementPage` | component | Agent type list, creation workflow, and active instance status table | `frontend/src/pages/agents/AgentManagementPage.tsx` |
| `AgentTypeForm` | component | Create/edit form for agent type definitions (mode, model, skill/SOP binding, limits) | `frontend/src/pages/agents/AgentTypeForm.tsx` |
| `GatewayConfigPage` | component | Gateway route list with endpoint URLs and transport option display per agent type | `frontend/src/pages/gateway/GatewayConfigPage.tsx` |
