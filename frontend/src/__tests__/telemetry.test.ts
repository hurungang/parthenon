/**
 * frontend/src/__tests__/telemetry.test.ts
 *
 * Unit tests for initTelemetry() and fetchTelemetryConfig().
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { FrontendTelemetryConfig } from '../api/telemetryApi'

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

const ENABLED_CONFIG: FrontendTelemetryConfig = {
  otlp_http_endpoint: 'http://localhost:4318',
  service_name: 'test-service',
  traces_enabled: true,
  metrics_enabled: true,
}

const DISABLED_CONFIG: FrontendTelemetryConfig = {
  otlp_http_endpoint: 'http://localhost:4318',
  service_name: 'test-service',
  traces_enabled: false,
  metrics_enabled: false,
}

// ------------------------------------------------------------------
// Hoisted mock functions — must be declared before vi.mock() calls
// because Vitest hoists vi.mock() to the top of the module.
// ------------------------------------------------------------------

const mockRegister = vi.hoisted(() => vi.fn())
const mockAddSpanProcessor = vi.hoisted(() => vi.fn())

// ------------------------------------------------------------------
// Module-level mocks (hoisted by Vitest transformer)
// ------------------------------------------------------------------

vi.mock('@opentelemetry/sdk-trace-web', () => ({
  WebTracerProvider: vi.fn().mockImplementation(() => ({
    addSpanProcessor: mockAddSpanProcessor,
    register: mockRegister,
  })),
}))
vi.mock('@opentelemetry/sdk-trace-base', () => ({
  BatchSpanProcessor: vi.fn(),
}))
vi.mock('@opentelemetry/exporter-trace-otlp-http', () => ({
  OTLPTraceExporter: vi.fn(),
}))
vi.mock('@opentelemetry/context-zone', () => ({
  ZoneContextManager: vi.fn(),
}))
vi.mock('@opentelemetry/instrumentation', () => ({
  registerInstrumentations: vi.fn(),
}))
vi.mock('@opentelemetry/instrumentation-fetch', () => ({
  FetchInstrumentation: vi.fn(),
}))
vi.mock('@opentelemetry/resources', () => ({
  Resource: vi.fn().mockImplementation(() => ({})),
}))
vi.mock('@opentelemetry/semantic-conventions', () => ({
  SEMRESATTRS_SERVICE_NAME: 'service.name',
}))
vi.mock('@opentelemetry/core', () => ({
  W3CTraceContextPropagator: vi.fn(),
}))

// ------------------------------------------------------------------
// initTelemetry() tests
// ------------------------------------------------------------------

describe('initTelemetry', () => {
  beforeEach(() => {
    // Reset module registry so _initialised flag is cleared between tests
    vi.resetModules()
    mockRegister.mockReset()
    mockAddSpanProcessor.mockReset()
  })

  it('registers OTEL providers when traces_enabled=true', async () => {
    const { initTelemetry } = await import('../telemetry')
    initTelemetry(ENABLED_CONFIG)

    expect(mockRegister).toHaveBeenCalledOnce()
  })

  it('returns without registering providers when traces_enabled=false', async () => {
    const { initTelemetry } = await import('../telemetry')
    initTelemetry(DISABLED_CONFIG)

    expect(mockRegister).not.toHaveBeenCalled()
  })

  it('is a no-op on second call (guard against double-init)', async () => {
    const { initTelemetry } = await import('../telemetry')
    initTelemetry(ENABLED_CONFIG)
    initTelemetry(ENABLED_CONFIG) // second call should be no-op

    // register() should only be called once
    expect(mockRegister).toHaveBeenCalledTimes(1)
  })
})

// ------------------------------------------------------------------
// fetchTelemetryConfig() tests
// ------------------------------------------------------------------

describe('fetchTelemetryConfig', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns config from backend on success', async () => {
    const mockConfig: FrontendTelemetryConfig = {
      otlp_http_endpoint: 'http://collector:4318',
      service_name: 'my-service',
      traces_enabled: true,
      metrics_enabled: true,
    }

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockConfig,
    } as Response)

    const { fetchTelemetryConfig } = await import('../api/telemetryApi')
    const result = await fetchTelemetryConfig()

    expect(result.service_name).toBe('my-service')
    expect(result.traces_enabled).toBe(true)
  })

  it('returns safe default when fetch fails (network error)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))

    const { fetchTelemetryConfig } = await import('../api/telemetryApi')
    const result = await fetchTelemetryConfig()

    expect(result.traces_enabled).toBe(false)
    expect(result.metrics_enabled).toBe(false)
  })

  it('returns safe default when backend returns non-200', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Not authenticated' }),
    } as Response)

    const { fetchTelemetryConfig } = await import('../api/telemetryApi')
    const result = await fetchTelemetryConfig()

    expect(result.traces_enabled).toBe(false)
  })

  it('returns safe default when backend returns 500', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: 'Internal error' }),
    } as Response)

    const { fetchTelemetryConfig } = await import('../api/telemetryApi')
    const result = await fetchTelemetryConfig()

    expect(result.traces_enabled).toBe(false)
    expect(result.otlp_http_endpoint).toBe('http://localhost:4318')
  })
})
