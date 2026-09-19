# Spec Change: Agent Management Panel

## Affected Spec Areas

- `docs/master/product/features/agent-management.md` — Agent Types module; new unified management panel; its Plan Preview tab bullet updated to mention the Communication Hub node
- `docs/master/product/features/agent-plan-mode.md` — the existing agent preview topology diagram (Plan Preview tab); updated to include the Communication Hub node
- `docs/master/product/features/agent-identity.md` — agent identity assignment and inline sign-in/provisioning from the panel
- `docs/master/product/features/skill-management.md` — skill attachment and inline creation from the panel
- `docs/master/product/features/sop-management.md` — SOP attachment and inline creation from the panel
- `docs/master/product/features/agent-data-types.md` — input/output type assignment and inline Agent Data Type creation from the panel
- `docs/master/product/features/model-configurations.md` — model selection and inline model configuration creation from the panel
- `docs/master/product/features/communication-hub.md` — Communication Hub rendered as a node in agent topology visualizations

## New Capabilities

- **Unified Agent Management Panel**
  - A single management module where an administrator creates and updates an agent type and equips it with roles, an identity, Skills/SOPs, input/output data types, and a model — plus any other agent configuration actions — without navigating to other modules.
  - Supports full setup using only existing resources, only newly created resources, or any mix of both.
  - Follows an RPG character-screen interaction model: the administrator visually equips the agent and sees the result before saving.
- **Inline Resource Provisioning (reuse-based)**
  - Create a new Agent Role inline (reusing the Agent Roles dialog) when no suitable role exists; the new role is immediately assignable.
  - Sign in / provision a new Agent Identity inline (reusing the Agent Identities flow) when no suitable identity exists; the new identity is immediately selectable.
  - Create new Skills or SOPs inline (reusing the Skill/SOP dialogs) and associate them with the agent in the same flow.
  - Create a new Agent Data Type inline (reusing the Agent Data Types dialog) and set it as the agent's input/output type.
  - Add a new Model Configuration inline (reusing the Model Configurations dialog) and select it for the agent.
  - All inline creation reuses the existing module dialogs, forms, and selectors — no duplicated components; behaviour, validation, and error handling are identical to the source modules.
- **Live Agent Topology Visualization**
  - The panel renders a dynamic agent topology graph with icons representing each equipped role, identity, skill, SOP, input/output data type, model, and the Communication Hub.
  - Any change made in the panel (assign, change, remove) updates the topology visually immediately — without saving.
  - Switching to another agent re-renders the topology for that agent's current configuration.
- **Communication Hub in Topology**
  - The Communication Hub appears as a node in the new panel topology, showing the agent's connection to the platform broker/gateway.

## Modified Capabilities

- **Agent Types — agent preview topology** (Agent Types view)
  - Before: the agent preview topology visualizes the agent's role, bound SOPs, skills, and related equipment, but does not show the Communication Hub.
  - After: the same preview topology additionally renders the Communication Hub as a connected node, so the full runtime picture (including the messaging/gateway path) is visible in both the Agent Types view and the new panel.
- **Agent type creation and editing flow**
  - Before: an administrator must work across Agent Roles, Agent Identities, Skills, SOPs, Agent Data Types, and Model Configurations modules separately, then assemble the configuration in Agent Types; missing resources require leaving the flow to create them.
  - After: the administrator can optionally perform the entire configuration — including creating any missing supporting resource — from a single Agent Management Panel; the existing module pages remain available and unchanged.
- **Related resource modules (Agent Roles, Agent Identities, Skills, SOPs, Agent Data Types, Model Configurations)**
  - Before: their dialogs/forms are used only inside their own module pages.
  - After: the same dialogs/forms/selectors are also invoked from the Agent Management Panel for inline creation; no change to their standalone module behaviour.

## Removed Capabilities

- None.

## Spec Update Instructions

- `docs/master/product/features/agent-management.md`: add an "Agent Management Panel" feature section describing the unified panel, inline provisioning, and the live topology visualization (capability description, user stories, acceptance criteria per the PRD); update the "Plan preview tab" bullet to mention the Communication Hub node; note that inline creation reuses existing module dialogs and adds no new standalone resource management.
- `docs/master/product/features/agent-plan-mode.md`: update the topology-diagram description to state that the Communication Hub is rendered as a connected node.
- `docs/master/product/features/communication-hub.md`: add a note that the Communication Hub is visualized as a node in agent topology graphs (both the Agent Types preview topology and the Agent Management Panel topology).
- `docs/master/product/features/agent-identity.md`: add a cross-reference that the Agent Management Panel invokes the identity sign-in/provisioning flow inline; no standalone behaviour change.
- `docs/master/product/features/skill-management.md` and `docs/master/product/features/sop-management.md`: add a cross-reference that Skill/SOP creation dialogs are reusable inline from the Agent Management Panel; no standalone behaviour change.
- `docs/master/product/features/agent-data-types.md`: add a cross-reference that Agent Data Type creation is available inline from the panel, subject to existing rules (conversational agents have no typed outputs; referenced data types cannot be deleted).
- `docs/master/product/features/model-configurations.md`: add a cross-reference that model configuration creation is available inline from the panel; no standalone behaviour change.
- `docs/master/product/README.md`: add the Agent Management Panel to the feature index if the change is accepted into the product.
- `docs/master/ux/` (at master-update time): update the product prototype to include the Agent Management Panel and the Communication Hub node in the agent topology mock.
