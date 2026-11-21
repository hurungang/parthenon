

# Agent Management (Unified AI Agent Navigation)

## Overview
Agent Management enables organizations to define, configure, and govern AI agent types, their roles, permissions, and operational lifecycles. All agent-related modules—including Agent Roles, Agent Identities, Agent Types, Agent Executions, and Agent Logs—are grouped under the **Agents group** in the sidebar for a single, intuitive navigation structure. This consolidation improves discoverability, reduces user confusion, and streamlines access to all agent management capabilities. The system supports secure, role-based access control, explicit identity-role assignments, and centralized management of agent identities, model access, and permissions. All agent actions are fully auditable and observable, supporting compliance and operational transparency.

## Who Uses It
- Platform Administrators: Define agent types, roles, assign permissions, manage agent identities and model access
- Business Users: Launch agents, review results, and interact with agents
- Developers/Integrators: Integrate agents into workflows via the gateway
- Compliance & Audit Teams: Review agent definitions, assignments, and activity


## What It Does
- Provides the **Agents group** in the sidebar with the following modules in order: Agent Roles, Agent Identities, Agent Types, Agent Executions, Agent Logs
- Supports creation and management of agent roles, with SOP/Skill permissions
- Enables explicit, many-to-many assignment of agent identities to roles, managed through the UI
- Provides guided forms for defining agent types, selecting identities, roles, models, and input/output options
- Inline MCP session assignment in the Edit Agent Role dialog: when SOPs or Skills are selected, the dialog automatically computes required MCP servers from tool dependencies and renders inline session dropdowns per server; the Save action is blocked until every required server has a session assigned, guaranteeing every saved role is execution-ready; each dropdown includes a refresh button to reload available sessions without leaving the form
- Manages agent identity authentication, token storage, refresh, and re-authentication flows
- Centralizes model provider configuration and selection for agent types, backed by the [Model Configurations](./model-configurations.md) catalogue supporting twelve LLM providers across two dispatch families (OpenAI-compatible and native-API)
- Enforces max-instance limits for each agent type
- Manages agent execution lifecycle (creation, operation, termination)
- Provides real-time preview of allowed actions for each role
- Ensures all agent actions, assignments, and executions are logged and auditable
- Renames "Agent Instances" to "Agent Executions" throughout the platform for clarity
- Management of every Agents-menu module (roles, identities, agent types, skills, SOPs, model configurations, schedules, data types, and MCP Hub connections) is also available in natural language through the embedded [Control Center Assistant](./control-center-assistant.md), which acts with the signed-in user's permissions and asks for approval of a previewed change before writing; the manual forms and dialogs remain the primary, unchanged path
- Agent Executions view supports filtering by agent type, enabling users to focus on relevant runs
- Agent Types table includes columns for "Role" and "Identity", displaying the actual role and identity names for each agent type
- Supports both traditional and passthrough session types for MCP servers; passthrough enables direct agent identity propagation without explicit session selection
- Provides a distinct guardrail profile view for every Agent Type, including iteration, delegation depth, delegated-step, timeout, and token-budget policies
- Allows authorized administrators to edit and save each Agent Type guardrail profile from the same governance workspace
- Presents token-budget values in k-token units with a default presentation value of 1000k for consistency across Agent Types
- Keeps guardrail editing compact by default so governance updates remain efficient in high-volume administration workflows
- Clicking an agent type row opens a comprehensive dialog with:
	- Agent type details (basic info)
	- Plan preview tab (shows the unified agent topology view — identical to the management panel topology, with zoom in/out; includes the Communication Hub as a connected node; available for all agent types, typed and conversational)
	- Implementation Plan tab with explicit plan authoring (see below)
	- Optimized Plan tab (see "Optimization Surface" below)
	- Execution logs tab (filtered by agent type)
	- Sessions tab (visible only for conversation-type agents) — lists all conversation sessions with title, status, and last active time
	- Role and Identity names as clickable links, opening the corresponding view dialogs
- All dialogs (agent type details, role/identity view) are fully responsive and maximize content area
- Role and identity view dialogs include an "Edit" button for direct editing
- After closing any dialog, the parent table refreshes automatically to show updated data
- Conversation agent sessions:
	- Users can start new conversation sessions from the Sessions tab
	- Session titles are automatically generated from the first user prompt
	- Users can resume previous sessions with full conversation history
	- Users can end or archive sessions to manage their workspace
	- All sessions are user-scoped (users only see their own sessions)
	- Conversation sessions surface inline intervention dialogs when delegated sub-agents request human input, with the pause-on-intervention state visible in the session list

## Agent Management Panel

The Agent Management Panel is a unified management module in the **Agents group** where an administrator creates, inspects, and edits agent types end-to-end — equipping each agent with its role, identity, skills, SOPs, input/output data types, and model — without navigating to the other modules. It follows a "character screen" interaction model: the administrator visually equips the agent, sees the result immediately, and saves when satisfied. Full setup works with only existing resources, only newly created resources, or any mix of both.

### What the panel provides
- **Single panel for the full agent lifecycle**: create, inspect, and edit an agent from one place
- **Header actions**: create a new agent and delete an agent (with confirmation); the agent list refreshes automatically after both
- **Right-hand property bar as the single editing surface**: ALL editing of an existing agent happens here — a Properties section (name, description, system instruction, execution guardrails) plus equipment slots for role, identity, skills, SOPs, input type, output data type, and model
- **Inline create-and-assign**: missing roles, identities (sign-in/provisioning), skills, SOPs, data types, and model configurations can be created directly from the panel using the exact same dialogs as their source modules — no duplicated forms, and no change to the standalone module pages
- **Searchable, paginated resource picker**: "Assign existing" opens a searchable, paginated selection dialog (single or multi-select per slot) with currently equipped resources pre-selected and an inline "Create new" action
- **Draft-until-save model**: every edit is held as a draft and summarized in a pending-changes tray with Save and Discard actions; a confirmation protects unsaved changes when switching agents or navigating away
- **Live agent topology — the single, canonical topology view**: a visual composition graph (equipped roles, identity, skills, SOPs, data types, model, tools) updates instantly as equipment changes — before saving — and re-renders when switching agents; the Communication Hub is shown as a connected platform element (a hub bar between capabilities and tools, with connectors crossing it). This is the one and only agent topology presentation in the product: it is presented identically in the agent management panel and in the agent type details dialog preview, for all agent types (both typed and conversational)
- **Fullscreen and zoom**: the topology can be expanded fullscreen with zoom in/out/fit and pan in both the management panel and the agent type details dialog preview; the view auto-fits when entering or leaving fullscreen. Text size is capped, so zooming and fullscreen reveal more of the topology content rather than simply magnifying text
- **Slot labels in the topology**: input and output slots in the topology show the same human-readable labels used in the editor dialogs (e.g., "None" or "Auto") rather than empty placeholders, so the diagram is always self-explanatory
- **Token health badges in the topology**: container nodes display a warning badge when a bound identity or MCP session expires within 7 days and an error badge when expired, so credential risk is visible while designing or reviewing agents (see [Token Expiry Alerting](token-expiry-alerting.md))
- **Permission-aware equipment slots**: actions a user lacks permission for are disabled with a clear explanation; read-only users can browse and review compositions

### Acceptance criteria (panel)
- Administrator can create a new agent with the required fields; it appears in the panel's agent list immediately with all values displayed
- Administrator can view all accessible agents with their equipment shown accurately; search and filter work correctly
- Administrator can edit any base property or equipment in the property bar; changes accumulate as a draft and become visible in the topology immediately — without saving
- After saving, changes are persisted and the agent list and topology reflect the saved state without a manual page reload
- Administrator can delete an agent with confirmation; it disappears from the list immediately, related counts update, and a new agent can be created with the same name afterwards
- Inline-created resources become immediately assignable in their slot without leaving the panel and behave identically (same fields, validation, error handling) to the source-module dialogs
- Validation errors are surfaced clearly (required fields, invalid names, binding conflicts); permission errors are shown gracefully inside dialogs and slots rather than failing silently
- The Communication Hub appears as a connected node in the topology, both in the management panel and in the agent type details dialog preview — which show the identical, unified topology view

## Optimization Surface (Optimize Action & Optimized Plan Tab)

Running an agent and optimizing it are separate acts in the agent surface:

- **Two distinct actions.** The launch surface exposes Run and Optimize as separate actions. Running an agent always executes the user's task with the agent's own instructions; there is no "run with optimization" mode, and no normal run becomes an optimization mission.
- **Preconditions are visible, not hidden.** Optimize is available only after at least one successful execution of the agent exists and a usable authoring (optimizer) model is configured. Otherwise it is disabled with a clear explanation of what is missing; when the model is the blocker, the message points to System Config and no optimization run starts. Optimize unlocks on its own as soon as a run completes — no page reload.
- **Explicit plan authoring.** Implementation plans are never generated by saving the agent. The Implementation Plan tab shows, before any plan exists, that none has been authored and offers a **Generate plan** action; once a plan exists the action reads **Regenerate plan**. A failed attempt shows its reason and keeps the last successful plan; a plan older than the agent's current configuration is flagged as out of date and offered for regeneration rather than regenerated silently. A generation shows a processing indicator until the new plan is ready.
- **Conversational-agent state.** Conversational agent types expose no Generate/Regenerate plan control and no one-shot Optimize action — the implementation-plan surface explains that plans are not available for them. Their optimization path is the conversation below, which is available to them on the same terms.
- **"Talk to optimizer" entry.** The Optimized Plan tab offers the optimization conversation, scoped to that one agent: the optimizer manipulates only this agent's plan, scripts, and history, declines anything else, and deletes nothing. Opening the conversation starts no work.
- **Scoped conversation view.** The conversation shows only a compact, **default-collapsed "What ran in this session"** bar (replay-only versus approved-live counts plus the current replay-only state) instead of a persistent scope header; expanding it reveals the audit detail. A single processing indicator is shown while a turn runs, and it clears when the turn reaches a terminal state.
- **Live-test approval card.** A live script run request names the script under test and its version and previews the tool calls it will make; the operator approves or denies one run of that script. Once decided — approved, running, executed, failed, denied, expired, or cancelled — the card collapses into a one-line summary in the chat history that can be expanded again without changing the recorded decision.
- **Requires-fix alert.** When an optimized plan has been flagged as requiring a fix after a later execution fell back, the next time the operator opens the agent (or its Optimized Plan tab) an alert names the problem, distinguishes automatically recorded feedback from manually entered feedback, and offers re-optimization carrying the prior plan plus that feedback.
- **Automatic refresh.** After a generation, an optimization, a re-optimization, or a conversation turn that authoring changes, the tab refreshes in place to the current plan state without a manual page reload; the hosting agent dialog reflects the completed run without reopening and offers an explicit reload action.

## Key Concepts
- **Agents Group**: A sidebar navigation group containing all agent-related modules for streamlined access
- **Agent Role**: A permission grouping for SOPs, Skills, and tools, assigned to agent identities
- **Identity-Role Assignment**: Explicit, many-to-many mapping between agent identities and roles, managed bidirectionally in the UI
- **Agent Type**: A defined class of agent with specific identity, role, and model configuration
- **Agent Management Panel**: A unified panel for creating, inspecting, and equipping agents end-to-end, with inline resource creation and a live topology preview that updates before saving
- **Conversation Agent Session**: A persistent, user-named conversation with a conversation-type agent; includes automatic title generation, session management (start/resume/end/archive), and full turn history
- **Session Type**: Either traditional (named session) or passthrough (direct agent identity propagation to MCP server)
- **Model Configuration**: Central management of model providers and enabled models for agent use; the supported provider catalogue and lifecycle are defined in the [Model Configurations](./model-configurations.md) feature spec
- **Execution Lifecycle**: The process of creating, running, and terminating agent executions (formerly instances)
- **Filtering**: Ability to filter agent executions by agent type for targeted review
- **Dialog-Based Details**: Agent type details, plan preview, and execution logs are accessible in a single, tabbed dialog
- **Column Visibility**: Role and identity columns are visible in the agent types table, with clickable names for direct navigation
- **Agent Identity as OIDC Principal**: All agent identities must be supported as first-class OIDC principals. The MCP Demo App provides a reference implementation for this requirement.
- **Guardrail Profile**: A per-Agent-Type policy definition for cycle prevention, execution boundaries, delegation boundaries, timeout, and token-budget behavior
- **Optimize Action**: A dedicated, preconditioned action separate from Run that authors and verifies an agent's optimized plan; it never runs as part of a normal execution
- **Optimization Conversation**: A conversation channel on the agent itself, opened from the Optimized Plan tab, in which the optimizer works under the agent's own identity and permissions, asks the operator questions, and may request one approved live run of the script under test
- **Requires-Fix Alert**: An operator alert on the Optimized Plan tab for a plan that a later execution had to fall back from, carrying the automatically recorded failure feedback


## Acceptance Criteria
- Every Agents-menu management action available in the manual UI is also reachable conversationally through the Control Center Assistant, with identical permission enforcement and no additional capability
- The **Agents group** exists in the sidebar with the following modules, in this order:
	1. Agent Roles
	2. Agent Identities
	3. Agent Types
	4. Agent Executions
	5. Agent Logs
- "Agent Instances" is renamed to "Agent Executions" everywhere in the UI and documentation
- Agent Executions view supports filtering by agent type (dropdown or similar)
- Agent Types table includes columns for "Role" and "Identity" displaying the actual role name and identity name for each agent type
- Supports both traditional and passthrough session types for MCP servers; passthrough enables direct agent identity propagation without explicit session selection
- Clicking an agent type row opens a dialog with:
	- Agent type details (basic info)
	- Tab: Plan preview (shows the unified agent topology view — identical to the management panel topology, with zoom in/out; includes the Communication Hub as a connected node; available for all agent types, typed and conversational)
	- Tab: Execution logs (list of executions for this agent type)
	- Tab: Sessions (visible only for conversation-type agents) — lists all user's conversation sessions with:
		- Session title (auto-generated from first user prompt)
		- Session status (active, closed, archived)
		- Last active timestamp
		- Actions: Resume, End, Archive
		- "Start New Conversation" entry point
	- Role and Identity names displayed as clickable links; clicking opens the corresponding view dialog
- All dialogs (AgentTypeDetailsDialog, role/identity view dialogs) are fully responsive and match the width of PlanPreviewModal, maximizing content area
- Role and identity view dialogs include an "Edit" button to enable editing mode
- "Active instances" feature works: clicking agent type row shows current executions for that type
- After closing any dialog, parent table refreshes automatically to show updated data
- Authorized administrators can open, edit, and save a distinct guardrail profile for each Agent Type
- Guardrail token budgets are shown in k-token units with 1000k as the default presentation value
- Guardrail editing remains compact by default and is easy to scan across large Agent Type portfolios
- After closing any create/edit/delete or guardrail dialog, parent tables refresh automatically to show updated policy values without manual page reload
- Conversation agent sessions work correctly:
	- Sessions tab appears only for agents with input_type = 'conversation'
	- Users can start new conversation sessions from the Sessions tab
	- Session titles are auto-generated from the first user prompt
	- Users can resume previous sessions with full turn history restored
	- Users can end sessions (status becomes 'closed', removed from active list)
	- Users can archive sessions (status becomes 'archived', excluded from default listing)
	- Sessions are user-scoped (users only see their own sessions)
	- Sessions list updates automatically after create/end/archive operations
	- Conversation sessions show intervention requests from delegated agents and allow inline response without leaving the conversation view
- Selecting SOPs or Skills in the Edit Agent Role dialog displays required MCP servers inline with session dropdowns per server
- Session dropdowns update dynamically when SOPs/Skills are added or removed
- Save is blocked (button disabled with inline validation message) when any required MCP server lacks a session assignment
- Each server dropdown includes a refresh button that reloads available sessions; current selection is preserved if the session still exists
- MCP servers configured with passthrough session type display a "Passthrough" badge next to the server name
- All changes are observable in the UI without requiring a page reload
- Error messages are clear and actionable if features fail
- Run and Optimize are distinct actions on the agent surface; no option turns a normal run into an optimization mission
- Optimize is unavailable until a successful execution exists and a usable authoring/optimizer model is configured, with the reason shown; when the model is missing the message points to System Config and no optimization starts
- Saving or updating an agent never generates or overwrites an implementation plan; Generate plan / Regenerate plan is the only trigger, no-plan and out-of-date states are shown, and a completed generation renders without a page reload
- Conversational agent types show no plan-generation control and no one-shot Optimize action, only the explanation plus the optimizer conversation entry
- The Optimized Plan tab offers the "Talk to optimizer" entry scoped to that agent, and the conversation shows a default-collapsed "What ran in this session" summary bar that expands into the audit detail
- The live-test approval card names the script and its version with a tool-call preview, and collapses to a one-line history summary once decided while keeping the recorded decision
- A plan requiring a fix surfaces an alert on the next visit, distinguishes automatic from manual feedback, and offers re-optimization that refreshes the tab in place
- After a generation, optimization, or re-optimization, the Optimized Plan tab reflects the current plan state without a manual page reload

## Out of Scope
- Backend API or data model changes not required for navigation/UI improvements
- Major redesign of agent configuration or execution logic
- Changes to authentication or RBAC logic
- Non-agent-related navigation changes
- No new functionality or changes to Agent Roles or Agent Identities pages themselves (other than menu placement and view dialog edit button)
- The Agent Management Panel does not replace or alter the standalone Agent Roles, Agent Identities, Skills, SOPs, Agent Data Types, or Model Configurations pages; inline creation reuses those modules' existing dialogs and adds no new standalone resource management

## Dependencies & Constraints
- Relies on existing agent type, execution, identity, and role data being available
- Must maintain compatibility with OIDC/OAuth2 and RBAC roles
- UI changes must not break existing agent workflows
- Requires OIDC-compliant identity provider (Keycloak, Azure EntraID)
- Inline identity provisioning from the Agent Management Panel requires a reachable, configured identity provider and degrades gracefully when it is unavailable
- Agent identities must be managed in a separate, configurable realm within the identity provider
- Relies on existing MCP tool and Skill registration mechanisms
- Asynchronous session system must be available for agent execution and result tracking
- System must securely store and refresh agent OAuth tokens for runtime use
- Bootstrap process must initialize both user and agent realms in the identity provider
- All changes must comply with Parthenon’s security, audit, and observability conventions

## Multi-Tenancy Note

When multi-tenancy is enabled (see [Multi-Tenancy](multi-tenancy.md)), agents, their roles, identities, and model access are tenant-owned; agents execute strictly within their tenant's skills, tools, and permissions. With multi-tenancy disabled (the default), behavior is unchanged — the deployment operates as the root tenant's workspace.
