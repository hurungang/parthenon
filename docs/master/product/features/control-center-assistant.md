# Control Center Assistant

## Overview

The Control Center Assistant is a built-in conversational assistant embedded in the Control Center that performs **Agents-menu management** on the signed-in user's behalf: creating, updating, and inspecting skills, SOPs, agent types, roles, identities, model configurations, schedules, data types, and MCP Hub connections. It removes the need to know which form, tab, or dialog a task lives in — operators describe the outcome in natural language and the assistant carries it out within that user's own permission scope, never beyond it. The assistant is additive: every existing form and manual workflow is unchanged, and nothing is written without the user's explicit approval of a previewed change. It is provided by the platform (not created by users), protected from user editing or deletion, and bounded by design — it does not delete anything and does not act outside the Agents menu group.

## Business Goals

- Reduce the time and navigation required to complete routine agent-administration tasks by letting users state the intended outcome in natural language.
- Broaden who can administer agents: users who know the result they need but not the exact UI workflow can act correctly without lowering the security bar.
- Guarantee zero privilege elevation — every action is performed as the signed-in user, attributed to that user, and refused when the user lacks the permission.
- Prevent costly misconfiguration by requiring an explicit, field-by-field preview and approval before any create or update.
- Keep every agent self-sufficient — each agent can inspect its own context and optimize its own recurring work without extra setup.

## Users & Personas

- **Platform Operator / Administrator** — completes routine agent-administration tasks quickly and repeatably without hunting through menus.
- **Agent Builder / Developer** — iterates on skills, SOPs, roles, and agent types across many small changes.
- **Permission-Restricted User** — uses the assistant safely inside their own scope; it never acts beyond what they may do themselves.
- **Security / Compliance Reviewer** — needs assurance that the assistant is a delegated actor with no elevated access, no direct data access, and no ability to destroy anything.

## User Stories

- As a platform operator, I want to ask the assistant to create a skill or add an SOP, so that I can define agent capability without locating and filling in the right form.
- As an agent builder, I want to ask the assistant to assemble a working agent type — model, identity or role, and skills — so that I end up with a functional agent rather than an empty shell.
- As an operator, I want to ask the assistant to update a role, identity, model configuration, schedule, or MCP Hub connection, so that I can make changes without navigating the Agents menu.
- As an operator, I want to ask the assistant what my current configuration is, so that I can verify state conversationally and trust it matches the UI.
- As an operator, I want to see exactly what will change before anything is written, so that I can approve or reject with confidence.
- As a permission-restricted user, I want the assistant to decline what I am not allowed to do, so that my boundaries are never crossed on my behalf.
- As a security-conscious administrator, I want the assistant to refuse deletions and anything outside the Agents menu, so that destructive or out-of-scope actions are impossible.
- As a returning user, I want my conversation with the assistant to be remembered and resumable, so that I can pick up a multi-step task later.
- As an administrator, I want to choose which approved model powers the assistant for my workspace, so that its behaviour stays inside enterprise model policy.

## Acceptance Criteria

### Availability, Scope & Boundaries

- A conversational assistant is available to signed-in users from the Control Center, and is clearly presented as a system-provided capability that cannot be edited or removed by users.
- The assistant's management scope is the Agents menu group (skills, SOPs, agent types, roles, identities, model configurations, schedules, data types, MCP Hub connections). Requests outside that group are declined with a clear explanation.
- The assistant never deletes any resource. Deletion requests are declined with a clear "not supported" message and nothing is removed.
- The assistant acts as the signed-in user: actions are attributed to that user, and any action the user is not authorized to perform is declined with a clear permission message and no change.
- The assistant never reveals sensitive material the user is not entitled to see (identity tokens, database credentials, decrypted connection credentials).

### Create, Update & Read

- A user can ask the assistant to create any in-scope resource; the created resource appears in its list/table with all field values correct.
- A user can ask the assistant to update or reconfigure an existing in-scope resource; changes are saved and visible in the corresponding list/table without a manual page reload, and related counts update.
- A user can ask the assistant to list or describe current configuration; the answer matches what the UI shows.
- Missing or invalid required fields produce a clear validation message and no resource is created; duplicate names/identifiers are rejected with a clear message in the conversation.
- The assistant asks for clarification rather than guessing names, identifiers, or field values.

### Confirmation Before Any Write

- Before any create or update, the assistant presents a preview of the exact change as a field-by-field table (for updates: previous value → new value) and waits for approval.
- No create or update is performed unless the user approves the preview; rejecting it leaves everything unchanged and the assistant offers to adjust.
- For an agent type, the preview shows the model, identity or role, skills/SOPs, and access grants, so the user can confirm the agent will be functional.
- The preview can be expanded to a larger view for reviewing wide tables.

### Completeness & Association Rules

- An agent type is only presented as complete when it has a working model and either an identity or a role plus its capability bindings; the assistant does not create non-functional agent types.
- A skill can only invoke the tools bound to it — there is no implicit tool access. The assistant discovers a server's available tools and binds the needed ones when creating a skill.
- A skill with no bound tools is visibly flagged as non-functional (in the conversation and in the Skills list) rather than presented as ready to use.
- Adding bindings or grants never silently removes existing ones; access is granted at the level the configuration consumes it — role grants for role-based agents, direct bindings for role-less ones.
- Identities are assigned to roles, and that chain is respected when the assistant grants access.

### Conversation Sessions

- The assistant keeps context across multiple turns, so follow-up references ("now change that one's schedule") resolve correctly.
- Closing the assistant only closes the view; the session stays active and the most recent active session resumes with full history on reopen.
- A session action bar offers: view all sessions, start a new session, end the current session, and exit.
- Viewing all sessions shows active and ended sessions, defaults to a recent time window, supports choosing a date range, and is paginated; active sessions can be resumed in place, ended sessions are clearly marked and cannot be resumed.
- Starting a new session leaves the previous session active; ending a session closes it and stops any work still in progress, and the next open starts fresh.
- Switching or ending a session is unavailable while the assistant is still working on a turn.
- Session history is user-scoped and retained for audit and replay.

### Model Configuration

- The model that powers the assistant is selected per workspace from the approved model catalogue.
- If no model is selected, the assistant explains the situation and offers a direct path to configure one, and input is disabled — it never falls back silently to an unapproved model.
- The same guidance appears if the model becomes unavailable mid-session.

### Built-in Self-Context & Optimization

- Every agent — the assistant included — can inspect its own plan, generated scripts, and execution history, and can generate and verify optimized workflows for recurring work, with no configuration and no per-agent setup.
- These built-in capabilities are always available and never depend on user-created bindings, while still respecting the same guardrails and permissions as any other action.

### Operating Within Guardrails

- The assistant is given a step budget sized for multi-step management tasks; if a request needs more steps than allowed, the user sees a clear explanation with guidance to split the request or ask an administrator, instead of a silent stop.

### Control Center Integration Surface

- The assistant's management capability appears in MCP Hub as a protected, system-managed Control Center integration.
- That integration is visible and usable only to users holding the Control Center integration permission; others do not see it at all.
- Nobody can edit, delete, sync, or attach sessions to that integration; granting its tools to roles remains governed by permission.
- The same permission-scoped management capability is available to external agents that connect using a user's own credentials, with identical enforcement and attribution.

## Out of Scope

- Deletion of any resource (skills, SOPs, agent types, roles, identities, model configurations, schedules, MCP Hub connections, data types, data, outputs, scripts, API keys).
- Actions outside the Agents menu group (other integration modules, system modules, identity-provider configuration, permissions administration beyond agent-scoped resources).
- Elevated or privileged operations the signed-in user is not authorized to perform.
- Changes to the existing forms, dialogs, and manual workflows — the assistant is additive.
- Running agents, arbitrary control-plane commands, or any execution behaviour beyond management actions.
- Model selection outside the approved model catalogue, and provider-specific tuning.

## Dependencies & Constraints

- Builds on the platform's existing conversational-agent experience (multi-turn context, thinking/working indicators, human-in-the-loop prompts, conversation persistence).
- Depends on the existing role- and permission-based authorization model; the assistant inherits the signed-in user's scope and is never a separate privileged identity.
- Depends on centrally managed model configurations and enabled-model policy; a workspace must select a model before the assistant can be used.
- Requires service segregation to hold: agents run only in the Agent Runtime, only the Control Center touches the database, and no sensitive material crosses service boundaries.
- Depends on the platform's system-managed integration convention for the Control Center entity, and on the Control Center integration permission being granted to the right roles.
- All assistant-facing text follows the product's localisation convention; error surfaces use the standard dialog/alert error presentation.

## Multi-Tenancy Note

When multi-tenancy is enabled (see [Multi-Tenancy](multi-tenancy.md) and [Strict Tenant Isolation](strict-tenant-isolation.md)), the assistant is provisioned per tenant and always acts inside the session's tenant: it can only see and change that tenant's resources, its sessions are tenant- and user-scoped, and the model selection is per workspace. With multi-tenancy disabled (the default), behaviour is unchanged — the deployment operates as the root tenant's workspace.
