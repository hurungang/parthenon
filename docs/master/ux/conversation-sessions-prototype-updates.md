# UX Prototype Updates — Conversation Agent Sessions

## Required Updates to `docs/master/ux/prototype/index.html`

The following UI components need to be added to the UX prototype to reflect the conversation agent sessions feature:

### 1. Agent Type Details Dialog — Sessions Tab

**Location**: Agent Management view → Agent Type row click → Details dialog

**New Tab**: Add "Sessions" tab (4th tab, after Details / Plan / Executions)

**Visibility Rule**: Show Sessions tab ONLY when `agent_type.input_type === 'conversation'`

**Tab Content**:

- **Header**: "Conversation Sessions" title and "Start New Conversation" button (primary action)
- **Session List Table**:
  - Columns: Title, Status, Last Active, Actions
  - Title: Auto-generated session title (or "Untitled" placeholder)
  - Status: Chip component (Active, Closed, Archived)
  - Last Active: Relative timestamp (e.g., "2 hours ago")
  - Actions: Resume button, End icon button, Archive icon button
- **Empty State** (when no sessions exist):
  - Icon: conversation bubble
  - Message: "No conversation sessions yet"
  - CTA: "Start New Conversation" button

**Interactions**:
- Click "Start New Conversation" → Opens ChatPage with new session
- Click session title or Resume → Opens ChatPage with full history loaded
- Click End → Shows confirmation dialog, then transitions session to `closed`
- Click Archive → Shows confirmation dialog, then transitions session to `archived`
- After End/Archive → Session list refreshes automatically

### 2. Agent Instance Dashboard — Session Column

**Location**: Agent Executions view (formerly Agent Instances)

**New Column**: Add "Session" column after "Agent Type" column

**Column Behavior**:
- **For conversation-type agents**: Display the linked conversation session title
- **For non-conversational agents**: Leave cell empty or display "—"
- Make session title clickable → Opens ChatPage with session context

### 3. Chat Page — Session Title Header

**Location**: Real-time chat interface (`/agents/:agentTypeId/chat/:sessionId`)

**New Header Component**:

- Back button (navigate to Agent Management)
- Session Title (live-updated via WebSocket):
  - Initial state: "Untitled" or loading skeleton
  - After title_update event: Display generated title
- Session Status badge (Active, Closed, Archived)
- Actions menu: End Session, Archive Session

**WebSocket Behavior**:
- Title starts as "Untitled" or null
- After first user message processed, `title_update` event received
- Title updates in real-time without page reload

### 4. Agent Type Form — Output Type Field

**Location**: Agent Type create/edit dialog

**Change**: Hide "Output Type" field when `input_type === 'conversation'`

**Reason**: Output type is implicit for conversation agents (they always return conversational responses)

## Visual Design Notes

### Status Chips
- **Active**: Green background, "Active" text
- **Closed**: Gray background, "Closed" text
- **Archived**: Blue background, "Archived" text
- **Error**: Red background, "Error" text

### Action Buttons
- **Resume**: Primary button, blue, "Resume" text
- **End**: Icon button (stop/close icon), gray, hover shows "End Session" tooltip
- **Archive**: Icon button (archive/folder icon), gray, hover shows "Archive Session" tooltip

### Confirmation Dialogs
- **End Session**: "Are you sure you want to end this conversation? This action cannot be undone."
- **Archive Session**: "Archive this conversation? It will be hidden from the active list but retained for audit."

## Responsive Behavior

- Sessions tab should be full-width within the dialog
- Session list table should stack/scroll horizontally on mobile
- Chat page header should collapse session title on small screens
- Action buttons should be accessible on touch devices (min 44px tap target)

## Implementation Status

✅ **IMPLEMENTED**: All UI components above have been implemented in the frontend codebase

- `ConversationSessionsTab` component created and integrated
- Sessions tab conditionally rendered for conversation-type agents
- Session column added to `AgentInstanceDashboardPage`
- Chat page header updated with live session title
- All interactions tested and verified

**Next Step**: Update HTML prototype mock to include visual representations of these components for design reference and stakeholder review.
