# Spec Change: Fix MCP Hub Sync & Sessions

## Affected Spec Areas
- `docs/master/product/features/mcp-hub.md` — MCP Hub feature spec (server management, session management)

## New Capabilities

### Explicit Default Session
- Admins can designate one session per MCP server as the **default session**
- When a server has exactly one session, that session is automatically the default — no manual action needed
- The default session is the session used for sync and tool calls when no specific session is specified
- The default session is visibly marked in the session list UI
- If the default session is deleted, the admin is notified and must choose a new default (if other sessions exist)

### Sync Visibility Control
- The sync action is only available (visible and enabled) when at least one session is configured for the server
- Servers with zero sessions show the sync action as disabled or hidden, with a clear explanation

### Sync Resilience
- The sync tool tolerates non-fatal errors during the MCP initialize handshake
- If tools/list succeeds, sync is considered successful — any initialize warnings are surfaced but do not block the result

## Modified Capabilities

### MCP Server List Display
- **Before**: The server list could show two System entries — one from backend virtual prepending and one from database seeding
- **After**: The server list shows exactly one System entry, visually distinct from real MCP servers, with no duplication

### Sync Tool Behavior
- **Before**: Sync fails entirely if the initialize handshake encounters any error
- **After**: Sync reports partial success when the initialize handshake has issues but tools/list succeeds; warnings are shown alongside the tool list

### Session Management
- **Before**: The "first active session ordered by created_at" is implicitly used as the default for sync and tool calls
- **After**: An explicit `is_default` flag determines which session is used; the implicit ordering fallback is removed

## Removed Capabilities
- **Implicit default session by creation order**: The behavior of using the first-created active session as the default is retired in favor of the explicit `is_default` flag. All consumers that relied on this implicit behavior must use the explicit default session instead.

## Spec Update Instructions

In `docs/master/product/features/mcp-hub.md`:

1. **Update "Key Concepts" section**:
   - Add an entry for **Default Session**: "The session used for sync and tool calls when no specific session is specified. Each MCP server has exactly one default session — explicitly set by the admin, or automatically assigned when only one session exists."
   - Update the **Session Management** entry to note the default session concept

2. **Update "What It Does" section**:
   - Add: "Supports designating a default session per server for predictable tool routing"
   - Add: "Automatically treats a server's sole session as the default"

3. **Update "Acceptance Criteria" section**:
   - Add: "The MCP server list shows exactly one System entry, visually distinct from user-registered servers"
   - Add: "Sync succeeds when tools/list works, even if the initialize handshake has warnings"
   - Add: "The sync action is only available when at least one session is configured for the server"
   - Add: "Admins can designate a default session; sole sessions are automatically the default"
   - Add: "The default session is visibly indicated and used for sync and tool calls"

4. **Ensure no regression**: Verify existing acceptance criteria for session management, credential binding, and passthrough session type remain intact and continue to work alongside the new default session concept.
