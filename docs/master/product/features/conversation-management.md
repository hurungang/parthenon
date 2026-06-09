# Conversation Management

## Overview
Conversation Management ensures that all interactions—across users, agents, and tools—are persistently recorded, auditable, and available for replay. This feature supports compliance, transparency, and operational review for all conversation types. For conversation-type agents, the system provides persistent, user-named sessions with automatic title generation, session management, and full turn history preservation.

## Who Uses It
- Enterprise Admins: Monitor and review conversation history
- Compliance Auditors: Audit and replay conversations for regulatory purposes
- Business Users: Review past interactions with agents

## What It Does
- Persists all conversation turns, including user, agent, tool, and agent-to-agent messages
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
- **Delegation Visibility Cues**: In-conversation progress signals (thinking, delegating, waiting, completion, timeout/failure) that make delegated execution understandable to non-technical users
- **Folded Delegation Snippets**: Compact delegation progress lines that are collapsed by default and can be expanded on demand without overwhelming chat readability
- **Turn Types**: Different types of conversation events (user, agent, tool, agent-to-agent, intervene_request, intervene_response)
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
