# Communication Hub

> **Authoritative documentation**: [Communication Hub Architecture](communication-hub/architecture.md)

The Communication Hub is the platform's central message broker and Agent Gateway. It handles three messaging flows — Web UI ↔ Agent conversations over WebSocket, Agent ↔ Agent internal routing, and inbound agent execution requests from Agent Runtime — all secured with mTLS certificate enforcement and Control Center-integrated identity token management.

Chat status is no longer process-local: the hub projects the authoritative activity state owned by Control Center and hydrates it on connect, and it routes an intervention response to whichever Agent Runtime instance can load the durably paused turn (de-duplicated to a single dispatch). It gains no data access and no signing rights — it remains a forward-only receiver.

For full architecture details including component diagrams, the parallel authentication paths (mTLS, API key, user OAuth for the management surface), message types, intervention routing, and system tool routing, see the authoritative module doc at [communication-hub/architecture.md](communication-hub/architecture.md).
