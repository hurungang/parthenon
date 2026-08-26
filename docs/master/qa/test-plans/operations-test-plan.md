# Operations Modules Test Plan

## What to Test
- **Scheduling**: Cron trigger accuracy, job execution recording, missed-fire handling; permission enforcement (`scheduling:read`, `scheduling:create`)
- **Conversation Store**: Persistence of all turn types, queryability, ordering; permission enforcement (`conversation:read`)
- **Result Repository**: `system____save_result` tool invocation (explicit only — runtime does not auto-save), storage, retrieval, permission scoping; permission enforcement (`result:read`). Negative test: agent completes without calling `save_result` → no result record created.
- **Notification System**: Full channel CRUD and delivery for all four channel types (SMTP, EMAIL_API, WEBHOOK, MESSENGER); recipient group CRUD and channel assignment; agent `system____send_notification` tool call flow; delivery log (`NotificationLog`) creation and query; partial failure handling (one channel fails, remaining channels still attempted); permission enforcement (`RT_NOTIFICATION`)
- **Observability**: OTEL trace emission, span correlation, metric export, log correlation fields

## Critical Scenarios

- **WHEN** a schedule's cron time arrives, **THEN** the scheduled SOP executes and a job record is created.
- **WHEN** an agent explicitly calls `system____save_result`, **THEN** a result record is persisted; **WHEN** the agent completes without calling it, **THEN** no result record is created.
- **WHEN** an agent triggers `system____send_notification` with a group slug, **THEN** a `NotificationLog` entry is created per assigned channel with per-channel delivery status.
- **WHEN** one notification channel fails, **THEN** delivery continues to the remaining channels.
- **WHEN** notification `source_type` is tool-triggered, **THEN** it is recorded as `AGENT`; **WHEN** UI-triggered, **THEN** `MANUAL`.
- **WHEN** a channel credential is written, **THEN** it is encrypted at rest and secret properties are omitted from read responses.
- **WHEN** a user without `scheduling:read` requests `GET /api/v1/schedules`, **THEN** 403 is returned.
- **WHEN** a user without `conversation:read` requests `GET /api/v1/conversations`, **THEN** 403 is returned.
- **WHEN** a user without `result:read` requests `GET /api/v1/results`, **THEN** 403 is returned.
- **WHEN** OTEL instrumentation is active, **THEN** traces are emitted for the complete execution chain.

## Edge Cases
- Missed cron fire
- Agent calls `save_result` with oversized payload
- Channel credential expiry
- Dropped OTEL spans
- Permission revoked between schedule create and next execution
- Notification channel test-send with invalid credentials → returns error detail; channel remains configured

## Notification-Specific Test Coverage

### Channel Management
- Create, read, update, delete for all four channel types; each channel type has distinct required property set
- Secret properties (`is_secret=true`) encrypted at write; never returned in GET/PUT responses
- Test-send per channel type: success and failure cases
- Delete channel that is assigned to a group returns 409

### Recipient Group Management
- Create, read, update, delete recipient groups
- Auto-slug generation from display name; slug must be unique
- Assign channel to group; remove channel from group; channel count updates in list response
- Two groups can share the same channel

### Notification Delivery
- `POST /api/v1/notifications/send` with valid group slug → one `NotificationLog` per assigned channel
- Delivery continues to remaining channels when one fails (`FAILED` log entry does not block others)
- `source_type` correctly set for each trigger method
- `NotificationLog` query endpoint returns entries filterable by status, date, and group

### MCP Tool Integration
- `system____send_notification` callable with `group_slug` and `body`; caller RBAC validated
- `system____get_recipient_group` returns group metadata for valid slug; 404 for unknown slug
- `source_type=AGENT` recorded in `NotificationLog` for tool-triggered sends

### Backend Integration Tests (Real Database Required)
- Test setup runs `alembic upgrade head`; verifies all five notification tables exist via `information_schema`
- Constraint tests: duplicate `GroupChannelMapping` entry returns 409; channel FK integrity on `NotificationLog`

## Test File References
- `backend/tests/unit/test_scheduling.py`, `e2e/tests/scheduling.spec.ts`
- `backend/tests/unit/test_conversation_store.py`, `e2e/tests/conversations.spec.ts`
- `backend/tests/unit/test_result_store.py`, `e2e/tests/results.spec.ts`
- `backend/tests/unit/test_notifications.py` — channel provider unit tests, NotificationService orchestration, DeliveryTracker
- `backend/tests/integration/test_notification_api.py` — full API + DB integration tests
- `e2e/tests/notifications/channel-management.spec.ts`, `e2e/tests/notifications/recipient-group-management.spec.ts`, `e2e/tests/notifications/notification-sending.spec.ts`, `e2e/tests/notifications/real-backend-integration.spec.ts`
- `e2e/tests/observability.spec.ts`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering across all operations pages
