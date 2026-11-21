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
- Lists all user's conversation sessions in a Sessions tab within the agent type view, with an active/ended filter, a default recent time window that can be narrowed by date range, and pagination
- Provides a four-action session bar in every conversational chat — View All Sessions, New Session, End Session, Exit — where Exit only closes the view (the session stays active and resumes with full history on reopen) and End closes the session and stops any work still in flight
- Serves the management-scoped [Control Center Assistant](control-center-assistant.md) as a consumer of the same conversational infrastructure
- Shows continuously updated current-session token usage in conversational session views
- Allows active conversations to continue when only token budget thresholds are reached
- Shows a clear thinking indicator while the primary conversational agent is processing
- Shows the assistant's activity from a single persisted, authoritative state — thinking, calling a tool, delegating, waiting for the user, or finished (with clear terminal failed and timed-out outcomes) — so the indicator always reflects real progress and never lingers after completion
- Restores the latest activity status when a conversation is reopened, reloaded, or reconnected, matching the agent's real state at that moment rather than the state when the user left
- Keeps the "waiting for your input" state visible continuously from the moment the agent pauses until the intervention is resolved, with no blank gap between the pause and the intervention prompt
- Distinguishes plainly between **waiting for the user**, **resumed and continuing**, **resolved**, and **no longer resumable**, and shows "waiting for your input" only when the turn can actually be answered
- Holds paused turns durably: a pending confirmation survives a restart or hand-off and remains answerable, and answering it continues the work with the same history and context; a turn that genuinely cannot be resumed ends with one clear, actionable message instead of a misleading timeout
- Applies a confirmed change exactly once even when the approval is delivered more than once, and keeps history intact — the response and the resumed (or resolved) outcome each appear once, in order
- Includes the optimization conversation as a conversation channel of the agent that owns it
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
- **Session Action Bar**: A consistent four-action control in every conversational chat — View All Sessions (browse and resume in place), New Session (start fresh; the previous session stays active), End Session (close the session and stop in-flight work; the next open starts fresh), and Exit (close the view only). Switching or ending is unavailable while a turn is still running
- **Exit vs End**: Exit preserves the session for later; End deliberately closes it. Reopening a conversation always resumes the most recent active session
- **Session Auto-Naming**: Automatic generation of session titles from the first user prompt using the agent's configured LLM
- **Session Lifecycle**: Transitions between active (accepting messages), closed (ended by user), and archived (hidden from active list but retained for audit)
- **Current-Session Token Visibility**: Ongoing display of conversational token consumption during active sessions
- **Conversation Continuation Policy**: Conversational sessions continue unless non-token guardrails (for example recursion, iteration, delegation boundary, or timeout policies) require termination
- **Delegation Visibility Cues**: In-conversation progress signals (thinking, calling a tool, delegating, waiting, completion, timeout/failure, intervention wait) that make delegated execution understandable to non-technical users. The intervention wait state appears when a delegated sub-agent requests human input, showing the intervention dialog inline and blocking new messages until resolved. Delegation status events and HITL intervention support are also available in non-conversational agent execution logs — the conversation UI handles conversational delegation; the execution log view handles non-conversational delegation.
- **Persisted Activity State**: One authoritative record per conversation turn of what the agent is doing right now — thinking, calling a tool, delegating, waiting for the user, or finished, with terminal failed and timed-out outcomes. The chat indicator, the session list, and reconnection all read from it, so status never depends on which server is serving the conversation. It contains status information only, never identity tokens, credentials, or other sensitive material.
- **Durable Paused Turn**: A conversational turn that pauses for human input outlives the process that paused it. It remains pending and answerable after a restart or on any other instance, and continues from the pause point when answered. The answerable window is bounded; answering after it is treated as a legitimately unrecoverable turn.
- **Resume Status Vocabulary**: Four plainly worded states an operator can rely on — waiting for the user, resumed and continuing, resolved, and no longer resumable. "Resumed and continuing" appears only when a turn was actually recovered (after reconnect or restart), never for a normal in-process answer.
- **Single-Application Guarantee**: A confirmed change is applied exactly once, even if the approval is delivered repeatedly or the response spans an instance change. A denied or expired confirmation applies nothing.
- **Optimization Conversation**: A conversation channel of the agent being optimized, held under that agent's own identity and permissions. It is separate from the agent's business conversations — neither can turn into the other — and its turns, questions, answers, approvals, and results are retained with the agent's conversation records. See [Sandboxed Scripting & Model-Authored Composition](sandboxed-scripting.md).
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
- Every conversational chat offers a session action bar with view all / new / end / exit actions
- Closing the view (exit) keeps the session active and the most recent active session resumes with full history when reopened
- Viewing all sessions shows active and ended sessions, defaults to a recent time window, supports a chosen date range, and is paginated; ended sessions are clearly marked and cannot be resumed
- Starting a new session leaves the previous session active; ending a session closes it and stops any work still in progress
- Session switching and ending are unavailable while a turn is still being processed
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
- The chat indicator reflects the agent's real current activity (thinking, calling a tool, delegating, waiting for the user, finished) and never keeps spinning after a turn reaches a terminal state
- The intervention wait state is shown continuously from the moment the agent pauses until the intervention is resolved — no blank gap, including on the tool-calling phase that precedes a confirm-before-write prompt
- Reopening, reloading, or reconnecting to a running conversation immediately shows the agent's current status, and a conversation mid-intervention re-surfaces its pending request
- A pending intervention remains answerable after a restart of any service in the path and can be answered on a different instance, with one coherent conversation for the operator
- A confirmed change is applied exactly once under duplicate or repeated delivery; a denied or expired confirmation applies nothing
- A turn that cannot be resumed resolves to a clear terminal state with an actionable message, message input is re-enabled, and the outstanding confirmation is no longer presented as actionable
- The conversation distinguishes waiting for the user, resumed and continuing, resolved, and no longer resumable
- The response and the resumed (or resolved) outcome each appear once, in order, in conversation history and in replay
- Optimization conversations are retained as a channel of the owning agent, separate from its business conversations, with their questions, answers, approvals, and results reviewable
- The persisted activity state contains only status information — never identity tokens, credentials, or other sensitive material — and is scoped per conversation (and per tenant when multi-tenancy is enabled)

## Out of Scope
- Agent execution engine internals and model reasoning
- Content generation quality and model selection
- Storage schema and database implementation details
- Resumption of non-conversational (task) executions and their logs
- Compensation for third-party side effects that tools already performed (the guarantee covers the conversational turn, not external systems)

## Multi-Tenancy Note

When multi-tenancy is enabled (see [Multi-Tenancy](multi-tenancy.md)), conversations are tenant-owned; only the owning tenant's members and agents can browse, replay, or export them. With multi-tenancy disabled (the default), behavior is unchanged — the deployment operates as the root tenant's workspace.
