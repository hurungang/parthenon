/**
 * frontend/src/telemetry.ts
 *
 * OpenTelemetry Web SDK initialisation.
 * - WebTracerProvider with OTLP HTTP exporter
 * - W3C TraceContext propagation injected into all fetch/XHR calls
 * - Core Web Vitals (LCP, FID/FCP, CLS) recorded as OTEL metrics
 *
 * Accepts a FrontendTelemetryConfig from the backend so all configuration
 * is resolved server-side — no hardcoded env-var reads.
 */

import { WebTracerProvider } from '@opentelemetry/sdk-trace-web';
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { ZoneContextManager } from '@opentelemetry/context-zone';
import { registerInstrumentations } from '@opentelemetry/instrumentation';
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch';
import { Resource } from '@opentelemetry/resources';
import { SEMRESATTRS_SERVICE_NAME } from '@opentelemetry/semantic-conventions';
import { metrics } from '@opentelemetry/api';
import { W3CTraceContextPropagator } from '@opentelemetry/core';
import type { Metric } from 'web-vitals';
import type { FrontendTelemetryConfig } from './api/telemetryApi';

let _initialised = false;

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

/**
 * Initialise OpenTelemetry for the browser from a resolved config.
 * Safe to call multiple times — subsequent calls are no-ops.
 *
 * When `config.traces_enabled` is false, no OTEL providers are registered
 * and the function returns immediately.
 */
export function initTelemetry(config: FrontendTelemetryConfig): void {
  if (_initialised) return;
  _initialised = true;

  if (!config.traces_enabled) {
    return;
  }

  const resource = new Resource({
    [SEMRESATTRS_SERVICE_NAME]: config.service_name,
  });

  // ── Tracer Provider ────────────────────────────────────────────────
  const exporter = new OTLPTraceExporter({
    url: `${config.otlp_http_endpoint}/v1/traces`,
  });

  const provider = new WebTracerProvider({ resource });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  provider.addSpanProcessor(new BatchSpanProcessor(exporter as any));

  // Use ZoneContextManager so async context propagates across promises
  provider.register({
    contextManager: new ZoneContextManager(),
    propagator: new W3CTraceContextPropagator(),
  });

  // ── Auto-instrument fetch ──────────────────────────────────────────
  // Only propagate trace headers to same-origin API calls.
  // Exclude Keycloak / external OIDC endpoints — they reject unknown CORS headers.
  const apiOrigin = (import.meta as ImportMeta & { env: Record<string, string> }).env
    ?.VITE_API_BASE_URL ?? 'http://localhost:8000';
  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        propagateTraceHeaderCorsUrls: [new RegExp(`^${apiOrigin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)],
        clearTimingResources: true,
      }),
    ],
  });

  // ── Core Web Vitals ────────────────────────────────────────────────
  if (config.metrics_enabled) {
    _recordWebVitals(config.service_name);
  }
}

// ------------------------------------------------------------------
// Internal helpers
// ------------------------------------------------------------------

/**
 * Lazily import web-vitals and record LCP, FID/FCP, and CLS as
 * OTEL histogram observations on the global MeterProvider.
 */
async function _recordWebVitals(serviceName: string): Promise<void> {
  try {
    const { onLCP, onFID, onCLS, onFCP } = await import('web-vitals');
    const meter = metrics.getMeter(serviceName);

    const lcpHistogram = meter.createHistogram('web_vital.lcp', {
      description: 'Largest Contentful Paint (ms)',
      unit: 'ms',
    });

    const fidHistogram = meter.createHistogram('web_vital.fid', {
      description: 'First Input Delay (ms)',
      unit: 'ms',
    });

    const clsHistogram = meter.createHistogram('web_vital.cls', {
      description: 'Cumulative Layout Shift (score x 1000)',
      unit: '1',
    });

    const fcpHistogram = meter.createHistogram('web_vital.fcp', {
      description: 'First Contentful Paint (ms)',
      unit: 'ms',
    });

    onLCP((metric: Metric) => lcpHistogram.record(metric.value));
    onFID((metric: Metric) => fidHistogram.record(metric.value));
    onCLS((metric: Metric) => clsHistogram.record(metric.value * 1000));
    onFCP((metric: Metric) => fcpHistogram.record(metric.value));
  } catch (err) {
    // web-vitals is optional — do not crash the app if it fails
    console.warn('[telemetry] web-vitals recording failed:', err);
  }
}
