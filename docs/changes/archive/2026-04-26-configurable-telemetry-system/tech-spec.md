# Technical Specification: configurable-telemetry-system

## Technical Overview

The hardcoded single-target OTEL initialisation in both backend and frontend is replaced with a configuration-driven system. The backend resolves a `TelemetrySettings` model (env vars → YAML file → defaults), feeds it into an `ExporterFactory` that wires the active export targets into the OTEL SDK, and exposes a lightweight `GET /api/v1/telemetry/config` endpoint so the frontend can initialise its own OTEL providers without duplicating configuration. Multiple exporters can run simultaneously for the same signal, and each signal type (traces, metrics, logs) can be independently disabled by registering a no-op provider, preserving all instrumented call sites.

---

## Component Breakdown

| Component | Responsibility |
|---|---|
| `TelemetrySettings` | Pydantic `BaseModel` embedded in `Settings`; holds all telemetry config fields; resolved from env vars and defaults |
| `TelemetryExporterType` | String enum of valid export target identifiers: `console`, `file`, `otlp`, `logfire`, `custom` |
| `OtlpExporterOptions` | Typed options for OTLP target: `endpoint`, `protocol` (grpc/http), `insecure` |
| `FileExporterOptions` | Typed options for file target: `path`, `max_bytes`, `backup_count` |
| `LogfireExporterOptions` | Typed options for Logfire target: `token` (nullable) |
| `CustomExporterOptions` | Typed options for custom endpoint: `endpoint` URL |
| `ExporterFactory` | Builds OTEL exporters and processors from a resolved `TelemetrySettings`; registers `TracerProvider`, `MeterProvider`, and `LoggerProvider`; installs no-op providers for disabled signals |
| `setup_telemetry()` | Startup entry point; guards against double-init; delegates to `ExporterFactory`; applies per-component log levels |
| `TelemetryRouter` | FastAPI `APIRouter` hosting `GET /telemetry/config`; returns `FrontendTelemetryConfigSchema` |
| `FrontendTelemetryConfigSchema` | Pydantic response model; safe subset of `TelemetrySettings` (no credentials) |
| `fetchTelemetryConfig()` | Frontend async function; calls backend config endpoint; returns typed `FrontendTelemetryConfig`; degrades to safe default on failure |
| `initTelemetry()` | Frontend OTEL initialiser; refactored to accept `FrontendTelemetryConfig`; gates exporter registration on `traces_enabled` / `metrics_enabled` flags |

---

## API Changes

### New Endpoint

**`GET /api/v1/telemetry/config`**

- **Auth**: JWT required (standard `get_current_user` dependency)
- **Purpose**: Returns the frontend-relevant telemetry configuration subset so the browser OTEL SDK can be initialised from a single authoritative source
- **Response shape** (`FrontendTelemetryConfigSchema`):

| Field | Type | Description |
|---|---|---|
| `otlp_http_endpoint` | `string` | OTLP HTTP endpoint the browser should export to |
| `service_name` | `string` | OTEL service name to attach to all frontend spans |
| `traces_enabled` | `boolean` | Whether browser trace collection is active |
| `metrics_enabled` | `boolean` | Whether browser metrics collection is active |

- **No credentials, no full config dump** — only the four fields above are returned

---

## State Management

No new frontend global state stores are introduced. The `FrontendTelemetryConfig` fetched at startup is consumed directly by `initTelemetry()` and discarded; it does not need to be persisted in a store because telemetry is a one-time initialisation at app mount.

---

## Data Access Patterns

| Operation | Location | Pattern |
|---|---|---|
| Backend config resolution | `backend/app/core/config.py` | Pydantic `BaseSettings` — env vars override defaults at process startup |
| YAML-based config override | `config/telemetry.yaml` (optional) | Loaded as a custom Pydantic settings source alongside existing `identity.yaml` pattern |
| Frontend config fetch | `frontend/src/api/telemetryApi.ts` → `GET /api/v1/telemetry/config` | Single HTTP GET at app bootstrap; result is ephemeral (not cached or stored) |
| OTEL export | `backend/app/core/telemetry.py` (SDK push) | OTEL SDK batch processors push spans/metrics/logs to configured targets on background threads |
| Log level application | `backend/app/core/telemetry.py` (end of `setup_telemetry()`) | `logging.getLogger(name).setLevel(level)` called once at startup; no runtime mutation |

---

## Code Reference Map

| Symbol | Type | Description | File |
|---|---|---|---|
| `TelemetryExporterType` | enum | String enum of valid exporter target names | `backend/app/core/config.py` |
| `OtlpExporterOptions` | class | Pydantic model for OTLP exporter parameters | `backend/app/core/config.py` |
| `FileExporterOptions` | class | Pydantic model for file exporter parameters | `backend/app/core/config.py` |
| `LogfireExporterOptions` | class | Pydantic model for Logfire exporter parameters | `backend/app/core/config.py` |
| `CustomExporterOptions` | class | Pydantic model for custom endpoint parameters | `backend/app/core/config.py` |
| `TelemetrySettings` | class | Central telemetry configuration model; embedded in `Settings` | `backend/app/core/config.py` |
| `Settings.telemetry` | field | Nested `TelemetrySettings` field replacing flat `otel_*` fields | `backend/app/core/config.py` |
| `get_settings` | function | Cached settings factory | `backend/app/core/config.py` |
| `ExporterFactory` | class | Builds OTEL exporters from `TelemetrySettings`; registers providers | `backend/app/core/telemetry.py` |
| `ExporterFactory.build_trace_processors` | method | Returns list of `SpanProcessor` instances for configured targets | `backend/app/core/telemetry.py` |
| `ExporterFactory.build_metric_readers` | method | Returns list of `MetricReader` instances for configured targets | `backend/app/core/telemetry.py` |
| `ExporterFactory.build_log_processors` | method | Returns list of `LogRecordProcessor` instances for configured targets | `backend/app/core/telemetry.py` |
| `setup_telemetry` | function | Startup entry point; guards double-init; delegates to `ExporterFactory`; applies log levels | `backend/app/core/telemetry.py` |
| `_instrument_libraries` | function | Auto-instrumentation for FastAPI, SQLAlchemy, Redis, httpx (unchanged) | `backend/app/core/telemetry.py` |
| `FrontendTelemetryConfigSchema` | class | Pydantic response schema for `GET /api/v1/telemetry/config` | `backend/app/schemas/telemetry.py` |
| `get_telemetry_config` | function | FastAPI route handler for `GET /api/v1/telemetry/config` | `backend/app/api/v1/telemetry.py` |
| `TelemetryRouter` | variable | `APIRouter` instance registered in the v1 router | `backend/app/api/v1/telemetry.py` |
| `FrontendTelemetryConfig` | interface | TypeScript interface matching `FrontendTelemetryConfigSchema` | `frontend/src/api/telemetryApi.ts` |
| `fetchTelemetryConfig` | function | Fetches telemetry config from backend; returns safe default on failure | `frontend/src/api/telemetryApi.ts` |
| `initTelemetry` | function | Initialises OTEL Web SDK from provided `FrontendTelemetryConfig` | `frontend/src/telemetry.ts` |
| `_recordWebVitals` | function | Records Core Web Vitals as OTEL histogram observations (unchanged) | `frontend/src/telemetry.ts` |
| `test_telemetry_settings_defaults` | function | Unit test: default `TelemetrySettings` field values | `backend/tests/core/test_telemetry_config.py` |
| `test_telemetry_settings_env_override` | function | Unit test: env-var override of telemetry settings | `backend/tests/core/test_telemetry_config.py` |
| `test_exporter_factory_console` | function | Unit test: console exporter produces correct processor type | `backend/tests/core/test_telemetry.py` |
| `test_exporter_factory_otlp_grpc` | function | Unit test: OTLP gRPC exporter registered for grpc protocol | `backend/tests/core/test_telemetry.py` |
| `test_exporter_factory_otlp_http` | function | Unit test: OTLP HTTP exporter registered for http protocol | `backend/tests/core/test_telemetry.py` |
| `test_exporter_factory_disabled_traces` | function | Unit test: no-op tracer provider when traces_enabled=False | `backend/tests/core/test_telemetry.py` |
| `test_exporter_factory_multi_target` | function | Unit test: multiple processors registered for multi-target config | `backend/tests/core/test_telemetry.py` |
| `test_telemetry_config_endpoint_authenticated` | function | API test: authenticated GET returns 200 with correct schema | `backend/tests/api/v1/test_telemetry.py` |
| `test_telemetry_config_endpoint_unauthenticated` | function | API test: unauthenticated GET returns 401 | `backend/tests/api/v1/test_telemetry.py` |
| `test_telemetry_config_returns_service_name` | function | API test: service name env var override reflected in response | `backend/tests/api/v1/test_telemetry.py` |
| `telemetry.test` | test module | Frontend: initTelemetry and fetchTelemetryConfig unit tests | `frontend/src/__tests__/telemetry.test.ts` |
| `telemetry.yaml` | config file | Sample annotated telemetry configuration for operators | `config/telemetry.yaml` |
| `.env.example` | config file | Documents all TELEMETRY__* env vars with types and defaults | `.env.example` |
| `_FileSpanExporter` | class | File-backed span exporter with RotatingFileHandler | `backend/app/core/telemetry.py` |
| `_FileMetricExporter` | class | File-backed metric exporter with RotatingFileHandler | `backend/app/core/telemetry.py` |
| `_FileLogExporter` | class | File-backed log exporter with RotatingFileHandler | `backend/app/core/telemetry.py` |
| `_apply_log_levels` | function | Applies per-component log levels from config map | `backend/app/core/telemetry.py` |
| `_resolve_otlp_http_endpoint` | function | Derives the OTLP HTTP endpoint for frontend from TelemetrySettings | `backend/app/api/v1/telemetry.py` |
| `FrontendTelemetryConfig` | interface | TypeScript interface matching FrontendTelemetryConfigSchema | `frontend/src/api/telemetryApi.ts` |
