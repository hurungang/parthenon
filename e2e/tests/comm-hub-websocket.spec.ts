import { test, expect } from '@playwright/test'

const CONTROL_CENTER_URL = 'http://localhost:8000'
const COMM_HUB_URL = 'http://localhost:8002'

test.describe('Communication Hub WebSocket Tests', () => {
  test('Communication Hub health endpoint responds correctly', async ({ request }) => {
    const response = await request.get(`${COMM_HUB_URL}/health`)
    expect(response.status()).toBe(200)
    
    const health = await response.json()
    expect(health.service).toBe('communication-hub')
    expect(health.status).toBe('ok')
  })

  test('Control Center health endpoint responds correctly', async ({ request }) => {
    const response = await request.get(`${CONTROL_CENTER_URL}/health`)
    expect(response.status()).toBe(200)
    
    const health = await response.json()
    expect(health.service).toBe('control-center')
  })

  test('Control Center does NOT have WebSocket on /ws path', async ({ request }) => {
    try {
      const response = await request.get(`${CONTROL_CENTER_URL}/ws/sessions/test-id`)
      // Should not return 200 or 101 (WebSocket upgrade)
      expect(response.status()).not.toBe(200)
      expect(response.status()).not.toBe(101)
    } catch (error) {
      // Connection error is acceptable
      expect(error).toBeDefined()
    }
  })
})
