# Monitoring — Reference

Parthenon monitoring is layered: **metrics** are what each service emits, **dashboards** turn them into an operator view, and **alerts** decide when a human is paged. This page is the entry point — the metric catalog, dashboard definitions, and alert thresholds live on the topic pages below.

---

## Topic Index

| Topic page | Covers |
|------------|--------|
| [monitoring-metrics.md](monitoring-metrics.md) | Key metrics by component, including which series are *proposed* and still log-derived |
| [monitoring-dashboards.md](monitoring-dashboards.md) | Every dashboard and panel group to create |
| [monitoring-alerts.md](monitoring-alerts.md) | Alert names, conditions, severities, and first actions |
| [monitoring-tenancy.md](monitoring-tenancy.md) | Tenancy metrics and OTEL dimensions, tenancy alerts, and isolation-boundary dashboard/alerts/metrics |

---

## Where to Start

| Question | Go to |
|----------|-------|
| What does this series mean, and is it real or *proposed*? | [monitoring-metrics.md](monitoring-metrics.md) |
| Which dashboard or panel should show it? | [monitoring-dashboards.md](monitoring-dashboards.md) |
| When does it page, at what severity, and what is the first action? | [monitoring-alerts.md](monitoring-alerts.md) |
| Why are tenant signals missing? | [monitoring-tenancy.md](monitoring-tenancy.md) — they exist only while `multi_tenancy_enabled` is on |
| Which log event backs a log-derived series? | [logging.md](logging.md) and its topic pages |
| A service will not start, or restarts repeatedly | [README.md](README.md) health targets, then the startup-validation alert in [monitoring-alerts.md](monitoring-alerts.md) |

---

## Monitoring Model

- **Metrics** — every service emits traces, metrics, and structured logs; the OTEL Collector is the single pipeline for all three. The per-component metric table records what is instrumented and why it matters.
- **Dashboards** — panel groups are described per subject area, with the exact series and thresholds to draw. Operators should be able to answer "is this component healthy?" from the relevant dashboard alone.
- **Alerts** — every alert carries a severity and a documented first action; conditions, severities, and routing live in [monitoring-alerts.md](monitoring-alerts.md).
- **Log-derived signals** — many Control Center Assistant and conversational-resume series have no OTel counter yet. Rows marked *proposed* must be derived from the log events in [logging.md](logging.md) until counters ship; the alert names are stable and safe to pre-create.
- **Tenancy gating** — tenant resolution, scoping, signed-header, and resource-usage signals exist only while the tenancy platform switch (`multi_tenancy_enabled`) is on.

---

## Readiness and Health Checks

Boot-time readiness is proven by structured events, not by an endpoint:

- Startup validation (`startup.validation.*`), configuration-source resolution (`config.*.resolved`), and telemetry initialisation (`Telemetry initialised`) are the three startup signal families — see [monitoring-metrics.md](monitoring-metrics.md) for the series and [logging-platform.md](logging-platform.md) for the events.
- Runtime endpoint checks (Platform API, OTEL Collector, MCP Demo App, certificate authority, and the CC → AR → CH ordering) are listed under "Production Health Check Targets" in [README.md](README.md).
- Conversational turn readiness has no dedicated endpoint: confirm the reaper started and that activity/resume failures are absent in the logs — see [README.md](README.md) and [logging-conversation-turns.md](logging-conversation-turns.md).

---

## Related Reference

- **Log events** behind every log-derived series: [logging.md](logging.md) — turn activity and resume events in [logging-conversation-turns.md](logging-conversation-turns.md), assistant events in [logging-control-center-assistant.md](logging-control-center-assistant.md).
- **Runbooks** for acting on an alert: start from the "Runbooks" table in [README.md](README.md).
- **Deployment-time health targets** and startup ordering: [README.md](README.md) and [../deployment/first-time-deployment.md](../deployment/first-time-deployment.md).

---

## Forwarding Pointers

These section names are referenced by other documents; their content now lives on the linked topic page.

### Multi-Tenancy

Tenancy metrics, OTEL dimensions, alerts, and isolation-boundary signals (tenancy only while `multi_tenancy_enabled` is on) → [monitoring-tenancy.md](monitoring-tenancy.md).

### Agent Execution Guardrails

Guardrail metrics, dashboard panels, and alerts → [monitoring-metrics.md](monitoring-metrics.md) (metrics) and [monitoring-alerts.md](monitoring-alerts.md) (alerts).

### Control Center Assistant

Assistant metrics, dashboard panels, alerts, and their log-derived fallbacks → [monitoring-metrics.md](monitoring-metrics.md) and [monitoring-alerts.md](monitoring-alerts.md).

### Conversational Turn Resume

Resume metrics, the dashboard panel group, and the resume alert table → [monitoring-metrics.md](monitoring-metrics.md) and [monitoring-alerts.md](monitoring-alerts.md).

### Service Segregation Boundary Enforcement

Boundary dashboard panels, trust alerts, and boundary metrics → [monitoring-tenancy.md](monitoring-tenancy.md).
