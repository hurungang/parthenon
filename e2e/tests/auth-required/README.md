# Authentication-Required E2E Tests

This folder contains E2E tests that require **real Keycloak authentication** with test users. These tests are excluded from the default test run because they need additional setup and cannot use mocked authentication.

## Tests in This Folder

- **permission-errors.spec.ts** - Tests structured permission error messages across all pages
- **access-control.spec.ts** - Tests permission-denied snackbars, access request flows, and group-role assignments
- **auth.spec.ts** - Tests authentication flows (login, logout, redirects)
- **oidc-callback.spec.ts** - Tests OIDC callback handling
- **communication-hub-auth.spec.ts** - Tests OAuth enforcement for MCP hub
- **gateway.spec.ts** - Tests gateway configuration (requires auth)

## Why Separate?

These tests use the `loginViaUI()` helper which:
1. Navigates to the real Keycloak login page
2. Fills in credentials from environment variables
3. Completes the full OIDC authentication flow

This approach:
- ✅ Tests the complete real authentication flow
- ✅ Validates permission error handling with actual backend responses
- ❌ Requires Keycloak to be running
- ❌ Requires test user provisioning
- ❌ Slower than mocked tests (~6s per test for login)

## Running These Tests

### Option 1: Use the Automated Script (Recommended)

The `run-e2e-with-test-user.ps1` script handles everything:
- Creates a timestamped test user in Keycloak
- Sets environment variables
- Runs the tests
- Cleans up the test user

```powershell
# Run all auth-required tests
.\scripts\run-e2e-with-test-user.ps1 tests/auth-required

# Run specific test file
.\scripts\run-e2e-with-test-user.ps1 tests/auth-required/permission-errors.spec.ts
```

### Option 2: Manual Setup

1. **Ensure services are running:**
   ```powershell
   .\parthenon.ps1 start
   ```

2. **Create a test user:**
   ```powershell
   python scripts/provision-test-user.py create testuser testpass123
   ```

3. **Set environment variables:**
   ```powershell
   $env:E2E_TEST_USERNAME = "testuser"
   $env:E2E_TEST_PASSWORD = "testpass123"
   ```

4. **Run the tests:**
   ```powershell
   cd e2e
   npx playwright test tests/auth-required --config=playwright.dev.config.ts --workers=1
   ```

5. **Clean up the test user:**
   ```powershell
   python scripts/provision-test-user.py delete testuser
   ```

### Option 3: NPM Script

```powershell
# From e2e directory
npm run test:e2e:auth-required
```

## Test User Requirements

Test users created for these tests:
- **Username**: Environment variable `E2E_TEST_USERNAME` (default: "testuser")
- **Password**: Environment variable `E2E_TEST_PASSWORD` (default: "testuser")
- **Realm**: parthenon (user realm)
- **Permissions**: None (used to test permission-denied scenarios)
- **Email Verified**: true (required for Keycloak authentication to complete)

## Troubleshooting

### Tests timeout at Keycloak login page

**Cause**: Test user doesn't have `emailVerified: true`

**Solution**: Ensure test users are created with email verification:
```python
# In provision-test-user.py
payload = {
    "username": username,
    "enabled": True,
    "email": f"{username}@test.local",
    "emailVerified": True,  # Required!
    "firstName": "Test",
    "lastName": "User",
    "credentials": [...]
}
```

### Tests fail with "User not found"

**Cause**: Test user wasn't created or was deleted

**Solution**: Use the automated script which handles user lifecycle, or manually create the user before running tests.

### Keycloak redirect issues

**Cause**: Keycloak client redirect URIs don't include dev server port

**Solution**: Verify `parthenon-api-ui` client in Keycloak has these redirect URIs:
- `http://localhost:5173/*`
- `http://localhost:4173/*`
- `http://localhost/*`

## Performance

These tests are slower than mocked tests:
- **Login overhead**: ~6 seconds per test (Keycloak authentication flow)
- **Total for all auth tests**: ~5-8 minutes
- **Regular E2E tests**: ~15-20 minutes (no auth overhead)

This is why they're separate - run them when you need to validate authentication flows, not on every code change.
