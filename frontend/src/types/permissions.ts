/**
 * TypeScript types and enums for the Permission Management module.
 */

export const PolicyEffect = {
  Allow: 'allow',
  Deny: 'deny',
} as const
export type PolicyEffect = (typeof PolicyEffect)[keyof typeof PolicyEffect]

export enum TagScope {
  Global = 'global',
  ResourceType = 'resource_type',
}

export enum AccessRequestStatus {
  Pending = 'pending',
  Approved = 'approved',
  Rejected = 'rejected',
}

export interface TagValue {
  id: string
  tag_definition_id: string
  value: string
  created_at: string
}

export interface TagDefinition {
  id: string
  key: string
  scope: TagScope
  resource_type?: string
  description?: string
  allowed_values: TagValue[]
  created_at: string
  updated_at: string
}

export interface TagDefinitionCreate {
  key: string
  scope: TagScope
  resource_type?: string
  description?: string
  allowed_values: string[]
}

export interface TagDefinitionUpdate {
  description?: string
  add_values?: string[]
  remove_values?: string[]
}

export interface PolicyAction {
  id: string
  action: string
}

export interface PolicyResource {
  id: string
  resource_type: string
  resource_id: string | null
}

export interface PolicyTagCondition {
  id: string
  tag_key: string
  tag_value: string
}

export interface PolicyStatement {
  id: string
  effect: PolicyEffect
  module: string
  created_at: string
  actions: PolicyAction[]
  resources: PolicyResource[]
  tag_conditions: PolicyTagCondition[]
}

export interface PolicyStatementCreate {
  effect: PolicyEffect
  module: string
  actions: { action: string }[]
  resources: { resource_type: string; resource_id?: string | null }[]
  tag_conditions: { tag_key: string; tag_value: string }[]
}

export interface Role {
  id: string
  name: string
  description?: string
  is_active: boolean
  is_system: boolean
  role_type: 'system' | 'user_defined'
  created_at: string
  updated_at: string
  policy_count: number
  user_assignment_count: number
  group_assignment_count: number
  policies?: PolicyStatement[]
  policy_statements?: PolicyStatement[]
}

export interface RoleCreate {
  name: string
  description?: string
}

export interface RoleUpdate {
  name?: string
  description?: string
}

export interface PlatformUser {
  id: string
  sub: string
  email: string
  display_name: string
  first_seen_at: string
  last_seen_at: string
  direct_role_count: number
  group_count: number
}

export interface GroupMembership {
  group_id: string
  group_name: string
  joined_at: string
  join_reason?: string
}

export interface PlatformUserDetail extends PlatformUser {
  direct_roles: Role[]
  group_memberships: GroupMembership[]
}

export interface Group {
  id: string
  name: string
  description?: string
  owner_id?: string
  owner_display_name?: string
  idp_claim_value?: string
  created_at: string
  updated_at: string
  member_count: number
  role_count: number
}

export interface GroupCreate {
  name: string
  description?: string
  owner_id?: string
  idp_claim_value?: string
  role_ids?: string[]
}

export interface GroupUpdate {
  name?: string
  description?: string
  owner_id?: string
  idp_claim_value?: string
}

export interface GroupMember {
  user_id: string
  group_id: string
  display_name: string
  email: string
  joined_at: string
  join_reason?: string
}

export interface AccessRequest {
  id: string
  batch_id: string
  user_id: string
  group_id: string
  status: AccessRequestStatus
  reviewer_id?: string
  reviewer_reason?: string
  created_at: string
  updated_at: string
  group_name?: string
  requester_display_name?: string
}

export interface AccessRequestBatch {
  id: string
  user_id: string
  justification: string
  submitted_at: string
  requests: AccessRequest[]
}

export interface RoleCloneCreate {
  name: string
  description?: string
}

export interface ResourceTypeDef {
  resource_type: string
  actions: string[]
}
