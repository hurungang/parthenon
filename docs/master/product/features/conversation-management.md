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
- **Turn Types**: Different types of conversation events (user, agent, tool, agent-to-agent)
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
- All turn types are captured and classified
- Conversation history is available for compliance and operational review
- All access to conversation data is logged
- Current-session token usage remains visible throughout active conversational sessions
- Conversational sessions are not hard-stopped solely due to token budget thresholds
