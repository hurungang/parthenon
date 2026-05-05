# Demo Cases: implement-agent-runtime-with-gateway
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/implement-agent-runtime-with-gateway/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Agent Role Management > renders agent roles page with role list
- Agent Identity Management > renders agent identities page with identity list
- Agent Identity Management > renders realm_name column values
- Agent Identity Management > OAuth sign-in button appears in edit dialog (mocked)
- Agent Type Configuration > renders agent type with input_type chip
- Agent Session Launch > opens launch dialog when launch button is clicked
- Agent Session Status > renders completed session with result
- Agent Realm Bootstrap — Mocked > agent identities page loads when realm is initialized (mocked)
- Agent Realm Bootstrap — Mocked > realm name column displays configured agent realm
- Agent Realm Bootstrap — Real Keycloak Integration > agent realm openid-configuration is reachable after bootstrap
- Real Backend Integration — Agent Runtime Migration > GET /agents/roles returns valid response (validates DB schema)

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Agent Role Management | User can view list of agent roles with their associated SOPs and Skills counts | agent-runtime.spec.ts | renders agent roles page with role list |
| 2 | Agent Identity Management | User can view list of agent identities with realm_name and realm_username columns; status chips (active/suspended/deprovisioned) | agent-runtime.spec.ts | renders agent identities page with identity list |
| 3 | Agent Identity — Realm Name | Identity list shows the agent realm name (ai_agents by default), confirming agents live in a separate realm from users | agent-runtime.spec.ts | renders realm_name column values |
| 4 | Agent Identity — OAuth Sign-In | Edit dialog for an agent identity exposes an OAuth sign-in button so a user can authorize the agent user in the IdP and store tokens | agent-runtime.spec.ts | OAuth sign-in button appears in edit dialog (mocked) |
| 5 | Agent Type Configuration | User can view agent types with rearchitected fields including input_type chip (none/typed/conversation) demonstrating new schema | agent-runtime.spec.ts | renders agent type with input_type chip |
| 6 | Agent Session Launch | User can click Launch button on an agent type to open launch dialog with input form based on input_type | agent-runtime.spec.ts | opens launch dialog when launch button is clicked |
| 7 | Agent Session Status | User can view completed session result page showing session ID, status chip, and output data from agent execution | agent-runtime.spec.ts | renders completed session with result |
| 8 | Agent Realm Bootstrap — Initialized | Identities page loads and shows agent identity after the ai_agents realm has been bootstrapped in the identity provider | agent-bootstrap.spec.ts | agent identities page loads when realm is initialized (mocked) |
| 9 | Agent Realm Bootstrap — Configurable Realm | Realm name column shows the configured realm name (not hardcoded to ai_agents), proving the realm is driven by bootstrap config | agent-bootstrap.spec.ts | realm name column displays configured agent realm |
| 10 | Agent Realm Bootstrap — Real Keycloak | Verifies that after bootstrap the ai_agents realm exposes its OpenID configuration on the same Keycloak instance as the user realm | agent-bootstrap.spec.ts | agent realm openid-configuration is reachable after bootstrap |
| 11 | Real Backend Integration | Validates database migration applied correctly by calling real backend endpoint (no mocks) to verify agent_roles table exists | agent-runtime.spec.ts | GET /agents/roles returns valid response (validates DB schema) |
