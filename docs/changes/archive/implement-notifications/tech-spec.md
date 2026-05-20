# Tech Spec — Notification System

## 1. Technical Overview

The notification system extends the existing `NotificationChannel` + `NotificationEvent` data layer with a fully typed service architecture composed of channel providers, a central `NotificationService`, and a `DeliveryTracker`. The backend exposes REST endpoints for admin CRUD on channels and recipient groups, plus a `send_notification` MCP tool registered in the Communication Hub so agents can trigger notifications by group slug. The frontend adds three admin pages (channel management, recipient group management, delivery log) backed by a typed service client and two hooks.

All sensitive channel properties (SMTP passwords, API keys, webhook secrets) are encrypted at rest using the existing `CredentialVault` (AES-256) and decrypted only at dispatch time. Every dispatch operation is wrapped in an OpenTelemetry span and delivery outcomes are recorded as structured log events and metrics. The `NotificationEvent` entity is superseded by `NotificationLog`, which adds recipient group attribution, source tracking, and richer delivery metadata.

---

## 2. Component Breakdown

### Backend — Data Layer

**`notifications.py` (model file)**
Defines all notification ORM entities: `NotificationChannel`, `ChannelProperty`, `RecipientGroup`, `GroupChannelMapping`, `NotificationLog`, and the `ChannelType`, `DeliveryStatus`, `SourceType` Python enums. The existing `NotificationEvent` entity is preserved during transition and marked for retirement once data migration is confirmed.

**`NotificationRepository`**
Encapsulates all async database operations for the notification domain. Accepts an `AsyncSession` and returns typed ORM instances. Never performs encryption — that responsibility belongs to the service layer.

### Backend — Service Layer

**`BaseChannelProvider`**
Abstract base class defining the `send(recipients, subject, body, properties)` async interface and the `ChannelDeliveryResult` typed dataclass. All concrete providers implement this interface.

**`SMTPChannelProvider`**
Implements `BaseChannelProvider` using Python `smtplib` wrapped in `asyncio.to_thread`. Reads `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `from_address`, `use_tls` from decrypted channel properties.

**`EmailAPIChannelProvider`**
Implements `BaseChannelProvider` using `httpx.AsyncClient`. Reads `api_url`, `api_key`, `from_address`, `provider_name` from channel properties. Supports SendGrid and Mailgun payload formats.

**`WebhookChannelProvider`**
Implements `BaseChannelProvider` using `httpx.AsyncClient`. Reads `webhook_url`, `secret` (optional), `http_method`, `content_type`. Signs requests with HMAC-SHA256 when a secret is configured.

**`MessengerChannelProvider`**
Implements `BaseChannelProvider` using `httpx.AsyncClient`. Reads `platform` (`teams` or `slack`), `webhook_url`, `channel_name`. Formats Teams adaptive card or Slack Block Kit payloads depending on `platform`.

**`DeliveryTracker`**
Records delivery outcomes to `NotificationLog` via `NotificationRepository` and emits OpenTelemetry structured log events + `notifications.sent.total` counter labelled by `channel_type` and `status`.

**`NotificationService`**
Top-level orchestrator. Resolves recipient groups by slug, loads channel configurations, decrypts secrets via `CredentialVault`, selects the appropriate provider, creates `NotificationLog` records, and coordinates dispatch. Continues to remaining channels on partial failure. Provides a `test_channel` method for admin test sends.

**`mcp_tool.py` (send_notification)**
Defines the `send_notification` MCP tool descriptor (input schema) and its async handler. Validates caller RBAC, calls `NotificationService.send_to_group` with `source_type=AGENT`, and returns a delivery summary to the MCP caller.

### Backend — API Layer

**`notifications.py` (router file)**
FastAPI router mounted at `/api/v1/notifications`. Handles all channel and recipient group CRUD, channel test, and manual send. Delegates to `NotificationService` and `NotificationRepository`. All handlers require JWT authentication and `RT_NOTIFICATION` permission.

### Frontend — Service Layer

**`notificationService.ts`**
Typed async functions for all notification REST endpoints. Imports TypeScript interfaces matching Pydantic response schemas. Attaches the JWT bearer token from the auth context. Single source of truth for all API calls in notification pages.

### Frontend — Hooks

**`useNotificationChannels`**
Fetches and caches channel list. Exposes `channels: NotificationChannelRead[]`, `isLoading`, `error`, `refetch`.

**`useRecipientGroups`**
Fetches and caches recipient group list. Exposes `groups: RecipientGroupRead[]`, `isLoading`, `error`, `refetch`.

### Frontend — Pages

**`ChannelListPage`**
Admin page for listing, creating, editing, and deleting notification channels. Uses `useNotificationChannels` for data. Opens `ChannelFormDialog` for create/edit.

**`ChannelFormDialog`**
MUI Dialog for channel create/edit. Renders dynamic property fields based on `channel_type` selection. Includes Test Send functionality in edit mode. Implements the Dialog Error Handling Standard.

**`RecipientGroupListPage`**
Admin page for listing, creating, editing, and deleting recipient groups. Uses `useRecipientGroups`. Shows channel count per group. Opens `RecipientGroupFormDialog`.

**`RecipientGroupFormDialog`**
MUI Dialog for recipient group create/edit. Auto-populates slug from name. Includes inline channel assignment management.

**`NotificationLogPage`**
Paginated admin page for browsing `NotificationLog` entries. Supports filtering by status, date range, and group. Row click shows delivery detail in a drawer.

---

## 3. API Changes

All endpoints are under `/api/v1/notifications`. All require a valid JWT bearer token. All management operations (`POST`, `PUT`, `DELETE`) require `manage` permission on `RT_NOTIFICATION`.

### Notification Channels

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications/channels` | List all notification channels with their property keys (not secret values). |
| `POST` | `/notifications/channels` | Create a channel. Request includes name, type, description, and a properties map (key → value). Secret values are encrypted before storage. |
| `GET` | `/notifications/channels/{id}` | Retrieve a single channel with its non-secret property keys. |
| `PUT` | `/notifications/channels/{id}` | Update channel name, description, active status, or properties. Secret values re-encrypted on update. |
| `DELETE` | `/notifications/channels/{id}` | Delete a channel and all its `ChannelProperty` records. Returns 409 if the channel is assigned to one or more recipient groups. |
| `POST` | `/notifications/channels/{id}/test` | Send a test message through the channel. Request body includes `test_recipient`. Returns `success` flag and optional `error`. |

### Recipient Groups

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications/recipient-groups` | List all recipient groups including assigned channel IDs. |
| `POST` | `/notifications/recipient-groups` | Create a recipient group. Slug is auto-derived from name if not provided. |
| `GET` | `/notifications/recipient-groups/{id}` | Retrieve group details with full channel assignment list. |
| `PUT` | `/notifications/recipient-groups/{id}` | Update group name, slug, description, or active status. |
| `DELETE` | `/notifications/recipient-groups/{id}` | Delete group and all `GroupChannelMapping` records. |
| `POST` | `/notifications/recipient-groups/{id}/channels` | Assign a channel to the group. Request body: `{ "channel_id": "<uuid>" }`. Returns 409 if already assigned. |
| `DELETE` | `/notifications/recipient-groups/{id}/channels/{channel_id}` | Remove a channel assignment from the group. |

### Notification Send

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/notifications/send` | Manually trigger a notification to a recipient group. Request: `group_slug`, `subject` (optional), `body`, `source_type` (default `MANUAL`), `source_id` (optional UUID). Returns 202 with `notification_log_ids` list. |

### Delivery Logs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications/logs` | Paginated list of `NotificationLog` entries. Query params: `group_id`, `channel_id`, `status`, `from_date`, `to_date`, `limit`, `offset`. |
| `GET` | `/notifications/logs/{id}` | Retrieve a single log entry including `metadata` and `error` detail. |

### Modified Endpoints

The following existing endpoints are modified (not removed):

- `POST /notifications/channels` — no longer accepts `encrypted_config`; now accepts `properties` map.
- `PUT /notifications/channels/{id}` — same change as above.
- `GET /notifications/channels` — response no longer includes `encrypted_config`; includes `properties` list with secret values omitted.

---

## 4. State Management

The frontend uses React local state and custom hooks — no global state store is introduced for notifications. This follows the existing pattern across other admin pages.

**Channel and group data**: Fetched on page mount via `useNotificationChannels` / `useRecipientGroups`. After create, update, or delete operations the hook's `refetch` function is called to reload the list. This ensures the table always reflects server state.

**Dialog state**: Each dialog manages its own `open`, `selectedItem`, and `dialogError` state in the parent page component. The `dialogError` pattern (from `useDialogErrorHandler`) is applied to all dialogs that perform API calls, ensuring permission errors and network failures surface inside the dialog rather than silently failing.

**Form state**: MUI-controlled inputs with local `useState` in each dialog component. No form library is required given the moderate field count.

**Log pagination**: `NotificationLogPage` manages `page`, `pageSize`, `filters` in local `useState`. Filter changes reset `page` to 0 and trigger a new `notificationService.listLogs` call.

---

## 5. Data Access Patterns

### Backend to Database

All database access goes through `NotificationRepository` using SQLAlchemy 2 async sessions (`AsyncSession`). Sessions are injected via FastAPI dependency injection (`DbSession` type alias). No direct ORM access from route handlers — handlers call the service layer which calls the repository.

Channel property secrets are encrypted via `CredentialVault.encrypt(value)` in `NotificationService` before passing to the repository for storage. On read, `CredentialVault.decrypt(encrypted_value)` is called at dispatch time only, never at list/read time. API responses for channel properties omit the `encrypted_value` field entirely; only `key` and `is_secret` are returned.

### Frontend to Backend

All frontend data access goes through `notificationService.ts`. The service uses the authenticated `fetch` wrapper (matching the existing pattern in other services). JWT tokens are retrieved from the auth context and attached as `Authorization: Bearer <token>` headers. The service never holds state; it is a thin I/O layer.

### Why this pattern

- **No direct DB from frontend**: The project convention prohibits frontend direct database access; all reads/writes go through the backend REST API.
- **Repository pattern**: Centralises query logic, makes service unit tests straightforward with mock sessions, and prevents ad-hoc ORM queries scattered across handlers.
- **Encrypted at service layer**: Keeping encryption/decryption in `NotificationService` (not the repository or handler) ensures the vault is only touched in one place and is easy to audit.

---

## 6. Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `NotificationChannel` | model | Notification channel ORM entity | `backend/app/db/models/notifications.py` |
| `ChannelProperty` | model | Per-channel property (encrypted at rest) | `backend/app/db/models/notifications.py` |
| `RecipientGroup` | model | Named addressable audience entity | `backend/app/db/models/notifications.py` |
| `GroupChannelMapping` | model | Association between group and channel | `backend/app/db/models/notifications.py` |
| `NotificationLog` | model | Immutable delivery record (replaces NotificationEvent) | `backend/app/db/models/notifications.py` |
| `ChannelType` | enum | SMTP, EMAIL_API, WEBHOOK, MESSENGER | `backend/app/db/models/notifications.py` |
| `SourceType` | enum | SOP, AGENT, MANUAL | `backend/app/db/models/notifications.py` |
| `DeliveryStatus` | enum | PENDING, DELIVERED, FAILED | `backend/app/db/models/notifications.py` |
| `NotificationRepository` | class | Async DB access for all notification entities | `backend/app/services/notifications/repository.py` |
| `DeliveryTracker` | class | Records delivery outcomes to DB and OTEL | `backend/app/services/notifications/delivery_tracker.py` |
| `NotificationService` | class | Core orchestration: group resolution, dispatch, tracking | `backend/app/services/notifications/notification_service.py` |
| `BaseChannelProvider` | abstract class | Provider interface; defines `send` and `ChannelDeliveryResult` | `backend/app/services/notifications/providers/base.py` |
| `ChannelDeliveryResult` | dataclass | Typed result returned by all providers | `backend/app/services/notifications/providers/base.py` |
| `SMTPChannelProvider` | class | SMTP email dispatch via smtplib | `backend/app/services/notifications/providers/smtp.py` |
| `EmailAPIChannelProvider` | class | Email API dispatch via httpx (SendGrid/Mailgun) | `backend/app/services/notifications/providers/email_api.py` |
| `WebhookChannelProvider` | class | HTTP webhook dispatch with optional HMAC signing | `backend/app/services/notifications/providers/webhook.py` |
| `MessengerChannelProvider` | class | Teams/Slack webhook dispatch with typed payloads | `backend/app/services/notifications/providers/messenger.py` |
| `handle_send_notification` | function | MCP tool handler for send_notification | `backend/app/services/notifications/mcp_tool.py` |
| `NotificationChannelRead` | Pydantic schema | Channel read response (no secret values) | `backend/app/schemas/notifications.py` |
| `NotificationChannelCreate` | Pydantic schema | Channel create request with properties map | `backend/app/schemas/notifications.py` |
| `RecipientGroupRead` | Pydantic schema | Recipient group read response | `backend/app/schemas/notifications.py` |
| `RecipientGroupCreate` | Pydantic schema | Recipient group create request | `backend/app/schemas/notifications.py` |
| `NotificationLogRead` | Pydantic schema | Delivery log read response | `backend/app/schemas/notifications.py` |
| `SendNotificationRequest` | Pydantic schema | Manual send request body | `backend/app/schemas/notifications.py` |
| `TestChannelRequest` | Pydantic schema | Test send request body | `backend/app/schemas/notifications.py` |
| `TestChannelResponse` | Pydantic schema | Test send response (`success`, optional `error`) | `backend/app/schemas/notifications.py` |
| `ChannelPropertyRead` | Pydantic schema | Property key + is_secret (no encrypted_value) | `backend/app/schemas/notifications.py` |
| `ChannelPropertyWrite` | Pydantic schema | Property key + plaintext value submitted by client (service encrypts before storage) | `backend/app/schemas/notifications.py` |
| `NotificationChannelUpdate` | Pydantic schema | Channel update request (name, description, is_active, properties) | `backend/app/schemas/notifications.py` |
| `RecipientGroupUpdate` | Pydantic schema | Recipient group update request (name, slug, description, is_active) | `backend/app/schemas/notifications.py` |
| `GroupChannelMappingRead` | Pydantic schema | Group-to-channel assignment read (id, channel_id) | `backend/app/schemas/notifications.py` |
| `AssignChannelRequest` | Pydantic schema | Request body for assigning a channel to a recipient group | `backend/app/schemas/notifications.py` |
| `NotificationRouter` | FastAPI router | All notification REST endpoints | `backend/app/api/v1/notifications.py` |
| `notificationService` | service module | Typed frontend API client for notifications | `frontend/src/services/notificationService.ts` |
| `useNotificationChannels` | hook | Channel list with loading/error state | `frontend/src/hooks/useNotificationChannels.ts` |
| `useRecipientGroups` | hook | Recipient group list with loading/error state | `frontend/src/hooks/useRecipientGroups.ts` |
| `ChannelListPage` | component | Admin page: list/create/edit/delete channels | `frontend/src/pages/notifications/ChannelListPage.tsx` |
| `ChannelFormDialog` | component | Dialog: create/edit channel with dynamic property fields | `frontend/src/pages/notifications/ChannelFormDialog.tsx` |
| `RecipientGroupListPage` | component | Admin page: list/create/edit/delete recipient groups | `frontend/src/pages/notifications/RecipientGroupListPage.tsx` |
| `RecipientGroupFormDialog` | component | Dialog: create/edit recipient group with channel assignment | `frontend/src/pages/notifications/RecipientGroupFormDialog.tsx` |
| `NotificationLogPage` | component | Admin page: paginated delivery log browser | `frontend/src/pages/notifications/NotificationLogPage.tsx` |
