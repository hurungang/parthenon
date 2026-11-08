# PRD: Control Center Assistant Management Tool Coverage

## Epic Overview

The Control Center Assistant lets administrators manage platform resources (skills, SOPs, agent types, agent roles, agent identities, model configurations, schedules, data types, MCP servers) through conversation instead of the web UI. Today the assistant's management tools cover only a subset of what the web UI supports: update operations silently drop or reject fields the UI edit forms accept (e.g. an agent type's role assignment, input/output configuration, instructions, and guardrails), and some operations fail with unhelpful validation errors. The result is broken conversations in which the assistant asks the user to finish the job manually in the UI. This epic closes that gap: every create, read, and update operation available in the web UI must be completable end-to-end through conversation, so the assistant becomes a trustworthy, complete alternative management surface.

## Business Goals

- Eliminate "capability dead ends": 100% of web-UI-supported create/update/read operations for assistant-managed resource families are completable via conversation, with no assistant-reported missing capability.
- Reduce assistant task abandonment: conversations that currently end with "please do this in the UI" drop to near zero.
- Improve self-correction: when the assistant submits invalid input, it receives actionable validation feedback and completes the operation on retry without human troubleshooting.
- Maintain governance: every assistant-driven write still passes the existing preview-and-approval confirmation flow, with full audit parity with the web UI.
- Reduce duplicate work: administrators no longer need to switch to the web UI to finish changes started by the assistant.

## Users & Personas

- **Platform / Tenant Administrators** — manage agents, skills, SOPs, schedules, and integrations day-to-day; want to make quick changes conversationally without navigating forms.
- **Control Center Assistant (system agent)** — needs complete, precisely described management capabilities so it can execute user intent fully and recover from its own input mistakes.
- **Compliance & Security Reviewers** — need assurance that conversational changes follow the same approvals, permissions, and audit trail as the web UI, and that no deletion capability or credential exposure is introduced.

## User Stories

- As an administrator, I want the assistant to update every aspect of an agent type (its role assignment, input/output configuration, instructions, and guardrails) through conversation, so that I don't have to finish the change in the web UI.
- As an administrator, I want the assistant to update an agent identity's role assignments conversationally, so that I can manage agent access without switching tools.
- As an administrator, I want the assistant to create and update model configurations, MCP servers, schedules, skills, SOPs, and data types with the same completeness as the web UI forms, so that conversation is a full alternative to the UI.
- As an administrator, I want the assistant to show me a clear preview of exactly what will change (old → new) and ask for my approval before writing, so that I stay in control of every conversational change.
- As an administrator, when I give the assistant incomplete or invalid details, I want it to receive clear guidance and fix itself, so that the task completes without me diagnosing errors.
- As a compliance reviewer, I want conversational writes to enforce the same per-resource permissions as the web UI, so that no privilege escalation is possible through chat.

## Acceptance Criteria

- When the assistant updates an agent type's role and input/output configuration through conversation, the change applies fully and the assistant does not report missing capability.
- When the assistant updates an agent identity's role assignments through conversation, the assignments change exactly as approved.
- For every assistant-managed resource family, every field editable in the corresponding web UI create/update form can also be set or changed through conversation.
- Read/list operations through conversation return all information the corresponding web UI list and detail views show, so the assistant can answer questions accurately.
- Before any write, the assistant presents the canonical preview (operation, resource, and a field table showing old → new values for updates) and proceeds only after user approval; rejection or timeout writes nothing.
- Deletion of any resource is not available through the assistant's management tools.
- When the assistant submits an invalid request, it receives a specific, actionable error identifying the problem, and can complete the operation correctly on its next attempt without user intervention.
- Conversational operations run under the requesting user's permissions: a user lacking permission for a resource action gets a clear denial, and the assistant cannot perform it.
- Assistant-performed creates and updates appear in audit trails identically to the same operations performed via the web UI.
- Regression check: existing assistant capabilities (skill, SOP, schedule, model config, MCP server, data type management) continue working unchanged after the expansion.

## Out of Scope

- Deletion of any resource via the assistant (prohibited by policy).
- New web UI capabilities or form changes — the UI is the parity baseline, not a target of change.
- New resource families beyond those already registered for assistant management.
- Direct database access from the assistant or bypassing the Communication Hub → Control Center routing.
- Bulk/import operations, cross-tenant administration, or platform settings changes via conversation.
- Changes to the confirmation flow itself (preview format and approval intervention stay as-is).

## Dependencies & Constraints

- Confirm-before-write policy: all assistant create/update operations must go through the canonical preview plus approval intervention; deletion is never exposed.
- Service segregation (top-priority rules): assistant agents run only in Agent Runtime; only Control Center touches the database; agents never receive identity tokens or credentials.
- Permission parity: assistant management operations execute under the user's OAuth identity and enforce the same per-resource read/manage permissions as the web UI.
- The Control Center MCP entity (slug `cc`) is system-managed; the seeder is the only writer — tool grants and identifiers follow the existing allocation rules.
- Parity scope depends on the current web UI capabilities of each resource family; where the UI itself changes later, this epic's parity guarantee applies to the UI at implementation time.
- Validation feedback must be consumable by the assistant (structured and descriptive), but the confirmation experience for users must remain unchanged.
