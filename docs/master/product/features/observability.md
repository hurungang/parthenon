# Observability

## Overview
Observability provides real-time insight into the health, performance, and activity of all Parthenon components. It leverages OTEL instrumentation, a central Collector, and multiple exporters to deliver comprehensive monitoring and diagnostics for administrators.

## Who Uses It
- Enterprise Admins: Monitor platform health, performance, and troubleshoot issues
- Compliance Auditors: Review logs, traces, and metrics for compliance
- Operations Teams: Respond to alerts and maintain system reliability
- **AI Operations Leads: Monitor live runtime topology, model-usage posture, and guardrail enforcement state**

## What It Does
- Instruments all platform components with OTEL for metrics, traces, and logs
- Integrates with an OTEL Collector for centralized data aggregation
- Supports multiple exporters (Prometheus, Jaeger, Loki) for external monitoring
- Provides an admin dashboard for real-time observability and diagnostics
- **Surfaces runtime control dashboard signals** including active agents, delegated children, configured model-usage limits, current usage posture, and guardrail enforcement state
- **Surfaces observe-only guardrail limit alerts as user-visible operational signals** in execution logs distinct from standard execution failures
- **Surfaces disabled-model and disabled-vendor block events** in execution logs and operational dashboards
- **Surfaces operator-initiated termination outcomes** as a distinct `terminated` state distinct from `failed` (genuine agent or runtime error)

## Key Concepts
- **OTEL Instrumentation**: Embedding observability hooks in all components
- **OTEL Collector**: Central service for aggregating observability data
- **Exporter**: Integration point for external monitoring tools
- **Admin Dashboard**: UI for real-time monitoring and diagnostics
- **Runtime Control Dashboard**: Read-only operator view of currently running agents, delegation topology, model-usage posture, and termination actions
- **Topology Diagram**: Visual representation of active parent-child agent execution relationships
- **Usage Posture**: Current state of a model's usage against its configured guardrail limits — `within limit`, `approaching limit`, or `breached`

## Acceptance Criteria
- All components emit OTEL metrics, traces, and logs
- OTEL Collector aggregates and forwards observability data
- Exporters are configurable for Prometheus, Jaeger, and Loki
- Admin dashboard displays real-time health and diagnostics
- All observability data is accessible for compliance and troubleshooting
- **Observe-only guardrail limit alerts are surfaced as user-visible operational signals in execution logs**
- **Operator-initiated termination outcomes are surfaced as a distinct operational signal distinct from `failed`**
- **Disabled-model and disabled-vendor block events are surfaced in execution logs and operational dashboards**

## Out of Scope
- (none additional)

## Dependencies & Constraints
- Depends on a vendor and model catalogue that the hierarchy can be built on top of, so that vendor enable/disable and model selection have a stable source of truth
- Depends on reliable runtime state and delegation relationship signals to render accurate running-agent topology
- Constrained by enterprise auditability requirements: guardrail alerts, model-usage posture changes, vendor/model disable changes, and termination actions must be visible in operational logs
