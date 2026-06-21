# PRD: Enhance Agent Output System

## Epic Overview

Currently, agent types define their input/output inline with no structured type system, and agent execution results are saved without any schema enforcement or type-based discoverability. This means downstream consumers — whether human operators reviewing execution logs, automated workflows querying past results, or analysis agents trying to reason across outputs — have no reliable way to interpret, filter, or compare agent results. This change introduces a centralized Agent Data Type registry where users define reusable typed schemas for agent outputs, enforces those schemas at execution time for non-conversational agents, renders results in a schema-aware UI within execution logs, provides a dedicated Agent Outputs admin page for querying and browsing past results, and exposes a `query_result` system tool so agents can retrieve and analyze past typed outputs. This transforms agent outputs from opaque blobs into first-class typed artifacts that the entire platform can work with.

---

## Business Goals

- Enable platform operators to define reusable output schemas once and apply them consistently across multiple agent types, reducing configuration duplication and schema drift.
- Provide operators with the ability to browse, filter, and search past agent outputs by data type, date range, and agent type from a dedicated admin page.
- Eliminate the need for manual workarounds (copy/paste, external tools) to interpret or collate results across multiple agent runs.
- Enable the creation of result-analysis agent types that can programmatically query past outputs using the `query_result` system tool, unlocking agent-to-result analysis workflows.
- Ensure execution log viewers always see agent outputs rendered in a user-friendly format matching the data type's field schema, not raw JSON.

---

## Users & Personas

**Platform Administrators** — Design and maintain the data type registry; configure which output type each agent type uses; query agent outputs across the platform for operational review.

**Operator / Business Users** — Review agent execution results in the execution log dialog and the Agent Outputs page; need schema-aware rendering to interpret results quickly.

**SOP Authors / Agent Designers** — Configure agent types to use typed outputs; design agent workflows that leverage `query_result` to retrieve and act on past typed results.

**Compliance / Audit Staff** — Need to search and retrieve agent outputs by type and time range for audit evidence and regulatory review.

---

## User Stories

- As a **Platform Administrator**, I want to create reusable data types in a centralized registry with typed fields, so that I can apply the same output schema to multiple agent types without duplicating field definitions.
- As a **Platform Administrator**, I want to edit and delete data types from the registry, so that I can maintain the schema catalogue as business requirements evolve.
- As a **Platform Administrator**, I want to assign a data type as the output type of a non-conversational agent type, so that the agent's results are validated and stored against that schema.
- As an **Operator**, I want the execution log dialog to render agent output formatted according to its data type schema, so that I can read the result in a structured, field-by-field layout instead of raw JSON.
- As an **Operator**, I want to browse and query all past agent outputs from a dedicated Agent Outputs page, filtering by data type, date range, and agent type, so that I can find results without opening individual execution logs.
- As an **SOP Author**, I want to instruct agents to call `query_result` to retrieve past outputs by data type, so that I can build analysis agents that reason across multiple prior results.
- As a **Compliance Auditor**, I want to see which data type schema was used for each saved agent result, so that I can verify output format compliance.
- As a **Platform Administrator**, I want the `save_result` tool to persist outputs together with their data type schema reference, so that saved results are typed and queryable.

---

## Acceptance Criteria

### Agent Data Type Registry (CRUD)

- User can create a new data type with a unique name, description, and a set of typed fields (string, number, boolean, date, enum).
- Created data type appears in the data types list immediately with all fields displayed correctly.
- User can edit an existing data type's fields and metadata.
- After editing, the data types list refreshes with updated values without requiring manual page reload.
- User can delete a data type with a confirmation dialog; deletion is blocked if any agent type currently references it (with a clear message identifying which agent types use it).
- Deleted data type is removed from the list and its name becomes available for reuse.
- System rejects duplicate data type names with a clear error message.
- System enforces at least one field per data type and rejects empty data type definitions.

### Agent Type Output Assignment

- The Agent Type create/edit form includes an "Output Data Type" field allowing selection from the data type registry.
- Only non-conversational agent types show the output data type field (conversational agents do not support typed outputs).
- When an output data type is assigned, the agent type's output type is set to `typed` and the schema is linked.
- The output type badge in the Agent Types list shows the assigned data type name.

### Typed Agent Execution

- When a non-conversational agent with a defined output type completes execution, the result is validated against the data type schema.
- If the output does not match the expected schema, the execution completes but the result is flagged with a schema validation error, visible in the execution log.
- If validation passes, the typed result is saved to the result database with a reference to the data type schema.
- The `save_result` system tool enhanced to accept and persist typed outputs with the agent's assigned data type.

### Execution Log Display (Typed Output)

- The execution log dialog's Result tab renders typed agent output as a structured field-by-field view following the data type schema.
- Each field is labeled with its field name and displays the value formatted according to its type (boolean as toggle, date as formatted date, enum as chip, etc.).
- The Result tab label includes the data type name badge (e.g., "Result [IncidentReport]").
- If schema validation failed, the validation error is displayed prominently in the Result tab with the raw output shown as fallback.

### Agent Outputs Admin Page

- A dedicated "Agent Outputs" page is available in the admin navigation.
- The page displays a filter bar with: data type selector, date range picker, and agent type selector.
- Results are displayed in a table with columns: timestamp, agent type, data type, field values (flattened into columns based on the selected data type), status (valid/validation error).
- Clicking a row opens a detail panel or dialog showing the complete output with full field rendering.
- The results refresh when filter criteria change.
- Pagination is supported for large result sets.
- CSV export is available for filtered results.

### `query_result` System Tool

- A new `system____query_result` tool is available to all agents by default.
- Agents call the tool with a data type name and optional filters (date range, specific field values).
- The tool returns a list of matching typed results conforming to the requested data type schema.
- This enables result-analysis agent types: an agent can query past outputs and reason across them.
- The tool follows the same explicit-trigger pattern as `save_result` — it must be referenced in agent instructions or SOPs to be used.

### Error Handling

- Validation errors during data type creation/editing are shown inline in the form.
- If data type lookup fails during execution, the agent run completes with a warning logged.
- Network errors on the Agent Outputs page display a clear message with a retry option.
- If an agent calls `query_result` with an invalid data type name, a descriptive error is returned.

---

## Out of Scope

- Typed outputs for conversational agents — only non-conversational agents are in scope.
- Real-time streaming of typed results — results are available after execution completes.
- Data type versioning or schema migration — data types are edited in place; existing results retain their original schema snapshot.
- Visual diagram or drag-and-drop schema builder — fields are added via a structured form.
- Automated schema generation from prompts or LLM output — data types are manually defined by administrators.
- Export integrations to external systems (e.g., data warehouse, S3) — CSV export from the UI is the only export mechanism.
- Changes to the conversation history store or how conversational interactions are persisted.

---

## Dependencies & Constraints

- The existing `save_result` system tool and result repository must be extended to support typed output storage — backwards compatibility with untyped results must be maintained.
- The Agent Execution Log viewer component must be updated to detect and render typed outputs using the data type schema.
- Agent Runtime must have access to the data type registry (via Control Center API) to perform schema validation at execution completion.
- The `query_result` system tool must be secured so agents can only query results they are authorized to access (based on agent type or role permissions).
- Must comply with existing service segregation rules: Control Center owns the data type registry; Agent Runtime calls read-only validation endpoints.
- Must preserve all existing untyped agent types and execution workflows — only agent types with an explicitly assigned data type are affected.
