# Runbook: Super Admin Lockout

## Symptoms

- Cannot log in as super admin
- Login page shows "Super admin authentication failed" or "Super admin is disabled"
- `superadmin.login.failure` log events with `reason=disabled` or `reason=invalid_credentials`
- OIDC is also unavailable or misconfigured, so no alternative login path exists
- `SuperAdminDisabledLoginAttempt` alert firing (non-zero rate of login attempts to a disabled super admin)

---

## Resolution Steps

### 1. Re-enable Super Admin via Environment Variable (Escape Hatch)

If super admin is disabled in the database and OIDC is broken, use the environment variable override to re-enable it:

1. Set the environment variable `SUPER_ADMIN_ENABLED=true` in the Control Center service configuration.
2. Restart the Control Center service.
3. The BootstrapService will re-enable the super admin tier regardless of the database setting.

This is the escape hatch when both OIDC and the UI-based super admin toggle are unavailable.

### 2. Re-seed Super Admin Credentials via Environment Variables

If super admin credentials are unknown or corrupted:

1. Generate a fresh bcrypt hash of the desired password using any standard bcrypt tool.
2. Set the following environment variables in the Control Center service configuration:
   - `SUPER_ADMIN_USERNAME=<desired_username>`
   - `SUPER_ADMIN_PASSWORD_HASH=<bcrypt_hash>`
3. Restart the Control Center service.
4. On restart, the BootstrapService will seed these into the database, overwriting existing credentials.

### 3. Verify Login

After applying either or both of the above fixes:

1. Navigate to the Parthenon login page.
2. Use the super admin credentials to log in.
3. If login still fails, check `superadmin.login_failure` log events for the specific `reason`:
   - `reason=expired`: The session token expired — re-authenticate (super admin tokens have a configurable expiry, default 15 minutes).
   - `reason=invalid_credentials`: Username or password is incorrect; re-seed credentials via step 2.
   - `reason=disabled`: The environment variable override didn't take effect; verify `SUPER_ADMIN_ENABLED=true` was set correctly and restart again.

### 4. Secure the System

Once OIDC is working again:

1. Disable the super admin via the System Config UI to ensure all authentication flows through the identity provider in production.
2. Remove or unset the `SUPER_ADMIN_ENABLED` environment variable to restore normal database-driven behaviour.
3. If credentials were re-seeded, rotate the super admin password to a secure vault-managed value.

---

## Notes

- Super admin tokens are short-lived (configurable, default 15 minutes). This limits the window of abuse if credentials are compromised.
- Super admin login events are logged to `backend/logs/control-center.log`. Search for `superadmin.` to find all related events.
- The `SuperAdminBruteForce` alert fires when login failure rate exceeds 10/min for 5 minutes — treat this as critical and investigate immediately.
- The environment variable override (`SUPER_ADMIN_ENABLED=true`) is the only recovery path when both OIDC and the database-based super admin toggle are unavailable. Ensure this is documented and accessible to on-call engineers.
- Never log full super admin password hashes in logs or support tickets.
