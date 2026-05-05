# Module: skills — Tech Spec

## Overview

The skills module defines the execution primitives that agents use to interact with external tools. A Skill is a named, permission-assignable unit that wraps one or more MCP tool calls with an optional `instructions` text; a Standard Operating Procedure (SOP) is a higher-level composition of multiple Skills with explicit sequencing logic and its own `instructions` text. The module provides REST endpoints for managing Skill and SOP records (including role membership management), a Skill Executor for MCP tool invocation, and a SOP Orchestrator for ordered multi-step execution. SOP steps use `target_agent_type_id` for agent-delegation steps and `step_config` for per-step configuration; step types are `skill_invocation` and `agent_delegation`.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `SkillRouter` | FastAPI router for Skill CRUD; eager-loads `tool_bindings` to return `tool_ids` in all responses; includes role membership endpoints (`GET`/`PUT` `/skills/{id}/roles`) |
| `SopRouter` | FastAPI router for SOP CRUD and step management; accepts and returns `instructions` field; step replacement uses `target_agent_type_id` and `step_config`; includes role membership endpoints (`GET`/`PUT` `/sops/{id}/roles`) |
| `SkillExecutor` | Service class that resolves the MCP tool bindings for a named skill, verifies permissions, and invokes tool calls via `McpProxyEngine`; supports single and chained tool sequences |
| `SopOrchestrator` | Service class that iterates over ordered SOP steps, dispatching skill steps to `SkillExecutor` and agent-delegation steps to the Agent Engine; coordinates result passing between steps |
| `Skill` | SQLAlchemy model for a named, permission-assignable MCP tool wrapper; has `tool_bindings` relationship to `SkillToolBinding` |
| `SkillToolBinding` | SQLAlchemy join model between `Skill` and `McpTool` with sort ordering; used by `selectinload` to derive `tool_ids` in API responses |
| `Sop` | SQLAlchemy model for a Standard Operating Procedure; includes `instructions` Text column |
| `SopStep` | SQLAlchemy model for an ordered SOP step; uses `target_agent_type_id` (renamed from `delegate_agent_type_id`) and `step_config` JSON; step type is `SopStepType` enum |
| `SopStepType` | Python enum: `skill_invocation` (renamed from `skill`) and `agent_delegation` |

### Frontend

| Component | Description |
|-----------|-------------|
| `SkillListPage` | Skill list with tool count badges and assigned role chips; hosts `SkillEditor` as an in-page slide-in panel |
| `SkillEditor` | In-page skill editor: Basic Info fields (name, description, instructions), MCP Tools multi-select grouped by server, and Assign to Roles sidebar |
| `SopListPage` | SOP list with step count; hosts `SopEditor` as an in-page slide-in panel |
| `SopEditor` | In-page SOP editor: Basic Info + `instructions` field, ordered step cards with drag-and-drop reorder, step type selector, and SOP Details sidebar |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/skills` | List all skills; response items include `tool_ids` array |
| `POST` | `/api/v1/skills` | Create a skill; accepts `instructions` field |
| `GET` | `/api/v1/skills/{skill_id}` | Get skill detail; includes `tool_ids` array |
| `PUT` | `/api/v1/skills/{skill_id}` | Update a skill; accepts `instructions` field |
| `DELETE` | `/api/v1/skills/{skill_id}` | Delete a skill |
| `GET` | `/api/v1/skills/{skill_id}/roles` | List role IDs that include this skill (via `agent_role_skills`) |
| `PUT` | `/api/v1/skills/{skill_id}/roles` | Atomically replace skill's role membership; body: `{"role_ids": [uuid, ...]}` |
| `GET` | `/api/v1/sops` | List all SOPs |
| `POST` | `/api/v1/sops` | Create a SOP; accepts `instructions` field |
| `GET` | `/api/v1/sops/{sop_id}` | Get SOP detail; includes `instructions` and steps |
| `PUT` | `/api/v1/sops/{sop_id}` | Update a SOP; accepts `instructions` field |
| `DELETE` | `/api/v1/sops/{sop_id}` | Delete a SOP |
| `GET` | `/api/v1/sops/{sop_id}/steps` | List steps for a SOP |
| `PUT` | `/api/v1/sops/{sop_id}/steps` | Replace full ordered step list; uses `target_agent_type_id`, `step_config` |
| `GET` | `/api/v1/sops/{sop_id}/roles` | List role IDs that include this SOP (via `agent_role_sops`) |
| `PUT` | `/api/v1/sops/{sop_id}/roles` | Atomically replace SOP's role membership; body: `{"role_ids": [uuid, ...]}` |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SkillRouter` | router | Skill CRUD + role membership endpoints; eager-loads `tool_bindings`; guarded by `require_permission(RT_SKILL, action)` | `backend/app/api/v1/skills.py` |
| `SopRouter` | router | SOP CRUD + step management + role membership endpoints; guarded by `require_permission(RT_SKILL, action)` | `backend/app/api/v1/sops.py` |
| `list_skills` | endpoint function | Returns all skills with eager-loaded `tool_ids` via `selectinload(Skill.tool_bindings)` | `backend/app/api/v1/skills.py` |
| `get_skill` | endpoint function | Returns one skill with eager-loaded `tool_ids` | `backend/app/api/v1/skills.py` |
| `get_skill_roles` | endpoint function | Returns role IDs that include a given skill via `agent_role_skills` join table | `backend/app/api/v1/skills.py` |
| `set_skill_roles` | endpoint function | Atomically replaces skill's role membership (delete + insert) | `backend/app/api/v1/skills.py` |
| `replace_sop_steps` | endpoint function | Replaces full step list atomically; uses `target_agent_type_id`, `step_config` | `backend/app/api/v1/sops.py` |
| `get_sop_roles` | endpoint function | Returns role IDs that include a given SOP via `agent_role_sops` join table | `backend/app/api/v1/sops.py` |
| `set_sop_roles` | endpoint function | Atomically replaces SOP's role membership (delete + insert) | `backend/app/api/v1/sops.py` |
| `SkillCreate` | Pydantic schema | Skill creation payload; includes `instructions` field | `backend/app/schemas/skills.py` |
| `SkillUpdate` | Pydantic schema | Skill partial update payload; includes `instructions` field | `backend/app/schemas/skills.py` |
| `SkillRead` | Pydantic schema | Skill response schema; includes `tool_ids: list[uuid.UUID]` derived from `tool_bindings` | `backend/app/schemas/skills.py` |
| `SopCreate` | Pydantic schema | SOP creation payload; includes `instructions` field | `backend/app/schemas/skills.py` |
| `SopUpdate` | Pydantic schema | SOP partial update payload; includes `instructions` field | `backend/app/schemas/skills.py` |
| `SopRead` | Pydantic schema | SOP response schema; includes `instructions` field | `backend/app/schemas/skills.py` |
| `SopDetailRead` | Pydantic schema | SOP response with `instructions` and full `steps` list | `backend/app/schemas/skills.py` |
| `SopStepCreate` | Pydantic schema | Step creation payload; uses `target_agent_type_id`, `step_config`; default `step_type` is `skill_invocation` | `backend/app/schemas/skills.py` |
| `SopStepRead` | Pydantic schema | Step response schema; uses `target_agent_type_id`, `step_config` | `backend/app/schemas/skills.py` |
| `SkillExecutor` | class | Resolves MCP tool bindings for a skill and invokes them via McpProxyEngine | `backend/app/services/skills/executor.py` |
| `SopOrchestrator` | class | Executes ordered SOP steps; dispatches to SkillExecutor or delegates to Agent Engine per step type | `backend/app/services/skills/sop_orchestrator.py` |
| `Skill` | model | SQLAlchemy model for a named, permission-assignable MCP tool wrapper; has `tool_bindings` relationship to `SkillToolBinding` | `backend/app/db/models/skills.py` |
| `SkillToolBinding` | model | SQLAlchemy join model between `Skill` and `McpTool` with sort ordering | `backend/app/db/models/skills.py` |
| `Sop` | model | SQLAlchemy model for a Standard Operating Procedure; includes `instructions` Text column | `backend/app/db/models/skills.py` |
| `SopStep` | model | SQLAlchemy model for an ordered SOP step; uses `target_agent_type_id`, `step_config` JSON, and `SopStepType` enum | `backend/app/db/models/skills.py` |
| `SopStepType` | enum | Python enum: `skill_invocation` and `agent_delegation` | `backend/app/db/models/skills.py` |
| `Sop` (TS) | TypeScript interface | Frontend SOP type; includes `instructions` field | `frontend/src/types/index.ts` |
| `SopStep` (TS) | TypeScript interface | Frontend SOP step type; uses `target_agent_type_id`, `step_config` | `frontend/src/types/index.ts` |
| `SopStepType` (TS) | TypeScript union type | `'skill_invocation' \| 'agent_delegation'` | `frontend/src/types/index.ts` |
| `Skill` (TS) | TypeScript interface | Frontend skill type; extended with `tool_ids: string[]` | `frontend/src/types/index.ts` |
| `useSkillRoles` | hook | React Query hook fetching role IDs for a skill (`GET /skills/{skillId}/roles`) | `frontend/src/hooks/useSkills.ts` |
| `useSopRoles` | hook | React Query hook fetching role IDs for a SOP (`GET /sops/{sopId}/roles`) | `frontend/src/hooks/useSops.ts` |
| `SkillListPage` | component | Skill list with tool count badges and role chips; hosts `SkillEditor` in-page panel | `frontend/src/pages/skills/SkillListPage.tsx` |
| `SkillEditor` | component | In-page skill editor: name, description, instructions, MCP Tools multi-select grouped by server, role assignment sidebar | `frontend/src/pages/skills/SkillEditor.tsx` |
| `SopListPage` | component | SOP list with step count; hosts `SopEditor` in-page panel | `frontend/src/pages/skills/SopListPage.tsx` |
| `SopEditor` | component | In-page SOP editor: name, description, instructions field, step cards with drag reorder, step type selector | `frontend/src/pages/skills/SopEditor.tsx` |
