# Run E2E tests with dynamically provisioned test user
# Usage:
#   .\scripts\run-e2e-with-test-user.ps1
#   .\scripts\run-e2e-with-test-user.ps1 tests/permission-errors.spec.ts

param(
    [string]$TestFile = "",
    [string]$Config = "playwright.dev.config.ts"
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== E2E Test with Dynamic Test User ===" -ForegroundColor Cyan

# Step 1: Create timestamped test user
Write-Host "`n[1/4] Creating timestamped test user..." -ForegroundColor Yellow
$timestamp = [DateTimeOffset]::Now.ToUnixTimeSeconds()
$testUsername = "testuser_$timestamp"
$testPassword = "testpass123"

try {
    python scripts/provision-test-user.py create $testUsername $testPassword
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create test user"
    }
    Write-Host "✓ Test user created: $testUsername" -ForegroundColor Green
}
catch {
    Write-Host "✗ Failed to provision test user: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Set environment variables for tests
Write-Host "`n[2/4] Setting test environment variables..." -ForegroundColor Yellow
$env:E2E_TEST_USERNAME = $testUsername
$env:E2E_TEST_PASSWORD = $testPassword
Write-Host "  E2E_TEST_USERNAME=$testUsername"
Write-Host "  E2E_TEST_PASSWORD=$testPassword"

# Step 3: Run E2E tests
Write-Host "`n[3/4] Running E2E tests..." -ForegroundColor Yellow
Set-Location e2e

try {
    if ($TestFile) {
        Write-Host "  Running: $TestFile" -ForegroundColor Cyan
        npx playwright test $TestFile --config=$Config --workers=1
    }
    else {
        Write-Host "  Running: all tests" -ForegroundColor Cyan
        npx playwright test --config=$Config --workers=1
    }
    $testExitCode = $LASTEXITCODE
}
catch {
    $testExitCode = 1
    Write-Host "✗ Test execution failed: $_" -ForegroundColor Red
}
finally {
    Set-Location ..
}

# Step 4: Cleanup - Delete test user
Write-Host "`n[4/4] Cleaning up test user..." -ForegroundColor Yellow
try {
    python scripts/provision-test-user.py delete $testUsername
    Write-Host "✓ Test user deleted: $testUsername" -ForegroundColor Green
}
catch {
    Write-Host "⚠ Warning: Failed to delete test user: $_" -ForegroundColor Yellow
}

# Report results
Write-Host "`n=== Test Results ===" -ForegroundColor Cyan
if ($testExitCode -eq 0) {
    Write-Host "✓ All tests passed" -ForegroundColor Green
}
else {
    Write-Host "✗ Some tests failed (exit code: $testExitCode)" -ForegroundColor Red
}

exit $testExitCode
