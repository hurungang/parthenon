/**
 * Centralized API configuration constants.
 * All API calls must use these values — never hardcode base URLs.
 */

export const API_CONFIG = {
  BASE_URL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  WS_BASE_URL: import.meta.env.VITE_WS_BASE_URL ?? '/ws',
  MCP_ENDPOINT: import.meta.env.VITE_MCP_ENDPOINT ?? 'http://localhost:8002/mcp',
  TIMEOUT_MS: 30_000,
} as const
