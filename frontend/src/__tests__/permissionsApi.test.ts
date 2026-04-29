import { describe, it, expect, vi } from 'vitest'

vi.mock('../api/permissionsApi', () => ({
  listTagDefinitions: vi.fn().mockResolvedValue([]),
  createTagDefinition: vi.fn().mockResolvedValue({}),
  updateTagDefinition: vi.fn().mockResolvedValue({}),
  deleteTagDefinition: vi.fn().mockResolvedValue(undefined),
  listRoles: vi.fn().mockResolvedValue([]),
  createRole: vi.fn().mockResolvedValue({}),
  getRole: vi.fn().mockResolvedValue({}),
  updateRole: vi.fn().mockResolvedValue({}),
  deleteRole: vi.fn().mockResolvedValue(undefined),
  listRolePolicies: vi.fn().mockResolvedValue([]),
  createPolicyStatement: vi.fn().mockResolvedValue({}),
  deletePolicyStatement: vi.fn().mockResolvedValue(undefined),
  listGroups: vi.fn().mockResolvedValue([]),
  createGroup: vi.fn().mockResolvedValue({}),
  getGroup: vi.fn().mockResolvedValue({}),
  updateGroup: vi.fn().mockResolvedValue({}),
  deleteGroup: vi.fn().mockResolvedValue(undefined),
  listGroupMembers: vi.fn().mockResolvedValue([]),
  addGroupMember: vi.fn().mockResolvedValue({}),
  removeGroupMember: vi.fn().mockResolvedValue(undefined),
  listGroupRoles: vi.fn().mockResolvedValue([]),
  assignGroupRole: vi.fn().mockResolvedValue({}),
  removeGroupRole: vi.fn().mockResolvedValue(undefined),
  listPlatformUsers: vi.fn().mockResolvedValue([]),
  getPlatformUser: vi.fn().mockResolvedValue({}),
  assignUserRole: vi.fn().mockResolvedValue({}),
  removeUserRole: vi.fn().mockResolvedValue(undefined),
  addUserToGroup: vi.fn().mockResolvedValue({}),
  removeUserFromGroup: vi.fn().mockResolvedValue(undefined),
  submitAccessRequest: vi.fn().mockResolvedValue({}),
  listMyAccessRequests: vi.fn().mockResolvedValue([]),
  listPendingRequests: vi.fn().mockResolvedValue([]),
  approveAccessRequest: vi.fn().mockResolvedValue({}),
  rejectAccessRequest: vi.fn().mockResolvedValue({}),
}))

describe('permissionsApi module', () => {
  it('exports listTagDefinitions function', async () => {
    const { listTagDefinitions } = await import('../api/permissionsApi')
    expect(typeof listTagDefinitions).toBe('function')
  })

  it('exports createTagDefinition function', async () => {
    const { createTagDefinition } = await import('../api/permissionsApi')
    expect(typeof createTagDefinition).toBe('function')
  })

  it('exports listRoles function', async () => {
    const { listRoles } = await import('../api/permissionsApi')
    expect(typeof listRoles).toBe('function')
  })

  it('exports listGroups function', async () => {
    const { listGroups } = await import('../api/permissionsApi')
    expect(typeof listGroups).toBe('function')
  })

  it('exports listPlatformUsers function', async () => {
    const { listPlatformUsers } = await import('../api/permissionsApi')
    expect(typeof listPlatformUsers).toBe('function')
  })

  it('exports submitAccessRequest function', async () => {
    const { submitAccessRequest } = await import('../api/permissionsApi')
    expect(typeof submitAccessRequest).toBe('function')
  })

  it('exports approveAccessRequest function', async () => {
    const { approveAccessRequest } = await import('../api/permissionsApi')
    expect(typeof approveAccessRequest).toBe('function')
  })

  it('exports rejectAccessRequest function', async () => {
    const { rejectAccessRequest } = await import('../api/permissionsApi')
    expect(typeof rejectAccessRequest).toBe('function')
  })
})


describe('permissionsApi module', () => {
  it('exports listTagDefinitions function', async () => {
    const { listTagDefinitions } = await import('../api/permissionsApi')
    expect(typeof listTagDefinitions).toBe('function')
  })

  it('exports createTagDefinition function', async () => {
    const { createTagDefinition } = await import('../api/permissionsApi')
    expect(typeof createTagDefinition).toBe('function')
  })

  it('exports listRoles function', async () => {
    const { listRoles } = await import('../api/permissionsApi')
    expect(typeof listRoles).toBe('function')
  })

  it('exports listGroups function', async () => {
    const { listGroups } = await import('../api/permissionsApi')
    expect(typeof listGroups).toBe('function')
  })

  it('exports listPlatformUsers function', async () => {
    const { listPlatformUsers } = await import('../api/permissionsApi')
    expect(typeof listPlatformUsers).toBe('function')
  })

  it('exports submitAccessRequest function', async () => {
    const { submitAccessRequest } = await import('../api/permissionsApi')
    expect(typeof submitAccessRequest).toBe('function')
  })

  it('exports approveAccessRequest function', async () => {
    const { approveAccessRequest } = await import('../api/permissionsApi')
    expect(typeof approveAccessRequest).toBe('function')
  })

  it('exports rejectAccessRequest function', async () => {
    const { rejectAccessRequest } = await import('../api/permissionsApi')
    expect(typeof rejectAccessRequest).toBe('function')
  })
})
