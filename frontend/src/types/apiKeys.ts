/** TypeScript types for the API Key Management module. */

export enum ApiKeyStatus {
  Active = 'active',
  Revoked = 'revoked',
}

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  agent_identity_id: string
  agent_identity_name: string
  agent_role_id: string
  agent_role_name: string
  status: ApiKeyStatus
  created_at: string
  last_used_at: string | null
  expires_at: string | null
}

export interface ApiKeyCreateRequest {
  name: string
  agent_identity_id: string
  agent_role_id: string
  expires_at?: string | null
}

export interface ApiKeyCreateResponse {
  id: string
  name: string
  key_prefix: string
  api_key: string
  agent_identity_id: string
  agent_identity_name: string
  agent_role_id: string
  agent_role_name: string
  expires_at: string | null
  created_at: string
}

export interface ApiKeyRevokeResponse {
  id: string
  status: string
  message: string
}

export interface ApiKeyDeleteResponse {
  id: string
  message: string
}

export interface RoleItem {
  role_id: string
  role_name: string
}

export interface IdentityWithRoles {
  identity_id: string
  identity_name: string
  roles: RoleItem[]
}
