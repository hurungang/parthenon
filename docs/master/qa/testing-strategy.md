# Testing Strategy: Parthenon Enterprise AI Harness

## Test Pyramid
- **Unit Tests**: Backend service logic, permission enforcement, skill composition (pytest). Frontend component rendering and state management (vitest).
- **Integration Tests**: REST API endpoints, MCP proxy round-trips, OIDC token flow.
- **End-to-End (E2E) Tests**: Full user journeys via Playwright browser automation covering all major UI flows.
- **Security Tests**: Auth boundary enforcement, permission isolation, credential leak prevention, max-instance enforcement.
- **Performance Tests**: Agent instance throughput, MCP tool call round-trip latency, Communication Hub message throughput under concurrent sessions.

## Test Layers
- **Backend (pytest)**: API endpoints, service logic, data model operations. Location: `backend/tests/`
- **Frontend (vitest)**: React component rendering, state, and user interaction. Location: `frontend/src/__tests__/`
- **E2E (Playwright)**: User journeys, cross-module flows, UI+backend integration. Location: `e2e/tests/`

## Critical Quality Gates
- 100% pass rate required for all test layers before release
- All PRD acceptance criteria must be mapped to at least one test scenario
- Edge cases and failure modes must be covered in test plans

## Test File Locations
- Backend: `backend/tests/`
- Frontend: `frontend/src/__tests__/`
- E2E: `e2e/tests/`

Refer to individual test plans for module-specific coverage and test file references.
