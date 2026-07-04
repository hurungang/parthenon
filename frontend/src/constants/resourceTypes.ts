/**
 * Resource type manifest — mirrors backend/app/core/resource_types.py.
 *
 * Each key is a namespaced resource type identifier (module::submodule)
 * and each value is a readonly array of allowed action strings.
 * Used by policy editor dropdowns and validation.
 */

export const RESOURCE_TYPE_MANIFEST = {
  "agent::roles": { actions: ["read", "manage"] },
  "agent::identities": { actions: ["read", "manage"] },
  "agent::management": { actions: ["create", "read", "update", "delete", "execute"] },
  "agent::runtime_control": { actions: ["read", "execute"] },
  "agent::skills": { actions: ["create", "read", "update", "delete", "execute"] },
  "agent::sops": { actions: ["read", "manage"] },
  "agent::model_configs": { actions: ["read", "manage"] },
  "agent::schedules": { actions: ["create", "read", "update", "delete"] },
  "agent::trails": { actions: ["create", "read", "update", "delete"] },
  "agent::human_intervention": { actions: ["view", "respond"] },
  "agent::data_types": { actions: ["create", "read", "update", "delete", "manage"] },
  "agent::outputs": { actions: ["read"] },
  "integration::mcp_hub": { actions: ["create", "read", "update", "delete", "execute", "manage"] },
  "integration::notifications": { actions: ["read", "manage"] },
  "system::observability": { actions: ["read"] },
  "system::permissions": { actions: ["create", "read", "update", "delete", "manage", "approve", "reject"] },
  "system::system_config": { actions: ["read", "manage"] },
} as const

export type ResourceType = keyof typeof RESOURCE_TYPE_MANIFEST

export interface ResourceTypeEntry {
  readonly actions: readonly string[]
}

export interface ModuleGroup {
  label: string
  submodules: ResourceType[]
}

export const MODULE_GROUPS: Record<string, ModuleGroup> = {
  agents: {
    label: "Agents",
    submodules: [
      "agent::roles",
      "agent::identities",
      "agent::management",
      "agent::runtime_control",
      "agent::skills",
      "agent::sops",
      "agent::model_configs",
      "agent::schedules",
      "agent::trails",
      "agent::human_intervention",
      "agent::data_types",
      "agent::outputs",
    ],
  },
  integrations: {
    label: "Integrations",
    submodules: [
      "integration::mcp_hub",
      "integration::notifications",
    ],
  },
  system: {
    label: "System",
    submodules: [
      "system::observability",
      "system::permissions",
      "system::system_config",
    ],
  },
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

/**
 * Extracts the module prefix from a namespaced resource type.
 * Returns the portion before ``::``, or an empty string if no delimiter present.
 */
export function getModuleForResourceType(resourceType: string): string {
  if (!resourceType.includes("::")) {
    return ""
  }
  return resourceType.split("::", 1)[0]
}
