# Demo Cases: control-center-chatbot
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/control-center-chatbot/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Control Center Assistant (mocked) > clicking the assistant FAB opens the conversational surface
- Control Center Assistant (mocked) > Agent Types list marks system agent types and disables edit/delete
- Real Backend Integration - Control Center Assistant > OAuth token establishes a session and lists management tools
- External MCP client parity - Control Center Assistant > tools/list filters and tools/call authorizes with parity
- Real Backend Integration - Control Center Assistant > unauthenticated MCP request is rejected (401)

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | In-app assistant entry | System assistant agent type resolves to a floating assistant launcher on the dashboard; clicking it opens the conversational surface (reused ConversationDialog) | e2e/tests/control-center-chatbot.spec.ts | clicking the assistant FAB opens the conversational surface |
| 2 | `is_system` protection in Agent Types UI | System agent type shows the "System" badge and its Edit/Delete controls are disabled — seeded assistant cannot be modified or removed from the UI | e2e/tests/control-center-chatbot.spec.ts | Agent Types list marks system agent types and disables edit/delete |
| 3 | OAuth-gated MCP surface | A real platform-account OAuth JWT establishes an MCP session on Communication Hub `/mcp` and receives the permission-filtered management catalog (every tool `system____`-prefixed) — no mocks, live CC resolve | e2e/tests/control-center-chatbot.real-backend.spec.ts | OAuth token establishes a session and lists management tools |
| 4 | External MCP client parity | An external MCP client presenting the user's OAuth credentials gets the same security layer: filtered `tools/list` (no delete-shaped tools) and `tools/call` routed to CC with the user's own subject | e2e/tests/control-center-chatbot-mcp.spec.ts | tools/list filters and tools/call authorizes with parity |
| 5 | No-delete / permission-denied boundary | Unauthenticated `/mcp` requests fail closed with 401; complemented in-flow by case 4's in-band `deletion_not_supported` / `out_of_scope` declines | e2e/tests/control-center-chatbot.real-backend.spec.ts | unauthenticated MCP request is rejected (401) |
