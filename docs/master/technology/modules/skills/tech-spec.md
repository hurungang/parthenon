# Module: skills — Tech Spec

## Overview

The skills module defines the execution primitives that agents use to interact with external tools. A Skill is a named, permission-assignable unit that wraps one or more MCP tool calls; a Standard Operating Procedure (SOP) is a higher-level composition of multiple Skills with explicit sequencing logic. The module provides REST endpoints for managing both Skill and SOP records, a Skill Executor that resolves MCP tool bindings and invokes them via the MCP Proxy Engine, and a SOP Orchestrator that executes ordered SOP steps — delegating skill steps to the Skill Executor and agent-delegation steps back to the Agent Engine.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `SkillRouter` | FastAPI router providing full CRUD operations for Skill records; Skills are the smallest permission-grantable unit for agents |
| `SopRouter` | FastAPI router for creating, reading, updating, and deleting SOP records; also exposes step listing and full ordered-step replacement endpoints |
| `SkillExecutor` | Service class that resolves the MCP tool bindings for a named skill, verifies permissions, and invokes the tool calls via `McpProxyEngine`; supports single and chained tool sequences |
| `SopOrchestrator` | Service class that iterates over the ordered steps of a SOP, dispatching each skill step to `SkillExecutor` and each agent-delegation step to the Agent Engine; coordinates result passing between steps |
| `Skill` | SQLAlchemy model for a named, permission-assignable wrapper around one or more MCP tool calls |
| `Sop` | SQLAlchemy model for a Standard Operating Procedure; holds metadata and references to its ordered steps |
| `SopStep` | SQLAlchemy model for a single ordered step within a SOP; records the step type (skill invocation or agent delegation), target, and configuration |

### Frontend

| Component | Description |
|-----------|-------------|
| `SkillListPage` | Paginated skill list with search filter and quick-action toolbar for create, edit, and delete |
| `SkillEditor` | Create and edit form for skills with MCP tool binding multi-select and permission assignment controls |
| `SopListPage` | Paginated SOP list with search filter and quick-action toolbar |
| `SopEditor` | Create and edit SOP form with drag-and-drop step ordering and per-step type configuration |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/skills` | List all skills |
| `POST` | `/api/v1/skills` | Create a skill |
| `GET` | `/api/v1/skills/{skill_id}` | Get skill detail |
| `PUT` | `/api/v1/skills/{skill_id}` | Update a skill |
| `DELETE` | `/api/v1/skills/{skill_id}` | Delete a skill |
| `GET` | `/api/v1/sops` | List all SOPs |
| `POST` | `/api/v1/sops` | Create a SOP |
| `GET` | `/api/v1/sops/{sop_id}` | Get SOP detail |
| `PUT` | `/api/v1/sops/{sop_id}` | Update a SOP |
| `DELETE` | `/api/v1/sops/{sop_id}` | Delete a SOP |
| `GET` | `/api/v1/sops/{sop_id}/steps` | List steps for a SOP |
| `PUT` | `/api/v1/sops/{sop_id}/steps` | Replace the full ordered step list |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `SkillRouter` | router | CRUD endpoints for Skill management; all operations guarded by `require_permission(RT_SKILL, action)` | `backend/app/api/v1/skills.py` |
| `SopRouter` | router | CRUD and step management endpoints for SOPs; all operations guarded by `require_permission(RT_SKILL, action)` | `backend/app/api/v1/sops.py` |
| `SkillExecutor` | class | Resolves MCP tool bindings for a skill and invokes them via McpProxyEngine | `backend/app/services/skills/executor.py` |
| `SopOrchestrator` | class | Executes ordered SOP steps; dispatches to SkillExecutor or delegates to Agent Engine per step type | `backend/app/services/skills/sop_orchestrator.py` |
| `Skill` | model | SQLAlchemy model for a named, permission-assignable MCP tool wrapper | `backend/app/db/models/skills.py` |
| `Sop` | model | SQLAlchemy model for a Standard Operating Procedure | `backend/app/db/models/skills.py` |
| `SopStep` | model | SQLAlchemy model for an ordered step within a SOP | `backend/app/db/models/skills.py` |
| `SkillListPage` | component | Paginated skill list with search filter and quick-action toolbar | `frontend/src/pages/skills/SkillListPage.tsx` |
| `SkillEditor` | component | Create/edit skill with MCP tool binding multi-select and permission assignment | `frontend/src/pages/skills/SkillEditor.tsx` |
| `SopListPage` | component | Paginated SOP list with search filter and quick-action toolbar | `frontend/src/pages/skills/SopListPage.tsx` |
| `SopEditor` | component | Create/edit SOP with drag-and-drop step ordering and step type configuration | `frontend/src/pages/skills/SopEditor.tsx` |
