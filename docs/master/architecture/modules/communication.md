# Communication Hub

> **Authoritative documentation**: [Communication Hub Architecture](communication-hub/architecture.md)

The Communication Hub is the platform's central message broker and Agent Gateway. It handles three messaging flows — Web UI ↔ Agent conversations over WebSocket, Agent ↔ Agent internal routing, and inbound agent execution requests from Agent Runtime — all secured with mTLS certificate enforcement and Control Center-integrated identity token management.

For full architecture details including component diagrams, dual-authentication flow (mTLS + API key), message types, intervention routing, and system tool routing, see the authoritative module doc at [communication-hub/architecture.md](communication-hub/architecture.md).
