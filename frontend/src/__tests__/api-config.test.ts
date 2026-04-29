import { describe, it, expect } from 'vitest'

/**
 * Tests for CredentialVault equivalent in frontend:
 * Verifies API_CONFIG constants are properly typed.
 */
describe('API_CONFIG', () => {
  it('should export BASE_URL as a string', async () => {
    const { API_CONFIG } = await import('../api/API_CONFIG')
    expect(typeof API_CONFIG.BASE_URL).toBe('string')
  })

  it('should export WS_BASE_URL as a string', async () => {
    const { API_CONFIG } = await import('../api/API_CONFIG')
    expect(typeof API_CONFIG.WS_BASE_URL).toBe('string')
  })

  it('should export TIMEOUT_MS as a positive number', async () => {
    const { API_CONFIG } = await import('../api/API_CONFIG')
    expect(API_CONFIG.TIMEOUT_MS).toBeGreaterThan(0)
  })
})
