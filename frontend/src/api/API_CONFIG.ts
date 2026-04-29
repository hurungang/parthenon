/**
 * Centralized API configuration constants.
 * All API calls must use these values — never hardcode base URLs.
 */

export const API_CONFIG = {
  BASE_URL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  WS_BASE_URL: import.meta.env.VITE_WS_BASE_URL ?? '/ws',
  TIMEOUT_MS: 30_000,
} as const
