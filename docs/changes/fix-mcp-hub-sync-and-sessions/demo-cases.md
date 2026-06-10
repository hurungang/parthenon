# Demo Cases: fix-mcp-hub-sync-and-sessions
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/fix-mcp-hub-sync-and-sessions/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- MCP Hub > MCP Hub shows server names from API
- MCP Hub — System Entry > MCP server table shows one System entry with Built-in chip
- MCP Hub — System Entry > server with zero sessions shows sync button disabled with tooltip
- Real Backend Integration - MCP Default Session > POST /mcp/servers/{id}/sync returns 422 when no sessions exist

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | MCP Hub server listing | Admin navigates to /mcp and sees registered MCP servers loaded from the backend API | e2e/tests/mcp-hub.spec.ts | MCP Hub shows server names from API |
| 2 | System Entry deduplication | Admin sees exactly one System entry with a Built-in chip — visually distinct from user-registered servers | e2e/tests/mcp-hub.spec.ts | MCP server table shows one System entry with Built-in chip |
| 3 | Sync visibility gated by sessions | Admin sees the sync button disabled for servers with zero sessions, with a tooltip explaining why | e2e/tests/mcp-hub.spec.ts | server with zero sessions shows sync button disabled with tooltip |
| 4 | Sync validation on real backend | Admin creates a server via API, attempts sync without sessions, and receives a clear 422 error: "no configured sessions" | e2e/tests/mcp-hub.spec.ts | POST /mcp/servers/{id}/sync returns 422 when no sessions exist |
