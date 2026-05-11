# Demo Cases: implement-agent-runtime-with-gateway
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/implement-agent-runtime-with-gateway/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Role Management > renders agent roles page with role list
- Agent Identity Management > renders agent identities page with identity list
- Agent Identity Management > renders realm_name column values
- Agent Identity Management > OAuth sign-in button appears in create dialog
- Agent Type Configuration > renders agent type with input_type chip
- Agent Session Launch > opens launch dialog when launch button is clicked
- Agent Session Status > renders completed session with result
- Agent Realm Bootstrap — Mocked > agent identities page loads when realm is initialized (mocked)
- Agent Realm Bootstrap — Mocked > realm name column displays configured agent realm
- Agent Realm Bootstrap — Real Keycloak Integration > agent realm openid-configuration is reachable after bootstrap
- Real Backend Integration — Agent Runtime Migration > GET /agents/roles returns valid response (validates DB schema)
- Model Config CRUD > renders model configs page with config list
- Agent Instance Dashboard > shows status filter dropdown
- Conversation History Display > renders chat interface for conversational session
- Real Backend Integration — Agent Runtime Migration > GET /agents/model-configs returns valid response (validates model_configs table)
- Agent Role Identity Constraints > create role with identity type constraint — allowed_identity_types persisted
- Agent Role Identity Constraints > assigning role with incompatible identity type shows validation error
- Agent Role Identity Constraints > assigning role with compatible identity type succeeds
- Identity-First Role Selection > selecting identity filters role dropdown to compatible roles only
- Identity-First Role Selection > changing identity selection clears previously selected role

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Agent Role Management | User can view list of agent roles with their associated SOPs and Skills counts | agent-runtime.spec.ts | renders agent roles page with role list |
| 2 | Agent Identity Management | User can view list of agent identities with realm_name and realm_username columns; status chips (active/suspended/deprovisioned) | agent-runtime.spec.ts | renders agent identities page with identity list |
| 3 | Agent Identity — Realm Name | Identity list shows the agent realm name (ai_agents by default), confirming agents live in a separate realm from users | agent-runtime.spec.ts | renders realm_name column values |
| 4 | Agent Identity — OAuth Sign-In | Create dialog for a new agent identity exposes an OAuth sign-in button so a user can authorize the agent user in the IdP and store tokens | agent-runtime.spec.ts | OAuth sign-in button appears in create dialog |
| 5 | Agent Type Configuration | User can view agent types with rearchitected fields including input_type chip (none/typed/conversation) demonstrating new schema | agent-runtime.spec.ts | renders agent type with input_type chip |
| 6 | Agent Session Launch | User can click Launch button on an agent type to open launch dialog with input form based on input_type | agent-runtime.spec.ts | opens launch dialog when launch button is clicked |
| 7 | Agent Session Status | User can view completed session result page showing session ID, status chip, and output data from agent execution | agent-runtime.spec.ts | renders completed session with result |
| 8 | Agent Realm Bootstrap — Initialized | Identities page loads and shows agent identity after the ai_agents realm has been bootstrapped in the identity provider | agent-bootstrap.spec.ts | agent identities page loads when realm is initialized (mocked) |
| 9 | Agent Realm Bootstrap — Configurable Realm | Realm name column shows the configured realm name (not hardcoded to ai_agents), proving the realm is driven by bootstrap config | agent-bootstrap.spec.ts | realm name column displays configured agent realm |
| 10 | Agent Realm Bootstrap — Real Keycloak | Verifies that after bootstrap the ai_agents realm exposes its OpenID configuration on the same Keycloak instance as the user realm | agent-bootstrap.spec.ts | agent realm openid-configuration is reachable after bootstrap |
| 11 | Real Backend Integration — Agent Roles | Validates database migration applied correctly by calling real backend endpoint (no mocks) to verify agent_roles table exists | agent-runtime.spec.ts | GET /agents/roles returns valid response (validates DB schema) |
| 12 | Model Config CRUD | User can view list of model configurations showing display name and provider type chips (openai, litellm_proxy); encrypted API key values are never exposed in the table | agent-runtime.spec.ts | renders model configs page with config list |
| 13 | Agent Instance Dashboard — Status Filtering | User can filter the instance dashboard by status (completed/running/failed) via a status dropdown, with time range filters, allowing operators to monitor live and historical agent sessions | agent-runtime.spec.ts | shows status filter dropdown |
| 14 | Conversation History — Instance Detail | Instance detail view renders a chat interface for conversational agent sessions, showing session ID and status metadata alongside the conversation panel | agent-runtime.spec.ts | renders chat interface for conversational session |
| 15 | Real Backend Integration — Model Configs | Validates that the model_configs table was created by the migration by calling the real backend endpoint (no mocks) | agent-runtime.spec.ts | GET /agents/model-configs returns valid response (validates model_configs table) |
| 16 | Agent Role Identity Constraints — Create | User can create an agent role with `allowed_identity_types` constraint; the field is persisted and echoed back in the API response | agent-runtime.spec.ts | create role with identity type constraint — allowed_identity_types persisted |
| 17 | Agent Role Identity Constraints — Incompatible Type | Attempting to assign an agent identity whose type does not satisfy the role's `allowed_identity_types` list returns a 400 validation error; the UI handles it without crashing | agent-runtime.spec.ts | assigning role with incompatible identity type shows validation error |
| 18 | Agent Role Identity Constraints — Compatible Type | Assigning an agent identity whose type matches the role's `allowed_identity_types` succeeds (201); confirms the happy path for constrained role assignment | agent-runtime.spec.ts | assigning role with compatible identity type succeeds |
| 19 | Identity-First Role Selection — Filtered Dropdown | Create/edit agent type form shows identity selector first; selecting an identity filters the role dropdown to only roles compatible with that identity's type (matching `allowed_identity_types` or unrestricted roles) | agent-runtime.spec.ts | selecting identity filters role dropdown to compatible roles only |
| 20 | Identity-First Role Selection — Role Cleared on Identity Change | Changing the selected identity in the agent type form clears the previously selected role, preventing stale incompatible role assignments | agent-runtime.spec.ts | changing identity selection clears previously selected role |
