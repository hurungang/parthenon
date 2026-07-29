
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import React from 'react'

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock window.location
const mockLocation = {
  href: '',
  origin: 'http://localhost:5173',
}
Object.defineProperty(window, 'location', {
  value: mockLocation,
  writable: true,
})

describe('AuthContext', () => {
  let AuthProvider: any
  let useAuthStore: any

  beforeEach(async () => {
    vi.clearAllMocks()
    mockLocation.href = ''

    // Mock fetch for provider discovery — default to no providers, no super admin
    const mockFetch = vi.fn()
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/system/identity-providers')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0 }),
        })
      }
      if (url.includes('/system/super-admin/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ is_enabled: false }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    globalThis.fetch = mockFetch as any

    // Setup localStorage mock
    const storage: Record<string, string> = {}
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key: string) => storage[key] ?? null)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key: string, value: string) => { storage[key] = value })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation((key: string) => { delete storage[key] })

    // Clear storage
    Object.keys(storage).forEach((k) => delete storage[k])

    const mod = await import('../stores/AuthContext')
    void mod.AuthContext
    AuthProvider = mod.AuthProvider

    const storeMod = await import('../stores/authStore')
    useAuthStore = storeMod.useAuthStore
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // -- Initial state tests --

  it('provider exposes isAuthenticated as false initially', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })
    expect(result.current.isAuthenticated).toBe(false)
  })

  it('provider exposes availableProviders initially null', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })
    expect(result.current.availableProviders).toBeNull()
  })

  it('provider exposes superAdminEnabled as false initially', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })
    expect(result.current.superAdminEnabled).toBe(false)
  })

  it('provider exposes isSuperAdmin as false initially', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })
    expect(result.current.isSuperAdmin).toBe(false)
  })

  // -- Token management tests --

  it('setToken updates the token and recognizes super admin', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    expect(result.current.token).toBe(token)
    expect(result.current.isSuperAdmin).toBe(true)
    expect(result.current.isAuthenticated).toBe(true)
  })

  it('setToken with non-super-admin token sets isSuperAdmin to false', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'user123', exp: now + 3600, iat: now, is_super_admin: false }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    expect(result.current.isSuperAdmin).toBe(false)
    expect(result.current.isAuthenticated).toBe(true)
  })

  it('setToken with expired token sets isAuthenticated to false', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    // Token expired 10 seconds ago
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now - 10, iat: now - 3600, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    expect(result.current.isAuthenticated).toBe(false)
  })

  it('stores token in localStorage when setToken called', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    expect(localStorage.setItem).toHaveBeenCalledWith('access_token', token)
  })

  // -- Logout tests --

  it('logout clears tokens from storage', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    // First set a token so isSuperAdmin is true (logout path differs)
    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    expect(result.current.isAuthenticated).toBe(true)

    // Logout
    act(() => {
      result.current.logout()
    })

    expect(localStorage.removeItem).toHaveBeenCalledWith('access_token')
    expect(localStorage.removeItem).toHaveBeenCalledWith('refresh_token')
    expect(localStorage.removeItem).toHaveBeenCalledWith('super_admin_token')
  })

  it('logout clears token from state', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })
    act(() => {
      result.current.logout()
    })

    expect(result.current.token).toBeNull()
    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.isSuperAdmin).toBe(false)
  })

  it('logout resets availableProviders to null', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })
    act(() => {
      result.current.logout()
    })

    expect(result.current.availableProviders).toBeNull()
  })

  it('logout resets superAdminEnabled to false', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })
    act(() => {
      result.current.logout()
    })

    expect(result.current.superAdminEnabled).toBe(false)
  })

  it('super admin logout redirects to /login', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now, is_super_admin: true }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })
    act(() => {
      result.current.logout()
    })

    expect(mockLocation.href).toBe('/login')
  })

  it('non-super-admin logout redirects to Keycloak logout', () => {
    // Set an id_token for the OIDC logout flow
    localStorage.setItem('id_token', 'test-id-token')

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    // Non-super-admin token
    const payload = btoa(JSON.stringify({ sub: 'user123', exp: now + 3600, iat: now, is_super_admin: false }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    // Confirm isSuperAdmin is false because token has no is_super_admin=true claim
    expect(result.current.isSuperAdmin).toBe(false)

    act(() => {
      result.current.logout()
    })

    // Should redirect to OIDC logout (contains protocol/openid-connect/logout)
    expect(mockLocation.href).toContain('protocol/openid-connect/logout')
    expect(mockLocation.href).toContain('localhost:8082')
  })

  // -- Provider discovery tests --

  it('discovers providers and super admin status on mount', async () => {
    const mockFetch = vi.fn()
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/system/identity-providers')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            items: [
              { provider_scope: 'user', provider_type: 'oidc_generic', display_name: 'User OIDC', is_enabled: true },
            ],
            total: 1,
          }),
        })
      }
      if (url.includes('/system/super-admin/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ is_enabled: true }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    globalThis.fetch = mockFetch as any

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    await waitFor(() => {
      expect(result.current.availableProviders).not.toBeNull()
    })

    expect(result.current.superAdminEnabled).toBe(true)
    expect(result.current.availableProviders).toHaveLength(1)
    expect(result.current.availableProviders![0].scope).toBe('user')
    expect(result.current.availableProviders![0].displayName).toBe('User OIDC')
  })

  it('handles failed provider discovery gracefully', async () => {
    const mockFetch = vi.fn()
    mockFetch.mockRejectedValue(new Error('Network error'))
    globalThis.fetch = mockFetch as any

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    // Should not crash; component renders without throwing
    await waitFor(() => {
      expect(result.current.isAuthenticated).toBe(false)
    })
  })

  it('handles failed super admin status discovery gracefully', async () => {
    const mockFetch = vi.fn()
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/system/identity-providers')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0 }),
        })
      }
      if (url.includes('/system/super-admin/status')) {
        return Promise.reject(new Error('Network error'))
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    globalThis.fetch = mockFetch as any

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    await waitFor(() => {
      // Should still have initial state
      expect(result.current.superAdminEnabled).toBe(false)
    })
  })

  it('maps multiple providers correctly', async () => {
    const mockFetch = vi.fn()
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/system/identity-providers')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            items: [
              { provider_scope: 'user', provider_type: 'oidc_generic', display_name: 'User SSO', is_enabled: true },
              { provider_scope: 'agent', provider_type: 'keycloak', display_name: 'Agent KC', is_enabled: true },
            ],
            total: 2,
          }),
        })
      }
      if (url.includes('/system/super-admin/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ is_enabled: false }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    globalThis.fetch = mockFetch as any

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    await waitFor(() => {
      expect(result.current.availableProviders).toHaveLength(2)
    })
    expect(result.current.availableProviders![0].scope).toBe('user')
    expect(result.current.availableProviders![1].scope).toBe('agent')
  })

  it('re-discovers providers when token changes', async () => {
    let fetchCallCount = 0
    const mockFetch = vi.fn()
    mockFetch.mockImplementation((url: string) => {
      fetchCallCount++
      if (url.includes('/system/identity-providers')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ items: [], total: 0 }),
        })
      }
      if (url.includes('/system/super-admin/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ is_enabled: false }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    globalThis.fetch = mockFetch as any

    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    await waitFor(() => {
      expect(fetchCallCount).toBeGreaterThan(0)
    })

    const initialCallCount = fetchCallCount

    // Set a new token — this should trigger re-discovery
    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({ sub: 'admin', exp: now + 3600, iat: now }))
    const token = `${header}.${payload}.signature`

    act(() => {
      result.current.setToken(token)
    })

    await waitFor(() => {
      expect(fetchCallCount).toBeGreaterThan(initialCallCount)
    })
  })

  // -- isSuperAdmin detection tests --

  it('detects is_super_admin from JWT claims', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({
      sub: 'super_admin:admin',
      username: 'admin',
      is_super_admin: true,
      exp: now + 900,
    }))
    const token = `${header}.${payload}.sig`

    act(() => {
      result.current.setToken(token)
    })

    expect(result.current.isSuperAdmin).toBe(true)
  })

  it('detects normal user (not super admin) from JWT claims', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    const now = Math.floor(Date.now() / 1000)
    const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    const payload = btoa(JSON.stringify({
      sub: 'user123',
      name: 'Normal User',
      exp: now + 900,
    }))
    const token = `${header}.${payload}.sig`

    act(() => {
      result.current.setToken(token)
    })

    expect(result.current.isSuperAdmin).toBe(false)
    expect(result.current.isAuthenticated).toBe(true)
  })

  it('handles malformed JWT gracefully', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    act(() => {
      result.current.setToken('not-a-jwt-at-all')
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.isSuperAdmin).toBe(false)
    expect(result.current.claims).toBeNull()
  })

  it('handles empty token gracefully', () => {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(AuthProvider, null, children)
    const { result } = renderHook(() => useAuthStore(), { wrapper })

    // Token is initially null
    expect(result.current.token).toBeNull()
    expect(result.current.claims).toBeNull()
    expect(result.current.isAuthenticated).toBe(false)
  })
})
