# Configurable Telemetry System — Test Plan

## Test Strategy

Testing will cover all layers (backend unit, backend API integration, frontend unit, E2E) to ensure the telemetry system is configurable via file and environment variables, supports multiple export targets, and exposes correct controls and error handling. Tests will validate configuration loading, runtime behavior, and API exposure, with a focus on both expected and edge-case scenarios. Each test layer will reference the appropriate test directories as defined in docs/config.yaml.

## Coverage Areas

- Telemetry config loading (file, env vars)
- Export target selection (console, file, OTEL, Logfire, custom)
- Signal controls (enable/disable traces, metrics, logs)
- Log level configuration
- Frontend telemetry config API endpoint
- Error handling (invalid config, missing exporters)
- Default behaviors (absent config, partial config)

## Critical Scenarios (WHEN/THEN)

1. **WHEN** the backend starts with a valid config file  
   **THEN** the telemetry system initializes with the specified exporters and signal controls.

2. **WHEN** environment variables override config file values  
   **THEN** the system uses the environment values for exporters and signal toggles.

3. **WHEN** only traces are enabled in config  
   **THEN** only trace data is exported; metrics and logs are not.

4. **WHEN** an invalid exporter is specified  
   **THEN** the system logs an error and falls back to default/no exporter.

5. **WHEN** the frontend requests the telemetry config API endpoint  
   **THEN** it receives the current effective configuration.

6. **WHEN** the config file is missing  
   **THEN** the system uses documented defaults and logs a warning.

7. **WHEN** log level is set to "debug"  
   **THEN** debug logs are emitted for telemetry initialization and export.

8. **WHEN** a required exporter dependency is missing  
   **THEN** the system disables that exporter and logs a clear error.

9. **WHEN** multiple exporters are configured (console + OTLP)  
   **THEN** telemetry data is sent to both targets simultaneously.

10. **WHEN** the frontend fetches telemetry config but the backend API fails  
    **THEN** the frontend uses safe defaults and continues initialization.

## Edge Cases

- Config file is empty or malformed YAML
- Multiple exporters specified, one fails to initialize
- Signal controls set to invalid values (e.g., non-boolean)
- API endpoint returns partial config due to missing values
- Exporter endpoint unreachable at startup/runtime
- Frontend calls telemetry config API before authentication
- Env var overrides with invalid type (string instead of boolean)
- Log level name case sensitivity (INFO vs info)
- File exporter path doesn't exist (should be created)
- File exporter disk full during rotation

## Acceptance Criteria Checklist

- [ ] Telemetry config loads from file and environment variables
- [ ] Export target selection works for all supported exporters (console, file, OTLP, Logfire, custom)
- [ ] Signal controls (traces, metrics, logs) enable/disable correctly
- [ ] Log level configuration is respected for all components
- [ ] Frontend API endpoint returns current config
- [ ] System handles invalid/missing config gracefully
- [ ] Defaults are applied when config is absent
- [ ] Errors are logged for invalid exporters or missing dependencies
- [ ] Multiple simultaneous exporters work correctly
- [ ] Frontend degrades gracefully when backend config fetch fails

## Test File References

| Coverage Area                     | Test Layer                | Test File(s) (from workspace root)                          |
|-----------------------------------|---------------------------|-------------------------------------------------------------|
| Config loading                    | Backend unit              | backend/tests/core/test_telemetry_config.py                  |
| Export target selection           | Backend unit              | backend/tests/core/test_telemetry.py                         |
| Signal controls                   | Backend unit              | backend/tests/core/test_telemetry.py                         |
| Log level config                  | Backend unit              | backend/tests/core/test_telemetry_config.py                  |
| Exporter factory (all types)      | Backend unit              | backend/tests/core/test_telemetry.py                         |
| API endpoint authentication       | Backend API               | backend/tests/api/test_telemetry.py                          |
| API endpoint schema validation    | Backend API               | backend/tests/api/test_telemetry.py                          |
| Frontend config fetch             | Frontend unit             | frontend/src/__tests__/telemetry.test.ts                     |
| Frontend init with config         | Frontend unit             | frontend/src/__tests__/telemetry.test.ts                     |
| Frontend graceful degradation     | Frontend unit             | frontend/src/__tests__/telemetry.test.ts                     |
| Error handling                    | Backend unit, Frontend    | backend/tests/core/test_telemetry.py, frontend/src/__tests__/telemetry.test.ts |
| Defaults behavior                 | Backend unit              | backend/tests/core/test_telemetry_config.py                  |
| E2E telemetry validation          | E2E (optional)            | e2e/tests/observability.spec.ts                              |

---

## Test Implementation Notes

### Backend Unit Tests (`backend/tests/core/`)

**test_telemetry_config.py:**
- Test `TelemetrySettings` default instantiation
- Test env var overrides for all fields
- Test validation errors (invalid log levels, invalid exporter types)
- Test nested exporter option models
- Test log levels map parsing

**test_telemetry.py:**
- Test `ExporterFactory` builds console exporters correctly
- Test `ExporterFactory` builds file exporters with rotation
- Test `ExporterFactory` builds OTLP exporters (gRPC and HTTP)
- Test `ExporterFactory` builds Logfire exporters (with/without token)
- Test `ExporterFactory` builds custom endpoint exporters
- Test signal disable flags produce no-op providers
- Test multi-target config produces multiple processors
- Test `setup_telemetry()` applies log levels correctly

### Backend API Tests (`backend/tests/api/`)

**test_telemetry.py:**
- Test `GET /api/v1/telemetry/config` with valid JWT returns 200 and correct schema
- Test `GET /api/v1/telemetry/config` without JWT returns 401
- Test response matches `FrontendTelemetryConfigSchema` structure
- Test no credentials/secrets in response

### Frontend Unit Tests (`frontend/src/__tests__/`)

**telemetry.test.ts:**
- Test `fetchTelemetryConfig()` success returns typed config
- Test `fetchTelemetryConfig()` network failure returns safe defaults
- Test `initTelemetry()` with `traces_enabled: true` registers OTEL providers
- Test `initTelemetry()` with `traces_enabled: false` skips provider registration
- Test `initTelemetry()` with `metrics_enabled: true` records Web Vitals
- Test `initTelemetry()` with `metrics_enabled: false` skips Web Vitals

### E2E Tests (`e2e/tests/`)

**observability.spec.ts** — Verifies telemetry system integration without breaking app functionality

**E2E Scenario 1: App Startup with Telemetry Enabled**
- **WHEN** the user navigates to the app with telemetry fully enabled in backend config
- **THEN** the app loads successfully without console errors
- **AND** the dashboard page renders correctly
- **AND** no telemetry-related errors appear in browser console

**E2E Scenario 2: Telemetry Config API Access**
- **WHEN** a logged-in user makes a request to view observability settings (simulated by test)
- **THEN** the frontend successfully fetches telemetry config from `/api/v1/telemetry/config`
- **AND** the response contains valid `service_name`, `otlp_http_endpoint`, `traces_enabled`, `metrics_enabled`
- **AND** no credentials or sensitive data are exposed in the response

**E2E Scenario 3: App Startup with Telemetry Disabled**
- **WHEN** the backend telemetry is disabled (`traces_enabled: false`, `metrics_enabled: false`)
- **THEN** the app still loads and functions normally
- **AND** the dashboard renders without errors
- **AND** no OTEL providers are initialized in the browser (verify via console)

**E2E Scenario 4: Graceful Degradation on Telemetry Failure**
- **WHEN** the telemetry config API endpoint returns 500 error
- **THEN** the app continues to load and render
- **AND** the frontend falls back to safe defaults (telemetry disabled)
- **AND** the user can navigate and use the app normally

---

## Coverage Targets

- Backend unit test coverage: ≥90% for `telemetry.py` and `config.py` telemetry-related code
- Frontend unit test coverage: ≥85% for `telemetry.ts` and `telemetryApi.ts`
- All API endpoints: 100% coverage (both success and error paths)
- E2E: At least one smoke test verifying observability doesn't block app startup
