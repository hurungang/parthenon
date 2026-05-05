# Testing Strategy: Parthenon Enterprise AI Harness

## Test Pyramid
- **Unit Tests**: Backend service logic, permission enforcement, skill composition (pytest). Frontend component rendering and state management (vitest).
- **Integration Tests**: REST API endpoints, MCP proxy round-trips, OIDC token flow. Database schema migration verification against real PostgreSQL.
- **End-to-End (E2E) Tests**: Full user journeys via Playwright browser automation covering all major UI flows.
- **Security Tests**: Auth boundary enforcement, permission isolation, credential leak prevention, max-instance enforcement.
- **Performance Tests**: Agent instance throughput, MCP tool call round-trip latency, Communication Hub message throughput under concurrent sessions.

## Test Layers
- **Backend (pytest)**: API endpoints, service logic, data model operations. Location: `backend/tests/`
- **Frontend (vitest)**: React component rendering, state, and user interaction. Location: `frontend/src/__tests__/`
- **E2E (Playwright)**: User journeys, cross-module flows, UI+backend integration. Location: `e2e/tests/`

## Database Migration Testing Requirements

Changes that include database schema changes (`has_db_changes: true`) require additional verification:

**Pre-test checklist (must be confirmed before running any tests):**
1. Alembic migration generated and committed
2. `alembic upgrade head` applied locally — verify with `alembic current`
3. Test database fixture applies migrations via `alembic upgrade head` in setup

**Backend integration tests must:**
- Run against a real PostgreSQL database (not in-memory mocks)
- Verify schema changes took effect by querying `information_schema.columns`
- Include negative tests for constraint violations (e.g., rejected legacy enum values)
- Test nullable column acceptance and non-nullable constraint enforcement

**E2E tests for database changes must include:**
- At least one `test.describe('Real Backend Integration - ...')` block per domain area that hits the running backend without `page.route()` mocking
- This catches migration issues that purely mocked tests cannot detect

## Frontend Component Test Infrastructure

Some complex components using React Query + MSW in the Vitest environment require workaround test files (`*.simple.test.tsx`, `*.minimal.test.tsx`). These cover core rendering assertions. Full CRUD coverage for affected components is provided by E2E tests. This is an infrastructure limitation, not an implementation defect.

## Critical Quality Gates
- 100% pass rate required for all test layers before release
- All PRD acceptance criteria must be mapped to at least one test scenario
- Edge cases and failure modes must be covered in test plans
- For changes with DB schema changes: at least one real-backend E2E test must pass before deployment

## Test File Locations
- Backend: `backend/tests/`
- Frontend: `frontend/src/__tests__/`
- E2E: `e2e/tests/`

Refer to individual test plans for module-specific coverage and test file references.
