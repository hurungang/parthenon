# Demo Cases: mcp-dual-identity-tools
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/mcp-dual-identity-tools/demo-cases.md -->

## Grep Patterns
<!-- One pytest test function name per line (must match the test name exactly) -->
- test_hello_agent_tool_with_role_returns_greeting
- test_hello_agent_tool_without_role_returns_access_denied
- test_hello_user_tool_with_role_returns_greeting
- test_hello_user_tool_without_role_returns_access_denied
- test_tools_call_with_real_jwt_returns_agent_sub

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | helloAgent — authorized | Agent with `mcp_role: demo_agent` calls helloAgent and receives greeting with agent claims (sub, realm, role) | mcp-demo-app/tests/integration/test_agent_flow.py | test_hello_agent_tool_with_role_returns_greeting |
| 2 | helloAgent — access-denied | Agent without required `demo_agent` role gets JSON-RPC success response with `access_denied: true` (HTTP 200, not 403) | mcp-demo-app/tests/integration/test_agent_flow.py | test_hello_agent_tool_without_role_returns_access_denied |
| 3 | helloUser — authorized | User identity via `X-User-Identity` header with `mcp_role: demo_user` gets greeting with user claims — demonstrates dual-identity chain | mcp-demo-app/tests/integration/test_agent_flow.py | test_hello_user_tool_with_role_returns_greeting |
| 4 | helloUser — access-denied | User without required `demo_user` role gets access-denied — proves per-tool role gating works independently from agent identity | mcp-demo-app/tests/integration/test_agent_flow.py | test_hello_user_tool_without_role_returns_access_denied |
| 5 | helloWorld — regression | Existing helloWorld tool unchanged: still surfaces agent identity, no role gating, works with real Keycloak JWT | mcp-demo-app/tests/integration/test_agent_flow.py | test_tools_call_with_real_jwt_returns_agent_sub |
