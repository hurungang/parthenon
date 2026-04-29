# Operations Modules Test Plan

## What to Test
- **Scheduling**: Cron trigger accuracy, job execution recording, missed-fire handling
- **Conversation Store**: Persistence of all turn types, queryability, ordering
- **Result Repository**: save_result tool invocation, storage, retrieval, permission scoping
- **Notification Engine**: Channel invocation via MCP tool, delivery to each channel type, failure handling
- **Observability**: OTEL trace emission, span correlation, metric export, log correlation fields

## Critical Scenarios
- Scheduled SOP executes at cron time
- Agent saves result via save_result
- Agent triggers notification
- Conversation history persisted with tool calls
- OTEL traces emitted for complete chain

## Edge Cases
- Missed cron fire
- Oversized save_result payload
- Channel credential expiry
- Dropped OTEL spans

## Test File References
- `backend/tests/unit/test_scheduling.py`, `e2e/tests/scheduling.spec.ts`
- `backend/tests/unit/test_conversation_store.py`, `e2e/tests/conversations.spec.ts`
- `backend/tests/unit/test_result_store.py`, `e2e/tests/results.spec.ts`
- `backend/tests/unit/test_notifications.py`, `e2e/tests/notifications.spec.ts`
- `e2e/tests/observability.spec.ts`
