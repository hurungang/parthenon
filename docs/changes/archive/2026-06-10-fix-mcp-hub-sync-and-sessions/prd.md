# PRD: Fix MCP Hub Sync & Sessions

## Epic Overview
The MCP Hub is the gateway through which Parthenon connects to external tool servers. Several quality issues are undermining administrator confidence and blocking productive use of the hub: a duplicate system-level entry causes confusion in the server list, the sync tool fails for servers that are otherwise functional, the sync action is misleadingly shown for servers that cannot possibly sync, and the absence of an explicit default session makes tool routing unpredictable when multiple sessions exist. This epic resolves all four issues to make MCP Hub server and session management reliable, predictable, and trustworthy.

## Business Goals
- Eliminate visual clutter and confusion caused by duplicate entries in the MCP server list
- Increase sync success rate so admins can reliably verify tool availability from configured servers
- Prevent admins from wasting time on sync actions that are guaranteed to fail (no sessions)
- Enable predictable tool routing by introducing an explicit default session concept
- Maintain backward compatibility — no disruption to existing server registrations or session configurations

## Users & Personas
- **Enterprise Admin**: Needs a clean, accurate server list and reliable sync to confidently manage tool integrations. Wants to designate which session is used by default without ambiguity.
- **AI Agent (indirect)**: Benefits from predictable tool routing when multiple sessions exist — the agent always knows which credentials will be used.
- **Platform Operator**: Needs the hub UI to reflect reality — no phantom entries, no misleading actions.

## User Stories
- As an Enterprise Admin, I want to see exactly one System entry in the MCP server list, so that I am not confused about which one represents the platform's built-in tools.
- As an Enterprise Admin, I want the sync tool to succeed for servers whose tools are demonstrably reachable, so that I can confirm tool availability without encountering false errors.
- As an Enterprise Admin, I want the sync action hidden (or disabled) for servers that have zero configured sessions, so that I do not attempt an action that cannot succeed.
- As an Enterprise Admin, I want to mark one session as the default for a server, so that tool routing is explicitly controlled when multiple sessions exist.
- As an Enterprise Admin, I want a server's sole session to be automatically treated as the default, so that I do not need to manually configure a default when only one session exists.

## Acceptance Criteria

### Duplicate System Entry
- The MCP server list displays exactly one System entry — no duplicates
- The System entry is visually distinct from real MCP servers (e.g., labeled as a virtual/platform entry)
- Creating or deleting real MCP servers does not affect the System entry

### Sync Resilience
- Sync succeeds for servers where the tools/list operation works, even if the initialize handshake has issues
- Sync results clearly indicate which tools were discovered and any warnings from the handshake
- Sync failure messages are specific and actionable (not generic "error")

### Sync Visibility & Session Dependency
- The sync action is visible and enabled only when a server has at least one configured session
- For servers with zero sessions, the sync action is hidden or disabled with an explanatory tooltip

### Default Session
- When a server has multiple sessions, the admin can designate exactly one as the default
- When a server has exactly one session, it is automatically the default
- The default session is visibly indicated in the sessions list
- If the default session is deleted and other sessions remain, the admin is prompted to select a new default
- Sync and tool calls use the default session when no specific session is specified

## Out of Scope
- Redesigning the overall MCP Hub page layout or navigation
- Changing the MCP protocol handshake behavior (this is a client-side resilience improvement)
- Adding batch sync (sync all servers at once)
- Changing the System entry to be a real, editable MCP server
- Supporting per-tool session overrides (tool always uses the default session)
- Passthrough session type — this is already covered by the existing MCP Hub spec

## Dependencies & Constraints
- Existing MCP server backend infrastructure and database schema
- Existing session management API endpoints and UI components
- Must not break the MCP Demo App reference implementation
- Must preserve existing permission and role-to-session mappings
- `is_default` flag requires a database migration (has_db_changes: true)
