import { useContext } from 'react'
import { AuthContext } from './AuthContext'

/**
 * Consumer hook for AuthContext.
 * Exposes login, logout, token, claims, and isAuthenticated.
 */
export function useAuthStore() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuthStore must be used within an AuthProvider')
  }
  return ctx
}
