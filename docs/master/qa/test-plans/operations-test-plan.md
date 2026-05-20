# Operations Modules Test Plan

## What to Test
- **Scheduling**: Cron trigger accuracy, job execution recording, missed-fire handling; permission enforcement (`scheduling:read`, `scheduling:create`)
- **Conversation Store**: Persistence of all turn types, queryability, ordering; permission enforcement (`conversation:read`)
- **Result Repository**: `system____save_result` tool invocation (explicit only — runtime does not auto-save), storage, retrieval, permission scoping; permission enforcement (`result:read`). Negative test: agent completes without calling `save_result` → no result record created.
- **Notification System**: Full channel CRUD and delivery for all four channel types (SMTP, EMAIL_API, WEBHOOK, MESSENGER); recipient group CRUD and channel assignment; agent `system____send_notification` tool call flow; delivery log (`NotificationLog`) creation and query; partial failure handling (one channel fails, remaining channels still attempted); permission enforcement (`RT_NOTIFICATION`)
- **Observability**: OTEL trace emission, span correlation, metric export, log correlation fields

## Critical Scenarios
- Scheduled SOP executes at cron time
- Agent saves result via `system____save_result` tool (explicit call only)
- Agent completes without calling `save_result` → no result record created
- Agent triggers notification via `system____send_notification` with group slug → `NotificationLog` entry created per channel; delivery status reflects per-channel outcome
- Delivery continues to remaining channels when one channel fails
- Notification source_type recorded as `AGENT` for tool-triggered sends; `MANUAL` for UI-triggered sends
- Channel credential encrypted at write; secret properties omitted from read response
- Channel assigned to group; group deleted-while-assigned returns 409 (if applicable per schema)
- Conversation history persisted with tool calls
- OTEL traces emitted for complete chain
- User without `RT_NOTIFICATION` receives 403 on notification channel/group/log endpoints; UI shows permission-denied snackbar
- User without `scheduling:read` receives 403 on `GET /api/v1/schedules`
- User without `conversation:read` receives 403 on `GET /api/v1/conversations`
- User without `result:read` receives 403 on `GET /api/v1/results`

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
