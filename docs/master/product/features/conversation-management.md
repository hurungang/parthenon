# Conversation Management

## Overview
Conversation Management ensures that all interactions—across users, agents, and tools—are persistently recorded, auditable, and available for replay. This feature supports compliance, transparency, and operational review for all conversation types. For conversation-type agents, the system provides persistent, user-named sessions with automatic title generation, session management, and full turn history preservation.

## Who Uses It
- Enterprise Admins: Monitor and review conversation history
- Compliance Auditors: Audit and replay conversations for regulatory purposes
- Business Users: Review past interactions with agents

## What It Does
- Persists all conversation turns, including user, agent, tool, and agent-to-agent messages
- Renders agent messages with content-type awareness: messages containing HTML are displayed as rich formatted text instead of raw markup, while plain-text and markdown messages continue to display with existing whitespace and line-break preservation
- Provides a maximize button on each rendered agent message, allowing operators to expand individual outputs into a focused full-view for detailed review without chat UI distractions
- Provides persistent, user-named conversation sessions for conversation-type agents
- Automatically generates session titles from the first user message
- Enables users to start, resume, end, and archive conversation sessions
- Lists all user's conversation sessions in a Sessions tab within the agent type view
- Shows continuously updated current-session token usage in conversational session views
- Allows active conversations to continue when only token budget thresholds are reached
- Shows a clear thinking indicator while the primary conversational agent is processing
- Shows delegation status in chat using the format "Delegating to agent <agent_type>" when delegation begins
- Keeps a visible waiting indicator during delegated work until a delegated response or terminal status is received
- Shows delegation execution snippets in a compact folded state, with optional expansion for additional detail
- Shows a clear timeout or failure end state so users are not left in indefinite waiting
- Shows an inline intervention dialog (approval, choice, or text) in the conversation when a delegated sub-agent requests human input, replacing the previous indefinite waiting state
- Pauses the conversation with a distinct "Waiting for your input" indicator and blocks new message input until the intervention is resolved
- Surfaces pending intervention requests automatically when a user reconnects to a conversation that was mid-intervention
- Supports audit and replay of any conversation
- Provides UI access to search and review conversation history
- Ensures all turn types are captured and traceable

## Key Concepts
- **Conversation Persistence**: Storing all conversation data for future access
- **Conversation Agent Session**: A persistent, bounded conversation with a conversation-type agent; includes automatic title generation, session lifecycle management (active → closed → archived), and full turn history
- **Session Auto-Naming**: Automatic generation of session titles from the first user prompt using the agent's configured LLM
- **Session Lifecycle**: Transitions between active (accepting messages), closed (ended by user), and archived (hidden from active list but retained for audit)
- **Current-Session Token Visibility**: Ongoing display of conversational token consumption during active sessions
- **Conversation Continuation Policy**: Conversational sessions continue unless non-token guardrails (for example recursion, iteration, delegation boundary, or timeout policies) require termination
- **Delegation Visibility Cues**: In-conversation progress signals (thinking, delegating, waiting, completion, timeout/failure, intervention wait) that make delegated execution understandable to non-technical users. The intervention wait state appears when a delegated sub-agent requests human input, showing the intervention dialog inline and blocking new messages until resolved. Delegation status events and HITL intervention support are also available in non-conversational agent execution logs — the conversation UI handles conversational delegation; the execution log view handles non-conversational delegation.
- **Folded Delegation Snippets**: Compact delegation progress lines that are collapsed by default and can be expanded on demand without overwhelming chat readability
- **Conversation Session Intervention Block**: While an intervention request is outstanding, the conversation session enters a distinct blocked state — message input is disabled and the session list shows a `waiting_for_human` indicator, allowing operators to identify conversations needing attention
- **Turn Types**: Different types of conversation events (user, agent, tool, agent-to-agent, intervene_request, intervene_response). Intervention turns now include delegation chain metadata so auditors can trace which sub-agent at which depth made the request
- **Audit and Replay**: Reviewing and replaying past conversations
- **Conversation Traceability**: Ensuring every interaction is logged and accessible

## Acceptance Criteria
- All conversation turns are persistently stored and accessible
- Users can create new conversation sessions for conversation-type agents
- Session titles are automatically generated from the first user prompt
- Users can view all their conversation sessions in a Sessions tab (agent type view)
- Users can resume previous sessions with full turn history restored
- Users can end or archive sessions to manage their workspace
- Sessions are user-scoped (users only see their own sessions)
- Conversations can be searched, audited, and replayed from the UI
- All turn types are captured and classified, including intervene request creation (context, type, options) and intervene response (operator, value, timestamp)
- Conversation history is available for compliance and operational review
- All access to conversation data is logged
- Current-session token usage remains visible throughout active conversational sessions
- Conversational sessions are not hard-stopped solely due to token budget thresholds
- While the primary conversational agent is processing, users see a visible thinking indicator in chat
- When delegation starts, chat displays "Delegating to agent <agent_type>" before the delegated reply
- During delegated execution, a visible waiting indicator remains present until response, timeout, or failure
- Delegation execution snippets appear folded by default and can be expanded by users on demand
- Folded snippets provide enough context for users to confirm progress at a glance
- If delegated execution times out or fails, users see a clear final status instead of indefinite waiting
- When a delegated sub-agent requests intervention in a conversation, an intervention dialog (approval, choice, or text) appears inline in the chat at the point of delegation
- During an intervention wait, the conversation shows a distinct "Waiting for your input" indicator and blocks new message input until the intervention is resolved
- The user's intervention response is recorded as a conversation turn visible in history and replay
- If a user disconnects while an intervention dialog is open, the pending intervention request is re-surfaced automatically when the user reconnects
- The parent conversational session shows a `waiting_for_human` state in the session list and dashboard while a sub-agent intervention is outstanding

## Out of Scope
- Agent execution engine internals and model reasoning
- Content generation quality and model selection
- Storage schema and database implementation details
