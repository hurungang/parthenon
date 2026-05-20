# Notification System — Operations Guide

## 1. Monitoring

### Metrics

The following OpenTelemetry metrics are emitted by the `DeliveryTracker` component and collected by the OTEL Collector. All metrics are available in the existing metrics pipeline (Prometheus, etc.).

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `notification_sent_total` | Counter | `channel_type`, `status` | Total notification dispatch attempts, partitioned by channel type and final delivery status (`DELIVERED`, `FAILED`) |
| `notification_delivery_duration_seconds` | Histogram | `channel_type` | End-to-end dispatch time per channel in seconds, from provider call start to result received |
| `notification_retry_total` | Counter | `channel_type`, `retry_attempt` | Count of retry attempts per channel type; `retry_attempt` label is the attempt number (1, 2, 3) |
| `notification_channel_health` | Gauge | `channel_id`, `channel_type` | Health status of each configured channel: `1` = last test or delivery succeeded, `0` = last attempt failed |

**Label values for `channel_type`**: `smtp`, `email_api`, `webhook`, `messenger`

**Label values for `status`**: `DELIVERED`, `FAILED`

### Alerts

Configure the following alerts in the monitoring stack:

| Alert | Condition | Severity | Action |
|---|---|---|---|
| High notification failure rate | `notification_sent_total{status="FAILED"}` rate > 20% of total over 5 minutes | Warning | Investigate channel health; check Notification Log for error details |
| Email delivery latency | 95th percentile of `notification_delivery_duration_seconds{channel_type="smtp"}` or `email_api` > 30 seconds | Warning | Check SMTP relay/email API provider status; review timeout settings |
| Webhook delivery latency | 95th percentile of `notification_delivery_duration_seconds{channel_type="webhook"}` > 5 seconds | Warning | Check target webhook endpoint health; consider increasing timeout or disabling channel |
| Channel health failure | `notification_channel_health` gauge = 0 for any channel for > 10 minutes | Critical | Channel is unreachable or misconfigured; verify credentials and endpoint availability |
| Sustained retry storm | `notification_retry_total` rate > 50 per minute across all channels | Warning | Possible provider outage; review retry configuration and consider temporary disable |

### Dashboards

Recommended dashboard panels in the existing observability UI:

**Notification Delivery Overview**
- Notification send rate (total per minute, stacked by `status`)
- Success rate percentage (rolling 5-minute window)
- Delivery latency percentiles (p50, p95, p99) per `channel_type`
- Retry rate over time

**Per-Channel Health and Performance**
- `notification_channel_health` gauge per channel (table view)
- Failure rate per channel over time
- Average delivery duration per channel
- Retry attempt distribution per channel

**Recipient Group Activity**
- Top recipient groups by notification volume (last 24 hours)
- Notification source breakdown (SOP vs Agent vs Manual)
- Failed delivery count per group

---

## 2. Logging

All notification events are emitted as OpenTelemetry structured log events and collected by the OTEL Collector alongside other platform logs.

### Log Events and Fields

**Notification Requested**
Emitted when a notification request is received (from MCP tool call, REST API, or internal trigger).

| Field | Value |
|---|---|
| `notification_id` | UUID of the `NotificationLog` record |
| `recipient_group_slug` | Slug of the target recipient group |
| `source_type` | `SOP`, `AGENT`, or `MANUAL` |
| `source_id` | UUID of the originating SOP or agent session (if applicable) |
| `message_summary` | First 120 characters of the notification body |
| `log_level` | `INFO` |

**Channel Dispatch Started**
Emitted once per channel for each notification.

| Field | Value |
|---|---|
| `notification_id` | Correlates to the parent notification request |
| `channel_id` | UUID of the channel |
| `channel_type` | `smtp`, `email_api`, `webhook`, `messenger` |
| `retry_attempt` | Attempt number (1 on first try) |
| `log_level` | `INFO` |

**Channel Dispatch Result**
Emitted after each delivery attempt.

| Field | Value |
|---|---|
| `notification_id` | Correlates to the parent notification request |
| `channel_id` | UUID of the channel |
| `channel_type` | `smtp`, `email_api`, `webhook`, `messenger` |
| `delivery_status` | `DELIVERED` or `FAILED` |
| `duration_ms` | Dispatch time in milliseconds |
| `error_message` | Error detail (only present on failure) |
| `retry_attempt` | Attempt number |
| `log_level` | `INFO` on success; `WARNING` on retryable failure; `ERROR` on final failure |

### Log Levels

| Condition | Level |
|---|---|
| Notification dispatched successfully | `INFO` |
| Delivery failed but retries remain | `WARNING` |
| All retry attempts exhausted; final failure recorded | `ERROR` |
| Channel credential decryption error | `ERROR` |
| Recipient group not found or has no active channels | `WARNING` |

### Finding Logs

All notification log events include the `notification_id` field. To trace a complete notification lifecycle:

1. Open the **Notification Log** admin page and locate the `notification_id` for the event in question.
2. Search the log aggregator (Loki, Elasticsearch, etc.) for `notification_id="<uuid>"` to retrieve all events for that notification, including per-channel dispatch and result records.

---

## 3. Common Issues

### Issue 1 — SMTP Authentication Failure

**Symptom**: Notifications via SMTP channels show `FAILED` status with an authentication error in the `NotificationLog` error field.

**Cause**: The SMTP username or password stored in the channel configuration is incorrect, expired, or the SMTP server requires a different authentication mechanism (e.g., OAuth instead of password).

**Resolution**:
1. Open the Channel management admin page and locate the affected SMTP channel.
2. Click **Edit** and re-enter the SMTP credentials.
3. Use the **Test Send** button to verify the channel before saving.
4. If the SMTP provider requires app-specific passwords or OAuth tokens, generate a new credential in the provider's admin console.

---

### Issue 2 — Webhook Timeout

**Symptom**: Webhook notifications consistently show `FAILED` with a timeout error. Delivery duration in `notification_delivery_duration_seconds` is near or at the channel's timeout limit.

**Cause**: The webhook endpoint is slow to respond or unreachable. The default timeout for webhook channels is 10 seconds.

**Resolution**:
1. Verify the webhook endpoint is reachable from the backend host: test via a manual HTTP POST to the endpoint URL from the server.
2. Check the target system's health and response times.
3. If the endpoint is legitimately slow, consider increasing the timeout value in the channel configuration.
4. If the endpoint is permanently unavailable, disable the channel via the admin UI to prevent continued failures and retries from degrading system performance.

---

### Issue 3 — Email API Rate Limit Exceeded

**Symptom**: Email API channel shows `FAILED` with a 429 HTTP status in the error message. Notifications succeed sporadically but fail when volume is high.

**Cause**: The email API provider (SendGrid, Mailgun, etc.) has rate-limited the account due to too many requests in a short period.

**Resolution**:
1. Check the email API provider's dashboard for rate limit usage and quota.
2. Review the notification volume in the Notification Overview dashboard — identify which SOPs or agents are sending at high frequency.
3. Reduce notification frequency at the SOP level (space out triggers) or split high-volume groups across multiple channels.
4. Upgrade the email API plan for higher rate limits if sustained volume is expected.
5. Enable retries (`NOTIFICATION_RETRY_MAX_ATTEMPTS`) so that rate-limited messages are automatically retried after `NOTIFICATION_RETRY_DELAY_SECONDS`.

---

### Issue 4 — Recipient Group Has No Active Channels

**Symptom**: A notification request completes with no delivery logs (no `NotificationLog` records for channels), or the response indicates 0 channels dispatched.

**Cause**: All channels assigned to the target recipient group have been disabled, deleted, or the group has no channel assignments at all.

**Resolution**:
1. Open the Recipient Group management page and locate the group.
2. Verify at least one channel is assigned and that the channel's **Active** status is enabled.
3. If no channels are assigned, add one via the inline channel assignment panel in the group editor.
4. If the assigned channel was recently deleted, create a replacement channel and assign it to the group.

---

### Issue 5 — Messenger Webhook Misconfigured (Teams/Slack)

**Symptom**: Messenger channel shows `FAILED`. Error message references HTTP 400 or 403 from the messaging platform.

**Cause**: The incoming webhook URL is expired, rotated, or the bot/app integration has been removed from the Teams channel or Slack workspace.

**Resolution**:
1. In the Teams admin center or Slack workspace settings, verify the incoming webhook connector is still active.
2. Regenerate the webhook URL if expired or revoked.
3. Update the channel configuration in the Notification admin UI with the new webhook URL.
4. Use **Test Send** to confirm delivery before re-enabling the channel.

---

### Issue 6 — Notification Log Missing for Agent-Triggered Send

**Symptom**: An agent reported success for a `send_notification` MCP tool call, but no corresponding `NotificationLog` entry exists.

**Cause**: The MCP tool call may have completed before the `NotificationLog` record was committed, or there was a database write failure during the dispatch cycle.

**Resolution**:
1. Search backend logs for `notification_id` or `source_id` matching the agent session.
2. If the log record was not written, check backend error logs for database connection errors or transaction rollback events.
3. If the OTEL structured log shows the dispatch was attempted, the log entry may have been lost due to a crash during the write — this is recoverable only from OTEL event records.
4. Verify the backend database connection pool is healthy and the PostgreSQL instance is not under write pressure.

---

### Issue 7 — Channel Credential Decryption Failure

**Symptom**: Channel dispatch fails immediately with a credential decryption error, before any network call is made to the provider.

**Cause**: The `CredentialVault` (AES-256) encryption key (`ENCRYPTION_MASTER_KEY`) has changed since the channel credentials were stored, making the stored ciphertext unreadable.

**Resolution**:
1. Do not change `ENCRYPTION_MASTER_KEY` on a running system with stored credentials — this is a destructive operation for all encrypted channel properties.
2. If the key was rotated without re-encrypting stored values, the affected channels must be reconfigured: open each channel in the admin UI and re-enter all secret properties.
3. Going forward, follow the key rotation procedure documented in the master operations guide before changing `ENCRYPTION_MASTER_KEY`.

---

### Issue 8 — High Retry Volume Degrading Backend Performance

**Symptom**: `notification_retry_total` metric is elevated. Backend response times increase, or other features show latency spikes.

**Cause**: One or more channels are in a persistent failed state and the retry mechanism is generating a high volume of outbound requests and database writes.

**Resolution**:
1. Identify which channels are failing repeatedly via the Per-Channel Health dashboard.
2. Disable the failing channels via the admin UI to halt retries immediately.
3. Investigate the root cause for each channel (authentication, endpoint health, rate limits).
4. Reduce `NOTIFICATION_RETRY_MAX_ATTEMPTS` or increase `NOTIFICATION_RETRY_DELAY_SECONDS` in the backend environment to limit retry throughput during incidents.
5. Re-enable channels after the root cause is resolved and a **Test Send** confirms delivery.

---

## 4. Master Operations Update Instructions

The following updates are required in `docs/master/operations/`:

- **Metrics reference**: Add the four notification metrics (`notification_sent_total`, `notification_delivery_duration_seconds`, `notification_retry_total`, `notification_channel_health`) with their label definitions to the platform metrics reference table.
- **Alerting runbook**: Add the five notification alerts from Section 1 to the alerting runbook. Include threshold values, severity levels, and initial response steps for each alert.
- **Troubleshooting guide**: Create a `notifications-troubleshooting.md` page in the operations docs using the eight common issues from Section 3 as the basis. Operators should be able to find it under the "Notifications" category.
- **Incident response**: Update the incident response procedures to include notification failures as a distinct failure category. Add: "If notification delivery failures are observed during an incident, disable affected channels via the admin UI to prevent retry storms. Restore channels after the incident is resolved."
- **Log correlation guide**: Add a note that all notification log events share the `notification_id` field for cross-event correlation, and document the log search pattern (search by `notification_id` in the log aggregator).
