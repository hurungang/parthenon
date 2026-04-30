/**
 * Typed API client functions for the Permission Management module.
 * All functions use the shared apiClient with centralized base URL.
 */
import apiClient from './apiClient'
import type {
  AccessRequest,
  AccessRequestBatch,
  Group,
  GroupCreate,
  GroupMember,
  GroupUpdate,
  PlatformUser,
  PlatformUserDetail,
  PolicyStatement,
  PolicyStatementCreate,
  ResourceTypeDef,
  Role,
  RoleCloneCreate,
  RoleCreate,
  RoleUpdate,
  TagDefinition,
  TagDefinitionCreate,
  TagDefinitionUpdate,
} from '../types/permissions'

// ── Tags ──────────────────────────────────────────────────────────────────────

export async function listTagDefinitions(
  filters?: { scope?: string; resource_type?: string }
): Promise<TagDefinition[]> {
  const response = await apiClient.get<TagDefinition[]>('/user-tags/definitions', { params: filters })
  return response.data
}

export async function createTagDefinition(data: TagDefinitionCreate): Promise<TagDefinition> {
  const response = await apiClient.post<TagDefinition>('/user-tags/definitions', data)
  return response.data
}

export async function updateTagDefinition(
  id: string,
  data: TagDefinitionUpdate
): Promise<TagDefinition> {
  const response = await apiClient.patch<TagDefinition>(`/user-tags/definitions/${id}`, data)
  return response.data
}

export async function deleteTagDefinition(id: string): Promise<void> {
  await apiClient.delete(`/user-tags/definitions/${id}`)
}

// ── Roles ─────────────────────────────────────────────────────────────────────

export async function listRoles(page = 1, pageSize = 20): Promise<Role[]> {
  const response = await apiClient.get<Role[]>('/user-roles', { params: { page, page_size: pageSize } })
  return response.data
}

export async function createRole(data: RoleCreate): Promise<Role> {
  const response = await apiClient.post<Role>('/user-roles', data)
  return response.data
}

export async function getRole(id: string): Promise<Role> {
  const response = await apiClient.get<Role>(`/user-roles/${id}`)
  return response.data
}

export async function updateRole(id: string, data: RoleUpdate): Promise<Role> {
  const response = await apiClient.patch<Role>(`/user-roles/${id}`, data)
  return response.data
}

export async function deleteRole(id: string, force = false): Promise<void> {
  await apiClient.delete(`/user-roles/${id}`, { params: { force } })
}

export async function listRolePolicies(roleId: string): Promise<PolicyStatement[]> {
  const response = await apiClient.get<PolicyStatement[]>(`/user-roles/${roleId}/policies`)
  return response.data
}

export async function createPolicyStatement(
  roleId: string,
  data: PolicyStatementCreate
): Promise<PolicyStatement> {
  const response = await apiClient.post<PolicyStatement>(`/user-roles/${roleId}/policies`, data)
  return response.data
}

export async function deletePolicyStatement(roleId: string, policyId: string): Promise<void> {
  await apiClient.delete(`/user-roles/${roleId}/policies/${policyId}`)
}

export async function updatePolicyStatement(
  roleId: string,
  policyId: string,
  data: PolicyStatementCreate
): Promise<PolicyStatement> {
  const response = await apiClient.patch<PolicyStatement>(
    `/user-roles/${roleId}/policies/${policyId}`,
    data
  )
  return response.data
}

// ── Policy catalogue ──────────────────────────────────────────────────────────

export async function listResourceTypes(): Promise<ResourceTypeDef[]> {
  const response = await apiClient.get<ResourceTypeDef[]>('/policy/resource-types')
  return response.data
}

export async function cloneRole(sourceId: string, data: RoleCloneCreate): Promise<Role> {
  const response = await apiClient.post<Role>(`/user-roles/${sourceId}/clone`, data)
  return response.data
}

// ── Groups ────────────────────────────────────────────────────────────────────

export async function listGroups(page = 1, pageSize = 20): Promise<Group[]> {
  const response = await apiClient.get<Group[]>('/user-groups', { params: { page, page_size: pageSize } })
  return response.data
}

export async function createGroup(data: GroupCreate): Promise<Group> {
  const response = await apiClient.post<Group>('/user-groups', data)
  return response.data
}

export async function getGroup(id: string): Promise<Group> {
  const response = await apiClient.get<Group>(`/user-groups/${id}`)
  return response.data
}

export async function updateGroup(id: string, data: GroupUpdate): Promise<Group> {
  const response = await apiClient.patch<Group>(`/user-groups/${id}`, data)
  return response.data
}

export async function deleteGroup(id: string): Promise<void> {
  await apiClient.delete(`/user-groups/${id}`)
}

export async function listGroupMembers(groupId: string): Promise<GroupMember[]> {
  const response = await apiClient.get<GroupMember[]>(`/user-groups/${groupId}/members`)
  return response.data
}

export async function addGroupMember(
  groupId: string,
  userId: string,
  joinReason?: string
): Promise<GroupMember> {
  const response = await apiClient.post<GroupMember>(`/user-groups/${groupId}/members`, {
    user_id: userId,
    join_reason: joinReason,
  })
  return response.data
}

export async function removeGroupMember(groupId: string, userId: string): Promise<void> {
  await apiClient.delete(`/user-groups/${groupId}/members/${userId}`)
}

export async function listGroupRoles(groupId: string): Promise<Role[]> {
  const response = await apiClient.get<Role[]>(`/user-groups/${groupId}/roles`)
  return response.data
}

export async function assignGroupRole(groupId: string, roleId: string): Promise<Role> {
  const response = await apiClient.post<Role>(`/user-groups/${groupId}/roles`, { role_id: roleId })
  return response.data
}

export async function removeGroupRole(groupId: string, roleId: string): Promise<void> {
  await apiClient.delete(`/user-groups/${groupId}/roles/${roleId}`)
}

// ── Platform Users ────────────────────────────────────────────────────────────

export async function listPlatformUsers(page = 1, pageSize = 20): Promise<PlatformUser[]> {
  const response = await apiClient.get<PlatformUser[]>('/platform-users', {
    params: { page, page_size: pageSize },
  })
  return response.data
}

export async function getPlatformUser(id: string): Promise<PlatformUserDetail> {
  const response = await apiClient.get<PlatformUserDetail>(`/platform-users/${id}`)
  return response.data
}

export async function assignUserRole(userId: string, roleId: string): Promise<Role> {
  const response = await apiClient.post<Role>(`/platform-users/${userId}/roles`, {
    role_id: roleId,
  })
  return response.data
}

export async function removeUserRole(userId: string, roleId: string): Promise<void> {
  await apiClient.delete(`/platform-users/${userId}/roles/${roleId}`)
}

export async function addUserToGroup(
  userId: string,
  groupId: string,
  joinReason?: string
): Promise<void> {
  await apiClient.post(`/platform-users/${userId}/groups`, {
    group_id: groupId,
    join_reason: joinReason,
  })
}

export async function removeUserFromGroup(userId: string, groupId: string): Promise<void> {
  await apiClient.delete(`/platform-users/${userId}/groups/${groupId}`)
}

// ── Access Requests ───────────────────────────────────────────────────────────

export async function submitAccessRequest(
  groupIds: string[] = [],
  justification: string
): Promise<AccessRequestBatch> {
  const response = await apiClient.post<AccessRequestBatch>('/user-access-requests', {
    group_ids: groupIds,
    justification,
  })
  return response.data
}

export async function listMyAccessRequests(): Promise<AccessRequestBatch[]> {
  const response = await apiClient.get<AccessRequestBatch[]>('/user-access-requests/my')
  return response.data
}

export async function listPendingRequests(): Promise<AccessRequest[]> {
  const response = await apiClient.get<AccessRequest[]>('/user-access-requests/pending')
  return response.data
}

export async function approveAccessRequest(
  requestId: string,
  groupId?: string,
  approvalReason?: string
): Promise<AccessRequest> {
  const response = await apiClient.patch<AccessRequest>(`/user-access-requests/${requestId}/approve`, {
    ...(groupId !== undefined && { group_id: groupId }),
    approval_reason: approvalReason,
  })
  return response.data
}

export async function rejectAccessRequest(
  requestId: string,
  rejectionReason: string
): Promise<AccessRequest> {
  const response = await apiClient.patch<AccessRequest>(`/user-access-requests/${requestId}/reject`, {
    rejection_reason: rejectionReason,
  })
  return response.data
}
