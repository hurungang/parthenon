# Module: observability — Tech Spec

## Overview

The observability module covers both the application-level telemetry configuration engine and the infrastructure pipeline that receives and routes that telemetry. The backend resolves a `TelemetrySettings` model (env vars → YAML file → defaults) and feeds it into an `ExporterFactory` that wires active export targets into the OTEL SDK; each signal type (traces, metrics, logs) can be independently disabled, and multiple exporters can run simultaneously for the same signal. A `GET /api/v1/telemetry/config` endpoint returns a safe configuration subset so the frontend OTEL SDK initialises from a single authoritative source without duplicating configuration. The OTEL Collector pipeline receives OTLP spans, metrics, and logs from all services and fans them out to Prometheus, Jaeger, and Loki backends. The module also covers the Docker Compose and Helm chart configurations for the full observability stack, and the GitHub Actions CI jobs for frontend testing and dependency vulnerability scanning.

---

## Key Components

### Backend — Telemetry Configuration Engine

| Component | Description |
|-----------|-------------|
| `TelemetryExporterType` | String enum of valid export target identifiers: `console`, `file`, `otlp`, `logfire`, `custom` |
| `OtlpExporterOptions` | Pydantic model for OTLP exporter parameters: endpoint, protocol (grpc/http), insecure flag |
| `FileExporterOptions` | Pydantic model for file exporter parameters: path, max_bytes, backup_count |
| `LogfireExporterOptions` | Pydantic model for Logfire exporter parameters: token (nullable) |
| `CustomExporterOptions` | Pydantic model for custom endpoint parameters: endpoint URL |
| `TelemetrySettings` | Central telemetry configuration model embedded in `Settings`; resolves from env vars and `config/telemetry.yaml` |
| `ExporterFactory` | Builds OTEL exporters and processors from `TelemetrySettings`; registers `TracerProvider`, `MeterProvider`, and `LoggerProvider`; installs no-op providers for disabled signals |
| `setup_telemetry` | Startup entry point; guards against double-init; delegates to `ExporterFactory`; applies per-component log levels |
| `_FileSpanExporter` | File-backed span exporter with RotatingFileHandler |
| `_FileMetricExporter` | File-backed metric exporter with RotatingFileHandler |
| `_FileLogExporter` | File-backed log exporter with RotatingFileHandler |

### Backend — Telemetry API

| Component | Description |
|-----------|-------------|
| `TelemetryRouter` | FastAPI `APIRouter` (prefix `/telemetry`) hosting the telemetry config endpoint |
| `FrontendTelemetryConfigSchema` | Pydantic response model; safe subset of `TelemetrySettings` — no credentials returned |
| `get_telemetry_config` | Route handler for `GET /api/v1/telemetry/config`; requires JWT authentication |
| `_resolve_otlp_http_endpoint` | Derives the OTLP HTTP endpoint for frontend from `TelemetrySettings` |

### Frontend — Telemetry Initialisation

| Component | Description |
|-----------|-------------|
| `FrontendTelemetryConfig` | TypeScript interface matching `FrontendTelemetryConfigSchema` |
| `fetchTelemetryConfig` | Async function; calls backend config endpoint at app bootstrap; returns safe default on failure |
| `initTelemetry` | Initialises the OTEL Web SDK from `FrontendTelemetryConfig`; gates exporter registration on `traces_enabled` / `metrics_enabled` flags |
| `_recordWebVitals` | Records Core Web Vitals as OTEL histogram observations |

### Frontend — Observability Dashboard

| Component | Description |
|-----------|-------------|
| `ObservabilityDashboard` | Admin page displaying real-time OTEL metrics panels and deep links to Jaeger trace search and Loki log stream for cross-referencing telemetry |

### Infrastructure — OTEL Collector and Backends

| Component | Description |
|-----------|-------------|
| `otel-collector-config.yaml` | OTEL Collector pipeline configuration: OTLP receiver accepting gRPC (4317) and HTTP (4318) input; batch processor for buffering; exporters for Prometheus metrics (port 8889), Jaeger traces, and Loki logs |
| `prometheus.yml` | Prometheus scrape configuration targeting the OTEL Collector's Prometheus exporter endpoint at port 8889 |
| `docker-compose.yml` | Adds `otel-collector`, `jaeger`, `prometheus`, and `loki` service definitions to the local deployment stack; injects `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable into the `api` service |

### Infrastructure — Helm Chart

| Component | Description |
|-----------|-------------|
| `Chart.yaml` | Helm chart metadata: name=parthenon, version=0.1.0, appVersion=0.1.0 |
| `values.yaml` | Default values for all services covering replica counts, container images and tags, resource requests and limits, autoscaling thresholds, secret key references, ingress configuration, and the full OTEL Collector pipeline config |
| `_helpers.tpl` | Shared Go template helpers providing `fullname`, `labels`, `selectorLabels`, `image`, `secretName`, and `configMapName` helper functions used across all templates |
| `api-deployment.yaml` | Kubernetes Deployment for the FastAPI backend with environment variable injection from the platform Secret and ConfigMap |
| `api-service.yaml` | Kubernetes ClusterIP Service for the API Deployment |
| `frontend-deployment.yaml` | Kubernetes Deployment for the React/Vite frontend container |
| `frontend-service.yaml` | Kubernetes ClusterIP Service for the frontend Deployment |
| `postgres-deployment.yaml` | Kubernetes Deployment and PersistentVolumeClaim for PostgreSQL |
| `postgres-service.yaml` | Kubernetes ClusterIP Service for PostgreSQL |
| `redis-deployment.yaml` | Kubernetes Deployment for Redis |
| `redis-service.yaml` | Kubernetes ClusterIP Service for Redis |
| `nginx-deployment.yaml` | Kubernetes Deployment for the nginx reverse proxy |
| `nginx-service.yaml` | Kubernetes ClusterIP Service for nginx |
| `otel-collector-deployment.yaml` | Kubernetes Deployment for the OTEL Collector with a ConfigMap volume mount for the pipeline configuration |
| `otel-collector-service.yaml` | Kubernetes ClusterIP Service exposing gRPC (4317), HTTP (4318), Prometheus metrics (8889), and health (13133) ports |
| `ingress.yaml` | Kubernetes Ingress routing `/api` and `/ws` paths to the API Service and `/` to the frontend Service |
| `secrets.yaml` | Kubernetes Secret holding database credentials, `SECRET_KEY`, `CREDENTIAL_VAULT_KEY`, and the OIDC client secret |
| `configmap.yaml` | Kubernetes ConfigMap holding the OIDC issuer URL, JWT audience, Vite environment variables, and the OTEL Collector pipeline configuration |
| `hpa.yaml` | Kubernetes HorizontalPodAutoscaler for the API Deployment (CPU + memory scaling) and the frontend Deployment (CPU scaling) |

### CI Jobs

| Component | Description |
|-----------|-------------|
| `dependency-check` | GitHub Actions CI job that runs OWASP Dependency Check on every push to main; fails the build if any dependency has a CVSS score ≥ 7; uploads the HTML report as a build artifact |
| `frontend-test` | GitHub Actions CI job that executes `npm run test -- --run` (vitest) in the frontend directory as part of the standard CI pipeline |

---

## API Endpoints

### `GET /api/v1/telemetry/config`

- **Auth**: JWT required
- **Purpose**: Returns the frontend-relevant telemetry configuration subset so the browser OTEL SDK can be initialised from a single authoritative source
- **Response** (`FrontendTelemetryConfigSchema`):

| Field | Type | Description |
|-------|------|-------------|
| `otlp_http_endpoint` | string | OTLP HTTP endpoint the browser should export to |
| `service_name` | string | OTEL service name to attach to all frontend spans |
| `traces_enabled` | boolean | Whether browser trace collection is active |
| `metrics_enabled` | boolean | Whether browser metrics collection is active |

No credentials or full configuration are returned.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `TelemetryExporterType` | enum | String enum of valid exporter target names: console, file, otlp, logfire, custom | `backend/app/core/config.py` |
| `OtlpExporterOptions` | class | Pydantic model for OTLP exporter parameters | `backend/app/core/config.py` |
| `FileExporterOptions` | class | Pydantic model for file exporter parameters | `backend/app/core/config.py` |
| `LogfireExporterOptions` | class | Pydantic model for Logfire exporter parameters | `backend/app/core/config.py` |
| `CustomExporterOptions` | class | Pydantic model for custom endpoint parameters | `backend/app/core/config.py` |
| `TelemetrySettings` | class | Central telemetry configuration model; embedded in `Settings` | `backend/app/core/config.py` |
| `Settings.telemetry` | field | Nested `TelemetrySettings` field on `Settings` | `backend/app/core/config.py` |
| `get_settings` | function | Cached settings factory | `backend/app/core/config.py` |
| `ExporterFactory` | class | Builds OTEL exporters from `TelemetrySettings`; registers all providers | `backend/app/core/telemetry.py` |
| `ExporterFactory.build_trace_processors` | method | Returns list of `SpanProcessor` instances for configured targets | `backend/app/core/telemetry.py` |
| `ExporterFactory.build_metric_readers` | method | Returns list of `MetricReader` instances for configured targets | `backend/app/core/telemetry.py` |
| `ExporterFactory.build_log_processors` | method | Returns list of `LogRecordProcessor` instances for configured targets | `backend/app/core/telemetry.py` |
| `setup_telemetry` | function | Startup entry point; guards double-init; delegates to `ExporterFactory`; applies log levels | `backend/app/core/telemetry.py` |
| `_instrument_libraries` | function | Auto-instrumentation for FastAPI, SQLAlchemy, Redis, httpx | `backend/app/core/telemetry.py` |
| `_FileSpanExporter` | class | File-backed span exporter with RotatingFileHandler | `backend/app/core/telemetry.py` |
| `_FileMetricExporter` | class | File-backed metric exporter with RotatingFileHandler | `backend/app/core/telemetry.py` |
| `_FileLogExporter` | class | File-backed log exporter with RotatingFileHandler | `backend/app/core/telemetry.py` |
| `_apply_log_levels` | function | Applies per-component log levels from config map | `backend/app/core/telemetry.py` |
| `FrontendTelemetryConfigSchema` | class | Pydantic response schema for `GET /api/v1/telemetry/config` | `backend/app/schemas/telemetry.py` |
| `TelemetryRouter` | variable | `APIRouter` instance registered in the v1 router | `backend/app/api/v1/telemetry.py` |
| `get_telemetry_config` | function | FastAPI route handler for `GET /api/v1/telemetry/config` | `backend/app/api/v1/telemetry.py` |
| `_resolve_otlp_http_endpoint` | function | Derives the OTLP HTTP endpoint for frontend from `TelemetrySettings` | `backend/app/api/v1/telemetry.py` |
| `FrontendTelemetryConfig` | interface | TypeScript interface matching `FrontendTelemetryConfigSchema` | `frontend/src/api/telemetryApi.ts` |
| `fetchTelemetryConfig` | function | Fetches telemetry config from backend; returns safe default on failure | `frontend/src/api/telemetryApi.ts` |
| `initTelemetry` | function | Initialises OTEL Web SDK from provided `FrontendTelemetryConfig` | `frontend/src/telemetry.ts` |
| `_recordWebVitals` | function | Records Core Web Vitals as OTEL histogram observations | `frontend/src/telemetry.ts` |
| `ObservabilityDashboard` | component | Real-time OTEL metrics panels with deep links to Jaeger and Loki | `frontend/src/pages/observability/ObservabilityDashboard.tsx` |
| `otel-collector-config.yaml` | config | OTEL Collector pipeline: OTLP receiver → batch processor → Prometheus / Jaeger / Loki exporters | `infra/otel-collector-config.yaml` |
| `prometheus.yml` | config | Prometheus scrape config targeting OTEL Collector exporter at port 8889 | `infra/prometheus.yml` |
| `docker-compose.yml` | config | Adds otel-collector, jaeger, prometheus, and loki services; injects OTEL_EXPORTER_OTLP_ENDPOINT into api | `docker-compose.yml` |
| `telemetry.yaml` | config | Sample annotated telemetry configuration for operators | `config/telemetry.yaml` |
| `.env.example` | config | Documents all `TELEMETRY__*` env vars with types and defaults | `.env.example` |
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
| `telemetry.test` | test module | Frontend: `initTelemetry` and `fetchTelemetryConfig` unit tests | `frontend/src/__tests__/telemetry.test.ts` |
| `Chart.yaml` | helm | Helm chart metadata (name=parthenon, version=0.1.0, appVersion=0.1.0) | `infra/helm/parthenon/Chart.yaml` |
| `values.yaml` | helm | Default values for all services: replicas, images, resources, autoscaling, secrets, ingress, OTEL Collector config | `infra/helm/parthenon/values.yaml` |
| `_helpers.tpl` | helm | Shared Go template helpers: fullname, labels, selectorLabels, image, secretName, configMapName | `infra/helm/parthenon/templates/_helpers.tpl` |
| `api-deployment.yaml` | helm | Deployment for FastAPI backend with env injection from Secret/ConfigMap | `infra/helm/parthenon/templates/api-deployment.yaml` |
| `api-service.yaml` | helm | ClusterIP Service for the API Deployment | `infra/helm/parthenon/templates/api-service.yaml` |
| `frontend-deployment.yaml` | helm | Deployment for React/Vite frontend | `infra/helm/parthenon/templates/frontend-deployment.yaml` |
| `frontend-service.yaml` | helm | ClusterIP Service for the frontend Deployment | `infra/helm/parthenon/templates/frontend-service.yaml` |
| `postgres-deployment.yaml` | helm | Deployment and PVC for PostgreSQL | `infra/helm/parthenon/templates/postgres-deployment.yaml` |
| `postgres-service.yaml` | helm | ClusterIP Service for PostgreSQL | `infra/helm/parthenon/templates/postgres-service.yaml` |
| `redis-deployment.yaml` | helm | Deployment for Redis | `infra/helm/parthenon/templates/redis-deployment.yaml` |
| `redis-service.yaml` | helm | ClusterIP Service for Redis | `infra/helm/parthenon/templates/redis-service.yaml` |
| `nginx-deployment.yaml` | helm | Deployment for nginx reverse proxy | `infra/helm/parthenon/templates/nginx-deployment.yaml` |
| `nginx-service.yaml` | helm | ClusterIP Service for nginx | `infra/helm/parthenon/templates/nginx-service.yaml` |
| `otel-collector-deployment.yaml` | helm | Deployment for OTEL Collector with ConfigMap volume mount | `infra/helm/parthenon/templates/otel-collector-deployment.yaml` |
| `otel-collector-service.yaml` | helm | ClusterIP Service exposing gRPC (4317), HTTP (4318), Prometheus (8889), and health (13133) ports | `infra/helm/parthenon/templates/otel-collector-service.yaml` |
| `ingress.yaml` | helm | Nginx Ingress routing /api and /ws to API Service; / to frontend Service | `infra/helm/parthenon/templates/ingress.yaml` |
| `secrets.yaml` | helm | Kubernetes Secret for DB credentials, SECRET_KEY, CREDENTIAL_VAULT_KEY, and OIDC client secret | `infra/helm/parthenon/templates/secrets.yaml` |
| `configmap.yaml` | helm | ConfigMap for OIDC URL, JWT audience, Vite env vars, and OTEL Collector pipeline config | `infra/helm/parthenon/templates/configmap.yaml` |
| `hpa.yaml` | helm | HPA for api (CPU+memory) and frontend (CPU) Deployments | `infra/helm/parthenon/templates/hpa.yaml` |
| `dependency-check` | CI job | OWASP Dependency Check on push to main; fails on CVSS ≥ 7; uploads HTML report artifact | `.github/workflows/ci.yml` |
| `frontend-test` | CI job | Runs `npm run test -- --run` (vitest) in the frontend directory | `.github/workflows/ci.yml` |
