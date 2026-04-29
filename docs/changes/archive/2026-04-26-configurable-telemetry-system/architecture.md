# Architecture Changes — Configurable Telemetry System

## Changed Components

| Component | Location | Change |
|---|---|---|
| **Backend Telemetry Module** | `backend/app/core/telemetry.py` | Hardcoded OTLP gRPC exporters replaced with config-driven exporter factory; providers initialised conditionally based on `TelemetryConfig` |
| **Frontend Telemetry Module** | `frontend/src/telemetry.ts` | Hardcoded OTLP endpoint replaced with runtime config lookup; OTEL SDK initialisation gated on enabled flags from config |
| **Backend App Config** | `backend/app/core/config.py` | `TelemetrySettings` section added covering export targets, signal enable flags, log levels, and exporter-specific parameters |

---

## New Components

Two new components are introduced: a **Telemetry Config Loader** (shared concern across backend and frontend) and an **Exporter Factory** that translates config into live OTEL provider registrations.

```mermaid
flowchart TB
    subgraph ConfigSources[Configuration Sources]
        CF[Config File\ntelemetry.yaml / app config]
        ENV[Environment Variables]
    end

    subgraph TelemetryInit[Telemetry Initialisation]
        CL[Telemetry Config Loader]
        EF[Exporter Factory]
    end

    subgraph OTELProviders[OTEL SDK Providers]
        TP[Tracer Provider]
        MP[Meter Provider]
        LP[Logger Provider]
    end

    subgraph ExportTargets[Export Targets]
        CON[Console]
        FILE[File + Rotation]
        COL[OTEL Collector\nHTTP / gRPC]
        LF[Logfire]
        CUST[Custom Endpoint]
    end

    CF --> CL
    ENV --> CL
    CL --> EF
    EF --> TP
    EF --> MP
    EF --> LP
    TP --> CON
    TP --> FILE
    TP --> COL
    TP --> LF
    TP --> CUST
    MP --> CON
    MP --> COL
    MP --> LF
    LP --> CON
    LP --> FILE
    LP --> COL
    LP --> LF
    LP --> CUST
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| **Telemetry Config Loader** | Reads telemetry settings from config file and environment overrides; resolves final `TelemetryConfig` |
| **Exporter Factory** | Instantiates OTEL exporters and processors based on `TelemetryConfig`; registers `TracerProvider`, `MeterProvider`, and `LoggerProvider` |
| **Config File** | Declarative telemetry settings per deployment; lives alongside app config; compatible with Docker Compose and Kubernetes ConfigMap |

---

## Integration Points

```mermaid
flowchart LR
    subgraph Backend
        BE_CL[Config Loader]
        BE_SDK[OTEL SDK\nBackend]
        BE_API[Config API\n/api/v1/telemetry/config]
    end

    subgraph Frontend
        FE_CL[Frontend Telemetry\nInitialiser]
        FE_SDK[OTEL SDK\nFrontend]
    end

    COL[OTEL Collector]

    subgraph Backends
        PROM[Prometheus]
        JAEG[Jaeger]
        LOKI[Loki]
    end

    BE_CL --> BE_SDK
    BE_CL --> BE_API
    BE_API -->|telemetry config JSON| FE_CL
    FE_CL --> FE_SDK
    BE_SDK -->|OTLP| COL
    FE_SDK -->|OTLP HTTP| COL
    COL --> PROM
    COL --> JAEG
    COL --> LOKI
```

**Integration notes:**
- The backend exposes a lightweight `/api/v1/telemetry/config` endpoint so the frontend can fetch its telemetry settings at startup without duplicating configuration.
- The OTEL Collector remains the primary fan-out hub; direct exporter targets (Logfire, custom endpoint) bypass the Collector only when explicitly configured.
- Environment variables take precedence over file-based config (12-factor pattern), enabling per-pod overrides in Kubernetes.

---

## Data Flow Changes

### Before (hardcoded)
All OTEL providers were initialised at startup with a single hardcoded OTLP gRPC endpoint and fixed log level. No runtime flexibility existed.

### After (config-driven)

```mermaid
sequenceDiagram
    participant App as Application\n(Backend / Frontend)
    participant CL as Config Loader
    participant EF as Exporter Factory
    participant SDK as OTEL SDK
    participant TGT as Export Targets

    App->>CL: load telemetry config
    CL->>CL: read config file
    CL->>CL: apply env var overrides
    CL-->>App: TelemetryConfig

    App->>EF: initialise(TelemetryConfig)
    EF->>EF: build enabled exporters
    EF->>EF: apply signal enable flags\n(traces / metrics / logs)
    EF->>SDK: register TracerProvider
    EF->>SDK: register MeterProvider
    EF->>SDK: register LoggerProvider
    SDK-->>App: providers ready

    loop Per signal emission
        App->>SDK: emit span / metric / log
        SDK->>TGT: export via configured exporter
    end
```

**Key changes to data flow:**
- Config resolution now precedes SDK initialisation — providers are never registered without a resolved config.
- Signal types (traces, metrics, logs) are independently gated; a disabled signal produces a no-op provider, preserving instrumented code without side effects.
- Log level is applied at SDK initialisation time per component, not globally.
- Multiple exporters can be active simultaneously for the same signal (e.g., Console + OTEL Collector for local debugging alongside production pipeline).

---

## Master Arch Update Instructions

Update `docs/master/architecture/modules/observability.md`:

1. **Telemetry Pipeline diagram** — Extend to show the Config Loader feeding into the OTEL SDK block; add export target branches (Console, File, Logfire, Custom) alongside the existing Collector path.
2. **Instrumentation Strategy section** — Add a bullet describing config-driven exporter selection and the signal enable/disable capability.
3. **New section: Telemetry Configuration** — Document the `TelemetryConfig` resolution order (config file → env var overrides), the frontend config fetch pattern, and the supported export targets.

No changes required to `docs/master/architecture/system-overview.md` — observability remains a cross-cutting concern anchored to the OTEL Collector; the new config layer is an internal initialisation detail, not a topology change.
