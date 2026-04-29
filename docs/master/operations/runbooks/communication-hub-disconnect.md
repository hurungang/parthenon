# Runbook: Communication Hub Connection Dropped

## Symptoms

- Web UI shows a disconnected or reconnecting state
- Agent responses stop appearing in the chat interface
- Logs from `communication-hub` contain repeated `WebSocket disconnect` events, often with the same session IDs
- Users report that conversations appear frozen or that responses from agents are not being delivered

---

## Resolution Steps

1. Check the Communication Hub container or pod health immediately. An out-of-memory kill or a crash loop is the most common cause of mass WebSocket disconnections. Check the container exit code and recent memory usage metrics. If the hub restarted, all active WebSocket connections will have been dropped simultaneously — this explains a sudden drop affecting all users rather than individual sessions.

2. Review the active WebSocket connection count metric in the Communication Hub dashboard. A drop to zero confirms a hub restart rather than a gradual client-side issue. A gradual decline suggests individual connection timeouts or nginx proxy disconnects rather than a hub crash.

3. Confirm that Redis pub/sub connectivity is healthy from the Communication Hub. The hub depends on Redis for inter-service message routing — a Redis connection failure causes the hub to be unable to deliver messages even if WebSocket connections appear established. Check Redis health metrics and the hub's logs for Redis connection error messages.

4. Check the nginx reverse proxy configuration for the WebSocket path. The `proxy_read_timeout` directive must be set to a value high enough to allow long-lived idle WebSocket connections to remain open. If `proxy_read_timeout` is set to a low value (e.g., 60 seconds), nginx will terminate connections during periods of low message activity, producing disconnect events that look like hub failures but are actually proxy timeouts.

5. Confirm that the frontend client-side reconnection logic is functioning. The Web UI is designed to automatically reconnect on WebSocket close events. If the hub has recovered but clients remain disconnected, check the `useChatSession` hook behaviour — reconnect attempts should be visible in the browser developer console. If clients are not reconnecting, there may be a frontend configuration issue with the WebSocket endpoint URL.

---

## Notes

- After the hub recovers, active agent instances from before the disconnect may still be running in the Agent Engine — their sessions are still valid and will resume delivering messages once the client reconnects
- If the hub is experiencing repeated OOM kills, increase the memory limit for the `communication-hub` container and review the active connection count at the time of the kill to determine whether the limit needs to be raised permanently
- Redis pub/sub failure is silent from the client's perspective — always check Redis connectivity as part of any hub disconnect investigation
