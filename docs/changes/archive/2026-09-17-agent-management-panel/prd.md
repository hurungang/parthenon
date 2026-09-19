# PRD: Agent Management Panel

## Epic Overview

Configuring an agent in Parthenon today requires an administrator to work across many separate modules — Agent Roles, Agent Identities, Skills, SOPs, Agent Data Types, and Model Configurations — then assemble the pieces into an Agent Type. This context-switching is slow, error-prone, and obscures the full picture of what an agent is equipped with. The Agent Management Panel is a single, unified management module where an administrator can fully "equip" an agent: assign roles, attach an identity, add skills and SOPs, set input/output data types, and choose a model — all from one place. Missing resources can be created inline, and a live topology visualization shows the agent's full composition (including the Communication Hub) updating instantly as equipment changes. This shortens agent onboarding, reduces misconfiguration, and makes agent capabilities transparent at a glance.

## Business Goals

- Reduce the time to fully configure a new agent from scratch by at least 50% by eliminating navigation between modules (target: end-to-end setup completed inside one panel).
- Reduce agent misconfiguration incidents (e.g., identity not assigned to role, missing model) by 30% within three months of launch, by making the full composition visible and validated before saving.
- Increase administrator self-service: 100% of new agents can be stood up using only existing resources, only newly created resources, or any mix, with zero support-assisted setups.
- Zero duplication of management components — all inline creation reuses the existing module dialogs, forms, and selectors, keeping maintenance cost flat.
- Improve stakeholder comprehension: reviewers can read an agent's full composition from the topology visualization in under two minutes (target: 85% positive feedback in review/audit walkthroughs).

## Users & Personas

- **Agent Administrator (primary)** — platform team member who creates and maintains agent configurations. Needs to set up or modify an agent quickly, with or without pre-existing supporting resources, and to verify the composition visually before saving.
- **Operations Engineer** — manages model configurations and agent identities (OIDC sign-in/provisioning). Needs to add a new model config or provision a new identity at the moment the agent needs it, without switching modules.
- **Process / Business Owner (secondary)** — needs to understand what a given agent can do (its roles, skills, SOPs, data types, model) for review, compliance, and audit purposes. Consumes the topology view read-only.

## User Stories

- As an administrator, I want to create and configure an agent entirely from a single panel, so that I don't have to navigate across multiple modules.
- As an administrator, I want to assign an existing role to the agent or create a new role inline, so that I am never blocked by a missing role.
- As an administrator, I want to assign an existing agent identity or sign in / provision a new identity inline, so that the agent always has a working identity.
- As an administrator, I want to attach existing Skills and SOPs or create new ones inline and associate them, so that I can grant capabilities in one flow.
- As an administrator, I want to pick existing input/output types or create a new Agent Data Type inline, so that typed outputs are configured without leaving the panel.
- As an administrator, I want to choose an existing model configuration or add a new one inline, so that the agent can run on the right LLM immediately.
- As an administrator, I want the topology visualization to update immediately as I change equipment — before saving — so that I can see exactly what I am about to persist.
- As an administrator, I want to switch between agents and see each agent's topology re-rendered, so that I can review and compare configurations quickly.
- As an administrator, I want the Communication Hub shown as a node in the agent topology, so that I understand how the agent connects to the platform at runtime.
- As a user with limited permissions, I want panel actions I am not allowed to perform to be clearly disabled or explained, so that I understand what is missing rather than encountering opaque errors.

## Acceptance Criteria

### Agent Configuration Lifecycle

- Administrator can create a new agent from the panel with the required fields (name, system instruction, and its equipment); the new agent appears in the agent list immediately with all values correctly displayed.
- Administrator can view the list of all agents they have access to from the panel, with all configuration fields and attached equipment shown accurately; filtering and search work correctly.
- Administrator can edit an existing agent from the panel; the form is pre-populated with current values; changes save successfully and are visible immediately.
- After closing any create/edit dialog, the parent panel and agent list automatically refresh to show updated data without a manual page reload.
- Administrator can delete an agent with a confirmation dialog; the agent is removed from the list immediately, related counts update, and a new agent can be created with the same name afterwards (proving true deletion).
- Validation errors are shown for invalid input; duplicate agent names are rejected with a clear message; required fields are enforced; permission errors are surfaced gracefully inside dialogs rather than failing silently.

### Inline Resource Creation (Roles, Identities, Skills/SOPs, Data Types, Models)

- From the panel, the administrator can assign an existing role or create a new role inline; the new role becomes available in the role selector immediately and is assignable to the agent without leaving the panel.
- From the panel, the administrator can assign an existing identity or sign in / provision a new identity inline; the new identity is immediately selectable for the agent.
- From the panel, the administrator can attach existing Skills/SOPs or create new ones inline; newly created Skills/SOPs are immediately associated with the agent.
- From the panel, the administrator can pick existing input/output types or create a new Agent Data Type inline; the new data type is immediately settable on the agent.
- From the panel, the administrator can choose an existing model or add a new model configuration inline; the new model is immediately selectable for the agent.
- Every inline creation dialog behaves identically (same fields, same validation, same error handling) to the corresponding dialog in its source module — the panel never offers a reduced or divergent variant.

### Topology Visualization

- The panel shows an agent topology graph with distinct icons representing each equipped role, identity, skill, SOP, input/output data type, model, and the Communication Hub.
- Whenever the administrator assigns, changes, or removes equipment in the panel, the topology updates visually immediately — without saving.
- Switching to a different agent re-renders the topology for that agent's current configuration.
- The existing agent preview topology in the Agent Types view is updated to also display the Communication Hub as a node, connected to the agent.

### Permissions

- Panel capabilities respect existing per-module permissions: a user lacking permission for a resource domain (e.g., roles) sees that action disabled or hidden with a clear explanation, and read access degrades gracefully instead of showing errors.

## Out of Scope

- Redesigning or altering the core functionality of the existing module pages (Agent Roles, Agent Identities, Skills, SOPs, Agent Data Types, Model Configurations) — they remain the single source for standalone management of those resources.
- Changes to permission resolution logic, the identity provider, or the Communication Hub's runtime behaviour — the panel only visualizes and references existing resources.
- Batch operations on multiple agents, agent templates/cloning, or import/export of agent configurations.
- Agent execution, scheduling, or monitoring features (covered by existing execution and runtime modules).
- Removing or un-provisioning identities in the identity provider from the panel.

## Dependencies & Constraints

- Depends on existing management modules and their components: the panel must REUSE the existing dialogs, forms, and selectors from Agent Roles, Agent Identities, Skills/SOPs, Agent Data Types, and Model Configurations — duplication of these components is explicitly prohibited.
- Identity provisioning/sign-in inline depends on a reachable and configured OIDC provider (Keycloak or Azure EntraID); behaviour when the provider is unavailable must be handled gracefully.
- Inline creation and assignment of every resource is subject to the existing platform permission model (module-scoped resource types); the panel cannot grant capabilities beyond the user's permissions.
- The Communication Hub must be representable as a node in topology graphs for both the existing agent preview topology and the new panel topology.
- Existing platform UI standards apply: all visible text must be localized through the platform's standard localization mechanism (no hardcoded text), and the panel must match the platform's established look and feel.
- Agent Data Type rules apply as-is: conversational agents do not support typed outputs, and data types cannot be deleted while referenced by agent types.
