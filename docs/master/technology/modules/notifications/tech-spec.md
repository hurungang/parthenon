# Module: notifications — Tech Spec

## Overview

The Notification module provides a multi-channel outbound notification system. Administrators configure notification channels (SMTP email, Email API providers, Webhooks, Instant Messengers) and recipient groups; agents and SOPs trigger notifications by calling `system____send_notification` with a group slug and message body. The platform resolves all channels assigned to the group, dispatches in parallel, and records a `NotificationLog` entry per channel attempt. Partial failures do not block remaining channels.

All sensitive channel properties (API keys, SMTP passwords, webhook signing secrets) are encrypted at rest using the existing credential vault (AES-256) and decrypted only at dispatch time.

---

## Key Components

### Backend — Data Layer

| Component | Description |
|-----------|-------------|
| `NotificationChannel` | ORM model for a configured outbound destination. `channel_type` enum: `SMTP`, `EMAIL_API`, `WEBHOOK`, `MESSENGER`. |
| `ChannelProperty` | Key-value configuration per channel. `is_secret=True` properties are AES-256 encrypted; never returned in API responses. |
| `RecipientGroup` | Named addressable audience with a unique `slug`. Agents reference groups by slug. |
| `GroupChannelMapping` | Many-to-many association between recipient groups and channels. |
| `NotificationLog` | Immutable delivery record per channel attempt. Tracks `source_type` (`SOP`, `AGENT`, `MANUAL`), status (`PENDING`, `DELIVERED`, `FAILED`), and error detail. |
| `NotificationRepository` | Async database operations for all notification entities. Never performs encryption. |

**Source**: `backend/app/db/models/notifications.py`

### Backend — Service Layer

| Component | Description |
|-----------|-------------|
| `BaseChannelProvider` | Abstract base class defining the `send(recipients, subject, body, properties)` async interface and `ChannelDeliveryResult` dataclass. All providers implement this interface. |
| `SMTPChannelProvider` | Sends via Python `smtplib` (wrapped in `asyncio.to_thread`). Reads `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `from_address`, `use_tls` from decrypted channel properties. |
| `EmailAPIChannelProvider` | Sends via `httpx.AsyncClient`. Reads `api_url`, `api_key`, `from_address`, `provider_name`. Supports SendGrid and Mailgun payload formats selected by `provider_name`. |
| `WebhookChannelProvider` | HTTP POST via `httpx.AsyncClient`. Reads `webhook_url`, `secret` (optional), `http_method`, `content_type`. Signs with HMAC-SHA256 when a secret is configured. |
| `MessengerChannelProvider` | HTTP POST via `httpx.AsyncClient`. Reads `platform` (`teams` or `slack`), `webhook_url`. Formats Teams adaptive card or Slack Block Kit payload based on `platform`. |
| `DeliveryTracker` | Records `NotificationLog` entries via `NotificationRepository`. Emits `notifications.sent.total` counter and `notification_delivery_duration_seconds` histogram to OpenTelemetry, labelled by `channel_type` and `status`. |
| `NotificationService` | Top-level orchestrator. Resolves recipient group by slug, loads channel configs, decrypts secrets via `CredentialVault`, selects the appropriate provider, coordinates dispatch, records results. Continues to remaining channels on partial failure. Exposes `test_channel()` for admin test-send. |

**Source**: `backend/app/services/notifications/`

### Backend — MCP Tool Registration

| Component | Description |
|-----------|-------------|
| `send_notification` tool | Registered in Communication Hub as `system____send_notification`. Input schema: `group_slug` (string), `body` (string), optional `subject` (string). Validates caller RBAC, calls `NotificationService.send_to_group` with `source_type=AGENT`. Returns delivery summary (channels attempted, delivered, failed). |
| `get_recipient_group` tool | Registered as `system____get_recipient_group`. Input schema: `group_slug` (string). Returns group display name, description, and assigned channel types. Allows agents to discover available groups. |

**Source**: `backend/app/services/notifications/mcp_tools.py`

### Backend — API Layer

| Component | Description |
|-----------|-------------|
| `NotificationRouter` | FastAPI router at `/api/v1/notifications`. Endpoints for channel CRUD, channel test-send, recipient group CRUD, manual send, and delivery log query. All handlers require `RT_NOTIFICATION` permission. |

**Source**: `backend/app/api/v1/notifications.py`

### Frontend — Service & Hooks

| Component | Description |
|-----------|-------------|
| `notificationService.ts` | Typed async functions for all notification REST endpoints. Single source of truth for API calls in notification pages. |
| `useNotificationChannels` | React Query hook. Exposes `channels: NotificationChannelRead[]`, `isLoading`, `error`, `refetch`. |
| `useRecipientGroups` | React Query hook. Exposes `groups: RecipientGroupRead[]`, `isLoading`, `error`, `refetch`. |

**Sources**: `frontend/src/services/notificationService.ts`, `frontend/src/hooks/useNotificationChannels.ts`, `frontend/src/hooks/useRecipientGroups.ts`

### Frontend — Pages

| Component | Description |
|-----------|-------------|
| `ChannelListPage` | Admin page for listing, creating, editing, and deleting notification channels. Opens `ChannelFormDialog` for create/edit. |
| `ChannelFormDialog` | MUI Dialog for channel create/edit. Renders dynamic property fields based on `channel_type` selection. Includes Test Send in edit mode. |
| `RecipientGroupListPage` | Admin page for listing, creating, editing, and deleting recipient groups. Shows channel count per group. Includes an info banner reminding SOP authors to use the group **slug** (not display name) when referencing `send_notification` or `get_recipient_group` tools. |
| `RecipientGroupFormDialog` | MUI Dialog for recipient group create/edit. Auto-populates slug from name. Includes inline channel assignment management. |
| `NotificationLogPage` | Paginated admin page for browsing `NotificationLog` entries. Filterable by status, date range, and group. Row click shows delivery detail in a drawer. |

**Sources**: `frontend/src/pages/notifications/`

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/notifications/channels` | List all configured notification channels |
| `POST` | `/api/v1/notifications/channels` | Create a notification channel |
| `PUT` | `/api/v1/notifications/channels/{channel_id}` | Update a channel configuration |
| `DELETE` | `/api/v1/notifications/channels/{channel_id}` | Delete a channel |
| `POST` | `/api/v1/notifications/channels/{channel_id}/test` | Send a test notification via the channel |
| `GET` | `/api/v1/notifications/groups` | List all recipient groups |
| `POST` | `/api/v1/notifications/groups` | Create a recipient group |
| `PUT` | `/api/v1/notifications/groups/{group_id}` | Update a recipient group |
| `DELETE` | `/api/v1/notifications/groups/{group_id}` | Delete a recipient group |
| `POST` | `/api/v1/notifications/send` | Manual send to a recipient group |
| `GET` | `/api/v1/notifications/log` | Query delivery log (paginated, filterable) |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `NotificationChannel` | model | ORM model: channel type, active state, created/updated timestamps | `backend/app/db/models/notifications.py` |
| `ChannelProperty` | model | Key-value config per channel; secret properties AES-256 encrypted | `backend/app/db/models/notifications.py` |
| `RecipientGroup` | model | Named audience with unique slug | `backend/app/db/models/notifications.py` |
| `GroupChannelMapping` | model | Many-to-many: group ↔ channel | `backend/app/db/models/notifications.py` |
| `NotificationLog` | model | Immutable delivery record per channel attempt | `backend/app/db/models/notifications.py` |
| `NotificationRepository` | class | All async DB operations for notification domain | `backend/app/services/notifications/repository.py` |
| `BaseChannelProvider` | class | Abstract provider interface; `ChannelDeliveryResult` dataclass | `backend/app/services/notifications/providers/base.py` |
| `SMTPChannelProvider` | class | SMTP delivery via smtplib + asyncio.to_thread | `backend/app/services/notifications/providers/smtp.py` |
| `EmailAPIChannelProvider` | class | HTTP-based email API (SendGrid / Mailgun); payload format selected by `provider_name` | `backend/app/services/notifications/providers/email_api.py` |
| `WebhookChannelProvider` | class | HTTP POST; HMAC-SHA256 signing when `secret` configured | `backend/app/services/notifications/providers/webhook.py` |
| `MessengerChannelProvider` | class | Teams adaptive card or Slack Block Kit; format selected by `platform` | `backend/app/services/notifications/providers/messenger.py` |
| `DeliveryTracker` | class | Records `NotificationLog` and emits OTEL counter + histogram | `backend/app/services/notifications/delivery_tracker.py` |
| `NotificationService` | class | Orchestrator: resolve group → load channels → decrypt → dispatch → record | `backend/app/services/notifications/service.py` |
| `NotificationRouter` | router | FastAPI router at `/api/v1/notifications`; all endpoints require `RT_NOTIFICATION` | `backend/app/api/v1/notifications.py` |
| `notificationService` | module | Frontend typed API client for all notification endpoints | `frontend/src/services/notificationService.ts` |
| `useNotificationChannels` | hook | React Query hook for channel list | `frontend/src/hooks/useNotificationChannels.ts` |
| `useRecipientGroups` | hook | React Query hook for recipient group list | `frontend/src/hooks/useRecipientGroups.ts` |
| `ChannelListPage` | component | Admin channel list with create/edit/delete | `frontend/src/pages/notifications/ChannelListPage.tsx` |
| `ChannelFormDialog` | component | Channel create/edit dialog with dynamic property fields and test-send | `frontend/src/pages/notifications/ChannelFormDialog.tsx` |
| `RecipientGroupListPage` | component | Admin recipient group list; slug usage reminder banner | `frontend/src/pages/notifications/RecipientGroupListPage.tsx` |
| `RecipientGroupFormDialog` | component | Recipient group create/edit with channel assignment | `frontend/src/pages/notifications/RecipientGroupFormDialog.tsx` |
| `NotificationLogPage` | component | Paginated delivery log with filter and detail drawer | `frontend/src/pages/notifications/NotificationLogPage.tsx` |

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `NotificationDispatcher` | Service class that dispatches notifications to the appropriate channel implementation (SMTP, Slack, Teams, or generic webhook) based on the channel type; registers each active channel as an invocable MCP tool on the platform |
| `NotificationRouter` | FastAPI router providing full CRUD operations on notification channel configuration, a test-send endpoint to verify a channel is working, and an event history listing endpoint |
| `NotificationChannel` | SQLAlchemy model for a configured outbound notification destination; stores channel type, connection parameters (encrypted where sensitive), and enabled state |
| `NotificationEvent` | SQLAlchemy model recording a single dispatched notification; stores the target channel, payload summary, delivery status, and timestamp |

### Frontend

| Component | Description |
|-----------|-------------|
| `NotificationConfigPage` | Channel list with add and edit forms per channel type (email, Slack, Teams, webhook), test-send action per channel, and notification event history table |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/notifications/channels` | List all configured notification channels |
| `POST` | `/api/v1/notifications/channels` | Create a notification channel |
| `PUT` | `/api/v1/notifications/channels/{channel_id}` | Update a channel configuration |
| `DELETE` | `/api/v1/notifications/channels/{channel_id}` | Delete a channel |
| `POST` | `/api/v1/notifications/channels/{channel_id}/test` | Send a test notification via the channel |
| `GET` | `/api/v1/notifications/events` | List notification dispatch events |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `NotificationDispatcher` | class | Dispatches notifications to configured channels; registers each channel as an MCP tool | `backend/app/services/notifications/dispatcher.py` |
| `NotificationRouter` | router | CRUD, test-send, and event history endpoints for notification channels; all operations guarded by `require_permission(RT_NOTIFICATION, action)` | `backend/app/api/v1/notifications.py` |
| `NotificationChannel` | model | SQLAlchemy model for a configured outbound notification destination (type, config, enabled state) | `backend/app/db/models/notifications.py` |
| `NotificationEvent` | model | SQLAlchemy model recording a dispatched notification with channel, payload summary, and status | `backend/app/db/models/notifications.py` |
| `NotificationConfigPage` | component | Channel list, add/edit form per channel type, test-send, and event history table | `frontend/src/pages/notifications/NotificationConfigPage.tsx` |
