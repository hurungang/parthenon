# /test-app

Run Parthenon's test suite across all three test layers.

## Quick Reference

| Layer | Command (from project root) | Directory |
|-------|------|-----------|
| Backend unit/integration | `.venv/bin/python3 -m pytest backend/tests/ -v` | `backend/tests/` |
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
