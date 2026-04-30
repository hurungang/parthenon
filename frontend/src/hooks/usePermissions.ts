/**
 * React Query hooks for the Permission Management module.
 * Replaces a Zustand store — provides typed, cached data access for all
 * permission entities with loading/error state managed by TanStack Query.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../api/permissionsApi'
import type {
  TagDefinitionCreate,
  TagDefinitionUpdate,
  RoleCloneCreate,
  RoleCreate,
  RoleUpdate,
  PolicyStatementCreate,
  GroupCreate,
  GroupUpdate,
} from '../types/permissions'

// ── Query Keys ─────────────────────────────────────────────────────────────────

export const permissionKeys = {
  tags: ['permissions', 'tags'] as const,
  roles: ['permissions', 'roles'] as const,
  role: (id: string) => ['permissions', 'roles', id] as const,
  groups: ['permissions', 'groups'] as const,
  platformUsers: ['permissions', 'platform-users'] as const,
  platformUser: (id: string) => ['permissions', 'platform-users', id] as const,
  accessRequestsMy: ['permissions', 'access-requests', 'my'] as const,
  accessRequestsPending: ['permissions', 'access-requests', 'pending'] as const,
  resourceTypes: ['permissions', 'resource-types'] as const,
}

// ── Tags ───────────────────────────────────────────────────────────────────────

export function useTagDefinitions(filters?: { scope?: string; resource_type?: string }) {
  return useQuery({
    queryKey: permissionKeys.tags,
    queryFn: () => api.listTagDefinitions(filters),
  })
}

export function useCreateTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TagDefinitionCreate) => api.createTagDefinition(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.tags }),
  })
}

export function useUpdateTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: TagDefinitionUpdate }) =>
      api.updateTagDefinition(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.tags }),
  })
}

export function useDeleteTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteTagDefinition(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.tags }),
  })
}

// ── Roles ──────────────────────────────────────────────────────────────────────

export function useRoles(page = 1, pageSize = 50) {
  return useQuery({
    queryKey: permissionKeys.roles,
    queryFn: () => api.listRoles(page, pageSize),
  })
}

export function useRole(id: string) {
  return useQuery({
    queryKey: permissionKeys.role(id),
    queryFn: () => api.getRole(id),
    enabled: !!id,
  })
}

export function useCreateRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: RoleCreate) => api.createRole(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.roles }),
  })
}

export function useUpdateRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: RoleUpdate }) => api.updateRole(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.roles }),
  })
}

export function useDeleteRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, force }: { id: string; force?: boolean }) => api.deleteRole(id, force),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.roles }),
  })
}

export function useCreatePolicyStatement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ roleId, data }: { roleId: string; data: PolicyStatementCreate }) =>
      api.createPolicyStatement(roleId, data),
    onSuccess: (_data, { roleId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.role(roleId) })
    },
  })
}

export function useDeletePolicyStatement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ roleId, policyId }: { roleId: string; policyId: string }) =>
      api.deletePolicyStatement(roleId, policyId),
    onSuccess: (_data, { roleId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.role(roleId) })
    },
  })
}

export function useUpdatePolicyStatement() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      roleId,
      policyId,
      data,
    }: {
      roleId: string
      policyId: string
      data: PolicyStatementCreate
    }) => api.updatePolicyStatement(roleId, policyId, data),
    onSuccess: (_data, { roleId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.role(roleId) })
    },
  })
}

export function useResourceTypes() {
  return useQuery({
    queryKey: permissionKeys.resourceTypes,
    queryFn: () => api.listResourceTypes(),
    staleTime: Infinity,
  })
}

export function useCloneRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sourceId, data }: { sourceId: string; data: RoleCloneCreate }) =>
      api.cloneRole(sourceId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permissionKeys.roles })
    },
  })
}

// ── Groups ─────────────────────────────────────────────────────────────────────

export function useGroups(page = 1, pageSize = 50) {
  return useQuery({
    queryKey: permissionKeys.groups,
    queryFn: () => api.listGroups(page, pageSize),
  })
}

export function useCreateGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: GroupCreate) => api.createGroup(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.groups }),
  })
}

export function useUpdateGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: GroupUpdate }) => api.updateGroup(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.groups }),
  })
}

export function useDeleteGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteGroup(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: permissionKeys.groups }),
  })
}

export function useGroupMembers(groupId: string | null) {
  return useQuery({
    queryKey: ['permissions', 'groups', groupId, 'members'],
    queryFn: () => api.listGroupMembers(groupId!),
    enabled: !!groupId,
  })
}

export function useGroupRoles(groupId: string | null) {
  return useQuery({
    queryKey: ['group-roles', groupId],
    queryFn: () => api.listGroupRoles(groupId!),
    enabled: !!groupId,
  })
}

export function useAssignGroupRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId, roleId }: { groupId: string; roleId: string }) =>
      api.assignGroupRole(groupId, roleId),
    onSuccess: (_data, { groupId }) => {
      qc.invalidateQueries({ queryKey: ['group-roles', groupId] })
    },
  })
}

export function useRemoveGroupRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupId, roleId }: { groupId: string; roleId: string }) =>
      api.removeGroupRole(groupId, roleId),
    onSuccess: (_data, { groupId }) => {
      qc.invalidateQueries({ queryKey: ['group-roles', groupId] })
    },
  })
}

// ── Platform Users ─────────────────────────────────────────────────────────────

export function usePlatformUsers(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: permissionKeys.platformUsers,
    queryFn: () => api.listPlatformUsers(page, pageSize),
  })
}

export function usePlatformUser(id: string) {
  return useQuery({
    queryKey: permissionKeys.platformUser(id),
    queryFn: () => api.getPlatformUser(id),
    enabled: !!id,
  })
}

export function useAssignUserRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      api.assignUserRole(userId, roleId),
    onSuccess: (_data, { userId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.platformUser(userId) })
    },
  })
}

export function useRemoveUserRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      api.removeUserRole(userId, roleId),
    onSuccess: (_data, { userId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.platformUser(userId) })
    },
  })
}

export function useAddUserToGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      userId,
      groupId,
      joinReason,
    }: {
      userId: string
      groupId: string
      joinReason?: string
    }) => api.addUserToGroup(userId, groupId, joinReason),
    onSuccess: (_data, { userId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.platformUser(userId) })
    },
  })
}

export function useRemoveUserFromGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, groupId }: { userId: string; groupId: string }) =>
      api.removeUserFromGroup(userId, groupId),
    onSuccess: (_data, { userId }) => {
      qc.invalidateQueries({ queryKey: permissionKeys.platformUser(userId) })
    },
  })
}

// ── Access Requests ────────────────────────────────────────────────────────────

export function useMyAccessRequests() {
  return useQuery({
    queryKey: permissionKeys.accessRequestsMy,
    queryFn: () => api.listMyAccessRequests(),
  })
}

export function usePendingAccessRequests() {
  return useQuery({
    queryKey: permissionKeys.accessRequestsPending,
    queryFn: () => api.listPendingRequests(),
  })
}

export function useSubmitAccessRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ groupIds, justification }: { groupIds?: string[]; justification: string }) =>
      api.submitAccessRequest(groupIds ?? [], justification),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permissionKeys.accessRequestsMy })
    },
  })
}

export function useApproveAccessRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, groupId, reason }: { requestId: string; groupId?: string; reason?: string }) =>
      api.approveAccessRequest(requestId, groupId, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permissionKeys.accessRequestsPending })
    },
  })
}

export function useRejectAccessRequest() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason: string }) =>
      api.rejectAccessRequest(requestId, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: permissionKeys.accessRequestsPending })
    },
  })
}
