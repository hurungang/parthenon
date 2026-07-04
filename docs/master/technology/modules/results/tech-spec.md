# Module: results — Tech Spec

## Overview

The results module provides persistent storage for structured outputs produced by agents and SOP executions. The `ResultRecord` model and `ResultStore` service retain existing data and operator-facing query endpoints, but `save_result` has been **removed from the active agent tool path** — agents now use `save_data` (intermediate named saves to `AgentData`) and final session output is persisted by the runtime executor. Stored results remain queryable through REST endpoints.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `ResultStore` | Service class that persists structured result records to the database; decoupled from the active agent tool path (`save_result` replaced by `save_data` for intermediate saves and runtime executor for final output) |
| `ResultRouter` | FastAPI router exposing filtered listing of result records and detailed retrieval of a single result by ID |
| `ResultRecord` | SQLAlchemy model for a structured agent or SOP output; stores the source agent instance, session handle, result payload, schema identifier, and creation timestamp |

### Frontend

| Component | Description |
|-----------|-------------|
| `ResultRepositoryPage` | Result record list with filter controls for agent type, date range, and schema; expands to a structured detail view for each record |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/results` | List result records (filterable by agent, session, date) |
| `GET` | `/api/v1/results/{result_id}` | Get full result record detail |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ResultStore` | class | Legacy service for `ResultRecord` persistence; decoupled from active agent tool path — no longer registers `save_result` as a platform MCP tool for agents | `backend/app/services/results/store.py` |
| `ResultRouter` | router | Query endpoints for filtered result listing and detailed record retrieval; guarded by `require_permission(RT_RESULT, "read")`; `RT_RESULT` was newly registered in this module's access-control change | `backend/app/api/v1/results.py` |
| `ResultRecord` | model | SQLAlchemy model for a structured agent/SOP output with payload, schema, and source metadata | `backend/app/db/models/results.py` |
| `ResultRepositoryPage` | component | Result record list with filter controls and structured detail view | `frontend/src/pages/results/ResultRepositoryPage.tsx` |
