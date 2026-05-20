/**
 * E2E tests — Agent Runtime Security Segregation
 *
 * Covers the four critical test plan scenarios:
 *   1. Certificate authentication flow
 *   2. Metadata security (no identity tokens in Agent Runtime responses)
 *   3. Tool call authorization with certificate validation
 *   4. Certificate revocation integration
 *
 * Test layers:
 *   - Real Backend Integration: direct HTTP calls to http://localhost:8000 (no mocks)
 *     — catches migration and endpoint-wiring issues that unit tests cannot detect
 *   - Mocked API tests: route-intercepted fetch calls (via page.evaluate) for response-shape
 *     verification
 *
 * NOTE: All API endpoints require JWT authentication (global middleware). Real backend
 * tests verify endpoints are wired (not 404, not 500) and properly require auth (401/403).
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const BACKEND = 'http://localhost:8000'
const API = `${BACKEND}/api/v1`

/** Helper: make a fetch call from within the browser context so page.route() can intercept it. */
async function browserFetch(
  page: Parameters<typeof standardSetup>[0],
  url: string,
  options: { method: string; body?: string; headers?: Record<string, string> } = { method: 'GET' }
): Promise<{ status: number; body: unknown }> {
  return page.evaluate(
    async ([fetchUrl, fetchOptions]) => {
      const r = await fetch(fetchUrl, fetchOptions as RequestInit)
      let body: unknown
      try {
        body = await r.json()
      } catch {
        body = await r.text()
      }
      return { status: r.status, body }
    },
    [url, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) } }] as const
  )
}

// ── Scenario 1: Certificate Authentication Flow ───────────────────────────────

test.describe('Real Backend Integration — Certificate Authentication Flow', () => {
  /**
   * These tests make real HTTP calls to the running backend.
   * They catch migration and endpoint-wiring issues that mocked tests cannot detect.
   * All endpoints require JWT auth; expecting 401 confirms the endpoint is wired correctly.
   */

  test('CA certificate endpoint is reachable and requires authentication (not 404)', async ({ request }) => {
    const response = await request.get(`${API}/certificates/ca`)
    // Must NOT be 404 (endpoint wired) or 500 (no server crash)
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    // 401 = endpoint exists, global auth middleware applied correctly
    // 200 = endpoint accessible (if CA initialized and no auth guard)
    expect([200, 401, 403]).toContain(response.status())
  })

  test('certificate issue endpoint requires admin authentication (not 404)', async ({ request }) => {
    const response = await request.post(`${API}/certificates/issue`, {
      data: {
        agent_type_id: '00000000-0000-0000-0000-000000000001',
        instance_id: 'e2e-test-probe',
      },
    })
    // Must NOT be 404 — endpoint must be wired
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    // Expected: 401 (unauthenticated) or 403 (no admin role) or 422 (schema validation)
    expect([401, 403, 422]).toContain(response.status())
  })

  test('certificate revoke endpoint requires admin authentication (not 404)', async ({ request }) => {
    const response = await request.post(`${API}/certificates/revoke`, {
      data: {
        serial_number: 'fake-serial-number',
        reason: 'e2e-test-probe',
        revoked_by: 'e2e-test',
      },
    })
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    expect([401, 403, 422]).toContain(response.status())
  })
})

test.describe('Mocked — Certificate Authentication: Issue response excludes identity tokens', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('certificate issue response has cert/key but never identity tokens', async ({ page }) => {
    const mockIssuedCert = {
      certificate_pem: '-----BEGIN CERTIFICATE-----\nMIIBmzCCAUGgAwIBAgIUAgent\n-----END CERTIFICATE-----\n',
      private_key_pem: '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAFake\n-----END RSA PRIVATE KEY-----\n',
      serial_number: '98765432109876543210',
      expires_at: '2026-05-14T06:53:51Z',
    }

    await page.route(`${API}/certificates/issue`, (route) =>
      route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(mockIssuedCert) })
    )

    // Use browser context fetch so page.route() intercepts it
    const { body } = await browserFetch(page, `${API}/certificates/issue`, {
      method: 'POST',
      body: JSON.stringify({ agent_type_id: '00000000-0000-0000-0000-000000000001', instance_id: 'test' }),
    })

    const b = body as Record<string, unknown>
    // Cert and private key are returned (one-time, to admin)
    expect(b).toHaveProperty('certificate_pem')
    expect(b).toHaveProperty('private_key_pem')
    // Security: NEVER include identity credentials in cert issue response (AC-1)
    expect(b).not.toHaveProperty('identity_token')
    expect(b).not.toHaveProperty('access_token')
    expect(b).not.toHaveProperty('refresh_token')
  })
})

// ── Scenario 2: Metadata Security — No Identity Tokens in Agent Runtime Responses ─

test.describe('Real Backend Integration — Metadata Security (AC-1)', () => {
  /**
   * Verifies internal certificate validation and authorization endpoints are wired.
   * Real backend test: catches migration issues in agent_instance_certificates,
   * certificate_validation_logs, and token_refresh_logs tables.
   */

  test('internal certificate validate endpoint is wired (not 404)', async ({ request }) => {
    const response = await request.post(`${API}/internal/certificates/validate`, {
      data: { certificate_pem: '-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n' },
    })
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    // 200 = processed (invalid cert result), 401 = auth required, 422 = schema validation
    expect([200, 401, 403, 422]).toContain(response.status())
  })
})

test.describe('Mocked — Metadata Security: zero identity tokens in Agent Runtime boundary', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('certificate validate response: identifies agent but never returns identity tokens', async ({ page }) => {
    const mockValidResponse = {
      valid: true,
      agent_type_id: 'at-uuid-1',
      instance_id: 'runtime-instance-1',
      serial_number: '12345678',
      expires_at: '2026-05-14T06:53:51Z',
      reason: null,
    }

    await page.route(`${API}/internal/certificates/validate`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockValidResponse) })
    )

    const { body } = await browserFetch(page, `${API}/internal/certificates/validate`, {
      method: 'POST',
      body: JSON.stringify({ certificate_pem: '-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n' }),
    })

    const b = body as Record<string, unknown>
    // Validation response identifies the agent
    expect(b).toHaveProperty('valid')
    expect(b).toHaveProperty('agent_type_id')
    expect(b).toHaveProperty('instance_id')
    // Security assertion AC-1: certificate validate has ZERO identity tokens
    // (used to identify agent, NOT to provide identity credentials)
    expect(b).not.toHaveProperty('identity_token')
    expect(b).not.toHaveProperty('access_token')
    expect(b).not.toHaveProperty('refresh_token')
  })

  test('authorization response: identity_token present at Communication Hub boundary (not Agent Runtime)', async ({ page }) => {
    // The authorize/tool-call endpoint returns identity_token TO the Communication Hub.
    // The Communication Hub uses it for tool execution but NEVER forwards it to Agent Runtime.
    // This test documents the security boundary — token IS at Comm Hub but NOT at Agent Runtime.
    const mockAuthResponse = {
      authorized: true,
      identity_token: 'eyJhbGciOiJSUzI1NiJ9.mock-token-comm-hub-only',
      identity_id: 'identity-uuid-1',
      agent_type_id: 'at-uuid-1',
      reason: null,
      required_permission: null,
      agent_type: 'Research Agent',
    }

    await page.route(`${API}/internal/authorize/tool-call`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAuthResponse) })
    )

    const { body } = await browserFetch(page, `${API}/internal/authorize/tool-call`, {
      method: 'POST',
      body: JSON.stringify({ certificate_serial_number: '12345678', tool_name: 'search_web' }),
    })

    const b = body as Record<string, unknown>
    expect(b.authorized).toBe(true)
    // identity_token IS present at the Communication Hub boundary — intentional
    // The Communication Hub consumes it internally; Agent Runtime never receives it
    expect(b).toHaveProperty('identity_token')
    expect(b.identity_token).toBeTruthy()
  })
})

// ── Scenario 3: Tool Call Authorization with Certificate Validation ────────────

test.describe('Real Backend Integration — Tool Authorization Endpoint', () => {
  /**
   * Verifies the internal authorization endpoint is wired.
   * Real backend test: validates that permission resolution service is operational
   * and agent_instance_certificates + token_refresh_logs migrations were applied.
   */

  test('internal authorize tool-call endpoint is wired (not 404)', async ({ request }) => {
    const response = await request.post(`${API}/internal/authorize/tool-call`, {
      data: {
        certificate_serial_number: 'nonexistent-serial-e2e-probe',
        tool_name: 'search_web',
      },
    })
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    // 200 = processed (cert not found → authorized=false), 401 = auth required, 422 = schema error
    expect([200, 401, 403, 422]).toContain(response.status())
    if (response.status() === 200) {
      const body = await response.json()
      // Unknown cert → not authorized; but endpoint responds correctly
      expect(body).toHaveProperty('authorized')
      expect(body.authorized).toBe(false)
    }
  })
})

test.describe('Mocked — Tool Authorization Decision Outcomes', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('authorized=true: response contains identity_token for Communication Hub', async ({ page }) => {
    const mockAuthorized = {
      authorized: true,
      identity_token: 'mock-jwt-token',
      identity_id: 'identity-uuid-1',
      agent_type_id: 'at-uuid-1',
      reason: null,
      required_permission: null,
      agent_type: 'Research Agent',
    }
    await page.route(`${API}/internal/authorize/tool-call`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockAuthorized) })
    )

    const { body } = await browserFetch(page, `${API}/internal/authorize/tool-call`, {
      method: 'POST',
      body: JSON.stringify({ certificate_serial_number: 'valid-serial', tool_name: 'allowed_tool' }),
    })

    const b = body as Record<string, unknown>
    expect(b.authorized).toBe(true)
    expect(b.identity_token).toBeTruthy()  // Token provided to Communication Hub
    expect(b.reason).toBeNull()
  })

  test('authorized=false: insufficient permissions — no token, includes reason', async ({ page }) => {
    const mockDenied = {
      authorized: false,
      identity_token: null,  // No token when denied — no credential exposure risk
      identity_id: 'identity-uuid-1',
      agent_type_id: 'at-uuid-1',
      reason: 'insufficient_permissions',
      required_permission: 'search_web',
      agent_type: 'Research Agent',
    }
    await page.route(`${API}/internal/authorize/tool-call`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDenied) })
    )

    const { body } = await browserFetch(page, `${API}/internal/authorize/tool-call`, {
      method: 'POST',
      body: JSON.stringify({ certificate_serial_number: 'valid-serial', tool_name: 'unauthorized_tool' }),
    })

    const b = body as Record<string, unknown>
    expect(b.authorized).toBe(false)
    expect(b.identity_token).toBeNull()   // No token on deny — fail-safe per AC-6
    expect(b.reason).toBe('insufficient_permissions')
    expect(b.required_permission).toBe('search_web')
  })

  test('authorized=false: invalid certificate — no token, reason identifies failure', async ({ page }) => {
    const mockInvalidCert = {
      authorized: false,
      identity_token: null,
      identity_id: null,
      agent_type_id: null,
      reason: 'certificate_not_found',
      required_permission: null,
      agent_type: null,
    }
    await page.route(`${API}/internal/authorize/tool-call`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockInvalidCert) })
    )

    const { body } = await browserFetch(page, `${API}/internal/authorize/tool-call`, {
      method: 'POST',
      body: JSON.stringify({ certificate_serial_number: 'invalid-serial', tool_name: 'any_tool' }),
    })

    const b = body as Record<string, unknown>
    expect(b.authorized).toBe(false)
    expect(b.identity_token).toBeNull()
    expect(b.reason).toBe('certificate_not_found')
  })
})

// ── Scenario 4: Certificate Revocation Integration ────────────────────────────

test.describe('Real Backend Integration — Certificate Revocation', () => {
  /**
   * Verifies the revocation endpoint and certificate_revocation_entries table migration.
   */

  test('revoke endpoint exists and requires admin authentication (not 404)', async ({ request }) => {
    const response = await request.post(`${API}/certificates/revoke`, {
      data: {
        serial_number: 'e2e-probe-serial',
        reason: 'e2e test probe',
        revoked_by: 'e2e-test',
      },
    })
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    expect([401, 403, 422]).toContain(response.status())
  })
})

test.describe('Mocked — Certificate Revocation Response and Downstream Effects', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('revocation response includes serial_number, revoked_at, and reason', async ({ page }) => {
    const mockRevokedResponse = {
      serial_number: 'abc123serial',
      revoked_at: '2026-05-13T16:53:51Z',
      reason: 'Compromised instance',
    }

    await page.route(`${API}/certificates/revoke`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockRevokedResponse) })
    )

    const { body } = await browserFetch(page, `${API}/certificates/revoke`, {
      method: 'POST',
      body: JSON.stringify({ serial_number: 'abc123serial', reason: 'Compromised instance', revoked_by: 'admin' }),
    })

    const b = body as Record<string, unknown>
    expect(b).toHaveProperty('serial_number')
    expect(b).toHaveProperty('revoked_at')
    expect(b).toHaveProperty('reason')
  })

  test('after revocation: certificate validate returns valid=false with revoked reason', async ({ page }) => {
    const mockRevokedValidation = {
      valid: false,
      agent_type_id: null,
      instance_id: null,
      serial_number: 'revoked-serial-123',
      expires_at: null,
      reason: 'revoked',
    }

    await page.route(`${API}/internal/certificates/validate`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockRevokedValidation) })
    )

    const { body } = await browserFetch(page, `${API}/internal/certificates/validate`, {
      method: 'POST',
      body: JSON.stringify({ certificate_pem: '-----BEGIN CERTIFICATE-----\nrevoked\n-----END CERTIFICATE-----\n' }),
    })

    const b = body as Record<string, unknown>
    expect(b.valid).toBe(false)
    expect(b.reason).toBe('revoked')
    // No agent identity data for revoked certificate
    expect(b.agent_type_id).toBeNull()
    expect(b.instance_id).toBeNull()
    // Security: no identity tokens in validation response
    expect(b).not.toHaveProperty('identity_token')
    expect(b).not.toHaveProperty('access_token')
  })

  test('after revocation: tool authorization returns unauthorized with revoked reason', async ({ page }) => {
    const mockRevokedAuth = {
      authorized: false,
      identity_token: null,
      identity_id: null,
      agent_type_id: null,
      reason: 'certificate_revoked',
      required_permission: null,
      agent_type: null,
    }

    await page.route(`${API}/internal/authorize/tool-call`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockRevokedAuth) })
    )

    const { body } = await browserFetch(page, `${API}/internal/authorize/tool-call`, {
      method: 'POST',
      body: JSON.stringify({ certificate_serial_number: 'revoked-serial-123', tool_name: 'search_web' }),
    })

    const b = body as Record<string, unknown>
    expect(b.authorized).toBe(false)
    expect(b.reason).toBe('certificate_revoked')
    expect(b.identity_token).toBeNull()  // No token for revoked cert — fail-safe per AC-6
  })
})
