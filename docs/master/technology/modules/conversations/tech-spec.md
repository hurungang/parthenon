# Module: conversations — Tech Spec

## Overview

The conversations module provides complete and durable persistence of every interaction that passes through the platform. Each conversation session groups a bounded set of turns; each turn captures a single message from a participant (user, agent, system, or tool); each tool call within a turn is separately recorded. This three-level structure ensures full audit trails and supports session replay for debugging and compliance purposes.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `ConversationStore` | Service class that writes conversation sessions, turns, and tool call records synchronously during agent execution; synchronous writes ensure the audit trail is complete even if a session fails mid-execution |
| `ConversationRouter` | FastAPI router exposing filtered listing of conversation sessions and detailed retrieval of a single session with all its turns and embedded tool call records |
| `ConversationSession` | SQLAlchemy model for a bounded interaction context; records the agent instance, participants, start and end times, and final status |
| `ConversationTurn` | SQLAlchemy model for a single message within a session; stores the role (user/agent/system/tool), content, timestamp, and sequence number |
| `ToolCallRecord` | SQLAlchemy model recording a tool invocation that occurred within a specific turn; stores the tool name, input arguments, result, and timing |

### Frontend

| Component | Description |
|-----------|-------------|
| `ConversationHistoryPage` | Session list with date range and agent type filters; expands to a turn-by-turn conversation viewer with tool call detail inline |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/conversations` | List conversation sessions (filterable by agent type, date, status) |
| `GET` | `/api/v1/conversations/{session_id}` | Get a session with all turns and embedded tool call records |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `ConversationStore` | class | Persists conversation sessions, turns, and tool call records synchronously during execution | `backend/app/services/conversations/store.py` |
| `ConversationRouter` | router | Query endpoints for filtered session listing and detailed session retrieval | `backend/app/api/v1/conversations.py` |
| `ConversationSession` | model | SQLAlchemy model for a bounded interaction context (agent instance, participants, status) | `backend/app/db/models/conversations.py` |
| `ConversationTurn` | model | SQLAlchemy model for a single message in a session (role, content, sequence) | `backend/app/db/models/conversations.py` |
| `ToolCallRecord` | model | SQLAlchemy model recording a tool invocation within a turn (tool, inputs, result, timing) | `backend/app/db/models/conversations.py` |
| `ConversationHistoryPage` | component | Session list with date/agent filter and turn-by-turn conversation viewer | `frontend/src/pages/conversations/ConversationHistoryPage.tsx` |
