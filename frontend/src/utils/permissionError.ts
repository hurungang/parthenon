/**
 * Utilities for parsing and surfacing structured permission-denied (403) errors.
 *
 * When the backend returns a 403 with a `required_permission` body, this module
 * parses that body and dispatches a browser custom event so any mounted
 * PermissionErrorSnackbar can display a targeted "Access Denied" message.
 */
import type { AxiosError } from 'axios'

export interface RequiredPermission {
  resource_type: string
  action: string
  resource_id?: string | null
}

export interface PermissionDeniedDetail {
  detail: string
  required_permission: RequiredPermission
}

/** Event name used to broadcast structured 403 errors across the app. */
export const PERMISSION_DENIED_EVENT = 'parthenon:permissionDenied'

/**
 * Extract a `PermissionDeniedDetail` from an Axios error, or return null
 * if the error is not a 403 or does not carry the structured body.
 */
export function parsePermissionError(error: unknown): PermissionDeniedDetail | null {
  const axiosError = error as AxiosError<unknown>
  if (axiosError?.response?.status !== 403) return null
  const data = axiosError.response.data as Record<string, unknown>
  if (data && typeof data === 'object' && 'required_permission' in data) {
    const rp = data.required_permission as Record<string, unknown>
    if (rp && typeof rp.resource_type === 'string' && typeof rp.action === 'string') {
      return {
        detail: typeof data.detail === 'string' ? data.detail : 'Permission denied.',
        required_permission: {
          resource_type: rp.resource_type,
          action: rp.action,
          resource_id: typeof rp.resource_id === 'string' ? rp.resource_id : null,
        },
      }
    }
  }
  return null
}

/**
 * Dispatch a custom DOM event so the global PermissionErrorSnackbar can
 * display the structured denial message without prop drilling.
 */
export function dispatchPermissionDeniedEvent(detail: PermissionDeniedDetail): void {
  window.dispatchEvent(new CustomEvent(PERMISSION_DENIED_EVENT, { detail }))
}
