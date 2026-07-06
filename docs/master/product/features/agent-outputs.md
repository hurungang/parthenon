# Agent Outputs

## Overview
Agent Outputs introduces schema-validated, typed agent results as first-class platform artifacts. When a non-conversational agent type is assigned an output data type from the [Agent Data Type Registry](./agent-data-types.md), its execution results are validated against that schema and stored with a schema reference. This enables operators to browse, filter, and export typed agent outputs from a dedicated admin page, allows agents to programmatically query past typed outputs using the `query_result` system tool, and renders results in execution logs as structured field-by-field views instead of raw JSON. Untyped agent types and conversational agents continue to work as before — only agent types with an explicitly assigned data type are affected.

## Business Goals
- Give operators a dedicated, filterable view of all agent outputs across the platform — by data type, date range, and agent type — eliminating the need to open individual execution logs.
- Enable CSV export of filtered outputs so operators can share results with external stakeholders or import them into reporting tools.
- Unlock result-analysis agent workflows by providing a `query_result` system tool that lets agents retrieve and reason across past typed outputs.
- Improve operator comprehension of agent results by rendering typed outputs in a schema-aware, field-by-field layout in execution logs.
- Ensure every saved typed output carries a reference to its data type schema, making downstream audit, automation, and governance straightforward.

## Who Uses It
- **Operators / Business Users**: Browse and filter agent outputs from the Agent Outputs admin page; view structured results in execution logs; export filtered results as CSV.
- **SOP Authors / Agent Designers**: Design agent workflows that leverage `query_result` to build cross-session analysis and reporting agents.
- **Compliance & Audit Staff**: Search and retrieve typed outputs by data type and time range for audit evidence; verify schema compliance per result.
- **Platform Administrators**: Govern output type assignments and ensure the data type registry powers consistent output structures.

## What It Does

### Typed Output Persistence
- When a non-conversational agent with an assigned data type completes execution, the platform validates the result against the data type schema.
- On validation success, the typed result is saved with a reference to the data type, making it queryable by schema.
- On validation failure, the execution still completes, but a validation error is recorded and surfaced in the execution log alongside a raw-output fallback.
- Untyped agents (no assigned data type) and conversational agents continue to save results as before with no schema validation.

### Agent Outputs Admin Page
- A dedicated "Agent Outputs" page is available under the Agents group in the admin sidebar navigation.
- The page provides a filter bar with:
  - **Data type selector**: Filters results to a specific data type from the registry.
  - **Date range picker**: Scopes results to a custom time window.
  - **Agent type selector**: Filters results produced by a specific agent type.
- When a data type is selected, the results table adapts its columns to display that data type's fields as flattened columns, so operators see field values directly in the table.
- Each row shows the timestamp, agent type, data type, flattened field values, and a status indicator (valid or validation error).
- Clicking a row opens a detail panel showing the complete output rendered field-by-field according to the data type schema.
- Results refresh automatically when filter criteria change.
- Pagination is supported for large result sets.
- A CSV export button downloads the currently filtered results for external use.

### Execution Log Result Rendering
- In the execution log dialog, the Result tab detects whether the agent produced a typed output.
- For typed outputs, the tab renders a structured field-by-field view: each field displays its label, its value formatted by type (booleans as toggle indicators, dates as formatted dates, enums as chips, numbers and strings as-is).
- The Result tab label includes a badge showing the data type name (for example, "Result [IncidentReport]").
- If schema validation failed, a prominent validation error message appears in the Result tab, and the raw (unvalidated) output is shown as fallback.
- For the `auto` output type, the platform now performs content-type detection at render time: if HTML tags are detected, the content renders directly as rich HTML (bypassing markdown conversion); if no HTML tags are detected, the content continues through standard markdown rendering. This ensures HTML-rich agent responses display correctly instead of appearing as corrupted markdown or raw markup.
- All rendered result areas (typed, auto, and markdown) now include a maximize button that lets operators expand the output into a focused, full-content view for reviewing large or complex agent results without surrounding UI distractions.
- Untyped outputs continue to render as plain text or markdown, unchanged.

### query_result System Tool
- A new `system____query_result` tool is available to all agents by default.
- Agents call the tool with a data type name and optional filters (date range, specific field values).
- The tool returns a list of matching typed results conforming to the requested data type schema.
- This enables result-analysis agent types: an agent can query past outputs, compare them, identify trends, or generate summary reports — all within a single SOP.
- The tool follows the explicit-trigger pattern: it must be referenced in agent instructions or SOP steps to be used; it does not fire automatically.
- If an agent calls `query_result` with an invalid or non-existent data type name, a descriptive error is returned.

## User Stories
- As an **Operator**, I want to browse all typed agent outputs from a single admin page, filtering by data type, date range, and agent type, so that I can find and review results without opening individual execution logs.
- As an **Operator**, I want to export filtered results as CSV, so that I can share output data with colleagues or load it into reporting tools.
- As an **Operator**, I want the execution log Result tab to display typed agent output as a structured field-by-field view, so that I can read results quickly without interpreting raw JSON.
- As an **Operator**, I want to see a validation error warning in the execution log when an agent's output did not match its assigned schema, so that I know the result may need manual review.
- As an **SOP Author**, I want to instruct agents to call `query_result` to retrieve past typed outputs, so that I can build analysis agents that reason across multiple prior results.
- As a **Compliance Auditor**, I want to see the data type name for each saved agent result, so that I can verify output format compliance.
- As a **Platform Administrator**, I want typed output results to carry their data type schema reference, so that every saved result is traceable to its governing schema.

## Acceptance Criteria
- When a non-conversational agent with an assigned output data type completes execution, its result is validated against the data type schema.
- On validation success, the typed result is saved with the data type reference and is immediately queryable from the Agent Outputs page.
- On validation failure, the execution completes with a validation error recorded; the error is visible in the execution log and the raw output is available as fallback.
- The Agent Outputs page is accessible from the admin sidebar under the Agents group.
- Filtering by data type, date range, and agent type works correctly and refreshes the results table without manual page reload.
- When a data type filter is applied, the results table columns adapt to display that data type's fields.
- Clicking a result row opens a detail view with full field-by-field rendering per the data type schema.
- CSV export downloads filtered results with correct column headers and data.
- Pagination handles large result sets without performance degradation.
- The execution log Result tab renders typed outputs as a structured field view with per-field type-appropriate formatting.
- The Result tab label includes a data type name badge for typed outputs.
- Schema validation errors are displayed prominently in the Result tab with a raw output fallback.
- The `query_result` tool is available to all agents and returns typed results filtered by data type name and optional criteria.
- `query_result` returns a descriptive error when called with an invalid data type name.
- Untyped agent types and conversational agents continue to function without regression.

## Out of Scope
- Typed outputs for conversational agents — only non-conversational agents are in scope.
- Real-time streaming of typed results — results are available after execution completes.
- Data type versioning or automatic schema migration — existing results retain their original schema snapshot.
- Export integrations to external systems (data warehouse, cloud storage) — CSV export from the UI is the only export mechanism.
- Automatic re-validation of past results when a data type schema is edited — past results are not retroactively validated.
- Changes to conversation history storage or how conversational interactions are persisted.

## Dependencies & Constraints
- Depends on the [Agent Data Type Registry](./agent-data-types.md) as the source of truth for output schemas.
- Depends on the existing result repository to store typed outputs with schema references; backwards compatibility with untyped results must be maintained.
- The execution log viewer (agent-session-logs feature) must detect typed outputs and render the structured view.
- Agent Runtime must access the data type registry (via Control Center API) to perform schema validation at execution completion.
- The `query_result` tool must respect the agent's access scope; an agent can only query results it is authorized to see.
- Must comply with service segregation rules: Control Center owns the data type registry; Agent Runtime performs read-only validation.
- The Agent Outputs admin page must follow the existing admin UI patterns (filter bar, paginated table, detail dialog).
