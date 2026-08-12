# Test Plan: Agent-to-Agent Communication and Slug Enforcement

## Test Strategy
- Unit tests
  - Validate permission decisions, slug validation logic, and lifecycle state transitions in isolation.
- Backend integration tests
  - Verify Communication Hub and Agent Runtime behavior for target resolution, dynamic receiver creation, session continuity, and cleanup.
- Frontend component tests
  - Verify existing SOP editor delegation step behavior, derived permission outputs, slug validation errors, role allowed-agent-type preview rendering, and plan/diagram delegation rendering.
- E2E tests
  - Validate end-to-end A2A behavior with real request/response flows and disconnect cleanup.
- Manual exploratory checks
  - Confirm existing SOP editor workflow remains unchanged while delegation-driven permissions and previews are updated correctly.

## Coverage Areas
- A2A routing and fallback provisioning
  - Request with available target vs unavailable target.
- Permission enforcement
  - SOP allow-list is derived from delegation steps and accepts only explicit target agent type slugs from those steps.
- Shared-session continuity
  - Multi-turn requester-receiver exchange remains in same session.
- Disconnect cleanup
  - Dynamic receiver lifecycle completes and instances are removed.
- Slug validation consistency
  - Agent type, agent name, and MCP server name reject non-slug input.
- Role preview visibility
  - Agent role edit dialog shows accurate allowed agent type slug list.
- Agent step preview rendering
  - Plan list and topology diagram both render agent-delegation steps.

## Critical Scenarios
- WHEN requester sends A2A call with allowed target slug and target is available THEN request routes successfully and response returns in same session.
- WHEN requester sends A2A call with allowed target slug and target is unavailable THEN runtime creates dynamic receiver, session link is established, and conversation continues.
- WHEN requester sends A2A call with target slug not in SOP allow-list THEN request is denied with explicit permission error and no runtime provisioning occurs.
- WHEN SOP author saves an SOP with delegation steps THEN target agent associations and A2A permissions are generated from those steps.
- WHEN requester finishes A2A conversation and sends disconnect THEN dynamic receiver is removed and link state is closed.
- WHEN admin enters non-slug value for agent type name THEN create/update is rejected with validation error.
- WHEN admin enters non-slug value for agent name THEN create/update is rejected with validation error.
- WHEN admin enters non-slug value for MCP server name THEN create/update is rejected with validation error.
- WHEN admin edits an agent role THEN allowed agent type slug preview displays all currently allowed slugs.
- WHEN plan preview is opened THEN delegation steps appear in ordered plan output and topology diagram output.

## Edge Cases & Risks
- Concurrent A2A requests to same unavailable target causing duplicate dynamic receiver creation.
- Partial failures during disconnect cleanup leaving orphaned instance or session-link state.
- Stale permission cache causing incorrect allow/deny decision.
- Backward compatibility for SOPs created before A2A permission fields existed.
- UI validation mismatch between client checks and backend authoritative slug validation.
- Race conditions where target becomes available during runtime fallback creation.

## Acceptance Criteria Checklist
- [ ] A2A requests use target agent type slug and route through Communication Hub.
- [ ] Runtime auto-creates dynamic receiver when target agent is unavailable.
- [ ] Requester and receiver share one session through full multi-turn A2A conversation.
- [ ] Disconnect action removes dynamic receiver and clears session-link state.
- [ ] SOP delegation steps generate and control allowed target agent type slugs for A2A.
- [ ] Agent role dialog shows allowed agent type slug preview.
- [ ] Existing SOP editor flow is retained (no structural UI rewrite required).
- [ ] Plan list and topology diagram both render agent-delegation steps.
- [ ] Non-slug values are rejected in agent type, agent name, and MCP server naming flows.

## Test File References
- Backend tests
  - `backend/tests/unit/test_permission_manager.py`
  - `backend/tests/integration/` (new or updated A2A lifecycle integration tests)
- Frontend tests
  - `frontend/src/__tests__/SopEditor.test.tsx`
  - `frontend/src/__tests__/PlanPreviewModal.test.tsx`
  - `frontend/src/__tests__/` (new or updated tests for slug validation and role preview)
- E2E tests
  - `e2e/tests/` (new A2A lifecycle and permission scenarios)
- Supporting integration checks
  - `mcp-demo-app/tests/` (if end-to-end simulation coverage is extended)
