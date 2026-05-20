# Notification System — Deployment Guide

## 1. Environment Variables

All notification environment variables are optional. Defaults are suitable for development. Production deployments should explicitly set every variable used by active channel types.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NOTIFICATION_SMTP_HOST` | No | `localhost` | SMTP relay server hostname for the SMTP channel provider |
| `NOTIFICATION_SMTP_PORT` | No | `587` | SMTP relay server port (587 = STARTTLS, 465 = SMTPS) |
| `NOTIFICATION_EMAIL_API_KEY` | No | — | Default API key for email API providers (SendGrid, Mailgun); used when no per-channel credential is configured |
| `NOTIFICATION_WEBHOOK_SECRET` | No | — | Default HMAC-SHA256 signing secret for webhook channels without a per-channel secret |
| `NOTIFICATION_RETRY_MAX_ATTEMPTS` | No | `3` | Maximum delivery attempts per channel before recording a FAILED status |
| `NOTIFICATION_RETRY_DELAY_SECONDS` | No | `60` | Wait time in seconds between retry attempts |

> **Note:** Per-channel credentials (SMTP passwords, API keys, webhook secrets) are configured via the admin UI and stored encrypted in the database using AES-256. The environment variables above are fallback defaults only. Per-channel values always take precedence.

---

## 2. Infrastructure Changes

### No New Services Required

The Notification Service runs as part of the existing backend process. No additional containers or pods are needed for this feature.

### No New Ports Required

All notification API endpoints are served on the existing backend port under `/api/v1/notifications`. No firewall or ingress rule changes are needed for the backend itself.

### External Service Connectivity (Optional)

Depending on which channel types are configured, the backend container/pod may need outbound connectivity to:

| Channel Type | Connectivity Needed |
|---|---|
| SMTP | Outbound TCP to the SMTP relay on the configured port (default 587) |
| Email API | Outbound HTTPS to the email API provider (e.g., `api.sendgrid.com`, `api.mailgun.net`) |
| Webhook | Outbound HTTPS to the webhook endpoint URL configured per channel |
| Messenger (Teams/Slack) | Outbound HTTPS to `outlook.office.com` (Teams) or `hooks.slack.com` (Slack) |

Network policies and security groups must allow these outbound connections before channels can be activated.

### Docker Compose (Dev / Self-Hosted)

No changes to `docker-compose.yml` are required. Add the new environment variables to the `backend` service's `environment` section if non-default values are needed.

### Kubernetes / Helm (Production)

Add the new environment variables to the backend `Deployment` manifest or Helm values file. Secret values (`NOTIFICATION_EMAIL_API_KEY`, `NOTIFICATION_WEBHOOK_SECRET`) should be stored in Kubernetes Secrets and mounted as environment variables — not embedded in plaintext values files.

---

## 3. Migration Steps

Follow these steps in order for a zero-downtime deployment.

**Step 1 — Update environment variables**

Add or update the notification environment variables in the deployment config (Docker Compose environment section or Kubernetes Secret/ConfigMap) before deploying the new backend image.

**Step 2 — Deploy the new backend container or pod**

Deploy the updated backend image. The Notification Service initialises lazily — it will not attempt channel dispatch until the first notification is triggered.

**Step 3 — Run database migrations**

Connect to the backend container or pod and run:

```
alembic upgrade head
```

This applies the notification schema migration, which creates the `notification_channel`, `channel_property`, `recipient_group`, `group_channel_mapping`, and `notification_log` tables.

**Step 4 — Verify the migration**

Run the following and confirm the output includes the notification migration revision ID:

```
alembic current
```

The output should show the latest revision. Cross-reference with the migration file name in `backend/alembic/versions/` to confirm.

**Step 5 — Configure notification channels via admin UI**

After deployment, navigate to the Notification admin pages in the management UI:

- **Channels**: Create at least one channel (SMTP, Email API, Webhook, or Messenger) and enter the channel-specific credentials.
- **Recipient Groups**: Create one or more recipient groups and assign channels to them.

This is a post-deployment, operator-performed step. The system is fully functional for all non-notification features before this step.

**Step 6 — Test notification delivery**

For each newly configured channel, use the **Test Send** button in the Channel management UI. Verify the test message arrives at the configured destination. Check the **Notification Log** admin page for the delivery record and status.

### Rollback Safety — NotificationEvent Entity

The legacy `NotificationEvent` entity is preserved in the database schema during the transition. It is not removed by the migration. This means rolling back to the previous backend version will not result in schema conflicts. `NotificationEvent` is marked for retirement only after the new `NotificationLog` table is confirmed operational.

---

## 4. Rollback Procedure

If a deployment failure requires rollback:

**Step 1 — Roll back the backend to the previous image**

Redeploy the previous backend container image (Docker Compose or Kubernetes rollout undo). The previous version does not reference the new notification tables, so the running application will be unaffected by their presence.

**Step 2 — Downgrade the database migration**

If any data integrity issues are observed, downgrade one revision:

```
alembic downgrade -1
```

To downgrade to a specific known-good revision:

```
alembic downgrade <revision_id>
```

This drops the notification tables added by the migration. Existing data in those tables will be lost.

**Step 3 — Verify rollback**

After rollback, confirm:
- Backend health endpoint responds: `GET /api/v1/health`
- Existing features (agents, SOPs, scheduling) function normally
- `alembic current` shows the previous revision

**Step 4 — Delivery log note**

Any notifications dispatched between the start of the new deployment and rollback will have delivery logs in the `notification_log` table up until the point the table is dropped (if downgrade is performed). These records are not recoverable after downgrade. If audit preservation is required, export the `notification_log` table before running `alembic downgrade`.

---

## 5. Master Deployment Update Instructions

The following updates are required in `docs/master/deployment/`:

- **Environment variable reference**: Add the six notification environment variables from Section 1 to the environment variable reference table. Include the same required/default/description columns.
- **Deployment checklist**: Add the notification migration step (`alembic upgrade head` after backend deploy) to the standard deployment checklist. It should appear after the "deploy backend" step.
- **Rollback procedures**: Add a notification-specific rollback note: if the notification migration was applied, include `alembic downgrade -1` in the rollback procedure and note that notification log data will be lost.
- **External connectivity**: Add the notification channel outbound connectivity requirements to the network/firewall configuration section.
