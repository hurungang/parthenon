# Implementation Plan — Notification System

## Overview

The notification system is built on top of existing `NotificationChannel` and `NotificationEvent` models, extending them with `ChannelProperty`, `RecipientGroup`, `GroupChannelMapping`, and `NotificationLog` entities to support group-based routing and per-channel credential storage. The backend introduces a layered service architecture (channel providers → NotificationService → DeliveryTracker) and exposes a unified `send_notification` MCP tool in the Communication Hub; the frontend adds dedicated admin pages for channel and recipient-group management.

## Task Checklist

### Phase 1 — Database Schema
- [x] 1.1 — Update NotificationChannel model (enum and encrypted_config)
- [x] 1.2 — Add ChannelProperty model
- [x] 1.3 — Add RecipientGroup model
- [x] 1.4 — Add GroupChannelMapping model
- [x] 1.5 — Add NotificationLog model
- [x] 1.6 — Generate and validate Alembic migration

### Phase 2 — Backend Core Services
- [x] 2.1 — Define BaseChannelProvider abstract interface
- [x] 2.2 — Implement SMTPChannelProvider
- [x] 2.3 — Implement EmailAPIChannelProvider
- [x] 2.4 — Implement WebhookChannelProvider
- [x] 2.5 — Implement MessengerChannelProvider
- [x] 2.6 — Implement NotificationRepository
- [x] 2.7 — Implement DeliveryTracker
- [x] 2.8 — Implement NotificationService

### Phase 3 — Backend API Endpoints
- [x] 3.1 — Update notification channel endpoints
- [x] 3.2 — Add recipient group CRUD endpoints
- [x] 3.3 — Add channel test endpoint
- [x] 3.4 — Add manual send endpoint
- [x] 3.5 — Update Pydantic schemas for all new entities

### Phase 4 — MCP Tool Integration
- [x] 4.1 — Implement send_notification MCP tool handler
- [x] 4.2 — Register send_notification in Communication Hub

### Phase 5 — Frontend UI
- [x] 5.1 — Add notificationService API client
- [x] 5.2 — Add useNotificationChannels hook
- [x] 5.3 — Add useRecipientGroups hook
- [x] 5.4 — Implement ChannelListPage
- [x] 5.5 — Implement ChannelFormDialog
- [x] 5.6 — Implement RecipientGroupListPage
- [x] 5.7 — Implement RecipientGroupFormDialog
- [x] 5.8 — Implement NotificationLogPage
- [x] 5.9 — Add i18n translation keys
- [x] 5.10 — Wire notification admin routing

### Phase 6 — Integration & Testing
- [ ] 6.1 — Backend unit tests: channel providers
- [ ] 6.2 — Backend unit tests: NotificationService
- [ ] 6.3 — Backend integration tests: API endpoints
- [ ] 6.4 — Frontend component tests
- [ ] 6.5 — E2E test: admin notification configuration flow

---

## Phase 1 — Database Schema

### Task 1.1 — Update NotificationChannel model (enum and encrypted_config)

Modify `backend/app/db/models/notifications.py`:

- Rename the `ChannelType` enum values from `(email, slack, teams, webhook)` to `(SMTP, EMAIL_API, WEBHOOK, MESSENGER)` to align with the PRD channel taxonomy.
- Remove the `encrypted_config: Mapped[str | None]` column from `NotificationChannel`; configuration migrates to `ChannelProperty` (Task 1.2).
- Add a `properties` relationship to `NotificationChannel` pointing at the new `ChannelProperty` entity.
- Update the `events` relationship reference on `NotificationChannel` to reference `NotificationLog` instead of `NotificationEvent` (in preparation for Task 1.5).

**Done when**: `NotificationChannel` has no `encrypted_config` column, `channel_type` uses the new four-value enum, and Pylance reports no type errors in `notifications.py`.

---

### Task 1.2 — Add ChannelProperty model

Add `ChannelProperty` to `backend/app/db/models/notifications.py`:

- Fields: `id` (UUID PK), `channel_id` (UUID FK → `notification_channels.id` with CASCADE delete), `key` (String, not null), `encrypted_value` (Text, not null — always stored encrypted regardless of `is_secret`), `is_secret` (Boolean, not null), `created_at`, `updated_at`.
- Add a `channel` back-reference to `NotificationChannel`.
- Unique constraint on `(channel_id, key)` so each channel has at most one value per property key.

**Done when**: `ChannelProperty` is importable from `app.db.models.notifications`, has the correct columns and FK constraint, and the unique constraint on `(channel_id, key)` is defined.

---

### Task 1.3 — Add RecipientGroup model

Add `RecipientGroup` to `backend/app/db/models/notifications.py`:

- Fields: `id` (UUID PK), `name` (String 200, not null, unique), `slug` (String 100, not null, unique — URL-safe identifier used by agents), `description` (Text, nullable), `is_active` (Boolean, default True), `created_at`, `updated_at`.
- Add `channel_mappings` relationship to `GroupChannelMapping` (Task 1.4) with cascade delete.
- Add `logs` relationship to `NotificationLog` (Task 1.5).

**Done when**: `RecipientGroup` is importable, `slug` has a unique constraint, and both relationships are defined without circular import errors.

---

### Task 1.4 — Add GroupChannelMapping model

Add `GroupChannelMapping` to `backend/app/db/models/notifications.py`:

- Fields: `id` (UUID PK), `group_id` (UUID FK → `recipient_groups.id`, CASCADE delete), `channel_id` (UUID FK → `notification_channels.id`, CASCADE delete), `created_at`.
- Unique constraint on `(group_id, channel_id)` to prevent duplicate mappings.
- Back-references on both `RecipientGroup` and `NotificationChannel`.

**Done when**: `GroupChannelMapping` is importable, both FKs are defined, and the unique constraint is present.

---

### Task 1.5 — Add NotificationLog model

Add `NotificationLog` to `backend/app/db/models/notifications.py` and introduce a `SourceType` enum:

- `SourceType` enum values: `SOP`, `AGENT`, `MANUAL`.
- `NotificationLog` fields: `id` (UUID PK), `group_id` (UUID FK → `recipient_groups.id`, nullable — nullable for backward compat with channel-direct sends), `channel_id` (UUID FK → `notification_channels.id`), `source_type` (`SourceType` enum), `source_id` (UUID, nullable), `subject` (String 500, nullable), `body` (Text, not null), `recipient` (String 500, nullable), `status` (`DeliveryStatus` enum, default `pending`), `error` (Text, nullable), `metadata` (JSON, nullable), `created_at`, `delivered_at` (DateTime, nullable).
- The existing `NotificationEvent` model is kept in place for this migration cycle; it will be retired after data migration is confirmed.

**Done when**: `NotificationLog` and `SourceType` are importable, all FKs are defined, and `NotificationEvent` is still present (not yet deleted).

---

### Task 1.6 — Generate and validate Alembic migration

Run `alembic revision --autogenerate -m "implement_notification_system"` from the `backend/` directory. Review the generated migration script to confirm:

- New tables `channel_properties`, `recipient_groups`, `group_channel_mappings`, `notification_logs` are created.
- `notification_channels.encrypted_config` column drop is present.
- `channel_type_enum` ALTER is present (or a new enum is created and the old one dropped).
- No unintended table drops appear (especially `notification_events`).

Apply with `alembic upgrade head` and verify with `alembic current`.

**Done when**: `alembic upgrade head` completes without error, `alembic current` shows the new revision, and `information_schema.tables` confirms all four new tables exist.

---

## Phase 2 — Backend Core Services

### Task 2.1 — Define BaseChannelProvider abstract interface

Create `backend/app/services/notifications/providers/base.py`:

- Abstract base class `BaseChannelProvider` with a single abstract async method `send(recipients, subject, body, properties)` returning a `ChannelDeliveryResult` typed dataclass.
- `ChannelDeliveryResult` fields: `success` (bool), `error` (str | None), `metadata` (dict | None).
- This interface is the contract all concrete providers implement.

**Done when**: `BaseChannelProvider` is importable, mypy/Pylance reports no type errors, and the abstract method signature uses Pydantic or dataclass types for parameters.

---

### Task 2.2 — Implement SMTPChannelProvider

Create `backend/app/services/notifications/providers/smtp.py`:

- Extends `BaseChannelProvider`.
- Reads the following property keys from `ChannelProperty`: `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password` (secret), `from_address`, `use_tls`.
- Uses Python `smtplib` (async-wrapped via `asyncio.to_thread`) to send MIME multipart messages.
- Returns `ChannelDeliveryResult` with success/failure and any SMTP error detail.
- OpenTelemetry span wraps the `send` call with attributes: `channel.type=SMTP`, `notification.recipient_count`.

**Done when**: Unit test can instantiate `SMTPChannelProvider` with mock property values, call `send`, and verify it invokes `smtplib.SMTP` with the correct host/port.

---

### Task 2.3 — Implement EmailAPIChannelProvider

Create `backend/app/services/notifications/providers/email_api.py`:

- Extends `BaseChannelProvider`.
- Reads property keys: `api_url`, `api_key` (secret), `from_address`, `provider_name` (e.g., `sendgrid`, `mailgun`).
- Uses `httpx.AsyncClient` to POST to the provider API URL.
- Returns `ChannelDeliveryResult`.
- OpenTelemetry span with `channel.type=EMAIL_API` and `email_api.provider_name`.

**Done when**: Unit test with `httpx` mock verifies the POST body is formed correctly and success/failure cases are handled.

---

### Task 2.4 — Implement WebhookChannelProvider

Create `backend/app/services/notifications/providers/webhook.py`:

- Extends `BaseChannelProvider`.
- Reads property keys: `webhook_url`, `secret` (optional, secret), `http_method` (default `POST`), `content_type` (default `application/json`).
- Signs the payload with HMAC-SHA256 if `secret` is present (header `X-Notification-Signature`).
- Uses `httpx.AsyncClient`; retries once on 5xx.
- Returns `ChannelDeliveryResult`.
- OpenTelemetry span with `channel.type=WEBHOOK` and `webhook.http_method`.

**Done when**: Unit test verifies HMAC signature header is present when secret is configured, and absent when it is not.

---

### Task 2.5 — Implement MessengerChannelProvider

Create `backend/app/services/notifications/providers/messenger.py`:

- Extends `BaseChannelProvider`.
- Reads property keys: `platform` (`teams` or `slack`), `webhook_url` (secret), `channel_name` (optional).
- For `teams`: formats adaptive card payload; for `slack`: formats Block Kit payload.
- Uses `httpx.AsyncClient` for HTTP POST to the webhook URL.
- Returns `ChannelDeliveryResult`.
- OpenTelemetry span with `channel.type=MESSENGER` and `messenger.platform`.

**Done when**: Unit test verifies correct payload format for both `teams` and `slack` platforms.

---

### Task 2.6 — Implement NotificationRepository

Create `backend/app/services/notifications/repository.py`:

- Async repository class `NotificationRepository` accepting an `AsyncSession`.
- Methods: `get_channel(id)`, `list_channels()`, `create_channel(data)`, `update_channel(id, data)`, `delete_channel(id)`, `get_channel_properties(channel_id)`, `set_channel_property(channel_id, key, encrypted_value, is_secret)`, `get_recipient_group(id)`, `get_recipient_group_by_slug(slug)`, `list_recipient_groups()`, `create_recipient_group(data)`, `update_recipient_group(id, data)`, `delete_recipient_group(id)`, `assign_channel_to_group(group_id, channel_id)`, `remove_channel_from_group(group_id, channel_id)`, `create_notification_log(data)`, `update_log_status(log_id, status, error, delivered_at, metadata)`, `list_logs(group_id, channel_id, limit, offset)`.
- All methods are `async def` and use SQLAlchemy 2 async patterns (`await session.execute(select(...))`).
- Return ORM model instances (not raw dicts) for type safety.

**Done when**: All methods are implemented, Pylance reports no type errors, and the repository can be instantiated in a unit test with a mock session.

---

### Task 2.7 — Implement DeliveryTracker

Create `backend/app/services/notifications/delivery_tracker.py`:

- Class `DeliveryTracker` with an async method `record(log_id, channel_type, status, error, metadata)`.
- Calls `NotificationRepository.update_log_status` to persist the outcome.
- Emits an OpenTelemetry structured log event with attributes: `notification.log_id`, `notification.channel_type`, `notification.status`, and `notification.error` (if failed).
- Increments OpenTelemetry counters: `notifications.sent.total` (labelled by `channel_type` and `status`).

**Done when**: `DeliveryTracker.record` writes to the database and the OTEL counter increment is called with correct labels in a unit test using a mock meter.

---

### Task 2.8 — Implement NotificationService

Create `backend/app/services/notifications/notification_service.py`:

- Class `NotificationService` coordinating the full send flow.
- Constructor accepts an `AsyncSession`; instantiates `NotificationRepository` and `DeliveryTracker` internally.
- Method `send_to_group(group_slug, subject, body, source_type, source_id)`:
  1. Resolve `RecipientGroup` by slug via repository (raise `ValueError` if not found or inactive).
  2. Load all `GroupChannelMapping` entries and their associated `NotificationChannel` + `ChannelProperty` records.
  3. Decrypt secret properties via `CredentialVault`.
  4. For each channel, select the appropriate `BaseChannelProvider` by `channel_type`.
  5. Create a `NotificationLog` record (status `PENDING`) before dispatch.
  6. Call provider `send`; on completion call `DeliveryTracker.record`.
  7. Continue to remaining channels if one fails (do not raise on partial failure).
- Method `test_channel(channel_id, test_recipient)`: sends a canned test message through the channel, returns `ChannelDeliveryResult`.
- Wrap the entire `send_to_group` call in a top-level OpenTelemetry span: `notification.send_to_group`.

**Done when**: A unit test mocks the repository, vault, and providers; calls `send_to_group`; and verifies that all channels are dispatched and `DeliveryTracker.record` is called for each.

---

## Phase 3 — Backend API Endpoints

### Task 3.1 — Update notification channel endpoints

Refactor `backend/app/api/v1/notifications.py`:

- Replace the direct `encrypted_config` read/write pattern with calls to `NotificationService` / `NotificationRepository`.
- Channel create/update no longer accepts `encrypted_config`; instead accept a `properties` dict of key/value pairs.
- Before storing any property value, encrypt it via `CredentialVault` regardless of `is_secret` flag.
- Remove references to the old `NotificationDispatcher` class for channel CRUD (it is replaced by the new service layer).
- Existing endpoint paths (`GET /notifications/channels`, `POST /notifications/channels`, `PUT /notifications/channels/{id}`, `DELETE /notifications/channels/{id}`) are preserved to avoid breaking the frontend.

**Done when**: All existing channel endpoints work with the new model; Pylance reports no type errors; `encrypted_config` is not referenced anywhere in the handler.

---

### Task 3.2 — Add recipient group CRUD endpoints

Add to `backend/app/api/v1/notifications.py` (or a new `recipient_groups.py` sub-router merged into the notifications router):

- `GET /notifications/recipient-groups` — list all groups.
- `POST /notifications/recipient-groups` — create a group (slug auto-generated from name if not provided).
- `GET /notifications/recipient-groups/{id}` — get group with its channel assignments.
- `PUT /notifications/recipient-groups/{id}` — update name/description/is_active.
- `DELETE /notifications/recipient-groups/{id}` — delete group and its mappings.
- `POST /notifications/recipient-groups/{id}/channels` — assign a channel to the group.
- `DELETE /notifications/recipient-groups/{id}/channels/{channel_id}` — remove a channel assignment.

All endpoints require JWT auth and `manage` permission on `RT_NOTIFICATION`.

**Done when**: All seven endpoint routes are reachable; `GET /notifications/recipient-groups` returns an empty list in a clean test database; `POST` creates a group and returns 201.

---

### Task 3.3 — Add channel test endpoint

Add `POST /notifications/channels/{id}/test` to `backend/app/api/v1/notifications.py`:

- Request body: `TestChannelRequest` with `test_recipient` (str).
- Delegates to `NotificationService.test_channel(channel_id, test_recipient)`.
- Returns 200 with `success` flag and optional `error` message.
- Requires `manage` permission on `RT_NOTIFICATION`.

**Done when**: Calling the endpoint with a valid channel ID and a test recipient invokes the provider and returns a JSON response with `success: true/false`.

---

### Task 3.4 — Add manual send endpoint

Add `POST /notifications/send` to `backend/app/api/v1/notifications.py`:

- Request body: `SendNotificationRequest` with `group_slug` (str), `subject` (str | None), `body` (str), `source_type` (`SourceType` enum, default `MANUAL`), `source_id` (UUID | None).
- Delegates to `NotificationService.send_to_group`.
- Returns 202 Accepted with a `notification_log_ids` list (one per channel dispatched).
- Requires `manage` permission on `RT_NOTIFICATION`.

**Done when**: `POST /notifications/send` with a valid group slug triggers dispatch and returns 202 with log IDs; a `NotificationLog` row is created in the database for each channel.

---

### Task 3.5 — Update Pydantic schemas for all new entities

Update `backend/app/schemas/notifications.py`:

- Add `ChannelPropertyRead`, `ChannelPropertyWrite` schemas (key, encrypted_value hidden on read, is_secret visible).
- Add `RecipientGroupCreate`, `RecipientGroupRead`, `RecipientGroupUpdate` schemas.
- Add `GroupChannelMappingRead` schema.
- Add `NotificationLogRead` schema (all fields, source_type as enum).
- Add `SendNotificationRequest` schema.
- Update `NotificationChannelCreate` and `NotificationChannelRead` to include `properties: list[ChannelPropertyRead]` and remove `encrypted_config`.
- Update `ChannelType` schema enum to match new model values: `SMTP`, `EMAIL_API`, `WEBHOOK`, `MESSENGER`.

All schemas use Pydantic v2 `model_config = ConfigDict(from_attributes=True)`.

**Done when**: Pylance reports no type errors; all new schemas are importable; existing `NotificationChannelRead` no longer exposes `encrypted_config`.

---

## Phase 4 — MCP Tool Integration

### Task 4.1 — Implement send_notification MCP tool handler

Create `backend/app/services/notifications/mcp_tool.py`:

- Defines a single MCP tool descriptor `send_notification` with `inputSchema` properties: `group_slug` (string, required), `subject` (string, optional), `body` (string, required).
- Implements the async handler function `handle_send_notification(args, db_session, caller_identity)`:
  1. Validates `caller_identity` has `send` permission on `RT_NOTIFICATION` (or uses existing RBAC check pattern).
  2. Calls `NotificationService.send_to_group` with `source_type=AGENT` and `source_id` from `caller_identity.agent_id`.
  3. Returns an MCP tool result with delivery summary (channels attempted, success/failure counts).
- OpenTelemetry span: `mcp.notification.send_notification`.

**Done when**: The tool descriptor is importable and the handler function passes a unit test mocking `NotificationService.send_to_group`.

---

### Task 4.2 — Register send_notification in Communication Hub

Update the Communication Hub's MCP tool registry (locate the tool registration point in `backend/app/communication_hub/`):

- Import `send_notification` tool descriptor and handler from `mcp_tool.py`.
- Register the tool so it appears in the `tools/list` MCP response.
- Wire the handler into the `tools/call` dispatch logic for the tool name `send_notification`.
- Remove the old per-channel MCP tools (`notify_email`, `notify_slack`, `notify_teams`, `notify_webhook`) from the dispatcher registration — they are superseded by `send_notification`.

**Done when**: A `tools/list` MCP request to the Communication Hub includes `send_notification` in the response; the old `notify_*` tools are no longer listed.

---

## Phase 5 — Frontend UI

### Task 5.1 — Add notificationService API client

Create `frontend/src/services/notificationService.ts`:

- Typed async functions wrapping `fetch` (or the existing authenticated HTTP client) for all notification endpoints:
  - `listChannels()`, `createChannel(data)`, `updateChannel(id, data)`, `deleteChannel(id)`, `testChannel(id, testRecipient)`.
  - `listRecipientGroups()`, `createRecipientGroup(data)`, `updateRecipientGroup(id, data)`, `deleteRecipientGroup(id)`.
  - `assignChannelToGroup(groupId, channelId)`, `removeChannelFromGroup(groupId, channelId)`.
  - `listNotificationLogs(params)`.
- All functions use TypeScript interfaces matching the Pydantic response schemas.
- All requests include the JWT bearer token from the auth context (follow existing service pattern).

**Done when**: The service file has no TypeScript compile errors; all function signatures match the API schema.

---

### Task 5.2 — Add useNotificationChannels hook

Create `frontend/src/hooks/useNotificationChannels.ts`:

- Wraps `notificationService.listChannels()` with loading/error state.
- Exposes `channels`, `isLoading`, `error`, `refetch`.
- Uses the established hook pattern (see `useMcpServers.ts` for reference).

**Done when**: Hook compiles without TypeScript errors and `channels` is typed as `NotificationChannelRead[]`.

---

### Task 5.3 — Add useRecipientGroups hook

Create `frontend/src/hooks/useRecipientGroups.ts`:

- Wraps `notificationService.listRecipientGroups()` with loading/error state.
- Exposes `groups`, `isLoading`, `error`, `refetch`.

**Done when**: Hook compiles without TypeScript errors and `groups` is typed as `RecipientGroupRead[]`.

---

### Task 5.4 — Implement ChannelListPage

Create `frontend/src/pages/notifications/ChannelListPage.tsx`:

- MUI `DataGrid` or `Table` listing all channels with columns: Name, Type, Active status, Created date, Actions.
- Toolbar with "Add Channel" button opening `ChannelFormDialog`.
- Each row has Edit and Delete actions.
- Delete triggers a confirmation dialog before calling `notificationService.deleteChannel`.
- All text via `t()` with keys under `notifications.channels.*`.
- Errors from API calls displayed via `PermissionDeniedAlert` following the Dialog Error Handling Standard.

**Done when**: Page renders without runtime errors; channel list loads; delete confirmation appears before deletion.

---

### Task 5.5 — Implement ChannelFormDialog

Create `frontend/src/pages/notifications/ChannelFormDialog.tsx`:

- MUI `Dialog` used for both create and edit.
- Fields: Name (text), Type (select: SMTP / Email API / Webhook / Messenger), Description (text, optional), Active (toggle).
- Dynamic property fields rendered based on selected `channel_type`:
  - SMTP: `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password` (masked), `from_address`, `use_tls`.
  - EMAIL_API: `api_url`, `api_key` (masked), `from_address`, `provider_name`.
  - WEBHOOK: `webhook_url`, `secret` (masked), `http_method`, `content_type`.
  - MESSENGER: `platform` (teams/slack), `webhook_url` (masked), `channel_name`.
- "Test Send" button (in edit mode) opens a small input for test recipient and calls `notificationService.testChannel`.
- Follows Dialog Error Handling Standard: `dialogError` state, `PermissionDeniedAlert` at top of `DialogContent`.

**Done when**: Dialog opens for create and edit; dynamic property fields switch correctly on type change; Test Send returns and displays success/failure.

---

### Task 5.6 — Implement RecipientGroupListPage

Create `frontend/src/pages/notifications/RecipientGroupListPage.tsx`:

- Lists all recipient groups with columns: Name, Slug, Channels assigned (count), Active, Actions.
- "Add Group" button opens `RecipientGroupFormDialog`.
- Each row has Edit, Delete, and "Manage Channels" inline action.
- All text via `t()` with keys under `notifications.groups.*`.
- Dialog Error Handling Standard applied to delete.

**Done when**: Page renders; groups load; channel count is shown per group.

---

### Task 5.7 — Implement RecipientGroupFormDialog

Create `frontend/src/pages/notifications/RecipientGroupFormDialog.tsx`:

- MUI `Dialog` for create/edit of a recipient group.
- Fields: Name (text), Slug (auto-populated from name, editable), Description (text, optional), Active (toggle).
- "Channels" multi-select section listing available channels with assign/remove capability (calls `assignChannelToGroup` / `removeChannelFromGroup`).
- Follows Dialog Error Handling Standard.

**Done when**: Dialog creates and updates groups; slug is auto-populated; channel assignment calls the correct API endpoints.

---

### Task 5.8 — Implement NotificationLogPage

Create `frontend/src/pages/notifications/NotificationLogPage.tsx`:

- Paginated table of `NotificationLog` records with columns: Timestamp, Group, Channel, Source, Subject, Status (chip: Delivered/Failed/Pending), Recipient.
- Filter controls: status filter (chip group), date range picker, group filter (select).
- Row click opens a detail panel/drawer showing `error` and `metadata` fields.
- All text via `t()` with keys under `notifications.logs.*`.

**Done when**: Page loads log entries; status filter changes the displayed rows; row click shows detail.

---

### Task 5.9 — Add i18n translation keys

Add all notification-related translation keys to the English locale file (`frontend/src/i18n/en.json` or equivalent):

Key namespaces to add:
- `notifications.channels.*` — page titles, column headers, form labels, button labels for channel management.
- `notifications.groups.*` — same for recipient groups.
- `notifications.logs.*` — same for notification log page.
- `notifications.channelTypes.*` — display names for SMTP, EMAIL_API, WEBHOOK, MESSENGER.
- `notifications.status.*` — display names for PENDING, DELIVERED, FAILED.
- `notifications.sourceTypes.*` — display names for SOP, AGENT, MANUAL.

**Done when**: All `t()` calls in notification pages resolve to defined keys with no missing-key warnings in the browser console.

---

### Task 5.10 — Wire notification admin routing

Update the frontend router configuration to add routes for the new pages:

- `/admin/notifications/channels` → `ChannelListPage`
- `/admin/notifications/groups` → `RecipientGroupListPage`
- `/admin/notifications/logs` → `NotificationLogPage`

Add navigation links in the admin sidebar under a "Notifications" section (follow existing nav pattern).

**Done when**: All three routes resolve to the correct page components; sidebar shows the Notifications nav section with working links.

---

## Phase 6 — Integration & Testing

### Task 6.1 — Backend unit tests: channel providers

Create `backend/tests/unit/test_notification_providers.py`:

- SMTP provider: mock `smtplib.SMTP`; verify correct connection params; verify MIMEText payload; verify failure path returns `success=False`.
- Email API provider: mock `httpx.AsyncClient`; verify POST body; verify header includes `api_key`; verify error on non-2xx.
- Webhook provider: mock `httpx.AsyncClient`; verify HMAC signature present when secret configured; verify absent without secret; verify retry on 5xx.
- Messenger provider: verify Teams adaptive card format; verify Slack Block Kit format; verify error on unknown platform.

**Done when**: All provider test cases pass with `pytest`; no warnings about missing fixtures.

---

### Task 6.2 — Backend unit tests: NotificationService

Create `backend/tests/unit/test_notification_service.py`:

- Test `send_to_group` with two channels: verify both providers are called; verify `DeliveryTracker.record` called twice; verify partial failure (one channel fails) does not prevent second channel dispatch.
- Test `send_to_group` with unknown slug: verify `ValueError` raised.
- Test `send_to_group` with inactive group: verify appropriate error.
- Test `test_channel`: verify correct provider invoked and result returned.

**Done when**: All tests pass; `NotificationService` is tested in isolation with mocks for repository, vault, and providers.

---

### Task 6.3 — Backend integration tests: API endpoints

Create `backend/tests/integration/test_notification_api.py`:

- Use real test database with `alembic upgrade head` applied in fixture.
- Test `GET /notifications/channels` returns empty list.
- Test `POST /notifications/channels` creates channel, properties are stored encrypted.
- Test `GET /notifications/recipient-groups` returns empty list.
- Test `POST /notifications/recipient-groups` creates group; slug is set.
- Test `POST /notifications/recipient-groups/{id}/channels` assigns a channel.
- Test `DELETE /notifications/recipient-groups/{id}/channels/{channel_id}` removes assignment.
- Test `POST /notifications/send` with valid group returns 202 and log IDs.
- Test `POST /notifications/send` with unknown group slug returns 404.

**Done when**: All integration tests pass against a real PostgreSQL test database with migrations applied.

---

### Task 6.4 — Frontend component tests

Create test files in `frontend/src/__tests__/notifications/`:

- `ChannelListPage.test.tsx` — mock `notificationService.listChannels`; verify table renders channels; verify delete confirmation appears.
- `RecipientGroupListPage.test.tsx` — mock `notificationService.listRecipientGroups`; verify table renders groups.
- `NotificationLogPage.test.tsx` — mock `notificationService.listLogs`; verify paginated table renders; verify status filter works.

**Done when**: All frontend tests pass with `vitest`; no TypeScript errors in test files.

---

### Task 6.5 — E2E test: admin notification configuration flow

Create the following files in `e2e/tests/notifications/`:

- `channel-management.spec.ts` — navigate to `/admin/notifications/channels`; create, edit, and delete a Webhook channel via the admin UI.
- `recipient-group-management.spec.ts` — create a recipient group; assign a channel to it; verify channel count; remove the channel; delete the group.
- `notification-sending.spec.ts` — trigger a manual send via UI; verify a log entry appears on the log page.
- `real-backend-integration.spec.ts` — labelled `Real Backend Integration - Notifications`; no `page.route()` mocks; runs against the live application stack; creates a channel and group, triggers a send, verifies `NotificationLog` row via real API.

**Done when**: All four spec files pass end-to-end against a running dev stack; a `NotificationLog` row is created in the database.

---

## Completion Checklist

- [ ] All Alembic migrations applied cleanly (`alembic upgrade head`)
- [ ] All new tables present in the database (`information_schema.tables`)
- [ ] `NotificationEvent` entity archived / data migrated to `NotificationLog`
- [ ] `notify_email`, `notify_slack`, `notify_teams`, `notify_webhook` MCP tools removed from Communication Hub
- [ ] `send_notification` MCP tool appears in `tools/list` response
- [ ] All backend unit tests passing (`pytest backend/tests/`)
- [ ] All backend integration tests passing against real test DB
- [ ] All frontend component tests passing (`vitest`)
- [ ] E2E test passing against real dev stack
- [ ] No TypeScript compile errors (`tsc --noEmit`)
- [ ] No Pylance type errors in changed files
- [ ] All UI text uses `t()` — no hardcoded strings in notification pages
- [ ] All new API endpoints documented in OpenAPI (`/docs`)
- [ ] Channel credentials never logged or returned in plain text in API responses
