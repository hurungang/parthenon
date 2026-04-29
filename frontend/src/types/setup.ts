/**
 * TypeScript types matching the backend Pydantic schemas for the Setup API.
 */

export enum SetupState {
  NOT_CONFIGURED = 'NOT_CONFIGURED',
  CONFIGURED = 'CONFIGURED',
  IN_PROGRESS = 'IN_PROGRESS',
}

export enum ProviderType {
  KEYCLOAK_BUNDLED = 'keycloak_bundled',
  KEYCLOAK_EXTERNAL = 'keycloak_external',
  AZURE_ENTRAID = 'azure_entraid',
}

export interface IdentityStatusResponse {
  setup_state: SetupState
  provider_type: string | null
  oidc_provider_url: string | null
}

export interface ProviderSetupRequest {
  provider_type: ProviderType
  // Keycloak-specific
  keycloak_url?: string
  realm_name?: string
  client_id?: string
  admin_user?: string
  admin_password?: string
  initial_admin_password?: string
  // External OIDC
  client_secret?: string
  oidc_discovery_url?: string
  // Re-configure guard
  force_reconfigure?: boolean
}

export interface ProviderSetupResult {
  success: boolean
  provider_type: string
  oidc_provider_url: string | null
  realm_name: string | null
  client_id: string | null
  error_code: string | null
  detail: string | null
}
