# Implementation Plan: configurable-telemetry-system

## Overview

Replace the hardcoded single-target OTEL initialisation in both backend and frontend with a config-driven system that supports multiple simultaneous export targets, per-signal enable/disable flags, and configurable log levels. The backend resolves `TelemetrySettings` from environment variables (with YAML file fallback), exposes a lightweight config endpoint for the frontend, and registers an `ExporterFactory` that wires the resolved config into the OTEL SDK at startup.

---

## Task Checklist

### Phase 1 — Backend Configuration Schema

- [x] 1.1 — Define `TelemetryExporterType` enum and per-exporter option models (`OtlpExporterOptions`, `FileExporterOptions`, `LogfireExporterOptions`, `CustomExporterOptions`) in `backend/app/core/config.py` — _Done when: all exporter option types are strongly typed Pydantic models with defaults_
- [x] 1.2 — Define `TelemetrySettings` Pydantic `BaseModel` embedding the exporter option models, signal enable flags, and per-component log level map — _Done when: model instantiates from env vars and from explicit kwargs with all fields validated_
- [x] 1.3 — Embed `TelemetrySettings` as a nested field in the `Settings` class, replacing the existing flat `otel_*` fields — _Done when: `get_settings().telemetry` returns a populated `TelemetrySettings`; existing `main.py` call site still works after update_

### Phase 2 — Backend Exporter Factory

- [x] 2.1 — Refactor `setup_telemetry()` in `backend/app/core/telemetry.py` to accept `TelemetrySettings` instead of individual primitive parameters — _Done when: function signature updated; `main.py` passes `settings.telemetry`; existing no-op disabled path preserved_
- [x] 2.2 — Implement `ExporterFactory` class in `backend/app/core/telemetry.py` with a Console exporter builder for traces, metrics, and logs — _Done when: console target produces `ConsoleSpanExporter`, `ConsoleMetricExporter`, and `ConsoleLogExporter` registered in providers_
- [x] 2.3 — Add File exporter builder to `ExporterFactory` using `RotatingFileHandler` for logs and a file-backed span/metric exporter — _Done when: file target writes OTEL data to configured path with rotation limits; missing directory is created automatically_
- [x] 2.4 — Add OTLP exporter builder to `ExporterFactory` supporting both HTTP and gRPC protocols — _Done when: `protocol=grpc` produces `OTLPSpanExporter` (gRPC); `protocol=http` produces `OTLPSpanExporter` (HTTP); existing default behavior (gRPC to `http://localhost:4317`) is preserved_
- [x] 2.5 — Add Logfire exporter builder to `ExporterFactory` — _Done when: logfire target instantiates the Logfire OTEL exporter when a token is provided; skipped with a warning log when token is absent_
- [x] 2.6 — Add custom-endpoint exporter builder to `ExporterFactory` using OTLP HTTP to the configured URL — _Done when: custom target sends spans/metrics/logs to the supplied endpoint URL_
- [x] 2.7 — Apply signal enable flags in `ExporterFactory`: disabled signals register no-op providers — _Done when: `traces_enabled=False` installs `NonRecordingTracer`; `metrics_enabled=False` installs no-op `MeterProvider`; `logs_enabled=False` skips `LoggerProvider` registration_
- [x] 2.8 — Apply per-component log levels from `TelemetrySettings.log_levels` map at end of `setup_telemetry()` — _Done when: root logger and named component loggers have levels set from config; unset components keep their defaults_

### Phase 3 — Backend Telemetry Config API

- [x] 3.1 — Define `FrontendTelemetryConfigSchema` response Pydantic model in `backend/app/schemas/` covering: `otlp_http_endpoint`, `service_name`, `traces_enabled`, `metrics_enabled` — _Done when: schema exports correctly; no credential fields included_
- [x] 3.2 — Create `backend/app/api/v1/telemetry.py` with `GET /telemetry/config` handler that returns the frontend-relevant subset of `TelemetrySettings` — _Done when: endpoint returns 200 with `FrontendTelemetryConfigSchema`; requires JWT auth_
- [x] 3.3 — Register `TelemetryRouter` in `backend/app/api/v1/__init__.py` — _Done when: route appears in OpenAPI docs at `/api/v1/telemetry/config`_

### Phase 4 — Frontend Config-Driven Initialisation

- [x] 4.1 — Add `fetchTelemetryConfig()` function to `frontend/src/api/` that calls `GET /api/v1/telemetry/config` and returns a typed `FrontendTelemetryConfig` interface — _Done when: function compiles; returns typed object; network failure returns safe default (traces disabled)_
- [x] 4.2 — Refactor `initTelemetry()` in `frontend/src/telemetry.ts` to accept `FrontendTelemetryConfig` as a parameter, replacing hardcoded env-var reads — _Done when: OTLP exporter URL and service name come from the passed config; trace registration skipped when `traces_enabled=false`_
- [x] 4.3 — Update the telemetry bootstrap call in `frontend/src/main.tsx` to fetch config from the backend before calling `initTelemetry()` — _Done when: app fetches config on startup; telemetry init receives live config; fetch failure degrades gracefully without crashing the app_

### Phase 5 — Tests

- [x] 5.1 — Write unit tests for `TelemetrySettings` covering: defaults, env-var override, validation errors for invalid log level strings — _Done when: pytest passes; all field defaults and env overrides verified_
- [x] 5.2 — Write unit tests for `ExporterFactory` covering: each exporter type built correctly, no-op providers for disabled signals, multi-target config produces multiple processors — _Done when: pytest passes; OTEL provider mocks confirm correct exporter types registered_
- [x] 5.3 — Write API test for `GET /api/v1/telemetry/config` — authenticated request returns correct schema; unauthenticated returns 401 — _Done when: pytest passes with both scenarios_
- [x] 5.4 — Write frontend unit tests for `initTelemetry()` with mocked `FrontendTelemetryConfig`: traces enabled path, traces disabled path, fetch-failure graceful degradation — _Done when: vitest passes for all three scenarios_

### Phase 6 — Sample Config & Environment Documentation

- [x] 6.1 — Create `config/telemetry.yaml` sample configuration file documenting all supported fields and export targets with inline comments — _Done when: file is valid YAML; covers all `TelemetrySettings` fields; includes examples for each exporter type_
- [x] 6.2 — Add all new `OTEL_*` environment variable names and descriptions to the project `.env.example` or equivalent reference — _Done when: every new env var is documented with type, default, and example value_

---

## Phase 1 — Backend Configuration Schema

### 1.1 — Exporter option models

Define strongly typed Pydantic models for each exporter's parameters. Keep them as `BaseModel` sub-models (not `BaseSettings`) so they nest cleanly inside `Settings`.

- `OtlpExporterOptions`: `endpoint: str`, `protocol: Literal["grpc", "http"]`, `insecure: bool`
- `FileExporterOptions`: `path: str`, `max_bytes: int`, `backup_count: int`
- `LogfireExporterOptions`: `token: str | None`
- `CustomExporterOptions`: `endpoint: str`
- `TelemetryExporterType`: string enum — `console`, `file`, `otlp`, `logfire`, `custom`

**Done when:** Each model has typed fields with sensible defaults; models can be imported and instantiated independently.

### 1.2 — TelemetrySettings model

Central model that drives all initialisation decisions:
- `exporters: list[TelemetryExporterType]` — which export targets are active
- `traces_enabled: bool` / `metrics_enabled: bool` / `logs_enabled: bool`
- `otlp: OtlpExporterOptions`
- `file: FileExporterOptions`
- `logfire: LogfireExporterOptions`
- `custom: CustomExporterOptions`
- `log_levels: dict[str, str]` — component name → level string (e.g. `{"root": "INFO", "app.services": "DEBUG"}`)
- `service_name: str`

**Done when:** `TelemetrySettings()` resolves from defaults; each field overridable via env vars.

### 1.3 — Embed in Settings

Replace the existing flat `otel_exporter_otlp_endpoint`, `otel_service_name`, and `otel_enabled` fields in `Settings` with `telemetry: TelemetrySettings = TelemetrySettings()`. Update `main.py` to pass `settings.telemetry` to `setup_telemetry()`.

**Done when:** `get_settings().telemetry.service_name` returns expected value; no references to removed flat fields remain.

---

## Phase 2 — Backend Exporter Factory

### 2.1 — setup_telemetry() signature change

The signature changes from `(service_name, otlp_endpoint, enabled)` to `(config: TelemetrySettings) -> None`. The early-exit `enabled=False` path becomes `not config.traces_enabled and not config.metrics_enabled and not config.logs_enabled`.

**Done when:** All callers compile; backward compat tested; `_telemetry_initialised` guard retained.

### 2.2 — Console exporter

Console targets produce human-readable output useful for local development. `ConsoleSpanExporter` and `ConsoleMetricExporter` are in the OTEL SDK. For logs, a standard `logging.StreamHandler(sys.stdout)` with OTEL-format formatter satisfies the requirement.

**Done when:** Running with `exporters: [console]` prints spans and metrics to stdout.

### 2.3 — File exporter with rotation

File-backed export uses `logging.handlers.RotatingFileHandler` for logs (OTEL SDK logs bridge). For trace spans, a custom `FileSpanExporter` writes OTLP JSON to a rotating file using Python's standard `logging.handlers`. `FileExporterOptions.path` is created if it doesn't exist.

**Done when:** Spans and logs written to configured file path; rotation kicks in at `max_bytes`; old files limited by `backup_count`.

### 2.4 — OTLP exporter (HTTP and gRPC)

Replaces the existing hardcoded gRPC-only path. `protocol=grpc` uses `opentelemetry-exporter-otlp-proto-grpc`; `protocol=http` uses `opentelemetry-exporter-otlp-proto-http`. The default remains gRPC to preserve existing OTEL Collector compatibility.

**Done when:** Switching `protocol` in config changes the exporter class used; insecure flag forwarded.

### 2.5 — Logfire exporter

Logfire provides its own OTEL-compatible SDK. When `TelemetryExporterType.logfire` is in the active exporters and `LogfireExporterOptions.token` is set, initialize the Logfire SDK alongside the standard OTEL providers. If the token is absent, emit a `WARNING` log and skip.

**Done when:** Logfire OTEL exporter registers as an additional span processor when token present.

### 2.6 — Custom endpoint exporter

A custom endpoint uses OTLP HTTP export to the configured URL. Implemented with the same classes as the OTLP HTTP exporter but pointing to `CustomExporterOptions.endpoint`. Useful for forwarding to self-hosted compatible receivers (e.g. Grafana Alloy, Honeycomb).

**Done when:** Spans reach the custom URL; no credentials required in config (auth headers handled at collector level).

### 2.7 — Signal enable flags

When a signal is disabled, register a no-op provider to keep instrumented code functional with zero overhead:
- `traces_enabled=False` → `trace.set_tracer_provider(ProxyTracerProvider())` or SDK no-op
- `metrics_enabled=False` → `metrics.set_meter_provider(NoOpMeterProvider())`
- `logs_enabled=False` → skip `LoggerProvider` setup entirely

**Done when:** Application runs normally with all signals disabled; instrumented code does not raise.

### 2.8 — Per-component log levels

After providers are registered, iterate `config.log_levels` and call `logging.getLogger(component).setLevel(level)`. The `root` key maps to the root logger (`logging.getLogger()`).

**Done when:** Changing `log_levels.root` to `DEBUG` in config produces verbose output; setting `app.services` to `WARNING` suppresses service-layer debug logs.

---

## Phase 3 — Backend Telemetry Config API

### 3.1 — FrontendTelemetryConfigSchema

Response model defined in `backend/app/schemas/telemetry.py`:
- `otlp_http_endpoint: str` — the HTTP OTEL endpoint the browser should export to
- `service_name: str`
- `traces_enabled: bool`
- `metrics_enabled: bool`

No secrets, no credentials, no full `TelemetrySettings` dump.

**Done when:** Schema validates correctly; Pydantic serialises to camelCase-compatible JSON.

### 3.2 — GET /telemetry/config handler

Read-only endpoint. Derives `otlp_http_endpoint` from `TelemetrySettings.otlp` when `otlp` is in the active exporters, or the `custom` endpoint URL if only custom is configured. Falls back to the Vite env default if no suitable HTTP target exists. Requires a valid JWT (standard `deps.get_current_user` dependency).

**Done when:** `curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/telemetry/config` returns 200 JSON.

### 3.3 — Router registration

Add to `backend/app/api/v1/__init__.py`:
```
from app.api.v1.telemetry import TelemetryRouter
router.include_router(TelemetryRouter)
```

**Done when:** Route visible in Swagger UI; no import errors on startup.

---

## Phase 4 — Frontend Config-Driven Initialisation

### 4.1 — fetchTelemetryConfig()

Thin API function in `frontend/src/api/telemetryApi.ts`. On failure (network error, 401, 500), returns a safe default: `{ traces_enabled: false, metrics_enabled: false, ... }`. Does not throw.

**Done when:** Function returns typed `FrontendTelemetryConfig`; compile-time type errors caught.

### 4.2 — Refactor initTelemetry()

`initTelemetry(config: FrontendTelemetryConfig): void` accepts the resolved config. If `config.traces_enabled` is false, register no OTEL providers and return early. OTLP exporter URL is `config.otlp_http_endpoint`. Service name is `config.service_name`. Web Vitals recording is conditioned on `config.metrics_enabled`.

**Done when:** Tests pass with enabled config (registers providers) and disabled config (returns without registering).

### 4.3 — Bootstrap update in main.tsx

On app mount, call `fetchTelemetryConfig()` then `initTelemetry(config)` before rendering. Since telemetry is non-critical, failure must not block rendering.

**Done when:** Browser DevTools Network tab shows the config fetch on page load; OTEL traces appear in collector when telemetry is enabled.

---

## Phase 5 — Tests

### 5.1 — TelemetrySettings unit tests

Location: `backend/tests/core/test_telemetry_config.py`

- Default instantiation — all fields populated
- Env-var override of `exporters`, `service_name`, `traces_enabled`
- Invalid log level string raises `ValidationError`
- OTLP options nested correctly

**Done when:** `pytest backend/tests/core/test_telemetry_config.py` passes; no skips.

### 5.2 — ExporterFactory unit tests

Location: `backend/tests/core/test_telemetry.py`

- Console config → `ConsoleSpanExporter` in tracer provider processors
- OTLP gRPC config → `OTLPSpanExporter` (grpc) registered
- OTLP HTTP config → `OTLPSpanExporter` (http) registered
- `traces_enabled=False` → no-op tracer provider
- Multi-target config (console + otlp) → two processors registered

**Done when:** `pytest backend/tests/core/test_telemetry.py` passes with all 5 scenarios.

### 5.3 — Telemetry config API test

Location: `backend/tests/api/test_telemetry.py`

- Authenticated GET → 200 with `FrontendTelemetryConfigSchema` shape
- Unauthenticated GET → 401

**Done when:** `pytest backend/tests/api/test_telemetry.py` passes.

### 5.4 — Frontend telemetry unit tests

Location: `frontend/src/__tests__/telemetry.test.ts`

- `initTelemetry({ traces_enabled: true, ... })` → provider registered (mock OTEL SDK)
- `initTelemetry({ traces_enabled: false, ... })` → no provider registered
- `fetchTelemetryConfig()` network failure → returns safe default without throwing

**Done when:** `npx vitest run frontend/src/__tests__/telemetry.test.ts` passes for all three scenarios.

---

## Phase 6 — Sample Config & Environment Documentation

### 6.1 — config/telemetry.yaml

Annotated sample file that doubles as the schema reference. Must cover:
- All five exporter targets with their option blocks
- Signal enable/disable flags
- Log level map examples

Structure mirrors `TelemetrySettings` so operators can copy-edit for their deployment. Compatible with Kubernetes ConfigMap volume mount.

**Done when:** File is valid YAML; all `TelemetrySettings` fields present with comments; loading the file via `TelemetrySettings(**yaml.safe_load(...))` succeeds.

### 6.2 — .env.example update

Add entries for every new env var introduced by `TelemetrySettings`, grouped under a `# Telemetry` section. Include type annotation comments and safe default values.

**Done when:** All new env vars documented; no existing vars removed; file loads cleanly.

---

## Completion Checklist

- [ ] `TelemetrySettings` model defined and embedded in `Settings`; all existing `otel_*` flat fields removed
- [ ] `ExporterFactory` handles all five export target types
- [ ] Signal enable flags produce no-op providers when disabled
- [ ] Per-component log levels applied at startup
- [ ] `GET /api/v1/telemetry/config` endpoint returns correct schema; requires JWT
- [ ] Frontend `initTelemetry()` driven by fetched config, not hardcoded env vars
- [ ] All backend unit tests passing (`pytest backend/tests/`)
- [ ] All frontend unit tests passing (`npx vitest run`)
- [ ] `config/telemetry.yaml` sample file created
- [ ] `.env.example` updated with all new telemetry env vars
