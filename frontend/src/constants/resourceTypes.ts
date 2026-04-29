/**
 * Resource type manifest — mirrors backend/app/core/resource_types.py.
 *
 * Each key is a resource type identifier and each value is a readonly
 * array of allowed action strings.  Used by RolePolicyDialog dropdowns
 * and any validation that needs to enumerate valid resource types or actions.
 */

export const RESOURCE_TYPES = {
  agent: 'agent',
  mcp_server: 'mcp_server',
  conversation: 'conversation',
  group: 'group',
  user: 'user',
  tag: 'tag',
  role: 'role',
  access_request: 'access_request',
  permissions: 'permissions',
  skill: 'skill',
  scheduling: 'scheduling',
  notification: 'notification',
} as const

export type ResourceType = (typeof RESOURCE_TYPES)[keyof typeof RESOURCE_TYPES]

export interface ResourceTypeEntry {
  readonly actions: readonly string[]
}

export const RESOURCE_TYPE_MANIFEST: Record<ResourceType, ResourceTypeEntry> = {
  agent: { actions: ['create', 'read', 'update', 'delete', 'execute'] },
  mcp_server: { actions: ['create', 'read', 'update', 'delete', 'execute'] },
  conversation: { actions: ['create', 'read', 'update', 'delete'] },
  group: { actions: ['create', 'read', 'update', 'delete', 'manage'] },
  user: { actions: ['create', 'read', 'update', 'delete', 'manage'] },
  tag: { actions: ['read', 'manage'] },
  role: { actions: ['read', 'manage'] },
  access_request: { actions: ['create', 'read', 'approve', 'reject'] },
  permissions: { actions: ['read', 'manage'] },
  skill: { actions: ['create', 'read', 'update', 'delete', 'execute'] },
  scheduling: { actions: ['create', 'read', 'update', 'delete'] },
  notification: { actions: ['read', 'manage'] },
}

/** Sorted list of all resource type identifiers for use in dropdowns. */
export const RESOURCE_TYPE_OPTIONS: ResourceType[] = Object.keys(
  RESOURCE_TYPE_MANIFEST,
) as ResourceType[]

/**
 * Returns the allowed actions for a given resource type,
 * or an empty array if the type is not in the manifest.
 */
export function getActionsForResourceType(resourceType: string): readonly string[] {
  return (RESOURCE_TYPE_MANIFEST as Record<string, ResourceTypeEntry>)[resourceType]?.actions ?? []
}
