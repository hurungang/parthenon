# /test-app

Run Parthenon's test suite across all three test layers.

## Quick Reference

| Layer | Command (from project root) | Directory |
|-------|------|-----------|
| Backend unit/integration | `.venv/bin/python -m pytest backend/tests/ -v` | `backend/tests/` |
| Frontend component | `npx vitest run src/__tests__/ --reporter=verbose` (from `frontend/`) | `frontend/src/__tests__/` |
| E2E | `npm test` (from `e2e/`) | `e2e/tests/` |

## Flags

- `--backend` — Run only backend tests (pytest)
- `--frontend` — Run only frontend tests (vitest)
- `--e2e` — Run only E2E tests (playwright)
- `--filter <pattern>` — Filter tests by name across ALL three layers
  - Backend: `pytest -k <pattern>`
  - Frontend: `vitest run --reporter=verbose` + grep test names
  - E2E: `playwright test --grep <pattern>`
- `--filter <pattern> --backend` — Filter only backend tests
- `--filter <pattern> --frontend` — Filter only frontend tests
- `--filter <pattern> --e2e` — Filter only E2E tests

⚠️ `--filter` alone (no layer flag) runs across **all 3 layers** with the filter.

## Multi-Tenant E2E Notes

- The multi-tenant E2E suites (`single-tenant-regression`, `multi-tenant-lifecycle`, `multi-tenant-login-flows`, `self-serve-signup`, `quota-enforcement`) are fully **mocked — no backend or live stack needed**.
- `multi-tenant-isolation.real-backend.spec.ts` and `self-serve-signup.real-backend.spec.ts` require a live running stack and **auto-skip** when the backend is not up (no failure).
- `system-one-real-backend.spec.ts` (`Real Backend Integration - Decision Tools`) also requires a live stack (backend on :8000 + Postgres + migrations applied); it registers/logs into two real tenants, authors identical `tool_a` decision tools in both (tenant containment), executes via the real internal `decision:` path with a local stub TypeSafe server (no external API calls), and verifies persistence via psql. Uses the persistent E2E account pattern (`e2e-ds-persistent@e2e.test`; registration is rate-limited to 10/hour/IP). Auto-skips when the backend is not up.

## Pre-Test Checklist

- If `has_db_changes` is true for recent changes:
  1. Verify migration: `python -m alembic current` in `backend/`
  2. If not at head: `python -m alembic upgrade head`
- Docker must be running for integration tests (PostgreSQL)

## Reporting

After tests run, summarize:
```
Backend:  N passed / M total  (N%)
Frontend: N passed / M total  (N%)
E2E:      N passed / M total  (N%)
```
If any failures, show the failing test names and suggest debugging steps.

## Frontend Test Report (if vitest fails to output)

If vitest produces no visible output, run with JSON reporter:
```powershell
cd frontend
npx vitest run --reporter=json --outputFile=vitest_results.json
$j = Get-Content vitest_results.json | ConvertFrom-Json
Write-Host "Passed: $($j.numPassedTests) / $($j.numTotalTests)"
```
macOS/Linux equivalent:
```bash
cd frontend && npx vitest run --reporter=json --outputFile=vitest_results.json && cat vitest_results.json | python3 -c "import json,sys; j=json.load(sys.stdin); print(f\"Passed: {j['numPassedTests']} / {j['numTotalTests']}\")"
```
