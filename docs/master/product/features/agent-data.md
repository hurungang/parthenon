# Agent Data

## Overview
The Agent Data module gives platform operators a dedicated UI for browsing intermediate data that agents save during execution via the `save_data` system tool. Previously this data was only accessible through internal system APIs (mTLS-protected), creating an observability gap — operators could see final agent outputs but had no way to inspect the named intermediate snapshots agents produced along the way. The Agent Data module closes this gap with a filterable data table and detail drawer, following the same UX pattern as the existing Agent Outputs module so operators experience a consistent, familiar interface.

## Business Goals
- Close the observability gap between intermediate agent data and final outputs by providing a dedicated, user-facing data browser
- Give operators the ability to filter and search saved agent data by data name and agent type, reducing time spent hunting for records
- Enable deep inspection of saved data payloads through a detail drawer that renders the full JSON value alongside record metadata
- Match the existing Agent Outputs UI pattern so operators face no additional learning curve

## Who Uses It
- **Platform Operators**: Monitor agent execution data, verify intermediate results, and debug agent behaviour by browsing saved data across sessions
- **Agent Builders**: Inspect the intermediate data their agents save to validate correct behaviour during development and testing

## What It Does

### Agent Data Page
- A new "Agent Data" page is accessible from the sidebar under the Agents group, positioned after Agent Data Types and before Agent Outputs.
- The page displays a filterable, paginated table of records with columns: Timestamp, Data Name, Agent Type, Session ID, and Data Type.
- Operators can filter the table by data name (text search) and agent type (dropdown selector) to quickly locate relevant records.
- Clicking any row opens a detail drawer that shows the full JSON value of the saved data record alongside all metadata fields.

### Permissions
- Access to the Agent Data page is governed by the `agent::data` resource type with `read` permission, ensuring only authorized operators can view intermediate agent data.
- The permission is registered in the platform's resource type manifest and grouped under the Agent module, consistent with other agent-related permissions.

## User Stories
- As a platform operator, I want to browse all intermediate data saved by agents so that I can inspect and debug agent execution data without relying on internal APIs
- As a platform operator, I want to filter agent data by data name and agent type so that I can quickly find relevant records across many sessions
- As a platform operator, I want to see the full JSON value of a saved data record in a detail drawer so that I can inspect the complete payload and metadata

## Acceptance Criteria
- A new "Agent Data" page exists at the Agent Data admin route accessible from the sidebar under the Agents group
- The page displays a table of agent data records with columns: Timestamp, Data Name, Agent Type, Session ID, Data Type
- Filters support filtering by data name (text) and agent type (dropdown)
- Pagination is supported for large record sets
- Clicking a row opens a detail drawer showing the full JSON data value and record metadata
- The Agent Data page is hidden from users who do not have the `agent::data` read permission
- API endpoints require the `agent::data` resource type with `read` permission

## Out of Scope
- Creating, editing, or deleting AgentData records from the UI (read-only page)
- CSV export for AgentData records (can be added later if needed)
- Data retention policies or TTL for AgentData records
- Soft-delete or archive UX for AgentData
- Removal of the legacy `ResultRecord` model or `ResultStore` service from the codebase (future cleanup)

## Dependencies & Constraints
- Depends on the existing agent data persistence layer already in the platform
- Follows the same UI and API pattern as the Agent Outputs module to maintain consistency
- No database schema changes required — the existing data storage table supports all needed queries
- The Agent Data page must be integrated into the sidebar under the Agents group, after Agent Data Types and before Agent Outputs
