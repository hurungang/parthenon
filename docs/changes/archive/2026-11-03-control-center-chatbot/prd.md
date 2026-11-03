# PRD: Control Center Assistant (Chatbot)

## Epic Overview

Managing the Parthenon "Agents" menu — skills, SOPs, agent types, roles, identities, model configurations, schedules, MCP Hub connections, data types, and more — currently requires operators to know exactly which form, tab, or dialog to open for each task. This change embeds a conversational assistant in the Control Center web UI that lets a user accomplish these management tasks in natural language, on behalf of the logged-in user and strictly within that user's own permission scope. It removes navigation and form-learning friction from day-to-day agent administration while preserving the platform's security boundaries: the assistant never gains elevated access and never performs an action the user could not perform themselves.

## Business Goals

- Reduce the time and manual navigation required to complete common Agents-menu management tasks (create / update / configure) by letting users state the outcome in natural language.
- Broaden access to agent administration for users who know the intended result but not the exact UI workflow, without lowering the security bar.
- Guarantee zero privilege elevation — every assistant action is bound to the invoking user's permission scope, and every action is attributable to that user.
- Deliver consistent coverage across the full `agent::*` resource type namespace (all Agents-menu submodules) plus MCP Hub connection management for create, update, and configure operations at this stage.
- Maintain a safe, explicit boundary: no deletion of any resource and no action outside the Agents menu group in this stage.

## Users & Personas

- **Platform Operator / Administrator** — needs to complete routine agent-administration tasks quickly and repeatably without hunting through menus and forms.
- **Agent Builder / Developer** — needs to create and refine skills, SOPs, and agent types iteratively, often across many small changes.
- **Permission-Restricted User** — must be served safely and correctly within their own permission scope; the assistant must never exceed it.
- **Security / Compliance Reviewer** — needs assurance that the assistant is a delegated actor (on behalf of the user) with no elevated or direct data access.

## User Stories

- As a platform operator, I want to ask the assistant in natural language to create a Skill, so that I can define agent capabilities without locating and filling in the Skills form.
- As an agent builder, I want to ask the assistant to add an SOP or configure an Agent Type, so that I can assemble and adjust agent workflows faster.
- As an operator, I want to ask the assistant to update an existing role, identity, model configuration, schedule, or MCP Hub connection, so that I can make changes without navigating the Agents menu.
- As an operator, I want to ask the assistant to list or describe my current agent configuration (e.g. "which roles does this agent type have?"), so that I can verify state conversationally.
- As a permission-restricted user, I want the assistant to only ever perform actions I am authorized to perform, so that security boundaries are never crossed on my behalf.
- As a security-conscious administrator, I want the assistant to decline deletion requests and any action outside the Agents menu group, so that destructive or out-of-scope actions are impossible at this stage.

## Acceptance Criteria

### Assistant Availability & Scope

- A conversational assistant is available to logged-in users within the Control Center web UI.
- The assistant's management scope is limited to the "Agents" menu group (the `agent::*` resource type namespace) plus MCP Hub connection management (enforced under its canonical `integration::mcp_hub` type); requests targeting any other module groups (e.g. other integration modules or system modules) are declined with a clear message.
- The assistant does not support deletion of any resource (skills, SOPs, agent types, roles, identities, model configs, schedules, MCP Hub connections, data types, data, outputs, scripts, API keys); deletion requests are declined with a clear "not supported" message.

### Create (across Agents-menu submodules)

- A user can instruct the assistant to create a Skill with the required fields; the created skill appears in the Skills list with all values displayed correctly.
- A user can instruct the assistant to add an SOP; the created SOP appears in the SOPs list with correct values.
- A user can instruct the assistant to create/configure an Agent Type, Agent Role, Agent Identity, Model Configuration, Schedule, MCP Hub connection, or Data Type; each created resource appears in its respective list/table with correct field values.
- When required fields are missing or invalid, the assistant surfaces a clear validation message and does not create the resource.
- Duplicate identifiers are rejected with a clear error surfaced in the conversation.

### Update / Configure

- A user can instruct the assistant to update or reconfigure an existing resource (skill, SOP, agent type, role, identity, model configuration, schedule, MCP Hub connection, data type, etc.).
- Changes are saved and immediately visible in the corresponding UI list/table without a manual page reload.
- Related counts/badges (e.g. number of roles on an agent type) update after a change.

### Read / Query

- A user can ask the assistant about current configuration (e.g. list agent types, describe a role's permissions, show a schedule); the response is accurate and consistent with what the UI shows.

### Permission Inheritance & No Elevation (critical)

- The assistant performs actions on behalf of the logged-in user and is attributed to that user (in audit/history) — never to a separate privileged identity.
- The assistant never performs an action the user is not authorized to perform; when the user lacks a required permission, the assistant declines with a clear permission-denied message (no action is taken).
- The assistant never exposes sensitive data to the user beyond what the user is already entitled to see (e.g. it does not reveal identity tokens, database credentials, or decrypted MCP credentials).

### Conversational Behavior

- The assistant maintains conversation context across multiple turns so follow-up references ("now change that one's schedule") resolve correctly.
- The assistant's behavior aligns with the platform's existing conversational-agent experience (thinking/working indicators, per-turn visibility).

## Out of Scope

- **Deletion of any resource** — no delete of skills, SOPs, agent types, roles, identities, model configurations, schedules, MCP Hub connections, data types, data, outputs, scripts, or API keys at this stage.
- Actions outside the "Agents" menu group (integration modules, system modules, identity-provider configuration, permissions administration beyond agent-scoped resources, etc.).
- Elevated/privileged operations the invoking user is not authorized to perform — the assistant is strictly a delegated actor within the user's permission scope.
- Changes to the existing forms, dialogs, and manual workflows themselves (they remain as-is; the assistant is additive).
- Runtime/execution operations beyond the management actions described (e.g. directly running agents or arbitrary control-plane commands outside the Agents management scope).

## Dependencies & Constraints

- Builds on the platform's existing conversational-agent infrastructure (LangChain-based deep agent framework and conversation management).
- Must honor `docs/config.yaml` top-priority rules: services fully segregated; agents run only in the Agent Runtime service; only Control Center connects to the database; agents never access sensitive data (identity tokens, database credentials, or decrypted credentials).
- The assistant is a **delegated action model**: every action resolves against the logged-in user's permission scope via proper service routing — never through direct database access and never through elevated service credentials.
- All management actions must respect existing resource-type permission enforcement (`agent::*` resource types); requests the user cannot authorize must be declined, not escalated.
- UI text must follow the i18n convention (no hardcoded strings); error surfaces must follow the existing dialog/alert error-handling standard where applicable.
