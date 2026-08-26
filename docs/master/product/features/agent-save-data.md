# Agent Save Data and Historical Retrieval

## Overview

Parthenon provides agents with two distinct persistence paths: **save_data** for intermediate, optional snapshots captured during an execution session, and **final output** for the single, definitive result produced when a session completes. Alongside these persistence paths, two new retrieval tools — **get_data** and **get_output** — enable agents to query historical records across sessions. This clear separation eliminates ambiguity about what is an intermediate save versus what is the final deliverable, making agent behaviour more predictable, auditable, and useful for cross-session analysis.

## Business Goals

- Eliminate user confusion between intermediate agent saves and final execution outputs by providing distinct, well-named tools and retrieval paths.
- Enable agents to preserve named intermediate findings at any point during execution so that important context is never lost.
- Unlock cross-session and historical analysis use cases by giving agents the ability to query previously saved data and final outputs.
- Provide a consistent, predictable persistence model that simplifies agent design and reduces support requests.
- Support compliance and audit requirements by clearly separating supplementary saved data from final session outputs.

## Users & Personas

- **Agent Designers**: Need reliable tools to save intermediate findings during execution and query prior records to build richer, context-aware workflows.
- **Platform Administrators**: Need clear, predictable persistence behaviour to govern enterprise agent usage and audit historical records.
- **Business Analysts and Operations Leads**: Need access to trends and history across sessions to generate reports and performance insights.
- **Compliance and Audit Stakeholders**: Need clear separation of final outputs from supplementary saved data for traceability.

## Key Principles

### save_data — Intermediate Persistence

- Agents can call `save_data` zero or more times during a single execution session.
- Each saved record carries a user-defined name, a timestamp, the agent type, and the session context automatically attached by the platform.
- Saved data records are **optional** and **supplementary** — they do not affect whether the session is considered complete.
- This tool replaces the legacy `save_result` naming. All new agent configurations and documentation use `save_data`.

### Final Output — Session-Completion Artifact

- Each completed execution session produces exactly **one** final output, automatically captured by the platform at session completion.
- The final output is the definitive, deliverable result of the session.
- Final outputs are distinct from `save_data` records in both purpose and retrieval path.

### get_data — Query Saved Data History

- Agents can query previously saved supplementary data records using filters:
  - **data_name**: The name given when the data was saved.
  - **agent_type**: The type of agent that saved the data.
  - **session_id**: The specific session in which the data was saved.
- This tool is available to all agents by default and enables cross-session data reuse.

### get_output — Query Final Output History

- Agents can query previously captured final outputs using filters:
  - **agent_type**: The type of agent that produced the output.
  - **session_context**: The execution context or identifier associated with the session.
  - **date_range**: A time window to scope the query.
- This tool is available to all agents by default and enables trend analysis, reporting, and comparison across sessions.

### Result Repository (UI)

The **Result Repository** provides a centralized, read-only view of all persisted artifacts — final outputs and intermediate saved data — in the Web UI, supporting compliance review, operational triage, and cross-session analysis. It is browse-only: operators can inspect and search records but cannot edit or delete them from the UI.

## User Stories

- As an **agent designer**, I want to save named data at any point in a session using `save_data`, so that I can preserve important intermediate findings for later reuse.
- As an **agent designer**, I want to query previously saved data by name, agent type, or session using `get_data`, so that I can build workflows that leverage historical context.
- As an **analyst**, I want to query historical final outputs by timeframe and agent context using `get_output`, so that I can create trend reports and summaries.
- As an **operations lead**, I want agents to be able to retrieve and analyse prior outputs automatically, so that recurring reporting tasks can be automated.
- As a **platform administrator**, I want intermediate agent data to be stored and labelled separately from final outputs, so that governance and audits are unambiguous.

## Acceptance Criteria

- The platform presents and documents the intermediate-save capability as `save_data`; the legacy `save_result` name is no longer available to end users.
- Agents can save zero or more named data records during a single execution session, and each saved record is retrievable with visible metadata including name, timestamp, agent type, and session context.
- Agents can query saved data records using one or more filters (data name, agent type, session), and returned results match the requested filters.
- Agents can query historical final outputs using filters (agent type, session context, date range), and returned results reflect the requested time scope.
- Users can clearly distinguish, in product behaviour and terminology, that final output is a session-completion artifact while saved data is optional and can occur multiple times during execution.
- The `get_data` and `get_output` tools are available to all agents by default and return results consistent with the caller's access scope.
- Existing business workflows that rely on final output persistence continue to function without regression after this change.

## Out of Scope

- Editing or deleting saved data records from the UI (read-only repository)
- Data retention policies, automatic archival of old results, or retention governance expansion
- Export integrations to external data warehouse or cloud storage
- Migration of legacy `save_result` records to the `save_data` model
- Changes to how final output quality is generated, evaluated, or formatted
- New visualisation dashboards or advanced analytics interfaces beyond the retrieval capability itself
- Redesign of broader agent lifecycle orchestration, scheduling, or delegation behaviour

## Dependencies & Constraints

- Alignment across product, documentation, and enablement materials is required to ensure consistent terminology.
- Rollout depends on coordinated adoption by agent designers to replace prior naming usage in existing prompts and workflows.
- Enterprise audit and compliance expectations require clear semantic separation between final outputs and supplementary saved data.
- Change communications must minimise disruption for teams with established workflows referencing prior naming.
