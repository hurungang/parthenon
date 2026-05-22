# PRD: Agent-to-Agent Communication and Slug Enforcement

## Epic Overview
Parthenon needs first-class agent-to-agent collaboration so one agent can request work from another through the Communication Hub using the A2A protocol, while preserving security, lifecycle control, and auditability. This change also standardizes naming constraints by requiring slug-form identifiers for agent types, agent names, and MCP server names to prevent runtime and integration failures caused by spaces or special characters.

## Business Goals
- Reduce manual operator involvement by enabling automatic dynamic target-agent instance creation when an A2A target is unavailable.
- Improve cross-agent workflow completion rate by supporting continuous same-session conversations until requester-driven disconnect.
- Decrease naming-related runtime errors by enforcing slug validation across agent and MCP naming surfaces.
- Improve SOP authoring governance by deriving agent-to-agent associations and permissions directly from existing SOP step definitions, aligned with current skill/tool permission derivation.
- Improve operator visibility by rendering both plan list and topology diagram for agent-delegation steps in preview surfaces.

## Users & Personas
- Platform Administrator: Configures agent roles, permissions, SOPs, and agent types.
- SOP Author / AI Operations Engineer: Designs and manages multi-step SOP flows, including delegation to other agents.
- Agent Runtime Operator: Monitors runtime-created dynamic agent instances and session behavior.
- Compliance and Security Stakeholder: Verifies explicit permission boundaries for inter-agent operations.

## User Stories
- As a SOP author, I want agent-delegation step definitions to automatically generate allowed target-agent associations and permissions so delegation policy stays consistent with skill/tool derivation.
- As an agent runtime, I want to auto-create a target agent instance when unavailable so that A2A requests do not fail prematurely.
- As a requesting agent, I want to continue conversation with the dynamically created target in the same session so that work can complete without context loss.
- As a platform admin, I want agent type names, agent names, and MCP server names to be slug-only so that integrations and routing remain stable.
- As an admin editing agent roles, I want to preview all allowed agent type slugs so that role scope is understandable before saving.
- As an admin reviewing execution plans, I want agent-delegation steps rendered in both plan list and topology diagram views, similar to MCP tool planning visibility.

## Acceptance Criteria
- A2A requests route through Communication Hub using agent type slug as target identity input.
- If no active target agent instance exists, runtime creates a dynamic receiver instance and binds it to the requesting session.
- Requesting and receiving agents exchange A2A messages in the same session until requester explicitly completes and disconnects.
- On A2A disconnect completion, the dynamic receiver instance is removed according to lifecycle rules.
- SOP permission model derives explicit A2A target-agent-type allow rules from SOP step definitions, using the same derivation pattern used for skills and MCP tools.
- Agent role edit dialog displays allowed agent type slug preview for the role.
- Plan preview surfaces render agent-delegation steps in both plan list and topology diagram.
- Agent type names, agent names, and MCP server names reject non-slug values (spaces and special characters) in creation and update flows.

## Out of Scope
- Introducing a new external protocol beyond the existing A2A contract.
- Redesigning global navigation or unrelated admin pages.
- Changing authentication architecture beyond required checks for A2A permission and identity validation.
- Reworking unrelated MCP session features.

## Dependencies & Constraints
- Depends on Communication Hub and Agent Runtime coordination for dynamic instance lifecycle.
- Depends on existing role/permission and SOP policy framework for A2A permission extension.
- Must preserve existing session tracking, audit logging, and observability conventions.
- Must maintain backward-safe behavior for existing SOPs that do not use A2A delegation.
