# Agent Data Type Registry

## Overview
The Agent Data Type Registry provides a centralized catalogue where platform administrators define reusable, typed output schemas — each composed of named fields with declared types (string, number, boolean, date, and enum). These data types serve as the single source of truth for structured agent output definitions across the platform. Once defined, a data type can be assigned to multiple non-conversational agent types, ensuring consistent output formatting, enabling schema-level validation at execution time, and powering structured rendering in execution logs and the Agent Outputs admin page. The registry includes lifecycle safeguards that prevent deletion of data types currently referenced by any agent type, protecting downstream consumers from broken schema references.

## Business Goals
- Eliminate schema duplication by providing one centralized, reusable data type catalogue that all agent types reference.
- Ensure consistency of agent output structures across the platform so operators and downstream systems can rely on predictable result formats.
- Simplify governance by giving administrators a single place to create, audit, and maintain output schemas.
- Protect data integrity by blocking deletion of data types that are in active use by agent types.

## Who Uses It
- **Platform Administrators**: Create, edit, and maintain the data type catalogue; govern which schemas are available for agent type assignment.
- **Agent Designers / SOP Authors**: Reference registered data types when configuring agent types to ensure outputs match expected schemas.
- **Compliance & Audit Staff**: Review the registry to verify which output schemas are in use and trace them back to consuming agent types.

## What It Does
- Provides a dedicated admin page for viewing, creating, editing, and deleting data types.
- Each data type has a unique name, an optional description, and a list of typed fields.
- Each field has a name and one of five types: string, number, boolean, date, or enum. Enum fields also define a set of allowed values.
- At least one field is required per data type; the registry enforces this on create and update.
- Duplicate data type names are rejected with a clear error message.
- Delete operations are blocked if one or more agent types currently reference the data type. The error message lists which agent types depend on it, so the administrator can reassign or remove those references before retrying deletion.
- Once a data type is deleted, its name becomes available for reuse as a new data type.
- After any create, edit, or delete operation, the data types list refreshes automatically without manual page reload.
- Agent types that reference a data type display the data type name as an output type badge in list and detail views.
- Conversational agent types cannot be assigned an output data type — the output type field is only available for non-conversational agent types.

## User Stories
- As a **Platform Administrator**, I want to create a new data type with named, typed fields, so that I can define a reusable output schema for my agent types.
- As a **Platform Administrator**, I want to edit an existing data type to add, remove, or modify fields, so that I can adapt schemas as business requirements change.
- As a **Platform Administrator**, I want to delete a data type that is no longer needed, so that I can keep the registry clean — but I expect the system to block deletion if any agent type still uses it, with a clear message identifying the dependents.
- As a **Platform Administrator**, I want the registry to reject duplicate data type names, so that naming conflicts are caught before they cause confusion.
- As an **Agent Designer**, I want to browse the registry to see which data types are available, so that I can choose the right schema when configuring a new agent type.

## Acceptance Criteria
- Administrators can create a new data type with a unique name, optional description, and at least one typed field (string, number, boolean, date, or enum with allowed values).
- Created data types appear immediately in the data types list with all fields correctly displayed.
- Administrators can open an existing data type for editing; the form pre-populates with current values.
- After saving edits, the data types list refreshes automatically to show updated values without manual page reload.
- Administrators can delete a data type after confirming a delete dialog.
- Deletion is blocked if any agent type references the data type; the error message clearly names the dependent agent types.
- After a successful deletion, the data type is removed from the list, and its name can be reused for a new data type.
- The system rejects data type creation without at least one field and rejects duplicate names with clear error messages.
- Enum fields enforce at least one allowed value; empty enum definitions are rejected.
- The data types list supports searching and browsing for registries with many entries.

## Out of Scope
- Data type versioning or schema migration history — edits are applied in place; past results retain the schema snapshot at the time of execution.
- Visual drag-and-drop schema builder — fields are added via a structured form.
- Automated schema generation from prompts or LLM output — data types are manually defined by administrators.
- Support for nested or composite field types — fields are flat (string, number, boolean, date, enum).
- Cascading deletion that automatically removes references from agent types — administrators must manually reassign agent types before deleting a referenced data type.

## Dependencies & Constraints
- The data type registry is owned by Control Center and served through its API.
- Agent Runtime reads data type schemas via Control Center API for execution-time validation; this is a read-only dependency.
- The Agent Type form (agent-types feature) depends on the registry to populate its output data type selector.
- Must comply with existing service segregation rules: Control Center owns the registry; Agent Runtime consumes it read-only.
- Data type names must be unique within the registry; the uniqueness constraint is enforced at the API layer.
