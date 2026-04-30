# Module: results — Tech Spec

## Overview

The results module provides persistent storage for structured outputs produced by agents and SOP executions. It exposes a `save_result` MCP tool that is registered on the platform and made available to all agents and SOPs, giving them a standardised mechanism to persist their final outputs. Stored results are queryable through REST endpoints that support filtering by agent type, session, date, and other criteria.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `ResultStore` | Service class that persists structured result records to the database; also registers the `save_result` MCP tool with the platform MCP Hub so that agents and SOPs can invoke it directly during execution |
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
| `ResultStore` | class | Persists structured result records; registers save_result as a platform MCP tool | `backend/app/services/results/store.py` |
| `ResultRouter` | router | Query endpoints for filtered result listing and detailed record retrieval; guarded by `require_permission(RT_RESULT, "read")`; `RT_RESULT` was newly registered in this module's access-control change | `backend/app/api/v1/results.py` |
| `ResultRecord` | model | SQLAlchemy model for a structured agent/SOP output with payload, schema, and source metadata | `backend/app/db/models/results.py` |
| `ResultRepositoryPage` | component | Result record list with filter controls and structured detail view | `frontend/src/pages/results/ResultRepositoryPage.tsx` |
