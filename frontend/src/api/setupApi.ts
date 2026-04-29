/**
 * Typed API client functions for the Setup endpoints.
 * Uses the project's configured axios instance (apiClient).
 */
import apiClient from './apiClient'
import type { IdentityStatusResponse, ProviderSetupRequest, ProviderSetupResult } from '../types/setup'

/**
 * Query the current identity provider setup state.
 * Calls GET /setup/identity-status (no auth required).
 */
export async function getIdentityStatus(): Promise<IdentityStatusResponse> {
  const response = await apiClient.get<IdentityStatusResponse>('/setup/identity-status')
  return response.data
}

/**
 * Provision the identity provider.
 * Calls POST /setup/identity (no auth required).
 *
 * @throws AxiosError with status 409 if already configured.
 * @throws AxiosError with status 502 if the Keycloak Admin API is unreachable.
 */
export async function postSetupIdentity(
  request: ProviderSetupRequest,
): Promise<ProviderSetupResult> {
  const response = await apiClient.post<ProviderSetupResult>('/setup/identity', request)
  return response.data
}
