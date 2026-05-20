# Demo Cases: implement-notifications
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/implement-notifications/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match describe + test name exactly with >) -->
- Notification Channel Management > create channel updates list without page reload
- Recipient Group Management > create group updates list without page reload
- Notification Log Page > clicking a log row opens the detail view
- Real Backend Integration - Notifications > notification channels endpoint returns 200

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Channel Management | Complete channel creation flow — user adds new notification channel, form submits, table updates without reload | channel-management.spec.ts | create channel updates list without page reload |
| 2 | Recipient Group Management | Complete group creation flow — user adds new recipient group, form submits, list updates without reload | recipient-group-management.spec.ts | create group updates list without page reload |
| 3 | Notification Logs | Log detail interaction — user clicks a log row and detail drawer opens showing full notification record | notification-sending.spec.ts | clicking a log row opens the detail view |
| 4 | API Integration (Real Backend) | Live backend contract validation — channels endpoint reachable, authenticated, and returns correct response | real-backend-integration.spec.ts | notification channels endpoint returns 200 |
