# Passthrough Sessions — Specification Delta

## 1. Affected Spec Areas
- MCP Server Registration & Configuration
- Session Management (Role Configuration, Tool Testing)
- Agent Identity Propagation
- Tool Registry Test Workflow

## 2. New Capabilities
- Ability to designate an MCP server as supporting "passthrough" session type
- Automatic forwarding of agent identity to passthrough-type MCP servers (no explicit session selection)
- Tool registry test feature supports agent identity selection for passthrough servers

## 3. Modified Capabilities
- Role configuration UI and workflow updated to allow associating MCP servers with passthrough sessions
- Communication Hub logic updated to detect passthrough session type and forward agent identity
- Tool registry test workflow updated to present agent identity selection instead of session selection for passthrough servers

## 4. Removed Capabilities
- None. All existing session-based workflows remain available and unchanged for non-passthrough MCP servers.

## 5. Spec Update Instructions
- Update MCP server registration and configuration documentation to describe passthrough session type and its intended use
- Revise session management and role configuration specs to include passthrough as a valid session type
- Update tool registry test workflow documentation to clarify agent identity selection for passthrough servers
- Ensure all acceptance criteria from the PRD are reflected in the updated specifications
