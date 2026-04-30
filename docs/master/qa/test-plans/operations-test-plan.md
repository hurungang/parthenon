# Operations Modules Test Plan

## What to Test
- **Scheduling**: Cron trigger accuracy, job execution recording, missed-fire handling; permission enforcement (`scheduling:read`, `scheduling:create`)
- **Conversation Store**: Persistence of all turn types, queryability, ordering; permission enforcement (`conversation:read`)
- **Result Repository**: save_result tool invocation, storage, retrieval, permission scoping; permission enforcement (`result:read`)
- **Notification Engine**: Channel invocation via MCP tool, delivery to each channel type, failure handling; permission enforcement (`notification:read`, `notification:manage`)
- **Observability**: OTEL trace emission, span correlation, metric export, log correlation fields
- **Permission Errors**: 403 structured responses with resource type, action, and resource ID across all operations endpoints; UI shows permission-denied snackbar with actionable messaging

## Critical Scenarios
- Scheduled SOP executes at cron time
- Agent saves result via save_result
- Agent triggers notification
- Conversation history persisted with tool calls
- OTEL traces emitted for complete chain
- User without `scheduling:read` receives 403 on `GET /api/v1/schedules`; UI shows permission-denied message
- User without `notification:manage` receives 403 on `POST /api/v1/notifications/channels`
- User without `conversation:read` receives 403 on `GET /api/v1/conversations`
- User without `result:read` receives 403 on `GET /api/v1/results`
- Schedule execution history panel shows success/failure status for completed runs
- Notification event log displays delivered events alongside configured channels
- Result repository shows tag chips attached to each result entry

## Edge Cases
- Missed cron fire
- Oversized save_result payload
- Channel credential expiry
- Dropped OTEL spans
- Permission revoked between schedule create and next execution

## Test File References
- `backend/tests/unit/test_scheduling.py`, `e2e/tests/scheduling.spec.ts`
- `backend/tests/unit/test_conversation_store.py`, `e2e/tests/conversations.spec.ts`
- `backend/tests/unit/test_result_store.py`, `e2e/tests/results.spec.ts`
- `backend/tests/unit/test_notifications.py`, `e2e/tests/notifications.spec.ts`
- `e2e/tests/observability.spec.ts`
- `e2e/tests/permission-errors.spec.ts` — structured 403 error rendering across all operations pages
