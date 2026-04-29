# Test Plan: Keycloak Identity Bootstrap

## 1. Test Strategy

The testing approach for the Keycloak Identity Bootstrap feature will ensure comprehensive coverage across all layers:

- **Backend (pytest):** Unit and integration tests for YAML loader, DB models, identity bootstrap service, and API endpoints. Focus on logic, error handling, and persistence.
- **Frontend (Vitest):** Component and integration tests for the multi-step setup wizard, including rendering, validation, navigation, and error states.
- **End-to-End (Playwright):** Full user journey tests simulating first-run setup, error flows, and configuration persistence. All API calls are mocked; no live Keycloak or DB required.

All features must have tests in all three layers. 100% pass rate is required.

---

## 2. Coverage Areas

- **YAML Config Loader:** Reads and merges config/identity.yaml with environment variable overrides.
- **Identity Bootstrap Service:** Provisions bundled Keycloak or validates external OIDC provider; writes config and updates DB state.
- **API Endpoints:**
  - `GET /setup/identity-status` (unauthenticated)
  - `POST /setup/identity` (unauthenticated)
- **CLI Entrypoint:** `python -m app.cli setup-identity` for non-interactive setup.
- **DB Models:** IdentityProviderConfig, IdentityProviderSetupState, User.idp_subject.
- **Frontend Setup Wizard:** 5-step React wizard for identity provider setup, including validation and error handling.
- **Infrastructure:** Docker Compose Keycloak service, start/stop scripts.

---

## 3. Critical Scenarios

1. **WHEN** the system is unconfigured and `/setup/identity-status` is called, **THEN** it returns `is_configured: false`.
2. **WHEN** the system is configured and `/setup/identity-status` is called, **THEN** it returns `is_configured: true`.
3. **WHEN** the user completes the wizard with bundled Keycloak selected, **THEN** Keycloak is provisioned and the config is persisted.
4. **WHEN** the user provides valid external OIDC provider details, **THEN** the setup completes and config is persisted.
5. **WHEN** the user provides an invalid or unreachable provider URL, **THEN** the setup fails with an appropriate error message.
6. **WHEN** the admin password and confirmation do not match in the wizard, **THEN** the wizard blocks progression and shows a validation error.
7. **WHEN** required fields are missing in any wizard step, **THEN** the wizard prevents submission and displays validation errors.
8. **WHEN** setup completes, **THEN** the YAML config is written with the correct values and DB state is updated.
9. **WHEN** an environment variable overrides a YAML config value, **THEN** the override is reflected in the running config.
10. **WHEN** the CLI setup command is run with valid parameters, **THEN** setup completes successfully and updates config/DB.
11. **WHEN** a setup attempt is made after the system is already configured, **THEN** the API rejects the attempt with an error.

---

## 4. Edge Cases

1. **WHEN** the YAML config file is missing or unreadable, **THEN** the loader fails gracefully and logs an error.
2. **WHEN** the DB is unreachable during setup, **THEN** the bootstrap service returns a clear error and does not proceed.
3. **WHEN** the Keycloak Admin REST API returns a non-200 response, **THEN** the setup fails with a descriptive error.
4. **WHEN** the wizard is refreshed mid-setup, **THEN** the state is preserved or the user is redirected appropriately.
5. **WHEN** multiple users attempt setup concurrently, **THEN** only one succeeds and others receive a conflict error.

---

## 5. Acceptance Criteria Checklist

| PRD Acceptance Criterion                                      | Test Scenario Reference |
|--------------------------------------------------------------|------------------------|
| First-run detection works (configured/unconfigured)           | 1, 2                  |
| Bundled Keycloak can be provisioned via wizard or CLI         | 3, 10                 |
| External OIDC provider can be validated and saved             | 4                     |
| Invalid/unreachable provider is rejected                      | 5                     |
| Wizard enforces password match and required fields            | 6, 7                  |
| YAML config is written and DB updated after setup             | 8                     |
| Env var overrides YAML config                                 | 9                     |
| CLI setup works as expected                                   | 10                    |
| Duplicate setup attempts are rejected                         | 11                    |
| Handles missing YAML, DB, or Keycloak errors gracefully       | Edge 1, 2, 3          |
| Wizard state is robust to refresh                             | Edge 4                |
| Concurrent setup attempts are handled safely                  | Edge 5                |

---

## 6. Test File References

| Layer     | Area                        | Test File Path                                             |
|-----------|-----------------------------|------------------------------------------------------------|
| Backend   | YAML Loader                 | backend/tests/test_config_loader.py                        |
| Backend   | DB Models                   | backend/tests/test_models_identity.py                      |
| Backend   | Bootstrap Service           | backend/tests/test_identity_bootstrap_service.py           |
| Backend   | API Endpoints               | backend/tests/test_api_setup_identity.py                   |
| Backend   | CLI Entrypoint              | backend/tests/test_cli_setup_identity.py                   |
| Frontend  | Setup Wizard (all steps)    | frontend/src/__tests__/SetupWizard.test.tsx                |
| Frontend  | Wizard Step Validation      | frontend/src/__tests__/SetupWizardValidation.test.tsx      |
| E2E       | First-run Setup Journey     | e2e/tests/setup-wizard-first-run.spec.ts                   |
| E2E       | Bundled Keycloak Provision  | e2e/tests/setup-wizard-keycloak.spec.ts                    |
| E2E       | External OIDC Provider      | e2e/tests/setup-wizard-external-oidc.spec.ts               |
| E2E       | Error/Edge Flows            | e2e/tests/setup-wizard-errors.spec.ts                      |

---

**Note:** All test files must be implemented and referenced here. Update this table as new files are added or renamed.
