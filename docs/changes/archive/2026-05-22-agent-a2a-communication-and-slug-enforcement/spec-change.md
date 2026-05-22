# Spec Change: Agent-to-Agent Communication and Slug Enforcement

## Affected Spec Areas
- openspec/specs/agent-runtime-session-management.md
- openspec/specs/communication-hub-routing.md
- openspec/specs/sop-management-and-execution.md
- openspec/specs/agent-role-and-permission-model.md
- openspec/specs/agent-type-definition.md
- openspec/specs/mcp-server-registration.md
- openspec/specs/agent-plan-preview.md

## New Capabilities
- Agent-to-agent invocation via Communication Hub using A2A protocol and target agent type slug input.
- Runtime auto-provisioning of a dynamic receiver agent instance when target is unavailable.
- Same-session A2A conversation continuity between requester and dynamically created receiver.
- Step-definition-driven A2A target permission derivation in SOP definitions (same derivation model as skills and MCP tools).
- Allowed agent type slug preview in agent role edit UX.
- Agent-delegation steps rendered in both plan list and topology diagram preview surfaces.

## Modified Capabilities
- SOP management continues using existing editor flow, but now derives A2A associations and permissions from delegation step definitions.
- Naming validation for agent type names, agent names, and MCP server names now enforces slug-only format.
- Session lifecycle behavior expands to support dynamic receiver create/join/disconnect/remove semantics for A2A flows.

Before:
- Agent-to-agent orchestration depended on manual or UI-triggered setup assumptions.
- SOP delegation permissions required separate explicit modeling outside step-derived association flow.
- Naming constraints were inconsistent and allowed invalid routing identifiers.
- Plan preview rendering emphasized MCP/tool-oriented visibility and did not fully represent agent-delegation steps.

After:
- A2A invocation can self-heal target availability by dynamic receiver provisioning.
- SOP step definitions directly drive A2A associations and permission resolution.
- Plan list and topology previews include agent-delegation steps alongside other execution steps.
- Slug-only identifiers ensure deterministic routing and integration-safe naming.

## Removed Capabilities
- Implicit tolerance for non-slug naming in affected entities.
- Dependence on separately maintained A2A permission mappings that are not derived from SOP step definitions.

## Spec Update Instructions
- Update session management spec with dynamic receiver lifecycle states and termination conditions.
- Update Communication Hub spec with A2A target resolution and runtime creation fallback.
- Update SOP spec to define A2A association/permission derivation from delegation step definitions.
- Update role/permission spec with allowed agent type preview expectations.
- Update agent type and MCP server specs to require slug validation on create/update.
- Update plan preview spec to include agent-delegation step rendering rules for both list and topology diagram views.
