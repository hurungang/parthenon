# Specification Change — Conversation Agent Sessions

## Affected Spec Areas
- Product specification: `docs/master/product/agents.md`, `docs/master/product/conversation-agents.md`
- UX prototype: `docs/master/ux/`
- Technology spec: `docs/master/technology/agent-execution.md`, `docs/master/technology/session-management.md`

## New Capabilities
- Persistent, user-named conversational agent sessions
- Automatic session title generation from first prompt
- "Instances" or "Sessions" tab listing all conversation agent sessions
- UI entry points to start, resume, and end conversations
- Ability to archive/end sessions from the UI

## Modified Capabilities
- Agent executions list now displays agent type, status, and session name for conversational agents (previously only agent type and status)
- Conversation agent definition flow no longer requires explicit output type selection (now implicit)
- Session management UI and navigation updated for discoverability and ease of use

## Removed Capabilities
- None

## Spec Update Instructions
- Update product spec to describe session-based conversational agent flows and UI
- Add details on session naming, listing, and management to `conversation-agents.md`
- Update UX prototype to include Instances/Sessions tab and entry points for session actions
- Revise technology spec to cover new session management logic and agent executions list changes
- Remove references to output type selection from conversation agent definition flows
