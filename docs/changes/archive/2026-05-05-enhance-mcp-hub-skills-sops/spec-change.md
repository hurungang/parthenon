
# Specification Change: Enhance MCP Hub, Skills, and SOPs

## Affected Product Documentation
- Product spec: `docs/master/product/` (MCP Hub, Skills, SOPs sections)
- UX prototype: `docs/master/ux/prototype/index.html`
- Data model: `docs/master/data-model/modules/mcp-hub/entities.md`, `docs/master/data-model/modules/skills/entities.md`
- Technology spec: `docs/master/technology/modules/skills/tech-spec.md`

## New and Enhanced Capabilities (WHAT changes)
- MCP Hub: Add full CRUD lifecycle for MCP servers, sessions, and credentials
- Tool Repository: Add view listing all tools from all servers, grouped by server
- Tool-to-skill mapping: Add visibility of which skills use each tool
- Server sync: Add ability to trigger sync and view sync status/history
- Sessions: Add support for multiple named sessions per MCP server with identity/credential bindings
- Skills: Support multi-tool binding, role assignment, dependency visualization, and tool namespace display
- SOPs: Add ordered step management, step type/target selection, per-step instructions, and role assignment

## Modified Capabilities
- Skills: Expand from single-tool/simple skills to multi-tool, role-assignable, visually composable skills
- MCP Hub: Expand from basic server list to management with sessions, credentials, sync, and tool/skill mapping
- SOPs: Expand from placeholder to full-featured, ordered, multi-step workflow with instructions and role assignment

## Removed Capabilities
- None (all changes are additive or enhancements)

## Spec Update Instructions (WHAT to update)
- Update product spec in `docs/master/product/` to describe the new and enhanced MCP Hub, Skills, and SOPs features, including all new user-facing capabilities
- Update UX prototype in `docs/master/ux/prototype/index.html` to reflect new user flows and visualizations for MCP Hub, Skills, and SOPs
- Update data model in `docs/master/data-model/modules/mcp-hub/entities.md` and `docs/master/data-model/modules/skills/entities.md` to include new/modified entities and relationships (sessions, tool-to-skill mapping, SOP instructions)
- Update technology spec in `docs/master/technology/modules/skills/tech-spec.md` to describe the new and enhanced product capabilities (not implementation details)
- Ensure all acceptance criteria from the PRD are reflected in the master documentation as user-observable requirements
