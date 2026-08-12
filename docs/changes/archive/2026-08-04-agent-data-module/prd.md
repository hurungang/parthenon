# Agent Data Module — PRD

## Epic Overview

Agents use the `save_data` system tool to persist intermediate named data during execution, and `get_data` to retrieve it. Currently this data is only accessible via internal system tools (mTLS-protected) — there is no public UI for operators to view saved agent data. Meanwhile, the Agent Trails page has a "Results" tab showing legacy `ResultRecord` data that predates the Agent Outputs system.

This change introduces a new "Agent Data" module that surfaces intermediate agent data (`AgentData` model) in a filterable table UI with the same UX pattern as the existing Agent Outputs module. It simultaneously removes the obsolete "Results" tab from Agent Trails, consolidating the results/output/data story into two clean modules: Agent Outputs (final structured outputs) and Agent Data (intermediate named data).

## Business Goals

- **Close the observability gap** — Operators can now see what intermediate data agents produced during execution, not just final outputs
- **Remove dead UI** — Eliminate the legacy "Results" tab that queries deprecated `ResultRecord` data
- **Consistent UX** — Agent Data follows the same filter/table/detail pattern as Agent Outputs, reducing learning curve

## Users & Personas

- **Platform Operators** — Monitor agent execution data, verify intermediate results, debug agent behavior
- **Agent Builders** — Inspect the data their agents save to validate correct behavior

## User Stories

- As a platform operator, I want to browse all intermediate data saved by agents so that I can inspect and debug agent execution data
- As a platform operator, I want to filter agent data by data name and agent type so that I can quickly find relevant records
- As a platform operator, I want to see the full JSON value of a saved data record in a detail drawer so that I can inspect the complete payload
- As an operator, I no longer want to see a "Results" tab showing obsolete data that has been superseded by Agent Outputs

## Acceptance Criteria

### Agent Data Module
- A new "Agent Data" page exists at `/admin/agent-data` accessible from the sidebar under the Agents group
- The page displays a table of `AgentData` records with columns: Timestamp, Data Name, Agent Type, Session ID, Data Type
- Filters support filtering by data name (text) and agent type (dropdown)
- Pagination is supported
- Clicking a row opens a detail drawer showing the full `data_value` JSON and metadata
- API endpoints require `agent::data` resource type with `read` permission

### Results Tab Removal
- The "Results" tab is removed from the Agent Trails page (`/agent-trails`)
- The standalone `/results` route is removed or redirected
- The legacy `ResultRepositoryPage` component is archived/removed
- The obsolete `ResultRecord` model and `ResultStore` service remain in the codebase (no DB changes in this change)

### Permissions
- New resource type `RT_AGENT_DATA = "agent::data"` with action `read`
- Added to `ResourceTypeManifest` in both backend and frontend
- Added to `MODULE_GROUPS` under the `agent` module

## Out of Scope

- Creating/editing/deleting AgentData records from the UI (read-only)
- Removing the `ResultRecord` model or `ResultStore` service (future cleanup)
- CSV export for AgentData (can be added later)
- Data retention policies or TTL for AgentData
- Soft-delete / archive UX for AgentData

## Dependencies & Constraints

- Depends on the `AgentData` model already existing in `backend/app/db/models/agent_data.py`
- Depends on `AgentDataService` already existing in `backend/app/services/agent_data/service.py`
- Follows the same UI/API pattern as Agent Outputs (`AgentOutputsPage`, `agent_outputs.py` router)
- No database schema changes required (existing `agent_data` table is sufficient)
