/**
 * frontend/src/api/telemetryApi.ts
 *
 * Fetches the telemetry configuration from the backend.
 * Returns a safe default on any failure — never throws.
 */

import { API_CONFIG } from './API_CONFIG'

export interface FrontendTelemetryConfig {
  otlp_http_endpoint: string
  service_name: string
  traces_enabled: boolean
  metrics_enabled: boolean
}

const SAFE_DEFAULT: FrontendTelemetryConfig = {
  otlp_http_endpoint: 'http://localhost:4318',
  service_name: 'parthenon-frontend',
  traces_enabled: false,
  metrics_enabled: false,
}

/**
 * Fetch the frontend-relevant telemetry config from the backend.
 *
 * On network failure, HTTP error, or parse error, returns `SAFE_DEFAULT`
 * (traces disabled) so telemetry never blocks app startup.
 */
export async function fetchTelemetryConfig(): Promise<FrontendTelemetryConfig> {
  try {
    const response = await fetch(`${API_CONFIG.BASE_URL}/telemetry/config`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    })

    if (!response.ok) {
      return SAFE_DEFAULT
    }

    const data = await response.json() as FrontendTelemetryConfig
    return data
  } catch {
    return SAFE_DEFAULT
  }
}
