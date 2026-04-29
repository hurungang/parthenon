# Module: comm-hub — Tech Spec

## Overview

The communication hub is the central message broker for real-time interactions in the Parthenon platform. It provides a Redis pub/sub backbone with per-session typed channels, a WebSocket server that authenticates browser clients and bridges them to the broker, an inter-agent routing layer that delivers messages to target agent instance channels, and a session context manager that stores active session state in Redis for low-latency access during agent execution.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `MessageBroker` | Redis pub/sub implementation with per-session typed message channels; handles publishing to session channels and delivering messages to subscribed consumers |
| `WebSocketServer` | FastAPI WebSocket endpoint handler that authenticates the incoming connection using the bearer token, subscribes to the session channel via `MessageBroker`, and bridges bidirectional traffic between the browser client and the message broker |
| `AgentRouter` | Service class that routes inter-agent messages from a source agent instance to a target instance's pub/sub channel via `MessageBroker`; enables agent-to-agent communication |
| `SessionContextManager` | Service class that stores and retrieves active session state — including participants, turn count, and current status — in Redis with a configurable TTL; context is flushed to PostgreSQL when the session closes |

### Frontend

| Component | Description |
|-----------|-------------|
| `ChatPage` | Real-time user-to-agent chat interface backed by the WebSocket connection; renders message history and a question-answer input panel |
| `useChatSession` | React hook that manages the full WebSocket connection lifecycle: opening the connection, handling inbound message queuing, tracking pending question state requiring user input, and executing reconnection logic on disconnect |

---

## API Endpoints

| Protocol | Path | Purpose |
|----------|------|---------|
| `WebSocket` | `/ws/sessions/{session_id}` | Bidirectional real-time messaging for user ↔ agent chat |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `MessageBroker` | class | Redis pub/sub broker with per-session typed message channels | `backend/app/services/comm_hub/broker.py` |
| `WebSocketServer` | class | WebSocket endpoint handler; authenticates connection and bridges to MessageBroker | `backend/app/api/ws/chat.py` |
| `AgentRouter` | class | Routes inter-agent messages to target instance channels via MessageBroker | `backend/app/services/comm_hub/agent_router.py` |
| `SessionContextManager` | class | Stores and retrieves active session state in Redis with configurable TTL; flushed to PostgreSQL on session close | `backend/app/services/comm_hub/session_context.py` |
| `ChatPage` | component | Real-time user-to-agent chat interface backed by WebSocket connection | `frontend/src/pages/chat/ChatPage.tsx` |
| `useChatSession` | hook | Manages WebSocket connection lifecycle, inbound message queue, pending question state, and reconnection | `frontend/src/hooks/useChatSession.ts` |
