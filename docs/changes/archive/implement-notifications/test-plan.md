# Test Plan — Notification System

## 1. Test Strategy

### Unit Testing (Backend Services)
Test each component in isolation with mocked dependencies. Focus on business logic correctness, not integration behavior.

- **Channel providers** (`SMTPChannelProvider`, `EmailAPIChannelProvider`, `WebhookChannelProvider`, `MessengerChannelProvider`): validate payload construction, HMAC signing logic, platform-specific formatting (Teams/Slack), and error propagation.
- **`NotificationService`**: validate orchestration logic — group resolution, provider selection, partial failure handling (continues to remaining channels on one failure), `CredentialVault` decrypt calls, and `DeliveryTracker` interaction.
- **`DeliveryTracker`**: validate log record creation, OTEL span/counter emission, and status mapping.
- **`NotificationRepository`**: validate query construction, filter logic, and pagination — tested against an in-memory SQLite or via mock sessions.

### Integration Testing (Backend API + Real Database)
Test the full request path: router → service → repository → PostgreSQL. All integration tests must use a real PostgreSQL database with migrations applied.

- **Database migration verification**: integration test setup must run `alembic upgrade head` and then confirm all notification tables and columns exist via `information_schema` queries.
- **CRUD lifecycle per entity**: channel creation, property encryption, group creation, channel assignment, log creation.
- **Authorization enforcement**: requests without JWT and requests with insufficient permissions must be rejected.
- **Constraint validation**: test behaviors that depend on schema constraints (FK integrity, 409 on duplicate assignment, 409 on delete-while-assigned).

### E2E Testing (Playwright + Real Backend)
Validate complete user flows through the browser. At least one test suite must hit the real backend without mocks.

- **Channel management flow**: create → test send → edit → delete through the admin UI.
- **Recipient group management flow**: create group → assign channels → edit → remove channel → delete.
- **Notification delivery flow**: trigger manual send via UI → verify log entry appears in `NotificationLogPage`.
- **Real backend integration variant**: labelled `test.describe('Real Backend Integration - Notifications')`, no `page.route()` mocks, runs against the live application stack.

### Manual Testing (Human Verification Required)
Some scenarios require a real external service and cannot be fully automated:

- Live SMTP send to a real inbox (verify received email with correct From, subject, body).
- Live Slack/Teams webhook delivery (verify message appears in channel with correct formatting).
- Live Email API (SendGrid/Mailgun) delivery with real API key.
- OTEL metrics appearing in the configured observability backend after sends.

---

## 2. Coverage Areas

### Channel Management
Channel CRUD is the foundational admin operation. All four channel types have distinct property sets; each must be validated independently. Secret properties must never appear in API responses.

- Create, read, update, delete for all four channel types (SMTP, EMAIL_API, WEBHOOK, MESSENGER)
- Property encryption: secret properties encrypted at write, omitted from read responses
- Test-send per channel type
- Delete rejection when channel is assigned to a group (409)
- Parent table auto-refresh after dialog close (no page reload required)

### Recipient Group Management
Groups are the addressable unit for notification routing. Channel assignment/removal is the critical sub-operation.

- Create, read, update, delete recipient groups
- Auto-slug generation from name
- Assign channel to group, remove channel from group
- Channel count badge updates automatically after assignment changes
- Delete rejection when group is in active use (if applicable per schema)

### Notification Delivery
Core behavior — all configured channels in a group must be attempted; partial failures must not block remaining channels.

- Manual send via `/api/v1/notifications/send` produces a `NotificationLog` per channel
- Delivery continues to remaining channels when one channel fails
- `DeliveryStatus` correctly reflects DELIVERED vs FAILED per channel
- `SourceType` recorded correctly (`MANUAL`, `AGENT`, `SOP`)

### Channel Provider Implementations
Each provider has unique logic requiring independent coverage.

- **SMTP**: correct use of TLS, authentication credentials, from/to addressing
- **Email API**: correct SendGrid vs Mailgun payload format selection based on `provider_name`
- **Webhook**: correct HMAC-SHA256 signing when secret is present; unsigned when no secret
- **Messenger**: correct Teams adaptive card vs Slack Block Kit payload based on `platform`

### MCP Tool Integration
Agents invoke `send_notification` through the Communication Hub. This path bypasses the UI entirely.

- `send_notification` tool callable with `group_slug` and `body`
- Caller RBAC validated before dispatch
- `source_type=AGENT` recorded in `NotificationLog`
- Delivery summary returned to MCP caller
- Invalid `group_slug` returns an error (not a silent failure)

### Credential Encryption / Decryption
Secret channel properties must be encrypted at rest and decrypted only at dispatch time.

- Secret values encrypted before storage (CredentialVault.encrypt called)
- API read responses omit encrypted_value (only key + is_secret returned)
- Decryption occurs at dispatch time, not at read time
- Channel update re-encrypts updated secret values

### Delivery Tracking and Logging
Every dispatch attempt must be recorded with full metadata for audit.

- `NotificationLog` created for each channel per send operation
- Status, error detail, and metadata captured correctly
- `NotificationLogPage` displays paginated log entries
- Filtering by status, date range, group works correctly
- Log detail drawer shows full metadata on row click

### Error Handling and Retry Logic
System must be resilient to individual channel failures.

- Channel provider exception captured and logged as FAILED status
- Other channels in the group continue after one fails
- Error detail stored in `NotificationLog.error` field
- Test-send failure returns `success=false` with error message to admin

### Frontend UI Flows
All admin pages follow project conventions (Dialog Error Handling Standard, i18n, no hardcoded strings).

- All dialogs display errors inline (PermissionDeniedAlert) per Dialog Error Handling Standard
- Dialog errors cleared on open/close
- All UI text goes through `t()` (i18next)
- Loading states displayed during async operations
- Parent tables refresh automatically after dialog operations

### API Authentication and Authorization
All endpoints require a valid JWT. Management operations require `RT_NOTIFICATION` permission.

- Unauthenticated requests return 401
- Authenticated users without `RT_NOTIFICATION` permission return 403
- Valid JWT with correct permission succeeds
- Agent-sourced MCP tool calls validated via RBAC before dispatch

---

## 3. Critical Scenarios

### Channel Lifecycle

**WHEN** admin creates an SMTP channel with valid host, port, credentials, and TLS enabled  
**THEN** channel is saved, appears in the channel list, and all secret properties are omitted from the API response

**WHEN** admin sends a test message through a newly created channel  
**THEN** the test send returns `success=true` and the recipient receives the message (manual verification for live environments)

**WHEN** admin edits a channel to change the SMTP password  
**THEN** the new password is re-encrypted at rest and the channel list refreshes automatically without page reload

**WHEN** admin attempts to delete a channel that is assigned to one or more recipient groups  
**THEN** the API returns 409 Conflict and the channel remains in the list

**WHEN** admin deletes a channel that has no group assignments  
**THEN** the channel and all its ChannelProperty records are removed and the list updates automatically

### Recipient Group Lifecycle

**WHEN** admin creates a recipient group with a name  
**THEN** the slug is auto-derived from the name, the group appears in the list, and the channel count shows 0

**WHEN** admin assigns a channel to a recipient group  
**THEN** the channel count badge on the group increments and the channel appears in the group's assignment list

**WHEN** admin attempts to assign the same channel to a group a second time  
**THEN** the API returns 409 Conflict and the assignment count does not change

**WHEN** admin removes a channel from a recipient group  
**THEN** the channel count decrements and the channel no longer appears in the group's list

**WHEN** admin deletes a recipient group  
**THEN** all GroupChannelMapping records for that group are removed and the group disappears from the list

### Notification Sending — All Channel Types

**WHEN** a manual send is triggered to a group with one SMTP channel  
**THEN** one NotificationLog entry is created with status DELIVERED and the email is dispatched

**WHEN** a manual send is triggered to a group with one EMAIL_API channel configured for SendGrid  
**THEN** the SendGrid-formatted payload is sent and a NotificationLog entry records the outcome

**WHEN** a manual send is triggered to a group with one EMAIL_API channel configured for Mailgun  
**THEN** the Mailgun-formatted payload is sent and a NotificationLog entry records the outcome

**WHEN** a manual send is triggered to a group with one WEBHOOK channel and a secret configured  
**THEN** the HTTP request is signed with HMAC-SHA256 using the secret before sending

**WHEN** a manual send is triggered to a group with one WEBHOOK channel and no secret  
**THEN** the HTTP request is sent without any signature header

**WHEN** a manual send is triggered to a group with one MESSENGER channel configured for Teams  
**THEN** a Teams adaptive card payload is sent to the webhook URL

**WHEN** a manual send is triggered to a group with one MESSENGER channel configured for Slack  
**THEN** a Slack Block Kit payload is sent to the webhook URL

**WHEN** a manual send is triggered to a group with three channels and one channel fails  
**THEN** two NotificationLog entries show DELIVERED, one shows FAILED, and the response includes all three log IDs

### MCP Tool Invocation

**WHEN** an agent calls `send_notification` with a valid `group_slug` and `body`  
**THEN** `NotificationService.send_to_group` is called with `source_type=AGENT` and a delivery summary is returned

**WHEN** an agent calls `send_notification` with a `group_slug` that does not exist  
**THEN** the tool returns an error result and no NotificationLog is created

**WHEN** an agent without the required RBAC permission calls `send_notification`  
**THEN** the tool returns a permission denied error and no send is attempted

### Error Conditions

**WHEN** a channel provider raises an exception during dispatch (e.g., SMTP connection refused)  
**THEN** the NotificationLog for that channel records status FAILED with the error detail, and delivery proceeds to other channels

**WHEN** an admin attempts to create a channel with missing required properties (e.g., no smtp_host for SMTP)  
**THEN** the API returns 422 Unprocessable Entity with a validation error message

**WHEN** a test send is attempted on a channel with an unreachable host  
**THEN** the API returns `success=false` with an error description

**WHEN** CredentialVault fails to decrypt a channel property at dispatch time  
**THEN** dispatch is aborted for that channel, FAILED status is logged, and other channels continue

### Security / Authorization

**WHEN** an unauthenticated request is made to `GET /api/v1/notifications/channels`  
**THEN** the API returns 401 Unauthorized

**WHEN** an authenticated user without `RT_NOTIFICATION` permission calls `POST /api/v1/notifications/channels`  
**THEN** the API returns 403 Forbidden and no channel is created

**WHEN** a dialog operation fails with 403  
**THEN** the PermissionDeniedAlert is displayed inside the dialog (not silently swallowed)

**WHEN** admin reads a channel via `GET /api/v1/notifications/channels/{id}`  
**THEN** the response includes property keys and `is_secret` flags but never exposes encrypted_value

---

## 4. Edge Cases & Risks

### Invalid Channel Configuration
- Malformed SMTP host (non-resolvable hostname) — should fail gracefully at test-send, not at save
- Invalid port numbers (0, negative, >65535) — API validation must reject these
- API key containing special characters — must be encrypted/decrypted without corruption
- Webhook URL using HTTP instead of HTTPS — system should not enforce HTTPS but should log a warning

### Network Failures During Delivery
- Provider HTTP call times out — exception must be caught, logged as FAILED, other channels continue
- SMTP server closes connection mid-send — exception must be caught and logged
- DNS resolution failure for webhook URL — same failure pattern applies

### Recipient Group Configuration Issues
- Group with zero channel assignments — send still creates a NotificationLog with a note that no channels are configured; does not 500
- Group that becomes empty after channel deletion — send should handle gracefully

### Credential Encryption/Decryption Failures
- Encrypted value in database is corrupted or truncated — decryption must fail safely and log FAILED status rather than crashing the dispatch loop
- CredentialVault key rotated without re-encrypting stored properties — delivery fails with clear error

### Concurrent Notifications
- Two concurrent sends to the same group — each should produce independent NotificationLog sets; no shared state corruption
- High-volume sends exceeding provider rate limits — failures logged with provider error detail

### Missing or Revoked API Credentials
- Email API key revoked — provider returns 401/403 from external API; captured as FAILED status with error
- Webhook endpoint returns 4xx — captured as FAILED with HTTP status code in error detail
- SMTP password changed externally — authentication error captured and logged

---

## 5. Acceptance Criteria Checklist

| PRD Acceptance Criterion | Test Coverage |
|---|---|
| Admin can create, edit, and delete recipient groups with one or more notification channels | Integration: group CRUD + channel assignment endpoints; E2E: full group lifecycle flow |
| Admin can configure channel-specific settings for each channel type | Integration: channel CRUD for all 4 types with property verification; Unit: per-provider property mapping |
| SOP authors can select recipient groups and notification channels in agent workflows | MCP tool unit test: valid group_slug dispatches correctly |
| Agents can trigger notifications by calling a tool with recipient group and message content | MCP tool integration: `send_notification` handler produces NotificationLog with source_type=AGENT |
| Notifications are delivered to all configured channels for the selected group | Integration: send to multi-channel group verifies all channels attempted |
| Delivery status and audit logs available for all notifications sent | Integration: NotificationLog created per channel; E2E: log page shows entries after send |
| System enforces identity and permission checks for configuration and sending | Integration: 401/403 tests for all protected endpoints |
| If a channel fails, system logs the error and continues with other channels | Unit: NotificationService continues after provider exception; Integration: partial failure scenario |

---

## 6. Database Migration Requirements (CRITICAL)

Backend integration tests **must** satisfy the following requirements, which apply to this feature because it introduces new tables and columns:

### In Test Setup
- Run `alembic upgrade head` before the first test executes
- Verify migration applied: query `alembic_version` table to confirm the expected revision ID is current

### Schema Verification Tests
At least one integration test must query `information_schema` to confirm:
- `notification_channels` table exists with correct columns
- `channel_properties` table exists with `encrypted_value` column
- `recipient_groups` table exists with `slug` column (unique constraint)
- `group_channel_mappings` table exists with correct FK columns
- `notification_logs` table exists with `status`, `source_type`, `error`, `metadata` columns

### Constraint Violation Tests
- Attempt to insert a `GroupChannelMapping` with the same `(group_id, channel_id)` twice — must raise a unique constraint violation
- Attempt to insert a `RecipientGroup` with a duplicate `slug` — must raise a unique constraint violation
- Attempt to delete a `NotificationChannel` that is referenced by a `GroupChannelMapping` — must return 409 (enforced at service layer before delete)

---

## 7. E2E Real Backend Requirements (CRITICAL)

At least one E2E test suite must run against the real backend stack with **no `page.route()` mocks**. This catches migration issues and integration bugs that mocked tests cannot detect.

- **Label**: `test.describe('Real Backend Integration - Notifications')`
- **What it must cover**:
  - Create a notification channel via UI → verify it appears via `GET /api/v1/notifications/channels`
  - Create a recipient group → assign the channel → trigger a manual send
  - Verify the NotificationLog entry appears in the delivery log page
  - Delete the channel and group as cleanup
- **Why**: Mocked E2E tests would pass even if migrations were not applied or the backend router was misconfigured

---

## 8. Test File References

| Test Layer | File Path |
|---|---|
| Backend unit — NotificationService | [backend/tests/unit/test_notification_service.py](../../../../backend/tests/unit/test_notification_service.py) |
| Backend unit — Channel providers | [backend/tests/unit/test_notification_providers.py](../../../../backend/tests/unit/test_notification_providers.py) |
| Backend unit — DeliveryTracker | [backend/tests/unit/test_delivery_tracker.py](../../../../backend/tests/unit/test_delivery_tracker.py) |
| Backend unit — MCP tool | [backend/tests/unit/test_notification_mcp_tool.py](../../../../backend/tests/unit/test_notification_mcp_tool.py) |
| Backend integration — API endpoints | [backend/tests/integration/test_notification_api.py](../../../../backend/tests/integration/test_notification_api.py) |
| Frontend component — ChannelListPage | [frontend/src/__tests__/notifications/ChannelListPage.test.tsx](../../../../frontend/src/__tests__/notifications/ChannelListPage.test.tsx) |
| Frontend component — RecipientGroupListPage | [frontend/src/__tests__/notifications/RecipientGroupListPage.test.tsx](../../../../frontend/src/__tests__/notifications/RecipientGroupListPage.test.tsx) |
| Frontend component — NotificationLogPage | [frontend/src/__tests__/notifications/NotificationLogPage.test.tsx](../../../../frontend/src/__tests__/notifications/NotificationLogPage.test.tsx) |
| E2E — Channel management | [e2e/tests/notifications/channel-management.spec.ts](../../../../e2e/tests/notifications/channel-management.spec.ts) |
| E2E — Recipient group management | [e2e/tests/notifications/recipient-group-management.spec.ts](../../../../e2e/tests/notifications/recipient-group-management.spec.ts) |
| E2E — Notification sending | [e2e/tests/notifications/notification-sending.spec.ts](../../../../e2e/tests/notifications/notification-sending.spec.ts) |
| E2E — Real backend integration | [e2e/tests/notifications/real-backend-integration.spec.ts](../../../../e2e/tests/notifications/real-backend-integration.spec.ts) |
