# Runbook: Agent Instance Limit Reached

## Symptoms

- New inbound agent interaction requests are being rejected with an HTTP 429 or a capacity error response
- Logs from `agent-engine` contain `max_instances reached for agent_type_id=<id>`
- Active users or consumers report that they cannot start a new conversation with a specific agent type
- Other agent types are functioning normally (the issue is scoped to a specific type)

---

## Resolution Steps

1. Check the platform admin UI under Agent Types and locate the affected agent type. Inspect the `max_instances` setting. Confirm whether the configured limit is intentionally low (e.g., a restricted agent type) or whether it was set without accounting for current demand.

2. Review the active instance count for the affected agent type in the Agent Engine dashboard. Compare the count against `max_instances`. If the count is at or near the limit, determine whether the instances are legitimately active (users are waiting for responses) or whether they are stuck (no activity for an extended period).

3. Inspect Communication Hub and Agent Gateway logs for the active instance IDs. Look for instances that have no recent message activity and for which no `close` lifecycle event was received. A dropped network connection between the client and the Agent Gateway can prevent the close event from reaching the engine, leaving the instance counted as active indefinitely.

4. For any instance confirmed to be orphaned (no active session, no recent activity, and no close event in logs), force-close the instance via the admin API (`DELETE /api/v1/agents/instances/{instance_id}`). This releases the slot and allows new instances to be created.

5. If the current limit is consistently being reached under legitimate load and the infrastructure has capacity to support more concurrent instances, increase the `max_instances` value for the affected agent type via the admin UI.

---

## Notes

- Increasing `max_instances` increases memory and LLM API cost proportionally — confirm the infrastructure and budget can support the higher limit before changing it
- If orphaned instances are recurring, investigate whether the client-side reconnect logic is generating duplicate sessions without properly closing previous ones
- The platform-wide default cap is set via `AGENT_ENGINE_DEFAULT_MAX_INSTANCES` but can be overridden per agent type
